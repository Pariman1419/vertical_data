drop table dead_letter;
alter table job_event drop constraint job_event_detail_small, drop constraint job_event_kind_check;
drop trigger job_event_immutable on job_event;
drop function heartbeat_run(uuid, bigint, int);
drop function claim_run(uuid, text, int);
drop function run_fence_check(uuid, bigint);
drop trigger job_run_guard on job_run;
drop function guard_job_run();
drop index dataset_generation_run_once;
alter table dataset_generation drop constraint dataset_generation_run_fk,
  drop column table_name, drop column dropped_at;
drop index job_run_workspace_idx;
drop index job_run_pending_idx;
alter table job_run
  drop column fence, drop column lease_owner, drop column heartbeat_at, drop column cancel_requested,
  drop column attempt, drop column max_attempts, drop column next_attempt_at, drop column started_at,
  drop column rows_read, drop column bytes_staged, drop column max_rows, drop column max_bytes,
  drop column max_seconds, drop column error_code;
alter table job_run drop constraint job_run_state_check;
alter table job_run add constraint job_run_state_check
  check (state in ('queued','running','succeeded','failed','cancelled','dead'));
