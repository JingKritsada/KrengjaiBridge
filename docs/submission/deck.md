# Slide deck — content spec (Template 2, 16:9, English, Thai only in examples)

Visual rules: keep the template backgrounds/logos. Dark navy text (#1d2742), accents from the template
(blue #3157d5, violet #6b4fd8, cyan #19a7c9) and one green for "safe/passed" (#1f6f5c). Max ~35 words of body
text per slide; numbers big. Thai runs use font "Leelawadee UI" (fallback Tahoma); Latin uses the template font.
Every slide has a short title (≤ 7 words) and one takeaway line at the bottom when useful.
Assets in `docs/submission/assets/` and `eval/results/`.

1. **Title** (template slide 1). Line 2 box: "Chulalongkorn University · [[Team Name]] · Kreng-jai Bridge".
   Add subtitle: "An AI agent that speaks up for Thai teams — and proves the feedback can't be traced back."

2. **The problem nobody says out loud**
   Left: three moments (icons + one line each): "PR waits 3 days — the junior won't chase a senior",
   "Blocker never mentioned in stand-up", "Urgent work lands at 17:30 every Friday".
   Right: big stats — "50% of developers lose >10 h/week to non-coding friction", "63% say leaders don't
   understand their problems" (Atlassian DevEx 2025). Footer: "Kreng-jai keeps teams polite — and problems unsaid."

3. **Why 'anonymous' tools fail in Thai teams**
   Example card: "หนูไม่กล้าบอกพี่หัวหน้าค่ะ ว่าสั่งงานเย็นวันศุกร์ทำให้หนูต้องยกเลิกนัดตลอด" with หนู/ค่ะ/พี่ highlighted
   in red → callout "1 word reveals gender + seniority". Bullets: "In a team of 5 the manager can guess the
   writer", "Quarterly surveys are too late and never follow up", "Every tool waits for people to speak".

4. **Our idea: the agent takes the hard-to-say role**
   Three steps horizontally: Observe (SDLC metadata only) → Ask (private LINE message, the person decides) →
   Act (neutral reminder or anonymous feedback). Line: "A bot has no seniority, no face to lose, no debt to anyone."

5. **Live demo (video, 2:16)**
   Embedded `../LiveDemo_Videos/2026-10-20_demo_edit.mp4` (outside the repo; `--video` overrides), poster
   `assets/demo-poster.jpg`, click to play. Recorded on the live ECS server with Mint's real LINE chat.
   Footer: the two teammates are simulated; waits are cut; YouTube link https://youtu.be/f4Op2MmzrTY. Slides 6 and 10 repeat what the video shows.

6. **Demo story: two weeks of Mint**
   Timeline (8 steps from the concept: Tue PR #123 → Thu 48 h trigger → LINE ask → neutral reminder w/o name →
   Fri feedback → k=3 reached → Mon manager accepts 15:00 cut-off → +2 weeks Friday after-17 work 3 → 0).
   Screenshot: `assets/screen-inbox.png` (LINE-style inbox).

7. **Privacy pipeline: 6 steps, tested by an attacker**
   Diagram of 6 steps (remove identifiers → neutralize Thai markers → rewrite ⇄ attacker → situation/impact/request
   → k-gate (k=3) → themes). Before/after example: original (red markers) → "สถานการณ์: มีการมอบหมายงานในช่วงเย็นวันศุกร์ ·
   ผลกระทบ: ต้องยกเลิกนัดหมายส่วนตัวอย่างต่อเนื่อง · สิ่งที่ขอ: พิจารณาปรับกระบวนการวางแผนงาน". Screenshot `assets/screen-pipeline.png`.

8. **Results: anonymity you can measure**
   Chart `eval/results/attacker_before_after.png` large. Callouts with the 3 strongest numbers from
   results.json (author attribution before→after vs 5% chance; gender inference; marker leak). Footnote:
   "Synthetic Thai dataset, 20 personas × 12 messages; pilot with real volunteers next."

9. **Results: detection and meaning**
   `eval/results/engine.png` + meaning stat (% judged ≥ 4/5) + theme clustering ARI + pipeline latency.

10. **Manager loop closes the circle**
   Screenshot `assets/screen-manager.png`. Bullets: themes as ranges (3–5 people), AI proposal, reply via
   anonymous token, follow-up metric before → after.

11. **Architecture on Huawei Cloud**
    `assets/architecture.png` full width.

12. **Built with AI agents on Huawei Cloud**
    Lifecycle row: Requirement → Code generation → Build → Troubleshoot → Deploy, each with 1 line from entry-form §2
    (contract-first; parallel coding agents; one FastAPI + Docker; region/IAM fixes; ECS + Caddy + LINE webhook).
    Callout: "Agent skill provisions VPC · ECS · RDS · DCS in one command (`skills/huawei-cloud-provision`)".

13. **Privacy by design (PDPA)**
    6 rules as icon grid: metadata only · opt-in · individual signals only to the person · originals deleted ·
    identities hashed, tokens encrypted · nothing reaches the manager below 3 people.

14. **Why we win** — comparison table (rows: survey tools Officevibe/TINYpulse/Lattice; burnout analytics
    Viva Insights/Uplevel; engineering metrics LinearB/Swarmia; Thai HR systems) × columns (acts for the employee,
    tested anonymity, Thai language/LINE, closes the loop with metrics). Kreng-jai Bridge row all ✓.

15. **Roadmap**
    Now (demo) → Next 4 weeks: pilot with 2 real teams, real-volunteer D1 dataset, MaaS DeepSeek/Typhoon 2,
    RDS/DCS via skill, CodeArts CI → Later: Lark, multi-tenant, calendar signals.
    Business: buyer = HR / CTO of Thai software houses & banks; uses existing engagement-survey budget.

16. **End** (template end slide): "Thank you · Live demo: https://119-13-81-32.sslip.io · Video https://youtu.be/f4Op2MmzrTY · LINE @075bvvrs".
