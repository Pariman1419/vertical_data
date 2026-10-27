-- Requests to add a dataset to the SPICE pod. The request holds NO credentials: it names an existing source profile.
create table dataset_request (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspace(id) on delete cascade,
  connection_id uuid not null references connection(id) on delete cascade,
  requested_by uuid not null references app_user(id),
  profile text not null check (profile in ('pg','scada')),
  dataset_name text not null check (dataset_name ~ '^[a-z][a-z0-9_]{2,60}$'),
  remote_object text not null check (length(remote_object) <= 200),
  status text not null default 'pending' check (status in ('pending','applied','cancelled')),
  note text check (length(note) <= 500),
  created_at timestamptz not null default now(),
  closed_at timestamptz
);
create unique index dataset_request_pending_name on dataset_request(workspace_id, dataset_name) where status = 'pending';
create index dataset_request_ws on dataset_request(workspace_id, created_at desc);

-- Only the status may change, and only out of 'pending'; a closed request is final.
create function guard_dataset_request() returns trigger language plpgsql as $$
begin
  if old.status <> 'pending' then
    raise exception 'dataset_request is closed' using errcode = '42501';
  end if;
  if (new.workspace_id, new.connection_id, new.requested_by, new.profile, new.dataset_name, new.remote_object, new.created_at)
     is distinct from (old.workspace_id, old.connection_id, old.requested_by, old.profile, old.dataset_name, old.remote_object, old.created_at) then
    raise exception 'dataset_request fields are immutable' using errcode = '42501';
  end if;
  return new;
end $$;
create trigger dataset_request_guard before update on dataset_request for each row execute function guard_dataset_request();
