"""Thin client for an OpenAI-compatible chat endpoint (LiteLLM proxy or Huawei Cloud MaaS)."""

import json
import re
from time import monotonic
from typing import Any

import httpx

from app.config import get_settings

_JSON_BLOCK = re.compile(r"\{.*\}|\[.*\]", re.S)
_last_error_at: float | None = None


def is_available() -> bool:
    """Report recent failures without making a network request."""
    return _last_error_at is None or monotonic() - _last_error_at >= 60


class LLMError(RuntimeError):
    def __init__(self, *args):
        global _last_error_at
        _last_error_at = monotonic()
        super().__init__(*args)


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 800,
) -> str:
    """Return the assistant text. Thinking is disabled so answers come back fast."""
    s = get_settings()
    body: dict[str, Any] = {
        "model": s.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Qwen3.x on vLLM/LiteLLM: skip the reasoning phase.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Authorization": f"Bearer {s.llm_api_key}"}
    async with httpx.AsyncClient(timeout=s.llm_timeout_s) as client:
        for attempt in range(3):
            try:
                r = await client.post(f"{s.llm_base_url}/chat/completions", json=body, headers=headers)
            except httpx.TransportError as e:
                if attempt == 2:
                    raise LLMError(str(e)) from e
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                continue
            if r.status_code != 200:
                raise LLMError(f"{r.status_code}: {r.text[:300]}")
            content = r.json()["choices"][0]["message"].get("content") or ""
            return content.strip()
    raise LLMError("unreachable")


async def chat_json(messages: list[dict[str, str]], **kw: Any) -> Any:
    """Ask for JSON and parse the first JSON object/array in the reply."""
    text = await chat(messages, **kw)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if not m:
            raise LLMError(f"no JSON in reply: {text[:200]}")
        return json.loads(m.group(0))
