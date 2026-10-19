"""Deterministic demo team and metadata scenarios relative to the current clock."""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.contracts import MetadataEvent
from app.db import Base, Event, Member, SignalRow, Team, Theme, actor_hash, aware, utcnow
from app.triggers.engine import run_engine
from app.triggers.rules import BANGKOK

TEAM_ID = "team-backend-demo"


def demo_now(redis):
    value = redis.get("kjb:demo-clock")
    return aware(datetime.fromisoformat(value)) if value else utcnow()


def ingest(session, team_id, event: MetadataEvent):
    # MetadataEvent has no content fields; only allow known SDLC metadata keys.
    allowed = {"labels", "until", "end", "days", "author_seniority", "reviewer_seniority", "policy"}
    values = event.model_dump()
    values["timestamp"] = aware(event.timestamp)
    values["meta"] = {k: v for k, v in event.meta.items() if k in allowed}
    session.add(Event(team_id=team_id, **values))


def seed_demo(session, *, now=None):
    if session.scalar(select(Team).limit(1)):
        return
    from app.privacy.pipeline import demo_roster
    now = aware(now or utcnow())
    session.add(Team(id=TEAM_ID, name="ทีม Backend (Demo)"))
    session.flush()
    for person in demo_roster():
        session.add(Member(id=person.member_id, team_id=TEAM_ID, display_name=person.display_name,
                           role=person.role, gender=person.gender, seniority=person.seniority,
                           actor_hash=actor_hash(person.member_id)))
    session.flush()
    # Historical workload: three urgent tasks in the older half of the 4-week window.
    # They age out at follow-up only if no new after-hours tasks are observed.
    friday = now.astimezone(BANGKOK).replace(hour=18, minute=0, second=0, microsecond=0)
    friday -= timedelta(days=(friday.weekday() - 4) % 7)
    if friday > now:
        friday -= timedelta(weeks=1)
    for index in range(3):
        when = friday - timedelta(weeks=2, minutes=index * 10)
        ingest(session, TEAM_ID, MetadataEvent(type="task_assigned", actor_hash=actor_hash("m-wan"),
               target_hash=actor_hash("m-mint"), timestamp=when, ref=f"HIST-URGENT-{index}"))
    for week in range(8):
        when = now - timedelta(weeks=week, days=1)
        for index, reviewer in enumerate(("m-somchai", "m-wan", "m-boat", "m-ton")):
            ref = f"HIST-PR-{week}-{index}"
            ingest(session, TEAM_ID, MetadataEvent(type="pr_review_requested", actor_hash=actor_hash("m-mint"),
                   target_hash=actor_hash(reviewer), timestamp=when - timedelta(hours=16 + week * 3), ref=ref))
            ingest(session, TEAM_ID, MetadataEvent(type="pr_reviewed", actor_hash=actor_hash(reviewer), timestamp=when, ref=ref))
    session.commit()


def reset_demo(session, redis):
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(delete(table))
    session.commit()
    # Do not flush a shared cloud Redis database; delete only this app's namespaces.
    for prefix in ("kjb:*", "privacy:gate:*"):
        keys = list(redis.scan_iter(match=prefix))
        if keys:
            redis.delete(*keys)
    seed_demo(session)


async def scenario(session, redis, name):
    now = demo_now(redis)
    mint, somchai = actor_hash("m-mint"), actor_hash("m-somchai")
    events = []
    if name == "pr_stale":
        events = [MetadataEvent(type="pr_review_requested", actor_hash=mint, target_hash=somchai,
                               timestamp=now - timedelta(hours=60), ref="PR #123")]
    elif name == "ticket_blocked":
        events = [MetadataEvent(type="ticket_status", actor_hash=mint, target_hash=somchai,
                               timestamp=now - timedelta(days=3), status="Blocked", ref="TICKET-42")]
    elif name == "friday_urgent":
        # Seed history already contains the three threshold events.
        pass
    elif name == "late_night":
        today = now.astimezone(BANGKOK).replace(hour=23, minute=15, second=0, microsecond=0)
        events = [MetadataEvent(type="commit", actor_hash=mint, timestamp=today - timedelta(days=d),
                                ref=f"PRIVATE-COMMIT-{d}") for d in range(1, 5)]
    elif name == "sprint_end":
        events = [MetadataEvent(type="sprint_ended", actor_hash=mint, timestamp=now, ref="Sprint 14")]
    else:
        raise HTTPException(404, "Unknown scenario")
    for event in events:
        exists = session.scalar(select(Event).where(Event.team_id == TEAM_ID, Event.type == event.type, Event.ref == event.ref))
        if not exists:
            ingest(session, TEAM_ID, event)
    session.flush()
    return await run_engine(session, redis, TEAM_ID, now=now)


async def advance(session, redis, weeks):
    from app.manager.loop import follow_up, release_themes, theme_view
    start = demo_now(redis)
    end = start + timedelta(weeks=weeks)
    themes = list(session.scalars(select(Theme).where(Theme.team_id == TEAM_ID)))
    friday_policy = any(t.slug == "friday-urgent-work" and t.accepted_proposal for t in themes)
    pr_policy = any(t.slug == "pr-review-delay" and t.accepted_proposal for t in themes)
    # A neutral nudge that was accepted gets the stale PR reviewed soon after the reminder,
    # and the team keeps a shorter review habit afterwards.
    nudged = list(session.scalars(select(SignalRow).where(
        SignalRow.team_id == TEAM_ID, SignalRow.kind == "pr_stale", SignalRow.state == "accepted")))
    for signal in nudged:
        if not session.scalar(select(Event).where(Event.team_id == TEAM_ID, Event.type == "pr_reviewed", Event.ref == signal.ref)):
            ingest(session, TEAM_ID, MetadataEvent(type="pr_reviewed", actor_hash=signal.target_hash or actor_hash("m-somchai"),
                   timestamp=start + timedelta(hours=3), ref=signal.ref))
    pr_policy = pr_policy or bool(nudged)
    # Simulate the intervening working weeks. Improvements come from these events,
    # never from overwriting a metric or deleting the old workload.
    for week in range(weeks):
        local = (start + timedelta(weeks=week)).astimezone(BANGKOK)
        friday = local.replace(hour=14 if friday_policy else 18, minute=0, second=0, microsecond=0)
        friday += timedelta(days=(4 - friday.weekday()) % 7)
        if friday <= start:
            friday += timedelta(weeks=1)
        if friday <= end:
            ingest(session, TEAM_ID, MetadataEvent(type="task_assigned", actor_hash=actor_hash("m-wan"),
                   target_hash=actor_hash("m-mint"), timestamp=friday, ref=f"FUTURE-TASK-{friday.isoformat()}"))
        opened = start + timedelta(weeks=week, hours=1)
        ref = f"FUTURE-PR-{opened.isoformat()}"
        ingest(session, TEAM_ID, MetadataEvent(type="pr_review_requested", actor_hash=actor_hash("m-mint"),
               target_hash=actor_hash("m-somchai"), timestamp=opened, ref=ref))
        reviewed = opened + timedelta(hours=12 if pr_policy else 30)
        if reviewed <= end:
            ingest(session, TEAM_ID, MetadataEvent(type="pr_reviewed", actor_hash=actor_hash("m-somchai"), timestamp=reviewed, ref=ref))
    session.flush()
    redis.set("kjb:demo-clock", end.isoformat())
    await release_themes(session, redis, TEAM_ID, now=end)
    follow_up(session, redis, TEAM_ID, now=end)
    return [theme_view(session, redis, theme) for theme in themes if theme.released_at is not None]
