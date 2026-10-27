# Runbook — adding a dataset to SPICE (for the SPICE operator)

Context: U-ETL never edits SPICE and never holds source-database passwords. A user files a **dataset request**
(Sources page -> "Request a new dataset"); U-ETL shows the exact spicepod entry. You apply it on the SPICE host.

Facts from the host report (2026-10-27): container `vdl-spice`, compose `D:\Train\docker-compose.yml`,
pod file `D:\Train\local-dev\spicepod.yaml` (mounted read-only into the container; edit it on the host),
secrets in `D:\Train\local-dev\.env` (plain text, git-ignored). Whether SPICE reloads the file by itself is **NOT confirmed**
(test it first - see "Reload test").

## Apply a request (existing source profile: `pg` or `scada`)
1. Back up: `Copy-Item D:\Train\local-dev\spicepod.yaml "D:\Train\local-dev\spicepod.yaml.bak.$(Get-Date -f yyyyMMdd_HHmmss)"`
2. Paste the entry shown by U-ETL at the end of the `datasets:` list, same indentation as its neighbours.
   Example (shape only): `- from: postgres:"schema"."table"` / `name: my_set` / `params: *pg`.
   The `*pg` / `*scada` alias must be used AFTER the place where the anchor `&pg` / `&scada` is defined in the file.
3. Validate: `python -c "import yaml;yaml.safe_load(open(r'D:\Train\local-dev\spicepod.yaml',encoding='utf-8'));print('yaml ok')"`
4. Reload: if the reload test showed SPICE picks the file up itself, wait; otherwise
   `docker compose -f D:\Train\docker-compose.yml restart spice` (running queries are cut; clients must reconnect).
5. Check: `curl http://localhost:8091/v1/datasets` lists the new name and the total grew by one.
6. In U-ETL press **Refresh catalog**; the request closes itself (status `applied`). Then tick the dataset in "Allowed objects".

## Roll back
Restore the backup from step 1, validate, reload/restart as in step 4, check `/v1/datasets`. Then cancel the U-ETL request.

## New database (no profile yet)
U-ETL cannot request this. An operator adds `KEY=value` lines to `.env` and a new anchored `params:` block in the pod.
Traps seen in this project: a `$` in a password must be written `$$`; do not wrap the value in quotes; values containing
`/` or `[` are literal. Never paste the password into U-ETL, chat or tickets.

## Reload test (do once, outside working hours, tell the owner first)
Add a tiny `zz_reload_probe` dataset copied from a small `_mock` entry, wait 60 s without restarting, check `/v1/datasets` and
`docker logs --tail 50 vdl-spice`. Record the result in `docs/v2/implementation-log.md`. Remove the probe afterwards.

## Known limits
- SPICE has no authentication and the firewall is open to any address (accepted by the owner for the test phase, decision-log 2026-10-27).
- Only the `pg` and `scada` profiles are supported; Oracle profiles need a sample entry from the host first.
- SQL Server-backed datasets do not accept a pushed-down `LIMIT`; U-ETL previews them with a client-side stream cut.
