# Spec: team GPU LLM endpoint + Tailscale access for the ECS

> **สรุปภาษาไทย (สำหรับคน):** เอกสารนี้เขียนให้ AI agent หรือเพื่อนในทีมทำตามได้ทันที
> มี 3 ส่วน:
> - **R** = สิ่งที่ต้องตั้งบนเครื่อง GPU
> - **T** = สิ่งที่ต้องตั้งใน Tailscale เพื่อให้ server บน Huawei Cloud (ECS) เรียกเครื่องนี้ได้
> - **A** = ชุดทดสอบที่ต้องผ่าน
>
> ทำเสร็จแล้วส่งของตามหัวข้อ "Deliverables" กลับมา

## Update 2026-10-19 (evening) — host moved to LM Studio

The team switched the secondary backend to **LM Studio** at `https://noboru-2.tanuki-hops.ts.net` (Tailscale Funnel, public HTTPS, LM Studio API token).
The app uses it as the **secondary** backend; the course endpoint stays primary:

```
LLM_FALLBACK_BASE_URL=https://noboru-2.tanuki-hops.ts.net
LLM_FALLBACK_API_KEY=<LM Studio token>
LLM_FALLBACK_MODEL=qwen/qwen3.5-9b
LLM_FALLBACK_API_STYLE=lmstudio      # POST /v1/chat/completions with "reasoning_effort": "none"
```

- **Funnel is public**, so the ECS reaches it directly. Section T (tailnet for the ECS) is no longer needed.
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

The original Ollama-based spec below is kept for reference.

## Context

- **App:** Kreng-jai Bridge, a FastAPI service running on a Huawei Cloud ECS in Hong Kong (Ubuntu 24.04, Docker).
- **What it calls the LLM for:** Thai text, short calls (≤ 800 output tokens):
  - identifier removal
  - neutral rewrite
  - an "attacker" that guesses the author
  - structuring
  - theme labels
  - manager proposals
- **Load:**
  - Live demo: ~5 sequential calls per user action, low traffic.
  - Offline evaluation run: ~700 calls, up to 4 in parallel.
- **Fallback:** when the endpoint fails or answers in a broken shape, the app falls back to local rules. The demo never hard-fails, but quality drops and the UI shows a "fallback mode" badge.
- **Current host:** `desktop-5tspfst` (Windows, RTX 4050), Tailscale IP `100.112.31.104`.
- **Current serving stack:** Ollama behind an API-key proxy on port `8787`. It exposes `/api/chat`, `/api/generate`, `/api/tags`, `/v1/chat/completions` and `/v1/models`, with Swagger at `/docs`.
- **Status verified on 2026-10-19 from a tailnet Mac:**
  - Reachable.
  - `qwen3.5:4b` listed.
  - `think:false` works.
  - ~1 s per short reply (warm).

## App configuration that will use this endpoint (FYI)

```
LLM_BASE_URL=http://100.112.31.104:8787
LLM_API_STYLE=ollama
LLM_MODEL=qwen3.5:4b
LLM_API_KEY=<dedicated key for the ECS, see R2>
```

Request the app sends: `POST /api/chat`, header `Authorization: Bearer <key>`, body:

```json
{"model": "qwen3.5:4b", "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
 "stream": false, "think": false, "options": {"temperature": 0.2, "num_predict": 650}}
```

- **Reads:** `response.message.content`. Most prompts ask for a single JSON object.
- **Client timeout:** 60 s.
- **Retries:** up to 3 attempts on network errors and HTTP 429/500/502/503/504.

## R — GPU host requirements

| ID | Requirement | Target / how | Status |
|---|---|---|---|
| R1 | Listen on the Tailscale interface only | Port 8787 reachable at `100.112.31.104`; Windows Firewall inbound TCP 8787 allowed **only** on the Tailscale adapter; no router port-forward; never exposed to the public internet | reachable from tailnet ✔ (public exposure: please confirm) |
| R2 | Dedicated API key for the ECS | Issue a separate key labelled `kjb-ecs` so it can be revoked alone. The key shared in chat on 2026-10-19 must be rotated after the competition | todo |
| R3 | Native Ollama chat API passes `think` through | `POST /api/chat` with `"think": false` → `message.content` holds the answer, `message.thinking` empty or absent, no `<think>` tags in content | ✔ |
| R4 | Stable model tag | Serve `qwen3.5:4b`. RTX 4050 (6 GB VRAM) cannot hold `qwen3.5:9b` (~6.6 GB) fully on GPU, so keep 4b. Do not replace the model behind the same tag without telling the team (it invalidates measurements) | ✔ |
| R5 | Context window ≥ 8192 tokens | Ollama default is 4096. Set system env `OLLAMA_CONTEXT_LENGTH=8192` and restart Ollama. The evaluation prompts carry a 20-person roster (~3–4k tokens). If VRAM overflows, report the largest value that stays 100% on GPU (`ollama ps` → PROCESSOR column shows `100% GPU`) | todo |
| R6 | No cold starts during demos/judging | Set `OLLAMA_KEEP_ALIVE=-1` (never unload) for the judging window. Today the model unloads after ~5 min idle | todo |
| R7 | Parallel requests queue instead of failing | `OLLAMA_NUM_PARALLEL=2` (raise to 4 if VRAM allows at ctx 8192). The proxy must queue or pass through; never return 429 for ≤ 4 concurrent requests from `kjb-ecs` | todo |
| R8 | Availability window | From 2026-10-20 until judging ends (dates TBA). PC awake, set to never sleep. Ollama and the proxy auto-start at boot/login. Windows Update active hours cover the demo times. Tell the team before planned downtime | todo |
| R9 | Privacy: no body logging | The proxy must not log request or response bodies (they contain workplace feedback). Access logs with time, path, status, latency and key label only | please confirm |
| R10 | Throughput | ≥ 60 requests/min allowed for `kjb-ecs`. Warm latency ≤ 5 s for 300 output tokens (today ~55 tok/s ✔) | ✔ |

