-- 0008 (Phase 3, Task 4 item 4): Security-definer DDL helpers for the worker role (uetl_app).
-- Allows uetl_app to create run-scoped staging tables, move them to uetl_published,
-- and swap views without granting broad CREATE privileges on schemas.

create or replace function uetl_meta.worker_create_staging_table(
  p_run uuid,
  p_fence bigint,
  p_table text,
  p_col_defs text
) returns void
language plpgsql
security definer
set search_path = uetl_meta, pg_temp
as $$
begin
  perform run_fence_check(p_run, p_fence);
  if p_table !~ '^r_[a-z0-9_]{1,60}$' then
    raise exception 'invalid staging table name' using errcode = '42602';
  end if;
  -- Basic sanity check on col_defs: no semicolons or comments
  if p_col_defs ~ '[;\-\-]' or p_col_defs ~* '\b(drop|alter|create|delete|truncate|insert|update|grant|revoke)\b' then
    raise exception 'invalid column definitions' using errcode = '42602';
  end if;
  execute format('create table if not exists uetl_staging.%I (%s)', p_table, p_col_defs);
  execute format('grant select, insert, update, delete on uetl_staging.%I to uetl_app', p_table);
end;
$$;

create or replace function uetl_meta.worker_publish_generation(
  p_run uuid,
  p_fence bigint,
  p_target text,
  p_stg_table text,
  p_gen_table text
) returns void
language plpgsql
security definer
set search_path = uetl_meta, pg_temp
as $$
begin
  perform run_fence_check(p_run, p_fence);
  if p_target !~ '^[a-z][a-z0-9_]{2,60}$' then
    raise exception 'invalid target name' using errcode = '42602';
  end if;
  if p_stg_table !~ '^r_[a-z0-9_]{1,60}$' then
    raise exception 'invalid staging table name' using errcode = '42602';
  end if;
  if p_gen_table !~ '^[a-z][a-z0-9_]{1,62}$' then
    raise exception 'invalid generation table name' using errcode = '42602';
  end if;

  execute format('alter table uetl_staging.%I set schema uetl_published', p_stg_table);
  execute format('alter table uetl_published.%I rename to %I', p_stg_table, p_gen_table);
  execute format('drop view if exists uetl_published.%I', p_target);
  execute format('create view uetl_published.%I as select * from uetl_published.%I', p_target, p_gen_table);

  execute format('grant select on uetl_published.%I to uetl_app', p_gen_table);
  execute format('grant select on uetl_published.%I to uetl_app', p_target);
end;
$$;

create or replace function uetl_meta.worker_drop_published_table(
  p_run uuid,
  p_fence bigint,
  p_table text
) returns void
language plpgsql
security definer
set search_path = uetl_meta, pg_temp
as $$
begin
  perform run_fence_check(p_run, p_fence);
  if p_table !~ '^[a-z][a-z0-9_]{1,62}$' then
    raise exception 'invalid table name' using errcode = '42602';
  end if;
  execute format('drop table if exists uetl_published.%I', p_table);
end;
$$;

grant execute on function uetl_meta.worker_create_staging_table(uuid, bigint, text, text) to uetl_app;
grant execute on function uetl_meta.worker_publish_generation(uuid, bigint, text, text, text) to uetl_app;
grant execute on function uetl_meta.worker_drop_published_table(uuid, bigint, text) to uetl_app;
