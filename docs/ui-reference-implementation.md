# UI reference implementation — 15 October 2026

## Reference and inspection limit

The reference is present at `docs/ui-reference/U-ETL_DataBridge_UI_Reference.html` and the earlier `docs/U-ETL_DataBridge_UI_Reference.html`. The owner also supplied screenshots of the four primary screens; those screenshots were visually compared with the application. Direct Browser inspection of the HTML was not completed: the headless Chrome workflow was blocked by `spawn EPERM`. The HTML/srcdoc, embedded CSS and screen-rendering JavaScript were inspected as source.

The reference uses a 204px navy sidebar (`#122442` → `#09162c`), purple U-ETL logo, white UTAC masthead, pale blue-gray canvas, table-first connection/storage/dataset pages, compact forms and navy primary actions. Its four real work areas are Database Connection, U-ETL DataBridge, AI Data Bridge, and Data Set. The 16-option screen-picker is for mockup inspection only.

## Applied to the existing application

- Kept the existing application entry point, Dataset Wizard, connection state, and Oracle read-only APIs. The mockup was not copied over the application.
- Reworked the normal shell to show the reference's four work areas, a closer purple U-ETL wordmark, UTAC masthead, notice band, and navy workspace sidebar.
- Replaced the connection cards with the reference-style table/list. Added a U-ETL DataBridge storage/copy overview that reports metadata snapshots only; it never invents copied row counts, storage sizes, or schedule state. The Data Set screen uses the reference-style list table.
- Applied the compact reference table, form, card, focus, badge and stepper styling through `ui-reference-theme.css`.
- Did not add the mockup's `เปิดดูหน้าจอ` / screen-picker dropdown to the application.
- Mapped the existing four-step guarded Dataset workflow into AI Data Bridge: Request → Review plan → Preview → Publish (prototype only). Required inputs and mapping/grain/relationship approval gates remain in place. AI is not called and real Target publication remains unavailable.
- Kept Oracle read-only HTTPS credentials, API, allowlist, catalog discovery and bounded-read logic unchanged. No live query was made for this UI change.

## Acceptance / validation

- Normal navigation is exactly Database Connection, U-ETL DataBridge, AI Data Bridge, and Data Set; no extra screen-picker control.
- Required request inputs and unapproved/ambiguous plan blockers prevent moving forward; Back/Edit retains request values and rebuilding the plan invalidates old approval.
- U-ETL DataBridge clearly distinguishes session metadata from copied Source rows; no real row data is represented as stored.
- `npm test`: 16/16 passed; `npm run build`: passed with nine runtime files; JavaScript syntax checks passed.
- Browser regression test was attempted against `http://localhost:5173/`, but Chrome could not launch (`spawn EPERM`). The current screen has not had post-change browser visual verification. No Oracle Test, Discovery or Sample was run during this change.
