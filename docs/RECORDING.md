# อัดคลิป demo

มี 2 ส่วน:
- **ส่วนเว็บ**: อัดอัตโนมัติด้วยสคริปต์ มีคำบรรยาย EN/TH รันซ้ำได้ทุกครั้งที่แก้ UI
- **ส่วน LINE บนมือถือ**: อัดหน้าจอแยก แล้วตัดต่อรวม (ดูหัวข้อ 4)

## 1. เตรียมเครื่อง (ครั้งแรกครั้งเดียว)

| ต้องมี | ติดตั้ง | ใช้ทำอะไร |
|---|---|---|
| uv | `brew install uv` | รันสคริปต์ Python พร้อม dependency |
| Chromium ของ Playwright | `uv run --with playwright playwright install chromium` | เบราว์เซอร์ที่ใช้อัด |
| ffmpeg | `brew install ffmpeg` | แปลง WebM เป็น MP4 และตัดต่อ (ถ้าไม่มีจะได้ไฟล์ `.webm`) |

## 2. อัดส่วนเว็บ

```bash
cd kreng-jai-bridge
uv run scripts/record_demo.py                                   # 1440×900 → ./demo.mp4
uv run scripts/record_demo.py --size 1920x1080 --out demo-1080p.mp4
uv run scripts/record_demo.py --base-url http://localhost:8000  # อัดจาก server ในเครื่อง
uv run scripts/record_demo.py --no-captions --headed            # ไม่มีคำบรรยาย และเปิดหน้าต่างให้ดูระหว่างอัด
```

- ใช้เวลาประมาณ 2.5 นาที ได้คลิปยาวประมาณ 2:10
- **สคริปต์จะกด "ล้างข้อมูลเดโม" บน server ที่ระบุ** อย่ารันระหว่างที่คนอื่นกำลัง demo อยู่บน server เดียวกัน
- ถ้าหน้า `/demo` ขึ้นป้าย "โหมดสำรอง (ไม่มี LLM)" ในคลิปก็จะเห็นป้ายนั้นด้วย ตรวจ `https://<server>/api/health` ก่อนอัด ช่อง `llm_available` ต้องเป็น `true`

ลำดับฉากในคลิป:

| # | หน้า | สิ่งที่เกิด |
|---|---|---|
| 1 | `/` | หน้าแนะนำ |
| 2 | `/demo` | ล้างข้อมูล → PR รอรีวิวนาน → มิ้นกด "ช่วยเตือนให้หน่อย" → แท็บพี่สมชายเห็นข้อความเตือนที่ไม่มีชื่อมิ้น |
| 3 | `/demo` | Privacy Pipeline 6 ขั้น → ยืนยันส่ง → เพื่อนร่วมทีม 2 คน → ประตู 3/3 |
| 4 | `/manager` | รอธีมขึ้น (สูงสุด 2 นาที) → พิมพ์คำตอบ → ยอมรับข้อเสนอ → ส่ง |
| 5 | `/demo` | มิ้นได้รับคำตอบ → ข้ามเวลา 2 สัปดาห์ |
| 6 | `/manager` | ติดตามผล 3 → 0 |
| 7 | architecture | ภาพสถาปัตยกรรมบน Huawei Cloud |

## 3. แก้คลิปเมื่อ UI หรือเนื้อเรื่องเปลี่ยน

ทุกอย่างอยู่ใน `scripts/record_demo.py`:
- **คำบรรยาย**: dict `CAPTIONS` (คู่ข้อความ อังกฤษ/ไทย ต่อฉาก)
- **ข้อความที่พิมพ์**: ค่าคงที่ `FEEDBACK` (ความเห็นของมิ้น) และ `REPLY` (คำตอบหัวหน้า)
- **ลำดับฉากและเวลารอ**: เมธอด `Demo.run()` ปรับเวลาต่อฉากที่ `await self.wait(วินาที)`
- **ถ้าแก้ UI แล้วสคริปต์หาปุ่มไม่เจอ** (error `Timeout ... waiting for locator`) ให้แก้ตัวเลือกปุ่มใน `Demo.run()` ตัวเลือกที่ใช้มี:
  - ข้อความบนปุ่ม: "ล้างข้อมูลเดโมและเริ่มใหม่", "ทดสอบการปกป้องตัวตน", "ยืนยันส่งความเห็น", "เพื่อนร่วมทีมส่งความเห็นคล้ายกัน", "ข้ามเวลา 2 สัปดาห์"
  - attribute: `button[data-scenario="pr_stale"]`
  - class: `.inbox-panel`, `.member-tabs`, `.live-pipeline`, `.reply-form`, `.followup`
  - id: `#feedback-form`
- ใช้ `--headed` ดูว่าสคริปต์ค้างที่ฉากไหน

## 4. อัดส่วน LINE

> **iOS Simulator ใช้ไม่ได้:** Simulator ติดตั้งแอปจาก App Store ไม่ได้ เลยไม่มีแอป LINE ให้ใช้

