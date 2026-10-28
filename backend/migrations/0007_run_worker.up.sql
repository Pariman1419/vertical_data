-- 0007 (Phase 3, Task 3): worker columns, fenced writes, publish bookkeeping, dead letters.
-- Extends 0002 job_run / job_event / dataset_generation; nothing is dropped or rewritten.

alter table job_run drop constraint job_run_state_check;
alter table job_run add constraint job_run_state_check
  check (state in ('queued','running','publishing','succeeded','failed','cancelled','dead'));

alter table job_run
  add column fence bigint not null default 0,
  add column lease_owner text check (lease_owner ~ '^[A-Za-z0-9_.:-]{1,100}$'),
  add column heartbeat_at timestamptz,
  add column cancel_requested boolean not null default false,
  add column attempt int not null default 0 check (attempt >= 0),
  add column max_attempts int not null default 3 check (max_attempts between 1 and 10),
  add column next_attempt_at timestamptz,
  add column started_at timestamptz,
  add column rows_read bigint not null default 0 check (rows_read >= 0),
  add column bytes_staged bigint not null default 0 check (bytes_staged >= 0),
  add column max_rows bigint not null default 5000000 check (max_rows > 0),
  add column max_bytes bigint not null default 2147483648 check (max_bytes > 0),
  add column max_seconds int not null default 1800 check (max_seconds between 1 and 86400),
  add column error_code text check (error_code ~ '^[a-z][a-z0-9_]{0,63}$');
create index job_run_pending_idx on job_run (state, next_attempt_at);
create index job_run_workspace_idx on job_run (workspace_id, created_at desc);

alter table dataset_generation
  add column table_name text check (table_name ~ '^[a-z][a-z0-9_]{0,62}$'),
  add column dropped_at timestamptz,
  add constraint dataset_generation_run_fk foreign key (run_id) references job_run(id);
-- a run can publish at most one generation: duplicate delivery cannot duplicate target data
create unique index dataset_generation_run_once on dataset_generation (run_id) where run_id is not null;

-- ---- job_run guards -------------------------------------------------------
create function guard_job_run() returns trigger language plpgsql as $$
declare rev_state text; rev_ws uuid;
begin
  if tg_op = 'INSERT' then
    select r.state, p.workspace_id into rev_state, rev_ws
      from pipeline_revision r join pipeline p on p.id = r.pipeline_id where r.id = new.revision_id;
    if rev_state is distinct from 'approved' then
      raise exception 'only an approved revision can run' using errcode = '42501';
    end if;
    if rev_ws is distinct from new.workspace_id then
      raise exception 'revision belongs to another workspace' using errcode = '42501';
    end if;
    if new.state <> 'queued' or new.fence <> 0 or new.attempt <> 0 then
      raise exception 'a new run must be queued with fence 0' using errcode = '42501';
    end if;
    return new;
  end if;
  if new.revision_id <> old.revision_id or new.workspace_id <> old.workspace_id
     or new.idempotency_key <> old.idempotency_key or new.requested_by <> old.requested_by then
    raise exception 'run identity columns are immutable' using errcode = '42501';
  end if;
  if old.state in ('succeeded','cancelled') and new.state <> old.state then
    raise exception 'terminal run state' using errcode = '42501';
  end if;
  if new.fence < old.fence or new.fence > old.fence + 1 then
    raise exception 'fence must not move backwards or skip' using errcode = '42501';
  end if;
  if new.attempt < old.attempt then
    raise exception 'attempt must not decrease' using errcode = '42501';
  end if;
  if new.state <> old.state and not (
       (old.state = 'queued'     and new.state in ('running','cancelled'))
    or (old.state = 'running'    and new.state in ('publishing','succeeded','failed','queued','cancelled','dead'))
    or (old.state = 'publishing' and new.state in ('succeeded','failed'))
    or (old.state in ('failed','dead') and new.state = 'queued')) then
    raise exception 'illegal run transition % -> %', old.state, new.state using errcode = '42501';
  end if;
  if new.state in ('succeeded','failed','cancelled','dead') and new.finished_at is null then
    new.finished_at := clock_timestamp();
  end if;
  if new.state = 'queued' and old.state in ('failed','dead') then   -- operator retry: fresh attempt budget
    new.attempt := 0; new.finished_at := null; new.error_code := null; new.cancel_requested := false;
  end if;
  return new;
end $$;
create trigger job_run_guard before insert or update on job_run
  for each row execute function guard_job_run();

-- ---- fenced writes: every worker write calls this in the same transaction -
create function run_fence_check(p_run uuid, p_fence bigint) returns void
language plpgsql as $$
declare r job_run%rowtype;
begin
  select * into r from job_run where id = p_run for share;
  if not found or r.fence <> p_fence or r.state not in ('running','publishing')
     or r.lease_expires_at is null or r.lease_expires_at <= clock_timestamp() then
    raise exception 'stale run fence' using errcode = '42501';
  end if;
end $$;

-- atomic claim: returns the new fence, or null when the run is not claimable
create function claim_run(p_run uuid, p_owner text, p_lease_s int) returns bigint
language plpgsql as $$
declare f bigint;
begin
  update job_run set state = 'running', fence = fence + 1, attempt = attempt + 1,
         lease_owner = p_owner, heartbeat_at = clock_timestamp(),
         lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_s),
         started_at = coalesce(started_at, clock_timestamp()), next_attempt_at = null
   where id = p_run and cancel_requested = false and attempt < max_attempts
     and ((state = 'queued' and coalesce(next_attempt_at, clock_timestamp()) <= clock_timestamp())
       or (state = 'running' and lease_expires_at <= clock_timestamp()))
  returning fence into f;
  return f;
end $$;

-- extends the lease only for the current holder; false means the caller lost the run
create function heartbeat_run(p_run uuid, p_fence bigint, p_lease_s int) returns boolean
language plpgsql as $$
declare n int;
begin
  update job_run set heartbeat_at = clock_timestamp(),
         lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_s)
   where id = p_run and fence = p_fence and state in ('running','publishing')
     and lease_expires_at > clock_timestamp();
  get diagnostics n = row_count;
  return n = 1;
end $$;

-- ---- append-only safe event log and dead letters --------------------------
alter table job_event
  add constraint job_event_kind_check check (kind ~ '^[a-z][a-z0-9_.]{0,63}$'),
  add constraint job_event_detail_small check (pg_column_size(detail) <= 2048);
create trigger job_event_immutable before update or delete on job_event
  for each row execute function forbid_mutation();

create table dead_letter (
  run_id uuid primary key references job_run(id),
  workspace_id uuid not null references workspace(id),
  reason text not null check (reason ~ '^[a-z][a-z0-9_]{0,63}$'),
  at timestamptz not null default now()
);
create trigger dead_letter_immutable before update or delete on dead_letter
  for each row execute function forbid_mutation();

grant select, insert, update on job_run to uetl_app;
grant select, insert, update on job_attempt to uetl_app;
grant select, insert on job_event to uetl_app;
grant select, insert on dataset, dataset_generation to uetl_app;
grant update on dataset, dataset_generation to uetl_app;
grant select, insert on dead_letter to uetl_app;
grant usage, select on sequence job_event_id_seq to uetl_app;
grant execute on function run_fence_check(uuid, bigint), claim_run(uuid, text, int),
  heartbeat_run(uuid, bigint, int) to uetl_app;
