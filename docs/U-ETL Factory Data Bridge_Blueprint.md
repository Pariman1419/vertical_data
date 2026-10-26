# U-ETL Factory Data Bridge

ชื่อ Repository/โฟลเดอร์: `UTL_ETL` | คำอธิบาย: Manufacturing Data Integration Platform
## Project Blueprint & Codex Implementation Plan — v1.3

วันที่: 9 ตุลาคม 2026 | เจ้าของโครงการ: Chatchai | สถานะ: Current product/workflow Blueprint; technical/provider choices remain subject to their decision status below

## Latest owner UI scope override — 15 October 2026

The latest owner direction, including screenshots of `docs/ui-reference/U-ETL_DataBridge_UI_Reference.html`, sets four normal work areas: **Database Connection, U-ETL DataBridge, AI Data Bridge, Data Set**. Database Connection is the home page. Use the mockup's visual language and table/form layout; its 16-screen `เปิดดูหน้าจอ` dropdown is inspection-only and must not be added to the application. The existing connection/profile and Oracle backend, metadata workspace, guarded Dataset Wizard, and Dataset list must be mapped into these areas rather than replacing the app with the standalone mockup. Activity/history can be nested under the relevant area.

This update supersedes only the 9 October navigation names/start page and related U53 wording. The four-step Wizard remains Request → Review plan → Preview → Publish (prototype only); required inputs and mapping/grain/relationship approval gates remain. No illustrative mockup rows/storage/schedules may be shown as live state. AI remains disabled, Oracle read-only HTTPS behavior stays unchanged, and no real copy, Target write, ETL, Scheduler or Production deployment is authorized. The 9 October workflow document is retained as a historical acceptance checkpoint; current visual acceptance is in `docs/ui-reference-implementation.md`.

### UI reset acceptance addendum

- U53: Normal navigation contains only My Datasets, Connections, Create Dataset and Activity; My Datasets is the start page. Legacy synthetic regression is opt-in at `?demo=1`.
- U54: Dataset Wizard has four owner-defined steps; Back/edit works, unresolved mapping/grain/relationship blockers prevent confirmation, and real metadata is never combined with synthetic rows.
- U55: Destination/table/cadence are visible in the final step but remain simulated; UI never claims a Target write or scheduled update.
- U56: Existing Data Prep IOT Oracle read-only HTTPS profile remains in Connections without a duplicate Oracle page/card; real Source statuses remain distinct from Demo.
- U57: Apply the supplied HTML reference's Navy Blue workspace/masthead/U mark, cards, form/table styling and responsive layout to the existing app, without replacing the app or changing its workflow state model.
- U58: Mockup screen-picker (`เปิดดูหน้าจอ`) is for design inspection only and is not a normal application feature.
- U59: Keep required-input validation and mapping/grain/relationship approval gates; incomplete or ambiguous definitions cannot advance/approve silently.
- U60: Keep the existing Oracle read-only HTTPS backend and its credential, allowlist and bounded-read behavior; visual asset routing must not alter Source API semantics. Keep Demo, real Source and simulated Target states distinguishable.
- U61 (owner UI correction, 15 October 2026): The latest supplied reference screenshots supersede only the normal-navigation labels/order and home page in U53. Normal navigation is now **Database Connection** (home), **U-ETL DataBridge**, **AI Data Bridge**, and **Data Set**. Map the existing connection profile/Oracle read-only path, metadata workspace, guarded Dataset Wizard, and Dataset list into these areas. Activity/history may be nested under the relevant area. The mockup's 16-screen `เปิดดูหน้าจอ` dropdown is inspection-only and must not appear in the application. Do not seed the reference's illustrative copied-row/storage/schedule values as real state; show only actual session metadata and truthfully mark copy/Target/AI capability unavailable. Preserve U54–U60 validation, approval, simulation and Oracle backend boundaries.
- U62 (owner product-boundary clarification, 15 October 2026): Source databases are never written. The intended output is a new Dataset stored locally on this machine; no external Target publish is implied. Checked Table/View objects in the Oracle catalog are discovered sequentially, at most 20 per request, using metadata-only queries; successful snapshots become selectable inputs to the Dataset request. No Source rows are read during this discovery, no AI call is enabled, and local durable Dataset storage/extraction remains unimplemented until separately built and verified. Partial errors are reported; selecting objects does not itself approve or create a Dataset.

Reference files: `docs/ui-reference/U-ETL_DataBridge_UI_Reference.html` and the earlier root copy are present. The owner supplied screenshots for visual comparison; direct Browser inspection could not be completed in the agent environment. Source/implementation limitations: `docs/ui-reference-implementation.md`.

เอกสารนี้เป็นข้อกำหนดหลักของ U-ETL Factory Data Bridge โดย Revision Notes v1.3 และส่วน “Dataset-first workflow” ด้านล่างเป็นข้อกำหนดล่าสุด หากข้อความ v1.2 ในเอกสารเดียวกันขัดแย้ง ให้ v1.3 มีผลแทนเฉพาะส่วนที่ขัดแย้งและคงข้อกำหนด connection/security/recovery/incremental ที่ยังสอดคล้องไว้ ไม่มีไฟล์ Blueprint v1.2 แยกหรือ Git history ใน workspace นี้ จึงเป็นการทำ requirement-to-implementation gap review ไม่ใช่การเดาความแตกต่างย้อนหลัง

เป้าหมายผลิตภัณฑ์มาจากการใช้งานวิเคราะห์ข้อมูลการผลิต Semiconductor ของ Operation Excellent, Engineering Department, UTAC Thai Limited ข้อมูลและกฎทางธุรกิจยังต้องให้ Data Owner/DBA ตรวจยืนยันก่อนใช้จริง

## v1.3 Dataset-first workflow — current authority

### จุดเริ่มต้นและ workflow

จุดเริ่มต้นของผู้ใช้คือ **Dataset ที่ต้องการและวัตถุประสงค์ทางธุรกิจ** ไม่ใช่การเลือก Table หรือเริ่มจากการดู Mapping ตัวอย่าง workflow หลักคือ:

**Create Dataset → Select Sources → Discover → Suggest Mapping → Review Fields & Relationships → Preview & Quality Checks → Approve Dataset Definition → Transform & Publish → Monitor & Update**

Yield Analysis เป็น Pilot Use Case ไม่ใช่ข้อจำกัดของผลิตภัณฑ์ ตัวอย่างคำขอ: “Yield Analysis: Lot number, input quantity, output quantity, package code, customer code, product/production code, production area.” `Product code` และ `Production code` เป็นคนละความหมายได้ ระบบต้องแยกให้ผู้ใช้พิจารณา ไม่รวม/เดาความหมายเอง

### Dataset Request

คำขอต้องเก็บ Dataset name, business purpose, requested business fields, selected Source profiles, requested time window, business-filter description, grain และ Target preference (เมื่อมีการตั้งค่า) พร้อม Request ID/revision/actor/time เมื่อ Backend พร้อม ข้อความ filter เป็นภาษาธุรกิจ ไม่ใช่ SQL ที่นำไปรันได้โดยตรง

Grain ที่เลือกได้รวมหนึ่ง record ต่อ Lot, Lot/Operation และ Production Event รวมถึง User-defined/Unknown ระบุผลกระทบต่อ join, aggregation, rework/retest และจำนวนแถว หากผู้ใช้ไม่ทราบให้แสดงข้อเสนอและคำถาม; ห้ามเลือก grain เงียบ ๆ และต้อง Block การอนุมัติ Definition จนยืนยัน grain/วิธีจัดการที่จำเป็น

Source, Application Registry และ Analytics Target เป็นคนละบทบาทกัน Target preference ใน Prototype ไม่ใช่การยืนยันหรือเชื่อมต่อ Target จริง การสร้าง Definition ไม่ได้หมายถึง Publish

### Candidate Ranking / Review

Candidate แต่ละรายการต้องมี Requested business field, Source/profile, Schema/Table/Column, source datatype, Matching Score และหน่วย/คำอธิบาย, หลักฐานและ dictionary/model version, alternatives, ambiguity/limitations, datatype compatibility และ join confidence ที่แยกจากกัน สถานะประกอบด้วย Pending, Approved, Overridden, Rejected, No suitable match และ Stale

Matching Score ใช้จัดอันดับเท่านั้น หากยังไม่มี calibrated evaluation ให้ระบุชัดว่าเป็น uncalibrated ranking points ไม่ใช่เปอร์เซ็นต์หรือความน่าจะเป็น แยก semantic evidence, datatype compatibility และ join confidence; ไม่รวมเป็น score เดียวโดยไม่อธิบายเหตุผล ข้อมูลที่ไม่มี candidate ต้องแสดง No suitable match ไม่ถูกเติมด้วยค่าที่ระบบเดา

Business Dictionary/Canonical Model เป็นมาตรฐานที่ทีมข้อมูลดูแลและ starter template ที่ต่อยอดได้ ไม่บังคับทุก Dataset ให้ตรงตารางมาตรฐานเดียว ผู้มีอำนาจดูแล Dictionary ต้องเพิ่ม/แก้ entry ผ่าน revisioned workflow; ผู้ใช้ปลายทางสามารถเสนอ business field ใหม่ใน Dataset Request แต่ระบบต้องไม่สร้าง/อนุมัติ Canonical field หรือ Target schema โดยอัตโนมัติ

Rule-based candidate provider เป็น fallback ที่ตรวจสอบได้ ไม่ใช่ AI: สามารถใช้ normalized exact name, curated aliases, metadata descriptions/types และ constraints โดยแสดงหลักฐานทุกข้อ ชื่อคล้ายหรือ synonym เช่น `BATCH_NO` เป็นเพียง candidate ไม่พิสูจน์ว่าเป็น Manufacturing Lot ความกำกวมต้องขอ explicit reviewer override พร้อมเหตุผล `Sample` values ไม่เป็น Mapping evidence จนกว่าจะอนุมัติ profiling scope/budget แยกชัดเจน

Review actions: เลือก alternative, Approve candidate, Override พร้อมเหตุผล, Reject พร้อมเหตุผล หรือระบุ No suitable match พร้อมเหตุผล การแก้ Request/Source config/discovery revision/dictionary/model version ทำให้ candidates/reviews/definition approval เก่าหมดอายุ Mapping approval ต้องผูก actor, evidence snapshot, request/definition revision และ audit เมื่อ Backend รองรับ

