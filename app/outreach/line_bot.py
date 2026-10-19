"""LINE SDK v3 integration. All synchronous SDK I/O runs in a thread pool."""
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (ApiClient, Configuration, FlexContainer, FlexMessage,
                                  MessagingApi, PostbackAction, PushMessageRequest,
                                  QuickReply, QuickReplyItem, ReplyMessageRequest, TextMessage)
from linebot.v3.webhook import WebhookParser
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api import (check_draft_recipient, confirm_feedback, db_session, get_member,
                     preview_feedback, redis_client)
from app.config import get_settings
from app.db import Member, Outreach
from app.outreach.channel import deliver
from app.triggers.engine import respond

router = APIRouter()


# LINE for PC/Mac shows no quick replies, so every button also works as typed text.
MIN_FEEDBACK_CHARS = 15
CONFIRM_WORDS = {"ยืนยัน", "ยืนยันส่ง", "ส่ง", "confirm"}
CANCEL_WORDS = {"ยกเลิก", "cancel"}
HELP_WORDS = {"ช่วยเหลือ", "วิธีใช้", "เมนู", "help"}
HELP_TEXT = ("วิธีใช้: พิมพ์ความเห็นที่อยากสะท้อนได้เลย (อย่างน้อยหนึ่งประโยค) ระบบจะให้ดูฉบับไม่ระบุตัวตนก่อนส่ง\n"
             "พิมพ์ \"ยืนยัน\" หรือ \"ยกเลิก\" สำหรับฉบับร่างล่าสุด\n"
             "ตอบข้อความเตือนได้ด้วยการพิมพ์: ช่วยเตือนให้หน่อย / ยังไม่ต้อง / ไม่มีประโยชน์ / ปิดแจ้งเตือนแบบนี้")
ACTION_REPLIES = {"nudge:accept": "ส่งข้อความเตือนตามข้อตกลงของทีมแล้ว ในข้อความไม่มีชื่อคุณ",
                  "nudge:decline": "รับทราบ ยังไม่ส่งข้อความเตือน",
                  "nudge:useless": "ขอบคุณ ระบบจะปรับเกณฑ์การแจ้งเตือน",
                  "mute": "ปิดการแจ้งเตือนประเภทนี้แล้ว"}


def _norm(text):
    return re.sub(r"\s+", "", text or "").casefold()


def quick_reply(buttons):
    # display_text echoes the choice into the chat, so a screen recording shows what was tapped.
    return QuickReply(items=[QuickReplyItem(action=PostbackAction(label=b["label"][:20], data=b["action"],
                                                                  display_text=b["label"][:300]))
                             for b in buttons[:13]])


def text_message(text, buttons=None):
    return TextMessage(text=text[:5000], quick_reply=quick_reply(buttons) if buttons else None)


def preview_message(draft_id, result):
    structured = result.get("structured") or {}
    rows = [{"type": "text", "text": "ตรวจสอบความเห็นก่อนส่ง", "weight": "bold", "size": "lg"}]
    for key, label in (("situation", "สถานการณ์"), ("impact", "ผลกระทบ"), ("request", "สิ่งที่ขอ")):
        rows += [{"type": "text", "text": label, "weight": "bold", "margin": "md"},
                 {"type": "text", "text": structured.get(key) or "—", "wrap": True}]
    rows.append({"type": "text", "text": f"ทดสอบผู้โจมตี {len(result.get('attacker_rounds', []))} รอบ", "size": "sm", "margin": "md"})
    bubble = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": rows},
              "footer": {"type": "box", "layout": "vertical", "contents": [
                  {"type": "button", "style": style, "action": {"type": "postback", "label": label, "data": f"fb:{action}:{draft_id}", "displayText": label}}
                  for style, label, action in (("primary", "ยืนยันส่ง", "confirm"), ("secondary", "ยกเลิก", "cancel"))]}}
    return FlexMessage(alt_text="ตรวจสอบความเห็นแบบไม่ระบุตัวตนก่อนส่ง", contents=FlexContainer.from_json(json.dumps(bubble, ensure_ascii=False)))


def _send_sync(method, payload):
    with ApiClient(Configuration(access_token=get_settings().line_channel_access_token)) as client:
        api = MessagingApi(client)
        getattr(api, method)(payload)


