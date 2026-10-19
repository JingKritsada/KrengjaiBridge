# Entry Information Form — content source

Source text for Template 1 (Entry Information Form). Fields marked `[[TODO: ...]]` need the team's input.
Metric placeholders `{{...}}` are filled from `eval/results/results.json`.

## Team Information
- University Name: Chulalongkorn University
- Team Name: [[TODO: team name]]
- Instructor (1 person): [[TODO: instructor name]]
- Students (max 3): [[TODO: confirm — กฤษฎา ลิ้มศรีประพันธ์, ชิติพัฒน์ ภู่ทอง, ภาณุพงษ์ สภานนท์ (from HC-2026a-02 roster); add English names]]
- Team Leader Tel: [[TODO]]
- Team Leader Email: [[TODO]]
- Team Group Photo: [[TODO: ~2 MB photo]]

## Entry Information
- Topic: Topic 1: Creating Innovative AI Applications Powered by Huawei Cloud
- Entry Name: Kreng-jai Bridge — an AI agent that speaks up for Thai teams
- Applicable Fields: Office assistant; HR-tech / people analytics; software engineering teams (SDLC)
- Technologies Used: AI agent on LINE (LINE Messaging API) with an LLM through an OpenAI-compatible API (Qwen3.5 today, Huawei Cloud ModelArts Studio MaaS DeepSeek-V4.1-Flash supported by configuration); Thai NLP (PyThaiNLP tokenization + NER, dictionary neutralization of gender/seniority particles); LLM attacker loop for author re-identification testing; k-anonymity gate and theme clustering (TF-IDF + agglomerative, LLM theme labels); FastAPI, PostgreSQL, Redis, Docker; Huawei Cloud VPC, Security Group, EIP and ECS (CN-Hong Kong); an AI-agent skill (`skills/huawei-cloud-provision`) that provisions VPC/ECS/RDS for PostgreSQL/DCS for Redis with the Huawei Cloud SDK and deploys the app.

## Entry Introduction

### 1. Background and value (≤ 500 words)

Thai workplaces run on *kreng-jai* — the habit of not wanting to burden or embarrass others, especially seniors. It keeps teams polite, but it also keeps problems unsaid. Thai research links low trust in performance appraisal to seniority, kreng-jai and reluctance to voice opinions; juniors rarely report problems or push back on a superior, and "ได้ครับ" ("yes") can mean "no". In software teams the cost is concrete: a pull request waits three days because the junior does not dare to chase a senior reviewer; a blocked ticket is never mentioned in stand-up; urgent work keeps arriving on Friday evening. Atlassian's Developer Experience Report 2025 finds 50% of developers lose more than 10 hours a week to non-coding friction and 63% say leaders do not understand their problems.

Existing tools wait for people to speak, which is exactly what kreng-jai blocks. "Anonymous" surveys also fail in small teams: a manager of five can guess the writer from style and timing, and Thai makes it worse — polite particles and pronouns (ครับ/ค่ะ, ผม/หนู/ดิฉัน) reveal gender and seniority in a single word.

Kreng-jai Bridge is a proactive AI agent in LINE that takes the socially costly action instead of the person:

1. **Observe** friction from SDLC metadata only (time, status, who-is-waiting-for-whom) — never chat or e-mail content: PRs waiting > 48 h for a more senior reviewer, tickets blocked > 2 days, urgent work assigned after 17:00 on Fridays, repeated late-night commits.
2. **Ask** the affected person privately in LINE. They always decide.
3. **Act** on their behalf: send the reviewer a neutral reminder that cites the team's agreed policy and never names the requester, or turn their concern into anonymous feedback.

Anonymity is tested, not promised. Each feedback goes through a six-step Thai privacy pipeline: identifier removal, deterministic neutralization of Thai gender/seniority markers, an LLM rewrite checked by an **LLM attacker that tries to name the author from the team roster and writing samples** (rewritten again until it fails, or never sent), structuring into situation / impact / request, a k-anonymity gate that releases a theme only when at least 3 people raised it (counts shown as ranges such as "3–5 people"), and theme clustering. The manager receives a weekly theme summary with an AI-drafted proposal (e.g. "no urgent work after 15:00 on Friday"), replies through an anonymous token, and the agent re-measures the SDLC metric two weeks later to show whether the problem actually went away.

