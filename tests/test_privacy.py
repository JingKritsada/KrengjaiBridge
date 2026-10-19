import asyncio
import json

import fakeredis
import pytest

from app import llm
from app.contracts import MemberProfile
from app.privacy import identifiers
from app.privacy.attacker import guess_author
from app.privacy.cluster import assign_theme, cluster_offline
from app.privacy.gate import KGate, count_range
from app.privacy.neutralize import leak_markers, neutralize
from app.privacy.pipeline import demo_roster, run_pipeline
from app.privacy.structure import structure

DEMO_TEXT = "หนูไม่กล้าบอกพี่หัวหน้าค่ะ ว่าสั่งงานเย็นวันศุกร์ทำให้หนูต้องยกเลิกนัดตลอด"
NEUTRAL_TEXT = "มีการมอบหมายงานด่วนเย็นวันศุกร์ ทำให้ต้องเปลี่ยนแผนส่วนตัว ควรวางแผนงานล่วงหน้า"
LOCAL_NER = identifiers._local_ner


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def no_network(*args, **kwargs):
        raise AssertionError("An offline test attempted an LLM call")

    monkeypatch.setattr(llm, "chat", no_network)
    monkeypatch.setattr(llm, "chat_json", no_network)
    monkeypatch.setattr(identifiers, "_local_ner", lambda: None)


@pytest.mark.parametrize("particle", [
    "ครับ", "ค่ะ", "คะ", "นะคะ", "จ้ะ", "คับ", "ค้าบ", "งับ", "ฮะ", "ค่า",
    "จ้า", "นะครับ", "เจ้าค่ะ", "ครับผม",
])
def test_particles(particle):
    assert neutralize("ช่วยวางแผนงานล่วงหน้า" + particle) == "ช่วยวางแผนงานล่วงหน้า"


@pytest.mark.parametrize("pronoun", ["ผม", "ดิฉัน", "หนู", "กระผม", "ฉัน", "เค้า"])
def test_pronouns(pronoun):
    result = neutralize(pronoun + "ต้องยกเลิกนัดค่ะ")
    assert result == "ผู้ให้ความเห็นต้องยกเลิกนัด"
    assert leak_markers(result) == []


@pytest.mark.parametrize("sentence", [
    DEMO_TEXT,
    "ผมอยากให้รีวิว PR เร็วขึ้นครับ",
    "ดิฉันขอให้ประชุมสั้นลงค่ะ",
    "กระผมติดงานด่วนคับ",
    "หนูทำงานจนดึกนะคะ",
    "เค้าอยากขอเวลาทดสอบเพิ่มจ้ะ",
    "ฉันต้องเข้าเวรทุกคืนค้าบ",
    "ขอ requirement ที่ชัดเจนงับ",
    "พี่สมชายช่วยรีวิวให้น้องมิ้นด้วยครับ",
    "ช่วยลดประชุมด้วยคะ",
    "หนูขอเลื่อนส่งงานเจ้าค่ะ",
    "ผมติดงานค่าใช้จ่ายนะครับ",
    "ค่าใช้จ่ายสูง คะแนนลดลง คณะกรรมการต้องทบทวน",
    "ห้องทำงานคับแคบมากค่ะ",
])
def test_no_markers_after_cleanup(sentence):
    cleaned = neutralize(sentence)
    assert cleaned
    assert leak_markers(cleaned) == []
    assert neutralize(cleaned) == cleaned


def test_lexical_words_and_grammatical_content_preserved():
    assert neutralize("ค่าใช้จ่าย คะแนน คณะ คับแคบ") == "ค่าใช้จ่าย คะแนน คณะ คับแคบ"
    assert neutralize("ผมต้องยกเลิกนัดครับ") == "ผู้ให้ความเห็นต้องยกเลิกนัด"
    assert leak_markers("หนูขอให้พี่ช่วยค่ะ") == ["หนู", "พี่", "ค่ะ"]


def test_demo_roster():
    roster = demo_roster()
    assert len(roster) == len({m.member_id for m in roster}) == 6
    assert all(len(m.style_samples) == 3 for m in roster)
    assert {m.member_id for m in roster} == {"m-mint", "m-somchai", "m-wan", "m-boat", "m-fon", "m-ton"}


def test_identifier_exact_fuzzy_and_non_identifier_words():
    roster = [MemberProfile(member_id="x", display_name="สมชาย", nicknames=["มิ้น"])]
    cleaned = identifiers.scrub_roster("พี่สมชายกับมิ้นและสมชายนัดกัน วันที่ 19/10/2026", roster)
    assert "สมชาย" not in cleaned and "มิ้น" not in cleaned and "19/10/2026" not in cleaned
    fuzzy = identifiers.scrub_roster("สมชาน ฝากงานไว้", roster)
    assert "สมชาน" not in fuzzy
    assert identifiers.scrub_roster("เริ่มต้นงานใหม่", demo_roster()) == "เริ่มต้นงานใหม่"


