# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47"]
#
# [tool.ty.analysis]
# allowed-unresolved-imports = ["playwright.**"]
# ///
"""Check the web UI against DESIGN.md and save screenshots of each page and key demo scenes.

Checks, per page, at the recording viewport (1536x864, device scale 1.667 -> 2560x1440 screenshots):
  1. font floor     every visible text is >= 13 px
  2. contrast       visible text >= 4.5:1 (>= 3:1 for >= 24 px, or >= 18.66 px bold) against its painted background
  3. overflow       no horizontal page scroll
  4. full width     page containers have no max-width
  5. fold           on /demo after a mock pipeline run, the gate bar and the last pipeline step end above y = 728
                    (864 minus the 136 px caption-safe band)

Usage:
  python3 -m http.server 8099 --directory app/static &      # static server, mock data
  uv run scripts/design_check.py                             # -> design-check/*.png, exit 1 on failures
  uv run scripts/design_check.py --base-url http://localhost:8000 --no-mock   # FastAPI server, real data
First run only: uv run --with playwright playwright install chromium
"""

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

W, H, SCALE, CAPTION_SAFE = 1536, 864, 1.667, 136
FONT_FLOOR = 13
CONTAINERS = "main, .workspace, .demo-workspace, .home-main, .nav-inner, #site-header > div"

AUDIT_JS = """([floor, containers]) => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (top, under) => { const a = top[3]; return [0, 1, 2].map(i => top[i] * a + under[i] * (1 - a)).concat(1); };
  const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
    return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2]); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + .05) / (y + .05); };
  const bgOf = el => { const layers = [];
    for (let n = el; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c[3] > 0) { layers.push(c); if (c[3] >= .99) break; } }
    let col = [255, 255, 255, 1]; for (let i = layers.length - 1; i >= 0; i--) col = over(layers[i], col); return col; };
  const label = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  const small = [], low = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('[aria-hidden="true"], svg, script, style, #kjb-cap')) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (!r.width || !r.height || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    const size = parseFloat(cs.fontSize), text = el.textContent.trim().slice(0, 40);
    if (size < floor) small.push(`${label(el)} ${size}px "${text}"`);
    const fg = parse(cs.color); if (!fg) continue;
    const bg = bgOf(el), need = (size >= 24 || (size >= 18.66 && +cs.fontWeight >= 600)) ? 3 : 4.5;
    const cr = ratio(over(fg, bg), bg);
    if (cr < need && !el.closest('[disabled], [aria-disabled="true"]')) low.push(`${label(el)} ${cr.toFixed(2)}:1 (needs ${need}) "${text}"`);
  }
  const capped = [...document.querySelectorAll(containers)].filter(e => getComputedStyle(e).maxWidth !== 'none').map(e => `${label(e)} max-width ${getComputedStyle(e).maxWidth}`);
  return { small, low, capped, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
}"""


def url(base, name, static, mock):
    path = f"/{name or 'index'}.html" if static else f"/{name}"
    return base.rstrip("/") + path + ("?mock=1" if mock else "")


async def settle(page):
    await page.wait_for_load_state("networkidle")
    await page.evaluate("document.fonts && document.fonts.ready")
    await page.wait_for_timeout(700)


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", default="http://localhost:8099")
    ap.add_argument(
        "--no-mock", action="store_true", help="use live data (needs the FastAPI server and LLM)"
    )
    ap.add_argument("--out", default="design-check")
    args = ap.parse_args()
    static, mock = args.base_url.endswith(":8099"), not args.no_mock
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - One-off screenshot script.
    failures = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": W, "height": H}, device_scale_factor=SCALE
        )
        page = await ctx.new_page()
        for name in ("", "manager", "demo"):
            await page.goto(url(args.base_url, name, static, mock))
            await settle(page)
            await page.screenshot(path=str(out / f"{name or 'home'}.png"))
            res = await page.evaluate(AUDIT_JS, [FONT_FLOOR, CONTAINERS])
            label = f"/{name}"
            problems = [
                ("font < 13px", res["small"]),
                ("contrast", res["low"]),
                ("max-width", res["capped"]),
            ]
            if res["overflow"] > 0:
                problems.append(("overflow", [f"page scrolls sideways by {res['overflow']}px"]))
            for kind, items in problems:
                if items:
                    failures += len(items)
                    print(f"FAIL {label} {kind}: {len(items)}")
                    for item in items[:8]:
                        print(f"     {item}")
            if not any(items for _, items in problems):
                print(f"ok   {label}")

        # demo scene: run the mock pipeline and check that the outcome sits above the caption band
        if mock:
            await page.goto(url(args.base_url, "demo", static, mock))
            await settle(page)
            await page.get_by_text("ล้างข้อมูลเดโมและเริ่มใหม่").click()
            await page.wait_for_timeout(800)
            await page.get_by_role("button", name="ทดสอบการปกป้องตัวตน").click()
            await page.get_by_role("button", name="ยืนยันส่งความเห็น").wait_for(timeout=20000)
            await page.wait_for_timeout(1200)
            await page.screenshot(path=str(out / "demo-pipeline.png"))
            limit = H - CAPTION_SAFE
            for sel in (".gate-bar, #gate", "#pipeline-steps > li:last-child"):
                box = await page.locator(sel).first.bounding_box()
                bottom = (box["y"] + box["height"]) if box else None
                if bottom is None or bottom > limit:
                    failures += 1
                    print(
                        f"FAIL /demo fold: {sel} ends at y={bottom and round(bottom)} (limit {limit})"
                    )
                else:
                    print(f"ok   /demo fold: {sel} ends at y={round(bottom)}")
        await browser.close()

    print(f"\n{failures} problem(s). Screenshots in {out}/")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
