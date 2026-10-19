"""Released themes, anonymous replies and metric-based two-week follow-up."""
import json
from datetime import datetime, timedelta
from statistics import mean, median

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select

from app import llm
from app.config import get_settings
from app.db import Event, FeedbackItem, Member, ReplyToken, Theme, aware, utcnow
from app.outreach.channel import deliver
from app.triggers.engine import load_events
from app.triggers.rules import BANGKOK

PROPOSALS = {
    "friday-urgent-work": "กำหนด cut-off งานด่วนก่อน 15:00 วันศุกร์",
    "pr-review-delay": "SLA review 24 ชม.",
    "blocked-tickets": "กำหนดผู้ช่วยแก้ block และติดตามภายใน 1 วัน",
}


def cipher(redis):
    key = get_settings().token_enc_key
    if not key:
        # Local fakeredis keys last for the process lifetime; cloud must set TOKEN_ENC_KEY.
        redis.set("kjb:local-encryption-key", Fernet.generate_key().decode(), nx=True)
        key = redis.get("kjb:local-encryption-key")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_recipient(redis, member):
    destination = f"line:{member.line_user_id}" if member.line_user_id else f"web:{member.id}"
    return cipher(redis).encrypt(destination.encode()).decode()


def gate_for(redis):
    from app.privacy.gate import KGate
    return KGate(redis, get_settings().k_anonymity)


def gate_view(redis, theme):
    gate = gate_for(redis)
    n = gate.count(theme.team_id, theme.slug)
    released = gate.is_open(theme.team_id, theme.slug)
    return {"theme_slug": theme.slug, "theme_label": theme.label, "count": n,
            "k": get_settings().k_anonymity, "released": released and theme.released_at is not None,
            "count_range": gate.count_range(n) if released else "รอครบกลุ่ม"}


def metrics(session, team_id, *, now=None):
    now = aware(now or utcnow())
    events = load_events(session, team_id)

    def measure(start, end):
        visible = [e for e in events if aware(e.timestamp) <= end]
        waits, blocked = [], []
        for e in visible:
            if aware(e.timestamp) < start:
                continue
            if e.type == "pr_review_requested":
                reviews = [r for r in visible if r.ref == e.ref and r.type == "pr_reviewed" and aware(r.timestamp) >= aware(e.timestamp)]
                done = min((aware(r.timestamp) for r in reviews), default=end)
                waits.append((done - aware(e.timestamp)).total_seconds() / 3600)
            if e.type == "ticket_status" and e.status.lower() == "blocked":
                done = min((aware(r.timestamp) for r in visible if r.ref == e.ref and r.type == "ticket_status"
                            and r.status.lower() != "blocked" and aware(r.timestamp) > aware(e.timestamp)), default=end)
                blocked.append((done - aware(e.timestamp)).total_seconds() / 86400)
        friday = sum(1 for e in visible if e.type == "task_assigned" and aware(e.timestamp) >= start
                     and aware(e.timestamp).astimezone(BANGKOK).weekday() == 4
                     and aware(e.timestamp).astimezone(BANGKOK).hour >= 17)
        reviews = [e.actor_hash for e in visible if e.type == "pr_reviewed" and aware(e.timestamp) >= start]
        from collections import Counter
        share = max(Counter(reviews).values(), default=0) / len(reviews) if reviews else 0
        ordered = sorted(waits)
        return {"pr_wait_hours_median": round(median(waits), 1) if waits else 0,
                "pr_wait_hours_p90": round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * .9))], 1) if ordered else 0,
                "blocked_ticket_days_avg": round(mean(blocked), 2) if blocked else 0,
                "friday_after17_assignments_4w": friday, "review_top_share": round(share, 3)}

    result = measure(now - timedelta(weeks=4), now)
    series = {"weeks": [], "pr_wait_hours": [], "friday_after17": [], "blocked_days": []}
    for offset in reversed(range(8)):
        end = now - timedelta(weeks=offset)
        weekly = measure(end - timedelta(weeks=1), end)
        series["weeks"].append(end.astimezone(BANGKOK).strftime("%d/%m"))
        series["pr_wait_hours"].append(weekly["pr_wait_hours_median"])
        series["friday_after17"].append(weekly["friday_after17_assignments_4w"])
        series["blocked_days"].append(weekly["blocked_ticket_days_avg"])
    return {**result, "series": series}