### Dataset Definition และ Publish gate

Versioned Dataset Definition ต้อง snapshot request/sources/connection revisions, fields, mapping decisions/transforms, grain, join plan, filters, quality rules, reviewer/evidence, dictionary/model/provider versions, target/generation, refresh strategy และ lineage ไม่มี approved Definition สำหรับ revision ปัจจุบัน หรือมี required field missing/ambiguous, grain/join unknown, type incompatibility หรือ stale source/dictionary ให้ Block Preview/Publish ที่เกี่ยวข้อง

Candidate ranking, review, approved Dataset Definition และ feedback เป็นคนละสถานะกัน การกด Approve ใน UI Prototype เป็น session-only interaction เท่านั้น ไม่ใช่ durable approval, Mapping Bundle ที่ใช้กับ ETL, หรือ authorization ให้ Transform/Publish จริง ห้ามนำ mock run ไปแสดงเป็น real ETL success

### AI/Feedback/Evaluation

AI provider ยังไม่ถูกเลือกและต้องปิดการเรียก AI ไว้ในรอบนี้ เตรียม provider adapter boundary ได้ แต่ห้ามส่ง metadata/sample/credentials ออกนอกองค์กรโดยอัตโนมัติ Rule baseline ต้องระบุว่าไม่ใช่ AI

เก็บ feedback แยก Approved, Corrected, Rejected เนื่องจาก semantic meaning ผิด, และ Not selected in this Dataset (ไม่เท่ากับความหมายผิด) การใช้ Mapping ที่อนุมัติซ้ำเป็น retrieval/memory ไม่ใช่การ Train model การ Train/evaluate ภายหลังต้องมี versioned gold labels, holdout, leakage check และวัดผลแยกตาม domain/field/join ก่อนกล่าวอ้างความแม่นยำ ไม่ train โมเดลใหญ่จากข้อมูลไม่กี่รายการ

### Implementation boundary ณ 9 ตุลาคม 2026

- สแต็กที่มีอยู่: Vanilla JavaScript/HTML/CSS UI, Node static Demo host และ Python standard-library local HTTPS Oracle read-only spike; มี offline SQLite Foundation harness แยกต่างหาก คงสแต็กเดิมใน Milestone นี้ ไม่ย้ายเป็น React/FastAPI โดยไม่มีการตัดสินใจใหม่
- **Multi-engine requirement clarified by owner (9 ต.ค. 2026):** Product connection architecture must support database engines beyond Oracle. Oracle remains the first/only verified real Source connector. SQL Server, PostgreSQL, MySQL and MariaDB are candidate profile types only until engine/version, Source/Target use, auth/TLS, driver policy and test endpoints are confirmed; the SQL Server Demo fixture is not a connector. UI and API contracts must expose per-engine capability/status and fail closed for unavailable adapters. This clarification does not authorize new DB connections or Target writes.
- Owner-reported live Source evidence: Oracle 12.2.0.1.0 / database IOT / identity BIDPENGUSR1, Test Connection, metadata discovery `BIDPITDBA.DP_WIP_DATA`, bounded sample 25 rows. เป็นหลักฐานที่ผู้ใช้ทดสอบ ไม่ใช่ agent-run evidence; ไม่ได้ยืนยันอีก 8 ตาราง, AI, approved mapping, Registry หรือ Target publish
- Live read spike ใช้ memory-only sessions/jobs และ Worker thread; SQLite Registry/Worker เป็น offline synthetic harness คนละ path ไม่มี real durable Registry/API/AI/ETL/Target Publish
- UI จะคง 9 เมนูเดิม; Overview เริ่มด้วย Create Dataset Request, Data Sources ใช้ profile `Data Prep IOT` เดิม, Data Mapping ใช้ review workspace เดิม ห้ามสร้าง Oracle page/card ซ้ำหรือทำ Demo ให้ดูเหมือนข้อมูลจริง
- Candidate baseline ใน Prototype อ่าน metadata ของ discovery ที่เลือกและ synthetic Demo metadata แยก environment; ไม่ใช้ตัวอย่าง row values มาจัดอันดับ ไม่เรียก AI และ state/review ไม่ persist ข้าม session
- การจัดการข้อมูล Demo ตามคำขอเจ้าของโครงการ (9 ต.ค. 2026): normal launch ไม่มี seeded Demo connection/rows/runs; migration ล้างเฉพาะข้อมูล synthetic ที่แอปเก็บใน browser storage และคง non-Demo connection profile ไว้ โหมดจำลองคงเฉพาะ URL `?demo=1` สำหรับ automated regression; หน้าผล ETL/Quality/Explorer/History ปกติไม่แสดง mock success หรือ mock rows

### Phase/roadmap authority ณ v1.3

| Phase | สถานะจาก Repository/evidence ล่าสุด | ทางออกถัดไป / Acceptance boundary |
|---|---|---|
| 0 — Confirm & Spike | Partially complete: owner-reported Oracle Test + Discovery + bounded 25-row sample สำหรับ `BIDPITDBA.DP_WIP_DATA`; ยืนยัน Local Windows และ Application Registry แยก Target | DBA ยืนยัน read-only grants/query budget/network policy; Target/Registry engine/provisioning/runtime identity/secret/auth decisions ยังเปิด; ไม่ขอ password ในแชต |
| 1 — UI Prototype | Accepted nine-menu baseline retained; normal mode is now clean of seeded Demo data. v1.3 Dataset Request/ranking/review automated Browser regression passes; owner UAT remains pending | Preserve nine menus and Data Prep IOT card; full synthetic flow stays test-only at explicit `?demo=1`; Dataset request and deterministic candidate/revision flow tested; no real ETL capability |
| 2 — Foundation | Partial: isolated memory-only HTTPS Oracle read spike + separate offline synthetic SQLite Registry/Worker; API contracts remain design | Implement actual selected Registry/API, durable auth/audit/approvals/jobs, safe secret references and supervised separate worker only after decisions/provisioning; restart/recovery tests |
| 3 — Discovery & Mapping | Partial for one owner-tested table's metadata/sample; no durable dictionary/candidates/mapping approvals | Source snapshot pipeline and versioned dictionary/provider/review evidence; Data Owner gold mapping and ambiguity/join/grain review; profile only with explicit budget |
| 4 — ETL MVP | Real ETL not started; UI model is Demo simulation | Approved Dataset Definition, confirmed Target, source-specific run boundaries/late-commit strategy/initial handoff, idempotent retry, quarantine and atomic publish/watermark tests |
| 5 — Quality & Explorer | Demo pages only for real data; no Target records | Real rule/reconciliation, durable quarantine reprocess, lineage and authorized explorer acceptance |
| 6 — Pilot & Release | Not started | Test-environment UAT/performance/operations/backup/restore/release approval; Production is separate authorization |

Implementation order in this milestone: A) current-state/gap review; B/C) v1.3/docs/contracts; D) preserve UI and add Dataset Request + metadata-only ranking/review prototype; E) next dependencies/plans. Scheduler/CDC stay later. Do not block these local synthetic tasks on DBs; do not represent the UI state as durable service behavior.

## 1. เป้าหมายและภาพปลายทาง

สร้าง Application เดียวสำหรับเชื่อมฐานข้อมูลโรงงานหลายระบบ ทำความเข้าใจโครงสร้างและความหมายข้อมูล เสนอ Mapping ให้ตรวจสอบ แล้ว Transform, Integrate และ Load ลงฐานข้อมูล Analytics กลาง ผู้ใช้ตรวจผลและย้อนกลับถึง Source ได้ภายในโปรแกรมเดียว

### Owner clarification after v1.3 — 9 October 2026

The product must discover the full catalog of schemas and objects that the configured Source identity is authorized to see, across supported Source engines; a single fixed schema/table allowlist is not the product-wide discovery design. Discovery is metadata-only and must respect database grants, per-user/workspace authorization, explicit exclusions and bounded catalog-query budgets. “All schemas” does not mean DBA/admin visibility, access to denied objects, reading table rows, or granting new Source permissions. **Owner clarification 9 October 2026:** the owner authorizes catalog metadata across every schema/object visible under the configured Oracle user account's existing grants; no database permission change is requested. Catalog discovery does not sample rows automatically; selected-object detail and bounded sample remain separate explicit actions. This is authorization for metadata discovery, not for full extraction/ETL.

AI-assisted Dataset selection is a required target capability: given the user's Dataset purpose/fields, an AI provider should rank relevant discovered schemas/tables/columns and explain evidence, alternatives and uncertainty. AI output is a recommendation, never approval, SQL execution, or permission to sample/extract. Human review remains required. Do not send credentials, row samples or unrestricted factory metadata to an external service. Provider/runtime location, approved metadata fields, retention/logging, and external-transfer policy must be selected before enabling an AI call. Until then, the AI feature remains not implemented/disabled; deterministic matching may be shown only as a clearly labelled non-AI fallback, not as equivalent fulfilment of the AI requirement.

Workflow ปัจจุบัน v1.3 เริ่มที่ Create Dataset Request แล้วค่อย Select Sources → Discover → Suggest/Review Mapping & Relationships ตาม section v1.3 ด้านบน ขั้นตอน Connect-first ต่อไปนี้เป็น workflow เดิม v1.2 ซึ่งถูกแทนเฉพาะจุดเริ่มต้น

หลัง Definition ได้รับอนุมัติ: เปิด Application → เลือก Dataset Definition/Run → ตรวจ Source/Target readiness และ version/revision → Transform & Load → ตรวจ Quality/Lineage/History หาก Source, Dictionary หรือ Definition เปลี่ยน ให้ invalidate/review ส่วนที่กระทบก่อน

การเป็น Application เดียวหมายถึงมี UI และ Workflow เดียว ส่วน API, Worker และ Database สามารถแยกส่วนเบื้องหลังได้ งานต้องทำต่อเมื่อผู้ใช้ปิดหน้าจอ และเมื่อเปิดกลับมาจะเห็นสถานะเดิม

### ผลลัพธ์ที่คาดหวัง

- แหล่งข้อมูลต่างชื่อ เช่น LOT_NO และ LOT_NUMBER มีมาตรฐานกลางที่ผ่านการยืนยัน
- สร้าง Analytics Database ที่มี Raw/Staging, Core และ Mart พร้อมการติดตามต้นทาง
- Mapping ที่อนุมัติแล้วนำกลับมาใช้ได้โดยไม่เรียก AI ในทุก ETL Run
- เห็นข้อมูลที่โหลดได้ ข้อมูลที่แยกไว้ตรวจสอบ และเหตุผลที่โหลดไม่ได้
- Power BI หรือเครื่องมืออื่นเชื่อมกับ Target Database ได้ โดยการ Refresh Power BI อัตโนมัติเป็นงานภายหลัง

