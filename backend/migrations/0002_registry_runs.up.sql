-- 0002: connections, catalog snapshots, pipelines/revisions, approvals, datasets, runs, settings.
create table connection (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspace(id) on delete cascade,
  name text not null,
  kind text not null check (kind in ('rest','flight')),
  base_url text not null,
  tls_verify boolean not null default true,
  auth_mode text not null default 'secret_ref',
  secret_ref_id uuid references secret_ref(id),
  scope text,
  timeout_s int not null default 10 check (timeout_s between 1 and 120),
  capabilities jsonb,
  last_test_at timestamptz,
  status text not null default 'untested',
  unique (workspace_id, name)
);

create table catalog_snapshot (
  id uuid primary key default gen_random_uuid(),
  connection_id uuid not null references connection(id) on delete cascade,
  revision int not null,
  fetched_at timestamptz not null default now(),
  payload jsonb not null,
  unique (connection_id, revision)
);

create table pipeline (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspace(id) on delete cascade,
  name text not null,
  created_by uuid not null references app_user(id),
  created_at timestamptz not null default now(),
  unique (workspace_id, name)
);

create table pipeline_revision (
  id uuid primary key default gen_random_uuid(),
  pipeline_id uuid not null references pipeline(id) on delete cascade,
  parent_id uuid references pipeline_revision(id),
  spec jsonb not null,
  checksum text not null check (checksum ~ '^[0-9a-f]{64}$'),
  state text not null default 'draft' check (state in ('draft','in_review','approved','rejected','superseded')),
  created_by uuid not null references app_user(id),
  created_at timestamptz not null default now()
);
create index pipeline_revision_pipeline_idx on pipeline_revision (pipeline_id, created_at desc);

-- spec/checksum/parent/author are frozen once a revision leaves draft; approved may only become superseded.
create function guard_revision() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    if old.state <> 'draft' then
      raise exception 'non-draft revision cannot be deleted' using errcode = '42501';
    end if;
    return old;
  end if;
  if new.pipeline_id is distinct from old.pipeline_id or new.created_by is distinct from old.created_by
     or new.parent_id is distinct from old.parent_id then
    raise exception 'revision identity columns are immutable' using errcode = '42501';
  end if;
  if old.state <> 'draft' and (new.spec is distinct from old.spec or new.checksum is distinct from old.checksum) then
    raise exception 'spec/checksum of a non-draft revision are immutable' using errcode = '42501';
  end if;
  if old.state = 'approved' and new.state not in ('approved','superseded') then
    raise exception 'approved revision may only become superseded' using errcode = '42501';
  end if;
  if old.state in ('rejected','superseded') and new.state <> old.state then
    raise exception 'terminal revision state' using errcode = '42501';
  end if;
  return new;
end $$;

create trigger pipeline_revision_guard before update or delete on pipeline_revision
  for each row execute function guard_revision();

create table approval_decision (
  id uuid primary key default gen_random_uuid(),
  revision_id uuid not null references pipeline_revision(id),
  checksum text not null,
  decided_by uuid not null references app_user(id),
  decision text not null check (decision in ('approve','reject')),
  comment text not null default '',
  decided_at timestamptz not null default now()
);
create trigger approval_decision_immutable before update or delete on approval_decision
  for each row execute function forbid_mutation();
create trigger approval_decision_no_truncate before truncate on approval_decision
  for each statement execute function forbid_mutation();
revoke update, delete, truncate on approval_decision from uetl_app;

-- separation of duties and checksum binding are enforced in the database, not only in the API
create function guard_approval() returns trigger language plpgsql as $$
declare r pipeline_revision%rowtype;
begin
  select * into r from pipeline_revision where id = new.revision_id;
  if r.state <> 'in_review' then
    raise exception 'revision not in_review' using errcode = '42501';
  end if;
  if r.checksum <> new.checksum then
    raise exception 'checksum mismatch' using errcode = '42501';
  end if;
  if r.created_by = new.decided_by then
    raise exception 'author cannot decide own revision' using errcode = '42501';
  end if;
  return new;
end $$;

create trigger approval_decision_guard before insert on approval_decision
  for each row execute function guard_approval();

create table dataset (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspace(id) on delete cascade,
  target_schema text not null default 'uetl_published',
  target_table text not null check (target_table ~ '^[a-z][a-z0-9_]{0,62}$'),
  current_generation int not null default 0,
  unique (workspace_id, target_table)
);

create table dataset_generation (
  dataset_id uuid not null references dataset(id) on delete cascade,
  generation int not null,
  revision_id uuid not null references pipeline_revision(id),
  run_id uuid,
  row_count bigint,
  published_at timestamptz not null default now(),
  primary key (dataset_id, generation)
);

create table job_run (
  id uuid primary key default gen_random_uuid(),
  revision_id uuid not null references pipeline_revision(id),
  workspace_id uuid not null references workspace(id),
  idempotency_key text not null,
  state text not null default 'queued' check (state in ('queued','running','succeeded','failed','cancelled','dead')),
  requested_by uuid not null references app_user(id),
  lease_token uuid,
  lease_expires_at timestamptz,
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (revision_id, idempotency_key)
);

create table job_attempt (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references job_run(id) on delete cascade,
  attempt int not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  outcome text,
  error_class text,
  unique (run_id, attempt)
);

create table job_event (
  id bigint generated always as identity primary key,
  run_id uuid not null references job_run(id) on delete cascade,
  at timestamptz not null default now(),
  kind text not null,
  detail jsonb not null default '{}'::jsonb
);

-- non-secret fields and secret_ref names only
create table setting (
  workspace_id uuid not null references workspace(id) on delete cascade,
  kind text not null check (kind in ('redis','postgres','llm')),
  config jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (workspace_id, kind)
);
