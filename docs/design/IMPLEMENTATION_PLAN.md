# Implementation plan: light redesign v1

Goal: rebuild the look of the three web pages (`/`, `/demo`, `/manager`) to the locked design system in
[`DESIGN.md`](../../DESIGN.md), so the demo video reads well at 1080p and 720p. Light theme only.
The product logic does not change.

| File | What it is |
|---|---|
| `DESIGN.md` (repo root) | The rules: tokens, type, depth, layout, components, page specs, contracts. **Source of truth.** |
| `docs/design/reference.html` | Visual reference: audit, live mockups of all 3 pages at 1536 × 864, recording and edit plan. Open it in a browser. |
| `scripts/design_check.py` | Automated gate: font floor, contrast, sideways scroll, full width, demo fold. Today it reports about 160 problems; the target is 0. |
| this file | Steps, file ownership, checks, and a prompt for an AI coding agent. |

Estimated effort: about 2.5 working days for one person, or about 1.5 days with three people (Phase 1 runs in parallel).

---

## 1. Copy-paste prompt for an AI coding agent

Use this with Claude Code, Codex or Cursor, run from the repository root. Give it one phase at a time
(replace `<PHASE>` with `Phase 0`, `Phase 1A`, …) and review the diff before the next phase.

```text
You are implementing a UI redesign in this repository (Kreng-jai Bridge, a FastAPI app with a vanilla
HTML/CSS/JS front end in app/static). Work on <PHASE> only, as described in
docs/design/IMPLEMENTATION_PLAN.md.

Read first, in this order:
1. DESIGN.md (repo root): the locked design system. It wins over anything else, including your own taste.
2. docs/design/IMPLEMENTATION_PLAN.md: the task list, file ownership and checks for <PHASE>.
3. docs/design/reference.html: visual reference. The mockups in section 5 are real HTML/CSS at
   1536x864; reuse their structure and values. Section 4 covers recording and the LINE card.
4. The current files you will change (listed under <PHASE>), and scripts/record_demo.py.

Rules:
- Light theme only. Vanilla HTML/CSS/JS, no build step, no new runtime dependencies, no CDN scripts.
- Use the tokens in app/static/css/tokens.css by name. No raw hex values in page CSS except #fff on the accent.
- Keep every label, class, attribute and id listed in DESIGN.md section 12. scripts/record_demo.py clicks them.
- Keep Thai UI copy as written in DESIGN.md; do not translate it to English.
- Do not change backend code, except app/outreach/line_bot.py and its test in Phase 2.
- Do not touch .env* files, deploy/, data/ or eval/.
- Keep mock mode working: python3 -m http.server 8099 --directory app/static, then open
  http://localhost:8099/demo.html?mock=1 (also index.html and manager.html).
- Keep the layout usable at 390 px wide (single column), but optimise for 1536x864.
- Only edit the files owned by <PHASE>. If you need a change in a file owned by another phase,
  stop and write it in your report instead.

Before you finish:
- Run: uv run pytest -q   (must pass)
- Start the static server above, then run: uv run scripts/design_check.py
  For Phase 0 report the before/after problem count. For Phase 1 parts, your page must report 0 problems.
- Open the screenshots in design-check/ and compare them with the matching mockup in
  docs/design/reference.html. List any visible difference you did not fix.
- Run git status and make sure only files owned by <PHASE> changed. Delete stray files.

Report: files changed, check results (paste the summary lines), screenshots compared, open questions.
Do not commit; I will review and commit.
```

---

## 2. Phases

Work on a branch: `git switch -c redesign/light-v1`. Commit once per phase after review.

### Phase 0: foundations (one person, about 4 h). Owns the shared files.

Files: `app/static/css/tokens.css` (new), `app/static/css/app.css`, `app/static/js/ui.js`,
`app/static/index.html`, `app/static/demo.html`, `app/static/manager.html` (head and header only),
new empty `app/static/css/home.css`, `demo.css`, `manager.css`.