## 2. ขอบเขตรุ่นแรกและรุ่นต่อไป

| ส่วน | MVP / รุ่นแรก | ระยะถัดไป |
|---|---|---|
| Source | มี owner-reported Oracle 12.2.0.1.0 read-only Test/Discovery/Sample สำหรับ `BIDPITDBA.DP_WIP_DATA` หนึ่งตาราง; ไม่ได้ยืนยันทั้ง allowlist | Source อื่นและการทดสอบ Oracle table ที่เหลือหลัง scope/query budget พร้อม |
| Target | Engine/Server/Database ยังไม่ยืนยัน; Demo target เป็น synthetic เท่านั้น | เลือก Analytics Target หลัง IT/DBA ยืนยัน Test destination และสิทธิ์ |
| Discovery | Schema, Table, Column, PK/FK และ View metadata; Allowlist ตาราง | View extraction ที่ยืนยัน Key และประสิทธิภาพแล้ว |
| Profiling | ตัวอย่างแบบจำกัด, null, distinct, pattern, type | Profiling ขนาดใหญ่และปรับตามความเสี่ยง |
| Mapping | Lot, Equipment, Process; กฎและคำแนะนำ AI แบบเลือกเปิด | Quality, Defect, Test, Measurement ครบ |
| Relationships | PK/FK และ Candidate ที่ผู้ใช้ตรวจ | ความสัมพันธ์ซับซ้อนและ Lot genealogy |
| ETL | Full initial load, Incremental ที่มี Key/Watermark ที่เชื่อถือได้ | CDC, delete capture, scheduling |
| Data Model | dim_lot, dim_equipment, dim_process, fact_process | Quality/Test facts และ Mart |
| UI | เมนูทั้งหมดพร้อม Prototype; MVP ใช้งานส่วนหลักได้ | Lot 360 ครบทุก Domain |
| Operations | Run History, Quality, retry, audit | Enterprise SSO, HA, multi-site scaling |

MVP ไม่ใช่การเข้าใจทุก Database อัตโนมัติ 100% และไม่สร้าง KPI จากชื่อ Column อย่างเดียว ตารางที่ยังไม่มี Mapping หรือ Grain ชัดเจนจะไม่ถูก Publish เข้า Core

## 3. ผู้ใช้และสิทธิ์

| บทบาท | สิทธิ์หลัก |
|---|---|
| Admin | Connection, Target, Dictionary, ผู้ใช้และนโยบายระบบ |
| Data Steward | ตรวจและอนุมัติ Mapping, Relationships, กฎคุณภาพ |
| Operator | เรียกงานที่ผ่านอนุมัติ ติดตามและ Retry |
| Viewer | ดูสถานะและข้อมูลที่ได้รับสิทธิ์ |

MVP ใช้ Local accounts ได้ แต่การเข้าถึงข้อมูลจริงต้องมี Authentication/Authorization ฝั่ง Backend เก็บ Audit ว่าใครเปลี่ยนอะไร เมื่อใด และใช้เวอร์ชันใดในแต่ละ Run

## 4. UI/UX Specification

### โครงสร้างร่วม

Sidebar: Overview (Dataset Request entry point) / Data Sources / Data Mapping / Relationships / Transform & Load / Data Explorer / Data Quality / Run History / Settings; คง 9 เมนูเดิม

ส่วนหัวแสดงชื่อ Workspace และ Environment: Demo, Test หรือ Production อย่างชัดเจน ส่วนท้ายแสดง Target และ Last Successful Run ทุกหน้ามี loading, empty, error และ retry state

หน้าจอ Desktop เป็นหลัก รองรับความกว้างประมาณ 1366 px ขึ้นไป และมีตารางเลื่อนแนวนอนเมื่อจำเป็น ใช้ Navy สำหรับโครงสร้างหลัก สีฟ้าสำหรับปุ่มหลัก สีเขียวสำหรับสำเร็จ สีเหลืองสำหรับต้องตรวจ และสีแดงสำหรับ Blocker ทุกสถานะมีข้อความ/ไอคอนร่วมกับสี ฟอนต์อ่านภาษาไทยและอังกฤษได้

Standard Mode แสดงงานและเหตุผลที่ผู้ใช้ต้องตัดสินใจ Advanced Mode เปิด Profiling, Transform rules, Watermark, SQL details และ Logs สิทธิ์ยังถูกบังคับเหมือนเดิม ไม่ขึ้นกับโหมดหน้าจอ

| หน้า | เนื้อหาและการกระทำ | เงื่อนไข UX |
|---|---|---|
| Overview | Source/Target readiness, Mapping pending, Last run, ปุ่ม Transform & Load | หากยังไม่พร้อม ปุ่มนำไปแก้ Blocker; ไม่เริ่มงานเงียบ ๆ |
| Data Sources | Source cards, Add/Edit, Test, Select tables, Analyze; Target แยกชัด | Connected หมายถึง Test ผ่าน ณ เวลาที่ระบุ ไม่รับประกันว่าเชื่อมได้ตลอด |
| Data Mapping | Filter Source/Domain/Status, ค้นหา, Mapping table, Review drawer | Confidence และ Approved แยกกัน; ค่า Confidence สูงไม่เท่ากับถูกอนุมัติ |
| Relationships | Graph และ List view; หลักฐาน, Key, Cardinality | เส้นที่ระบบเสนอแยกจากเส้นที่อนุมัติ; คลิกดู Evidence ได้ |
| Transform & Load | Scope, Mode, Pre-check, Preview, Start, Progress, Cancel | คำนวณความพร้อมจาก Table ที่เลือก ไม่ใช่ % Column ทั้ง Database |
| Data Explorer | Target tables, Filter, จำกัดแถว, Lot detail, Lineage | แสดงข้อมูลที่ Publish สำเร็จ; MVP ไม่เปิด SQL editor อิสระ |
| Data Quality | Rule results, Severity, rejected rows, View records | แยกข้อมูลผ่าน/กักไว้/Run ที่ Block; ห้ามมีคะแนนรวมที่ไม่มีสูตร |
| Run History | Run ID, status, rows, duration, version, details, retry | งานปิด UI แล้วยังอยู่; Retry มี scope และผลชัดเจน |
| Settings | Dictionary, AI policy, limits, retention, users | ค่าที่มีผลต่อ Run ต้องบันทึกเป็นเวอร์ชัน |

### First-run wizard

1. Create Dataset Request: purpose, business fields, source profiles, time/filter, grain และ Target preference; ทำโดยไม่ต้องเปิด Target จริง
2. เลือก Source profile; Test/Connect ตามสิทธิ์ แล้วเลือก Schema/Table ที่อนุญาต
3. Discover metadata ตามขอบเขต; profiling/sample ทำเฉพาะเมื่อผู้ใช้เลือกและยืนยัน budget
4. สร้าง Candidate ranking พร้อม evidence/alternatives/ambiguities/missing/type; baseline ไม่ใช่ AI
5. Review/override/reject fields, grain, keys, relationships/cardinality และ join fan-out; unresolved blockers ห้ามอนุมัติ Definition
6. Preview และ Quality checks จาก Definition version ที่กำลัง review; Prototype แสดงเฉพาะ synthetic behavior ไม่ใช่ real ETL
7. Approve versioned Dataset Definition แล้วจึง Transform/Publish เมื่อ Backend/Target จริงผ่าน Acceptance
8. Monitor Quality/Lineage/History; การ Refresh ใช้ strategy ที่ตรวจรับแล้วและอยู่ใต้ incremental/recovery contracts เดิม

Wizard กลับมาแก้ขั้นก่อนหน้าได้ เก็บงานที่ทำแล้ว เมื่อ Mapping เปลี่ยน Preview/Pre-check เดิมต้องหมดอายุ

### Connection Setup — หน้าตอนเปิดโปรแกรม

โปรแกรมต้องมีหน้าเลือก Connection ก่อนเข้าสู่ Workflow ข้อมูลจริง หากมี Application login ให้ Login ก่อน แล้วแสดงเฉพาะ Connection ที่ผู้ใช้นั้นมีสิทธิ์ บัญชีเข้า Application และบัญชี Database เป็นคนละส่วน การ Connect ไม่ใช่การเริ่ม Analyze หรือ Load อัตโนมัติ

หน้า Connection Setup แบ่ง Source Databases (เลือกได้หลาย Connection) และ Target Analytics Database (เลือกหนึ่ง Connection ต่อ Run) มีตัวเลือก Use saved connection / Add new connection และปุ่ม Test Connection, Connect, Edit, Disconnect ส่วน Demo เปิดได้โดยไม่ต้องมีฐานข้อมูลจริง

| Field | พฤติกรรมที่กำหนด |
|---|---|
| Connection name | ชื่อแสดง เช่น UTL1 MES; ไม่ใช้ Password เป็นส่วนของชื่อ |
| Connection role | Source หรือ Target ชัดเจน |
| Database engine | MVP SQL Server; Engine อื่นยังไม่ให้เลือกใช้งานจริงจนมี Connector |
| Server/Host | รองรับรูปแบบ endpoint ที่ Connector รองรับ; SQL Server แยก Instance/Port เมื่อจำเป็น |
| Database | กรอกชื่อได้ก่อน Connect; list databases เป็น Optional ตามสิทธิ์ ไม่ต้องมีสิทธิ์อ่านทุก DB |
| Authentication | SQL Server Authentication หรือ Windows Integrated เมื่อ Environment รองรับ |
| Username | แสดงและจำได้ตามตัวเลือก สำหรับ SQL Authentication |
| Password | Mask โดย default; Show/Hide แบบชั่วคราว; Password ที่บันทึกแล้วไม่ส่งกลับ UI |
| Remember connection | บันทึกชื่อ/endpoint/database/auth type; ไม่รวม Password โดยอัตโนมัติ |
| Remember username | แยกจากการบันทึก Password และจำเฉพาะเมื่อเลือก |
| Save password securely | ปิดโดย default; เปิดได้เฉพาะเมื่อ Secret store พร้อมและนโยบายอนุญาต |
| Advanced connection | Timeout และ TLS policy; ไม่ใส่ Secrets ใน URL หรือ free-text ที่ถูก Log |