async def proposal_for(theme):
    fallback = PROPOSALS.get(theme.slug, "ตกลงแนวทางร่วมกับทีมและติดตามผลใน 2 สัปดาห์")
    if get_settings().llm_api_key:
        try:
            result = await llm.chat([
                {"role": "system", "content": "เสนอการปรับกระบวนการทีม 1 ข้อ เป็นภาษาไทยสั้น ๆ ห้ามคาดเดาตัวผู้ส่ง"},
                {"role": "user", "content": theme.label},
            ], max_tokens=200)
            if result.strip():
                return result.strip()[:1000]
        except (llm.LLMError, ValueError):
            pass
    return fallback


async def release_themes(session, redis, team_id, *, now=None):
    for theme in session.scalars(select(Theme).where(Theme.team_id == team_id)):
        if theme.released_at is None and gate_for(redis).is_open(team_id, theme.slug):
            due = redis.get(f"kjb:release-at:{theme.id}")
            if due and aware(datetime.fromisoformat(due)) > aware(now or utcnow()):
                continue
            theme.released_at = now or utcnow()
            theme.proposal = await proposal_for(theme)
    session.flush()


def theme_view(session, redis, theme):
    if theme.released_at is None or not gate_for(redis).is_open(theme.team_id, theme.slug):
        raise HTTPException(404, "Theme not released")
    items = session.scalars(select(FeedbackItem).where(FeedbackItem.theme_id == theme.id).limit(3))
    count = gate_for(redis).count(theme.team_id, theme.slug)
    return {"id": theme.id, "slug": theme.slug, "label": theme.label,
            "count_range": gate_for(redis).count_range(count), "status": theme.status,
            "samples": [item.structured for item in items], "proposal": theme.proposal,
            "manager_reply": theme.manager_reply, "followup": theme.followup,
            "released_at": aware(theme.released_at).isoformat()}


async def reply_to_theme(session, redis, theme, text, accept_proposal, *, now=None):
    theme_view(session, redis, theme)
    now = aware(now or utcnow())
    theme.manager_reply = text
    theme.accepted_proposal = accept_proposal
    theme.status = "responded"
    metric_name = "friday_after17_assignments_4w" if theme.slug == "friday-urgent-work" else "pr_wait_hours_median" if theme.slug == "pr-review-delay" else "blocked_ticket_days_avg"
    before = metrics(session, theme.team_id, now=now)[metric_name]
    theme.followup = {"due_at": (now + timedelta(weeks=2)).isoformat(), "metric_name": metric_name,
                      "before": before, "after": None, "improved": None}
    destinations = set()
    for token in session.scalars(select(ReplyToken).where(ReplyToken.theme_id == theme.id)):
        try:
            destination = cipher(redis).decrypt(token.enc_recipient.encode()).decode()
        except InvalidToken:
            continue
        if destination in destinations:
            continue
        destinations.add(destination)
        channel, value = destination.split(":", 1)
        member = session.scalar(select(Member).where(Member.line_user_id == value)) if channel == "line" else session.get(Member, value)
        if member:
            await deliver(session, member, f"คำตอบจากหัวหน้าทีมเรื่อง {theme.label}: {text}", kind="manager_reply")
    session.flush()
    return theme_view(session, redis, theme)


def follow_up(session, redis, team_id, *, now=None):
    now = aware(now or utcnow())
    current = metrics(session, team_id, now=now)
    for theme in session.scalars(select(Theme).where(Theme.team_id == team_id, Theme.status == "responded")):
        followup = theme.followup
        if followup and aware(datetime.fromisoformat(followup["due_at"])) <= now:
            after = current[followup["metric_name"]]
            improved = after < followup["before"]
            theme.followup = {**followup, "after": after, "improved": improved}
            if improved:
                theme.status = "resolved"
    session.flush()
