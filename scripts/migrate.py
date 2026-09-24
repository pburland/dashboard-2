"""Apply database migrations (and optionally the seed) in order.

    python -m scripts.migrate           # schema only
    python -m scripts.migrate --seed    # schema, then db/seed/*.sql once each

Each file runs once; applied files are recorded in schema_migrations.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from app.config import load_settings

ROOT = Path(__file__).resolve().parent.parent


def apply(conn: psycopg.Connection, files: list[Path]) -> list[str]:
    conn.execute("create table if not exists schema_migrations "
                 "(name text primary key, applied_at timestamptz not null default now())")
    done = {r[0] for r in conn.execute("select name from schema_migrations")}
    applied = []
    for f in files:
        key = f"{f.parent.name}/{f.name}"
        if key in done:
            continue
        with conn.transaction():
            conn.execute(f.read_text())
            conn.execute("insert into schema_migrations (name) values (%s)", (key,))
        applied.append(key)
    return applied


MIGRATION_LOCK = 7_310_2026   # arbitrary advisory-lock key for this app


def files(seed: bool = True) -> list[Path]:
    out = sorted((ROOT / "db" / "migrations").glob("*.sql"))
    if seed:
        out += sorted((ROOT / "db" / "seed").glob("*.sql"))
    return out


def run(url: str, seed: bool = True) -> list[str]:
    """Apply pending files. Safe to call from several processes at once:
    an advisory lock makes the second caller wait, then find nothing to do."""
    with psycopg.connect(url, autocommit=True, connect_timeout=15) as conn:
        conn.execute("select pg_advisory_lock(%s)", (MIGRATION_LOCK,))
        try:
            return apply(conn, files(seed))
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (MIGRATION_LOCK,))


def main(argv: list[str]) -> int:
    url = load_settings().db_url
    if not url:
        print("SUPABASE_DB_URL is not set", file=sys.stderr)
        return 1
    applied = run(url, seed="--seed" in argv)
    print("applied: " + (", ".join(applied) if applied else "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
