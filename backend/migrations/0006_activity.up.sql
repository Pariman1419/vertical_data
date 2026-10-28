-- Task 1 only: closed, structured source metrics; no SQL/message/token/detail column.
create table source_event (
  id bigint generated always as identity primary key,
  at timestamptz not null default clock_timestamp(),
  workspace_id uuid not null,
  connection_id uuid not null,
  user_id uuid,
  dataset text check (length(dataset) <= 200 and dataset ~ '^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$'),
  kind text not null check (kind in ('queue_wait','busy_429','timeout','read_ok','read_error')),
  waited_ms bigint check (waited_ms >= 0),
  rows bigint check (rows >= 0),
  bytes bigint check (bytes >= 0)
);
create index source_event_ws_id on source_event(workspace_id, id desc);
create index source_event_at on source_event(at);

create function guard_source_event() returns trigger language plpgsql as $$
begin
  -- The only mutation exception is expiry pruning by the migration-owner function below.
  if tg_op = 'DELETE' and current_user = 'uetl_migrator'
     and old.at < clock_timestamp() - interval '30 days' then
    return old;
  end if;
  raise exception 'source_event is append-only' using errcode='42501';
end $$;
create trigger source_event_immutable before update or delete on source_event
  for each row execute function guard_source_event();
create trigger source_event_no_truncate before truncate on source_event
  for each statement execute function guard_source_event();
revoke all on source_event from uetl_app;
grant select, insert on source_event to uetl_app;
grant usage, select on sequence source_event_id_seq to uetl_app;

create function prune_source_events() returns bigint language plpgsql security definer
set search_path=uetl_meta,pg_temp as $$
declare removed bigint;
begin
  delete from source_event where at < clock_timestamp() - interval '30 days';
  get diagnostics removed = row_count;
  return removed;
end $$;
revoke all on function prune_source_events() from public;
grant execute on function prune_source_events() to uetl_app;
