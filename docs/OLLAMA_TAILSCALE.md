# ใช้ LLM จากเครื่อง GPU ของเพื่อนในทีม (Ollama + Tailscale)

ใช้เมื่อ key LLM ของคอร์สหมดงบ หรืออยากรัน evaluation ซ้ำโดยไม่เสียเงิน

```
ECS (Hong Kong) ── Tailscale (เข้ารหัส, ไม่เปิดพอร์ตสู่อินเทอร์เน็ต) ── เครื่องเพื่อน: Ollama + GPU
   app → http://<tailscale-ip>:11434/api/chat
```

App รองรับ Ollama โดยตรงแล้ว: ถ้า `LLM_BASE_URL` ใช้พอร์ต `11434` (หรือตั้ง `LLM_API_STYLE=ollama`) จะเรียก `/api/chat` แบบ `think: false` เพื่อปิด thinking ของ Qwen3.5 ให้ตอบเร็ว

## 1. เลือกขนาดโมเดลตาม VRAM

| VRAM ของ GPU | โมเดล | ขนาดไฟล์ (ประมาณ) | หมายเหตุ |
|---|---|---|---|
| 8–12 GB | `qwen3.5:9b` | 6.6 GB | ใช้ได้ ภาษาไทยพอใช้ |
| 16 GB | `qwen3.5:9b-q8` | 11 GB | คุณภาพดีกว่า q4 เล็กน้อย |
| 24 GB ขึ้นไป | `qwen3.5:27b` หรือ `qwen3.5:35b-a3b` | 17–24 GB | ใกล้กับ endpoint ของคอร์สที่สุด; `35b-a3b` เป็น MoE จึงตอบเร็ว |

> เราไม่รู้ว่า endpoint `qwen3.5` ของคอร์สใช้ขนาดไหน ตัวเลขใน `eval/results/REPORT.md` วัดบน endpoint นั้น
> ถ้าเปลี่ยนมาใช้เครื่องเพื่อน ให้รัน evaluation ใหม่ (ฟรี เพราะรันในเครื่อง) แล้วสร้างเอกสารใหม่

## 2. ฝั่งเครื่องเพื่อน (GPU)

### Linux (NVIDIA driver + CUDA พร้อมแล้ว)
```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl edit ollama
# ใส่ 4 บรรทัดนี้แล้ว save:
# [Service]
# Environment="OLLAMA_HOST=0.0.0.0:11434"
# Environment="OLLAMA_KEEP_ALIVE=24h"
# Environment="OLLAMA_NUM_PARALLEL=4"
sudo systemctl restart ollama
ollama pull qwen3.5:9b            # หรือขนาดตามตารางข้อ 1
nvidia-smi                        # ตรวจว่า GPU ถูกใช้ตอนรันข้อถัดไป
ollama run qwen3.5:9b "ตอบสั้น ๆ: 1+1 เท่ากับเท่าไร" --think=false
```

### Windows
1. ติดตั้ง Ollama จาก https://ollama.com/download
2. Settings → System → About → Advanced system settings → Environment Variables → เพิ่ม User variables 3 ตัว:
   - `OLLAMA_HOST` = `0.0.0.0:11434`
   - `OLLAMA_KEEP_ALIVE` = `24h`
   - `OLLAMA_NUM_PARALLEL` = `4`
3. ปิดแล้วเปิด Ollama ใหม่ (คลิกขวาไอคอนที่ taskbar → Quit แล้วเปิดใหม่)
4. PowerShell: `ollama pull qwen3.5:9b`
5. Windows Firewall: อนุญาต inbound TCP 11434 **เฉพาะ profile/interface ของ Tailscale** ห้ามเปิดให้ทั้งเครื่อง

### ทั้งสองระบบ: ติดตั้ง Tailscale
1. ติดตั้งจาก https://tailscale.com/download แล้ว login เข้า tailnet ของทีม
2. จดค่าไว้ส่งให้ผม:
   - IP ของเครื่อง: `tailscale ip -4` (รูปแบบ `100.x.y.z`)
   - หรือชื่อ MagicDNS เช่น `gpu-box`
3. ตั้งเครื่องไม่ให้ sleep ตลอดช่วงตัดสิน

## 3. ฝั่ง tailnet (เจ้าของ tailnet ทำ)
1. https://login.tailscale.com/admin/settings/keys → **Generate auth key**
   - Reusable: ปิด
   - Ephemeral: ปิด
   - Tags: `tag:kjb-ecs` (ถ้าใช้ ACL)
2. บันทึก key ลงไฟล์ `kreng-jai-bridge/.env.tailscale` บรรทัดเดียว `TS_AUTHKEY=tskey-...` (อย่าวางในแชท)
3. (แนะนำ) Access controls ให้ ECS เข้าถึงเครื่องเพื่อนได้แค่พอร์ต 11434:
   ```json
   {"tagOwners": {"tag:kjb-ecs": ["autogroup:admin"]},
    "acls": [{"action": "accept", "src": ["tag:kjb-ecs"], "dst": ["<ชื่อหรือ IP เครื่องเพื่อน>:11434"]},
             {"action": "accept", "src": ["autogroup:member"], "dst": ["*:*"]}]}
   ```

## 4. ฝั่ง ECS (ผมทำให้ เมื่อมีไฟล์ `.env.tailscale`)
```bash
ssh root@119.13.81.32 'curl -fsSL https://tailscale.com/install.sh | sh'
ssh root@119.13.81.32 "tailscale up --authkey $(grep TS_AUTHKEY .env.tailscale | cut -d= -f2) --hostname kjb-ecs"
ssh root@119.13.81.32 'curl -s http://100.x.y.z:11434/api/tags'           # ต้องเห็นชื่อโมเดล
```

แก้ `.env.server` 4 บรรทัด แล้ว `deploy/deploy.sh`:
```
LLM_BASE_URL=http://100.x.y.z:11434
LLM_MODEL=qwen3.5:9b
LLM_API_KEY=
LLM_API_STYLE=ollama
```

ตรวจผล:
- `https://119-13-81-32.sslip.io/api/health` → `llm_model` เป็นชื่อใหม่
- ส่งความเห็น 1 ครั้ง แล้ว `llm_available` ต้องเป็น `true`
- ถ้าเครื่องเพื่อนดับ ระบบจะเข้าโหมดสำรองเองภายในคำขอถัดไป (demo ไม่ล่ม)

## 5. ข้อควรระวัง
- Ollama **ไม่มีระบบยืนยันตัวตน** ห้ามเปิดพอร์ต 11434 สู่อินเทอร์เน็ต (ห้าม port-forward ที่ router) ให้เข้าผ่าน Tailscale เท่านั้น
- ความเร็วขึ้นกับ GPU: โมเดล 9B บน GPU ระดับ RTX 3060–4070 ใช้ประมาณ 1–3 วินาทีต่อคำขอ หนึ่งความเห็นมี 4–6 คำขอ
- Evaluation ทั้งชุดประมาณ 700 คำขอ ใช้เวลาประมาณ 20–40 นาทีบน GPU เดียว:
  ```bash
  LLM_BASE_URL=http://100.x.y.z:11434 LLM_MODEL=qwen3.5:9b LLM_API_KEY= uv run python eval/run_all.py
  ```
- รันจาก Mac ต้องให้ Mac อยู่ใน tailnet เดียวกันด้วย
