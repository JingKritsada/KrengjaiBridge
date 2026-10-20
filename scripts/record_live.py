# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "playwright>=1.48",
#   "pyobjc-framework-Quartz>=10",
#   "pyobjc-framework-Vision>=10",
#   "pyobjc-framework-Cocoa>=10",
# ]
#
# [tool.ty.analysis]
# allowed-unresolved-imports = ["playwright.**", "Quartz", "Vision", "AppKit", "Foundation"]
# ///
"""Record the live demo from the real screen (macOS only): web console + Mint's real LINE on iPhone Mirroring.

Takes:
  line  browser (left 1400 pt) + iPhone Mirroring (right): nudge in LINE, feedback in LINE, the gate and
        teammates on the web, the manager's reply arriving in LINE, the two-week follow-up.
  web   browser only (full frame): home page, the web console's six-step privacy pipeline, manager, follow-up,
        architecture.

Usage:  uv run scripts/record_live.py line --out ../LiveDemo_Videos/2026-10-20_take-line
        uv run scripts/record_live.py web  --out ../LiveDemo_Videos/2026-10-20_take-web
        uv run scripts/record_live.py line --dry   (no screen recording)

Needs: ffmpeg, Screen Recording + Accessibility permission for the terminal, iPhone Mirroring open and unlocked
with LINE on the Kreng-jai Bridge chat (linked as Mint). The real cursor moves and clicks, so do not touch the
mouse while it runs. Frame: 1920x1080 pt starting at y=100 (Retina capture -> 3840x2160 crop).

Writes <out>.raw.mp4 (full screen), <out>.mp4 (16:9 crop), <out>.srt (EN/TH captions timed to the video) and
<out>.events.json (every click and wait, for markers in the editor).
"""

import argparse
import asyncio
import json
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import AppKit
import Quartz as Q
import Vision
from Foundation import NSURL
from playwright.async_api import Locator, Page, async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://119-13-81-32.sslip.io"
ARCHITECTURE = (ROOT / "docs/submission/assets/architecture.html").as_uri()
FRAME_Y, FRAME_W, FRAME_H = 100, 1920, 1080  # points; the video is cropped to this
WEB_W = 1400  # browser width in the line take; the phone column is the rest
TITLE_BAR = 28  # app-mode window title bar, kept above the crop
BG = "#e8eded"  # page background, also behind the phone
FEEDBACK_CHUNKS = [
    "หนูไม่กล้า",
    "บอกพี่หัวหน้าค่ะ",
    " ว่าสั่งงาน",
    "เย็นวันศุกร์",
    "ทำให้หนู",
    "ต้องยกเลิกนัดตลอด",
]
FEEDBACK = "".join(FEEDBACK_CHUNKS)
REPLY = "ขอบคุณที่สะท้อนเรื่องนี้ ตั้งแต่สัปดาห์หน้าจะตัดรอบงานด่วนวันศุกร์ที่ 15:00"