1. Create `css/tokens.css` from DESIGN.md section 2.
2. In all 3 HTML heads: static `<link>` tags for `tokens.css`, `app.css` and the page CSS (no script-set `href`),
   and the new Google Fonts URL. Keep the `appAssetBase` script only for JS imports, or switch to relative paths
   that work both on FastAPI (`/static/...`) and on the static server.
3. Put the header markup **statically** in each HTML file (DESIGN.md section 8) with `min-height: 64px`.
   Change `shell()` in `ui.js` to only set `aria-current`, the `href`s (via `pageURL`), the status pill text and the mock badge.
4. Rebuild `app.css` as base + components only: reset, body (`--paper`, 16/1.65), headings, links, focus,
   buttons, chips, inputs, tabs, panels (raised), wells (inset), toast (top-right, float shadow), empty state, `.sr-only`.
   Move page-specific rules out to `home.css`, `demo.css`, `manager.css` (they may stay rough; Phase 1 rewrites them).
5. Remove `max-width` from `.nav-inner`, `.workspace`, `.demo-workspace`, `.home-main`; use `var(--gutter)`.
6. Replace the icon `paths` map in `ui.js` with a Lucide `<symbol>` sprite (DESIGN.md section 6), injected once by `shell()`,
   and an `icon(name)` helper that returns `<svg class="icon"><use href="#i-name"/></svg>`. Copy path data from
   `docs/design/reference.html` (the `<symbol>` block) or lucide.dev.
7. Recording mode in `ui.js`: if `?rec=1`, add `body.rec`, set `--step-cadence: 900ms` on `:root`, export
   `isRec`, and define `window.kjbSpotlight(selector)` (DESIGN.md section 10). Keep `?mock=1` and `?rec=1` combinable,
   and keep both query flags when `pageURL()` builds links.

Done when: all 3 pages load in mock mode with the new header, colours and fonts; no page scrolls sideways;
`design_check.py` shows no `max-width` failures and fewer problems than before; `pytest` passes.

### Phase 1: pages (parallel after Phase 0 is committed)

Each part owns only its own files. None of them edits `app.css`, `tokens.css` or `ui.js`; shared needs go in the report.

**1A · Demo console (about 6 h).** Owns `demo.html`, `css/demo.css`, `js/demo.js`.
- Column order rail → inbox → pipeline, grid from DESIGN.md section 5.
- Rail: scenario rows with Lucide icons; selected row inset; trail line under the selected scenario fed by
  `/api/signals` state (reuse the state labels in `loadSignals()`); `#advance`, hint, `#reset`.
  Move `#teammates` out of the rail into the gate bar.
- Inbox: tabs as inset track, identity row, chat well, bubbles, quick replies (answered = inset-sm + accent).
- Pipeline: gate bar first, as the state machine in DESIGN.md section 9 (it holds `#pipeline-status`,
  `#confirm-actions`, `#gate`, `#gate-count`, `#teammates`). Replace the progress bar with 3 person slots.
- Source: after a run, show the sentence with `<del>` markers in place of the textarea (`#removed-markers`),
  restore the textarea on cancel/reset.
- Steps: one line per finished step; only steps 3 (`#attacker-rounds`) and 4 (`#feedback-preview`) expand.
  Use `--step-cadence` for the reveal delay. Remove the old auto-scroll code inside the panel.
- Signals table into `<details class="signals-panel">` below the grid, closed by default.
- Done when: `/demo` reports 0 problems including both fold checks; the mock flow works end to end
  (reset → PR scenario → ช่วยเตือนให้หน่อย → switch to พี่สมชาย → test → confirm → teammates → 3/3).

**1B · Manager dashboard (about 4 h).** Owns `manager.html`, `css/manager.css`, `js/manager.js`.
- Title row with privacy line; two-column grid.
- Theme card per DESIGN.md section 9; when `status === 'resolved'`, render `.followup` first as the outcome band
  and hide the form behind the sent reply (keep the existing "add to the reply" `<details>`).
- Metrics: `<dl id="metrics">` rows with inline SVG sparklines from `summary.metrics.series`; delta = last − first,
  shown with the unit. Delete Chart.js (`<script src=…chart.umd…>`) and `renderChart()`.
