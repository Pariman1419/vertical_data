drop trigger if exists connection_secret_guard on connection;
drop function if exists guard_connection_secret();
drop table if exists connection_allowed_object;
