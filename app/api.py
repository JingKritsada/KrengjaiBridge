"""HTTP contract shared by the demo pages and LINE postback handlers."""
import asyncio
import hashlib
import json
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.config import get_settings
from app.contracts import PipelineResult
from app.db import FeedbackItem, Member, Outreach, ReplyToken, SignalRow, Team, Theme, aware, utcnow
from app.demo import TEAM_ID, advance, demo_now, reset_demo, scenario
from app.manager.loop import (cipher, encrypt_recipient, gate_for, gate_view, metrics,
                              release_themes, reply_to_theme, theme_view)
from app.outreach.channel import outreach_view
from app.triggers.engine import respond, signal_view

router = APIRouter(prefix="/api")


def db_session(request: Request):
    with request.app.state.session_factory() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def redis_client(request: Request):
    return request.app.state.redis


def get_member(session, member_id):
    member = session.get(Member, member_id)
    if not member:
        raise HTTPException(404, "Member not found")
    return member


class ActionBody(BaseModel):
    action: str = Field(min_length=1, max_length=200)


class PreviewBody(BaseModel):
    member_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=10000)


class DraftBody(BaseModel):
    draft_id: str = Field(min_length=1, max_length=100)


class TeammatesBody(BaseModel):
    theme_slug: str | None = Field(default=None, max_length=100)


class AdvanceBody(BaseModel):
    weeks: int = Field(default=2, ge=1, le=12)