ทางเลือกที่ใช้ได้ เรียงจากที่แนะนำ:

| วิธี | ได้อะไร | ข้อควรระวัง |
|---|---|---|
| **A. iPhone จริง + iPhone Mirroring / QuickTime** | ภาพตรงกับที่ผู้ใช้เห็นจริง มี quick reply ครบ | ต้องมี iPhone 2 เครื่องถ้าจะโชว์ทั้งมิ้นและพี่สมชาย |
| **B. LINE for Mac + LINE ส่วนขยาย Chrome** | 2 บัญชีบนจอเดียว อัดด้วย macOS ได้เลย และไม่กระทบ LINE บนมือถือ | เวอร์ชัน PC/Mac **ไม่แสดง quick reply** ให้พิมพ์แทน (ระบบรองรับแล้ว ดูตารางล่าง) |
| C. Android Emulator + LINE จาก Play Store | อัดได้ทั้งเครื่อง | **การ login LINE บัญชีหลักใน emulator จะย้ายบัญชีออกจากมือถือจริง** (LINE ใช้บนสมาร์ทโฟนได้ทีละเครื่อง) ใช้เฉพาะบัญชีสำรองที่มีเบอร์แยก |

**วิธี A**
- iPhone Mirroring (macOS 15+ และ iOS 18+): เปิดแอป iPhone Mirroring บน Mac แล้วอัดหน้าจอด้วย `Cmd+Shift+5` → Record Selected Portion
- QuickTime (ใช้สาย USB): QuickTime Player → File → New Movie Recording → กดลูกศรข้างปุ่มอัด แล้วเลือก iPhone เป็นกล้อง
- เครื่องที่สอง: ใช้ Screen Recording ใน Control Center ของ iPhone แล้ว AirDrop ไฟล์มาที่ Mac

**วิธี B**
- LINE for Mac (App Store) login บัญชีที่ 1 → ผูกเป็น "มิ้น"
- Chrome → ติดตั้งส่วนขยาย LINE แล้ว login บัญชีที่ 2 → ผูกเป็น "พี่สมชาย"
- การ login บน PC/Mac เป็นอุปกรณ์รอง ไม่ทำให้ LINE บนมือถือหลุด

**คำสั่งพิมพ์แทนปุ่ม (ใช้ได้ทุกเครื่อง)**

| ตอนไหน | พิมพ์ | ผล |
|---|---|---|
| ยังไม่ได้ผูกตัวละคร | `มิ้น`, `สมชาย`, `วรรณ`, `โบ๊ท`, `ฝน`, `ต้น` | ผูกเป็นคนนั้น |
| ได้ข้อความเตือน | `ช่วยเตือนให้หน่อย` / `ยังไม่ต้อง` / `ไม่มีประโยชน์` / `ปิดแจ้งเตือนแบบนี้` | เหมือนกดปุ่ม (ใช้กับข้อความล่าสุดที่ยังไม่ตอบ) |
| หลังได้การ์ดตัวอย่างความเห็น | `ยืนยัน` / `ยกเลิก` | ยืนยันหรือยกเลิกฉบับร่างล่าสุด |
| ทุกเมื่อ | `ช่วยเหลือ` | วิธีใช้ |
| ข้อความยาวอย่างน้อย 15 ตัวอักษร | ความเห็นใด ๆ | ส่งเข้า privacy pipeline แล้วได้การ์ดตัวอย่าง |
| ข้อความสั้นที่ไม่ใช่คำสั่ง | เช่น `งานเยอะ` | บอทขอรายละเอียดเพิ่ม (ไม่เปลือง LLM) |

## 5. ตัดต่อรวม (ffmpeg)

**วางจอเว็บกับจอมือถือคู่กัน** (ปรับมือถือให้สูงเท่าคลิปเว็บ):
```bash
ffmpeg -i demo.mp4 -i phone.mov -filter_complex "[1:v]scale=-2:900[p];[0:v][p]hstack=inputs=2" \
  -c:v libx264 -crf 20 -pix_fmt yuv420p side-by-side.mp4
```

**ตัดช่วง** (เช่น เอาวินาทีที่ 5 ถึง 1:30):
```bash
ffmpeg -ss 00:00:05 -to 00:01:30 -i demo.mp4 -c:v libx264 -crf 20 part1.mp4
```

**ต่อหลายคลิป** (ต้องเป็นขนาดเดียวกัน):
```bash
printf "file 'part1.mp4'\nfile 'phone-part.mp4'\nfile 'part2.mp4'\n" > list.txt
ffmpeg -f concat -safe 0 -i list.txt -c:v libx264 -crf 20 -pix_fmt yuv420p final.mp4
```

**ใส่เสียงบรรยาย** (อัดเสียงด้วย QuickTime → New Audio Recording):
```bash
ffmpeg -i final.mp4 -i voice.m4a -map 0:v -map 1:a -c:v copy -c:a aac -shortest final-voice.mp4
```