Windows Integrated ใช้ตัวตนของ Backend/Worker Process หรือ Service ที่กำหนด ไม่รับประกันว่าเป็นบัญชี Windows ของคนเปิด Browser ต้องแสดง effective execution identity ที่ตรวจได้ หาก Worker อยู่คนละเครื่องหรือบัญชี ต้องทดสอบจาก Worker ด้วย ห้ามจำลองว่า Windows Authentication ผ่านจากการตรวจ UI เพียงอย่างเดียว

### Connection states และการเปลี่ยน Connection

States: not_configured, disconnected, testing, test_passed, connecting, connected, failed, credentials_required แสดง Last tested time และข้อความ error ที่แก้ได้ เช่น auth failed, network timeout หรือ database access denied โดยไม่เผย Secret

Test Connection ตรวจ endpoint/database/auth และสิทธิ์ที่จำเป็นจาก Runtime ที่ทำงานจริง การ Test ผ่านไม่ถือว่าเปิด Session ถาวร Connect ตรวจอีกครั้งและกำหนด Active selection; ก่อน Analyze/Load Worker ต้องตรวจ Connection อีกครั้ง

เมื่อแก้ Server, Database, Authentication หรือ Credentials ผล Test เดิมหมดอายุ เมื่อเปลี่ยน Active Source/Target ต้อง invalidate Preview/Pre-check ที่เกี่ยวข้อง Mapping ของ Source เดิมยังเก็บไว้โดยผูก stable source_id ไม่ย้าย Mapping ไป Source ใหม่เพราะชื่อเหมือนกัน

Source ใหม่ต้อง Analyze/Review ก่อน Load ส่วน Target ใหม่ต้องตรวจ readiness และ initial-load/watermark scope ใหม่ ห้ามใช้ checkpoint ของ Target เดิม Target replacement หรือ Full refresh ต้องแสดงสิ่งที่จะเปลี่ยนและขอบเขตข้อมูลก่อนเริ่ม ไม่ลบ Database ทั้งก้อนโดย default

### Credential lifecycle และ Background jobs

- Credentials เดินทางจาก UI ไป Backend ผ่านช่องทางที่ป้องกันตาม deployment; ไม่อยู่ใน browser localStorage/sessionStorage, URL, logs, export, fixture หรือ Git
- หากเลือก Save password securely เก็บใน OS credential store สำหรับ local deployment หรือ Secret manager ฝั่ง Server ตาม ADR ของ Phase 0; Metadata เก็บเฉพาะ secret_ref และ credential scope ไม่เก็บ plaintext หรือ encryption key คู่กับ Password
- หากไม่บันทึก Password ให้ใช้ในหน่วยความจำ Backend/Worker สำหรับ Session/Run ที่อนุญาตเท่านั้น การปิด Browser ไม่ทำให้ Worker ทิ้ง Credentials ระหว่าง Run แต่เมื่อ Backend/Worker restart ต้องขอกรอกใหม่ก่อน Resume ห้ามแอบ Persist Password เพื่อให้ Retry ผ่าน
- หาก Secret store ไม่พร้อม ให้ปิดตัวเลือก Save password พร้อมเหตุผล และให้กรอกใหม่ได้
- Edit Password ช่องว่างหมายถึงคง Secret เดิม; มี Clear saved password แยกชัดเจน และต้องตรวจสิทธิ์ หากมี Run ใช้งานอยู่ไม่ลบ Secret จนไม่มี reference ที่ต้องใช้งาน
- Disconnect ยกเลิก Active selection/ปิด idle connections แต่ไม่ยกเลิก Run ที่กำลังทำงานเอง; หากต้องหยุดงานใช้ Cancel Run โดยตรง
- หลัง restart จำ Connection selection ได้ แต่แสดง disconnected/credentials_required จนผ่านการตรวจใหม่ ไม่จำสถานะ connected เป็นข้อเท็จจริง
- Run บันทึก Connection config revision และ Secret reference/version ที่ใช้ โดยไม่บันทึกค่า Secret; การแก้ Connection ระหว่าง Run ใช้กับ Run ใหม่ งานเดิมใช้ Snapshot ที่เริ่มไว้

### Bootstrap และการสร้าง Target

โปรแกรมต้องเปิดหน้า Setup ได้แม้ยังไม่มี Target Database กำหนด Local bootstrap config เฉพาะค่าที่ไม่ใช่ Secret และใช้ Secret store/หน่วยความจำตาม policy Metadata/job registry ต้องพร้อมก่อนเริ่ม Background job โดย Phase 0 เลือกว่าจะเป็น Application database แยกหรืออยู่ Target พร้อมวิธี Bootstrap ห้ามสร้างวงจรที่ต้องต่อ Target ก่อนจึงจะอ่านข้อมูล Connection ของ Target ได้

Default ใช้ Target Database ที่มีอยู่และสร้าง schemas/tables ผ่าน migration ที่ผ่าน review หากต้องการ Create new database ให้เป็นตัวเลือก Admin แยก ตรวจสิทธิ์และ Preview ชื่อ/DDL ก่อนทำ ไม่สมมติว่าบัญชี Load มีสิทธิ์ CREATE DATABASE ไม่มีการ Drop database อัตโนมัติ

### Mapping review drawer

แสดง Source/Table/Column, suggested standard field, type, transform, evidence, alternatives, sample และข้อขัดแย้ง ผู้ใช้เลือก Approve / Override / Reject / Exclude ได้ Exclude ต้องมีเหตุผล และห้าม Exclude required key เพื่อหลีกเลี่ยง Blocker

Bulk approve แสดงรายการและผลกระทบก่อนทำ และใช้ได้เฉพาะรายการที่ไม่มีข้อขัดแย้งเชิงโครงสร้าง

### Load Mode และสถานะการอัปเดตข้อมูล

- Initial Load: ใช้เมื่อ Target scope ยังไม่เคย Publish สำเร็จ แสดงขอบเขตข้อมูลและ Preview ก่อนเริ่ม
- Incremental Load: ใช้หลัง Initial สำเร็จและมี extraction strategy ที่ตรวจรับแล้ว เป็นตัวเลือกเริ่มต้นสำหรับ scope ที่พร้อม
- Full Refresh: แยกจาก Initial และ Incremental แสดงผลกระทบต่อ Target ก่อนเริ่ม ไม่ลบทั้ง Database และไม่ Reset watermark เงียบ ๆ
- แสดงต่อ Table: Strategy, Last successful sync, Last attempt, Committed watermark และขอบเขต Run; Standard Mode ใช้คำอธิบายง่าย ส่วนค่าทางเทคนิคอยู่ Advanced Mode
- Progress/Result แสดง Extracted, Inserted, Updated, Unchanged, Quarantined, Filtered และ Duplicate/Superseded พร้อมนิยามที่ไม่ทับซ้อน ตัวเลข upsert ต้องแยกจากยอดแถว Target ปัจจุบัน
- No new data เป็นข้อความผลลัพธ์ของ Run ที่สำเร็จ ไม่ใช่ error; ห้ามเพิ่มจำนวน Target หรือ Watermark จากค่าที่ไม่ได้ยืนยันด้วย strategy
- Last successful sync หมายถึงเวลาที่ Publish สำเร็จ ไม่รับรองว่าข้อมูล Source ทั้งหมดถึงเวลานั้นถูกโหลดแล้ว แสดง data cutoff/lag เฉพาะเมื่อมีข้อมูลรองรับ
- แสดง Unsupported incremental พร้อมเหตุผลหาก Key/change tracking ไม่พร้อม; ห้ามเลือก Incremental แล้วใช้ Full refresh แทนโดยไม่แจ้ง
- Prototype ต้องจำลอง: Initial, Incremental ที่มีแถวใหม่, ไม่มีข้อมูลใหม่, มี Insert ระหว่าง Run, Commit ช้า, Failure/Retry และ schema drift
- Scheduler/CDC อยู่ระยะถัดไป หน้า MVP ไม่แสดงสถานะเสมือนว่ามี Auto-sync จริง หากแสดงแนวคิดให้ติดป้าย Planned/Unavailable

### Run progress

แสดง Connecting → Extracting → Staging → Transforming → Integrating → Validating → Publishing พร้อมจำนวนแถวและสถานะต่อ Table หากยังไม่รู้จำนวนรวมใช้ progress แบบไม่ระบุ % และไม่สร้าง Estimated time ปลอม

Cancel หยุดที่ขอบเขต Batch ที่ปลอดภัย แล้วแสดงสิ่งที่สำเร็จ/ค้างอยู่ ข้อมูลที่ยังไม่ผ่าน Validation ไม่ปรากฏเป็น Core/Mart ที่สำเร็จ

## 5. Technical Architecture ที่เสนอ

เริ่มแบบ Local/On-premises Application: Frontend ใน Browser + Backend API + Background Worker บนเครื่อง/Server ภายในเครือข่าย ใช้ Launcher เปิดหน้าจอภายหลังได้ หากต้องการ Installer แบบ Windows ให้ออกแบบ Packaging หลังทดสอบ Driver และระบบฐานข้อมูลจริงแล้ว

Stack ใน Repository ปัจจุบันคือ Vanilla JavaScript/HTML/CSS สำหรับ UI, Node static Demo host, Python standard-library local HTTPS Source spike และ offline SQLite synthetic Foundation harness แยกกัน ให้รักษา stack นี้ต่อใน Dataset Request/candidate Prototype ไม่ migrate UI หรือ API framework โดยไม่มี ADR/เหตุผลจากการตรวจ stack จริง ข้อเสนอ React/TypeScript + Python/FastAPI ด้านล่างเป็นทางเลือกเดิมที่ยังไม่ได้เลือกหรือ implement

| Component | หน้าที่ |
|---|---|
| Frontend | เก้าเมนูเดิม; Dataset Request ใน Overview, Candidate/Review ใน Data Mapping, progress, explorer |
| API | Design contract ครอบคลุม Dataset Request/Definition, Auth, config, validation, งาน async และสถานะ; API contract ไม่ถือว่าเป็น implemented service |
| Worker | Discovery, profiling, mapping suggestions, ETL และ quality |
| Connector interface | Metadata, samples, bounded extraction และ pagination ตาม Source |
| Mapping engine | Dictionary/rules/evidence และ optional AI adapter |
| Metadata registry | Config, versions, approval, lineage และ run history |
| Target writer | Staging, deterministic transformations, transactional publish |

