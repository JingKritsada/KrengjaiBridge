# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.48"]
# ///
"""Record the web demo walkthrough (with EN/TH captions) to an MP4.

First run only:  uv run --with playwright playwright install chromium
Record:          uv run scripts/record_demo.py
Options:         --base-url http://localhost:8000  --size 1920x1080  --out demo.mp4  --no-captions  --headed

The run resets the demo data on the target server, plays the whole story
(PR nudge -> anonymous feedback -> k-gate -> manager reply -> 2-week follow-up)
and ends on the architecture diagram. ffmpeg converts the WebM to MP4 when available.
"""

import argparse
import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parent.parent
ARCHITECTURE = (ROOT / "docs/submission/assets/architecture.html").as_uri()
FEEDBACK = "หนูไม่กล้าบอกพี่หัวหน้าค่ะ ว่าสั่งงานเย็นวันศุกร์ทำให้หนูต้องยกเลิกนัดตลอด"
REPLY = "ขอบคุณที่สะท้อนเรื่องนี้ ตั้งแต่สัปดาห์หน้าจะตัดรอบงานด่วนวันศุกร์ที่ 15:00"

# (english, thai) caption per scene; edit here when the story changes.
CAPTIONS = {
    "intro": ("Kreng-jai Bridge — an AI agent that speaks up for Thai teams",
              "เอเจนต์ที่พูดแทนสิ่งที่คนทำงานไทยเกรงใจเกินกว่าจะพูด"),
    "pr": ("1 · The agent reads SDLC metadata only: PR #123 has waited > 48 h for a senior reviewer",
           "อ่านเฉพาะ metadata — PR #123 รอรุ่นพี่ review เกิน 48 ชั่วโมง"),
    "ask": ("It asks the junior privately — she decides", "ทักมิ้นเป็นการส่วนตัว ให้เจ้าตัวตัดสินใจเอง"),
    "nudge": ("The senior gets a neutral reminder that cites team policy — the junior is never named",
              "พี่สมชายได้ข้อความเตือนตามข้อตกลงทีม โดยไม่มีชื่อมิ้น"),
    "markers": ("2 · Anonymous feedback: “หนู” and “ค่ะ” reveal a young woman in one word",
                "คำลงท้ายและสรรพนามบอกเพศและอาวุโสทันที"),
    "pipeline": ("6-step privacy pipeline: remove identifiers → neutralize Thai markers → attacker tries to name the author → structure",
                 "ลบตัวระบุ → ทำให้เป็นกลาง → attacker ลองเดาผู้เขียน → จัดโครงสร้าง"),
    "attacker": ("The attacker fails to identify the author, so the text may be sent",
                 "Attacker เดาผู้เขียนไม่ได้ ข้อความจึงผ่าน"),
    "gate": ("She confirms. The k-anonymity gate holds it until at least 3 people raise the same theme",
             "ประตูนิรนามรอจนมีอย่างน้อย 3 คนพูดเรื่องเดียวกัน"),
    "teammates": ("Two teammates (simulated) raise a similar concern → gate reaches 3/3",
                  "เพื่อนร่วมทีม 2 คน (จำลอง) ส่งเรื่องคล้ายกัน"),
    "manager": ("3 · The manager sees a theme, a range (“3–5 people”) and a proposal — never who wrote it",
                "หัวหน้าเห็นเป็นธีมและจำนวนเป็นช่วง ไม่รู้ว่าใครเขียน"),
    "reply": ("The reply goes back to the authors through an encrypted anonymous token",
              "คำตอบส่งกลับถึงผู้เขียนผ่าน token นิรนาม"),
    "heard": ("Mint receives the answer — she knows she was heard, the manager still does not know who she is",
              "มิ้นได้รับคำตอบ รู้ว่ามีคนฟัง"),
    "followup": ("4 · Two weeks later the agent re-measures: urgent work after 17:00 on Friday 3 → 0. Loop closed.",
                 "ติดตามผลด้วยตัวเลขจริง: งานหลัง 17:00 วันศุกร์ 3 → 0"),
    "outro": ("Running on Huawei Cloud (ECS · VPC · EIP) · Live: 119-13-81-32.sslip.io · LINE @075bvvrs", ""),
}

CAPTION_JS = """([en, th]) => {
  let el = document.getElementById('kjb-cap');
  if (!el) {
    el = document.createElement('div'); el.id = 'kjb-cap';
    el.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;'
      + 'max-width:min(1100px,90vw);background:rgba(20,32,48,.92);color:#fff;padding:14px 22px;border-radius:12px;'
      + 'font:600 20px/1.45 Inter,system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.25);text-align:center';
    document.body.appendChild(el);
  }
  el.innerHTML = en + (th ? `<div style="font-weight:400;font-size:16px;opacity:.85;margin-top:4px">${th}</div>` : '');
}"""


