"""Deterministic thresholds over SDLC metadata, never message content."""

from collections import Counter, defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from app.contracts import MetadataEvent, Signal
from app.db import aware, utcnow

BANGKOK = ZoneInfo("Asia/Bangkok")
RANK = {"junior": 0, "mid": 1, "senior": 2, "lead": 3}


def detect(events: list[MetadataEvent], roster=(), *, now=None) -> list[Signal]:
    now = aware(now or utcnow())
    events = sorted(
        (e for e in events if aware(e.timestamp) <= now), key=lambda e: aware(e.timestamp)
    )
    ranks = {getattr(m, "actor_hash", ""): RANK.get(m.seniority, 1) for m in roster}
    signals = []

    def emit(kind, event, evidence=None, target=None):
        signals.append(
            Signal(
                kind=kind,
                affected_hash=event.actor_hash,
                target_hash=target,
                ref=event.ref,
                detected_at=now,
                evidence=evidence or {},
            )
        )

    by_ref = defaultdict(list)
    for event in events:
        by_ref[event.ref].append(event)
    for ref_events in by_ref.values():
        prs = [e for e in ref_events if e.type in ("pr_opened", "pr_review_requested")]
        if prs:
            request = prs[-1]
            age = (now - aware(request.timestamp)).total_seconds() / 3600
            done = any(
                e.type in ("pr_reviewed", "pr_merged")
                and aware(e.timestamp) >= aware(request.timestamp)
                for e in ref_events
            )
            senior = ranks.get(
                request.target_hash, RANK.get(request.meta.get("reviewer_seniority"), 2)
            )
            junior = ranks.get(
                request.actor_hash, RANK.get(request.meta.get("author_seniority"), 0)
            )
            if age > 48 and not done and request.target_hash and senior > junior:
                labels = list(request.meta.get("labels", []))
                for e in ref_events:
                    if e.type == "pr_labeled":
                        labels = e.meta.get("labels", [e.status])
                emit(
                    "pr_stale",
                    request,
                    {"wait_hours": round(age, 1), "labels": labels},
                    request.target_hash,
                )
        statuses = [e for e in ref_events if e.type == "ticket_status"]
        reopens = [e for e in ref_events if e.type == "ticket_reopened"]
        if statuses and statuses[-1].status.lower() == "blocked":
            blocked = statuses[-1]
            # Repeated status snapshots must not reset the start of a blocked interval.
            for e in reversed(statuses[:-1]):
                if e.status.lower() != "blocked":
                    break
                blocked = e
            age = (now - aware(blocked.timestamp)).total_seconds() / 86400
            if age > 2:
                emit("ticket_blocked", blocked, {"blocked_days": round(age, 2)})
                continue
        if len(reopens) >= 3 and (
            not statuses or statuses[-1].status.lower() not in ("done", "closed", "resolved")
        ):
            emit("ticket_blocked", reopens[-1], {"reopened": len(reopens)})

    friday = defaultdict(list)
    late = defaultdict(set)
    reviews = []
    for e in events:
        age = now - aware(e.timestamp)
        local = aware(e.timestamp).astimezone(BANGKOK)
        if (
            e.type == "task_assigned"
            and age <= timedelta(weeks=4)
            and local.weekday() == 4
            and local.hour >= 17
        ):
            friday[e.target_hash or e.actor_hash].append(e)
        if e.type == "commit" and age <= timedelta(days=7) and local.hour >= 22:
            late[e.actor_hash].add(local.date())
        if e.type == "pr_reviewed" and age <= timedelta(weeks=4):
            reviews.append(e)
        if e.type == "sprint_ended" and age <= timedelta(days=7):
            emit("sprint_end", e)
    for person, items in friday.items():
        if len(items) >= 3:
            signal = Signal(
                kind="friday_urgent",
                affected_hash=person,
                ref="Friday assignments",
                detected_at=now,
                evidence={"count_4w": len(items)},
            )
            signals.append(signal)
    for person, days in late.items():
        if len(days) >= 4:
            signals.append(
                Signal(
                    kind="late_night",
                    affected_hash=person,
                    ref="Private wellbeing",
                    detected_at=now,
                    evidence={"days_7d": len(days), "self_only": True},
                )
            )
    if reviews:
        _actor, count = Counter(e.actor_hash for e in reviews).most_common(1)[0]
        if count / len(reviews) > 0.5:
            signals.append(
                Signal(
                    kind="review_concentration",
                    affected_hash="team",
                    ref="Team review distribution",
                    detected_at=now,
                    evidence={"top_share": round(count / len(reviews), 3), "team_only": True},
                )
            )
    return signals


# Public name used by the evaluation runner.
evaluate_rules = detect