# (english, thai) per beat. EN <= 42 characters, TH <= 35 (docs/RECORDING.md section 3).
CAPTIONS = {
    "live": ("Live: Huawei Cloud server + real LINE", "ระบบจริงบน Huawei Cloud + LINE จริง"),
    "pr": ("PR #123 has waited over 48 hours for review", "PR #123 รอรีวิวเกิน 48 ชั่วโมง"),
    "ask": ("The agent asks Mint privately in LINE", "เอเจนต์ถามมิ้นเป็นการส่วนตัวใน LINE"),
    "accept": ("Mint taps: “please remind for me”", "มิ้นกด “ช่วยเตือนให้หน่อย”"),
    "nudge": ("Somchai gets a neutral reminder. No names.", "พี่สมชายได้คำเตือนกลาง ๆ ไม่มีชื่อมิ้น"),
    "share": ("Mint writes what she can’t say out loud", "มิ้นพิมพ์เรื่องที่ไม่กล้าพูดตรง ๆ"),
    "pipeline": ("Six privacy steps run before anyone sees it", "ผ่าน 6 ขั้นปกป้องตัวตนก่อนส่ง"),
    "markers": ("“หนู” and “ค่ะ” reveal who wrote it: removed", "คำที่บอกเพศและอาวุโสถูกตัดออก"),
    "attacker": ("An attacker model fails to name her", "AI ผู้โจมตีเดาตัวผู้เขียนไม่ได้"),
    "confirm": ("She checks the rewrite and confirms", "ตรวจข้อความที่ปรับแล้ว แล้วกดยืนยัน"),
    "gate": ("No one is shown until 3 people agree", "หัวหน้าจะเห็นเมื่อมีอย่างน้อย 3 คน"),
    "teammates": ("Two teammates (simulated) say the same", "เพื่อน 2 คน (จำลอง) พูดเรื่องเดียวกัน"),
    "manager": ("The manager sees a theme and a range", "หัวหน้าเห็นเป็นประเด็นและจำนวนเป็นช่วง"),
    "proposal": ("AI drafts a concrete policy proposal", "AI ร่างข้อเสนอที่ทำได้จริง"),
    "reply": ("The reply returns via an anonymous token", "คำตอบส่งกลับผ่าน token นิรนาม"),
    "heard": ("Mint hears back. Her name was never shown.", "มิ้นได้คำตอบ โดยไม่มีใครรู้ว่าเป็นเธอ"),
    "followup": ("Two weeks later: late Friday work 3 → 0", "2 สัปดาห์ต่อมา งานด่วนเย็นศุกร์ 3 → 0"),
    "intro": ("Kreng-jai Bridge speaks up for Thai teams", "พูดแทนสิ่งที่คนทำงานเกรงใจจะพูด"),
    "console": ("The presenter console drives the story", "ห้องควบคุมเดโมจำลองข้อมูลงาน SDLC"),
    "outro": ("Runs on Huawei Cloud: ECS · VPC · EIP", "ทำงานบน Huawei Cloud"),
    "line": ("Try it on LINE: @075bvvrs", "ลองใช้ได้ที่ LINE @075bvvrs"),
}


# ---------------------------------------------------------------- desktop input (Quartz)

MOUSE = (
    threading.RLock()
)  # the keep-alive task and the story never move the cursor at the same time


def _post(ev):
    Q.CGEventPost(Q.kCGHIDEventTap, ev)


def cursor():
    p = Q.CGEventGetLocation(Q.CGEventCreate(None))
    return p.x, p.y


def glide(x, y, seconds=0.45):
    x0, y0 = cursor()
    steps = max(1, int(seconds * 60))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)
        point = (x0 + (x - x0) * t, y0 + (y - y0) * t)
        _post(Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, point, 0))
        time.sleep(seconds / steps)


def mouse_click(x, y, seconds=0.45):
    with MOUSE:
        _click(x, y, seconds)


def _click(x, y, seconds):
    glide(x, y, seconds)
    time.sleep(0.12)
    _post(Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseDown, (x, y), 0))
    time.sleep(0.1)
    _post(Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseUp, (x, y), 0))


def locked_glide(x, y, seconds=0.45):
    with MOUSE:
        glide(x, y, seconds)


def locked_wheel(lines):
    with MOUSE:
        glide(*cursor(), 0.01)
        wheel(lines)


def wheel(lines):
    step = 1 if lines > 0 else -1
    for _ in range(abs(lines)):
        _post(Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitLine, 1, step))
        time.sleep(0.04)


def _key(code, down, flags=0, src=None):
    ev = Q.CGEventCreateKeyboardEvent(src, code, down)
    Q.CGEventSetFlags(ev, flags)
    _post(ev)


def paste(text):
    """iPhone Mirroring forwards key codes only, so Thai text goes in through the clipboard (real Cmd down/up)."""
    pb = AppKit.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, AppKit.NSPasteboardTypeString)
    time.sleep(1.2)
    src = Q.CGEventSourceCreate(Q.kCGEventSourceStateHIDSystemState)
    cmd = Q.kCGEventFlagMaskCommand
    for code, down, flags in ((55, True, cmd), (9, True, cmd), (9, False, cmd), (55, False, 0)):
        _key(code, down, flags, src)
        time.sleep(0.05)


def window_bounds(owner):
    for w in Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly, Q.kCGNullWindowID):
        if w.get("kCGWindowOwnerName") == owner and w.get("kCGWindowLayer") == 0:
            b = w["kCGWindowBounds"]
            return int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])
    return None


