"""Backup round trip against a real Postgres (TEST_DATABASE_URL)."""
import os
import zipfile, io, json
from datetime import date

import psycopg
import pytest

DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL not set")


def test_export_restore_round_trip():
    from scripts import backup, migrate
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("drop schema public cascade; create schema public")
    migrate.run(DB, seed=True)
    with psycopg.connect(DB) as c:
        c.execute("insert into integrations (provider, access_token) values ('oura', 'secret-token')")
        c.execute("insert into weekly_notes (week_start, type, text) values ('2026-10-05', 'context', 'a, \"quoted\"\nnote')")
        c.commit()
        before = {t: c.execute(f'select count(*) from "{t}"').fetchone()[0] for t in backup.tables(c)}
        plain = backup.export(c)
        full = backup.export(c, include_secrets=True)
    names = zipfile.ZipFile(io.BytesIO(plain)).namelist()
    assert "integrations.csv" not in names and "phases.csv" in names       # no tokens by default
    assert b"secret-token" in zipfile.ZipFile(io.BytesIO(full)).read("integrations.csv")

    with psycopg.connect(DB) as c:                 # wreck the data, then restore
        c.execute("delete from weekly_notes"); c.execute("delete from planned_workouts")
        c.commit()
        backup.restore(c, full)
        after = {t: c.execute(f'select count(*) from "{t}"').fetchone()[0] for t in backup.tables(c)}
        assert after == before
        assert c.execute("select text from weekly_notes").fetchone()[0] == 'a, "quoted"\nnote'
        assert c.execute("select started_on from health_episodes where closed_on is null").fetchone()[0] == date(2026, 9, 15)
        # New rows get fresh ids after a restore.
        c.execute("insert into weekly_notes (week_start, type, text) values ('2026-10-12', 'context', 'x')")
        c.commit()
    # Schema bookkeeping came back too, so seeds won't re-run on the next start.
    assert migrate.run(DB, seed=True) == []
