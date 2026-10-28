"""Explicitly opted-in, disposable PG13 tests. Never falls back to shared .env credentials."""
import os
import pathlib
import shutil
import subprocess
import uuid
from contextlib import contextmanager

import psycopg2
from psycopg2 import sql

ROOT = pathlib.Path(__file__).resolve().parents[2]


@contextmanager
def postgres():
    if os.environ.get('UETL_ACTIVITY_TEST_COMPOSE') != '1':
        raise RuntimeError('Isolated tests require owner approval, then UETL_ACTIVITY_TEST_COMPOSE=1')
    docker = shutil.which('docker') or r'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    project = 'uetl-activity-test-' + uuid.uuid4().hex[:12]
    command = [docker, 'compose', '--env-file', os.devnull, '--project-name', project, '--file', str(ROOT / 'compose.activity-test.yml')]
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    environment = os.environ.copy()
    environment['PATH'] = str(pathlib.Path(docker).parent) + os.pathsep + environment.get('PATH', '')
    def run(arguments, timeout=60):
        result = subprocess.run(command + arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, creationflags=flags, env=environment)
        if result.returncode:
            raise RuntimeError('Isolated Compose failed: ' + result.stderr.decode(errors='replace'))
        return result.stdout.decode().strip()
    try:
        run(['up', '-d', '--wait', '--wait-timeout', '45'], timeout=180)
        endpoint = run(['port', 'pg', '5432'])
        host, port = endpoint.rsplit(':', 1)
        if host != '127.0.0.1' or not port.isdecimal():
            raise RuntimeError('Unexpected isolated PostgreSQL endpoint')
        settings = dict(host=host, port=int(port), dbname='postgres', user='fixture_owner', connect_timeout=3)
        admin = psycopg2.connect(**settings)
        try:
            admin.autocommit = True
            with admin.cursor() as cur:
                for role in ('uetl_migrator', 'uetl_app'):
                    cur.execute(sql.SQL('create role {} login').format(sql.Identifier(role)))
                cur.execute('create database activity_fixture owner uetl_migrator')
        finally:
            admin.close()
        settings.update(dbname='activity_fixture', user='uetl_migrator')
        connection = psycopg2.connect(**settings)
        try:
            with connection, connection.cursor() as cur:
                cur.execute('revoke create on schema public from public')
                for schema in ('uetl_meta', 'uetl_staging', 'uetl_published'):
                    cur.execute(sql.SQL('create schema {} authorization uetl_migrator').format(sql.Identifier(schema)))
                    cur.execute(sql.SQL('grant usage on schema {} to uetl_app').format(sql.Identifier(schema)))
                    cur.execute(sql.SQL('alter default privileges in schema {} grant select,insert,update,delete on tables to uetl_app').format(sql.Identifier(schema)))
                    cur.execute(sql.SQL('alter default privileges in schema {} grant usage,select on sequences to uetl_app').format(sql.Identifier(schema)))
                cur.execute('set search_path=uetl_meta')
                for migration in sorted((ROOT / 'backend/migrations').glob('*.up.sql')):
                    if migration.name[:4] <= '0005' or migration.name == '0006_activity.up.sql':
                        cur.execute(migration.read_text(encoding='utf-8'))
        finally:
            connection.close()
        yield settings
    finally:
        run(['down', '--volumes', '--remove-orphans', '--timeout', '5'], timeout=45)
