-- 0001: identity, tenancy, sessions, secret refs, append-only audit. Runs as uetl_migrator, search_path=uetl_meta.
create table app_user (
  id uuid primary key default gen_random_uuid(),
  username text not null,
  display_name text not null default '',
  password_hash text not null,
  platform_role text not null default 'none' check (platform_role in ('none','superadmin')),
  is_active boolean not null default true,
  failed_logins int not null default 0,
  locked_until timestamptz,
  created_at timestamptz not null default now()
);
create unique index app_user_username_uq on app_user (lower(username));

create table workspace (
  id uuid primary key default gen_random_uuid(),
  slug text not null check (slug ~ '^[a-z0-9][a-z0-9-]{1,40}$'),
  name text not null,
  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  unique (slug)
);

create table membership (
  workspace_id uuid not null references workspace(id) on delete cascade,
  user_id uuid not null references app_user(id) on delete cascade,
  role text not null check (role in ('viewer','author','reviewer','operator','admin')),
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

create table permission_grant (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspace(id) on delete cascade,
  user_id uuid not null references app_user(id) on delete cascade,
  object_type text not null,
  object_id uuid not null,
  permission text not null,
  created_at timestamptz not null default now(),
  unique (workspace_id, user_id, object_type, object_id, permission)
);

-- names only, never secret values
create table secret_ref (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspace(id) on delete cascade,
  name text not null,
  provider text not null check (provider in ('env','file')),
  rotated_at timestamptz,
  created_at timestamptz not null default now(),
  unique (workspace_id, name)
);

-- id_hash is sha256 of the opaque cookie token
create table app_session (
  id_hash bytea primary key,
  user_id uuid not null references app_user(id) on delete cascade,
  csrf_token text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  ip inet
);
create index app_session_user_idx on app_session (user_id);

create table audit_event (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  correlation_id uuid,
  actor_user_id uuid,
  workspace_id uuid,
  action text not null,
  object_type text,
  object_id text,
  outcome text not null check (outcome in ('allow','deny','error')),
  detail jsonb not null default '{}'::jsonb
);
create index audit_event_ws_at_idx on audit_event (workspace_id, at desc);

create function forbid_mutation() returns trigger language plpgsql as $$
begin
  raise exception '% on % is not allowed (append-only)', tg_op, tg_table_name using errcode = '42501';
end $$;

create trigger audit_event_immutable before update or delete on audit_event
  for each row execute function forbid_mutation();
create trigger audit_event_no_truncate before truncate on audit_event
  for each statement execute function forbid_mutation();
revoke update, delete, truncate on audit_event from uetl_app;