def activate(name):
    for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if app.localizedName() == name:
            app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
            return True
    return False


def osa(script):
    return subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    ).stdout.strip()


# ---------------------------------------------------------------- phone (iPhone Mirroring + Vision OCR)


class Phone:
    """Find and tap LINE elements on iPhone Mirroring by their Thai text."""

    def __init__(self):
        self.box = window_bounds("iPhone Mirroring")
        if not self.box:
            raise SystemExit("iPhone Mirroring is not on screen")
        self.tmp = Path(tempfile.mkdtemp()) / "phone.png"
        self.last_touch = time.monotonic()

    def rel(self, fx, fy):
        x, y, w, h = self.box
        return x + w * fx, y + h * fy

    def read(self):
        """[(text, cx, cy, top)] in screen points."""
        x, y, w, h = self.box
        subprocess.run(["screencapture", "-x", f"-R{x},{y},{w},{h}", str(self.tmp)], check=True)
        src = Q.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(self.tmp)), None)
        img = Q.CGImageSourceCreateImageAtIndex(src, 0, None)
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setRecognitionLanguages_(["th-TH", "en-US"])
        req.setUsesLanguageCorrection_(False)
        Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            img, None
        ).performRequests_error_([req], None)
        out = []
        for obs in req.results() or []:
            b = obs.boundingBox()
            cx = x + (b.origin.x + b.size.width / 2) * w
            top = y + (1 - b.origin.y - b.size.height) * h
            cy = top + b.size.height * h / 2
            out.append((obs.topCandidates_(1)[0].string(), cx, cy, top))
        return out

    def find(self, pattern, *, lowest=True):
        hits = [t for t in self.read() if re.search(pattern, t[0].replace(" ", ""))]
        if not hits:
            return None
        return max(hits, key=lambda t: t[2]) if lowest else min(hits, key=lambda t: t[2])

    def wait(self, pattern, timeout=60.0, *, gone=False):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            hit = self.find(pattern)
            if (hit is None) == gone:
                return hit or True
            self.keepalive()
            time.sleep(0.4)
        return None

    def count(self, pattern):
        return sum(1 for t in self.read() if re.search(pattern, t[0].replace(" ", "")))

    def wait_more(self, pattern, before, timeout=60.0):
        """Wait until `pattern` shows more often than `before` (a new bubble with the same text)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.count(pattern) > before:
                return True
            self.keepalive()
            time.sleep(0.4)
        return False

    def tap(self, x, y, seconds=0.5):
        # A click on an inactive iPhone Mirroring window only focuses it and never reaches the phone.
        # It also drops a click that lands right after the window comes forward: let the cursor rest first.
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front or front.localizedName() != "iPhone Mirroring":
            activate("iPhone Mirroring")
            time.sleep(0.3)
            with (
                MOUSE
            ):  # priming tap on the empty left margin of the chat; the phone drops this one
                glide(*self.rel(0.03, 0.55), seconds)
                time.sleep(0.3)
                _click(*self.rel(0.03, 0.55), 0.05)
                time.sleep(0.4)
            seconds = 0.35
        with MOUSE:
            glide(x, y, seconds)
            time.sleep(0.6)
            _click(x, y, 0.05)
        self.last_touch = time.monotonic()

    def tap_until(self, pattern, check, before, tries=3, timeout=8.0):
        """Tap `pattern` until `check` shows more often than `before` (the phone reacted)."""
        for _ in range(tries):
            hit = self.find(pattern)
            if hit:
                self.tap(hit[1], hit[2])
            if self.wait_more(check, before, timeout):
                return True
        return False

    def clear_chat(self):
        """Delete this chat's history (setup, before recording): menu > Settings > Delete data > Delete all."""
        self.tap(*self.rel(0.923, 0.128))
        time.sleep(1.5)
        self.tap_text(r"Settings$|การตั้งค่า")
        time.sleep(1.5)
        self.tap_text(r"Deletedata$|ลบข้อมูล")
        time.sleep(1.5)
        self.tap_text(r"Deleteallchat|ลบข้อมูลแชท")
        time.sleep(1.5)
        hit = self.wait(r"^Cancel$|^ยกเลิก$", 5)  # the confirm dialog is up
        if hit and hit is not True:
            # The dialog's Delete sits right of Cancel, below the per-type Delete buttons.
            hits = [t for t in self.read() if t[0].strip() in ("Delete", "ลบ")]
            self.tap(*max(hits, key=lambda t: t[2])[1:3])
        time.sleep(2)
        self.tap(*self.rel(0.887, 0.128))  # close settings
        time.sleep(1.5)
        self.tap(*self.rel(0.109, 0.128))  # back to the chat
        time.sleep(1.5)

    def tap_text(self, pattern, timeout=20.0):
        hit = self.wait(pattern, timeout)
        if not hit or hit is True:
            raise RuntimeError(f"phone: no {pattern!r}")
        self.tap(hit[1], hit[2])
        return hit

    def keepalive(self, every=50.0):
        """iPhone Mirroring pauses after a few idle minutes; a one-line scroll on the chat keeps it awake."""
        if time.monotonic() - self.last_touch < every:
            return
        with MOUSE:
            here = cursor()
            glide(*self.rel(0.5, 0.55), 0.4)
            wheel(1)
            time.sleep(0.2)
            wheel(-1)
            glide(*here, 0.4)
            self.last_touch = time.monotonic()