- Gate stats panel; keep the polling and the "never erase a draft reply" logic in `renderThemes()`.
- Done when: `/manager` reports 0 problems; in mock mode both states render: open theme with the reply form,
  and resolved theme with 3 → 0 at the top.

**1C · Home (about 2 h).** Owns `index.html`, `css/home.css`, `js/home.js`.
- Hero, facts row, journey card, 4-step loop per DESIGN.md section 9. Remove the 3 pillars.
- Health status now lives in the header pill (`#health`); keep `health()` working.
- Done when: `/` reports 0 problems and matches the mockup at 1536 × 864.

### Phase 2: recorder and LINE card (about 3 h)

Owns `scripts/record_demo.py`, `docs/RECORDING.md`, `app/outreach/line_bot.py`, `tests/test_backend.py` (LINE preview test only).

1. `record_demo.py`:
   - defaults `--size 1536x864 --scale 1.667` (`device_scale_factor` and `record_video_size` 2560 × 1440);
   - add `?rec=1` to every URL; call `window.kjbSpotlight(selector)` before each click;
   - wait for `document.fonts.ready` after each navigation;
   - replace the two `mouse.wheel(0, 450)` scrolls with `scroll_into_view_if_needed()` on `.gate-bar`;
   - write `demo.srt` (one event per caption key, timed from the actual calls) and `events.json` (time, selector, label per click) next to the video;
   - caption font `"IBM Plex Sans Thai", system-ui`, EN 29 px / TH 26 px CSS (36/32 px in the 1080p video), max width 1037 px;
   - shorten the `CAPTIONS` texts to the 14-shot list in `docs/design/reference.html` section 4.4 (EN ≤ 42 characters, TH ≤ 35);
   - add `--mock`: use the static server paths (`/index.html`, `/demo.html`, `/manager.html`) with `?mock=1`.
2. `line_bot.py`: restyle `preview_message()` to DESIGN.md section 11. Add an optional `markers` argument, filled from
   `leak_markers(text)` where the LINE text handler builds the preview; markers stay in memory only.
   Add a test that checks the Flex JSON shape (title text, a `line-through` span per marker, both postback actions).
3. `docs/RECORDING.md`: update commands and the scene table (Thai, as now).

Done when: `uv run scripts/record_demo.py --mock --base-url http://localhost:8099 --out /tmp/dry.mp4` runs end to end
without timeouts and writes `.mp4`, `.srt` and `.json`; `pytest` passes.

### Phase 3: verify (about 2 h, the reviewer)

- `uv run pytest -q`, `uv run scripts/design_check.py` → 0 problems.
- Mobile: open each page at 390 px wide; no sideways scroll, single column, all buttons reachable.
- Watch the dry-run video at 720p on a 13–14″ laptop: every caption and every number named in a caption must be readable,
  and panel edges must still show (soft shadows survive the encode).
- One live run on the ECS when `/api/health` shows `llm_available: true`.
- Check `git status` for stray files.

### Phase 4: shoot and edit (the team, about 1 day)

Follow `docs/design/reference.html` section 4: web take (OBS capture of `record_demo.py --headed` for the final),
Mint's and Somchai's phone takes in LINE, edit layouts L1–L4, the 14-shot list, captions from `demo.srt`, export at
1920 × 1080, 30 fps, H.264 12–16 Mbit/s, CRF ≤ 18, −14 LUFS.

---

## 3. Review checklist (for each phase)

- [ ] Only the files owned by the phase changed (`git status`, `git diff --stat`).
- [ ] No raw hex in page CSS; no `max-width` on page containers; no text under 13 px.
- [ ] Inputs have the 1 px `--rule-strong` border; the primary button is solid teal; selected states use inset + accent text.
- [ ] No unicode arrows or ticks as icons; no Chart.js; no new CDN scripts.
- [ ] Every label and id in DESIGN.md section 12 still exists.
- [ ] Mock mode works on the static server; `pytest` passes; `design_check.py` result pasted in the PR.
- [ ] Screenshots in `design-check/` match the mockups in `docs/design/reference.html`.
