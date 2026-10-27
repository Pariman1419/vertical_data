# 09 — SPICE read-only probe results (D2)

Date: 2026-10-27. Target: `10.153.90.17` (HTTP `:8091`, Flight SQL `:50051`), supplied by the owner, who asked for the probe ("ลองดู"). Everything below was run from the dev machine, read-only. Label: **TESTED LIVE** unless stated.

## What was executed (complete list)
`GET /health`, `/v1/status`, `/v1/datasets`; `POST /v1/sql` with: `SELECT 1`, typed-literal SELECTs, `information_schema.tables LIMIT 5`, `DESCRIBE machine_map`, `count(*)` on `machine_map` (16,968 rows), `generate_series` of 100k and 2M rows (synthetic, no table), two deliberately invalid statements. Flight: `get_flight_info`/`do_get` with the same kinds of queries. **No INSERT/UPDATE/DELETE/DDL was attempted**, so "SPICE rejects writes" is NOT tested. No production table rows were read; only the row count and column list of `machine_map`.

## Verified capabilities
| Capability | Result | Evidence |
|---|---|---|
| HTTP liveness | VERIFIED | `GET /health` → 200 `ok` (40 ms) |
| Components | VERIFIED | `/v1/status`: http `:8090` Ready, flight `:50051` Ready, metrics Disabled |
| **Authentication** | **NONE** | `/health`, `/v1/datasets`, `/v1/sql`, Flight all answered without any credential |
| Datasets | VERIFIED: 24 | `/v1/datasets` → name + `from` (e.g. `postgres:"sixmonth"."YD_BWIP_LOT_OPERATE"`); none accelerated or replicated; static per pod, same for every caller |
| REST SQL, plain text body | VERIFIED | `Content-Type: text/plain`, body = SQL → JSON array of row objects |
| REST SQL, JSON body | VERIFIED | needs **both** `sql` and `parameters`; `parameters` as list (`$1`) **or** object (`$x`) both bind correctly |
| Bind parameters over Flight | **UNSUPPORTED** on the plain command path | `SELECT $1` → "Placeholder '$1' was not provided a value" |
| Catalog / metadata | VERIFIED | `information_schema.tables`, `DESCRIBE <dataset>` → Arrow type names (`Utf8`, `Timestamp(ns, "UTC")`), nullability |
| SQL dialect | Apache DataFusion (error text `Error during planning: table 'spice.public.x' not found`, `ParserError`) | decision D8: validate with a DataFusion-compatible parser |
| **REST streaming / row cap** | **NONE** | one response with `Content-Length`; 100k rows = 1.6 MB in 0.23 s; **2 M rows = 34.9 MB in 3.4 s with no server limit** |
| **Flight streaming** | **VERIFIED** | batches of 8,192 rows; 2 M rows in 245 batches / 1.4 s; first batch 29 ms; **stopping after 2 batches took 0.03 s** → bounded-memory read is demonstrated |
| Exact numerics, Flight | VERIFIED | `decimal128(38,10)` and `int64` returned as Arrow types |
| Exact numerics, REST | PARTIAL | decimals/BIGINT are sent as exact JSON number *text* (`123456789012345678.1234567890`, `9007199254740993`); a default JSON parser turns the decimal into a float and **loses digits** (`1.2345678901234568e+17`); parsing with `Decimal` keeps them |
| Error format | VERIFIED | plain text, HTTP 400, **leaks internal names** (`spice.public.<table>`, parser positions) |
| Latency | VERIFIED | simple queries 10–40 ms |

## Not verified (still UNKNOWN)
Product/version string; whether writes/DDL are rejected; server-side query cancel (client abort works, server effect unknown); query timeout or memory limit under load on the shared 5 GB host; per-source behaviour for large real tables (live federated read of Postgres/Oracle/SCADA); Flight prepared statements (Flight SQL protobuf path); TLS (both endpoints are plaintext); behaviour of `ORDER BY`/paging on large datasets.

## Consequences for the design (proposed; need owner OK)
1. **Worker and bounded preview use Flight** (`pyarrow.flight`, command descriptor with SQL text). This removes the "streaming UNKNOWN blocks Gate 3" risk: the worker can read batch-by-batch, enforce row/byte/time budgets and stop early.
2. **REST is used only for health, `/v1/datasets` and `information_schema`/`DESCRIBE`** — never for data extraction, because it has no streaming and no server-side cap. If REST must read data, the client must stream the body and abort at a byte limit.
3. **Binds:** Flight has none on this path, so U-ETL must not build SQL by string concatenation. Parameters come from typed values rendered by our own validated literal formatter (date/number/enum from a closed grammar) after AST validation; REST+JSON binds remain available for small catalog-style queries.
4. **Precision rule:** never pass numbers through JSON number parsing. Arrow `decimal128`/`int64` are carried as Decimal/int server-side and sent to the browser as **strings**.
5. **Error sanitising:** SPICE error text must never be forwarded to users; map to the error classes in 03 and log the raw text server-side only.
6. **No authentication on SPICE** — anyone on the LAN can query all 24 datasets, including the non-`_mock` production-backed ones. The U-ETL allowlist (decision D13) controls what U-ETL users can reach but is **not** a control on SPICE itself. Recommend network restriction / an auth proxy on the SPICE side (owner/infra).
7. **Load protection:** a 2 M-row read costs ~35 MB and 3 s; one runaway query on the shared host is realistic. Keep worker concurrency at 1–2 per SPICE, hard LIMIT injection, and a per-run byte budget.
