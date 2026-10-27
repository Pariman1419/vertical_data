drop table if exists setting, job_event, job_attempt, job_run, dataset_generation, dataset,
  approval_decision, pipeline_revision, pipeline, catalog_snapshot, connection cascade;
drop function if exists guard_approval();
drop function if exists guard_revision();
