# Kreng-jai Bridge — build contract

Demo build for Huawei ICT Competition 2026 (Innovation). Deadline: 2026-10-20.
Product: a proactive AI agent in LINE that (a) privately asks Thai team members about friction it detects
from SDLC metadata and sends neutral nudges on their behalf, and (b) turns their feedback into anonymous,
attacker-tested text that a manager sees only after k=3 people raise the same theme.

Stack: Python 3.12, FastAPI, SQLAlchemy 2 (SQLite local / RDS PostgreSQL cloud), Redis (fakeredis local /
DCS cloud), LINE Messaging API (`line-bot-sdk` v3), OpenAI-compatible LLM via `app/llm.py`
(`qwen3.5` on the course LiteLLM proxy; MaaS `deepseek-v4.1-flash` later). UI text is Thai. Code comments English.

Run: `uv sync && uv run uvicorn app.main:app --reload` · Tests: `uv run pytest -q`.

## Hard privacy rules (product behaviour, enforce in code)
1. Read SDLC metadata only (time, status, actors). Never chat/email content.
2. Original feedback text is never persisted (not in DB, not in Redis, not in logs). Only the rewritten,
   user-confirmed text is stored. Drafts in Redis hold rewritten text only, TTL 1 h.
3. Identity is hashed at ingest (`actor_hash = sha256(salt + member_id)[:16]`). Feedback rows hold no author id.
   Reply goes through a random token; the token row stores the recipient LINE id encrypted with Fernet (`TOKEN_ENC_KEY`).
4. Individual signals (late-night work) go to that person only, never to the manager view.
5. Manager sees counts as ranges ("3–5 คน"), never exact counts below 6, and only after the k gate opens.
6. Max 3 nudges per person per week (Redis counter). Every nudge has "ไม่มีประโยชน์" and "ปิดการแจ้งเตือนประเภทนี้".

## Shared types
`app/contracts.py` (MemberProfile, PipelineResult, StructuredFeedback, AttackerGuess, PipelineStep,
MetadataEvent, Signal). Do not change field names; add optional fields only if needed and report it.

## Modules and owners

### Privacy pipeline — `app/privacy/` (worker A)
```python
# app/privacy/pipeline.py
async def run_pipeline(text: str, author_id: str, roster: list[MemberProfile],
                       *, existing_themes: list[tuple[str, str]] = (),  # (slug, label)
                       max_rounds: int | None = None) -> PipelineResult
```
Steps (each appends a `PipelineStep` for the demo trace):
1. `identifiers.remove_identifiers(text, roster)` — roster names/nicknames (exact + fuzzy), PyThaiNLP NER if
   available (graceful fallback), LLM pass for project names used by one person, dates, "ในประชุมที่มีแค่ผมกับพี่".
2. `neutralize.neutralize(text)` — deterministic dictionary: strip polite particles (ครับ คับ ค้าบ ฮะ ค่ะ คะ ค่า
   จ้ะ จ้า นะคะ นะครับ เจ้าค่ะ งับ …), replace first-person pronouns (ผม ดิฉัน หนู กระผม เค้า(self) ฉัน)
   with neutral phrasing, drop seniority kin terms used as self/other reference (พี่/น้อง + name).
   Also `leak_markers(text) -> list[str]` returning any gender/seniority markers left.
3. `rewrite.rewrite_with_attacker(...)` — LLM rewrites in neutral formal Thai; `neutralize` again (the model
   adds "ครับ" by itself!); `attacker.guess_author(text, roster)` asks the LLM to pick the author from the
   roster using profiles + style samples. `identified = guess == author and confidence >= max(0.5, 2/len(roster))`.
   Rewrite again (more aggressive) until not identified, max `attacker_max_rounds`; then `ok=False`.
4. `structure.structure(text) -> StructuredFeedback` — สถานการณ์ / ผลกระทบ / สิ่งที่ขอ, neutralized.
5. `gate.KGate` — Redis-backed: `add(team_id, theme_slug, item_id)`, `count(...)`, `is_open(...)` (count ≥ k),
   `count_range(n) -> "3–5 คน"`, random release delay 0..`gate_max_delay_s`. Pipeline does not call it; the
   backend calls it after the user confirms. Pipeline step 5 says "รอยืนยันส่ง แล้วรวมเสียงให้ครบอย่างน้อย k คน".
6. `cluster.assign_theme(text, existing_themes) -> (slug, label)` (LLM + seed list: friday-urgent-work
   "งานด่วนเย็นวันศุกร์", pr-review-delay "PR review ล่าช้า", blocked-tickets "งานติด block ไม่มีเจ้าของ",
   workload-oncall "ภาระงาน on-call", unclear-requirements "requirement ไม่ชัด", meeting-overload "ประชุมเยอะ").
   `cluster.cluster_offline(texts) -> list[int]` (TF-IDF over PyThaiNLP tokens + agglomerative) for eval.

### Backend — `app/` except `app/privacy/` and `app/static/` (worker B)
- `app/db.py` SQLAlchemy models: Team, Member(line_user_id nullable, actor_hash, opted_in, muted_kinds JSON),
  Event, SignalRow, Outreach, FeedbackItem(no author!), Theme, ReplyToken(token_hash, theme_id, enc_recipient).
- `app/redis_client.py` — real Redis if `REDIS_URL` else one shared `fakeredis` instance.
- `app/triggers/` — `rules.py` (thresholds below), `judge.py` (LLM context check: WIP label, reviewer on leave),
  `engine.py` (events → signals → outreach), `mockdata.py` (D3: 12-week team history generator with injected
  ground-truth friction, deterministic seed; also used by eval).
