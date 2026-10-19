"""Deliver agent messages with a durable web inbox fallback."""

from app.db import Outreach

# The agent's answer to a tapped button: LINE sends it as a reply, the web inbox shows it under the member's choice.
ACTION_REPLIES = {
    "nudge:accept": "ส่งข้อความเตือนตามข้อตกลงของทีมแล้ว ในข้อความไม่มีชื่อคุณ",
    "nudge:decline": "รับทราบ ยังไม่ส่งข้อความเตือน",
    "nudge:useless": "ขอบคุณ ระบบจะปรับเกณฑ์การแจ้งเตือน",
    "mute": "ปิดการแจ้งเตือนประเภทนี้แล้ว",
}


def action_reply(action):
    return ACTION_REPLIES.get(
        "mute" if action.startswith("mute:") else action.rsplit(":", 1)[0], "รับทราบแล้ว"
    )


def outreach_view(row, member):
    return {
        "id": row.id,
        "member_id": row.member_id,
        "display_name": member.display_name,
        "kind": row.kind,
        "text": row.text,
        "buttons": row.buttons,
        "channel": row.channel,
        "created_at": row.created_at.isoformat(),
        "response": row.response,
        "reply": action_reply(row.response) if row.response else None,
    }


async def deliver(session, member, text, *, kind, buttons=None, signal_id=None):
    row = Outreach(
        member_id=member.id,
        signal_id=signal_id,
        kind=kind,
        text=text,
        buttons=buttons or [],
        channel="web",
    )
    session.add(row)
    session.flush()
    if member.line_user_id:
        from app.outreach.line_bot import push_text

        if await push_text(member.line_user_id, text, row.buttons):
            row.channel = "line"
    session.flush()
    return row
