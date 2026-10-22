# Token Dashboard

หน้าเว็บ localhost แสดงการใช้ token และค่าใช้จ่ายโดยประมาณของบอท Hermes 4 ตัว (`astra`, `sol`, `flash`, `luna`) แยก Claude / GPT
อ่านข้อมูลจาก `state.db` ของแต่ละโปรไฟล์แบบ **อ่านอย่างเดียว** (SQLite `mode=ro`) ไม่เขียน ไม่คัดลอกฐานข้อมูล

## วิธีรัน

```bash
python server.py            # http://127.0.0.1:8787
python server.py --port 9000
python server.py --base "D:\path\to\profiles"   # ระบุโฟลเดอร์ profiles เอง
```

- ใช้ Python 3.11+ ไลบรารีมาตรฐานเท่านั้น (ไม่ต้อง pip install)
- ผูกที่ `127.0.0.1` เท่านั้น เครื่องอื่นเข้าไม่ได้ ไม่มี endpoint ที่เขียนข้อมูล
- ค่าเริ่มต้นอ่านที่ `%LOCALAPPDATA%\hermes\profiles\<ชื่อ>\state.db`
- หน้าเว็บรีเฟรชเองทุก 30 วินาที ถ้าโหลดไม่สำเร็จจะขึ้นแถบแดงและคงข้อมูลล่าสุดไว้

## การดูข้อมูลผ่านอินเทอร์เน็ต / Cloudflare

1. **ส่งข้อมูลขึ้น Cloudflare Pages ด้วยคลิกเดียว (Static):**
   - ดับเบิลคลิกที่ไฟล์ `Push-To-Web.exe` (หรือชอร์ตคัตบนหน้า Desktop)
   - โปรแกรมจะอ่านข้อมูล Token ล่าสุดจาก Hermes ในเครื่อง Export เป็น JSON และ Git Push ขึ้น GitHub / Cloudflare Pages ให้อัตโนมัติ

2. **เปิดดูแบบ Real-time ตลอดเวลาผ่าน Cloudflare Tunnel:**
   - ดับเบิลคลิกที่ไฟล์ `start-cloudflare.bat`
   - ระบบจะเปิดเซิร์ฟเวอร์และสร้าง Public URL จาก Cloudflare (`trycloudflare.com`) ให้เปิดดูผ่านมือถือหรืออุปกรณ์อื่นได้ทันทีแบบ Real-time

## ตัวเลขแต่ละอย่างหมายถึงอะไร

| ตัวเลข | ความหมาย |
|---|---|
| token รวม | input + output + cache read + cache write (ไม่รวม reasoning ซึ่งแสดงแยก) |
| ตระกูล | ชื่อโมเดลมี `claude` → Claude; มี `gpt` หรือ `openai/` → GPT; อื่น ๆ → Other (นับเฉพาะ "รวมทั้งหมด") |
| ค่าประมาณ (USD) | `estimated_cost_usd` ที่ Hermes บันทึกไว้ **ประมาณการ ไม่ใช่ยอดเรียกเก็บจริง** — เส้นทาง Claude เป็น subscription |
| ครั้ง | จำนวนการเรียก API (`api_call_count`) |
| กราฟกิจกรรมตามเวลา | **ตัวแทนกิจกรรม ไม่ใช่ยอดที่ถูกเรียกเก็บ**: รวม `messages.token_count` ต่อช่วงเวลา ถ้าเป็น NULL ใช้ `ความยาวข้อความ ÷ 4` — เวลาแบ่งตาม Asia/Bangkok (UTC+7) |
| เซสชันสูงสุด | 20 อันดับตาม input+output+cache ต่อ (เซสชัน, โมเดล) |

ถ้าโปรไฟล์ใดเปิดไม่ได้ (ไม่พบไฟล์ / ถูกล็อก) จะแสดงเป็น "ใช้ไม่ได้" ส่วนโปรไฟล์อื่นยังแสดงปกติ (ลองใหม่ 1 ครั้งเมื่อฐานข้อมูลถูกล็อก)

## ทดสอบ

```bash
python -m unittest discover -s tests          # AC-01..04 (fixture SQLite ชั่วคราว)
cd tests/ui && npm install && npx playwright test -c playwright.config.mjs   # AC-05 (Playwright, chromium ที่ติดตั้งไว้)
```

`playwright.config.mjs` ใช้ Chromium ที่มีอยู่แล้วในเครื่อง (ไม่ดาวน์โหลดใหม่) กำหนดเองได้ด้วย `SUBSPLIT_CHROMIUM=<path>` และเลือก Python ด้วย `PYTHON=<path>`
