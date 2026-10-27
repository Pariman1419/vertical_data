-- Independent, short transactions make leases visible across API processes.
create table source_lease (
  id uuid primary key default gen_random_uuid(),
  pool text not null check (pool in ('spice', 'odbc')),
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index source_lease_pool_expiry on source_lease(pool, expires_at);
grant select, insert, delete on source_lease to uetl_app;