MVP ใช้ Job queue ใน Database ได้ โดย Worker มี lease/heartbeat และป้องกัน Job ถูกทำซ้ำพร้อมกัน งานบน Table เดียวกันต้องมี lock การยกเลิกและ recovery ไม่อาศัยสถานะใน Browser

### Data path

Source (read only) → Run-scoped Raw/Staging → Transform ด้วย Approved mapping version → Core validation → Publish Core → Build/Publish Mart

Source ห้าม Rename Column, สร้าง Table หรือแก้ข้อมูล Credentials ของ Source ใช้ Read-only และจำกัด Schema ที่อนุญาต Target ใช้บัญชีแยกและสิทธิ์เท่าที่จำเป็น

## 6. หลักการ Mapping และ AI

Canonical Dictionary/Business Dictionary เป็นมาตรฐานที่ทีม Data Owner ดูแลและแก้แบบมี version; Canonical Manufacturing Model เป็น starter template ไม่ใช่บังคับทุก Dataset ผู้ใช้ระบุ business field ใหม่ได้ใน Dataset Request แต่การเพิ่ม field เข้ากลาง/Target ต้องผ่าน Dictionary governance แยก AI หรือระบบ rule เสนอ Candidate ได้แต่ห้ามสร้างชื่อกลางใหม่หรือ Load ทันที

Evidence: ชื่อ Column, ชนิดข้อมูล/description, table context, PK/FK, approved dictionary และ Mapping เดิม; profile/sample เป็นหลักฐานเพิ่มได้เฉพาะ scope ที่อนุมัติ บันทึกว่ามาจาก metadata, sample หรือทั้งชุดและจำนวน/เวลาอย่างชัดเจน ห้ามนำ Source sample ไปใช้จัดอันดับโดยไม่ opt-in profiling ที่กำหนดงบและ policy

คะแนน Candidate ที่ยังไม่ได้ calibrate ด้วย gold labels ให้เรียกว่า Matching Score / uncalibrated ranking points ไม่เรียก Probability ว่าถูกต้อง 97% น้ำหนักและ threshold ปรับจาก Pilot dataset ไม่ใช้เปอร์เซ็นต์จากตัวอย่างบทสนทนาเป็นเกณฑ์ Production ต้องแสดง semantic evidence, datatype compatibility และ join confidence แยกจากกัน

AI ไม่อยู่ใน Critical path ของ Production ETL เมื่อ Mapping อนุมัติแล้ว การเรียก AI มี timeout, cost limit, log แบบไม่เก็บ secret และ fallback เป็น Rules/Manual review ได้

Default AI policy ส่งเฉพาะ Metadata ที่อนุญาต การส่ง Sample ออกนอกองค์กรต้องมีนโยบายที่ยืนยันก่อน มีการ Mask/Redact และสามารถปิด AI ทั้งหมดได้ ข้อความในชื่อ Column หรือข้อมูล Source ถือเป็นข้อมูล ห้ามนำไปเป็นคำสั่งระบบ

Mapping states: suggested → in_review → approved / rejected / excluded; approved → stale เมื่อ Source หรือกฎเปลี่ยน การแก้ approved สร้าง revision ใหม่ Run เดิมยังอ้างอิง revision เก่า

## 7. Metadata Schema — Logical Design

ใช้ surrogate IDs, UTC timestamps และ audit fields ทุก Entity ที่มีการเปลี่ยน ไม่เก็บ Password ในตารางเหล่านี้ ตารางต่อไปนี้เป็นแบบ Logical; Codex ต้องสร้าง migrations หลังเลือก SQL engine จริง

| Entity | Fields สำคัญ / Constraints |
|---|---|
| source_registry | source_id, name, engine, endpoint, database, site_code, auth_type, remember_username, credential_scope, secret_ref, config_revision, status; unique name ใน Workspace |
| target_registry | target_id, engine, endpoint, database, auth_type, secret_ref, config_revision, environment |
| discovery_snapshot | snapshot_id, source_id, scope, started_at, completed_at, schema_fingerprint, status |
| table_profile | table_id, snapshot_id, schema_name, table_name, object_type, row_estimate, key_metadata |
| column_profile | profile_id, table_id, column_name, ordinal, source_type, nullable, null_rate, distinct_estimate, sample_count, pattern_summary |
| canonical_field | field_id, domain, canonical_name, description, logical_type, unit, timezone_policy, dictionary_version |
| table_mapping | mapping_id, source_table, target_entity, grain, key_spec, filter_spec, version, status |
| column_mapping | mapping_id, source_column, canonical_field_id, transform_spec, score, evidence_ref, revision, status, approved_by/at |
| relationship_mapping | relationship_id, left/right_entity, composite_key_spec, cardinality, evidence, revision, status |
| mapping_bundle | bundle_id, dictionary_version, table/column/relationship revision references, published_at |
| etl_job | job_id, target_id, selected_table_mappings, mode, incremental_spec, quality_policy |
| etl_run | run_id, job_id, mapping_bundle_id, state, request_id, started/ended_at, counts, error_summary |
| etl_run_table | run_table_id, run_id, table_mapping_id, batch_cursor, checkpoint, lower/upper_boundary, snapshot_semantics, strategy_version, counts, state |
| incremental_state | job_id + table_mapping_id + target_id unique, source_scope_ref, target_generation, strategy_version, committed_watermark, tie_breaker, committed_run_id |
| quality_rule/result | rule_id, version, scope, severity, condition; run_id, evaluated/passed/failed counts |
| quarantine_record | run_id, source_row_ref, rule_id, sanitized_payload_ref, resolution_status |
| lineage_record | run_id, source_id, source_table, source_record_key, target_entity, target_key |
| audit_event | actor, action, entity, revision, timestamp, sanitized diff |

เก็บ Profile history ผูกกับ Snapshot ไม่เขียนทับ Evidence เดิม Unique mapping ต้องรวม source/schema/table/column และ revision เพื่อแยกชื่อซ้ำข้ามระบบ

## 8. Canonical Manufacturing Model

การเปลี่ยนชื่อให้เป็น lot_id เหมือนกันไม่ได้พิสูจน์ว่าเป็น Lot เดียวกัน และไม่ควร Join facts โดยตรงเพียงเพราะชื่อ Key ตรงกัน

| Target entity | Grain / Key |
|---|---|
| dim_lot | หนึ่งแถวต่อ Lot ที่ผ่านการระบุตัวตน; lot_key เป็น surrogate key |
| lot_identity_crosswalk | หนึ่งแถวต่อ Source/site/business lot identifier → lot_key |
| dim_equipment | หนึ่งแถวต่อ Equipment ภายใน site; equipment_key |
| dim_process | หนึ่งแถวต่อ Process definition/version ภายใน site; process_key |
| fact_process | หนึ่งแถวต่อ Source process event; event_key และ lot/equipment/process keys |
| fact_inspection | หนึ่งแถวต่อ Inspection event; ระบุจุดตรวจและเวลา |
| fact_defect | หนึ่งแถวต่อ Defect occurrence หรือ summary ตาม Grain ที่ยืนยัน |
| fact_measurement | หนึ่งแถวต่อค่าที่วัดพร้อม unit, characteristic, spec version |
| fact_test | หนึ่งแถวต่อ Test event/attempt ตามนิยามที่ยืนยัน |
| lot_genealogy | parent_lot_key, child_lot_key, split/merge event และเวลามีผล |

MVP implement เฉพาะ dim_lot, crosswalk, dim_equipment, dim_process และ fact_process ตารางอื่นเป็น roadmap

Business lot identifier เก็บเป็น String รักษา Leading zero และ Original value ห้ามสมมติให้ lot_id unique ทั้งองค์กร การรวม Lot ข้าม Source ต้องมี crosswalk/กฎที่อนุมัติ หากยังพิสูจน์ไม่ได้ให้แยก Identity ไว้

ต้องระบุ timezone ของ Source ก่อนแปลง timestamp เป็น UTC, ระบุหน่วยวัดก่อนรวม และเก็บ Original value ที่ตรวจย้อนกลับได้ ห้าม deduplicate จาก lot_id เพียงอย่างเดียว เพราะ Lot เดียวมีหลาย Event, rework และ retest ได้

Mart Yield ต้องยืนยัน denominator, good/reject definition, rework/retest policy และ Grain กับ Business owner ก่อน สูตรจาก Sample ไม่ถือเป็น Production KPI

## 9. ETL Contract และความถูกต้อง

### Pre-check

ตรวจ Connection ใหม่, Target permissions, Scope, required fields, table grain, approved bundle, type/units/timezone, relationship keys, extraction strategy, schema drift, concurrency lock และพื้นที่/ข้อจำกัดที่กำหนด

Column ที่ไม่จำเป็น Exclude ได้พร้อมเหตุผล Required fields ที่ไม่มี Mapping, ambiguous identity หรือ incompatible type เป็น Blocker ห้ามแทนค่าเองเพื่อทำให้ Run ผ่าน

### Extraction

อ่านแบบ Batch มี limit/timeout และเลือก PK pagination เมื่อใช้ได้ Profiling ไม่ scan ทุกแถวโดย default เก็บ Snapshot policy ของ Source หากต้องการผลที่สอดคล้องกันข้าม Table ต้องกำหนด consistency strategy ร่วมกับ DBA

### Initial/Incremental

- Initial load ลงพื้นที่ Run แยก แล้ว Publish เมื่อผ่านกฎ
- Incremental ใช้ extraction strategy ที่ผ่านการตรวจพฤติกรรม Commit ของ Source จริง; monotonic key หรือ updated_at + stable tie-breaker ใช้ได้เมื่อพิสูจน์เงื่อนไขความครบถ้วนแล้ว ไม่ใช้ MAX(ID) เป็นหลักฐานว่าทุกแถวก่อนหน้านั้น Commit แล้ว
- Watermark ขยับเมื่อ Publish สำเร็จเท่านั้น และต้องอยู่ใน atomic commit เดียวกันหรือมี recovery protocol ที่พิสูจน์ได้
- Late updates ใช้ overlap window + upsert เมื่อมี timestamp ที่เชื่อถือได้
- หากไม่มี timestamp/CDC ที่จับการเปลี่ยนได้ ต้องแจ้งว่าไม่รองรับ Incremental updates ไม่สมมติว่าข้อมูลใหม่อย่างเดียว
- Hard delete ไม่ถูกตรวจด้วย updated_at; MVP ต้องระบุ limitation หรือมี reconciliation policy

