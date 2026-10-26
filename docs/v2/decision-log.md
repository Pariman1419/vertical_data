# Decision log
| Date | Decision | Evidence |
|---|---|---|
| 2026-10-26 | Repo = `Pariman1419/vertical_data`; baseline tag `v1-pilot-baseline` | commit 1578c79 |
| 2026-10-26 | Stack: FastAPI/PostgreSQL/Redis/Compose, React+Vite+TS, argon2id | owner message |
| 2026-10-26 | Worker extraction via Flight SQL (REST only catalog/preview) | `01-capability-matrix.md` probes #2/#3 |
| 2026-10-26 | Compose Postgres host port 15432 (5432 occupied) | netstat on dev host |
