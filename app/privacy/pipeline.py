"""Six-step privacy preview. Source text stays only in the current call."""

from app import llm
from app.config import get_settings
from app.contracts import MemberProfile, PipelineResult, PipelineStep
from app.privacy.identifiers import remove_identifiers, scrub_roster
from app.privacy.neutralize import leak_markers, neutralize
from app.privacy.rewrite import rewrite_with_attacker
from app.privacy.structure import structure_and_theme


async def run_pipeline(
    text: str, author_id: str, roster: list[MemberProfile], *,
    existing_themes: list[tuple[str, str]] = (), max_rounds: int | None = None,
) -> PipelineResult:
    result = PipelineResult(ok=False)
    ids = [member.member_id for member in roster]
    rounds = get_settings().attacker_max_rounds if max_rounds is None else max_rounds
    if not text.strip() or len(ids) < 2 or len(set(ids)) != len(ids) or author_id not in ids or rounds < 1:
        result.reason_blocked = "ข้อมูลไม่เพียงพอสำหรับการตรวจสอบความเป็นส่วนตัว"
        return result
    try:
        cleaned = await remove_identifiers(text, roster)
        result.steps.append(PipelineStep(step=1, name="ลบข้อมูลระบุตัวตน", output=cleaned))
        cleaned = neutralize(cleaned)
        result.steps.append(PipelineStep(step=2, name="ปรับภาษาให้เป็นกลาง", output=cleaned))
        rewritten, guesses, safe = await rewrite_with_attacker(
            cleaned, author_id, roster, max_rounds=rounds,
        )
        result.attacker_rounds = guesses
        result.steps.append(PipelineStep(
            step=3, name="ทดสอบผู้โจมตี", output=rewritten,
            notes=[f"ทดสอบ {len(guesses)} รอบ", "ผ่านการทดสอบ" if safe else "ยังระบุผู้เขียนได้"],
        ))
        if not safe:
            result.reason_blocked = "ยังสามารถระบุผู้เขียนได้หลังทดสอบครบจำนวนรอบ"
            return result
        structured, theme = await structure_and_theme(rewritten, existing_themes)
        for field in type(structured).model_fields:
            setattr(structured, field, neutralize(scrub_roster(getattr(structured, field), roster)))
        slug, label = theme
        label = neutralize(scrub_roster(label, roster))
        if any(leak_markers(value) for value in [rewritten, *structured.model_dump().values(), label]):
            raise ValueError("Remaining privacy markers")
        result.steps.append(PipelineStep(
            step=4, name="จัดโครงสร้าง", output=structured.model_dump_json(),
        ))
        result.steps.append(PipelineStep(
            step=5, name="ประตูความเป็นส่วนตัว", output="รอประตู k",
            notes=["นับหลังยืนยันส่งเท่านั้น"],
        ))
        result.steps.append(PipelineStep(step=6, name="จัดกลุ่มประเด็น", output=f"{slug}: {label}"))
        result.final_text = rewritten
        result.structured = structured
        result.theme_slug, result.theme_label = slug, label
        result.ok = True
    except (llm.LLMError, ValueError, TypeError, KeyError):
        # Exceptions from model replies may contain source text; never expose them.
        result.reason_blocked = "ตรวจสอบความเป็นส่วนตัวไม่สำเร็จ กรุณาลองใหม่"
    return result


def demo_roster() -> list[MemberProfile]:
    return [
        MemberProfile(
            member_id="m-mint", display_name="มิ้น", nicknames=["มิ้นท์", "มิ้นต์", "Mint"],
            role="Junior Backend Developer", gender="female", seniority="junior",
            style_samples=["หนูเปิด PR แล้วค่ะ ฝากพี่ช่วยดูหน่อยนะคะ", "หนูยังติดปัญหานี้อยู่ค่ะ", "ขอบคุณพี่มากค่ะ หนูจะลองแก้ดู"],
        ),
        MemberProfile(
            member_id="m-somchai", display_name="พี่สมชาย", nicknames=["สมชาย", "Somchai"],
            role="Senior Backend Developer", gender="male", seniority="senior",
            style_samples=["ผมตรวจโค้ดให้แล้วครับ ปรับตามคอมเมนต์ได้เลย", "เดี๋ยวผมช่วยดูให้นะครับ", "ผมขอให้เพิ่มเทสต์ก่อนรวมโค้ดครับ"],
        ),
        MemberProfile(
            member_id="m-wan", display_name="พี่วรรณ", nicknames=["วรรณ", "Wan"],
            role="Engineering Manager (หัวหน้าทีม)", gender="female", seniority="lead",
            style_samples=["พี่ขอนัดคุยเรื่องแผนงานค่ะ", "ทีมช่วยแจ้งความคืบหน้าภายในวันนี้นะคะ", "พี่จะช่วยจัดลำดับความสำคัญให้ค่ะ"],
        ),
        MemberProfile(
            member_id="m-boat", display_name="โบ๊ท", nicknames=["โบ้ท", "Boat"],
            role="Backend Developer", gender="male", seniority="mid",
            style_samples=["ผมแก้ API เรียบร้อยแล้วครับ", "ขอผมเช็ก log ก่อนครับ", "ผมจะส่ง PR ให้รีวิวช่วงบ่ายครับ"],
        ),
        MemberProfile(
            member_id="m-fon", display_name="ฝน", nicknames=["Fon"],
            role="QA Engineer", gender="female", seniority="junior",
            style_samples=["หนูเจอบั๊กเพิ่มอีกหนึ่งจุดค่ะ", "ขอหนูทดสอบรอบสุดท้ายก่อนนะคะ", "หนูแนบขั้นตอนทดสอบไว้แล้วค่ะ"],
        ),
        MemberProfile(
            member_id="m-ton", display_name="ต้น", nicknames=["Ton"],
            role="DevOps Engineer", gender="male", seniority="mid",
            style_samples=["ผม deploy ให้แล้วครับ", "คืนนี้ผมเข้าเวร on-call ครับ", "ผมกำลังเช็กระบบแจ้งเตือนครับ"],
        ),
    ]