# ---------------------------------------------------------------- screen recorder (ffmpeg avfoundation)


class Recorder:
    def __init__(self, out: Path):
        self.out, self.proc, self.t0 = out, None, None

    def start(self):
        dev = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
        ).stderr
        screen = re.search(r"\[(\d+)\] Capture screen 0", dev)
        if not screen:
            raise SystemExit("ffmpeg lists no screen to capture")
        index = screen.group(1)
        # Quality over size: the editor re-encodes anyway.
        proc = self.proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-y", "-f", "avfoundation", "-capture_cursor", "1",
             "-capture_mouse_clicks", "1", "-framerate", "30", "-i", f"{index}:none",
             "-c:v", "h264_videotoolbox", "-b:v", "45M", "-realtime", "1", "-pix_fmt", "yuv420p",
             "-color_range", "tv", "-stats", str(self.out)],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )  # fmt: skip
        started = threading.Event()

        def watch():
            stderr = proc.stderr
            assert stderr
            for line in iter(lambda: stderr.read(80), ""):
                if not started.is_set() and "frame=" in line:
                    self.t0 = time.monotonic() - 0.5
                    started.set()

        threading.Thread(target=watch, daemon=True).start()
        if not started.wait(20):
            raise SystemExit("ffmpeg did not start capturing (Screen Recording permission?)")

    def stop(self):
        if self.proc and self.proc.stdin and self.proc.poll() is None:
            self.proc.stdin.write("q")
            self.proc.stdin.flush()
            self.proc.wait(30)


# ---------------------------------------------------------------- the take


