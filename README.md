# U-ETL Factory Data Bridge — SPICE AI handoff

ชุดนี้จัดทำเพื่อให้ทีม SPICE AI ตรวจสอบสถาปัตยกรรมและพิจารณานำแนวคิด/หน้าจอของ U-ETL ไปประยุกต์ใช้กับ connection platform ที่ทีมดูแล ไม่ได้หมายความว่าโปรเจคนี้เชื่อมต่อ SPICE AI แล้ว

เอกสารนี้เป็นสรุปสถานะที่ยึดตาม source code ในชุดนี้ ณ 19 ตุลาคม 2026 ส่วน Blueprint และ API contract ใน `docs/` เป็นเอกสารออกแบบ/ความต้องการประกอบการ review ไม่ใช่หลักฐานว่าฟีเจอร์ทุกข้อ implement แล้ว

## สถานะปัจจุบัน

- มี UI สำหรับ Database Connection, U-ETL Database, AI Data Bridge และ Data Set
- มี local HTTPS backend สำหรับ Oracle Source บางส่วน: ทดสอบ connection, ค้น metadata, ดู structure/sample ตามคำสั่ง และอ่านข้อมูลแบบจำกัดจำนวนแถว
- Source Oracle ถูกใช้อ่านอย่างเดียวเท่านั้น การโหลดข้อมูลเขียนลง SQLite ในเครื่องแยกจาก Source โดยใช้ Primary Key สำหรับ upsert; ค่า row limit เริ่มต้น 100 และแก้ได้
- มี View data เพื่อดู preview จาก SQLite และ load group ที่ทำงานตามลำดับแบบ manual
- Candidate matching เป็น deterministic metadata baseline ยังไม่ได้เรียก AI; การ review Dataset ยังไม่ใช่ durable production workflow

## ยังไม่ใช่ production-ready

- ยังไม่มี adapter/API integration กับ SPICE AI; รูปแบบ interface, authentication, authorization และวิธีเรียก connection ต้องให้ทีม SPICE ยืนยัน
- SQLite target อยู่ในเครื่องผู้ใช้ ไม่ใช่ shared server database; ไม่มี multi-user persistence, scheduler, incremental/CDC, deletion reconciliation หรือ production retry/monitoring
- การอ่าน Oracle ปัจจุบันมีเพดานต่อ request และ timeout; ต้องออกแบบ paging/streaming, checkpoint, retry และ resource control ก่อนรองรับ full-scale workload
- automated Oracle tests ใช้ mock เป็นหลัก การเชื่อมต่อจริงและสิทธิ์ต้องตรวจใน environment ที่ได้รับอนุญาต

## ประเด็นที่ขอให้ทีม SPICE AI review

1. SPICE ให้บริการ connection/catalog/read ผ่าน API, SDK, job service หรือ UI embedding แบบใด และมีเอกสาร/API version หรือ sandbox ให้ทดลองหรือไม่
2. ระบบระบุผู้ใช้และ enforce สิทธิ์ราย connection/schema/table อย่างไร รวมถึง secret handling และ audit log
3. สามารถค้น metadata, อ่าน columns/keys, และดึงแถวด้วย limit + pagination/cursor โดยไม่เปิดเผย credential ให้ U-ETL ได้อย่างไร
4. U-ETL ควรเป็น UI แยกที่เรียก SPICE หรือเป็น module ภายใน SPICE; ผู้ใดเป็นเจ้าของ job lifecycle, retry, schedule และ monitoring
5. ปลายทางจัดเก็บข้อมูลจะเป็น SPICE-managed target หรือ service อื่น และรองรับ key-based upsert, schema evolution, transaction และ recovery อย่างไร
6. กำหนด security/performance budgets, row/byte limits, timeout, concurrency, retention, data classification และ approval process แบบใด

## เนื้อหาในชุดส่งต่อ

- `app.js`, `prototype.js`, `real-source-ui.js`, stylesheet และ static assets: UI ปัจจุบัน
- `backend/`: Oracle read backend, local SQLite target และ engine-neutral foundation/contracts
- `tests/`: unit, browser-fixture และ service tests; browser tests อาจต้องติดตั้ง runtime เพิ่ม
- `scripts/`, `package.json`, lockfiles และ `Start U-ETL Test.bat`: build/test/start helpers
- `docs/`: Blueprint และ API/acceptance contracts ที่ช่วยอธิบายเจตนาการออกแบบ โปรดอ่านสถานะใน README นี้ประกอบ

ไม่มี `.spike-venv`, `node_modules`, `dist`, temporary test folders, local SQLite warehouse, Oracle credentials, certificate/private key หรือข้อมูล Source จริงรวมอยู่ในชุดนี้

## ตรวจสอบและรัน

Static UI:

```powershell
npm ci
npm test
npm run build
npm start
```

Oracle local HTTPS backend ต้องใช้ Python/driver ตาม lockfile และเครื่องที่ได้รับอนุญาต:

```powershell
python -m venv .spike-venv
& .\.spike-venv\Scripts\python.exe -m pip install -r backend\requirements-spike.lock.txt
& .\.spike-venv\Scripts\python.exe -m unittest discover -s tests
```

จากนั้นเปิด `Start U-ETL Test.bat` และตั้ง local application passphrase ใหม่เมื่อระบบถาม ห้ามใช้หรือส่ง Oracle password ผ่านไฟล์/แชต และอย่าต่อฐานข้อมูลจริงจนกว่า DBA/ทีม SPICE อนุมัติ scope และ environment

## ข้อควรระวังในการรับช่วง

ให้ใช้ source code เป็นหลักในการตรวจพฤติกรรมจริง อย่านำ local SQLite หรือ credentials จากเครื่องพัฒนามาเป็น artifact ของทีม ให้ยืนยันขอบเขตสิทธิ์, query budget, target owner, audit, retention, backup และ deployment model ก่อนเปิดใช้งานข้อมูลจริงหรือ production workload
