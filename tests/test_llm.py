"""LLM client wire format (no real network: respx intercepts httpx)."""

import json

import httpx
import respx

from app import llm
from app.config import get_settings


async def test_llm_chat_uses_native_ollama_api(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_base_url", "http://gpu-box:11434/v1")
    monkeypatch.setattr(settings, "llm_model", "qwen3.5:9b")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_api_style", "auto")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://gpu-box:11434/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"role": "assistant", "content": " สวัสดี "}}))
        assert await llm.chat([{"role": "user", "content": "hi"}]) == "สวัสดี"
    sent = route.calls[0].request
    body = json.loads(sent.content)
    assert body["think"] is False and body["stream"] is False and body["model"] == "qwen3.5:9b"
    assert "authorization" not in sent.headers


async def test_llm_chat_uses_openai_format_by_default(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_api_style", "auto")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://proxy.example/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))
        assert await llm.chat([{"role": "user", "content": "hi"}]) == "ok"
    body = json.loads(route.calls[0].request.content)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