### ข้อมูลใหม่ที่ Insert ต่อเนื่องและขอบเขตแต่ละ Run

Source ยังรับ Insert ได้ระหว่าง ETL แต่แต่ละ Run ต้องมีขอบเขตที่แน่นอนและอ่านแบบมีจุดสิ้นสุด ไม่ไล่ตามข้อมูลใหม่จน Run ไม่จบ เก็บ lower/upper boundary, snapshot/cursor semantics และ strategy version ต่อ Table/Run ข้อมูลที่อยู่นอกขอบเขตจะโหลดรอบถัดไปตาม strategy ที่ยืนยัน

การกำหนด ID หรือเวลา Upper bound อย่างเดียวไม่ได้ทำให้ปลอดภัยจาก Transaction ที่ Commit ช้า เช่น ID 101 ยังไม่ Commit แต่ ID 102 Commit และถูกโหลดไปแล้ว หากเลื่อน watermark เป็น 102 ทันที รอบต่อไปอาจข้าม 101 ต้องทดสอบกรณีนี้ก่อนอนุมัติ strategy รวมถึงช่วงเปลี่ยนจาก Initial เป็น Incremental

Phase 0/Connector spike ต้องระบุวิธีที่ใช้ได้จริงโดยไม่แก้ Source เอง เช่น commit-aware change tracking ที่ Source มีอยู่และ DBA อนุมัติ หรือ reconciliation/การอ่านเทียบซ้ำที่ครอบคลุมข้อมูลที่มาช้า หาก Source รับประกันว่า Commit เรียงตาม Key ต้องมีหลักฐานก่อนใช้ key watermark

Overlap window ช่วยเมื่อมีขอบเขต late commit/update ที่เชื่อถือได้ แต่ไม่รับประกันจับ Transaction ที่ช้าได้ไม่จำกัด เมื่อไม่มีความรับประกันหรือ tracking ที่เหมาะสม ให้ใช้ reconciliation/full comparison ที่ทำได้ภายใต้ query budget หรือแสดงว่า Incremental ยังไม่พร้อม ห้ามอ้างว่าไม่มีข้อมูลตกหล่นด้วย delay ที่ตั้งขึ้นเอง

Initial load ต้องกำหนด consistent snapshot/cutoff และแผนรับการเปลี่ยนแปลงระหว่าง Initial กับรอบถัดไป หาก CDC ยังไม่ได้ implement ห้ามอ้างว่า initial-to-incremental handoff รองรับทุก Source

### Checkpoint, Retry และการเปลี่ยน Mapping

- แยก in-flight batch checkpoint ออกจาก committed watermark; checkpoint ใช้ Resume งานเดิม ไม่เป็นหลักฐานว่า Target Publish สำเร็จ
- Commit ข้อมูล Target และ watermark ด้วย atomic boundary เดียวกันตาม Table/Dataset policy หรือ recovery protocol ที่ทดสอบ หากล้มเหลวก่อน Publish watermark เดิมคงอยู่
- แถวที่ Quarantine ต้องมี durable reference/payload และเส้นทาง reprocess ก่อนเลื่อนผ่านแถวนั้น หรือ Block scope ตาม policy ห้ามทำให้แถวหายถาวรเมื่อโหลดรอบถัดไป
- Run ซ้ำใช้ stable event/upsert key ของ Source ที่อนุมัติ การอ่านช่วงซ้ำไม่เพิ่ม Event ซ้ำ และต้องพิสูจน์ผลทั้งกรณี crash ก่อน/หลัง Commit
- ขอบเขต state รวม stable Source/table mapping, Job, Target และ Target dataset generation; Full refresh ที่สำเร็จสร้าง baseline/generation ใหม่ ส่วน Full refresh ที่ fail ไม่ทำลาย baseline เดิม
- Mapping/Transform เปลี่ยนต้องประเมินผลต่อข้อมูลเก่า หากต้อง Backfill ให้สร้างงานแยกพร้อมขอบเขต ห้ามใช้ Incremental ใหม่แล้วอ้างว่าประวัติทั้งหมดถูกแปลงตาม Mapping ใหม่แล้ว

### วิธีใช้งานและการตั้งเวลาในอนาคต

MVP: เลือก Connection → เลือก Scope/Incremental → Pre-check → Transform & Load → ตรวจ Run History/Quality ใช้ approved bundle เดิมเมื่อไม่เปลี่ยน ไม่มีการเรียก AI ใหม่ทุกครั้ง

ระยะถัดไป: Scheduler เรียก workflow เดียวกันตามเวลา เช่น ทุก 5 นาที/ทุกชั่วโมง โดยต้องมี Worker ที่เปิดทำงานและ Credentials ที่อนุญาตสำหรับ unattended runs กำหนด timezone, pause/resume, retry policy และ missed-run policy ป้องกัน Run ทับซ้อนด้วย scope lock; ถ้า Run เดิมยังไม่จบให้ coalesce/skip ตามนโยบายที่ระบุ ไม่สร้าง backlog ไม่จำกัด เมื่อ Credentials หมดอายุหรือ Mapping stale ให้ Block และแจ้งสถานะ ไม่รันต่อเงียบ ๆ

การเพิ่ม Scheduler/CDC เป็นงานระยะถัดไปที่ต้องยืนยัน scope และ estimate ไม่เพิ่มเข้า MVP โดยอัตโนมัติจากการอัปเดตนี้

### Idempotency และ Recovery

กำหนด unique source event identity และ upsert key ที่อนุมัติ Request ซ้ำต้องไม่สร้าง concurrent duplicate run Retry Batch/Run เดิมไม่ทำให้จำนวน Fact เพิ่มโดยไม่มีข้อมูลใหม่

Run states: queued, running, cancel_requested, cancelled, failed, succeeded, succeeded_with_warnings ต้องมีสถานะต่อ Table ด้วย ความสำเร็จของ Table เดียวไม่แปลว่าทั้ง Run สำเร็จ

MVP เลือก Atomic publish ต่อ Table และแสดง Partial failure ชัดเจน หาก Dataset ต้องสอดคล้องกันทั้งชุด ให้ Publish ด้วย Dataset version/pointer หลังทุก Table ผ่าน ห้ามปล่อย UI อ้างว่า Global atomic เมื่อทำได้เพียงต่อ Table

### Quality และ Reconciliation

ตรวจ required key, cast failures, duplicates ตาม Event key, referential integrity, timestamps, unit/spec และ source-to-target reconciliation

ทุก Extracted row ต้องอธิบายได้ว่า published, quarantined, filtered หรือ duplicate/superseded โดยแยกจำนวน Insert/Update/Unchanged ใน Target ไม่ใช้สูตร Source rows = Target rows กับ incremental upsert ตรง ๆ

Quality severity: Blocker ห้าม Publish ชุดที่ได้รับผล, Warning Publish ได้ตาม policy พร้อมสถานะ warnings, Info บันทึกเพื่อดูย้อนหลัง Quarantine เก็บตามสิทธิ์และ retention; UI/Logs ไม่แสดงข้อมูลอ่อนไหวโดยไม่มีสิทธิ์

## 10. API และ Repository Guidelines

API กลุ่มที่ต้องมี: dataset-requests, candidate-evaluations, field-reviews, dataset-definitions/approvals, sources, targets, discovery-jobs, profiles, dictionary, mappings, relationships, mapping-bundles, etl-jobs, runs, quality-results, explorer และ audit

Long-running endpoints คืน Job/Run ID ให้ UI poll หรือ subscribe ห้ามรอ ETL จบใน HTTP request เดียว ทุก Mutation ตรวจ Auth และ revision conflict ฝั่ง Backend

Repository ที่เสนอ:

```text
docs/                  Blueprint, decisions, UI specification, UAT
frontend/              React UI
backend/               API, domain, connectors, mapping, ETL, quality
migrations/            Metadata และ Target migrations
tests/                 Unit และ Integration tests ที่พิสูจน์ Contract
fixtures/              Synthetic data เท่านั้น
scripts/               Local setup และ test database utilities
.env.example           Placeholder ไม่มี Secret
README.md              Setup, run, test และข้อจำกัด
```

ใช้ Parameterized SQL สำหรับค่า และ validate/quote Identifier จาก Allowlist Connector ห้าม execute SQL ที่ AI สร้างโดยตรง Transform rules ต้องเป็น typed/allowlisted operations ไม่เปิด arbitrary eval

## 11. แผนพัฒนาและจุดตรวจรับ

ระยะเวลาเป็นกรอบวางแผนสำหรับ Developer 1 คนที่ทำงานเต็มเวลา มี Data owner/DBA ช่วย ไม่ใช่ Commitment และต้องปรับหลัง Spike/Pilot หากทำเฉพาะบางเวลาระยะปฏิทินจะยาวขึ้น

| Phase | งาน | Deliverable / Exit criteria | ประมาณ |
|---|---|---|---|
| 0 — Confirm & Spike | ยืนยัน Source/Target, sample, rights, volumes, driver | Decision log + เชื่อม Test DB แบบ read-only ได้ | 3–5 วัน |
| 1 — UI Prototype | ทุกหน้าพร้อม synthetic data, wizard, review, failure states | ผู้ใช้เดิน First run/Repeat run/Failure flow ครบ | 5–8 วัน |
| 2 — Foundation | Auth, registry, API, worker, migrations, secret handling | เก็บ Connection และเรียก Background job ได้; restart แล้วยังติดตามได้ | 5–8 วัน |
| 3 — Discovery & Mapping | Profiles, dictionary, evidence, review, drift | ตรวจ Mapping ของ Pilot tables และบันทึก version ได้ | 8–12 วัน |
| 4 — ETL MVP | Staging/Core, keys, initial/incremental, preview, retry | End-to-end 2 Sources → Core; rerun ไม่ซ้ำ | 10–15 วัน |
| 5 — Quality & Explorer | Rules, quarantine, lineage, history | ตรวจตัวเลขย้อนถึง Source และ Failure recovery ได้ | 5–8 วัน |
| 6 — Pilot & Release | UAT, benchmark, packaging, guide, backup/restore | ผ่าน UAT กับข้อมูลที่อนุญาตและมี Operational guide | 5–8 วัน |

