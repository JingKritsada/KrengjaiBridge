# Spec: team GPU LLM endpoint (secondary backend)

> **สรุปภาษาไทย:** เครื่อง GPU ของเพื่อนในทีมรัน LM Studio เป็น LLM สำรองของ server บน Huawei Cloud
> เมื่อ endpoint ของคอร์สใช้ไม่ได้ ตารางด้านล่างคือสิ่งที่เครื่องนี้ต้องทำให้ครบจนจบการตัดสิน

## Update 2026-10-19 (evening) — host moved to LM Studio

The team switched the secondary backend to **LM Studio** at `https://noboru-2.tanuki-hops.ts.net` (Tailscale Funnel, public HTTPS, LM Studio API token).
The app uses it as the **secondary** backend; the course endpoint stays primary:

```
LLM_FALLBACK_BASE_URL=https://noboru-2.tanuki-hops.ts.net
LLM_FALLBACK_API_KEY=<LM Studio token>
LLM_FALLBACK_MODEL=qwen/qwen3.5-9b
LLM_FALLBACK_API_STYLE=lmstudio      # POST /v1/chat/completions with "reasoning_effort": "none"
```

- **Funnel is public**, so the ECS reaches it directly; the ECS does not join the tailnet.
- **Verified from the ECS:**
  - full privacy pipeline runs with no fallback
  - ~20–30 s per feedback
  - two parallel requests take the same time as one

Remaining asks for the LM Studio host:

| ID | Ask | Why |
|---|---|---|
| L1 | Keep `qwen/qwen3.5-9b` loaded: turn off JIT auto-unload / idle TTL for this model | The first request after an unload is slow during a live demo |
| L2 | Load it with context length **8192** (today 4096) | Evaluation prompts with a 20-person roster need ~3–4k tokens plus output |
| L3 | Max concurrent predictions ≥ 2 | The demo runs two teammates' pipelines at once |
| L4 | Start the LM Studio server at login. Keep the PC awake and Funnel on during judging | Availability |
| L5 | Turn off request/response logging in LM Studio's developer logs, or clear them after the demo | Prompts contain workplace feedback |
| L6 | Rotate the API token after the competition (it was shared in chat). Use a separate token for the ECS if LM Studio allows | The Funnel URL is public; the token is the only lock |
| L7 | (Optional) `qwen/qwen3.8-27b` if VRAM allows it fully on GPU | Better Thai quality; tell the team before switching, it changes measurements |
