"""Thai copy. Reminders never name the person who asked for help."""


def nudge_text(signal):
    templates = {
        "pr_stale": f"{signal.ref} รอ review เกิน 48 ชั่วโมง ต้องการให้ช่วยส่งคำเตือนตามข้อตกลงของทีมไหม?",
        "ticket_blocked": f"{signal.ref} ติด block หรือต้องแก้ซ้ำ ต้องการให้ช่วยประสานหาคนช่วยไหม?",
        "friday_urgent": "มีงานเข้าหลัง 17:00 วันศุกร์หลายครั้ง อยากสะท้อนผลกระทบแบบไม่ระบุตัวตนไหม?",
        "late_night": "เห็นกิจกรรมงานหลัง 22:00 หลายวัน สะดวกพักหรืออยากให้ช่วยเรื่องภาระงานไหม? ข้อความนี้ส่งถึงคุณเท่านั้น",
        "sprint_end": "จบ sprint แล้ว มีเรื่องติดขัดที่อยากสะท้อนแบบไม่ระบุตัวตนไหม?",
    }
    return templates.get(signal.kind, "อยากให้ช่วยประสานเรื่องงานไหม?")


def nudge_buttons(signal_id, kind):
    return [
        {"label": "ช่วยเตือนให้หน่อย", "action": f"nudge:accept:{signal_id}"},
        {"label": "ยังไม่ต้อง", "action": f"nudge:decline:{signal_id}"},
        {"label": "ไม่มีประโยชน์", "action": f"nudge:useless:{signal_id}"},
        {"label": "ปิดการแจ้งเตือนประเภทนี้", "action": f"mute:{kind}"},
    ]


def reminder_text(signal):
    return f"แจ้งเตือนตามข้อตกลงของทีม: {signal.ref} รอการดำเนินการเกินเกณฑ์ กรุณาตรวจสอบและแจ้งเวลาที่สะดวก ข้อความนี้ส่งโดย Kreng-jai Bridge"
