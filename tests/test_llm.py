"""LLM client wire formats and failover (no real network: respx intercepts httpx)."""

import json

import httpx
import pytest
import respx

from app import llm
from app.config import get_settings


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(llm, "_cooldown_until", {})
    for name, value in {
        "llm_base_url": "https://proxy.example/v1",
        "llm_api_key": "k",
        "llm_model": "qwen3.5",
        "llm_api_style": "auto",
        "llm_fallback_base_url": "",
        "llm_fallback_api_key": "",
        "llm_fallback_model": "",
        "llm_fallback_api_style": "auto",
    }.items():
        monkeypatch.setattr(s, name, value)
    return s


def ok(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_openai_format_by_default(settings):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://proxy.example/v1/chat/completions").mock(return_value=ok("ok"))
        assert await llm.chat([{"role": "user", "content": "hi"}]) == "ok"
    body = json.loads(route.calls[0].request.content)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


async def test_native_ollama_api(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "http://gpu-box:11434/v1")
    monkeypatch.setattr(settings, "llm_api_key", "")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://gpu-box:11434/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"role": "assistant", "content": " สวัสดี "}}
            )
        )
        assert await llm.chat([{"role": "user", "content": "hi"}]) == "สวัสดี"
    sent = route.calls[0].request
    body = json.loads(sent.content)
    assert body["think"] is False and body["stream"] is False
    assert "authorization" not in sent.headers


async def test_failover_to_lmstudio_and_cooldown(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_base_url", "https://gpu.example")
    monkeypatch.setattr(settings, "llm_fallback_api_key", "sk-lm")
    monkeypatch.setattr(settings, "llm_fallback_model", "qwen/qwen3.5-9b")
    monkeypatch.setattr(settings, "llm_fallback_api_style", "lmstudio")
    with respx.mock(assert_all_called=True) as mock:
        primary = mock.post("https://proxy.example/v1/chat/completions").mock(
            return_value=httpx.Response(422, json={"error": "Budget has been exceeded"})
        )
        secondary = mock.post("https://gpu.example/v1/chat/completions").mock(
            return_value=ok("จาก GPU")
        )
        assert await llm.chat([{"role": "user", "content": "hi"}]) == "จาก GPU"
        assert await llm.chat([{"role": "user", "content": "hi"}]) == "จาก GPU"
    assert (
        primary.call_count == 1
    )  # quota error: primary cooled down, second call goes straight to GPU
    body = json.loads(secondary.calls[0].request.content)
    assert body["reasoning_effort"] == "none" and body["model"] == "qwen/qwen3.5-9b"
    assert secondary.calls[0].request.headers["authorization"] == "Bearer sk-lm"
    assert llm.status()["last_backend"] == "secondary" and llm.is_available()


async def test_all_backends_down_raises_fast(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_base_url", "https://gpu.example")
    monkeypatch.setattr(settings, "llm_fallback_api_style", "lmstudio")
    with respx.mock() as mock:
        mock.post("https://proxy.example/v1/chat/completions").mock(
            return_value=httpx.Response(503)
        )
        gpu = mock.post("https://gpu.example/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("down")
        )
        with pytest.raises(llm.LLMError):
            await llm.chat([{"role": "user", "content": "hi"}])
        assert not llm.is_available()
        with pytest.raises(llm.LLMError, match="cooling down"):
            await llm.chat([{"role": "user", "content": "hi"}])
        assert gpu.call_count == 2  # one retry, then cooled down: the next call makes no request
