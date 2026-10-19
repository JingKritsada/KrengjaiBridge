# /// script
# requires-python = ">=3.12"
# dependencies = ["python-docx>=1.1,<2", "python-pptx>=1.0,<2", "lxml>=5,<7"]
# ///
"""Build the official submission templates; optionally render previews with --render.

Run from any directory: uv run docs/submission/build_submission.py [--render].
Templates default to the repository's parent directory; --template-dir overrides it.
Evaluation values are read afresh from results.json, never copied into this script.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn as wqn
from docx.shared import Cm, Pt as WPt
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement as AElement
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ASSETS = HERE / "assets"
EVAL = ROOT / "eval/results"
NAVY, BLUE, VIOLET, CYAN, GREEN, RED = (
    "1d2742", "3157d5", "6b4fd8", "19a7c9", "1f6f5c", "c7362f"
)
MAPPING = {
    "tests_passed": ("tests_passed", "integer"),
    "stylo_before": ("privacy.attackers.stylometric.before", "percent"),
    "stylo_after": ("privacy.attackers.stylometric.after", "percent"),
    "llm_before": ("privacy.attackers.llm_attacker.before", "percent"),
    "llm_after": ("privacy.attackers.llm_attacker.after", "percent"),
    "gender_before": ("privacy.attackers.gender.before", "percent"),
    "gender_after": ("privacy.attackers.gender.after", "percent"),
    "gender_base": ("privacy.attackers.gender.baseline", "percent"),
    "senior_before": ("privacy.attackers.seniority.before", "percent"),
    "senior_after": ("privacy.attackers.seniority.after", "percent"),
    "leak_before": ("privacy.attackers.marker_leak.before", "percent"),
    "leak_after": ("privacy.attackers.marker_leak.after", "percent"),
    "meaning": ("privacy.meaning.fraction_ge_4", "percent"),
    "ok_rate": ("privacy.pipeline.ok_rate", "percent"),
    "p50": ("privacy.pipeline.latency.p50_seconds", "decimal"),
    "ari": ("theme.released_only.ari", "decimal4"),
    "theme_acc": ("theme.released_only.assign_theme_accuracy", "percent"),
    "recall": ("engine.recall.mean", "percent"),
    "precision": ("engine.precision.mean", "percent"),
    "delay": ("engine.median_detection_delay_minutes.mean", "decimal"),
}


def value(data, path, kind="percent"):
    node = data
    try:
        for key in path.split("."):
            node = node[key]
        if isinstance(node, bool) or not isinstance(node, (int, float)) or not math.isfinite(node):
            raise ValueError(path)
    except (KeyError, TypeError, ValueError):
        return f"[[TODO: missing result {path}]]"
    return {
        "percent": lambda: f"{node * 100:.1f}%",
        "decimal": lambda: f"{node:.2f}",
        "decimal4": lambda: f"{node:.4f}",
        "integer": lambda: str(int(node)),
    }[kind]()


def substitute(text, data):
    return re.sub(r"\{\{(.*?)\}\}", lambda m: value(data, *MAPPING[m[1]])
                  if m[1] in MAPPING else f"[[TODO: unmapped {m[1]}]]", text)


def section(text, heading):
    depth = len(heading.split(" ", 1)[0])
    return re.search(r"^" + re.escape(heading) + r"\n(.*?)(?=^#{1," + str(depth) + r"} |\Z)",
                     text, re.M | re.S)[1].strip()


def doc_runs(paragraph, text):
    # Preserve source emphasis and highlight every unresolved field.
    for token in re.split(r"(\[\[TODO.*?\]\]|\*\*.*?\*\*|`[^`]+`)", text):
        if not token:
            continue
        clean = token.strip("*`") if not token.startswith("[[") else token
        clean = re.sub(r"\*([^*]+)\*", r"\1", clean)
        for segment in re.split(r"([\u0e00-\u0e7f]+)", clean):
            if not segment:
                continue
            run = paragraph.add_run(segment)
            run.font.name = "Leelawadee UI" if re.search(r"[\u0e00-\u0e7f]", segment) else "Arial"
            run.font.size = WPt(12)
            run.bold = token.startswith("**")
            fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
            fonts.set(wqn("w:eastAsia"), "Leelawadee UI")
            fonts.set(wqn("w:cs"), "Leelawadee UI")
            if token.startswith("[[TODO"):
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def add_doc_text(cell, text, before=None):
    for block in re.split(r"\n\s*\n", text.strip()):
        # Each source list item is a separate paragraph; keep all its text.
        for line in block.splitlines() if any(re.match(r"(?:- |\d+\. )", ln) for ln in block.splitlines()) else [block.replace("\n", " ")]:
            p = cell.add_paragraph()
            p.paragraph_format.space_after = WPt(6)
            p.paragraph_format.line_spacing = 1.02
            doc_runs(p, line.removeprefix("- "))
            if before is not None:
                before.addprevious(p._p)


def remove_empty(cell):
    for p in list(cell.paragraphs):
        if not p.text.strip() and not p._p.xpath(".//w:drawing"):
            p._p.getparent().remove(p._p)


def build_form(template, source, data):
    doc = Document(template)
    table = doc.tables[0]
    floating = table._tbl.tblPr.find(wqn("w:tblpPr"))
    if floating is not None:
        table._tbl.tblPr.remove(floating)
    # The supplied 18.75 cm table exceeds its A4 text area; fit its original widths.
    for sec in doc.sections:
        sec.left_margin = Cm(1.1)
        sec.right_margin = Cm(1.1)
        sec.top_margin = Cm(1.3)
        sec.bottom_margin = Cm(1.3)
    fields = dict(re.findall(r"^- ([^:\n]+): (.*)$", source, re.M))
    rows = {label: row for row in table.rows for label in [row.cells[0].text.strip()]}
    for label in ("University Name", "Team Name", "Team Leader Tel", "Team Leader Email", "Team Group Photo",
                  "Entry Name", "Applicable Fields", "Technologies Used"):
        cell = rows[label].cells[1]
        remove_empty(cell)
        add_doc_text(cell, fields[label])
    # The member header and detail rows are separate in the actual official file.
    member_row = table.rows[4]
    add_doc_text(member_row.cells[1], fields["Instructor (1 person)"])
    student_source = fields["Students (max 3)"]
    names = re.search(r"— (.*?) \(from", student_source)
    student_names = names[1].split(", ") if names else []
    for i in range(3):
        add_doc_text(member_row.cells[i + 2], f"[[TODO: confirm — {student_names[i]}; add English name]]"
                     if i < len(student_names) else "[[TODO: student name]]")
    intro = rows["Entry Introduction"].cells[1]
    remove_empty(intro)
    prompt2 = next(p._p for p in intro.paragraphs if p.text.startswith("2."))
    part1 = section(source, "### 1. Background and value (≤ 500 words)")
    part2 = section(source, "### 2. Huawei Cloud across the development lifecycle (≤ 1,000 words)")
    add_doc_text(intro, part1, prompt2)
    add_doc_text(intro, part2)
    words = [len(re.sub(r"[*`]", "", p).split()) for p in (part1, part2)]
    assert words[0] <= 500 and words[1] <= 1000, f"Introduction exceeds word limits: {words}"

    tech = rows["Technical Solution Introduction"].cells[1]
    remove_empty(tech)
    instructions = [p for p in tech.paragraphs if not p.text.startswith("Module ")]
    for p in list(tech.paragraphs):
        if p.text.startswith("Module "):
            p._p.getparent().remove(p._p)
    technical = section(source, "## Technical Solution Introduction")
    overall, modules = technical.split("**Module 1", 1)
    modules, results = ("**Module 1" + modules).split("**Results (measured).**", 1)
    add_doc_text(tech, overall, instructions[1]._p)
    picture_p = tech.add_paragraph()
    picture_p.add_run().add_picture(str(ASSETS / "architecture.png"), width=Cm(15))
    instructions[1]._p.addprevious(picture_p._p)
    add_doc_text(tech, modules, instructions[2]._p)
    # Explicitly label the mixed denominators rather than implying all results use one set.
    results = results.replace("Theme clustering ARI", "Released-text theme clustering ARI")
    results = results.replace("theme assignment accuracy", "released-text theme assignment accuracy")
    add_doc_text(tech, "**Results (measured).**" + results)
    add_doc_text(tech,
        "**Evaluation limits (SYNTHETIC).** All-output privacy and meaning metrics include blocked outputs. "
        "Theme ARI and assignment accuracy above use released texts only. Independent LLM attribution remains "
        "above chance; these measurements do not establish anonymity. Meaning preservation is incomplete. "
        "Native threshold clustering fragments the data. Shared model-family generation, rewriting, attack "
        "and judging can bias results. Detection measures rules plus deterministic context filtering, not "
        "the LLM context judge or human usefulness; zero median delay does not mean instant detection. "
        "Latency uses ten serial uncached pipelines with dated measurements reused on reruns. "
        "Real volunteers, independent attacks and human utility ratings are next.")
    demo = rows["Entry Demonstration"].cells[1]
    remove_empty(demo)
    add_doc_text(demo, section(source, "## Entry Demonstration"))
    for image, caption in [("screen-manager.png", "Manager dashboard — https://119-13-81-32.sslip.io/manager"),
                           ("screen-inbox.png", "Private LINE-style inbox — https://119-13-81-32.sslip.io/demo")]:
        p = demo.add_paragraph()
        p.paragraph_format.keep_with_next = True
        doc_runs(p, caption)
        p = demo.add_paragraph()
        p.add_run().add_picture(str(ASSETS / image), width=Cm(7.5))
    # Keep template instruction text and formatting; remove inherited row minimums.
    for row in table.rows:
        row.height = None
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.widow_control = True
    output = HERE / "Entry_Form_KrengjaiBridge.docx"
    doc.save(output)
    print(f"FORM words part1={words[0]}/500 part2={words[1]}/1000 (whitespace count)")
    return output


def rgb(color):
    return RGBColor.from_string(color)


def slide_runs(p, text, size, color=NAVY, bold=False, highlight=False):
    # Segment Thai explicitly so Windows sets both complex-script and East Asian fonts.
    for token in re.split(r"([\u0e00-\u0e7f]+)", text):
        if not token:
            continue
        r = p.add_run()
        r.text = token
        r.font.name = "Leelawadee UI" if re.search(r"[\u0e00-\u0e7f]", token) else "Arial"
        r.font.size, r.font.bold, r.font.color.rgb = Pt(size), bold, rgb(color)
        if re.search(r"[\u0e00-\u0e7f]", token):
            pr = r._r.get_or_add_rPr()
            for tag in ("a:ea", "a:cs"):
                el = AElement(tag)
                el.set("typeface", "Leelawadee UI")
                pr.append(el)
        if highlight:
            el = AElement("a:highlight")
            fill = AElement("a:srgbClr")
            fill.set("val", "FFF176")
            el.append(fill)
            pr = r._r.get_or_add_rPr()
            latin = next((c for c in pr if c.tag.endswith("}latin")), None)
            pr.insert(list(pr).index(latin) if latin is not None else len(pr), el)


def textbox(slide, text, x, y, w, h, size=18, color=NAVY, bold=False):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    # Conservative line estimate (Thai has no word spaces); explicit newlines are honoured.
    def lines_at(s):
        return sum(max(1, math.ceil(sum(1.05 if '\u0e00' <= c <= '\u0e7f' else .54 for c in line) * s / (w * 72)))
                   for line in text.splitlines())
    while size > 14 and lines_at(size) * size * 1.28 > h * 72:
        size -= 1
    for i, line in enumerate(text.splitlines()):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(6)
        p.line_spacing = 1.12
        for token in re.split(r"(\[\[TODO.*?\]\])", line):
            slide_runs(p, token, size, color, bold, token.startswith("[[TODO"))
    return box


def panel(slide, x, y, w, h, fill="FFFFFF"):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    s.line.fill.background()
    return s


def picture(slide, path, x, y, w, h):
    # png dimensions from IHDR: no extra image dependency beyond python-pptx.
    import struct
    iw, ih = struct.unpack(">II", Path(path).read_bytes()[16:24])
    scale = min(w / iw, h / ih)
    pw, ph = iw * scale, ih * scale
    return slide.shapes.add_picture(str(path), Inches(x + (w - pw) / 2), Inches(y + (h - ph) / 2),
                                    width=Inches(pw), height=Inches(ph))


def footer(slide, text):
    textbox(slide, text, .55, 6.45, 12.05, .35, 12, color="4C5570")


def build_deck(template, data, deck_source):
    prs = Presentation(template)
    # Retain original title slide; drop the three unused original slides and relationships.
    for sid in list(prs.slides._sldIdLst)[1:]:
        prs.part.drop_rel(sid.rId)
        prs.slides._sldIdLst.remove(sid)
    layout = next(l for l in prs.slide_layouts if l.name == "自定义版式")
    end_layout = next(l for l in prs.slide_layouts if l.name == "结束页")
    specifications = re.split(r"^\d+\. \*\*", deck_source, flags=re.M)[1:]
    assert len(specifications) == 15, "Expected the 15-slide source specification"
    def content(title):
        s = prs.slides.add_slide(layout)
        textbox(s, title, .55, .40, 12.15, .65, 30, bold=True)
        return s
    def metric(key):
        return value(data, *MAPPING[key])
    def stat(s, number, label, x, y, w=3.6, size=44):
        textbox(s, number, x, y, w, .75, size, BLUE, True)
        textbox(s, label, x, y + .85, w, .65, 17)
    s = prs.slides[0]
    for shape in s.shapes:
        if not shape.has_text_frame:
            continue
        text = ("Huawei ICT Competition 2026–2027\nInnovation Competition"
                if "Huawei ICT" in shape.text else
                "Chulalongkorn University · [[TODO: team name]] · Kreng-jai Bridge")
        if "School Name" in shape.text:
            shape.left, shape.top, shape.width, shape.height = Inches(.55), Inches(2.18), Inches(12.2), Inches(.55)
        tf = shape.text_frame
        tf.clear()
        for i, line in enumerate(text.splitlines()):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = PP_ALIGN.CENTER
            for token in re.split(r"(\[\[TODO.*?\]\])", line):
                slide_runs(p, token, 30 if "Competition" in line else 20, NAVY, True, token.startswith("[[TODO"))
    textbox(s, "An AI agent that speaks up for Thai teams", .55, 2.85, 12.0, .45, 24, bold=True)
    textbox(s, "With attacker-tested Thai feedback privacy", .55, 6.4, 10.2, .4, 20)
    # The original subtitle promises untraceability; the report expressly rejects that claim.

    s = content("The problem nobody says out loud")
    for i, (num, line) in enumerate([
        ("01", "PR waits 3 days; the junior won’t chase"),
        ("02", "A blocker stays unsaid in stand-up"),
        ("03", "Urgent work lands Friday at 17:30")]):
        y = 1.55 + i * 1.35
        panel(s, .55, y, 7.0, 1.05)
        textbox(s, num, .8, y + .20, .7, .6, 28, VIOLET, True)
        textbox(s, line, 1.65, y + .24, 5.6, .65, 20)
    stat(s, "50%", "lose >10 h/week to non-coding friction", 8.3, 1.65)
    stat(s, "63%", "say leaders don’t understand their problems", 8.3, 3.8)
    footer(s, "Atlassian DevEx 2025 · Kreng-jai keeps teams polite — and problems unsaid.")

    s = content("Why anonymous tools fail in Thai")
    panel(s, .55, 1.45, 7.2, 3.6)
    quote = "หนูไม่กล้าบอกพี่หัวหน้าค่ะ ว่าสั่งงานเย็นวันศุกร์ทำให้หนูต้องยกเลิกนัดตลอด"
    box = textbox(s, "", .85, 1.8, 6.6, 1.9, 24)
    p = box.text_frame.paragraphs[0]
    for token in re.split("(หนู|ค่ะ|พี่)", quote):
        slide_runs(p, token, 24, RED if token in {"หนู", "ค่ะ", "พี่"} else NAVY)
    textbox(s, "One word can reveal gender + seniority", .85, 4.0, 6.5, .8, 24, RED, True)
    textbox(s, "Small teams make writers guessable\nQuarterly surveys arrive too late\nTools wait for people to speak", 8.2, 1.8, 4.5, 3.4, 22)

    s = content("The agent takes the hard-to-say role")
    for i, (title, body) in enumerate([
        ("Observe", "SDLC metadata only"), ("Ask", "Private LINE message\nThe person decides"),
        ("Act", "Neutral reminder or\nanonymous feedback")]):
        x = .55 + i * 4.22
        panel(s, x, 2.05, 3.8, 2.65)
        textbox(s, str(i + 1), x + .25, 2.3, .7, .7, 42, CYAN, True)
        textbox(s, title, x + 1, 2.45, 2.5, .6, 28, BLUE, True)
        textbox(s, body, x + .3, 3.4, 3.2, 1.0, 22)
    footer(s, "A bot has no seniority, no face to lose, no debt to anyone.")

    s = content("Demo story: two weeks of Mint")
    events = ["Tue · PR #123", "Thu · 48 h trigger", "Private LINE ask", "Reminder; no requester name",
              "Fri · Feedback", "k = 3 reached", "Mon · 15:00 cut-off accepted", "+2 weeks · Late-Friday work 3 → 0"]
    for i, line in enumerate(events):
        col, row = i // 4, i % 4
        x, y = .55 + col * 4.05, 1.45 + row * 1.12
        panel(s, x, y, 3.8, .92)
        textbox(s, f"{i + 1:02}", x + .18, y + .18, .6, .5, 22, VIOLET, True)
        textbox(s, line, x + .85, y + .17, 2.75, .65, 17)
    picture(s, ASSETS / "screen-inbox.png", 9.1, 1.3, 3.25, 4.9)
    footer(s, "SYNTHETIC demo scenario · The 3 → 0 follow-up is simulated.")

    s = content("Six privacy steps, tested by an attacker")
    steps = ["Remove identifiers", "Neutralize Thai markers", "Rewrite ⇄ attacker", "Situation / impact / request", "k-gate: 3 people", "Cluster themes"]
    for i, line in enumerate(steps):
        x, y = .55 + (i % 3) * 3.05, 1.45 + (i // 3) * 1.03
        panel(s, x, y, 2.85, .8)
        textbox(s, f"{i + 1}. {line}", x + .15, y + .15, 2.55, .55, 17, BLUE, True)
    textbox(s, "หนู / ค่ะ / พี่ →", .7, 3.72, 8.4, .48, 22, RED, True)
    textbox(s, "สถานการณ์: มีการมอบหมายงานในช่วงเย็นวันศุกร์\nผลกระทบ: ต้องยกเลิกนัดหมายส่วนตัวอย่างต่อเนื่อง\nสิ่งที่ขอ: พิจารณาปรับกระบวนการวางแผนงาน", .7, 4.32, 8.5, 1.7, 20)
    picture(s, ASSETS / "screen-pipeline.png", 9.8, 1.35, 2.8, 4.9)
    footer(s, "The user previews and confirms; an unsafe rewrite is blocked.")

    s = content("Results: measure privacy, acknowledge the limits")
    picture(s, EVAL / "attacker_before_after.png", .55, 1.45, 8.15, 4.65)
    for i, (number, label) in enumerate([
        (metric("stylo_after"), f"author identified by stylometry (was {metric('stylo_before')}; chance 5%)"),
        (metric("gender_after"), f"gender guessed correctly (was {metric('gender_before')}; chance 50%)"),
        (metric("leak_after"), f"texts with Thai gender/seniority markers (was {metric('leak_before')})")]):
        stat(s, number, label, 9.05, 1.35 + i * 1.62, 3.7, 40)
    footer(s, f"SYNTHETIC · 20 personas × 12 messages; 80 test outputs · LLM attacker {metric('llm_after')} vs "
           f"{value(data, 'privacy.attackers.llm_attacker.chance')} chance. No anonymity guarantee.")

    s = content("Results: detection and meaning")
    picture(s, EVAL / "engine.png", .55, 1.45, 7.15, 4.55)
    stat(s, metric("meaning"), "meaning judged ≥ 4/5; all 80 outputs", 8.0, 1.4, 4.5, 42)
    stat(s, metric("ari"), "fixed-k theme ARI; released texts only", 8.0, 3.05, 4.5, 42)
    textbox(s, f"{metric('p50')} s p50 · {metric('ok_rate')} pass\nTheme assignment: {metric('theme_acc')} released", 8.0, 4.95, 4.7, .95, 19)
    footer(s, "SYNTHETIC · Rules + deterministic context; 15-min ticks. Zero median ≠ instant. Native clustering fragments; timing n=10.")

    s = content("The manager loop closes the circle")
    picture(s, ASSETS / "screen-manager.png", .55, 1.32, 7.2, 4.9)
    for i, line in enumerate(["Themes shown as ranges: 3–5 people", "AI-drafted proposal", "Reply through an anonymous token", "Follow-up metric: before → after"]):
        panel(s, 8.05, 1.6 + i * 1.05, 4.65, .85)
        textbox(s, line, 8.28, 1.78 + i * 1.05, 4.15, .6, 19)
    footer(s, "From a concern to a manager response and a measurable follow-up.")

    s = content("Architecture on Huawei Cloud")
    picture(s, ASSETS / "architecture.png", .55, 1.2, 12.15, 5.0)
    footer(s, "Current: ECS + container PostgreSQL/Redis · Next: managed RDS/DCS and ModelArts MaaS inference.")

    s = content("Built with agents on Huawei Cloud")
    lifecycle = [("Requirement", "Contract first"), ("Code generation", "Parallel agents"),
                 ("Build", "FastAPI + Docker"), ("Troubleshoot", "Region / IAM fixes"), ("Deploy", "ECS + Caddy + LINE")]
    for i, (title, body) in enumerate(lifecycle):
        x = .55 + i * 2.46
        panel(s, x, 1.85, 2.28, 2.25)
        textbox(s, str(i + 1), x + .18, 2.08, 1, .7, 40, CYAN, True)
        textbox(s, title, x + .18, 2.95, 1.95, .52, 18, BLUE, True)
        textbox(s, body, x + .18, 3.5, 1.95, .5, 16)
    textbox(s, "Provisioning skill: VPC · ECS · RDS · DCS", .7, 4.7, 11.8, .65, 26, VIOLET, True)
    textbox(s, "skills/huawei-cloud-provision · RDS/DCS await IAM permissions", .7, 5.5, 11.8, .5, 18)

    s = content("Privacy by design: PDPA considerations")
    rules = ["Metadata only", "Opt-in", "Individual signals stay private", "Originals deleted", "Hashed identities; encrypted tokens", "Honest limits for small teams"]
    for i, line in enumerate(rules):
        x, y = .55 + (i % 3) * 4.22, 1.6 + (i // 3) * 2.15
        panel(s, x, y, 3.8, 1.8)
        textbox(s, f"{i + 1:02}", x + .22, y + .18, .8, .7, 40, GREEN, True)
        textbox(s, line, x + .22, y + 1.0, 3.35, .65, 20)
    footer(s, "Design principles; no legal compliance certification is claimed.")

    s = content("Why we win: nobody acts for the employee")
    # Gaps as found in the team's concept research (docs: concept study, competitor section).
    headers = ["Category", "Examples", "What is missing for Thai teams"]
    widths = [2.6, 3.3, 5.9]
    table = s.shapes.add_table(6, 3, Inches(.55), Inches(1.4), Inches(11.8), Inches(4.1)).table
    for c, width in zip(table.columns, widths): c.width = Inches(width)
    rows = [headers,
            ["Anonymous surveys", "Officevibe, TINYpulse, Lattice", "Wait for people to fill in; no style hiding; no Thai/LINE; no automatic follow-up"],
            ["Burnout analytics", "Viva Insights, Uplevel, Erudit", "Read message content (privacy criticism); do not act for the employee"],
            ["Engineering metrics", "LinearB, Swarmia", "Process alerts, but not designed around kreng-jai; no anonymous channel"],
            ["Thai HR systems", "HumanSoft, HONO, MiHCM", "Payroll, leave, appraisal forms; AI still on the roadmap"],
            ["Kreng-jai Bridge", "this prototype", "Acts for the employee · attacker-tested anonymity* · Thai + LINE · follow-up metrics"]]
    for i, row in enumerate(rows):
        for j, text in enumerate(row):
            cell = table.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb("E8EDFC" if i == 0 else "E5F4EF" if i == 5 else "FFFFFF")
            cell.margin_left = Inches(.13)
            cell.margin_top = Inches(.1)
            p = cell.text_frame.paragraphs[0]
            slide_runs(p, text, 15, NAVY, i in (0, 5))
    textbox(s, "*Attacker-tested on SYNTHETIC data; anonymity is not established.", .55, 5.7, 12.0, .4, 15)
    footer(s, "Competitor gaps from our desk research (public product pages and press, Oct 2026); to be re-verified before the regional stage.")

    s = content("Roadmap: validate with real teams")
    for i, (title, body) in enumerate([
        ("Now", "Working demo\nSYNTHETIC evaluation"),
        ("Next 4 weeks", "Pilot: 2 teams; volunteer data\nMaaS DeepSeek / Typhoon 2\nRDS / DCS; CodeArts CI"),
        ("Later", "Lark\nMulti-tenant\nCalendar signals")]):
        x = .55 + i * 4.22
        panel(s, x, 1.6, 3.8, 3.25)
        textbox(s, title, x + .25, 1.9, 3.3, .7, 28, BLUE, True)
        textbox(s, body, x + .25, 2.95, 3.3, 1.6, 20)
    textbox(s, "Buyer: HR / CTO · Thai software houses and banks", .7, 5.25, 12.0, .5, 22, bold=True)
    footer(s, "Business hypothesis: use existing engagement-survey budgets.")

    s = prs.slides.add_slide(end_layout)
    # The end layout owns its right-side legal block and logo; use only the free left area.
    textbox(s, "Kreng-jai Bridge", .65, 2.8, 7.3, .7, 32, bold=True)
    textbox(s, "Live demo\nhttps://119-13-81-32.sslip.io\n\nLINE @075bvvrs", .65, 3.75, 7.3, 1.8, 22, BLUE)
    for slide, spec in zip(prs.slides, specifications):
        slide.notes_slide.notes_text_frame.text = "Content source: docs/submission/deck.md\n" + spec + (
            "\nEvaluation caveats: eval/results/REPORT.md. All experimental results are SYNTHETIC. "
            "All-output metrics include blocked texts; released-only theme metrics are explicitly labelled. "
            "Current measurements do not establish anonymity."
        )
    assert len(prs.slides) == 15
    output = HERE / "Slides_KrengjaiBridge.pptx"
    prs.save(output)
    print(f"DECK slides={len(prs.slides)}")
    return output


def render(outputs, scratch):
    import zipfile
    from xml.sax.saxutils import escape
    preview = HERE / "preview"
    preview.mkdir(exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    soffice = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    profile = scratch / "lo-profile"
    inputs = scratch / "render-input"
    inputs.mkdir(exist_ok=True)
    # Headless macOS LibreOffice otherwise searches only its bundled Latin fonts.
    font_config = scratch / "fonts.conf"
    font_dirs = [Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"),
                 Path.home() / "Library/Fonts", Path("/Applications/LibreOffice.app/Contents/Resources/fonts/truetype")]
    font_config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
                           '<fontconfig>' + ''.join(f'<dir>{escape(str(d))}</dir>' for d in font_dirs if d.exists())
                           + f'<cachedir>{escape(str(scratch / "font-cache"))}</cachedir></fontconfig>')
    render_env = os.environ.copy()
    render_env["FONTCONFIG_FILE"] = str(font_config)
    render_env["SAL_FONTPATH"] = "/System/Library/Fonts/Supplemental"
    for output, prefix in zip(outputs, ("form", "slides")):
        # LibreOffice on macOS has no Leelawadee UI. Substitute in render-only
        # copies; the deliverables keep the requested Windows font declarations.
        render_input = inputs / output.name
        with zipfile.ZipFile(output) as src, zipfile.ZipFile(render_input, "w", zipfile.ZIP_DEFLATED) as dest:
            for item in src.infolist():
                payload = src.read(item.filename)
                if item.filename.endswith(".xml"):
                    payload = payload.replace(b"Leelawadee UI", b"Tahoma")
                dest.writestr(item, payload)
        subprocess.run([soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(scratch), str(render_input)], env=render_env, check=True, timeout=120)
        pdf = scratch / output.with_suffix(".pdf").name
        subprocess.run(["pdftoppm", "-png", "-r", "60", str(pdf), str(scratch / prefix)], check=True, timeout=120)
        for old in preview.glob(f"{prefix}-*.png"):
            old.unlink()
        for png in sorted(scratch.glob(f"{prefix}-*.png")):
            dest = preview / f"{prefix}-{int(png.stem.rsplit('-', 1)[1]):02}.png"
            dest.write_bytes(png.read_bytes())
        print(f"PREVIEW {prefix}: {len(list(preview.glob(prefix + '-*.png')))} pages")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-dir", type=Path, default=ROOT.parent)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--scratch", type=Path)
    args = parser.parse_args()
    data = json.loads((EVAL / "results.json").read_text())
    raw_source = (HERE / "entry-form.md").read_text()
    source = substitute(raw_source, data)
    deck_source = (HERE / "deck.md").read_text()
    doc_template = next(args.template_dir.glob("_Template_1*.docx"))
    ppt_template = next(args.template_dir.glob("_Template_2*.pptx"))
    outputs = [build_form(doc_template, source, data), build_deck(ppt_template, data, deck_source)]
    active_placeholders = set(re.findall(r"\{\{(\w+)\}\}", raw_source))
    for key, (path, kind) in MAPPING.items():
        if key in active_placeholders:
            print(f"MAP {{{{{key}}}}} <- {path} = {value(data, path, kind)}")
    todos = sorted(set(re.findall(r"\[\[TODO.*?\]\]", source.split("## Team Information", 1)[1])))
    print("SOURCE TODOS: " + " | ".join(todos))
    print("DECK TODO: [[TODO: team name]]")
    if args.render:
        if args.scratch:
            render(outputs, args.scratch.resolve())
        else:
            with tempfile.TemporaryDirectory(prefix="kjb-submission-") as tmp:
                render(outputs, Path(tmp))


if __name__ == "__main__":
    main()
