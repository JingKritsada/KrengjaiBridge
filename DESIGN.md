# Design — Kreng-jai Bridge (web UI, light theme v1)

The locked design system for `app/static`. Every page change reads this file first.
Extend or amend this file when the system needs to grow; do not invent per-page styles.

- Visual reference with live mockups: `docs/design/reference.html` (open in a browser).
- Implementation steps: `docs/design/IMPLEMENTATION_PLAN.md`.
- Automated check: `uv run scripts/design_check.py` (font floor, contrast, overflow, full width, fold).

## 1. Direction

**A quiet instrument panel.** The product watches, measures and protects. The UI is one soft material
(neumorphism) with raised controls and inset readouts, neutral and exact. Colour appears only where
something is protected, waiting or identifiable.

Four rules decide every case:

1. **Summary before detail.** Each page leads with the one state that matters now (gate count, theme
   waiting for a reply, the 3 → 0 result).
2. **Colour means state.** Teal = protected / done / primary action. Amber = waiting. Red = identifiable
   or error. Everything else is neutral.
3. **Depth means role.** Raised = holds content or can be pressed. Inset = takes input or holds data.
   Flat = text, charts, state chips. At most two depth levels in one region.
4. **Readable in a compressed video.** No text under 13 px. No meaning carried by a hairline or by a
   shadow alone.

Scope: light theme only. No dark theme work in v1.

## 2. Tokens

Create `app/static/css/tokens.css` with exactly this block and load it before `app.css` on every page.
Pages use tokens by name (`var(--ink-2)`), never raw hex, except `#fff` on the accent.

```css
:root {
  color-scheme: light;

  /* base and depth (neumorphism: page and panels share one colour) */
  --paper: #e8eded;
  --surface: var(--paper);
  --surface-2: #e1e7e7;                     /* wells: chat area, data wells */
  --neu-hi: rgb(255 255 255 / .85);         /* light shadow, top-left */
  --neu-lo: rgb(160 178 178 / .55);         /* dark shadow, bottom-right; core 1.38:1 on --paper */
  --neu-raised: 6px 6px 14px var(--neu-lo), -6px -6px 14px var(--neu-hi);
  --neu-raised-sm: 3px 3px 7px var(--neu-lo), -3px -3px 7px var(--neu-hi);
  --neu-inset: inset 3px 3px 7px var(--neu-lo), inset -3px -3px 7px var(--neu-hi);
  --neu-inset-sm: inset 2px 2px 4px var(--neu-lo), inset -2px -2px 4px var(--neu-hi);
  --neu-float: 12px 12px 28px var(--neu-lo), -8px -8px 20px var(--neu-hi);
  --neu-accent: 4px 4px 10px rgb(11 106 96 / .32), -4px -4px 10px var(--neu-hi);

  /* lines */
  --rule: #d2dada;                          /* dividers only (decorative) */
  --rule-strong: #7a8787;                   /* input borders, 3.15:1 on --paper */

  /* text (ratios on --paper) */
  --ink: #142022;                           /* 14.11:1 */
  --ink-2: #4a5759;                         /*  6.35:1 */
  --ink-3: #566264;                         /*  5.34:1, lightest allowed text */

  /* accent and states */
  --accent: #0b6a60;                        /* 5.48:1; white on it 6.47:1 */
  --accent-hover: #08554d;                  /* white on it 8.69:1 */
  --accent-soft: #d7e8e4;
  --accent-ink: #0a5a52;                    /* on --accent-soft 6.37:1 */
  --warn: #7f5300;  --warn-soft: #f3e6c8;   /* 5.40:1 */
  --danger: #a8231b; --danger-soft: #f4dcd9;/* 5.51:1 */
  --line: #06c755;  --line-ink: #04723a;    /* LINE dot only; label text 5.12:1 */

  /* type */
  --font-ui: "IBM Plex Sans Thai", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
  --t-xs: 13px; --t-sm: 14px; --t-md: 16px; --t-lg: 18px; --t-xl: 22px;
  --t-2xl: 28px; --t-3xl: 36px; --t-4xl: 48px; --t-5xl: 64px;
  --lh-body: 1.65; --lh-ui: 1.5; --lh-head: 1.3;

  /* space (4-pt) and layout */
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; --s7: 48px; --s8: 64px; --s9: 96px;
  --gutter: clamp(16px, 2.1vw, 48px);       /* 32 px at the 1536 recording width */
  --header-h: 64px;
  --caption-safe: 136px;

  /* radius */
  --r-chip: 8px; --r-ctl: 12px; --r-well: 14px; --r-panel: 18px;

  /* motion */
  --ease-out: cubic-bezier(.2, .8, .2, 1);
  --dur-fast: 120ms; --dur-med: 240ms; --dur-slow: 320ms;
  --step-cadence: 420ms;                    /* 900ms in recording mode */
}
```