Windows commands for R5–R7 (PowerShell as the user who runs Ollama, then quit and reopen Ollama from the tray):

```powershell
setx OLLAMA_CONTEXT_LENGTH 8192
setx OLLAMA_KEEP_ALIVE -1
setx OLLAMA_NUM_PARALLEL 2
# after restarting Ollama:
ollama run qwen3.5:4b "hi" --think=false
ollama ps        # expect: qwen3.5:4b ... 100% GPU ... CONTEXT 8192 ... UNTIL Forever
```

## T — Tailscale access for the ECS

- **Goal:** the ECS joins a tailnet from which `desktop-5tspfst:8787` is reachable.
- **Today:** the desktop lives in tailnet `taildfbb56` (owner: Chitipat) and is shared into `jing.kritsada@gmail.com`'s tailnet.

| ID | Requirement | Detail |
|---|---|---|
| T1 | One auth key for the ECS | **Option A (recommended):** generated by `jing.kritsada@gmail.com` (the account the desktop is shared with). Settings → Keys → Generate auth key: Reusable **off**, Ephemeral **off**, Pre-approved **on**, **no tags**. Shared devices are reachable from devices owned by the recipient user, so a tagged node may not see the shared desktop. Expiry ≥ 30 days. **Option B:** generated in tailnet `taildfbb56` with tag `tag:kjb-ecs`; then T2 must grant that tag |
| T2 | ACL allows the ECS → desktop on port 8787 only | Option A: the sharer's (`taildfbb56`) policy must allow the share recipient to reach `desktop-5tspfst:8787` (the default allow-all policy already does). Option B: add `{"action":"accept","src":["tag:kjb-ecs"],"dst":["desktop-5tspfst:8787"]}` and nothing broader for that tag |
| T3 | Hand-over without chat | Put the key in `kreng-jai-bridge/.env.tailscale` as one line `TS_AUTHKEY=tskey-auth-...` on the orchestrator's Mac. Do not paste it in chat |
| T4 | No surprise expiry | After the ECS joins (machine name `kjb-ecs`), disable key expiry for `kjb-ecs`. Check that `desktop-5tspfst` key expiry is after the judging date (shown today: "in 3 months" ✔) |

The orchestrator then runs on the ECS:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --authkey "$TS_AUTHKEY" --hostname kjb-ecs
```

## A — Acceptance tests

Run A1–A5 from any tailnet device. A6 is run by the orchestrator after T1. `$KEY` = the `kjb-ecs` key.

```bash
H=http://100.112.31.104:8787
# A1 model listed
curl -s -H "Authorization: Bearer $KEY" $H/v1/models | jq -r '.data[].id' | grep -x 'qwen3.5:4b'
# A2 thinking off, fast, Thai answer
time curl -s -H "Authorization: Bearer $KEY" $H/api/chat -d '{"model":"qwen3.5:4b","stream":false,"think":false,
  "messages":[{"role":"user","content":"ตอบเป็น JSON {\"text\":\"...\"}: สรุปว่า PR รอรีวิวนานทำให้งานช้า"}],
  "options":{"num_predict":200}}' | jq '{content: .message.content, thinking: (.message.thinking // "")}'
#    pass: content is JSON-like Thai, thinking empty, wall time < 5 s (warm)
# A3 JSON reliability: run A2 ten times, at least 9 replies parse with: jq -r .message.content | sed 's/```json//; s/```//g' | jq .
# A4 concurrency: 4 parallel A2 requests (e.g. `for i in 1 2 3 4; do (A2 &) ; done; wait`) all return 200 within 30 s
# A5 no cold start: wait 10 minutes idle, run A2 again, wall time < 5 s
# A6 (from the ECS) same as A1 using the Tailscale IP
```

## Deliverables (send back to the orchestrator)

1. Model tag(s) served. Current: `qwen3.5:4b`.
2. Effective settings from `ollama ps` and env: context length, `OLLAMA_NUM_PARALLEL`, `OLLAMA_KEEP_ALIVE`.
3. The `kjb-ecs` API key → into `kreng-jai-bridge/.env.gpu` as `GPU_LLM_KEY=...` (file, not chat).
4. The Tailscale auth key → `kreng-jai-bridge/.env.tailscale` (T3).
5. Confirmation of R1 (no public exposure) and R9 (no body logging).
6. Availability window, plus a phone/LINE contact for restarting the PC or Ollama during judging.
7. A1–A5 results (paste outputs; they contain no secrets).
