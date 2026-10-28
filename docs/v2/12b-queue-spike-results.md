# Phase 3 Task 2 — Dramatiq spike

Date: 2026-10-28. Task 2 only; Task 3 and deployment are outside this spike.

## Environment and scope

- **TESTED LIVE / ISOLATED:** Redis 7.0.15 in WSL Ubuntu-24.04, on a random port bound only to `127.0.0.1`. The pre-existing Redis on 6379 is not used or stopped. The spike checks that unauthenticated PING is rejected. A random temporary password lives in process environment/memory and Redis configuration supplied through stdin; no password/config file, command-line password, or credential-bearing URL is created.
- **TESTED LIVE / ISOLATED:** Python 3.12.3 in WSL, `dramatiq==2.2.1` and existing `redis==8.1.0`. Owner approved the Dramatiq pip installation; `pip install --no-deps dramatiq==2.2.1` installed only that package. WSL imports these pure Python packages from the existing Windows site-packages through process-local `PYTHONPATH`; no second installation or application requirements change.
- **TESTED LIVE / ISOLATED:** PostgreSQL 16.15, private Unix socket in a mode-0700 temporary directory, `listen_addresses=''`, host authentication rejected. No shared database connection, application config import, `.env` read, Docker command, system package installation, or service registration is involved.
- Native Windows PostgreSQL lacks `postgres.bki`; WSL initially has PostgreSQL clients only. Instead of falling back to a mock, the harness downloads the official Ubuntu `postgresql-16_16.15-0ubuntu0.24.04.1_amd64.deb`, verifies SHA-256 `d60ae76fb862cd4cca7bfdcdcdcc271c5e1d75f6b7915305ce2d962735a4b666`, and extracts it under `TemporaryDirectory`. Its binaries, catalog resources and test cluster are deleted together. Source: [Ubuntu package](https://archive.ubuntu.com/ubuntu/pool/main/p/postgresql-16/postgresql-16_16.15-0ubuntu0.24.04.1_amd64.deb). Versions: [Dramatiq on PyPI](https://pypi.org/project/dramatiq/2.2.1/), [redis-py on PyPI](https://pypi.org/project/redis/8.1.0/).
- **No MOCKED results:** run/lease authority, competing claims, fenced writes and reaper scans use actual isolated PostgreSQL. Its tiny throwaway tables/functions are **not** the future Task 3 migration, role design, production schema, or PG13 compatibility certification.

## Method and plan corrections

The retained [throwaway harness](../../scripts/spike_queue.py) imports no application backend modules. Each Dramatiq actor receives exactly `{"run_id": "<generated UUID>"}` as application payload; mode, progress, lease and fence come from PG. No SQL, source data or credentials are sent in queue payloads.

PG claims use one conditional `UPDATE ... RETURNING`, increment the fence, and set a six-second lease. A separate thread renews that lease every second only while the current token and unexpired running state still match. The staging-write surrogate has a PG trigger that locks/checks the run and rejects old/expired tokens. Completion is likewise conditional on token, running state and an unexpired lease. The reaper reads queued/expired-running rows from PG and supplies fresh queue wakeups; it does not trust Redis as a run ledger.

Ruling: use the owner's WSL/no-Docker instruction instead of the plan's Compose step, and the requested `12b` report path instead of `12`. Temporary package extraction allows real PG evidence without touching the shared DB. These results cover PG16 only.

Ruling: Dramatiq has no Celery-style `acks_late=True` setting. Redis acknowledgement happens after actor processing. `max_retries=0` is set on the actor and `Retries` middleware, not as a Redis connection argument. See [Dramatiq RedisBroker source](https://dramatiq.io/_modules/dramatiq/brokers/redis.html) and [worker source](https://dramatiq.io/_modules/dramatiq/worker.html); the installed 2.2.1 source was inspected directly.

Broker death detection is based on **broker-process heartbeat**, not a per-message visibility extension API. For fast failure injection the harness sets `heartbeat_timeout=1500 ms`, consumer idle timeout 100 ms, and `maintenance_chance=1_000_000` (maintenance on every eligible dispatch). Production defaults, probability-dependent recovery latency, broker saturation and throughput are not measured. Redis AOF uses `appendfsync always`, with snapshots disabled; this does not certify loss-free power failure under `everysec`.

One worker thread and prefetch=1 keep one active run per worker. A diagnostic run with default prefetch=2 stalled the concurrent-duplicate experiment: worker one reserved the duplicate behind its held job, so worker two could not consume it. PG heartbeats continued; no second claim occurred. Setting prefetch=1 makes that experiment exercise two processes as intended. The full six-experiment run also passed four isolated PG contract tests covering concurrent claims, expired-token rejection (including no takeover), and durable queued-state scans. Their initial missing implementation failed before the working implementation passed.

The final isolation review added a fifth regression: inherited `PGSERVICE`/`PGHOSTADDR` must not override the explicit private socket. It failed before the query helper discarded inherited `PG*` settings and selected `/dev/null` as its password file, then **all five tests passed** against a fresh isolated PG. The measured full run had no inherited `PG*` variables. Its measurements below are from that completed run, before this environment-only guard; all five regression tests were rerun after the guard. No application/shared-DB suite was run in this task.

## Results

Any assertion failure in (a)–(d) stops the harness before (e)/(f) and always runs cleanup. The results below are measured, not estimates.

| Experiment | Evidence | Observed result |
|---|---|---|
| (a) Kill worker mid-job | **TESTED LIVE / ISOLATED** | Actual Linux `SIGKILL`, exit **-9**. The **same Dramatiq message ID** was delivered again **6.871 s** after the kill. Two actor invocations, fence **2**, **one** successful completion. The PG trigger rejected a write carrying the old fence. |
| (b) Duplicate `run_id` | **TESTED LIVE / ISOLATED** | Three messages for one run: original, duplicate during its held lease (another process), duplicate after completion. **Three deliveries, two no-ops, fence 1, one completion, one guarded staging-write surrogate.** |
| (c) Redis restart with AOF | **TESTED LIVE / ISOLATED** | Enqueued with no workers, killed Redis with `SIGKILL`, restarted the same isolated data directory. **1 queued before, 1 after**, byte-identical message envelope, same message ID, **one completion**. `appendfsync=always`; this is not an `everysec` durability claim. |
| (d) Redis flush | **TESTED LIVE / ISOLATED** | `FLUSHALL` on the dedicated random-port instance left **0 keys** while PG still held a queued run. PG reaper found/enqueued **1** run; worker claimed fence **1** and completed **once**. |
| (e) Five-minute job / heartbeat | **TESTED LIVE / ISOLATED** | Actual actor duration **300.051 s**, exceeding the **1,500 ms** broker death timeout and **6 s** PG lease many times. **296 PG heartbeats**, **574 samples**, minimum observed PG lease remaining **4.978 s**, maximum observed broker heartbeat age **113 ms**. An idle competing worker drove maintenance throughout; **1 delivery, fence 1, 1 completion**, no redelivery. |
| (f) Stream 5 M local synthetic rows | **TESTED LIVE / ISOLATED** | A fresh worker consumed **5,000,000** generated `(integer, synthetic string, modulo)` tuples without collecting them, in **1.639 s**. Checksum **12,499,997,500,000** matched. RSS before **37,609,472 B**, sampled peak/after **37,658,624 B**: growth **49,152 B (48 KiB)**. |

Additional **TESTED LIVE / ISOLATED** observation from an earlier diagnostic run: redelivery arrived **5.793 s** after worker death, before the six-second PG lease expired. It correctly became a no-op/ACK; when the PG lease expired, the PG reaper supplied a new wakeup. Total **3 invocations, 1 no-op, fence 2, 1 completion**, old-fence write rejected. Redis redelivery alone therefore cannot replace the PG reaper. In the final run the replacement worker started late enough to claim directly after lease expiry, so that run needed no reaper intervention in (a). These startup-dependent times are observations, not recovery SLOs.

For (e), the broker's normal queue/delay-queue consumer traffic updates its process heartbeat; no invented per-message visibility-extension call was used. The explicit one-second thread renews the independent PG lease. Keeping both alive is necessary; a PG heartbeat alone does not keep a Dramatiq broker alive.

For (f), RSS came from `/proc/self/status` every **10,000 rows** (500 sampling boundaries). Linux `resource.getrusage(RUSAGE_SELF).ru_maxrss` was **43,278,336 B (41.2734375 MiB)** both before and after streaming: no increase in the process lifetime high-water mark. RSS sampled growth was **0.046875 MiB**. The difference between current RSS and lifetime high-water is retained explicitly; the sample is a small local-generator workload, not a Flight/COPY performance estimate.

## Limits

This selects a queue transport, not Gate 3 acceptance. It does not test SPICE/Flight, Arrow batches, COPY, real source data, application migrations/permissions, publication transactions, multiple hosts, network partitions, production Compose, Redis AOF `everysec` loss windows, or failover. The synthetic memory experiment uses an in-process generator; its result must not be presented as a full ETL memory bound.

## Reproduce after review

Requires the already approved exact Python packages, existing WSL Redis 7.0.15, PostgreSQL16 `psql`, `dpkg-deb`, and access to the pinned Ubuntu package. Run from the repository in PowerShell:

```powershell
$site = python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
$siteWsl = wsl.exe -d Ubuntu-24.04 -- wslpath -u $site
$scriptWsl = wsl.exe -d Ubuntu-24.04 -- wslpath -u (Join-Path (Get-Location) 'scripts\spike_queue.py')
wsl.exe -d Ubuntu-24.04 -- env "PYTHONPATH=$siteWsl" python3 -B $scriptWsl --self-test
wsl.exe -d Ubuntu-24.04 -- env "PYTHONPATH=$siteWsl" python3 -B $scriptWsl --run
```

`--self-test` creates/removes only its own PG instance; `--run` repeats the five contract tests and runs all six experiments. It must run for at least five minutes for (e). It emits safe JSON measurements to stdout; no measurement is inferred from a simulation. `SIGINT`/`SIGTERM` and experiment failures run finally-based cleanup; manually killing the controller with `SIGKILL` cannot run Python cleanup and is not part of this procedure. Worker/Redis failure injection is owned by the controller.

## Cleanup and decision

**TESTED LIVE / ISOLATED:** the completed six-experiment run exited **0**, with no failure class. Its finally block reaped all owned workers, Redis and PostgreSQL, scanned temporary files for the actual random password (**not found**), restored its process environment and removed its complete temporary directory. The final five-test run also exited **0** and removed its cluster. External `/proc` and `/tmp` checks found **0 owned processes and 0 spike/probe/unit scratch directories**. The pre-existing Redis service remains outside the spike. No shared migration was applied; no Docker command was issued; no Task 3 work was started.

The confirmation is conditional on **PG authority, fenced writes, PG-driven recovery/retries and an active reaper**, as demonstrated here. Redis wakeups can be duplicated or disappear. Retain prefetch=1 for one run per worker, keep broker heartbeats independently alive, and choose/document AOF fsync policy when implementing hosting. This is the Task 2 framework decision only; stop for owner/Claude review before Task 3.

Dramatiq confirmed
