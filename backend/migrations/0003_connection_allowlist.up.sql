-- 0003: per-connection object allowlist (decision D13: SPICE has no per-user auth, so U-ETL enforces access)
-- and a rule that a connection can only use a secret_ref from its own workspace.
create table connection_allowed_object (
  connection_id uuid not null references connection(id) on delete cascade,
  object_name text not null check (object_name ~ '^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$' and length(object_name) <= 200),
  added_by uuid not null references app_user(id),
  added_at timestamptz not null default now(),
  primary key (connection_id, object_name)
);

create function guard_connection_secret() returns trigger language plpgsql as $$
begin
  if new.secret_ref_id is not null and not exists (
       select 1 from secret_ref s where s.id = new.secret_ref_id and s.workspace_id = new.workspace_id) then
    raise exception 'secret_ref belongs to another workspace' using errcode = '42501';
  end if;
  return new;
end $$;

create trigger connection_secret_guard before insert or update on connection
  for each row execute function guard_connection_secret();
