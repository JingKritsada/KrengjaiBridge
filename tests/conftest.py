"""Offline backend fixtures; never call the real LLM or Messaging API."""
import sys
import types

import fakeredis
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import get_settings
from app.contracts import AttackerGuess, MemberProfile, PipelineResult, PipelineStep, StructuredFeedback


@pytest.fixture
def backend_settings(monkeypatch):
    for key, value in {"LLM_API_KEY": "", "LINE_CHANNEL_SECRET": "", "LINE_CHANNEL_ACCESS_TOKEN": "",
                       "GATE_MAX_DELAY_S": "0", "TOKEN_ENC_KEY": Fernet.generate_key().decode()}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def fallback_roster():
    return [MemberProfile(member_id=mid, display_name=display, seniority=seniority, role=role)
            for mid, display, seniority, role in [
                ("m-mint", "มิ้น", "junior", "Junior Backend Developer"),
                ("m-somchai", "พี่สมชาย", "senior", "Senior Backend Developer"),
                ("m-wan", "พี่วรรณ", "lead", "Engineering Manager"),
                ("m-boat", "โบ๊ท", "mid", "Backend Developer"),
                ("m-fon", "ฝน", "junior", "QA Engineer"),
                ("m-ton", "ต้น", "mid", "DevOps Engineer")]]


@pytest.fixture
def pipeline_mock(monkeypatch):
    async def run_pipeline(text, author_id, roster, **kwargs):
        friday = any(marker in text.lower() for marker in ("ศุกร์", "friday", "cut-off"))
        situation = "มีงานด่วนช่วงเย็นวันศุกร์" if friday else "PR รอ review หลายวัน"
        return PipelineResult(ok=True, final_text=situation,
                              structured=StructuredFeedback(situation=situation, impact="กระทบการวางแผนงาน", request="กำหนดข้อตกลงทีมที่ชัดเจน"),
                              theme_slug="friday-urgent-work" if friday else "pr-review-delay",
                              theme_label="งานด่วนเย็นวันศุกร์" if friday else "PR review ล่าช้า",
                              attacker_rounds=[AttackerGuess(round=1, guessed_member_id=None, confidence=.1, identified=False)],
                              steps=[PipelineStep(step=3, name="ทดสอบผู้โจมตี", output="ผ่าน")])
    try:
        from app.privacy import pipeline
    except ImportError:
        pipeline = types.ModuleType("app.privacy.pipeline")
        pipeline.demo_roster = fallback_roster
        monkeypatch.setitem(sys.modules, "app.privacy.pipeline", pipeline)
    monkeypatch.setattr(pipeline, "run_pipeline", run_pipeline, raising=False)
    try:
        from app.privacy.gate import KGate  # noqa: F401
    except ImportError:
        gate = types.ModuleType("app.privacy.gate")

        class KGate:
            def __init__(self, redis, k):
                self.redis, self.k = redis, k
            def add(self, team_id, slug, item_id):
                self.redis.sadd(f"privacy:gate:{team_id}:{slug}", item_id)
            def count(self, team_id, slug):
                return self.redis.scard(f"privacy:gate:{team_id}:{slug}")
            def is_open(self, team_id, slug):
                return self.count(team_id, slug) >= self.k
            @staticmethod
            def count_range(n):
                return "3–5 คน" if 3 <= n <= 5 else "รอสมาชิกเพิ่มเติม" if n < 3 else "6–10 คน"
        gate.KGate = KGate
        monkeypatch.setitem(sys.modules, "app.privacy.gate", gate)
    return pipeline


@pytest.fixture
def backend_client(backend_settings, pipeline_mock, monkeypatch):
    from app import llm
    from app.main import create_app

    async def no_network(*args, **kwargs):
        raise AssertionError("Offline test attempted an LLM request")
    monkeypatch.setattr(llm, "chat", no_network)
    monkeypatch.setattr(llm, "chat_json", no_network)
    app = create_app(database_url="sqlite:///:memory:", redis=fakeredis.FakeRedis(decode_responses=True), background=False)
    with TestClient(app) as client:
        yield client