รวมกรอบเริ่มต้น 41–64 วันทำงาน ไม่รวม Oracle/CDC, Mart ทุก Domain, Enterprise SSO หรือช่วงรอสิทธิ์และข้อมูลจริง หลัง Phase 0 ให้ทบทวน Estimate; หลัง Phase 4 จะมีโปรแกรมรุ่นแรกที่ทำงานหลักครบ

Dependency: Phase 0 → 1/2 → 3 → 4 → 5 → 6 Prototype ใช้ Fixture ได้ แต่การเชื่อมจริงต้องผ่านการตรวจสิทธิ์/ระบบใน Phase 0

### Pilot dataset

เลือก 2 Source, ประมาณ 5–10 Tables ที่มี Lot/Equipment/Process รวมกรณีชื่อ Column ต่างกัน, Lot ซ้ำข้าม Site, Leading zero, null, duplicate event, late update, rework, invalid timestamp และ schema drift สร้าง Gold mapping ที่ Data owner ยืนยันเพื่อประเมินคำแนะนำ

## 12. Acceptance & UAT Checklist

| ID | Scenario | ผลที่ต้องได้ |
|---|---|---|
| U01 | First run | Connect → Analyze → Approve → Preview → Load → Explore ครบ |
| U02 | Wrong credential | แจ้ง error ที่แก้ได้โดยไม่แสดง Password/connection string |
| U03 | Ambiguous BATCH_NO | มี Evidence และ alternatives; ยังไม่ Publish โดยอัตโนมัติ |
| U04 | Lot ID เท่ากันต่าง Site | ไม่รวมกันจนกว่า identity rule ได้รับอนุมัติ |
| U05 | Leading zero | 000123 ยังเป็น 000123 หลัง Load |
| U06 | Rerun ข้อมูลเดิม | ไม่มี duplicate facts; counts อธิบาย Unchanged ได้ |
| U07 | Late update | แก้แถวเดิมตาม strategy ไม่สร้าง Event ซ้ำ |
| U08 | Worker crash ก่อน Publish | ไม่มี watermark ขยับ; recovery ทำงานซ้ำได้อย่างถูกต้อง |
| U09 | Close UI | Worker ทำต่อ และกลับมาดู Run เดิมได้ |
| U10 | Schema drift | Mapping ที่ได้รับผลเป็น stale และ Run ที่เกี่ยวข้องถูก Block |
| U11 | Invalid required key | Row ถูก quarantine หรือชุดถูก Block ตาม policy; ไม่หายเงียบ |
| U12 | Relationships many-to-many | แสดง cardinality จริงและไม่ Join facts จนตัวเลขคูณ |
| U13 | Cancel | หยุดที่ safe boundary และรายงาน Partial state |
| U14 | Mapping revision | Run history ใช้เวอร์ชันที่รันจริง ไม่แสดงแต่ค่า Mapping ล่าสุด |
| U15 | Source protection | บัญชี read-only; source schema/data ไม่ถูกเปลี่ยน |
| U16 | Permission | Viewer ไม่แก้ Mapping/Connection หรือ Start job ผ่าน API ได้ |
| U17 | AI unavailable | Review/manual mapping และ ETL ด้วย approved bundle ยังใช้งานได้ |
| U18 | Quality warning | UI แสดง succeeded_with_warnings พร้อม records/counts |
| U19 | เปิดโปรแกรมครั้งแรก | มี Connection Setup และ Add Source/Target โดยไม่ต้องมี Target อยู่แล้ว |
| U20 | Saved connection | เลือก Connection เดิมได้ แต่ตรวจใหม่ก่อนแสดง connected |
| U21 | Username/Password | SQL Authentication ต้องกรอกค่าที่จำเป็น; error ไม่เผย Credentials |
| U22 | ไม่ Save Password | Run ทำต่อเมื่อปิด UI; restart Worker แล้วขอ Password ใหม่ก่อน Resume |
| U23 | Save Password | ผ่าน Secret store ที่เลือก; UI/Logs/Config ไม่คืน plaintext |
| U24 | Windows Integrated | ตรวจด้วย identity ของ Runtime จริง; ถ้าไม่รองรับปิดตัวเลือกพร้อมเหตุผล |
| U25 | เปลี่ยน Source/Target | Preview/Pre-check หมดอายุ; Mapping/checkpoint ไม่ถูกใช้กับระบบผิดตัว |
| U26 | แก้ Connection ระหว่าง Run | Run เดิมใช้ config snapshot; revision ใหม่ใช้กับ Run ถัดไป |
| U27 | Secret store ใช้งานไม่ได้ | ปิด Save Password; ยังกรอกแบบไม่บันทึกเพื่อ Connect ได้ |
| U28 | Disconnect ระหว่าง Run | ไม่ยกเลิก Run เงียบ ๆ; Cancel เป็น action แยก |
| U29 | Target ยังไม่มี schemas | Preview/apply migrations ด้วยสิทธิ์ที่ถูกต้อง; ไม่ Drop Database |
| U30 | ชื่อผลิตภัณฑ์ | หน้า UI/README/Prompt ใช้ U-ETL Factory Data Bridge; Repository UTL_ETL |

| U31 | Insert ระหว่าง Run | Run มีขอบเขตและจบได้; แถวนอกขอบเขตเข้ารอบถัดไปโดยไม่ตกหล่นตาม strategy |
| U32 | ไม่มีข้อมูลใหม่ | Run สำเร็จพร้อม No new data; ไม่มี Target row เพิ่มและไม่ขยับ watermark โดยไม่มีหลักฐาน |
| U33 | ID ต่ำกว่า Commit ช้า | โหลด ID 102 ก่อน 101 ได้ แต่เมื่อ 101 Commit ต้องถูกเก็บในภายหลัง; strategy ที่พิสูจน์ไม่ได้ถูก Block |
| U34 | Timestamp ซ้ำ | Stable tie-breaker/pagination ไม่ข้ามแถวเมื่อหลายแถวมีเวลาเดียวกัน |
| U35 | Initial-to-incremental handoff | Insert/Commit ระหว่าง Initial และรอบถัดไปไม่หายตาม consistency strategy ที่ตรวจรับ |
| U36 | Crash ก่อน/หลัง Commit | Target กับ committed watermark สอดคล้องกัน; Retry/Resume ไม่สร้าง Event ซ้ำ |
| U37 | Quarantine และ watermark | แถวไม่ผ่านกฎยัง reprocess ได้ หรือ scope ถูก Block; ไม่หายจากรอบต่อไป |
| U38 | Mapping revision ใหม่ | แจ้งความจำเป็นของ Backfill; Run ใหม่ไม่เปลี่ยนความหมาย Run history/ข้อมูลเก่าเงียบ ๆ |
| U39 | UI ตัวเลขและเวลา | Last sync/attempt, cutoff และ Insert/Update/Unchanged ตรงกับผลจริง/fixture; ไม่ใช้ Last sync รับรอง freshness |
| U40 | Scope ที่ไม่รองรับ Incremental | แสดงเหตุผลและไม่ fallback Full refresh เงียบ ๆ |
| U41 | Run พร้อมกัน/Full refresh | Lock ป้องกัน scope ทับซ้อน; refresh fail ไม่ทำลาย baseline/checkpoint ที่ใช้ได้ |
| U42 | Dataset-first start | เปิด Overview แล้วเริ่มด้วย Dataset name/purpose/business fields ก่อนเลือก schema/table; เก้าเมนูเดิมยังอยู่ |
| U43 | Business ambiguity | `Product code`/`Production code`, `input/output quantity` และ grain ที่ไม่ชัด แสดงเป็นคำถาม ไม่ merge/เลือกเงียบ ๆ |
| U44 | Candidate evidence | แต่ละ candidate แสดง Source/schema/table/column/type, uncalibrated Matching Score และเหตุผล/alternatives/ambiguity; datatype compatibility และ join confidence แยกกัน |
| U45 | Rule baseline labeling | Exact/alias/token matching แสดงว่า deterministic baseline ไม่ใช่ AI หรือ calibrated probability; ไม่มี AI call |
| U46 | Missing candidate | แสดง No suitable match พร้อมเหตุผล; ห้าม map ไป field เดาเพื่อให้ Definition ผ่าน |
| U47 | Review actions | Approve/Override/Reject/No suitable match ทำงานตาม permission; Override/Reject/no-match ต้องมีเหตุผล; ambiguous top candidate ห้าม direct approve |
| U48 | Revision invalidation | เปลี่ยน Dataset request, Source config/discovery snapshot, Dictionary/provider revision ทำให้ candidates/reviews/definition เดิม stale และต้องทบทวนใหม่ |
| U49 | Definition gate | Required field ยังไม่ reviewed, No suitable match/Rejected, unresolved ambiguity, grain/join blocker หรือ stale revision ทำให้ Dataset Definition ไม่พร้อม Approve/Publish |
| U50 | Metadata/fixture boundary | Real Source candidate ใช้ metadata ของ discovery snapshot เท่านั้น; Sample ไม่เป็น evidence โดย default; Demo synthetic schema/records แยกชัดและไม่แทน real metadata |
| U51 | Definition durability | Prototype approval เป็น session-only ไม่ใช่ durable approval/bundle; Backend persistence/audit ต้องผ่าน Phase 2+ acceptance ก่อนใช้จริง |
| U52 | Training claims | Reuse approved mapping แยกจาก model training; accuracy/training claims ต้องผ่าน versioned gold/holdout/leakage evaluation |

Performance acceptance กำหนดหลัง Phase 0 โดยใช้ Volume, extraction budget และ Test environment จริง ห้ามรับรอง 1.8 ล้านแถว/18 นาทีจากตัวเลข Mockup

## 13. ความเสี่ยงและรายการที่ต้องยืนยัน

| ประเด็น | แนวทาง / ผู้ช่วยยืนยัน |
|---|---|
| Source engine/version, authentication, network | DBA/IT ยืนยันก่อน Connector spike |
| Target SQL Server และ License/Provisioning | IT ยืนยัน; เปลี่ยน Target ผ่าน decision log ได้ |
| Lot/Batch/Job semantics และ cross-site identity | Data owner ยืนยันพร้อมตัวอย่าง |
| Grain, Key, delete และ late update | Data owner + DBA |
| Data volume, retention, source query budget | DBA ช่วยตั้งขอบเขตและ Benchmark |
| External AI policy | เจ้าของข้อมูล/IT ยืนยัน; Default ปิดส่ง Sample |
| Desktop Installer vs internal server | ทดสอบแบบ local web ก่อน แล้วเลือก deployment |
| KPI และ Quality threshold | Business owner อนุมัติก่อนสร้าง Mart |

