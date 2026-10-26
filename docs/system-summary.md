# U-ETL Factory Data Bridge — สรุประบบ ณ ปัจจุบัน และสิ่งที่ต้องออกแบบต่อ

สรุปจาก source code และเอกสารในชุด handoff (อ้างอิง README 19 ต.ค. 2026, Blueprint v1.3)
แยกให้ชัดระหว่าง **มีแล้วจริง** กับ **ออกแบบไว้ / ยังไม่มี**

---

## 1. ภาพรวม

ระบบดึงข้อมูลจากฐานข้อมูลโรงงาน (ปัจจุบันรองรับ Oracle) แบบ **read-only** มาลงฐานข้อมูลปลายทางเพื่อทำ Dataset ให้ AI/ผู้ใช้งานธุรกิจใช้ โดยมี workflow: ขอ Dataset → ค้นหา Candidate ที่ตรง → คนรีวิว → อนุมัติ Definition → โหลดข้อมูล

สถานะ: **prototype / spike** ยังไม่เชื่อม SPICE AI และยังไม่ใช่ production

---

## 2. โครงสร้างปัจจุบัน (มีอยู่จริง)

```
Browser UI (vanilla JS)  ──HTTPS──>  Python backend (local, single-owner)  ──>  Oracle Source (read-only)
                                              │
                                              └──>  SQLite ในเครื่อง (local target, upsert ด้วย PK)
```

### 2.1 Frontend
| ไฟล์ | หน้าที่ |
|---|---|
| `index.html`, `app.js`, `prototype.js` | โครง UI และ logic หลัก |
| `real-source-ui.js` | UI ฝั่งต่อ Source จริง (test / discover / sample) |
| `sync-ui.js`, `demo-sync.js` | UI/ข้อมูลจำลองการ sync |
| `dataset-workflow.js` | workflow Dataset |
| `styles.css`, `ui-reference-theme.css` | สไตล์ |
| `serve.js` | static server (Node ≥ 20) |

หน้าจอ: Database Connection, U-ETL Database, AI Data Bridge, Data Set

### 2.2 Backend (Python)
**`backend/spike/`** — service จริงที่รันได้ในเครื่อง
- `server.py` — HTTPS server, session เจ้าของคนเดียว
- `service.py` — logic หลัก, jobs เก็บใน memory + worker thread
- `catalog_store.py` — cache catalog
- `target_store.py` — SQLite target (`load_rows`, `preview`)

**`backend/foundation/`** — แกนกลางที่ไม่ผูกกับ engine
- `oracle_read.py` — `test_connection`, discovery, `sample` (bounded)
- `read_budget.py` — เพดานแถว/เวลา
- `secrets.py` — จัดการ secret
- `core.py`, `worker.py`, `smoke.py` — harness ออฟไลน์ (ใช้ข้อมูลสังเคราะห์)

**`backend/contracts.ts`** — TypeScript interface เพื่อออกแบบเท่านั้น (compile-time)

### 2.3 API ที่ implement แล้ว
| Route | หน้าที่ |
|---|---|
| `POST /api/login`, `GET /api/session`, `POST /api/logout` | session ท้องถิ่น |
| `POST /api/test` | ทดสอบ connection |
| `POST /api/catalog` | ค้น catalog แบบ paging (`ALL_OBJECTS`, keyset cursor) |
| `POST /api/discover` | metadata ของ object ที่เลือก |
| `POST /api/sample` | ตัวอย่างแถว (จำกัดจำนวน) |
| `GET /api/jobs/{id}` | poll job |
| `/api/profile/connect`, `/disconnect` | จัดการ profile |
| `/api/local-target/status`, `/preview` | ดูสถานะ/preview SQLite |
| `/api/catalog/cache` | cache catalog |

### 2.4 หลักการความปลอดภัยที่ทำแล้ว
- Source อ่านอย่างเดียว ไม่มี SQL อิสระจาก UI/AI
- ชื่อ object มาจากผลลัพธ์ `ALL_OBJECTS` เท่านั้น, identifier ถูก validate/quote, ค่าถูก bind
- row limit เริ่มต้น 100 (ปรับได้), มี timeout
- ไม่เก็บ Oracle password ในไฟล์

### 2.5 Test
- Python: `test_oracle_read`, `test_read_budget`, `test_local_target`, `test_catalog_store`, `test_foundation`, `test_spike`
- Node/Browser: dataset-workflow, demo-sync, real-source-catalog, phase1, spike, sync-ui, ui-workflow-reset
- Oracle test ส่วนใหญ่ใช้ mock; owner รายงานว่าทดสอบสดกับ `BIDPITDBA.DP_WIP_DATA` แล้วเพียงตารางเดียว

---

## 3. ยังไม่มี (ต้องรู้ก่อนออกแบบ)