class Demo:
    def __init__(self, page: Page, base_url: str, captions: bool):
        self.p, self.base, self.captions = page, base_url.rstrip("/"), captions

    async def cap(self, key: str):
        if self.captions:
            await self.p.evaluate(CAPTION_JS, list(CAPTIONS[key]))

    async def go(self, path: str):
        await self.p.goto(self.base + path)
        await self.p.wait_for_timeout(1800)

    async def wait(self, seconds: float):
        await self.p.wait_for_timeout(int(seconds * 1000))

    async def run(self):
        p = self.p
        await self.go("/")
        await self.cap("intro"); await self.wait(6)

        await self.go("/demo")
        await p.get_by_text("ล้างข้อมูลเดโมและเริ่มใหม่").click(); await self.wait(2.5)
        await self.cap("pr")
        await p.locator('button[data-scenario="pr_stale"]').click(); await self.wait(5)
        await self.cap("ask"); await self.wait(4)
        await p.locator(".inbox-panel button", has_text="ช่วยเตือนให้หน่อย").first.click(); await self.wait(3)
        await p.locator(".member-tabs button", has_text="พี่สมชาย").click(); await self.wait(3.5)
        await self.cap("nudge"); await self.wait(6)
        await p.locator(".member-tabs button", has_text="มิ้น").click(); await self.wait(1)

        await self.cap("markers")
        await p.locator("#feedback-form textarea").first.fill(FEEDBACK)
        await p.locator(".live-pipeline").scroll_into_view_if_needed(); await self.wait(4.5)
        await p.get_by_role("button", name="ทดสอบการปกป้องตัวตน").click()
        await self.cap("pipeline")
        confirm = p.get_by_role("button", name="ยืนยันส่งความเห็น")
        await confirm.wait_for(timeout=90_000); await self.wait(4)
        await p.mouse.wheel(0, 450); await self.wait(3.5)
        await self.cap("attacker")
        await p.mouse.wheel(0, 450); await self.wait(5.5)
        await confirm.click(); await self.wait(2.5)
        await self.cap("gate"); await self.wait(4)
        await p.mouse.wheel(0, -1200); await self.wait(0.8)
        await p.get_by_role("button", name="เพื่อนร่วมทีมส่งความเห็นคล้ายกัน").click()
        await self.cap("teammates"); await self.wait(12)

        await self.go("/manager")
        await self.cap("manager")
        for _ in range(24):  # the agent loop releases the theme within ~30-50 s
            if await p.locator(".reply-form").count():
                break
            await self.wait(5); await p.reload(); await self.wait(1.5); await self.cap("manager")
        await self.wait(5)
        box = p.locator(".reply-form textarea").first
        await box.scroll_into_view_if_needed()
        await box.press_sequentially(REPLY, delay=35)
        await p.locator('.reply-form input[name="accept_proposal"]').first.check()
        await self.cap("reply"); await self.wait(2.5)
        await p.locator('.reply-form button[type="submit"]').first.click(); await self.wait(4)

        await self.go("/demo")
        await p.locator(".inbox-panel").scroll_into_view_if_needed()
        await self.cap("heard"); await self.wait(6)
        await p.get_by_role("button", name="ข้ามเวลา 2 สัปดาห์").click(); await self.wait(4)
        await self.go("/manager")
        await self.cap("followup")
        followup = p.locator(".followup").first
        if await followup.count():
            await followup.scroll_into_view_if_needed()
        await self.wait(8)

        await p.goto(ARCHITECTURE); await self.wait(1.5)
        await self.cap("outro"); await self.wait(7)


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="https://119-13-81-32.sslip.io")
    ap.add_argument("--size", default="1440x900", help="WIDTHxHEIGHT, e.g. 1920x1080")
    ap.add_argument("--out", default=str(ROOT / "demo.mp4"))
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--headed", action="store_true", help="show the browser while recording")
    args = ap.parse_args()
    width, height = (int(v) for v in args.size.lower().split("x"))
    out = Path(args.out).resolve()

    with tempfile.TemporaryDirectory() as tmp:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not args.headed)
            ctx = await browser.new_context(
                viewport={"width": width, "height": height}, screen={"width": width, "height": height},
                device_scale_factor=1, record_video_dir=tmp, record_video_size={"width": width, "height": height},
            )
            page = await ctx.new_page()
            try:
                await Demo(page, args.base_url, not args.no_captions).run()
            finally:
                video = page.video
                await ctx.close()
                await browser.close()
            webm = Path(await video.path())
        if shutil.which("ffmpeg") and out.suffix == ".mp4":
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-preset", "medium",
                            "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
        else:
            out = out.with_suffix(".webm")
            shutil.copy(webm, out)
    print(f"saved {out}")


if __name__ == "__main__":
    asyncio.run(main())