Value. Juniors get a safe go-between; managers see real problems early with a concrete fix; HR gets team-level engagement signals without surveillance (no individual scores, no individual signals to managers, opt-in). The buyer is HR or the CTO/VP Engineering of Thai software houses, banks and enterprises with in-house IT, using existing engagement-survey budgets. The approach generalizes to other high-context, hierarchy-sensitive cultures in Asia.

### 2. Huawei Cloud across the development lifecycle (≤ 1,000 words)

We built the prototype in about one day with AI agents doing most of the hands-on work and humans owning decisions. Huawei Cloud carried the runtime, and an agent skill makes the infrastructure reproducible. We list what was used and what is still pending, without overstating either.

**Requirement analysis.** We started from a concept study (problem evidence, users, risks, competitors) and converted it into a one-page build contract (`docs/ARCHITECTURE.md`): hard privacy rules, module boundaries, the HTTP API, view shapes, LINE postback actions and one end-to-end demo story. An LLM helped turn the research into user stories and acceptance criteria; the team fixed the scope for a one-day MVP (LINE 1:1 bot, three SDLC signals, full privacy pipeline, manager loop, evaluation). We checked Huawei Cloud capabilities early in the console: ModelArts Studio MaaS in CN-Hong Kong lists DeepSeek-V4.1-Flash, GLM-5.x and DeepSeek-V4 with OpenAI-compatible endpoints (`/v2/chat/completions`), which is why the app talks to LLMs only through an OpenAI-compatible client.

**Code generation.** An orchestrating coding agent wrote the shared contracts (`app/contracts.py`, LLM client, settings) and then dispatched parallel coding agents with disjoint file scopes: (A) the Thai privacy pipeline, (B) backend, trigger engine, LINE bot and manager loop, (C) the Thai web UI, then (D) evaluation and (E) the Huawei Cloud provisioning skill. Each worker received only goal, scope and verification commands; the orchestrator reviewed every diff and re-ran the tests itself. The result is about 2,000 lines of Python and a static web UI with 74 automated tests.

**Project building.** One FastAPI service (Python 3.12, `uv`), PostgreSQL and Redis, packaged with a Dockerfile and `docker compose`. Local development uses SQLite and in-process Redis, so tests run offline in seconds; the same code runs on PostgreSQL/Redis in the cloud by changing `DATABASE_URL` and `REDIS_URL`.

**Troubleshooting.** Real issues we hit and fixed on Huawei Cloud:
- VPC quota was exhausted in AP-Bangkok and AP-Singapore for our shared tenant, so we moved the stack to CN-Hong Kong, the same region as MaaS.
- The competition IAM user has VPC/ECS rights but gets 403 on RDS and `dcs:instance:create` on DCS, and has no programmatic access (no AK/SK). We kept the database and cache as containers on the ECS behind the same interfaces and wrote the provisioning skill so RDS and DCS can be created as soon as the permissions are granted, with no code change.
- The LLM added polite particles ("ครับ") to "neutral" rewrites, so the pipeline re-runs the deterministic neutralizer after every LLM step and refuses to publish if any marker remains.
- Container start-up failures (missing compose variables, DB host resolution) were diagnosed from `docker compose logs` on the ECS and fixed in the deploy script.
- The shared LLM key reached its budget during evaluation. We added an offline fallback (roster scrub + PyThaiNLP, a local stylometric attacker, rule-based structuring and themes), labelled in the UI, so the demo degrades instead of failing.

**Deployment.** VPC `vpc-kjb`, security group `sg-kjb` (HTTP/HTTPS public, SSH only from the admin IP), an EIP and a pay-per-use ECS (c9.large.2, Ubuntu 24.04) in CN-Hong Kong. `deploy/deploy.sh` syncs the repo and rebuilds with Docker Compose; Caddy terminates TLS automatically, which LINE requires for webhooks. The LINE webhook URL was registered and tested through the LINE API (HTTP 200).

**AI agent skill for provisioning RDS and Redis.** `skills/huawei-cloud-provision/` contains a `SKILL.md` that a coding agent loads and a Huawei Cloud SDK v3 script with `plan`, `apply`, `env` and `destroy`. It checks credentials and permissions first, finds resources by name (idempotent), creates VPC/subnet/security group, ECS, RDS for PostgreSQL and DCS for Redis in the team's enterprise project, waits until they are ACTIVE and prints the connection lines for `.env.server`. Switching the demo from containers to managed RDS/DCS is then one command plus a redeploy.