| ด้าน | สถานะ |
|---|---|
| เชื่อม SPICE AI | ไม่มี adapter/API; รูปแบบ auth/interface รอทีม SPICE ยืนยัน |
| Engine อื่น (SQL Server, PostgreSQL, MySQL, MariaDB) | เป็นแค่ตัวเลือกใน profile UI ไม่มี Test/Connect |
| Dataset Request / Candidate / Definition API | ออกแบบไว้ใน `docs/api-contract.md` ยังไม่มี route และ record ถาวร |
| AI ranking | ใช้ deterministic metadata baseline (ไม่เรียก AI) |
| Persistence | jobs อยู่ใน memory; ไม่มี durable store |
| ผู้ใช้หลายคน / RBAC / audit | ไม่มี (session เจ้าของคนเดียว) |
| Target ถาวร | SQLite ในเครื่องเท่านั้น |
| Incremental / CDC / scheduler / delete reconciliation | ไม่มี |
| Paging/streaming ปริมาณมาก, checkpoint, retry, monitoring | ไม่มี |
| การทดสอบกับ Oracle จริงหลาย schema | ยังไม่ได้ verify |

---

## 4. สิ่งที่ต้องออกแบบต่อ

### 4.1 ตัดสินใจก่อน (blocker)
1. **บทบาทของ SPICE AI** — U-ETL เป็น UI แยกที่เรียก SPICE หรือเป็น module ใน SPICE; ใครเป็นเจ้าของ job lifecycle / retry / schedule / monitoring
2. **Target ปลายทาง** — SPICE-managed หรือ service อื่น; ต้องรองรับ key-based upsert, schema evolution, transaction, recovery
3. **Identity และสิทธิ์** — ระบุผู้ใช้อย่างไร, enforce สิทธิ์ราย connection/schema/table, secret handling, audit log
4. **Budget และนโยบาย** — row/byte limit, timeout, concurrency, retention, data classification, กระบวนการอนุมัติ

### 4.2 งานออกแบบ/พัฒนาเรียงตามลำดับที่แนะนำ
| # | งาน | หมายเหตุ |
|---|---|---|
| 1 | **Connector abstraction** | ยก `DatabaseEngine` contract ให้ใช้จริง; adapter ใหม่ต้อง fail-closed; ถ้าใช้ SPICE ให้ทำเป็น adapter ใน `foundation/` |
| 2 | **Persistence layer** | แทน memory jobs ด้วย durable store (Request, Candidate, Review, Definition, Run, Audit) |
| 3 | **Dataset Request → Definition API** | ตามตาราง route ใน `api-contract.md`: idempotency key, `If-Match` revision, 409 `revision_conflict`, invalidation เมื่อ source/dictionary/provider เปลี่ยน |
| 4 | **Candidate matching + AI** | คง baseline เป็น fallback; AI provider ปิดไว้จนกว่านโยบาย metadata egress อนุมัติ; ส่ง metadata เท่านั้น ไม่ส่ง credential/row; ห้ามรัน SQL ที่โมเดลสร้าง; ผลเป็นคำแนะนำที่ต้องมีคนรีวิว |
| 5 | **Human review & approval** | Override/Reject ต้องมีเหตุผล; Definition เป็น immutable snapshot; อนุมัติได้เมื่อ blocker หมด |
| 6 | **Load / Incremental** | ตาม `incremental-backend-contract.md`: run boundary ไม่เปลี่ยนแปลง, commit-late, staging checkpoint vs committed watermark, atomic publish, quarantine/reprocess |
| 7 | **Shared target + ops** | scheduler, retry, monitoring, multi-user, RBAC, backup/retention |
| 8 | **Verification** | ทดสอบ Oracle จริงข้าม schema ใน environment ที่ DBA อนุมัติ |

### 4.3 Flow เป้าหมาย
```
Dataset Request ─> Candidate evaluation (baseline / AI) ─> Field review ─> Definition (draft)
      ─> Approval ─> Bounded preview ─> Load run (staging -> atomic publish) ─> Target
                          ▲ ทุกขั้น: authz, audit, revision check, invalidation
```

---

## 5. ความเสี่ยงสำคัญ
- Frontend เป็น vanilla JS แบบ global scope ขยายแล้วดูแลยาก ควรตัดสินใจเรื่อง framework/โมดูลก่อนเพิ่มหน้าจอ
- ถ้าอ่านข้อมูลปริมาณมากด้วยเพดานต่อ request ปัจจุบัน จะไม่พอ ต้องมี paging/checkpoint
- ความถูกต้องของ Matching Score: เป็นค่า ranking ที่ยังไม่ calibrate ห้ามนำเสนอเป็นความน่าจะเป็น
- การเชื่อมฐานจริงต้องได้รับอนุมัติจาก DBA/ทีม SPICE ก่อนเสมอ

---

## 6. ไฟล์อ้างอิง
- `README.md` — สถานะและคำถามสำหรับทีม SPICE
- `docs/U-ETL Factory Data Bridge_Blueprint.md` — Blueprint (เจตนาการออกแบบ)
- `docs/api-contract.md` — API Dataset (ออกแบบเท่านั้น)
- `docs/incremental-backend-contract.md` — สัญญา incremental/load
- `docs/ui-reference-implementation.md` — อ้างอิง UI
- `backend/contracts.ts` — domain types
