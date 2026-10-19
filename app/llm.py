"""Chat client with ordered failover across OpenAI-compatible, Ollama and LM Studio endpoints.

Primary: course LiteLLM proxy (or Huawei Cloud MaaS). Secondary (optional): the team GPU box.
A backend that fails is cooled down for a while so later requests do not wait on it again;
when every backend is down the caller gets LLMError and the privacy steps use local fallbacks.
"""

import json
import re
from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx

from app.config import get_settings

_JSON_BLOCK = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)
_cooldown_until: dict[str, float] = {}
_last_error: dict[
    str, str
] = {}  # status code or exception type only, never request/response content
_last_backend: str | None = None
# Quota/auth failures do not heal on their own; transient errors get a short pause.
_PERSISTENT_STATUS = {401, 402, 403, 404, 422}


class LLMError(RuntimeError):
    status: int


class LLMOutputError(LLMError):
    """The model answered but not in the expected shape; the endpoint itself is fine."""


# Anything a privacy step may hit from a failed call or an unusable reply (small models break JSON).
FALLBACK_ERRORS = (LLMError, ValueError, TypeError, KeyError)


def fallback_note(error: Exception) -> str:
    if isinstance(error, LLMError) and not isinstance(error, LLMOutputError):
        return "โหมดสำรอง: LLM ไม่พร้อมใช้งาน"
    return "โหมดสำรอง: ผลจาก LLM ใช้ไม่ได้"


@dataclass(frozen=True)
class Backend:
    name: str
    base_url: str
    api_key: str
    model: str
    style: str  # openai | ollama | lmstudio


def _style(style: str, base_url: str) -> str:
    if style != "auto":
        return style
    return "ollama" if ":11434" in base_url else "openai"


def backends() -> list[Backend]:
    s = get_settings()
    found = [
        Backend(
            "primary",
            s.llm_base_url.rstrip("/"),
            s.llm_api_key,
            s.llm_model,
            _style(s.llm_api_style, s.llm_base_url),
        )
    ]
    if s.llm_fallback_base_url:
        found.append(
            Backend(
                "secondary",
                s.llm_fallback_base_url.rstrip("/"),
                s.llm_fallback_api_key,
                s.llm_fallback_model or s.llm_model,
                _style(s.llm_fallback_api_style, s.llm_fallback_base_url),
            )
        )
    return found


def is_available() -> bool:
    """True when at least one backend is not cooling down (no network request)."""
    now = monotonic()
    return any(_cooldown_until.get(b.name, 0) <= now for b in backends())


def status() -> dict[str, Any]:
    now = monotonic()
    return {
        "last_backend": _last_backend,
        "backends": [
            {
                "name": b.name,
                "model": b.model,
                "style": b.style,
                "cooldown_s": max(0, round(_cooldown_until.get(b.name, 0) - now)),
                "last_error": _last_error.get(b.name),
            }
            for b in backends()
        ],
    }


def _request(b: Backend, messages, temperature, max_tokens) -> tuple[str, dict[str, Any]]:
    if b.style == "ollama":
        # Native Ollama API: the only reliable way to switch Qwen3.x thinking off there.
        return f"{b.base_url.removesuffix('/v1')}/api/chat", {
            "model": b.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
    body: dict[str, Any] = {
        "model": b.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if b.style == "lmstudio":
        # LM Studio OpenAI-compatible endpoint: reasoning_effort "none" turns thinking off.
        body["reasoning_effort"] = "none"
        base = b.base_url if b.base_url.endswith("/v1") else f"{b.base_url}/v1"
        return f"{base}/chat/completions", body
    # Qwen3.x on vLLM/LiteLLM: skip the reasoning phase.
    body["chat_template_kwargs"] = {"enable_thinking": False}
    return f"{b.base_url}/chat/completions", body


async def _call(b: Backend, messages, temperature, max_tokens) -> str:
    """One backend with a single retry on transient errors. Raises LLMError with a status hint."""
    s = get_settings()
    url, body = _request(b, messages, temperature, max_tokens)
    headers = {"Authorization": f"Bearer {b.api_key}"} if b.api_key else {}
    async with httpx.AsyncClient(timeout=s.llm_timeout_s) as client:
        for attempt in range(2):
            try:
                r = await client.post(url, json=body, headers=headers)
            except httpx.TransportError as e:
                if attempt == 1:
                    raise LLMError(f"{b.name}: {type(e).__name__}") from e
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                continue
            if r.status_code != 200:
                error = LLMError(f"{b.name}: HTTP {r.status_code}")
                error.status = r.status_code
                raise error
            data = r.json()
            message = data["message"] if b.style == "ollama" else data["choices"][0]["message"]
            return (message.get("content") or "").strip()
    raise LLMError(f"{b.name}: unreachable")


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 800,
) -> str:
    """Return the assistant text from the first healthy backend. Thinking is disabled."""
    global _last_backend
    s = get_settings()
    failures = []
    for b in backends():
        if _cooldown_until.get(b.name, 0) > monotonic():
            failures.append(f"{b.name}: cooling down")
            continue
        try:
            text = await _call(b, messages, temperature, max_tokens)
        except LLMError as e:
            long = getattr(e, "status", None) in _PERSISTENT_STATUS
            _cooldown_until[b.name] = monotonic() + (
                s.llm_cooldown_long_s if long else s.llm_cooldown_s
            )
            _last_error[b.name] = str(e)
            failures.append(str(e))
            continue
        _last_backend = b.name
        return text
    raise LLMError("all LLM backends failed: " + "; ".join(failures))


async def chat_json(messages: list[dict[str, str]], **kw: Any) -> Any:
    """Ask for JSON and parse the first JSON object/array in the reply."""
    text = await chat(messages, **kw)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if not m:
            raise LLMOutputError("no JSON object in reply") from None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise LLMOutputError("malformed JSON in reply") from e
