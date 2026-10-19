"""Thresholds → context judge → private, rate-limited outreach."""

import asyncio
import hashlib
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.contracts import MetadataEvent
from app.db import Event, Member, SignalRow, aware, utcnow
from app.outreach.channel import deliver
from app.outreach.messages import nudge_buttons, nudge_text, reminder_text
from app.triggers.judge import judge_signal
from app.triggers.rules import BANGKOK, detect


def load_events(session, team_id):
    return [
        MetadataEvent(
            type=e.type,
            actor_hash=e.actor_hash,
            target_hash=e.target_hash,
            timestamp=aware(e.timestamp),
            status=e.status,
            ref=e.ref,
            meta=e.meta,
        )
        for e in session.scalars(select(Event).where(Event.team_id == team_id))
    ]


def signal_view(row, members):
    names = {m.actor_hash: m.display_name for m in members}
    return {
        "id": row.id,
        "kind": row.kind,
        "ref": row.ref,
        "affected_display": names.get(row.affected_hash, "ทีม"),
        "target_display": names.get(row.target_hash),
        "detected_at": row.detected_at.isoformat(),
        "judge_ok": row.judge_ok,
        "judge_reason": row.judge_reason,
        "state": row.state,
    }


def reserve_nudge(redis, member, now):
    if not member.opted_in:
        return False
    local = now.astimezone(BANGKOK)
    monday = (local - timedelta(days=local.weekday())).date().isoformat()
    key = f"kjb:nudges:{member.actor_hash}:{monday}"
    # Atomic limit reservation, including target reminders.
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, 8 * 86400)
    return count <= get_settings().nudge_weekly_limit


async def run_engine(session, redis, team_id, *, now=None, kinds=None):
    now = aware(now or utcnow())
    members = list(session.scalars(select(Member).where(Member.team_id == team_id)))
    member_map = {m.actor_hash: m for m in members}
    events = load_events(session, team_id)
    rows, outreach = [], []
    fresh = []
    for signal in detect(events, members, now=now):
        if kinds is not None and signal.kind not in kinds:
            continue
        period = (
            now.strftime("%G-%V")
            if signal.kind in ("friday_urgent", "late_night", "review_concentration")
            else ""
        )
        key = hashlib.sha256(
            f"{team_id}:{signal.kind}:{signal.ref}:{signal.affected_hash}:{period}".encode()
        ).hexdigest()
        if not session.scalar(select(SignalRow).where(SignalRow.dedup_key == key)):
            fresh.append((key, signal))
    # Judge in parallel and before any write, so no DB lock is held while the LLM thinks.
    judged = await asyncio.gather(*(judge_signal(signal, events) for _, signal in fresh))
    for (key, _), signal in zip(fresh, judged, strict=True):
        row = SignalRow(team_id=team_id, dedup_key=key, **signal.model_dump())
        row.state = "pending" if signal.judge_ok else "suppressed"
        session.add(row)
        session.flush()
        rows.append(row)
        if not signal.judge_ok or signal.kind == "review_concentration":
            continue
        member = member_map.get(signal.affected_hash)
        if member and signal.kind not in member.muted_kinds and reserve_nudge(redis, member, now):
            outreach.append(
                await deliver(
                    session,
                    member,
                    nudge_text(signal),
                    kind=signal.kind,
                    buttons=nudge_buttons(row.id, signal.kind),
                    signal_id=row.id,
                )
            )
    session.flush()
    return rows, outreach


async def respond(session, redis, outreach, action):
    member = session.get(Member, outreach.member_id)
    if action not in {b["action"] for b in outreach.buttons}:
        raise HTTPException(400, "Unknown action")
    if outreach.response:
        if outreach.response != action:
            raise HTTPException(409, "Already answered")
        return outreach
    if action.startswith("mute:"):
        kind = action.split(":", 1)[1]
        member.muted_kinds = list({*member.muted_kinds, kind})
    elif action.startswith("nudge:"):
        _, response, signal_id = action.split(":", 2)
        signal = session.get(SignalRow, signal_id)
        if signal is None or signal_id != outreach.signal_id:
            raise HTTPException(400, "Invalid signal")
        signal.state = {"accept": "accepted", "decline": "declined", "useless": "useless"}[response]
        # A self-only signal must never result in outreach to anyone else.
        if response == "accept" and signal.kind != "late_night" and signal.target_hash:
            target = session.scalar(select(Member).where(Member.actor_hash == signal.target_hash))
            if (
                target
                and signal.kind not in target.muted_kinds
                and reserve_nudge(redis, target, utcnow())
            ):
                await deliver(
                    session,
                    target,
                    reminder_text(signal),
                    kind="reminder",
                    buttons=nudge_buttons(signal.id, signal.kind)[2:],
                    signal_id=signal.id,
                )
    outreach.response = action
    session.flush()
    return outreach