สิ่งเหล่านี้ไม่ขวางการทำ Prototype ด้วยข้อมูลจำลอง แต่ขวางการอ้างว่าพร้อม Production

## 14. วิธีนำไปเริ่มโปรเจกต์บน Codex

1. สร้างโฟลเดอร์/Repository ชื่อ UTL_ETL
2. วางเอกสารนี้ที่ docs/U-ETL Factory Data Bridge_Blueprint.md
3. เปิดโฟลเดอร์ด้วย Codex และส่ง Prompt ด้านล่าง
4. ทบทวน Prototype และ Decision log ก่อนเริ่ม Connector จริง
5. ทำทีละ Milestone โดย Codex รายงานผลตรวจรับและข้อจำกัดท้ายแต่ละช่วง

### Prompt เริ่มต้น — คัดลอกใช้ได้

```text
เริ่มโปรเจกต์ U-ETL Factory Data Bridge (Repository: UTL_ETL) โดยอ่าน
docs/U-ETL Factory Data Bridge_Blueprint.md ให้ครบก่อนลงมือ

เป้าหมายปลายทางคือ Application เดียวสำหรับเชื่อมหลาย Source Database,
Discover/Profile, เสนอและ Review Mapping/Relationships, Transform & Load
เข้า Analytics Database และตรวจ Data Quality/Lineage ภายในโปรแกรมเดียว

รอบนี้ทำ Phase 0 ส่วนที่ทำได้โดยไม่มีฐานข้อมูลจริง และ Phase 1 UI Prototype:
1. ตรวจ Repository และคำสั่ง AGENTS.md ที่มีอยู่ก่อน ไม่เขียนทับงานเดิม
2. สร้าง README, docs/decision-log.md และ docs/backlog.md จาก Blueprint
   แยก confirmed requirements, proposed decisions และ open questions
3. สร้าง UI Prototype ที่คลิกใช้งานได้ครบ 9 เมนูตาม UI specification
   ใช้ synthetic manufacturing fixtures เท่านั้น แสดง Demo mode ชัดเจน
4. ทำหน้า Connection Setup ตอนเปิดโปรแกรม เลือก/เพิ่ม Source หลายตัวและ Target หนึ่งตัว
   มี Server, Database, Authentication, Username/Password, Remember options,
   Test/Connect/Disconnect และ mock credential states ตาม Blueprint
   ทำ First-run wizard, Mapping review drawer, Relationship graph/list,
   Transform pre-check, simulated progress, Quality และ Run History
5. ทำ Flow: first run, repeat run, ambiguous mapping, schema drift,
   connection error, credentials_required, เปลี่ยน Source/Target, partial failure และ retry ให้ตรวจได้
6. ใช้ state/data model ร่วมกันระหว่างหน้าจอ ตัวเลข/status ต้องสอดคล้องกัน
   การอนุมัติ Mapping ต้องเปลี่ยน readiness และการแก้ต้อง invalidate preview
7. ออกแบบ interface สำหรับ API/Connector/Worker ภายหลัง
   ยังไม่สร้าง Connector จริง ไม่เรียก AI ไม่เชื่อมฐานข้อมูลจริง
8. เก็บ dependency versions ที่เลือกไว้ใน lockfile และบอกวิธีรันใน README
9. เพิ่ม UI Load Mode/Last sync/counts และจำลอง Initial, Incremental, No new data,
   Insert ระหว่าง Run, Commit ช้า และ Retry ตาม v1.2; ไม่เปิด Scheduler/CDC จริง
   ตรวจ build และทดสอบ critical UI flows ที่จำเป็น
10. สรุปไฟล์ที่เปลี่ยน วิธีเปิด Prototype ผลตรวจ และ open decisions

ข้อกำหนด: UI อ่านง่าย รองรับไทย/อังกฤษ, Navy/Blue theme,
ทุกสถานะมีข้อความร่วมกับสี, mock progress ไม่อ้างว่าเป็น ETL จริง,
ห้ามใช้ข้อมูลจริง/Secrets ใน fixture หรือ Git และไม่ deploy Production

ดำเนินงานที่ทำได้ให้ครบโดยใช้ข้อเสนอใน Blueprint เป็นค่าเริ่มต้น
หากเจอการตัดสินใจที่ต้องใช้ข้อมูลจริง ให้บันทึก open question และทำ
Prototype ส่วนอื่นต่อ ห้ามอ้างว่าระบบพร้อม Production จาก Prototype
```

### Prompt สำหรับ Milestone ถัดไป

```text
อ่าน Blueprint, decision-log และ backlog ล่าสุด แล้วทำเฉพาะ Milestone
[ใส่ชื่อ Phase] ที่ dependency พร้อมแล้ว รักษา UI contract ที่ตรวจรับไว้
ก่อนเริ่มระบุ acceptance criteria จากเอกสารและข้อที่ยังขาดข้อมูล
Implement พร้อม meaningful tests ตาม risk ของงาน โดยเฉพาะ idempotency,
mapping revision, watermark commit, source read-only และ failure recovery
ใช้ Test environment เท่านั้นและไม่เก็บ Credentials ใน Repository
เมื่อจบรายงานสิ่งที่ทำ ผลทดสอบ วิธีตรวจรับ และข้อจำกัดจริง
```

### Prompt v1.2 เมื่ออัปเดต Blueprint — historical; replaced by v1.3 above

```text
Blueprint รุ่น v1.2 (เก็บเป็นประวัติในเนื้อหาเอกสาร) อ่านไฟล์ล่าสุด:
"docs/U-ETL Factory Data Bridge_Blueprint.md"

เทียบกับ implementation, decision-log และ backlog ที่มีอยู่
หากไม่มีเอกสารเวอร์ชันเก่า อย่าเดาส่วนต่าง ให้ทำ requirement-to-implementation gap review
บันทึก Blueprint version และสรุปผลกระทบ/Acceptance criteria
รักษางานเดิมและแก้เฉพาะส่วนที่ได้รับผลกระทบ ไม่สร้างโปรเจกต์ใหม่

รอบนี้ยังทำ UI Prototype ใช้ข้อมูลจำลอง:
- Initial/Incremental/Full Refresh readiness และข้อความ Unsupported incremental
- Last successful sync/Last attempt และ counts ที่สอดคล้องกันทุกหน้า
- กรณีมีแถวใหม่, No new data, Insert ระหว่าง Run, Commit ช้า, Failure/Retry
- แสดง Demo ชัดเจน และไม่อ้างว่า simulation พิสูจน์ Backend extraction แล้ว

อัปเดต backlog Backend ให้ครอบคลุม run boundaries, late commit,
initial handoff, checkpoint/watermark, quarantine reprocess และ backfill
Scheduler/CDC ยังคงเป็นระยะถัดไป ไม่เชื่อม DB จริง ไม่เรียก AI ไม่ Deploy
ตรวจ flows ที่เกี่ยวข้องและรายงานสิ่งที่แก้ ผลตรวจ และข้อจำกัด
```

## 15. Definition of Done

Prototype complete: ทุกหน้ามี state สอดคล้องกัน เดิน user flows ได้ และแสดงชัดว่าเป็น Demo

MVP complete: เชื่อม Test Source จริง 2 แหล่ง, Mapping ที่ตรวจแล้ว, Load ลง Core จริง, rerun/recovery ถูกต้อง, Quality/Lineage/History ตรวจได้ และผ่าน UAT ที่เกี่ยวข้อง

Production ready: Pilot ผ่าน, สิทธิ์และ Secrets ตรวจแล้ว, performance/retention ชัด, backup/restore และ recovery ทดสอบ, มีคู่มือปฏิบัติการและผู้รับผิดชอบ พร้อม release plan แยกจากการทำ Prototype

หลักการสุดท้าย: User workflow เรียบง่าย แต่ความถูกต้องของข้อมูลต้องตรวจสอบและอธิบายได้เสมอ

## 16. Revision Notes และแนวทางใช้เอกสาร

Version 1.3 (9 ตุลาคม 2026): ปรับ Product workflow เป็น Dataset-first โดยเริ่มจาก business purpose/fields; เพิ่ม Dataset Request/Definition, grain, Candidate evidence/ranking/review/ambiguity, missing candidates, field/type/join score separation, Dictionary governance, feedback/evaluation และ AI provider boundary; ระบุ current implementation/evidence จริงกับ Demo/offline harness/owner-reported live evidence; รักษาเก้าเมนู, Data Prep IOT profile เดิม, connection security, Source read-only, incremental/watermark/retry/recovery contracts และ Scheduler/CDC roadmap; เพิ่ม acceptance U42–U52. No stack migration, AI call, real Target/ETL or Production deployment implied.

Version 1.2 (7 ตุลาคม 2026): เพิ่ม Continuous Insert/Run boundaries, late commit และ Initial handoff; UI Load Mode/Last sync/counts; quarantine recovery, target generation และ backfill; เพิ่ม UAT U31–U41 และ Prompt อัปเดตโปรเจกต์ โดยไม่ย้าย Scheduler/CDC เข้า MVP

Version 1.1: ยืนยันชื่อ Application เป็น U-ETL Factory Data Bridge, Repository UTL_ETL; เพิ่ม Startup Connection Setup, Authentication/Credential lifecycle, Target bootstrap, config revisions, Target-scoped watermark และ UAT U19–U30 พร้อมปรับ Prompt เริ่มต้น

ใช้ไฟล์นี้เป็น Blueprint หลักเพียงฉบับเดียวใน Repository ที่ docs/U-ETL Factory Data Bridge_Blueprint.md และบันทึกการตัดสินใจใน decision-log แทนการให้ Prompt ที่ขัดกัน แต่รายละเอียด v1.2 ที่ขัดแย้งกับ workflow/stack/evidence ใน v1.3 เป็นข้อความประวัติและไม่ใช่ข้อกำหนดปัจจุบัน รายละเอียดที่ยังต้องยืนยันได้แก่ Test Registry/Target engine/destination/rights, runtime identity, OS Secret store/Auth policy, source query budget/grants, grain/business meanings/gold mappings, AI provider/data policy และ Target transaction/recovery acceptance; Prototype/contract ไม่ใช่หลักฐานว่าปิด decisions เหล่านี้แล้ว
