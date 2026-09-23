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


def main(argv: list[str]) -> int:
    url = load_settings().db_url
    if not url:
        print("SUPABASE_DB_URL is not set", file=sys.stderr)
        return 1
    files = sorted((ROOT / "db" / "migrations").glob("*.sql"))
    if "--seed" in argv:
        files += sorted((ROOT / "db" / "seed").glob("*.sql"))
    with psycopg.connect(url, autocommit=True) as conn:
        applied = apply(conn, files)
    print("applied: " + (", ".join(applied) if applied else "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
