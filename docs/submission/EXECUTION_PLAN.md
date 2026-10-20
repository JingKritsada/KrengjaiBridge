# Execution plan — งานที่ยังค้าง (Kreng-jai Bridge)

อัปเดต: 20 ต.ค. 2026 · ระบบ live: https://119-13-81-32.sslip.io · LINE OA: @075bvvrs

เสร็จแล้ว: Huawei Cloud (VPC, SG, EIP, ECS ใน CN-Hong Kong), LINE webhook และโปรไฟล์ OA, วิดีโอ demo 2:16
(`../LiveDemo_Videos/2026-10-20_demo_edit.mp4` ฝังเป็น slide 5, YouTube https://youtu.be/f4Op2MmzrTY), `Entry_Form_KrengjaiBridge.docx` และ
`Slides_KrengjaiBridge.pptx` สร้างใหม่วันที่ 20 ต.ค. ด้วย `uv run docs/submission/build_submission.py --render`

ไฟล์ลับ (ห้าม commit, ห้ามส่งต่อ): `.env`, `.env.line`, `.env.cloud` (รหัส root ECS), `.env.server`, `deploy/.env`

## 1. ข้อมูลทีมสำหรับ Template 1 (15 นาที)
ส่งข้อมูลต่อไปนี้ให้ผม หรือกรอกเองในไฟล์ docx ที่ผมสร้างให้:
- ชื่อทีม (Team Name)
- อาจารย์ที่ปรึกษา 1 คน
- ชื่อนักศึกษา 3 คนเป็นภาษาอังกฤษ — ผมใส่ชื่อจากไฟล์ Excel แถว HC-2026a-02 ไว้ก่อน (กฤษฎา / ชิติพัฒน์ / ภาณุพงษ์) ช่วยยืนยันว่าถูก
- เบอร์โทรและอีเมลหัวหน้าทีม
- รูปทีม ~2 MB

## 2. ขอสิทธิ์จากอาจารย์/ผู้ดูแลบัญชี (5 นาที) — ข้อ 4) เรื่อง budget LLM ด่วนที่สุด

ณ 20 ต.ค. endpoint ของคอร์สยังตอบ 422 ระบบจึงใช้เครื่อง GPU ของทีม (LM Studio) อยู่
บัญชี IAM ตอนนี้สร้าง RDS/DCS ไม่ได้ (403 และ `dcs:instance:create required`) และไม่มี AK/SK ข้อความที่ใช้ส่งได้เลย:

> เรียนอาจารย์ครับ ทีม HC-2026a-02 ขออนุญาตเพิ่มสิทธิ์ใน tenant cp-dept-deverhood สำหรับ enterprise project HC-2026a-02 ดังนี้
> 1) RDS FullAccess และ DCS FullAccess (ใช้สร้าง RDS for PostgreSQL ขนาดเล็กสุด และ DCS Redis 0.125 GB แบบ pay-per-use ใน CN-Hong Kong)
> 2) เปิด programmatic access (AK/SK) ให้ IAM user HC-2026a-02
> 3) (ถ้าได้) สิทธิ์สร้าง API key ของ ModelArts Studio MaaS เพื่อเรียก DeepSeek-V4.1-Flash
> 4) **ด่วน:** เพิ่ม budget ของ LLM key `huawei-2026-k02` บน llm.nattee.net (ตอนนี้ใช้ครบ 3.00 USD แล้ว ระบบตอบ 422 Budget has been exceeded) เพราะ demo ต้องใช้ LLM ตอนกรรมการทดลอง
> ขอบคุณครับ

ได้สิทธิ์แล้วให้แจ้งผม ผมจะรัน `skills/huawei-cloud-provision/provision.py plan → apply → env` แล้ว redeploy ให้ ใช้เวลาประมาณ 20 นาที

## 3. ตรวจก่อนส่ง (15 นาที)
- เติม [[TODO]] ที่เหลือใน `entry-form.md` และชื่อทีมใน `build_submission.py` แล้ว build ใหม่ ตั้งชื่อไฟล์ตามรูปแบบ "Area_Team Name"
- เปิด `Slides_KrengjaiBridge.pptx` ใน PowerPoint บนเครื่องที่จะนำเสนอ แล้วกดเล่นวิดีโอใน slide 5 หนึ่งครั้ง (ไฟล์ประมาณ 34 MB เพราะมีวิดีโอ)
- ทุกจุดที่เขียนว่า "synthetic" ต้องคงไว้ เพราะชุดข้อมูลยังไม่ใช่อาสาสมัครจริง

## 4. หลังส่งงาน / หลังตัดสิน
- ลบ inbound rule SSH (TCP 22) จาก `0.0.0.0/0` ใน `sg-kjb` ที่เพิ่มเมื่อ 20 ต.ค. เพื่อ deploy ระหว่างอัด demo
  ให้เหลือเฉพาะ IP ผู้ดูแล เพราะ sshd ยังรับ root password login อยู่ (ควรทำทันทีที่ไม่ต้อง deploy แล้ว)
- ECS คิดเงินรายชั่วโมงตลอดเวลาที่เปิด หลังตัดสินให้ลบ `ecs-kjb` (EIP ถูกลบตามไปด้วย), `sg-kjb`, `vpc-kjb`
- เปลี่ยนรหัสผ่าน IAM (มีอยู่ในแชทและในไฟล์ Excel) และ reissue LINE channel access token
- ถ้าจะเปิด repo สาธารณะ ให้ตรวจก่อนว่าไม่มีไฟล์ `.env*` อยู่ใน history (ตอนนี้ไม่มี เพราะอยู่ใน .gitignore ตั้งแต่ต้น)