Google Fonts link (replace the current one on all 3 pages):
`https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Thai:wght@400;500;600&display=swap`

## 3. Typography

| Role | Size / line-height / weight | Use |
|---|---|---|
| display | 64 / 1.3 / 600 | home H1 only |
| 4xl | 48 / 1.15 / 500 | outcome number (3 → 0) |
| 2xl | 28 / 1.3 / 600 | page title, gate count |
| xl | 22 / 1.35 / 600 | theme title (26 px inside the theme card) |
| lg | 18 / 1.45 / 600 | panel title |
| md | 16 / 1.65 / 400 | body, chat, inputs, buttons |
| sm | 14 / 1.55 / 400–500 | labels, small buttons, table cells |
| xs | 13 / 1.5 / 400 | floor: meta, timestamps, hints |
| mono | 13–14 / 1.5 / 400 | references only: `PR #123`, `k=3`, model names |

- IBM Plex Sans Thai includes Plex Latin, and its digits share one width, so numbers align without `tnum`. Still set `font-variant-numeric: tabular-nums` on numbers.
- Thai: `letter-spacing: 0` everywhere (remove the hero's `-0.025em`). Headings never below line-height 1.25.
- Paragraphs cap their own width: `max-width: 68ch` (hero pitch `30em`).
- Use Arabic digits. Headings name what people see (Thai first); English only for names (PR, LINE, k = 3).
- Buttons start with a verb. Numbers always carry a unit ("18 ชม.", "3–5 คน").
- No subtitle under every heading; no badge that only describes. Badges/chips report state only.

## 4. Depth (soft neumorphism) and its guardrails

| Level | Token | Used for |
|---|---|---|
| raised | `--neu-raised` | panels, theme card, journey card |
| raised-sm | `--neu-raised-sm` | secondary buttons, chips with counts, tabs (selected), scenario icon tiles, avatars, chat bubbles |
| inset | `--neu-inset` | text inputs, textarea, chat well, gate bar, AI proposal block, selected scenario row, tab track |
| inset-sm | `--neu-inset-sm` | pressed / selected buttons and quick replies, empty gate slots, status pill, attacker rows |
| float | `--neu-float` | toast, menus |
| primary | solid `--accent` + `--neu-accent` | the one primary button per view |

Guardrails (required; these keep WCAG 1.4.11 and video legibility):

- Text inputs and textareas keep a **1 px `--rule-strong` border** inside the inset well.
- The **primary button is a solid teal fill** with white text. Never a shadow-only primary.
- **Selected / pressed = inset + `--accent-ink` text**: two cues, not shadow alone.
- **Focus**: `outline: 2px solid var(--accent); outline-offset: 3px`, shown instantly (no transition).
- **Flat**: text, charts, sparklines, state chips (`ok` / `wait` / `danger`). Never emboss text.
- Panels have no border. Dividers inside panels use 1 px `--rule`.
- Demo-only controls (teammates, skip 2 weeks) add `1px dashed var(--rule-strong)` to show they are simulated.
- On screens ≤ 700 px use `--neu-raised-sm` for panels (lighter shadows).

## 5. Layout: full width

- **No `max-width` on page containers.** Remove it from `.nav-inner` (1600), `.workspace` (1600),
  `.demo-workspace` (1700), `.home-main` (1320). Pages fill the window.
- Horizontal padding is `var(--gutter)` on header, main and footer.
- Text blocks keep their own measure (section 3), so wide screens get more room, not longer lines.
- Hit targets: primary 44 px high (home CTAs 52), small 36 px, never under 32 px; 8 px between targets.

| Page | Grid at ≥ 1101 px | ≤ 1100 px | ≤ 700 px |
|---|---|---|---|
| `/` hero | `minmax(0,1fr) minmax(0,.78fr)`, gap 96 | gap 48 | 1 column |
| `/` loop | 4 columns, 1 px `--rule` separators | 2 × 2 | 1 column |
| `/demo` | `clamp(260px,19vw,360px) clamp(360px,26vw,520px) 1fr`, gap 20 | rail + pipeline; inbox under rail | 1 column: rail, inbox, pipeline |
| `/manager` | `minmax(0,1.6fr) minmax(400px,1fr)`, gap 24 | 1 column, metrics after themes | 1 column |

## 6. Icons

Lucide (ISC licence), inline `<symbol>` sprite in `js/ui.js` (no runtime fetch). 24 px grid, drawn at
20 px in rows and 24 px in empty states, `stroke-width: 1.75`, round caps and joins, `currentColor`.
Remove every unicode glyph used as an icon (`→ ↗ ✓ ✗`). Remove text "icons" ("PR", "!", "17:00", "22:00", "14").

| Meaning | Lucide name |
|---|---|
| PR waiting / ticket blocked / Friday urgent / late night / sprint end | `git-pull-request` / `circle-alert` / `calendar-clock` / `moon` / `flag` |
| pipeline steps 1–6 | `eraser`, `languages`, `crosshair`, `list-checks`, `users`, `layers` |
| protected / not stored / done | `shield-check` / `lock` / `check` |
| skip time / reset / metrics / open in new view | `fast-forward` / `rotate-ccw` / `chart-line` / `arrow-up-right` |
| arrow in buttons / close | `arrow-right` / `x` |
| observe / ask / act / close the loop (home) | `eye` / `message-square` / `send` / `refresh-cw` |
| brand mark (custom, white on `--accent`, stroke 2) | `M3 18h18 M5 18V9 M19 18V9 M5 11c3 0 4.5-4 7-4s4 4 7 4 M9 18v-5 M15 18v-5` |

No sparkle / magic-wand icons for AI. Label AI output with the model name in mono (`qwen3.5`).

## 7. Motion

| What | Duration | Easing |
|---|---|---|
| hover / press colour, shadow flip | 120 ms | linear |
| step expand / collapse | 240 ms | `--ease-out` |
| gate slot fill | 320 ms | `--ease-out` |
| pipeline step cadence | 420 ms (900 ms in recording mode) | — |
| toast in / out | 200 / 160 ms | `--ease-out` |
| `prefers-reduced-motion` | ≤ 150 ms, opacity only | — |

Animate `transform`, `opacity` and `box-shadow` only.

## 8. Components

- **Header** (static HTML in each page, not injected): height 64, `--paper`, `box-shadow: 0 10px 18px -12px var(--neu-lo)`.
  Brand mark 32 px tile (radius 8) + "เกรงใจบริดจ์" 18/600 + "Kreng-jai Bridge" 13 `--ink-3`. Nav links 15 px `--ink-2`;
  current = `--ink` 600 + 2 px `--accent` bar at the bottom. Right: status pill (inset-sm, 13 px): dot + "ระบบพร้อม · qwen3.5 · LINE เปิด", or the mock badge.
- **Buttons**: radius 12, 16 px/500, height 44 (small 36, 14 px). Primary solid accent; secondary raised-sm; demo-only raised-sm + dashed border. Press = inset-sm.
- **Chips**: radius 8, height 28, 14/500. `ok` accent-soft/accent-ink, `wait` warn-soft/warn, `danger` danger-soft/danger (flat); count chip raised-sm with `users` icon.
- **Inputs**: radius 12, inset, 1 px `--rule-strong`, 16 px text, padding 10 × 12.
- **Tabs (member tabs)**: inset track (radius 14, padding 5, gap 4), 3 × 2 grid, tab 34 px high, 14 px; selected raised-sm + `--accent-ink` 600; LINE-linked member shows a 6 px `--line` dot.
- **Toast**: top-right, 16 px below the header, float shadow, 15 px, max 420 px wide. Never at the bottom (captions live there).
- **Empty states**: one line of help, said once, inside the empty area.

## 9. Pages

Reference mockups for all three pages are in `docs/design/reference.html` (section 5), drawn at 1536 × 864.

### `/` Home
Z-path: H1 → pitch → primary CTA → journey card → its 3 → 0 result → 4-step loop.
- Left: H1 "ให้ความเกรงใจ / ไม่ขวาง**การทำงาน**" (last word `--accent`), pitch 20/1.7 `--ink-2` max 30em, CTAs:
  primary "เริ่มเดโม" → `/demo`, secondary "ดูแดชบอร์ดหัวหน้า". Facts row (product rules, not metrics):
  **k = 3** คนขึ้นไป หัวหน้าจึงเห็น · **0** แชตหรืออีเมลที่ถูกอ่าน · **≤ 3** ข้อความต่อคนต่อสัปดาห์.
- Right: raised "เส้นทางของหนึ่งเสียง" card, ordered list of 4: worry (with `<del>` on หนู / ค่ะ), protect (3 ok chips),
  team theme + "3–5 คน", result "3 → 0 ครั้ง / 4 สัปดาห์" at 40 px.
- Below: 4-step loop (สังเกต, ถามเป็นการส่วนตัว, ลงมือแทน, ปิดวงจร), numbered because the order is real. Replaces the 3 pillars.

### `/demo` Demo console
Columns follow the story: **rail (scenarios, time controls) → inbox → privacy pipeline**.
- Page title row: H1 28 + "ทีม Backend (Demo) · ข้อมูลจำลอง" 14 `--ink-3` + secondary "เปิดแดชบอร์ดหัวหน้า".
- **Rail**: 5 scenario rows (36 px raised-sm icon tile + name 15/500 + meta 13). Selected row = inset + accent icon, and a trail line
  showing the signal state ("ส่งถึงมิ้น · ตอบรับแล้ว") — this replaces the signals table on camera. Bottom: `#advance` (demo-only button), hint, `#reset` as a 14 px text button.
- **Inbox**: title "กล่องข้อความส่วนตัว" + "เห็นเฉพาะเจ้าตัว" (lock), member tabs, identity row, chat well (inset, `--surface-2`) with raised-sm bubbles (16/1.6) and quick replies (raised-sm; answered one = inset-sm + accent).
- **Pipeline** ("ปกป้องตัวตนก่อนส่ง", mono meta "privacy pipeline · 6 ขั้น"), top to bottom:
  1. **Gate bar** (inset, always first, always above the caption band). One state machine:
     `idle` "พร้อมทดสอบ · ความเห็นจะยังไม่ถูกส่ง" → `running` "กำลังทดสอบ… ขั้น N/6" → `ready` shows `#confirm` / `#cancel` →
     `sent` shows 3 person slots (filled = accent, empty = inset-sm) + count 28 px + `#teammates` (demo-only) → `released` "ผ่านประตูนิรนามแล้ว · หัวหน้าเห็นจำนวนเป็นช่วง 3–5 คน".
  2. **Source** (`#feedback-form`): author select + textarea (input rules) + `#preview`. After a run, the textarea is replaced in place by the same sentence with `<del>` on removed markers (`#removed-markers`); "ต้นฉบับไม่ถูกบันทึก" with lock.
  3. **Steps** `#pipeline-steps`: 6 rows, one line each when done (number dot 26 px accent, name 15/600, result 14 `--ink-2` with ellipsis, check). Only step 3 (attacker rounds, `#attacker-rounds`) and step 4 (structured text, `#feedback-preview`, accent 1 px border) expand. All six fit in 864 px.
- Full signals table moves into a collapsed `<details class="signals-panel">` below the grid.

### `/manager` Manager dashboard
F-path: title + privacy promise → theme → voice → AI draft → reply; metrics are the second column.
- Title row: H1 28 + privacy line with `shield-check` ("เห็นเฉพาะประเด็นที่มีเสียงร่วมอย่างน้อย 3 คน · จำนวนแสดงเป็นช่วง · ไม่มีข้อมูลรายบุคคล"); right: week 16/500 + live dot "อัปเดตทุก 5 วินาที".
- **Theme card** (raised, padding 24 × 28): title 26/600, count chip, status chip (`wait` รอหัวหน้าตอบ / `ok` ปิดวงจรแล้ว).
  When resolved, `.followup` moves to the **top** of the card as an accent-soft band: label + "3 → 0" at 48 px.
  Voice as `<dl>` rows (label column 88 px 14 `--ink-3`, text 16). AI proposal block (inset) labelled "ข้อเสนอจาก AI" + mono model name. Reply form (`.reply-form`) unchanged fields; after reply, show the sent reply as a quote and hide the form.
- **Metrics** (raised panel): a `<dl>` list, one row per metric: label 14 | sparkline 112 × 32 (inline SVG, 2 px accent line, ≤ 10 % area fill, end dot) | value 32 px + unit | delta (first vs last of the 8-week series, computed, never typed). Metrics without a series show "—" in place of the sparkline. **Remove Chart.js** and its CDN script.
- **Gate stats** (raised panel): 4 numbers 26 px + 13 px labels.

## 10. Recording mode and video

- `?rec=1` adds `body.rec`: `--step-cadence: 900ms`, inbox polling every 1 s, and `window.kjbSpotlight(selector)` which draws a 3 px `--accent` ring, 4 px offset, 8 px soft halo on the target for 1.2 s (Playwright video shows no cursor).
- Layout viewport for recording 1536 × 864, device scale 1.667 → 2560 × 1440 capture.
- Critical content for each scene sits between y = 140 and y = 728; the bottom 136 px is the caption-safe band.
- Captions: IBM Plex Sans Thai, EN 36 px / TH 32 px on a 1080p canvas, EN ≤ 42 chars, TH ≤ 35, one line each, 0.83–7 s per event, ≥ (EN + TH chars) ÷ 17 + 1 s.
- Full video plan (phone takes, LINE OA, edit layouts, 14-shot list, export): `docs/design/reference.html` section 4.

## 11. LINE Flex preview card

LINE stays flat (Flex has no shadows) but uses the same colours. `preview_message()` in `app/outreach/line_bot.py`:
title "ตรวจสอบก่อนส่งแบบนิรนาม" (`lg`, bold, `#142022`); row "ร่องรอยที่ตัดออก" with each removed marker as a
`span` (`decoration: "line-through"`, `color: "#A8231B"`); separator; label rows (`xs`, `#566264`) and values (`sm`,
`#142022`, wrap); status "ทดสอบเดาตัวตน N รอบ · ระบุตัวตนไม่ได้" (`xs`, `#0A5A52`); footer buttons primary `#0B6A60`
"ยืนยันส่ง" and secondary "ยกเลิก" (keep postback data `fb:confirm:` / `fb:cancel:`). Markers come from
`leak_markers(text)` on the incoming message, in memory only; never store them.

## 12. Contract with `scripts/record_demo.py` (do not break)

Keep exactly: button texts "ล้างข้อมูลเดโมและเริ่มใหม่", "ทดสอบการปกป้องตัวตน", "ยืนยันส่งความเห็น", "เพื่อนร่วมทีมส่งความเห็นคล้ายกัน",
"ข้ามเวลา 2 สัปดาห์", "ช่วยเตือนให้หน่อย"; `button[data-scenario="…"]`; classes `.member-tabs` (buttons with member names),
`.inbox-panel`, `.live-pipeline`, `.reply-form` (with `textarea`, `input[name="accept_proposal"]`, `button[type="submit"]`), `.followup`;
`#feedback-form textarea`. JS ids may move inside new containers but keep their names:
`#pipeline-status #pipeline-steps #attacker-rounds #feedback-preview #confirm-actions #confirm #cancel #gate #gate-count #teammates #advance #reset #member-tabs #member-select #feedback-text #preview #inbox #signals #themes #metrics #pipeline-stats #theme-count #week-label #refresh-status #health`.

## 13. Do not

Gradients, glass blur, glow, coloured shadows (except the primary's accent shadow), embossed text, radius over 24 px,
shadow-only inputs or primary buttons, three equal feature cards, a subtitle under every heading, descriptive badges,
emoji or unicode glyphs as icons, sparkle icons for AI, invented metrics, drawn browser or phone frames, negative
letter-spacing on Thai, toasts at the bottom, any text under 13 px.