def test_identifier_ner_failure_and_llm_pass(monkeypatch):
    class BrokenNER:
        def tag(self, text):
            raise OSError("model unavailable")

    monkeypatch.setattr(identifiers, "_local_ner", lambda: BrokenNER())
    sent = []

    async def mock_json(messages, **kwargs):
        sent.append(messages[-1]["content"])
        return {"text": "มีการมอบหมายงานเฉพาะในการประชุม ทำให้งานล่าช้า"}

    monkeypatch.setattr(llm, "chat_json", mock_json)
    raw = "พี่สมชายสั่งโครงการ Unicorn วันที่ 19/10/2026 ในประชุมที่มีแค่ผมกับพี่"
    result = asyncio.run(identifiers.remove_identifiers(raw, demo_roster()))
    assert "สมชาย" not in sent[0]
    assert "Unicorn" not in result and "19/10/2026" not in result
    assert "แค่ผมกับพี่" not in result


def test_missing_ner_model_never_attempts_download(monkeypatch):
    import pythainlp.corpus
    import pythainlp.tag

    attempted = []

    def forbidden(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("NER attempted an automatic download")

    LOCAL_NER.cache_clear()
    monkeypatch.setattr(pythainlp.corpus, "get_corpus_default_db", lambda *a, **kw: None)
    monkeypatch.setattr(pythainlp.corpus, "get_corpus_db_detail", lambda *a, **kw: {})
    monkeypatch.setattr(pythainlp.corpus, "get_corpus_path", forbidden)
    monkeypatch.setattr(pythainlp.tag, "NER", forbidden)
    assert LOCAL_NER() is None
    assert not attempted
    LOCAL_NER.cache_clear()


@pytest.mark.parametrize("confidence,guessed,expected", [
    (0.5, "m-mint", True), (0.49, "m-mint", False), (0.99, "m-boat", False), (1 / 6, None, False),
])
def test_attacker_threshold(monkeypatch, confidence, guessed, expected):
    async def mock_json(messages, **kwargs):
        assert "author_id" not in messages[-1]["content"]
        return {"guessed_member_id": guessed, "confidence": confidence, "reason": "รูปแบบภาษา"}

    monkeypatch.setattr(llm, "chat_json", mock_json)
    result = asyncio.run(guess_author(NEUTRAL_TEXT, demo_roster(), author_id="m-mint", round=2))
    assert result.identified is expected
    assert result.round == 2


def test_small_roster_threshold(monkeypatch):
    async def mock_json(*args, **kwargs):
        return {"guessed_member_id": "m-mint", "confidence": 0.8}

    monkeypatch.setattr(llm, "chat_json", mock_json)
    assert not asyncio.run(guess_author(NEUTRAL_TEXT, demo_roster()[:2], author_id="m-mint")).identified


def fake_pipeline_llm(monkeypatch, *, identified_rounds=0, malformed=False):
    calls = []
    attacks = []

    async def mock_json(messages, **kwargs):
        prompt = messages[0]["content"]
        calls.append(prompt)
        if "You anonymize" in prompt:
            return {"text": "หนูได้รับงานด่วนเย็นวันศุกร์ค่ะ ทำให้ต้องยกเลิกนัด"}
        if "Rewrite feedback" in prompt:
            return {"text": NEUTRAL_TEXT + "ครับ"}
        if "privacy attacker" in prompt:
            attacks.append(json.loads(messages[-1]["content"])["feedback"])
            assert leak_markers(attacks[-1]) == []
            return {"guessed_member_id": "m-mint", "confidence": 0.9 if len(attacks) <= identified_rounds else 0.2}
        if malformed:
            return {"situation": None}
        return {
            "situation": "มีงานด่วนเย็นวันศุกร์ครับ", "impact": "กระทบแผนส่วนตัวค่ะ",
            "request": "ขอให้วางแผนงานล่วงหน้านะคะ", "theme_slug": "friday-urgent-work",
            "theme_label": "งานด่วนเย็นวันศุกร์ครับ",
        }

    monkeypatch.setattr(llm, "chat_json", mock_json)
    return calls, attacks


def test_pipeline_six_step_trace_and_call_budget(monkeypatch):
    calls, attacks = fake_pipeline_llm(monkeypatch, identified_rounds=1)
    result = asyncio.run(run_pipeline(DEMO_TEXT, "m-mint", demo_roster()))
    assert result.ok
    assert result.theme_slug == "friday-urgent-work"
    assert result.theme_label == "งานด่วนเย็นวันศุกร์"
    assert [step.step for step in result.steps] == [1, 2, 3, 4, 5, 6]
    assert result.steps[4].output == "รอประตู k"
    assert DEMO_TEXT not in result.model_dump_json()
    assert len(attacks) == 2
    assert len(calls) == 2 + 2 * len(attacks)
    assert [g.identified for g in result.attacker_rounds] == [True, False]
    assert leak_markers(result.final_text) == []
    assert all(not leak_markers(value) for value in result.structured.model_dump().values())


def test_pipeline_trace_step_one_never_has_names(monkeypatch):
    fake_pipeline_llm(monkeypatch)
    result = asyncio.run(run_pipeline("พี่สมชายสั่งงานให้มิ้นค่ะ", "m-mint", demo_roster()))
    assert result.ok
    assert "สมชาย" not in result.steps[0].output
    assert "มิ้น" not in result.steps[0].output


def test_pipeline_attacker_exhaustion_blocks(monkeypatch):
    calls, attacks = fake_pipeline_llm(monkeypatch, identified_rounds=10)
    result = asyncio.run(run_pipeline(DEMO_TEXT, "m-mint", demo_roster(), max_rounds=2))
    assert not result.ok and result.reason_blocked
    assert len(attacks) == 2 and len(calls) == 5
    assert result.final_text == "" and result.structured is None
    assert all(guess.identified for guess in result.attacker_rounds)


def test_pipeline_invalid_model_response_blocks(monkeypatch):
    fake_pipeline_llm(monkeypatch, malformed=True)
    result = asyncio.run(run_pipeline(DEMO_TEXT, "m-mint", demo_roster()))
    assert not result.ok and result.reason_blocked
    assert result.structured is None and result.final_text == ""


def test_pipeline_llm_error_does_not_echo_source(monkeypatch):
    async def broken(*args, **kwargs):
        raise llm.LLMError(DEMO_TEXT)

    monkeypatch.setattr(llm, "chat_json", broken)
    result = asyncio.run(run_pipeline(DEMO_TEXT, "m-mint", demo_roster()))
    assert not result.ok and result.steps == []
    assert DEMO_TEXT not in result.model_dump_json()


@pytest.mark.parametrize("kwargs", [{"max_rounds": 0}, {"author_id": "unknown"}, {"roster": []}, {"text": " "}])
def test_pipeline_invalid_inputs_do_not_call_llm(kwargs):
    args = {"text": DEMO_TEXT, "author_id": "m-mint", "roster": demo_roster(), **kwargs}
    assert not asyncio.run(run_pipeline(**args)).ok


def test_standalone_structure_neutralizes(monkeypatch):
    fake_pipeline_llm(monkeypatch)
    result = asyncio.run(structure(NEUTRAL_TEXT))
    assert all(not leak_markers(value) for value in result.model_dump().values())


def test_assign_theme_reuses_existing_label(monkeypatch):
    async def mock_json(messages, **kwargs):
        assert "release-process" in messages[-1]["content"]
        return {"theme_slug": "release-process", "theme_label": "ชื่อใหม่ครับ"}

    monkeypatch.setattr(llm, "chat_json", mock_json)
    assert asyncio.run(assign_theme("ขั้นตอนปล่อยระบบ", [("release-process", "ขั้นตอนปล่อยระบบ")])) == (
        "release-process", "ขั้นตอนปล่อยระบบ",
    )


def test_gate_count_threshold_deduplication_and_isolation():
    gate = KGate(fakeredis.FakeRedis(), k=3)
    assert gate.count("team", "theme") == 0
    assert gate.add("team", "theme", "a") == 1
    assert gate.add("team", "theme", "a") == 1
    assert not gate.is_open("team", "theme")
    assert gate.add("team", "theme", "b") == 2
    assert not gate.is_open("team", "theme")
    assert gate.add("team", "theme", "c") == 3
    assert gate.is_open("team", "theme")
    assert gate.count("other-team", "theme") == 0
    assert gate.count("team", "other-theme") == 0
    assert gate.count_range(3) == "3–5 คน"
    assert "1" not in gate.count_range(1)
    assert gate.count_range(1) == gate.count_range(2)
    assert count_range(5) == "3–5 คน"
    assert count_range(6) == "6–10 คน"
    assert all(0 <= gate.release_delay() <= 20 for _ in range(30))
    assert KGate(fakeredis.FakeRedis(), max_delay_s=0).release_delay() == 0


def test_cluster_offline_two_obvious_themes():
    texts = [
        "มีงานด่วนเข้ามาเย็นวันศุกร์ทุกสัปดาห์",
        "งานด่วนเย็นวันศุกร์ทำให้ต้องยกเลิกนัด",
        "ขอให้งดมอบหมายงานด่วนเย็นวันศุกร์",
        "PR รอรีวิวนานหลายวัน งานล่าช้า",
        "ขอให้ช่วยรีวิว PR เร็วขึ้น เพราะรอนาน",
        "การรีวิว PR ล่าช้าหลายวัน ทำให้งานสะสม",
    ]
    labels = cluster_offline(texts)
    assert len(set(labels)) == 2
    assert len(set(labels[:3])) == len(set(labels[3:])) == 1
    assert labels[0] != labels[3]
    assert cluster_offline([]) == []
    assert cluster_offline(["หนึ่งข้อความ"]) == [0]
    assert cluster_offline(["", " "]) == [0, 1]
