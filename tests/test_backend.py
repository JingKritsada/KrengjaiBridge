import base64
import hashlib
import hmac
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select

from app import llm
from app.config import get_settings
from app.db import FeedbackItem, Member, ReplyToken, Theme
from app.privacy.pipeline import run_pipeline as real_run_pipeline


def post(client, path, body=None):
    response = client.post(path, json={} if body is None else body)
    assert response.status_code == 200, response.text
    return response.json()


def preview(client, member="m-mint", text="งานด่วนวันศุกร์กระทบการพักผ่อน"):
    return post(client, "/api/feedback/preview", {"member_id": member, "text": text})


def confirm(client, draft):
    return post(client, "/api/feedback/confirm", {"draft_id": draft["draft_id"]})


def release_friday(client):
    confirm(client, preview(client))
    result = post(client, "/api/demo/teammates", {"theme_slug": "friday-urgent-work"})
    assert result["gate"]["released"] is True
    return client.get("/api/manager/summary").json()["themes"][0]


@pytest.mark.parametrize("llm_down", [False, True])
def test_full_http_story(backend_client, pipeline_mock, monkeypatch, llm_down):
    if llm_down:
        from app.privacy import identifiers

        async def unavailable(*args, **kwargs):
            raise llm.LLMError("422: Budget has been exceeded")

        monkeypatch.setattr(llm, "chat", unavailable)
        monkeypatch.setattr(llm, "chat_json", unavailable)
        monkeypatch.setattr(identifiers, "_local_ner", lambda: None)
        monkeypatch.setattr(pipeline_mock, "run_pipeline", real_run_pipeline)
        monkeypatch.setattr(get_settings(), "llm_api_key", "offline-test-key")
    c = backend_client
    assert c.get("/api/health").json()["ok"] is True
    assert len(c.get("/api/team").json()["members"]) == 6
    result = post(c, "/api/demo/scenario/pr_stale")
    signal = next(s for s in result["signals"] if s["kind"] == "pr_stale")
    outreach = next(o for o in result["outreach"] if o["kind"] == "pr_stale")
    assert signal["judge_ok"]
    if llm_down:
        assert c.get("/api/health").json()["llm_available"] is False
    post(c, f"/api/outreach/{outreach['id']}/respond", {"action": f"nudge:accept:{signal['id']}"})
    reviewer_inbox = c.get("/api/outreach", params={"member_id": "m-somchai"}).json()
    reminder = next(o for o in reviewer_inbox if o["kind"] == "reminder")
    assert "PR #123" in reminder["text"] and "ข้อตกลงของทีม" in reminder["text"]
    assert "มิ้น" not in reminder["text"] and "Mint" not in reminder["text"]
    draft = preview(c)
    assert draft["result"]["ok"] and draft["result"]["structured"]
    if llm_down:
        assert any("โหมดสำรอง" in note for step in draft["result"]["steps"] for note in step["notes"])
    gate = confirm(c, draft)["gate"]
    assert gate["count"] == 1 and not gate["released"]
    assert c.get("/api/manager/summary").json()["themes"] == []
    teammates = post(c, "/api/demo/teammates", {"theme_slug": "friday-urgent-work"})
    assert teammates["added"] == 2 and teammates["gate"]["released"]
    summary = c.get("/api/manager/summary").json()
    theme = summary["themes"][0]
    assert theme["count_range"] == "3–5 คน" and "count" not in theme
    assert "15:00" in theme["proposal"]
    assert summary["metrics"]["friday_after17_assignments_4w"] == 3
    reply = "ตกลง จะกำหนด cut-off งานด่วนก่อน 15:00 วันศุกร์"
    responded = post(c, f"/api/manager/themes/{theme['id']}/reply", {"text": reply, "accept_proposal": True})
    assert responded["status"] == "responded"
    inbox = c.get("/api/outreach", params={"member_id": "m-mint"}).json()
    assert any(reply in item["text"] and item["kind"] == "manager_reply" for item in inbox)
    followed = post(c, "/api/demo/advance", {"weeks": 2})["themes"][0]
    assert followed["status"] == "resolved"
    assert followed["followup"]["improved"] is True
    assert followed["followup"]["before"] == 3 and followed["followup"]["after"] == 0
    assert c.get("/api/manager/metrics").json()["friday_after17_assignments_4w"] == 0