class ReplyBody(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    accept_proposal: bool = False


async def preview_feedback(session, redis, member, text):
    from app.privacy.pipeline import demo_roster, run_pipeline
    existing = [(t.slug, t.label) for t in session.scalars(select(Theme).where(Theme.team_id == member.team_id))]
    redis.incr("kjb:stats:submitted")
    result = await run_pipeline(text, member.id, demo_roster(), existing_themes=existing)
    result = PipelineResult.model_validate(result)
    if not result.ok:
        redis.incr("kjb:stats:blocked")
        return {"draft_id": None, "result": result.model_dump(mode="json")}
    if not result.structured or not result.final_text.strip() or not result.theme_slug:
        raise HTTPException(502, "Invalid privacy pipeline result")
    draft_id = secrets.token_urlsafe(32)
    # No raw source, author, trace, or attacker guess is saved to Redis.
    contribution = hashlib.sha256(f"{member.actor_hash}:{result.theme_slug}".encode()).hexdigest()
    draft = {"team_id": member.team_id, "text": result.final_text,
             "structured": result.structured.model_dump(), "slug": result.theme_slug,
             "label": result.theme_label, "rounds": len(result.attacker_rounds),
             "enc_recipient": encrypt_recipient(redis, member), "contribution": contribution}
    redis.set(f"kjb:draft:{draft_id}", json.dumps(draft, ensure_ascii=False), ex=3600)
    return {"draft_id": draft_id, "result": result.model_dump(mode="json")}


def check_draft_recipient(redis, draft_id, line_user_id):
    value = redis.get(f"kjb:draft:{draft_id}")
    if not value:
        raise HTTPException(404, "Draft expired or already confirmed")
    draft = json.loads(value)
    recipient = cipher(redis).decrypt(draft["enc_recipient"].encode()).decode()
    if recipient != f"line:{line_user_id}":
        raise HTTPException(403, "This draft belongs to another recipient")


async def confirm_feedback(session, redis, draft_id):
    lock_key = f"kjb:draft-lock:{draft_id}"
    if not redis.set(lock_key, "1", nx=True, ex=30):
        raise HTTPException(409, "Draft is being confirmed")
    try:
        value = redis.get(f"kjb:draft:{draft_id}")
        if not value:
            raise HTTPException(404, "Draft expired or already confirmed")
        draft = json.loads(value)
        theme = session.scalar(select(Theme).where(Theme.team_id == draft["team_id"], Theme.slug == draft["slug"]))
        if theme is None:
            theme = Theme(team_id=draft["team_id"], slug=draft["slug"], label=draft["label"])
            session.add(theme)
            session.flush()
        # One gate contribution per person and theme, without linking a DB row to an author.
        contribution_key = f"kjb:confirmed:{theme.team_id}:{theme.slug}"
        if not redis.sismember(contribution_key, draft["contribution"]):
            session.add(FeedbackItem(theme_id=theme.id, text=draft["text"], structured=draft["structured"],
                                     attacker_rounds=draft["rounds"]))
            token = secrets.token_urlsafe(32)
            session.add(ReplyToken(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                   theme_id=theme.id, enc_recipient=draft["enc_recipient"]))
            session.commit()
            redis.sadd(contribution_key, draft["contribution"])
            gate_for(redis).add(theme.team_id, theme.slug, draft["contribution"])
            redis.incrby("kjb:stats:rounds", draft["rounds"])
        if gate_for(redis).is_open(theme.team_id, theme.slug):
            # Decouple release from the third person's submission time.
            delay = secrets.randbelow(get_settings().gate_max_delay_s + 1)
            due = aware(demo_now(redis)) + timedelta(seconds=delay)
            redis.set(f"kjb:release-at:{theme.id}", due.isoformat(), nx=True)
        await release_themes(session, redis, theme.team_id, now=demo_now(redis))
        redis.delete(f"kjb:draft:{draft_id}")
        return {"gate": gate_view(redis, theme)}
    finally:
        redis.delete(lock_key)


@router.get("/health")
def health(session=Depends(db_session), redis=Depends(redis_client)):
    from app import llm
    from sqlalchemy import text
    db_ok = bool(session.execute(text("SELECT 1")).scalar())
    return {"ok": db_ok and bool(redis.ping()), "llm_model": get_settings().llm_model,
            "llm_available": llm.is_available(), "llm": llm.status(),
            "line_enabled": get_settings().line_enabled, "db": "ok", "redis": "ok"}


@router.get("/team")
def team(session=Depends(db_session)):
    row = session.get(Team, TEAM_ID)
    from app.privacy.pipeline import demo_roster
    order = {person.member_id: i for i, person in enumerate(demo_roster())}
    # Stable roster order (Postgres returns recently updated rows last), so the UI opens on Mint.
    members = sorted(session.scalars(select(Member).where(Member.team_id == TEAM_ID)), key=lambda m: order.get(m.id, 99))
    return {"team": {"id": row.id, "name": row.name}, "members": [
        {"member_id": m.id, "display_name": m.display_name, "role": m.role, "seniority": m.seniority,
         "gender": m.gender, "line_linked": bool(m.line_user_id)} for m in members]}


@router.post("/demo/reset")
def reset(session=Depends(db_session), redis=Depends(redis_client)):
    reset_demo(session, redis)
    return {"ok": True}


@router.post("/demo/scenario/{name}")
async def run_scenario(name: str, session=Depends(db_session), redis=Depends(redis_client)):
    rows, outreach = await scenario(session, redis, name)
    members = list(session.scalars(select(Member).where(Member.team_id == TEAM_ID)))
    member_map = {m.id: m for m in members}
    return {"signals": [signal_view(r, members) for r in rows],
            "outreach": [outreach_view(r, member_map[r.member_id]) for r in outreach]}


@router.get("/signals")
def signals(session=Depends(db_session)):
    members = list(session.scalars(select(Member).where(Member.team_id == TEAM_ID)))
    return [signal_view(r, members) for r in session.scalars(select(SignalRow).where(SignalRow.team_id == TEAM_ID))]


@router.get("/outreach")
def inbox(member_id: str, session=Depends(db_session)):
    member = get_member(session, member_id)
    return [outreach_view(r, member) for r in session.scalars(select(Outreach).where(Outreach.member_id == member.id).order_by(Outreach.created_at))]


@router.post("/outreach/{outreach_id}/respond")
async def respond_outreach(outreach_id: str, body: ActionBody, session=Depends(db_session), redis=Depends(redis_client)):
    outreach = session.get(Outreach, outreach_id)
    if not outreach:
        raise HTTPException(404, "Outreach not found")
    await respond(session, redis, outreach, body.action)
    return outreach_view(outreach, get_member(session, outreach.member_id))


@router.post("/feedback/preview")
async def preview(body: PreviewBody, session=Depends(db_session), redis=Depends(redis_client)):
    return await preview_feedback(session, redis, get_member(session, body.member_id), body.text)


@router.post("/feedback/confirm")
async def confirm(body: DraftBody, session=Depends(db_session), redis=Depends(redis_client)):
    return await confirm_feedback(session, redis, body.draft_id)


@router.post("/feedback/cancel")
def cancel(body: DraftBody, redis=Depends(redis_client)):
    redis.delete(f"kjb:draft:{body.draft_id}")
    return {"ok": True}


@router.post("/demo/teammates")
async def teammates(body: TeammatesBody = TeammatesBody(), session=Depends(db_session), redis=Depends(redis_client)):
    theme = session.scalar(select(Theme).where(Theme.team_id == TEAM_ID, Theme.slug == body.theme_slug)) if body.theme_slug else session.scalar(select(Theme).where(Theme.team_id == TEAM_ID).order_by(Theme.id.desc()))
    if not theme:
        raise HTTPException(404, "Submit feedback first")
    texts = {
        "friday-urgent-work": ["งานด่วนเย็นวันศุกร์ทำให้วางแผนพักไม่ได้ อยากให้แจ้งก่อนบ่ายสาม", "มีการสั่งงานด่วนเย็นวันศุกร์บ่อย ควรกำหนด cut-off ก่อน 15:00"],
        "pr-review-delay": ["PR review ล่าช้าทำให้งานต่อไปติดขัด ขอ SLA review ภายใน 24 ชั่วโมง", "PR ต้องรอ review หลายวัน อยากให้มีกรอบเวลา review 24 ชั่วโมง"],
    }
    added = 0
    pairs = list(zip(("m-boat", "m-fon"), texts.get(theme.slug, [theme.label, theme.label])))
    # Run both privacy pipelines at once (slow local LLMs batch parallel requests); confirm in order.
    previews = await asyncio.gather(*(preview_feedback(session, redis, get_member(session, member_id), text)
                                      for member_id, text in pairs))
    for (member_id, _), previewed in zip(pairs, previews):
        prior = gate_for(redis).count(TEAM_ID, theme.slug)
        if previewed["draft_id"]:
            # Simulated teammates explicitly opt into the same existing theme.
            draft_key = f"kjb:draft:{previewed['draft_id']}"
            draft = json.loads(redis.get(draft_key))
            draft["slug"], draft["label"] = theme.slug, theme.label
            draft["contribution"] = hashlib.sha256(f"{get_member(session, member_id).actor_hash}:{theme.slug}".encode()).hexdigest()
            redis.set(draft_key, json.dumps(draft, ensure_ascii=False), ex=3600)
            await confirm_feedback(session, redis, previewed["draft_id"])
            added += gate_for(redis).count(TEAM_ID, theme.slug) > prior
    return {"added": added, "gate": gate_view(redis, theme)}


@router.post("/demo/advance")
async def advance_demo(body: AdvanceBody, session=Depends(db_session), redis=Depends(redis_client)):
    return {"themes": await advance(session, redis, body.weeks)}


@router.get("/manager/metrics")
def manager_metrics(session=Depends(db_session), redis=Depends(redis_client)):
    return metrics(session, TEAM_ID, now=demo_now(redis))


@router.get("/manager/summary")
async def summary(session=Depends(db_session), redis=Depends(redis_client)):
    now = demo_now(redis)
    await release_themes(session, redis, TEAM_ID, now=now)
    themes = list(session.scalars(select(Theme).where(Theme.team_id == TEAM_ID, Theme.released_at.is_not(None))))
    released = session.scalar(select(func.count()).select_from(FeedbackItem).where(FeedbackItem.theme_id.in_([t.id for t in themes]))) or 0
    confirmed = session.scalar(select(func.count()).select_from(FeedbackItem)) or 0
    rounds = int(redis.get("kjb:stats:rounds") or 0)
    return {"week_label": now.strftime("%d/%m/%Y"),
            "themes": [theme_view(session, redis, t) for t in themes if gate_for(redis).is_open(TEAM_ID, t.slug)],
            "metrics": metrics(session, TEAM_ID, now=now),
            "pipeline": {"submitted": int(redis.get("kjb:stats:submitted") or 0), "released": released,
                         "blocked_by_attacker": int(redis.get("kjb:stats:blocked") or 0),
                         "avg_attacker_rounds": round(rounds / confirmed, 2) if confirmed else 0}}


@router.post("/manager/themes/{theme_id}/reply")
async def manager_reply(theme_id: str, body: ReplyBody, session=Depends(db_session), redis=Depends(redis_client)):
    theme = session.get(Theme, theme_id)
    if not theme or theme.team_id != TEAM_ID:
        raise HTTPException(404, "Theme not found")
    return await reply_to_theme(session, redis, theme, body.text, body.accept_proposal, now=demo_now(redis))
