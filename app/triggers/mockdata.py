"""D3: reproducible 12-week SDLC history and labelled friction episodes."""
import random
from datetime import UTC, datetime, timedelta

from app.contracts import MemberProfile, MetadataEvent
from app.db import actor_hash, aware
from app.triggers.judge import context_check
from app.triggers.rules import BANGKOK, detect


def generate_history(seed=42, *, now=None):
    rng = random.Random(seed)
    now = aware(now or datetime(2026, 10, 19, 5, tzinfo=UTC))
    monday = now.astimezone(BANGKOK).replace(hour=9, minute=0, second=0, microsecond=0)
    monday -= timedelta(days=monday.weekday(), weeks=12)
    people = [("m-mint", "junior"), ("m-somchai", "senior"), ("m-wan", "lead"),
              ("m-boat", "mid"), ("m-fon", "junior"), ("m-ton", "mid")]
    profiles = [MemberProfile(member_id=mid, display_name=mid, seniority=rank) for mid, rank in people]
    from types import SimpleNamespace
    roster = [SimpleNamespace(actor_hash=actor_hash(mid), seniority=rank) for mid, rank in people]
    events, truth, decoys = [], [], []

    def event(kind, who, when, ref, *, target=None, status="", **meta):
        e = MetadataEvent(type=kind, actor_hash=actor_hash(who), target_hash=actor_hash(target) if target else None,
                          timestamp=when, ref=ref, status=status, meta=meta)
        events.append(e)
        return e

    def friction(kind, who, ref, when):
        truth.append({"kind": kind, "affected_hash": actor_hash(who) if who != "team" else "team",
                      "ref": ref, "detectable_at": when.isoformat()})

    for week in range(12):
        start = monday + timedelta(weeks=week)
        # Review distribution is balanced; timestamps are tied to avoid startup artefacts.
        for person in ("m-somchai", "m-wan", "m-boat", "m-ton"):
            event("pr_reviewed", person, start, f"BASE-{week}-{person}")
        for day in range(5):
            event("commit", rng.choice(people)[0], start + timedelta(days=day, hours=6), f"COMMIT-{week}-{day}")
            event("task_assigned", "m-wan", start + timedelta(days=day, hours=2), f"TASK-{week}-{day}", target="m-mint")
        ref = f"PR #{100 + week}"
        opened = start + timedelta(hours=1)
        event("pr_review_requested", "m-mint", opened, ref, target="m-somchai")
        delayed = week in (1, 4, 7, 10)
        reviewed = opened + timedelta(hours=80 if delayed else rng.randint(5, 30))
        event("pr_reviewed", "m-somchai", reviewed, ref)
        event("pr_merged", "m-mint", reviewed + timedelta(hours=1), ref)
        if delayed:
            friction("pr_stale", "m-mint", ref, opened + timedelta(hours=48, seconds=1))
        if week in (2, 5, 8):
            ref = f"TICKET-{week}"
            event("ticket_status", "m-boat", start, ref, status="Blocked")
            event("ticket_status", "m-boat", start + timedelta(days=5), ref, status="Done")
            friction("ticket_blocked", "m-boat", ref, start + timedelta(days=2, seconds=1))
        event("sprint_ended", "m-mint", start + timedelta(days=11), f"Sprint {week // 2}") if week % 2 == 0 else None
        if week % 2 == 0:
            friction("sprint_end", "m-mint", f"Sprint {week // 2}", start + timedelta(days=11))
        # Negative cases exceed the timer but must be rejected by the context judge.
        ref = f"WIP-{week}"
        event("pr_review_requested", "m-mint", start, ref, target="m-somchai", labels=["WIP"])
        event("pr_reviewed", "m-somchai", start + timedelta(days=4), ref)
        decoys.append(ref)
        ref = f"LEAVE-{week}"
        leave_start = start + timedelta(days=4)
        event("pr_review_requested", "m-fon", leave_start, ref, target="m-wan")
        event("leave", "m-wan", leave_start, f"Leave-{week}", until=(leave_start + timedelta(days=4)).isoformat())
        event("pr_reviewed", "m-wan", leave_start + timedelta(days=4), ref)
        decoys.append(ref)
    for week in (9, 10, 11):
        when = monday + timedelta(weeks=week, days=4, hours=9)
        event("task_assigned", "m-wan", when, f"URGENT-{week}", target="m-mint")
        if week == 11:
            friction("friday_urgent", "m-mint", "Friday assignments", when)
    for day in range(4):
        when = monday + timedelta(weeks=8, days=day, hours=14)
        event("commit", "m-ton", when, f"LATE-{day}")
        if day == 3:
            friction("late_night", "m-ton", "Private wellbeing", when)
    for index in range(3):
        when = monday + timedelta(weeks=6, hours=index)
        event("ticket_reopened", "m-fon", when, "REOPEN-3")
        if index == 2:
            friction("ticket_blocked", "m-fon", "REOPEN-3", when)
    event("ticket_status", "m-fon", monday + timedelta(weeks=6, days=1), "REOPEN-3", status="Done")
    # A genuine team-level review bottleneck late in the history.
    when = monday + timedelta(weeks=11, days=2)
    for index in range(40):
        event("pr_reviewed", "m-somchai", when, f"CONCENTRATED-{index}")
    friction("review_concentration", "team", "Team review distribution", when)
    return {"events": sorted(events, key=lambda e: aware(e.timestamp)), "ground_truth": truth,
            "decoys": decoys, "roster": roster, "profiles": profiles, "end": now}


generate_mock_data = generate_history


def evaluate_engine(seed=42):
    """Replay every six hours; score unique episodes after deterministic context checks.

    No LLM or network calls are made; truth is injected independently of the rules.
    Repeated observations of the same episode count once, including false alerts.
    """
    from statistics import median
    data = generate_history(seed)
    first_seen = {}
    cursor = aware(data["events"][0].timestamp)
    while cursor <= data["end"]:
        observed = [e for e in data["events"] if aware(e.timestamp) <= cursor]
        for signal in detect(observed, data["roster"], now=cursor):
            if context_check(signal, observed)[0]:
                first_seen.setdefault((signal.kind, signal.affected_hash, signal.ref), cursor)
        cursor += timedelta(hours=6)
    expected = {(g["kind"], g["affected_hash"], g["ref"]): datetime.fromisoformat(g["detectable_at"])
                for g in data["ground_truth"]}
    matched = set(first_seen) & set(expected)
    delays = [max(0, (first_seen[key] - aware(expected[key])).total_seconds() / 60) for key in matched]
    return {"recall": len(matched) / len(expected) if expected else 1.0,
            "precision": len(matched) / len(first_seen) if first_seen else 1.0,
            "median_detection_delay_minutes": median(delays) if delays else 0.0}
