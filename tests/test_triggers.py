import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.contracts import MetadataEvent
from app.triggers.judge import context_check, judge_signal
from app.triggers.mockdata import evaluate_engine, generate_history
from app.triggers.rules import BANGKOK, detect

NOW = datetime(2026, 10, 19, 6, tzinfo=UTC)
ROSTER = [
    SimpleNamespace(actor_hash="junior", seniority="junior"),
    SimpleNamespace(actor_hash="senior", seniority="senior"),
]


def event(kind, days=0, **kwargs):
    return MetadataEvent(
        type=kind,
        actor_hash=kwargs.pop("actor_hash", "junior"),
        timestamp=kwargs.pop("timestamp", NOW - timedelta(days=days)),
        ref=kwargs.pop("ref", "REF"),
        **kwargs,
    )


def test_pr_boundary_seniority_and_completed_work():
    request = event("pr_review_requested", days=2, target_hash="senior")
    assert detect([request], ROSTER, now=NOW) == []
    request = request.model_copy(update={"timestamp": NOW - timedelta(hours=49)})
    assert detect([request], ROSTER, now=NOW)[0].kind == "pr_stale"
    equal = [SimpleNamespace(actor_hash="junior", seniority="senior"), ROSTER[1]]
    assert detect([request], equal, now=NOW) == []
    completed = event("pr_merged")
    assert detect([request, completed], ROSTER, now=NOW) == []


def test_judge_rejects_wip_and_leave_without_llm(backend_settings):
    request = event("pr_review_requested", days=3, target_hash="senior", meta={"labels": ["WIP"]})
    signal = detect([request], ROSTER, now=NOW)[0]
    assert not asyncio.run(judge_signal(signal, [request])).judge_ok
    request.meta = {}
    leave = event(
        "leave", days=4, actor_hash="senior", meta={"until": (NOW + timedelta(days=1)).isoformat()}
    )
    signal = detect([request, leave], ROSTER, now=NOW)[0]
    assert not context_check(signal, [request, leave])[0]
    leave.meta["until"] = (NOW - timedelta(days=1)).isoformat()
    assert context_check(signal, [request, leave])[0]


def test_blocked_and_reopened_thresholds():
    blocked = event("ticket_status", days=2, status="Blocked")
    assert detect([blocked], now=NOW) == []
    blocked.timestamp -= timedelta(seconds=1)
    assert detect([blocked], now=NOW)[0].kind == "ticket_blocked"
    assert detect([blocked, event("ticket_status", status="Done")], now=NOW) == []
    reopened = [event("ticket_reopened", days=i) for i in range(3)]
    assert len(detect(reopened, now=NOW)) == 1
    assert detect(reopened[:2], now=NOW) == []
    assert detect([*reopened, event("ticket_status", status="Closed")], now=NOW) == []


def test_bangkok_friday_window_and_late_night_distinct_days():
    friday = datetime(2026, 10, 16, 18, tzinfo=BANGKOK)
    urgent = [
        event("task_assigned", timestamp=friday - timedelta(weeks=i), target_hash="junior")
        for i in range(3)
    ]
    assert detect(urgent, now=NOW)[0].kind == "friday_urgent"
    assert detect(urgent[:2], now=NOW) == []
    assert (
        detect(
            [e.model_copy(update={"timestamp": e.timestamp - timedelta(hours=2)}) for e in urgent],
            now=NOW,
        )
        == []
    )
    late = [
        event("commit", timestamp=(NOW - timedelta(days=d)).astimezone(BANGKOK).replace(hour=23))
        for d in range(1, 5)
    ]
    signals = detect(late, now=NOW)
    assert len(signals) == 1 and signals[0].evidence["self_only"] is True
    assert detect([late[0]] * 8, now=NOW) == []


def test_review_concentration_is_team_only_and_sprint_checkin():
    reviews = [event("pr_reviewed", actor_hash="senior"), event("pr_reviewed", actor_hash="other")]
    assert detect(reviews, now=NOW) == []
    reviews.append(event("pr_reviewed", actor_hash="senior"))
    signal = detect(reviews, now=NOW)[0]
    assert signal.kind == "review_concentration" and signal.affected_hash == "team"
    assert signal.evidence["team_only"]
    assert detect([event("sprint_ended")], now=NOW)[0].kind == "sprint_end"


def test_d3_deterministic_12_week_history_and_offline_eval():
    first = generate_history(42)
    second = generate_history(42)
    assert first["events"] == second["events"]
    assert len(first["events"]) > 250 and len(first["decoys"]) >= 12
    assert (first["end"] - first["events"][0].timestamp).days >= 80
    assert {g["kind"] for g in first["ground_truth"]} == {
        "pr_stale",
        "ticket_blocked",
        "friday_urgent",
        "late_night",
        "review_concentration",
        "sprint_end",
    }
    metrics = evaluate_engine(42)
    assert metrics["recall"] >= 0.9 and metrics["precision"] >= 0.8
    assert metrics["median_detection_delay_minutes"] >= 0
