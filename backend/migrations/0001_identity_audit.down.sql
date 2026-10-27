drop table if exists audit_event, app_session, secret_ref, permission_grant, membership, workspace, app_user cascade;
drop function if exists forbid_mutation() cascade;