async def push_text(user_id, text, buttons=None):
    if not get_settings().line_enabled:
        return False
    try:
        await run_in_threadpool(_send_sync, "push_message", PushMessageRequest(to=user_id, messages=[text_message(text, buttons)]))
        return True
    except Exception:
        # SDK exceptions can include request data; do not log them.
        return False


async def reply_message(reply_token, message):
    await run_in_threadpool(_send_sync, "reply_message", ReplyMessageRequest(reply_token=reply_token, messages=[message]))


async def linking_prompt(session, reply_token):
    buttons = [{"label": m.display_name, "action": f"link:{m.id}"} for m in session.scalars(select(Member))]
    await reply_message(reply_token, text_message("คุณคือใครในทีมเดโม", buttons))


def action_reply(action):
    return ACTION_REPLIES.get("mute" if action.startswith("mute:") else action.rsplit(":", 1)[0], "รับทราบแล้ว")


def typed_member(session, typed):
    """Match a typed name ("มิ้น", "สมชาย", "Mint") to a demo member while linking."""
    from app.privacy.pipeline import demo_roster
    nicknames = {p.member_id: p.nicknames for p in demo_roster()}
    for target in session.scalars(select(Member)):
        names = {target.display_name, re.sub(r"^(?:พี่|น้อง)", "", target.display_name), *nicknames.get(target.id, [])}
        if typed in {_norm(n) for n in names if n}:
            return target
    return None


def typed_button(session, member, typed):
    """Typed equivalent of a quick-reply button on the member's latest unanswered messages."""
    recent = list(session.scalars(select(Outreach).where(Outreach.member_id == member.id, Outreach.response.is_(None))
                                  .order_by(Outreach.created_at.desc()).limit(5)))
    # Newest first; among messages sent together, reminders the agent can act on come first.
    actionable = {"pr_stale": 0, "ticket_blocked": 1}
    recent.sort(key=lambda o: (-int(o.created_at.timestamp()), actionable.get(o.kind, 9)))
    for outreach in recent:
        for button in outreach.buttons:
            if typed in {_norm(button["label"]), _norm(button["label"][:20])}:
                return outreach, button["action"]
    return None


async def link_member(session, member, target, user_id, reply_token):
    if target.line_user_id and target.line_user_id != user_id:
        raise HTTPException(409, "Demo member already linked")
    if member and member.id != target.id:
        member.line_user_id = None
        session.flush()
    target.line_user_id, target.opted_in = user_id, True
    await reply_message(reply_token, text_message(f"เชื่อมต่อเป็น {target.display_name} แล้ว ส่งความเห็นได้ที่แชตนี้ ข้อความจะผ่านการตรวจความเป็นส่วนตัวก่อนส่ง\n\n" + HELP_TEXT))


async def finish_draft(session, redis, user_id, draft_id, kind, reply_token):
    check_draft_recipient(redis, draft_id, user_id)
    if kind == "confirm":
        result = await confirm_feedback(session, redis, draft_id)
        text = "ยืนยันแล้ว รอครบกลุ่มก่อนส่งให้หัวหน้าทีม" if not result["gate"]["released"] else "ยืนยันแล้ว ประเด็นนี้พร้อมแสดงแบบไม่ระบุตัวตน"
    else:
        redis.delete(f"kjb:draft:{draft_id}")
        text = "ยกเลิกและลบฉบับร่างแล้ว"
    redis.delete(f"kjb:line-draft:{user_id}")
    await reply_message(reply_token, text_message(text))