- `app/outreach/` — `messages.py` Thai templates, `line_bot.py` (webhook, signature check, push, quick reply,
  Flex preview), `channel.py` (deliver to LINE if member linked else store in web inbox).
- `app/manager/loop.py` — weekly summary, LLM proposal per theme, reply via token, 2-week follow-up comparing metrics.
- `app/demo.py` — demo seed + scenario endpoints. `app/api.py` routers. `app/main.py` app factory, static pages.

Trigger thresholds: PR waiting > 48 h and reviewer more senior → pr_stale · ticket Blocked > 2 days or reopened 3× →
ticket_blocked · task assigned after 17:00 Friday ≥ 3 times in 4 weeks → friday_urgent · commits after 22:00 on
≥ 4 days/week → late_night (self only) · one person > 50% of team reviews → review_concentration (team level only)
· sprint ended → sprint_end check-in.

### Web UI — `app/static/` (worker C)
Thai UI, no build step (plain HTML + JS modules, one CSS file; CDN libs allowed: Chart.js 4.4.x).
Pages served by backend: `/` → `index.html`, `/manager` → `manager.html`, `/demo` → `demo.html`.

## HTTP API (JSON)
```
GET  /api/health -> {ok, llm_model, line_enabled, db, redis}
GET  /api/team -> {team:{id,name}, members:[{member_id, display_name, role, seniority, gender, line_linked}]}
POST /api/demo/reset -> {ok}
POST /api/demo/scenario/{name}  name ∈ pr_stale|ticket_blocked|friday_urgent|late_night|sprint_end
     -> {signals:[SignalView], outreach:[OutreachView]}
POST /api/demo/teammates {theme_slug?} -> {added, gate:GateView}     # 2 simulated teammates submit similar feedback
POST /api/demo/advance {weeks} -> {themes:[ThemeView]}               # jump time, run follow-up
GET  /api/signals -> [SignalView]          # demo "god view" only
GET  /api/outreach?member_id= -> [OutreachView]   # web inbox (fallback when member has no LINE)
POST /api/outreach/{id}/respond {action} -> OutreachView   # same actions as LINE postbacks
POST /api/feedback/preview {member_id, text} -> {draft_id, result:PipelineResult}
POST /api/feedback/confirm {draft_id} -> {gate:GateView}
POST /api/feedback/cancel {draft_id} -> {ok}
GET  /api/manager/summary -> {week_label, themes:[ThemeView], metrics:MetricsView, pipeline:PipelineStats}
POST /api/manager/themes/{id}/reply {text, accept_proposal} -> ThemeView
GET  /api/manager/metrics -> MetricsView
POST /line/webhook

SignalView   = {id, kind, ref, affected_display, target_display|null, detected_at, judge_ok, judge_reason, state}
OutreachView = {id, member_id, display_name, kind, text, buttons:[{label, action}], channel:"line"|"web",
                created_at, response|null}
GateView     = {theme_slug, theme_label, count, k, released, count_range}
ThemeView    = {id, slug, label, count_range, status:"open"|"responded"|"resolved",
                samples:[StructuredFeedback], proposal, manager_reply|null,
                followup:{due_at, metric_name, before, after, improved}|null, released_at}
MetricsView  = {pr_wait_hours_median, pr_wait_hours_p90, blocked_ticket_days_avg,
                friday_after17_assignments_4w, review_top_share,
                series:{weeks:[str], pr_wait_hours:[num], friday_after17:[num], blocked_days:[num]}}
PipelineStats= {submitted, released, blocked_by_attacker, avg_attacker_rounds}
```
Postback/button actions: `nudge:accept:{signal_id}`, `nudge:decline:{signal_id}`, `nudge:useless:{signal_id}`,
`mute:{kind}`, `fb:confirm:{draft_id}`, `fb:cancel:{draft_id}`, `link:{member_id}`.

## Demo team (seed)
Team "ทีม Backend (Demo)", 6 members:
| id | display | role | gender | seniority |
|---|---|---|---|---|
| m-mint | มิ้น | Junior Backend Developer | female | junior |
| m-somchai | พี่สมชาย | Senior Backend Developer | male | senior |
| m-wan | พี่วรรณ | Engineering Manager (หัวหน้าทีม) | female | lead |
| m-boat | โบ๊ท | Backend Developer | male | mid |
| m-fon | ฝน | QA Engineer | female | junior |
| m-ton | ต้น | DevOps Engineer | male | mid |
Each has 3 Thai style samples (messages the manager has seen), matching gender/seniority markers.

Story (must work end to end): Mint opens PR #123, Somchai is reviewer → `pr_stale` → Mint gets LINE message with
buttons → "ช่วยเตือนให้หน่อย" → Somchai gets neutral reminder citing team policy, no Mint name → Mint sends
feedback about Friday urgent work → preview → confirm → gate 1/3 → demo teammates → gate 3/3 → manager dashboard
shows theme "งานด่วนเย็นวันศุกร์ (3–5 คน)" + proposal "cut-off 15:00" → manager replies → Mint receives reply via
token → advance 2 weeks → Friday after-17 assignments 3 → 0, theme resolved.

LINE linking: on follow, bot asks "คุณคือใครในทีมเดโม" with quick replies of members → `link:{member_id}`.
Typing "ความเห็น" (or any free text when linked) starts anonymous feedback; bot replies with Flex preview
(3 sections + attacker rounds) and buttons ยืนยันส่ง / ยกเลิก.
