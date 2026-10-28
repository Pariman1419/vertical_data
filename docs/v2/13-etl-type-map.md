# ETL Type Mapping and Pipeline Contracts

Date: 2026-10-28
Phase: Phase 3 Task 4
Module: `backend/v2/etl.py`

## 1. Apache Arrow to PostgreSQL Type Matrix

The U-ETL engine reads source datasets via Apache Arrow Flight and stages them into PostgreSQL using bulk `COPY` operations. The mapping guarantees exact round-trips for critical industrial, SCADA, and accounting data types:

| Apache Arrow Type | PostgreSQL Staging / Published Type | Python In-Memory | Browser / API Contract | Notes |
|---|---|---|---|---|
| `boolean` | `boolean` | `bool` | `boolean` | Direct boolean mapping |
| `int8`, `int16` | `smallint` | `int` | `number` | Exact integer |
| `int32` | `integer` | `int` | `number` | Exact integer |
| `int64` | `bigint` | `int` | `number` or `string` | Safe up to $2^{53}-1$; $\ge 2^{53}$ serialized as string |
| `uint8` | `smallint` | `int` | `number` | Widened to smallint |
| `uint16` | `integer` | `int` | `number` | Widened to integer |
| `uint32` | `bigint` | `int` | `number` | Widened to bigint |
| `uint64` | `numeric(20, 0)` | `decimal.Decimal` / `int` | `string` | Unsigned 64-bit max ($18,446,744,073,709,551,615$) exceeds `bigint` max ($9,223,372,036,854,775,807$); `numeric(20, 0)` prevents overflow |
| `float16`, `float32` | `real` | `float` | `number` | IEEE 754 single precision |
| `float64` | `double precision` | `float` | `number` | IEEE 754 double precision |
| `decimal128(p, s)` | `numeric(p, s)` | `decimal.Decimal` | `string` | Preserves exact precision up to 38 digits |
| `decimal256(p, s)` | `numeric(p, s)` | `decimal.Decimal` | `string` | Arbitrary precision numeric |
| `timestamp(unit, tz)` | `timestamptz` | `datetime.datetime` (with tz) | `string` (ISO 8601) | Normalized UTC or offset |
| `timestamp(unit, null)`| `timestamp without time zone` | `datetime.datetime` | `string` (ISO 8601) | Wall-clock timestamp |
| `date32`, `date64` (valid) | `date` | `datetime.date` | `string` (YYYY-MM-DD) | Valid Gregorian dates (years 1..9999) |
| `date32`, `date64` (out-of-range) | `text` | `str` | `string` (ISO text) | E.g. `0000-01-01` from legacy SCADA; stored as exact text |
| `utf8`, `large_utf8` | `text` | `str` | `string` | Standard UTF-8 text |
| `binary`, `large_binary`| `bytea` | `bytes` | `string` (`0x...`) | Hex-encoded bytes |
| `null` (any type) | `NULL` | `None` | `null` | CSV unquoted empty string maps to `NULL` |

---

## 2. Special Type Invariants

### 2.1 Unsigned 64-bit Integers (`uint64`)
PostgreSQL does not provide a native unsigned 64-bit integer type. Storing `uint64` in `bigint` would wrap or fail on values greater than $2^{63}-1$. We map `uint64` directly to `numeric(20, 0)`, which losslessly accommodates all 64-bit unsigned integers up to $18,446,744,073,709,551,615$.

### 2.2 Arbitrary Precision Decimals (`Decimal128(38, 10)`)
Financial and high-precision SCADA readings must never be rounded or cast through floating point. `Decimal128` is mapped to `numeric(p, s)` in PostgreSQL and parsed into Python `decimal.Decimal`. Browser transport formats numbers with scale or precision beyond JS safe integers as exact decimal strings.

### 2.3 Out-of-Range Dates
Certain upstream legacy systems emit out-of-range dates (such as `0000-01-01` or year $< 1$ or $> 9999$). PostgreSQL's standard `date` type rejects `0000-01-01` with an out-of-range error. In accordance with the preview fix, date columns containing out-of-range values are mapped to `text`, preserving their exact ISO string representation without failing the pipeline.

### 2.4 NULL and Empty String Disambiguation
In PostgreSQL `COPY ... WITH (FORMAT csv, HEADER true, NULL '')`:
- Empty unquoted fields represent `NULL`.
- Quoted empty strings `""` represent the literal empty string `""`.
PyArrow's CSV writer naturally follows this convention, ensuring no loss of distinction between `NULL` and empty string values.

---

## 3. Resource Budgets

Every run enforces three strict default ceilings:
1. **Row Ceiling:** `max_rows = 5,000,000` (stops with `error_code = 'budget_rows'`).
2. **Byte Ceiling:** `max_bytes = 2,147,483,648` (2 GB staging ceiling, stops with `error_code = 'budget_bytes'`).
3. **Time Ceiling:** `max_seconds = 1800` (30 minutes, stops with `error_code = 'budget_seconds'`).

Flight readers cancel the active query immediately upon reaching any ceiling so the upstream SPICE instance terminates processing.

---

## 4. Fenced Execution and Atomic Generation Swap

1. **Fenced Writes:**
   All mutations to `uetl_staging`, `dataset_generation`, and `job_run` call:
   ```sql
   SELECT run_fence_check(run_id, fence);
   ```
   If a worker's lease has expired or been taken over by another worker, the database raises an exception with SQLSTATE `42501` (`stale run fence`), aborting the transaction before any data corruption can occur.

2. **Atomic Publish:**
   `publish_generation` moves the completed staging table into `uetl_published` via `ALTER TABLE ... SET SCHEMA`, creates or replaces the public view pointing to the new generation table, updates the pointer and generation metadata, and prunes generations older than the 3 newest all within a single database transaction. Readers never observe a partial or transient state.