**Efficient practices.** (1) Write the contract first, then parallelize; (2) keep every external dependency behind an environment variable (LLM endpoint, DB, cache, LINE); (3) offline tests with mocked LLM calls plus a separate live smoke test; (4) cache LLM calls in evaluation so experiments are cheap to rerun; (5) never store secrets in git (`.env*` ignored; passwords generated per resource).

**Next on Huawei Cloud.** Move inference to ModelArts Studio MaaS (DeepSeek-V4.1-Flash is already subscribed in the tenant; needs an API key) and evaluate a Thai model (Typhoon 2) on ModelArts; create RDS/DCS with the skill; keep reply-token keys in DEW/KMS; move logs to LTS without user content; run CI/CD on CodeArts Repo/Pipeline.

## Technical Solution Introduction

**Overall solution.** See the architecture diagram below. Data flows one way: SDLC metadata (hashed identities) → Trigger Engine → private outreach in LINE → (optional) feedback → Privacy Pipeline → k-anonymity gate → themes → Manager Loop → follow-up metric.

**Module 1 — Thai privacy pipeline with attacker loop.** Identifier removal (roster names and nicknames, PyThaiNLP NER when available, LLM pass for unique projects/dates/meetings) → deterministic neutralization over PyThaiNLP tokens (polite particles ครับ/ค่ะ/คะ/จ้ะ/คับ/งับ…, first-person pronouns ผม/ดิฉัน/หนู/กระผม…, kin terms พี่/น้อง) → LLM rewrite → LLM attacker given the roster profiles and past messages guesses the author; if it hits the real author with confidence ≥ max(0.5, 2/N) the text is rewritten more aggressively, up to 3 rounds, otherwise blocked → structured "situation / impact / request" → user preview and confirmation. Originals are never persisted.

**Module 2 — SDLC trigger engine and outreach agent.** Rules on normalized metadata events plus an LLM context judge (WIP labels, reviewer on leave) to cut false positives; rate limit 3 nudges/person/week; buttons "help me remind", "not now", "not useful", "mute this type". A reminder cites the team policy ("PR waiting > 48 h") and never names the requester. Late-night signals go only to the person.

**Module 3 — k-anonymity gate, themes and manager loop.** Redis-backed gate per theme; release only at k ≥ 3 distinct submitters plus random delay; counts reported as ranges. Weekly summary with AI-drafted proposal, manager reply delivered through an encrypted token, two-week follow-up comparing the SDLC metric before/after.

**Module 4 — provisioning skill.** Agent-readable `SKILL.md` + Huawei Cloud SDK script (idempotent plan/apply/env/destroy) for VPC, ECS, RDS for PostgreSQL and DCS for Redis.

**Results (measured).** On a synthetic Thai dataset (20 personas × 12 messages; not real volunteers yet):
- Stylometric author attribution: {{stylo_before}} → {{stylo_after}} (chance 5%).
- LLM attacker author attribution: {{llm_before}} → {{llm_after}}.
- Gender inference: {{gender_before}} → {{gender_after}} (majority baseline {{gender_base}}); seniority: {{senior_before}} → {{senior_after}}.
- Texts with any Thai gender/seniority marker: {{leak_before}} → {{leak_after}}.
- Meaning preserved (LLM judge ≥ 4/5): {{meaning}}; pipeline pass rate {{ok_rate}}; median latency {{p50}} s.
- Theme clustering ARI {{ari}}, theme assignment accuracy {{theme_acc}}.
- Trigger engine on a 12-week simulated team history with decoys: recall {{recall}}, precision {{precision}}; every episode detected within one 15-minute replay tick (median delay {{delay}} min at that resolution).
- Demo story end to end: PR #123 nudged without naming the junior; Friday urgent-work theme released at 3 people; after the manager accepted the 15:00 cut-off, Friday after-17:00 assignments went 3 → 0 in the simulated follow-up.

Expected impact (to validate in a pilot): shorter PR wait and blocked time, higher check-in response than quarterly surveys, and a measurable share of themes that managers answer and fix. Running cost of the demo stack: about USD 0.10 per hour (ECS) plus LLM tokens.

## Entry Demonstration
- Live web demo: https://119-13-81-32.sslip.io (dashboard `/manager`, presenter console `/demo`)
- LINE Official Account: @075bvvrs (Kreng-jai Bridge)
- Video: [[TODO: link after recording]]
- Source code: [[TODO: repository link]]