async def handle_event(session, redis, event):
    source = getattr(event, "source", None)
    # Feedback is accepted only in a private chat, never in a group or room.
    if not source or source.type != "user":
        return
    user_id = getattr(source, "user_id", None)
    if not user_id:
        return
    member = session.scalar(select(Member).where(Member.line_user_id == user_id))
    if event.type == "follow":
        if member:
            member.opted_in = True
        await linking_prompt(session, event.reply_token)
    elif event.type == "unfollow":
        if member:
            member.opted_in = False
    elif event.type == "postback":
        action = event.postback.data
        if action.startswith("link:"):
            await link_member(session, member, get_member(session, action.split(":", 1)[1]), user_id, event.reply_token)
        elif not member:
            await linking_prompt(session, event.reply_token)
        elif action.startswith("fb:"):
            parts = action.split(":", 2)
            if len(parts) != 3 or parts[1] not in ("confirm", "cancel"):
                raise HTTPException(400, "Invalid feedback action")
            await finish_draft(session, redis, user_id, parts[2], parts[1], event.reply_token)
        elif action.startswith(("nudge:", "mute:")):
            candidates = list(session.scalars(select(Outreach).where(Outreach.member_id == member.id).order_by(Outreach.created_at.desc())))
            outreach = next((r for r in candidates if action in {b["action"] for b in r.buttons}), None)
            if not outreach:
                raise HTTPException(404, "Action not found for this recipient")
            await respond(session, redis, outreach, action)
            await reply_message(event.reply_token, text_message(action_reply(action)))
        else:
            raise HTTPException(400, "Unknown action")
    elif event.type == "message" and event.message.type == "text":
        text = event.message.text
        typed = _norm(text)
        if not member:
            target = typed_member(session, typed)
            if target:
                await link_member(session, None, target, user_id, event.reply_token)
            else:
                await linking_prompt(session, event.reply_token)
        elif typed == _norm("ความเห็น"):
            await reply_message(event.reply_token, text_message("พิมพ์ความเห็นที่อยากสะท้อนได้เลย ระบบจะให้ตรวจฉบับไม่ระบุตัวตนก่อนยืนยัน"))
        elif typed in {_norm(w) for w in HELP_WORDS}:
            await reply_message(event.reply_token, text_message(HELP_TEXT))
        elif typed in {_norm(w) for w in CONFIRM_WORDS | CANCEL_WORDS}:
            draft_id = redis.get(f"kjb:line-draft:{user_id}")
            if not draft_id:
                await reply_message(event.reply_token, text_message("ไม่มีฉบับร่างที่รอยืนยัน พิมพ์ความเห็นใหม่ได้เลย"))
                return
            kind = "confirm" if typed in {_norm(w) for w in CONFIRM_WORDS} else "cancel"
            await finish_draft(session, redis, user_id, draft_id, kind, event.reply_token)
        elif outreach_action := typed_button(session, member, typed):
            outreach, action = outreach_action
            await respond(session, redis, outreach, action)
            await reply_message(event.reply_token, text_message(action_reply(action)))
        elif len(text.strip()) < MIN_FEEDBACK_CHARS:
            await reply_message(event.reply_token, text_message("ช่วยเล่ารายละเอียดเพิ่มอีกนิด (อย่างน้อยหนึ่งประโยค) ระบบจะเรียบเรียงแบบไม่ระบุตัวตนได้ถูกต้อง\n\n" + HELP_TEXT))
        else:
            if len(text) > 10000:
                await reply_message(event.reply_token, text_message("กรุณาส่งความเห็นไม่เกิน 10,000 ตัวอักษร"))
                return
            result = await preview_feedback(session, redis, member, text)
            if result["draft_id"]:
                redis.set(f"kjb:line-draft:{user_id}", result["draft_id"], ex=3600)
                await reply_message(event.reply_token, preview_message(result["draft_id"], result["result"]))
            else:
                await reply_message(event.reply_token, text_message("ยังไม่ผ่านการตรวจความเป็นส่วนตัว กรุณาปรับข้อความแล้วลองใหม่"))


@router.post("/line/webhook")
async def webhook(request: Request, session=Depends(db_session), redis=Depends(redis_client)):
    settings = get_settings()
    if not settings.line_enabled:
        raise HTTPException(503, "LINE is disabled")
    body = await request.body()
    if len(body) > 1000000:
        raise HTTPException(413, "Webhook too large")
    try:
        events = WebhookParser(settings.line_channel_secret).parse(body.decode("utf-8"), request.headers.get("X-Line-Signature", ""))
    except InvalidSignatureError:
        raise HTTPException(403, "Invalid signature") from None
    except (ValueError, UnicodeError, KeyError, TypeError):
        raise HTTPException(400, "Invalid webhook") from None
    for event in events:
        event_id = getattr(event, "webhook_event_id", None)
        if event_id and redis.exists(f"kjb:line-event:{event_id}"):
            continue
        try:
            await handle_event(session, redis, event)
            session.commit()
        except HTTPException:
            raise
        except Exception:
            # Never put SDK request payloads or original feedback in error responses.
            raise HTTPException(502, "LINE service temporarily unavailable") from None
        if event_id:
            redis.set(f"kjb:line-event:{event_id}", "1", ex=86400)
    return {"ok": True}
