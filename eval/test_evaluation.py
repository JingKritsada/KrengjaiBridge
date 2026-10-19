"""Offline checks for split leakage and the evaluation-only LLM cache/limiter."""

import asyncio
import json

import pytest

import run_all as evaluation


def test_split_keeps_all_themes_in_train_and_no_test_samples_in_roster():
    cards = evaluation.persona_cards()
    rows = [{"persona_id": c["persona_id"], "gender": c["gender"], "seniority": c["seniority"],
             "theme": theme, "text": f"{c['persona_id']} {theme} distinct {i}"}
            for c in cards for theme, _ in evaluation.cluster.SEED_THEMES for i in range(2)]
    evaluation.validate_dataset(cards, rows)
    train, test = evaluation.split_dataset(cards, rows)
    roster = evaluation.make_roster(cards, train)
    heldout = {r["text"] for r in test}
    assert all(len(member.style_samples) == 3 and not heldout.intersection(member.style_samples)
               for member in roster)
    assert max(evaluation.Counter(r["theme"] for r in test).values()) - min(
        evaluation.Counter(r["theme"] for r in test).values()) <= 2


@pytest.mark.asyncio
async def test_cache_retries_bad_json_and_limits_network_concurrency(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, "CACHE", tmp_path)
    cached = evaluation.CachedLLM()
    active = peak = 0

    async def response(messages, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.001)
        active -= 1
        if messages[0]["content"] == "bad-json" and len(messages) == 1:
            return '{"text":"unescaped\nnewline"}'
        return '{"text":"valid"}'

    cached.original = response
    monkeypatch.setattr(evaluation.llm, "chat", cached.chat)
    monkeypatch.setattr(evaluation.llm, "chat_json", cached.chat_json)
    messages = [[{"role": "user", "content": str(i)}] for i in range(12)]
    await asyncio.gather(*(evaluation.llm.chat_json(m) for m in messages))
    assert peak == 4 and cached.calls == 12
    await evaluation.llm.chat_json(messages[0])
    assert cached.calls == 12 and cached.hits == 1
    assert await evaluation.llm.chat_json([{"role": "user", "content": "bad-json"}]) == {"text": "valid"}
    assert cached.retries == 1
    assert len(list(tmp_path.glob("*.json"))) == 14  # Includes the malformed raw response.
    assert all("request" in json.loads(p.read_text()) for p in tmp_path.glob("*.json"))
