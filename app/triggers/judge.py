"""Reject known context decoys before asking an optional LLM context judge."""
import asyncio

from app import llm
from app.config import get_settings
from app.db import aware


def context_check(signal, events):
    labels = [str(x).lower() for x in signal.evidence.get("labels", [])]
    if signal.kind == "pr_stale" and any(x in ("wip", "draft", "work in progress") for x in labels):
        return False, "PR ยังเป็น WIP / draft จึงไม่เตือน"
    if signal.kind == "pr_stale":
        for e in events:
            if e.type == "leave" and e.actor_hash == signal.target_hash:
                start = aware(e.timestamp)
                end_value = e.meta.get("until") or e.meta.get("end")
                if end_value:
                    from datetime import datetime
                    end = aware(datetime.fromisoformat(end_value))
                else:
                    from datetime import timedelta
                    end = start + timedelta(days=float(e.meta.get("days", 1)))
                if start <= aware(signal.detected_at) <= end:
                    return False, "ผู้ review อยู่ระหว่างลา จึงยังไม่เตือน"
    return True, "ผ่านเกณฑ์และตรวจบริบท SDLC แล้ว"


async def judge_signal(signal, events):
    ok, reason = context_check(signal, events)
    if ok and get_settings().llm_judge_enabled and get_settings().llm_api_key:
        try:
            # The rules above already decided; the LLM may only refine it within a short budget.
            answer = await asyncio.wait_for(llm.chat_json([
                {"role": "system", "content": "Check this SDLC metadata signal. Return JSON {ok: boolean, reason: string in Thai}. Do not infer private conversations."},
                {"role": "user", "content": signal.model_dump_json()},
            ], max_tokens=200), timeout=get_settings().llm_judge_timeout_s)
            if isinstance(answer.get("ok"), bool):
                ok, reason = answer["ok"], str(answer.get("reason", reason))[:500]
        except (llm.LLMError, ValueError, TypeError, AttributeError, asyncio.TimeoutError):
            pass
    return signal.model_copy(update={"judge_ok": ok, "judge_reason": reason})