class Take:
    def __init__(self, page: Page, phone: Phone | None, t0):
        self.p, self.phone, self.t0 = page, phone, t0
        self.cues, self.events = [], []

    def now(self):
        return round(time.monotonic() - self.t0(), 2)

    def mark(self, what, **extra):
        self.events.append({"time": self.now(), "event": what, **extra})
        print(f"[{self.now():7.1f}] {what} {extra or ''}", flush=True)

    async def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.phone:
                await asyncio.to_thread(self.phone.keepalive)
            await asyncio.sleep(min(1.0, max(0.0, end - time.monotonic())))

    async def cap(self, key, hold=0.0):
        """Start a caption cue (the .srt only; nothing is burned into the screen)."""
        if self.cues:
            last = self.cues[-1]
            left = min(7.0, (len(last["en"]) + len(last["th"])) / 17 + 1) - (
                self.now() - last["start"]
            )
            if left > 0:
                await self.wait(left)
        en, th = CAPTIONS[key]
        self.cues.append({"key": key, "start": self.now(), "en": en, "th": th})
        self.mark(f"caption:{key}")
        if hold:
            await self.wait(hold)

    async def screen_point(self, locator: Locator):
        await locator.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        box = await locator.bounding_box()
        origin = await self.p.evaluate(
            "() => [window.screenX, window.screenY + window.outerHeight - window.innerHeight]"
        )
        return origin[0] + box["x"] + box["width"] / 2, origin[1] + box["y"] + box["height"] / 2

    async def spot(self, locator: Locator):
        await locator.scroll_into_view_if_needed()
        await locator.evaluate("el => window.kjbSpotlight ? window.kjbSpotlight(el, 1400) : false")

    async def click(self, locator: Locator, label: str, *, ring=True):
        x, y = await self.screen_point(locator)
        if ring:
            await self.spot(locator)
        self.mark("click", target=label)
        await asyncio.to_thread(mouse_click, x, y, 0.55)
        await asyncio.sleep(0.2)

    async def hover(self, locator: Locator):
        x, y = await self.screen_point(locator)
        await asyncio.to_thread(locked_glide, x, y, 0.6)

    async def go(self, name):
        url = f"{BASE}/{name}?rec=1"
        await self.p.evaluate("url => setTimeout(() => location.assign(url))", url)
        await self.p.wait_for_url(url)
        await self.p.evaluate("document.fonts.ready.then(() => true)")
        self.mark("page", url=url)
        await self.wait(1.2)

    async def phone_do(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    # -------------------------------------------------------- line take

    async def run_line(self):
        p, ph = self.p, self.phone
        assert ph, "the line take needs the phone"
        await self.cap("live", 3)
        await self.click(p.locator("#reset"), "reset demo")
        await self.wait(2.5)
        await self.click(p.locator(".member-tabs button", has_text="มิ้น"), "tab Mint")
        await self.wait(1)

        await self.cap("pr")
        before = await self.phone_do(ph.count, r"PR#123")
        await self.click(p.locator('button[data-scenario="pr_stale"]'), "scenario PR stale")
        if not await self.phone_do(ph.wait_more, r"PR#123", before, 30):
            raise RuntimeError("LINE nudge did not arrive")
        self.mark("line:nudge arrived")
        await self.cap("ask", 2.5)
        await self.cap("accept")
        replies = await self.phone_do(ph.count, r"ส่งข้อความเตือน")
        self.mark("line:tap accept")
        if not await self.phone_do(
            ph.tap_until, r"^ช่วยเตือนให้หน่อย$", r"ส่งข้อความเตือน", replies, 3, 10
        ):
            raise RuntimeError("LINE did not answer the tapped button")
        await self.wait(2.5)
        await self.click(p.locator(".member-tabs button", has_text="พี่สมชาย"), "tab Somchai")
        await self.cap("nudge", 5.5)
        await self.click(p.locator(".member-tabs button", has_text="มิ้น"), "tab Mint")
        await self.wait(1.5)

        await self.cap("share")
        # One paste: Universal Clipboard needs a moment to reach the phone, so quick pastes repeat older text.
        for attempt in range(3):
            await self.phone_do(ph.tap, *ph.rel(0.42, 0.931))
            await self.wait(0.8)
            await self.phone_do(paste, FEEDBACK)
            await asyncio.sleep(1.5)
            typed = "".join(t[0] for t in await self.phone_do(ph.read)).replace(" ", "")
            if typed.count("หนูไม่กล้า") == 1 and "ยกเลิกนัด" in typed and "วันศุกร์" in typed:
                break
            await asyncio.to_thread(lambda: [(_key(51, True), _key(51, False)) for _ in range(90)])
            if attempt == 2:
                raise RuntimeError("feedback text did not reach the LINE input")
        self.mark("line:typed feedback")
        await self.wait(1.5)
        cards = await self.phone_do(ph.count, r"^ย.นยันส่ง$|ตรวจสอบก่อนส่ง")
        input_y = ph.rel(0, 0.88)[1]
        for _ in range(3):
            await self.phone_do(ph.tap, *ph.rel(0.925, 0.931))
            await asyncio.sleep(2)
            typed = await self.phone_do(ph.find, r"หนูไม่กล้า")
            if not typed or typed[2] < input_y:  # the text left the input box
                break
        self.mark("line:sent feedback")
        await self.cap("pipeline")
        if not await self.phone_do(ph.wait_more, r"^ย.นยันส่ง$|ตรวจสอบก่อนส่ง", cards, 240):
            raise RuntimeError("LINE preview card did not arrive")
        self.mark("line:preview card")
        await self.wait(1.5)
        # Show the top of the card (removed words) if the chat scrolled past it.
        # The wheel direction depends on the Mac's scroll setting: if the card's button does not move down, flip it.
        sign, scrolled = 1, 0
        for _ in range(5):
            if await self.phone_do(ph.find, r"ร่องรอยที่ตัดออก"):
                break
            ref = await self.phone_do(ph.find, r"ตรวจสอบก่อนส่ง|ยืนยันส่ง|ยกเลิก")
            await asyncio.to_thread(locked_glide, *ph.rel(0.5, 0.45), 0.4)
            await asyncio.to_thread(locked_wheel, 3 * sign)
            await asyncio.sleep(0.8)
            moved = await self.phone_do(ph.find, r"ตรวจสอบก่อนส่ง|ยืนยันส่ง|ยกเลิก")
            if ref and moved and moved[2] <= ref[2] + 4:
                sign = -sign  # hit the bottom: the other way reveals older content
            else:
                scrolled += 3 * sign
        hit = await self.phone_do(ph.find, r"ร่องรอยที่ตัดออก")
        if hit:
            await asyncio.to_thread(locked_glide, ph.box[0] + ph.box[2] * 0.3, hit[2] + 22, 0.5)
        await self.cap("markers", 3)
        hit = await self.phone_do(ph.find, r"ทดสอบเดาตัวตน")
        if hit:
            await asyncio.to_thread(locked_glide, hit[1], hit[2], 0.5)
        await self.cap("attacker", 3)
        await asyncio.to_thread(locked_glide, *ph.rel(0.5, 0.6), 0.3)
        if scrolled:
            await asyncio.to_thread(locked_wheel, -scrolled - (4 if scrolled > 0 else -4))
        await self.wait(1)
        await self.cap("confirm")
        done = await self.phone_do(ph.count, r"ย.นยันแล้ว")
        self.mark("line:tap confirm")
        if not await self.phone_do(ph.tap_until, r"^ย.นยันส่ง$", r"ย.นยันแล้ว", done, 2, 20):
            raise RuntimeError("LINE did not confirm the draft")
        await self.wait(2)

        gate = p.locator(".gate-bar")
        await p.locator("#gate:not([hidden])").wait_for(timeout=20_000)
        await self.hover(p.locator("#gate"))
        await self.spot(gate)
        await self.cap("gate", 3)
        await self.click(p.locator("#teammates"), "teammates")
        await self.cap("teammates")
        await p.locator("#gate-count", has_text="3/").wait_for(timeout=300_000)
        self.mark("web:gate 3/3")
        await self.wait(4)

        await self.go("manager")
        await self.cap("manager")
        await p.locator(".reply-form").first.wait_for(timeout=240_000)
        self.mark("web:theme released")
        card = p.locator(".theme-card").first
        await self.spot(card)
        await self.hover(card.locator(".theme-title"))
        await self.wait(3)
        proposal = card.locator(".proposal").first
        if await proposal.count():
            await self.hover(proposal)
            await self.spot(proposal)
        await self.cap("proposal", 3)
        box = p.locator(".reply-form textarea").first
        await self.click(box, "reply box", ring=False)
        await box.press_sequentially(REPLY, delay=35)
        await self.click(
            p.locator('.reply-form input[name="accept_proposal"]').first, "accept proposal"
        )
        await self.cap("reply", 1.5)
        heard = await self.phone_do(ph.count, r"15:00|คำตอบจาก")
        await self.click(p.locator('.reply-form button[type="submit"]').first, "send reply")
        await asyncio.to_thread(locked_glide, *ph.rel(0.5, 0.62), 0.8)
        if await self.phone_do(ph.wait_more, r"15:00|คำตอบจาก", heard, 40):
            self.mark("line:manager reply arrived")
        await self.cap("heard", 5)

        await self.go("demo")
        await self.click(p.locator("#advance"), "advance 2 weeks")
        await self.wait(4)
        await self.go("manager")
        followup = p.locator(".followup").first
        await followup.wait_for(timeout=20_000)
        await self.hover(followup)
        await self.spot(followup)
        await self.cap("followup", 7)

    # -------------------------------------------------------- web take

    async def run_web(self):
        p = self.p
        await self.cap("intro", 3)
        # Hold still: the home page barely overflows the window, so wheel scrolls only
        # rubber-band it on macOS and the shot jitters.
        await self.wait(8)

        await self.go("demo")
        await self.cap("console")
        await self.click(p.locator("#reset"), "reset demo")
        await self.wait(2.5)
        await self.click(p.locator(".member-tabs button", has_text="มิ้น"), "tab Mint")
        await self.cap("pr")
        await self.click(p.locator('button[data-scenario="pr_stale"]'), "scenario PR stale")
        await self.wait(4)
        await self.cap("ask", 2)
        await self.click(
            p.locator(".line-chat button", has_text="ช่วยเตือนให้หน่อย").first, "web: accept nudge"
        )
        await self.wait(3)
        await self.click(p.locator(".member-tabs button", has_text="พี่สมชาย"), "tab Somchai")
        await self.cap("nudge", 5)
        await self.click(p.locator(".member-tabs button", has_text="มิ้น"), "tab Mint")
        await self.wait(1)

        await self.cap("share")
        box = p.locator("#feedback-text")
        await self.click(box, "feedback box", ring=False)
        await box.fill("")
        await box.press_sequentially(FEEDBACK, delay=30)
        await self.wait(1.5)
        confirm = p.get_by_role("button", name="ยืนยันส่งความเห็น")
        for attempt in range(3):
            await self.click(p.locator("#preview"), "run privacy pipeline")
            if attempt == 0:
                await self.cap("pipeline")
            try:
                await confirm.wait_for(timeout=200_000)
                break
            except Exception:
                if attempt == 2:
                    raise
        await self.wait(1)
        markers = p.locator("#removed-markers")
        if await markers.is_visible():
            await self.hover(markers)
            await self.spot(markers)
        await self.cap("markers", 3)
        rounds = p.locator("#attacker-rounds")
        await self.hover(rounds)
        await self.spot(rounds)
        await self.cap("attacker", 3)
        preview = p.locator("#feedback-preview")
        if await preview.is_visible():
            await self.hover(preview)
            await self.spot(preview)
            await self.wait(3)
        await self.cap("confirm")
        await self.click(confirm, "confirm feedback")
        await self.wait(2.5)
        await self.spot(p.locator(".gate-bar"))
        await self.cap("gate", 3)
        await self.click(p.locator("#teammates"), "teammates")
        await self.cap("teammates")
        await p.locator("#gate-count", has_text="3/").wait_for(timeout=300_000)
        await self.wait(4)

        await self.go("manager")
        await self.cap("manager")
        await p.locator(".reply-form").first.wait_for(timeout=240_000)
        card = p.locator(".theme-card").first
        await self.spot(card)
        await self.hover(card.locator(".theme-title"))
        await self.cap("proposal", 4)
        box = p.locator(".reply-form textarea").first
        await self.click(box, "reply box", ring=False)
        await box.press_sequentially(REPLY, delay=35)
        await self.click(
            p.locator('.reply-form input[name="accept_proposal"]').first, "accept proposal"
        )
        await self.cap("reply", 1.5)
        await self.click(p.locator('.reply-form button[type="submit"]').first, "send reply")
        await self.wait(3)

        await self.go("demo")
        await self.click(p.locator(".member-tabs button", has_text="มิ้น"), "tab Mint")
        await self.spot(p.locator(".inbox-panel"))
        await self.cap("heard", 5)
        await self.click(p.locator("#advance"), "advance 2 weeks")
        await self.wait(4)
        await self.go("manager")
        followup = p.locator(".followup").first
        await followup.wait_for(timeout=20_000)
        await self.hover(followup)
        await self.spot(followup)
        await self.cap("followup", 7)

        await self.p.goto(ARCHITECTURE)
        self.mark("page", url="architecture")
        await self.wait(1.5)
        await self.cap("outro", 4)
        await self.cap("line", 4)

    # -------------------------------------------------------- sidecars

    def write_sidecars(self, out: Path):
        end = self.now()
        lines = []
        for i, cue in enumerate(self.cues):
            stop = self.cues[i + 1]["start"] if i + 1 < len(self.cues) else end
            stop = max(cue["start"] + 0.83, min(stop, cue["start"] + 7.0))
            lines += [str(i + 1), f"{srt(cue['start'])} --> {srt(stop)}", cue["en"], cue["th"], ""]
        out.with_suffix(".srt").write_text("\n".join(lines), encoding="utf-8")
        out.with_suffix(".events.json").write_text(
            json.dumps(self.events, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def srt(seconds):
    ms = round(max(0.0, seconds) * 1000)
    return f"{ms // 3_600_000:02}:{ms // 60_000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("take", choices=["line", "web"])
    ap.add_argument("--out", default=str(ROOT.parent / "LiveDemo_Videos/take"))
    ap.add_argument("--dry", action="store_true", help="run the story without recording the screen")
    ap.add_argument(
        "--keep-chat",
        action="store_true",
        help="line take: do not delete the LINE chat history first",
    )
    args = ap.parse_args()
    out = Path(args.out).resolve()  # noqa: ASYNC240 - one-off recording script
    out.parent.mkdir(parents=True, exist_ok=True)
    line = args.take == "line"

    phone = None
    if line:
        osa('tell application "System Events" to tell process "iPhone Mirroring" '
            f"to set position of window 1 to {{{WEB_W + 20}, {FRAME_Y + 16}}}")  # fmt: skip
        await asyncio.sleep(0.5)
        phone = Phone()
        if not phone.find(r"Kreng-jaiBridge"):
            raise SystemExit("open the Kreng-jai Bridge chat in LINE on iPhone Mirroring first")
        if not args.keep_chat:
            phone.clear_chat()
    width = WEB_W if line else FRAME_W
    start_url = f"{BASE}/{'demo' if line else ''}?rec=1"

    async with async_playwright() as pw:
        common = ["--force-device-scale-factor=2", "--hide-scrollbars", "--disable-infobars"]
        background = None
        if line:
            # A persistent context opens the --app window itself (launch() starts with no window).
            background = await pw.chromium.launch_persistent_context(
                tempfile.mkdtemp(),
                headless=False,
                no_viewport=True,
                args=[f"--app=data:text/html,<body style='margin:0;background:{BG}'>",
                      f"--window-position={WEB_W},{FRAME_Y - TITLE_BAR}",
                      f"--window-size={FRAME_W - WEB_W},{FRAME_H + TITLE_BAR}", *common],
                ignore_default_args=["--enable-automation"],
            )  # fmt: skip
        ctx = await pw.chromium.launch_persistent_context(
            tempfile.mkdtemp(),
            headless=False,
            no_viewport=True,
            args=[f"--app={start_url}", f"--window-position=0,{FRAME_Y - TITLE_BAR}",
                  f"--window-size={width},{FRAME_H + TITLE_BAR}", *common],
            ignore_default_args=["--enable-automation"],
        )  # fmt: skip
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.wait_for_load_state("networkidle")
        await page.evaluate("document.fonts.ready.then(() => true)")
        if line:
            await asyncio.sleep(1)
            activate("iPhone Mirroring")
        await asyncio.sleep(1.5)

        recorder = Recorder(out.with_suffix(".raw.mp4"))
        if not args.dry:
            recorder.start()
        t0 = time.monotonic()
        take = Take(page, phone, lambda: recorder.t0 or t0)

        async def keep_phone_awake(ph: Phone):
            while True:
                await asyncio.to_thread(ph.keepalive)
                await asyncio.sleep(5)

        awake = asyncio.create_task(keep_phone_awake(phone)) if phone else None
        try:
            await take.wait(1.5)
            await (take.run_line() if line else take.run_web())
            await take.wait(2)
        finally:
            if awake:
                awake.cancel()
            take.write_sidecars(out)
            recorder.stop()
            await ctx.close()
            if background:
                await background.close()

    if not args.dry:
        top = FRAME_Y * 2
        subprocess.run(  # noqa: ASYNC221 - offline crop after the browser closes
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(out.with_suffix(".raw.mp4")),
             "-vf", f"crop=3840:2160:0:{top}", "-c:v", "h264_videotoolbox", "-b:v", "40M",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out.with_suffix(".mp4"))],
            check=True,
        )  # fmt: skip
    print(f"saved {out.with_suffix('.mp4')} (+ .raw.mp4, .srt, .events.json)")


if __name__ == "__main__":
    asyncio.run(main())