def test_health_llm_availability_expires_without_network(backend_client, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(llm, "monotonic", lambda: clock[0])
    monkeypatch.setattr(llm, "_last_error_at", None)
    assert backend_client.get("/api/health").json()["llm_available"] is True
    llm.LLMError("422: Budget has been exceeded")
    assert backend_client.get("/api/health").json()["llm_available"] is False
    clock[0] += 59
    assert backend_client.get("/api/health").json()["llm_available"] is False
    clock[0] += 1
    assert backend_client.get("/api/health").json()["llm_available"] is True


def test_source_never_persisted_and_no_author_column(backend_client):
    c = backend_client
    original = "SOURCE-DO-NOT-SAVE-93817 หนูได้รับงานศุกร์เย็นจากพี่สมชายค่ะ"
    draft = preview(c, text=original)
    redis = c.app.state.redis
    cached = redis.get(f"kjb:draft:{draft['draft_id']}")
    assert original not in cached and "m-mint" not in cached
    assert 3500 < redis.ttl(f"kjb:draft:{draft['draft_id']}") <= 3600
    confirm(c, draft)
    with c.app.state.session_factory() as session:
        columns = {column["name"] for column in inspect(session.bind).get_columns("feedback_items")}
        assert not columns & {"author", "author_id", "member_id", "actor_hash", "line_user_id", "recipient"}
        assert columns == {"id", "theme_id", "text", "structured", "attacker_rounds"}
        dump = "\n".join(session.connection().connection.driver_connection.iterdump())
        assert original not in dump and "SOURCE-DO-NOT-SAVE-93817" not in dump
        token = session.scalar(select(ReplyToken))
        assert "m-mint" not in token.enc_recipient and len(token.token_hash) == 64
    assert not redis.exists(f"kjb:draft:{draft['draft_id']}")


def test_repeat_author_does_not_open_gate_and_private_theme_cannot_be_replied_to(backend_client):
    c = backend_client
    for _ in range(3):
        gate = confirm(c, preview(c))["gate"]
        assert gate["count"] == 1 and not gate["released"]
    assert c.get("/api/manager/summary").json()["themes"] == []
    with c.app.state.session_factory() as session:
        theme_id = session.scalar(select(Theme)).id
        assert len(list(session.scalars(select(FeedbackItem)))) == 1
    assert c.post(f"/api/manager/themes/{theme_id}/reply", json={"text": "reply"}).status_code == 404


def test_cancel_expiry_and_failed_pipeline(backend_client, pipeline_mock, monkeypatch):
    c = backend_client
    draft = preview(c)
    post(c, "/api/feedback/cancel", {"draft_id": draft["draft_id"]})
    assert c.post("/api/feedback/confirm", json={"draft_id": draft["draft_id"]}).status_code == 404
    draft = preview(c)
    c.app.state.redis.delete(f"kjb:draft:{draft['draft_id']}")
    assert c.post("/api/feedback/confirm", json={"draft_id": draft["draft_id"]}).status_code == 404
    from app.contracts import PipelineResult
    async def blocked(*args, **kwargs):
        return PipelineResult(ok=False, reason_blocked="unsafe")
    monkeypatch.setattr(pipeline_mock, "run_pipeline", blocked)
    assert preview(c)["draft_id"] is None
    assert c.get("/api/manager/summary").json()["pipeline"]["blocked_by_attacker"] == 1


def test_weekly_limit_idempotence_and_self_only(backend_client):
    c = backend_client
    result = post(c, "/api/demo/scenario/pr_stale")
    nudge = next(o for o in result["outreach"] if o["kind"] == "pr_stale")
    action = nudge["buttons"][0]["action"]
    for _ in range(2):
        post(c, f"/api/outreach/{nudge['id']}/respond", {"action": action})
    assert len(c.get("/api/outreach?member_id=m-somchai").json()) == 1
    post(c, "/api/demo/scenario/late_night")
    post(c, "/api/demo/scenario/ticket_blocked")
    inbox = c.get("/api/outreach?member_id=m-mint").json()
    assert len(inbox) == 3
    late = next(o for o in inbox if o["kind"] == "late_night")
    post(c, f"/api/outreach/{late['id']}/respond", {"action": late["buttons"][0]["action"]})
    assert len(c.get("/api/outreach?member_id=m-somchai").json()) == 1
    manager = c.get("/api/manager/summary").text
    assert "late_night" not in manager and "22:00" not in manager
    assert post(c, "/api/demo/scenario/pr_stale")["outreach"] == []


def test_mute_blocks_future_nudges(backend_client):
    c = backend_client
    with c.app.state.session_factory() as session:
        member = session.get(Member, "m-mint")
        member.muted_kinds = ["pr_stale"]
        session.commit()
    result = post(c, "/api/demo/scenario/pr_stale")
    assert any(s["kind"] == "pr_stale" for s in result["signals"])
    assert not any(o["kind"] == "pr_stale" for o in result["outreach"])


def test_advance_without_accepted_proposal_keeps_observed_friday_work(backend_client):
    c = backend_client
    theme = release_friday(c)
    post(c, f"/api/manager/themes/{theme['id']}/reply", {"text": "ขอดูต่อไป", "accept_proposal": False})
    followed = post(c, "/api/demo/advance", {"weeks": 2})["themes"][0]
    assert followed["followup"]["after"] >= 2


def test_release_delay_hides_theme_until_due(backend_client, backend_settings, monkeypatch):
    c = backend_client
    monkeypatch.setattr(backend_settings, "gate_max_delay_s", 20)
    monkeypatch.setattr("app.api.secrets.randbelow", lambda n: n - 1)
    confirm(c, preview(c))
    gate = post(c, "/api/demo/teammates")["gate"]
    assert gate["count"] == 3 and not gate["released"]
    assert c.get("/api/manager/summary").json()["themes"] == []
    from app.demo import demo_now
    c.app.state.redis.set("kjb:demo-clock", (demo_now(c.app.state.redis) + timedelta(seconds=21)).isoformat())
    assert len(c.get("/api/manager/summary").json()["themes"]) == 1


def test_inputs_reset_and_static_routes(backend_client):
    c = backend_client
    assert c.post("/api/feedback/preview", json={"member_id": "m-mint", "text": ""}).status_code == 422
    assert c.post("/api/demo/advance", json={"weeks": -1}).status_code == 422
    assert c.post("/api/demo/scenario/unknown").status_code == 404
    for path in ("/", "/manager", "/demo"):
        assert c.get(path).status_code == 200
    release_friday(c)
    post(c, "/api/demo/reset")
    assert c.get("/api/manager/summary").json()["themes"] == []
    assert c.get("/api/outreach?member_id=m-mint").json() == []


def line_event(c, secret, events, *, signature=None):
    events = [{"webhookEventId": uuid.uuid4().hex, "deliveryContext": {"isRedelivery": False}, **event} for event in events]
    body = json.dumps({"destination": "Ubot", "events": events}, ensure_ascii=False).encode()
    computed = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return c.post("/line/webhook", content=body, headers={"Content-Type": "application/json", "X-Line-Signature": computed if signature is None else signature})


def test_line_signature_follow_link_preview_confirm_and_push(backend_client, backend_settings, monkeypatch):
    c = backend_client
    backend_settings.line_channel_secret = "test-channel-secret"
    backend_settings.line_channel_access_token = "test-access-token"
    replies, pushes = [], []
    from linebot.v3.messaging import MessagingApi
    monkeypatch.setattr(MessagingApi, "reply_message", lambda self, payload: replies.append(payload))
    monkeypatch.setattr(MessagingApi, "push_message", lambda self, payload: pushes.append(payload))
    base = {"replyToken": "reply-token", "timestamp": 1720000000000, "source": {"type": "user", "userId": "Umint"}, "mode": "active"}
    secret = backend_settings.line_channel_secret
    follow = {**base, "type": "follow", "follow": {"isUnblocked": False}}
    assert line_event(c, secret, [follow], signature="invalid").status_code == 403
    assert line_event(c, secret, [follow]).status_code == 200
    prompt = replies[-1].messages[0]
    assert "คุณคือใคร" in prompt.text and len(prompt.quick_reply.items) == 6
    assert any(item.action.data == "link:m-mint" for item in prompt.quick_reply.items)
    assert line_event(c, secret, [{**base, "type": "postback", "postback": {"data": "link:m-mint"}}]).status_code == 200
    text_event = {**base, "type": "message", "message": {"id": "message1", "type": "text", "quoteToken": "quote-token", "text": "หนูไม่สะดวกรับงานศุกร์เย็นค่ะ"}}
    assert line_event(c, secret, [text_event]).status_code == 200
    flex = replies[-1].messages[0]
    assert flex.type == "flex"
    action = flex.contents.footer.contents[0].action.data
    assert action.startswith("fb:confirm:")
    assert line_event(c, secret, [{**base, "type": "postback", "postback": {"data": action}}]).status_code == 200
    result = post(c, "/api/demo/scenario/pr_stale")
    line_outreach = next(o for o in result["outreach"] if o["kind"] == "pr_stale")
    assert line_outreach["channel"] == "line" and pushes[-1].to == "Umint"
    assert pushes[-1].messages[0].quick_reply


def test_line_push_failure_falls_back_to_web(backend_client, backend_settings, monkeypatch):
    c = backend_client
    backend_settings.line_channel_secret = "secret"
    backend_settings.line_channel_access_token = "token"
    from linebot.v3.messaging import MessagingApi
    def unavailable(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(MessagingApi, "push_message", unavailable)
    with c.app.state.session_factory() as session:
        session.get(Member, "m-mint").line_user_id = "Umint"
        session.commit()
    result = post(c, "/api/demo/scenario/pr_stale")
    assert all(o["channel"] == "web" for o in result["outreach"])


def test_line_typed_text_works_without_quick_replies(backend_client, backend_settings, monkeypatch):
    # LINE for PC/Mac has no quick replies: typed names, button labels and ยืนยัน must work.
    c = backend_client
    backend_settings.line_channel_secret = "test-channel-secret"
    backend_settings.line_channel_access_token = "test-access-token"
    replies, pushes = [], []
    from linebot.v3.messaging import MessagingApi
    monkeypatch.setattr(MessagingApi, "reply_message", lambda self, payload: replies.append(payload))
    monkeypatch.setattr(MessagingApi, "push_message", lambda self, payload: pushes.append(payload))
    secret = backend_settings.line_channel_secret
    base = {"replyToken": "reply-token", "timestamp": 1720000000000, "source": {"type": "user", "userId": "Upc"}, "mode": "active"}

    def say(text):
        event = {**base, "type": "message", "message": {"id": uuid.uuid4().hex, "type": "text", "quoteToken": "q", "text": text}}
        assert line_event(c, secret, [event]).status_code == 200
        return replies[-1].messages[0]

    assert "เชื่อมต่อเป็น มิ้น" in say(" มิ้น ").text
    with c.app.state.session_factory() as session:
        assert session.get(Member, "m-mint").line_user_id == "Upc"

    assert "รายละเอียดเพิ่ม" in say("งานเยอะ").text  # too short to be feedback; no pipeline call

    post(c, "/api/demo/scenario/pr_stale")
    assert "ไม่มีชื่อคุณ" in say("ช่วยเตือนให้หน่อย").text
    nudge = next(o for o in c.get("/api/outreach?member_id=m-mint").json() if o["kind"] == "pr_stale")
    assert nudge["response"].startswith("nudge:accept:")
    assert any(o["kind"] != "pr_stale" for o in c.get("/api/outreach?member_id=m-somchai").json())

    flex = say("หนูไม่สะดวกรับงานศุกร์เย็นค่ะ เพราะต้องยกเลิกนัดบ่อยมาก")
    assert flex.type == "flex"
    assert "ยืนยันแล้ว" in say("ยืนยัน").text
    assert "ไม่มีฉบับร่าง" in say("ยืนยัน").text
