# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.48"]
#
# [tool.ty.analysis]
# allowed-unresolved-imports = ["playwright.**"]
# ///
"""Record the web demo walkthrough (with EN/TH captions) to an MP4.

First run only:  uv run --with playwright playwright install chromium
Record:          uv run scripts/record_demo.py
Options:         --base-url http://localhost:8000  --size 1536x864  --scale 1.667  --out demo.mp4  --no-captions  --headed
Dry run (mock):  python3 -m http.server 8099 --directory app/static &
                 uv run scripts/record_demo.py --mock --out /tmp/dry.mp4

The run resets the demo data on the target server, plays the whole story
(PR nudge -> anonymous feedback -> k-gate -> manager reply -> 2-week follow-up)
and ends on the architecture diagram. Pages open in recording mode (?rec=1): slower step cadence, 1 s inbox
polling, and a spotlight ring before each click (the video shows no cursor).

Writes next to the video: <name>.srt (one event per caption, timed from the real run) and
<name>.events.json (time, selector and label of each click), for the editor. ffmpeg converts the WebM to MP4
when available.

Playwright's own video is the layout size (1536x864): it records CSS pixels and never scales up, so --scale
only sharpens rendering. For the final cut, run --headed and capture the window with OBS (native Retina,
no scale override); see docs/design/reference.html section 4.1.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.async_api import Locator, Page, async_playwright

ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE = (ROOT / "docs/submission/assets/architecture.html").as_uri()
FEEDBACK = "หนูไม่กล้าบอกพี่หัวหน้าค่ะ ว่าสั่งงานเย็นวันศุกร์ทำให้หนูต้องยกเลิกนัดตลอด"
REPLY = "ขอบคุณที่สะท้อนเรื่องนี้ ตั้งแต่สัปดาห์หน้าจะตัดรอบงานด่วนวันศุกร์ที่ 15:00"

# (english, thai) caption per scene, from the shot list in docs/design/reference.html section 4.4.
# One line each: EN <= 42 characters, TH <= 35. Edit here when the story changes.
CAPTIONS = {
    "intro": ("Kreng-jai Bridge speaks up for Thai teams", "พูดแทนสิ่งที่คนทำงานเกรงใจจะพูด"),
    "pr": ("PR #123 has waited 52 hours for review", "อ่านเฉพาะข้อมูลงาน ไม่อ่านแชต"),
    "ask": ("It asks Mint privately. She decides.", "ถามมิ้นเป็นการส่วนตัว ให้เธอตัดสินใจ"),
    "nudge": ("Somchai gets a neutral reminder. No names.", "พี่สมชายได้คำเตือนกลาง ๆ ไม่มีชื่อมิ้น"),
    "share": ("Mint shares what she can’t say out loud", "มิ้นเล่าเรื่องที่ไม่กล้าพูดตรง ๆ"),
    "pipeline": ("Six steps remove and rewrite the clues", "ลบร่องรอยแล้วเขียนใหม่ 6 ขั้น"),
    "markers": ("“หนู” and “ค่ะ” give away who wrote it", "คำลงท้ายบอกเพศและอาวุโสทันที"),
    "attacker": ("An attacker model fails to name her", "AI ผู้โจมตีเดาตัวผู้เขียนไม่ได้"),
    "confirm": ("She checks the rewrite and confirms", "ตรวจข้อความที่ปรับแล้ว แล้วกดยืนยัน"),
    "gate": ("No one is shown until 3 people agree", "หัวหน้าจะเห็นเมื่อมีอย่างน้อย 3 คน"),
    "teammates": ("Two teammates (simulated) say the same", "เพื่อน 2 คน (จำลอง) พูดเรื่องเดียวกัน"),
    "manager": ("The manager sees a theme and a range", "หัวหน้าเห็นเป็นประเด็นและจำนวนเป็นช่วง"),
    "reply": ("The reply returns via an anonymous token", "คำตอบส่งกลับผ่าน token นิรนาม"),
    "heard": ("Mint hears back. Her name was never shown.", "มิ้นได้คำตอบ โดยไม่มีใครรู้ว่าเป็นเธอ"),
    "followup": ("Two weeks later: late Friday work 3 → 0", "2 สัปดาห์ต่อมา งานด่วนเย็นศุกร์ 3 → 0"),
    "outro": ("Runs on Huawei Cloud: ECS · VPC · EIP", "ทำงานบน Huawei Cloud"),
    "line": ("Try it on LINE: @075bvvrs", "ลองใช้ได้ที่ LINE @075bvvrs"),
}

# Sizes are CSS px at the 1536x864 layout; x1.25 gives EN 36 / TH 32 px and a 1296 px box on the 1080p canvas.
CAPTION_JS = """([en, th, ms]) => {
  let el = document.getElementById('kjb-cap');
  if (!el) {
    el = document.createElement('div'); el.id = 'kjb-cap';
    el.style.cssText = 'position:fixed;left:50%;bottom:32px;transform:translateX(-50%);z-index:99999;max-width:1037px;'
      + 'background:rgb(20 32 34 / .92);color:#fff;padding:10px 24px 12px;border-radius:10px;text-align:center;white-space:nowrap;'
      + 'font-family:"IBM Plex Sans Thai",system-ui,sans-serif';
    document.body.appendChild(el);
  }
  el.innerHTML = `<div style="font-weight:600;font-size:29px;line-height:1.35">${en}</div>`
    + (th ? `<div style="font-weight:400;font-size:26px;line-height:1.45;color:rgb(255 255 255 / .86)">${th}</div>` : '');
  el.hidden = false;
  clearTimeout(window.kjbCapTimer);  // hide when the .srt cue ends (max 7 s) so video and subtitles agree
  window.kjbCapTimer = setTimeout(() => { el.hidden = true; }, ms);
}"""


MAX_CUE = 7.0  # seconds, longest subtitle event


def reading_time(en: str, th: str) -> float:
    """Seconds a caption must stay up: (EN + TH characters) / 17 + 1, clamped to 0.83-7 s."""
    return min(MAX_CUE, max(0.83, (len(en) + len(th)) / 17 + 1))


def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3_600_000:02}:{ms // 60_000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


class Demo:
    def __init__(self, page: Page, base_url: str, captions: bool, mock: bool):
        self.p, self.base, self.captions, self.mock = page, base_url.rstrip("/"), captions, mock
        self.t0 = time.monotonic()  # the video starts when the page opens
        self.cues: list[dict] = []  # caption events for the .srt
        self.events: list[dict] = []  # clicks for events.json

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 3)

    def url(self, name: str) -> str:
        if self.mock:  # plain static server (python3 -m http.server) with mock data
            return f"{self.base}/{name or 'index'}.html?mock=1&rec=1"
        return f"{self.base}/{name}?rec=1"

    async def show(self, key: str):
        """Burn in the current caption for the rest of its cue (max 7 s from the cue start)."""
        cue = self.cues[-1]
        left = MAX_CUE - (self.now() - cue["start"])
        if self.captions and left > 0:
            await self.p.evaluate(CAPTION_JS, [*CAPTIONS[key], int(left * 1000)])

    async def cap(self, key: str):
        # Keep the previous caption up for its reading time before the next one replaces it.
        if self.cues:
            last = self.cues[-1]
            left = reading_time(last["en"], last["th"]) - (self.now() - last["start"])
            if left > 0:
                await self.wait(left)
        en, th = CAPTIONS[key]
        self.cues.append({"key": key, "start": self.now(), "en": en, "th": th})
        await self.show(key)

    async def go(self, name: str):
        url = self.url(name)
        if self.p.url.startswith(self.base):
            # An in-page navigation runs the page's view transition; goto() counts as the address bar and skips it.
            await self.p.evaluate("url => setTimeout(() => location.assign(url))", url)
            await self.p.wait_for_url(url)
        else:
            await self.p.goto(url)
        await self.p.evaluate("document.fonts.ready.then(() => true)")
        await self.wait(1.2)

    async def wait(self, seconds: float):
        await self.p.wait_for_timeout(int(seconds * 1000))

    async def spot(self, locator: Locator):
        """Ring the element (window.kjbSpotlight, recording mode) so the viewer sees where the action is."""
        await locator.scroll_into_view_if_needed()
        await locator.evaluate("el => window.kjbSpotlight ? window.kjbSpotlight(el) : false")

    async def click(self, locator: Locator, selector: str):
        await self.spot(locator)
        await self.wait(0.5)
        label = " ".join((await locator.inner_text()).split()) or await locator.evaluate(
            "el => (el.closest('label')?.innerText || el.getAttribute('aria-label') || el.name || '').trim()"
        )
        self.events.append({"time": self.now(), "selector": selector, "label": label})
        await locator.click()

    async def button(self, name: str):
        await self.click(self.p.get_by_role("button", name=name), f'button:has-text("{name}")')

    async def run(self):
        p = self.p
        await self.go("")
        await self.cap("intro")
        await self.wait(6)

        await self.go("demo")
        await self.click(p.get_by_text("ล้างข้อมูลเดโมและเริ่มใหม่"), "#reset")
        await self.wait(2.5)
        await self.click(
            p.locator(".member-tabs button", has_text="มิ้น"), '.member-tabs button:has-text("มิ้น")'
        )
        await self.cap("pr")
        await self.click(
            p.locator('button[data-scenario="pr_stale"]'), 'button[data-scenario="pr_stale"]'
        )
        await self.wait(5)
        await self.cap("ask")
        await self.wait(2)
        await self.click(
            p.locator(".inbox-panel button", has_text="ช่วยเตือนให้หน่อย").first,
            '.inbox-panel button:has-text("ช่วยเตือนให้หน่อย")',
        )
        await self.wait(3)
        await self.click(
            p.locator(".member-tabs button", has_text="พี่สมชาย"),
            '.member-tabs button:has-text("พี่สมชาย")',
        )
        await self.wait(2)
        await self.cap("nudge")
        await self.wait(5)
        await self.click(
            p.locator(".member-tabs button", has_text="มิ้น"), '.member-tabs button:has-text("มิ้น")'
        )
        await self.wait(1)

        await self.cap("share")
        box = p.locator("#feedback-form textarea").first
        await self.spot(box)
        await box.fill(FEEDBACK)
        await self.wait(3)
        confirm = p.get_by_role("button", name="ยืนยันส่งความเห็น")
        # A slow fallback model can take a minute, and the attacker may block a rewrite; try up to 3 times.
        for attempt in range(3):
            await self.button("ทดสอบการปกป้องตัวตน")
            if attempt == 0:
                await self.cap("pipeline")
            try:
                await confirm.wait_for(timeout=150_000)
                break
            except Exception:
                if attempt == 2:
                    raise
        await p.locator(".gate-bar").scroll_into_view_if_needed()
        await self.wait(1)
        markers = p.locator("#removed-markers")
        if await markers.is_visible():
            await self.spot(markers)
        await self.cap("markers")
        await self.wait(3)
        await self.spot(p.locator("#attacker-rounds"))
        await self.cap("attacker")
        await self.wait(3)
        await self.cap("confirm")
        await self.button("ยืนยันส่งความเห็น")
        await self.wait(2.5)
        await self.spot(p.locator(".gate-bar"))
        await self.cap("gate")
        await self.wait(3)
        await self.button("เพื่อนร่วมทีมส่งความเห็นคล้ายกัน")
        await self.cap("teammates")
        await self.wait(8)

        await self.go("manager")
        await self.cap("manager")
        for _ in range(24):  # the agent loop releases the theme within ~30-50 s
            if await p.locator(".reply-form").count():
                break
            await self.wait(5)
            await p.reload()
            await self.wait(1.5)
            await self.show("manager")
        await self.wait(4)
        box = p.locator(".reply-form textarea").first
        await self.spot(box)
        await box.press_sequentially(REPLY, delay=35)
        await self.click(
            p.locator('.reply-form input[name="accept_proposal"]').first,
            '.reply-form input[name="accept_proposal"]',
        )
        await self.cap("reply")
        await self.wait(2)
        await self.click(
            p.locator('.reply-form button[type="submit"]').first,
            '.reply-form button[type="submit"]',
        )
        await self.wait(4)

        await self.go("demo")
        await self.click(
            p.locator(".member-tabs button", has_text="มิ้น"), '.member-tabs button:has-text("มิ้น")'
        )
        await self.spot(p.locator(".inbox-panel"))
        await self.cap("heard")
        await self.wait(5)
        await self.button("ข้ามเวลา 2 สัปดาห์")
        await self.wait(4)
        await self.go("manager")
        followup = p.locator(".followup").first
        if await followup.count():
            await self.spot(followup)
        await self.cap("followup")
        await self.wait(7)

        await p.goto(ARCHITECTURE)
        await self.wait(1.5)
        await self.cap("outro")
        await self.wait(4)
        await self.cap("line")
        await self.wait(4)

    def write_sidecars(self, out: Path):
        """<name>.srt: one event per caption, ending at the next one (max 7 s). <name>.events.json: the clicks."""
        end = self.now()
        lines = []
        for i, cue in enumerate(self.cues):
            stop = self.cues[i + 1]["start"] if i + 1 < len(self.cues) else end
            stop = max(cue["start"] + 0.83, min(stop, cue["start"] + MAX_CUE))
            lines += [
                str(i + 1),
                f"{srt_time(cue['start'])} --> {srt_time(stop)}",
                cue["en"],
                *([cue["th"]] if cue["th"] else []),
                "",
            ]
        out.with_suffix(".srt").write_text("\n".join(lines), encoding="utf-8")
        out.with_name(out.stem + ".events.json").write_text(
            json.dumps(self.events, ensure_ascii=False, indent=2), encoding="utf-8"
        )


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--base-url", help="default: the live server, or http://localhost:8099 with --mock"
    )
    ap.add_argument(
        "--mock", action="store_true", help="static server pages (/demo.html …) with ?mock=1 data"
    )
    ap.add_argument("--size", default="1536x864", help="layout viewport WIDTHxHEIGHT")
    ap.add_argument(
        "--scale",
        type=float,
        default=1.667,
        help="device scale factor (headless only; --headed keeps the screen's own)",
    )
    ap.add_argument("--out", default=str(ROOT / "demo.mp4"))
    ap.add_argument(
        "--no-captions", action="store_true", help="clean video; captions still go to the .srt"
    )
    ap.add_argument("--headed", action="store_true", help="show the browser while recording")
    args = ap.parse_args()
    base_url = args.base_url or (
        "http://localhost:8099" if args.mock else "https://119-13-81-32.sslip.io"
    )
    width, height = (int(v) for v in args.size.lower().split("x"))
    out = Path(args.out).resolve()  # noqa: ASYNC240 - One-off recording script.

    with tempfile.TemporaryDirectory() as tmp:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not args.headed)
            ctx = await browser.new_context(
                viewport={"width": width, "height": height},
                screen={"width": width, "height": height},
                device_scale_factor=None if args.headed else args.scale,
                record_video_dir=tmp,
                record_video_size={"width": width, "height": height},
            )
            page = await ctx.new_page()
            demo = Demo(page, base_url, not args.no_captions, args.mock)
            try:
                await demo.run()
            finally:
                out.parent.mkdir(parents=True, exist_ok=True)
                demo.write_sidecars(out)
                video = page.video
                await ctx.close()
                await browser.close()
            webm = Path(await video.path())
        if shutil.which("ffmpeg") and out.suffix == ".mp4":
            subprocess.run(  # noqa: ASYNC221 - Offline conversion after the browser closes.
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(webm),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(out),
                ],
                check=True,
            )
        else:
            out = out.with_suffix(".webm")
            shutil.copy(webm, out)
    print(f"saved {out}, {out.with_suffix('.srt').name}, {out.stem}.events.json")


if __name__ == "__main__":
    asyncio.run(main())
