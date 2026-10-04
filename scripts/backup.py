"""Back up and restore the whole database as one zip of CSV files.

    python -m scripts.backup export backup.zip [--with-secrets]
    python -m scripts.backup restore backup.zip        # replaces ALL data

One CSV per table (opens in Excel/Numbers) plus manifest.json. Provider
tokens (the ``integrations`` table) are left out unless --with-secrets is
given; the weekly GitHub backup includes them and is encrypted before upload.

Restore runs against a database whose schema is already migrated (start the
server once, or ``python -m scripts.migrate``): it empties every table in
the backup and reloads it in one transaction, so it either fully works or
changes nothing. Needs only psycopg and SUPABASE_DB_URL.
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone

import psycopg

SECRET_TABLES = {"integrations"}


def tables(conn) -> list[str]:
    """Public tables, parents before children (foreign-key order)."""
    names = [r[0] for r in conn.execute(
        "select tablename from pg_tables where schemaname = 'public' order by tablename")]
    deps = {n: set() for n in names}
    for child, parent in conn.execute(
            """select c.relname, p.relname from pg_constraint k
               join pg_class c on c.oid = k.conrelid join pg_class p on p.oid = k.confrelid
               join pg_namespace n on n.oid = c.relnamespace
               where k.contype = 'f' and n.nspname = 'public'"""):
        if child != parent and child in deps:
            deps[child].add(parent)
    ordered: list[str] = []
    while deps:
        ready = sorted(n for n, d in deps.items() if not d - set(ordered))
        if not ready:                      # a cycle: fall back to name order
            ready = sorted(deps)
        for n in ready:
            ordered.append(n)
            deps.pop(n)
    return ordered


def export(conn, include_secrets: bool = False) -> bytes:
    buf = io.BytesIO()
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "format": 1,
                "with_secrets": include_secrets, "tables": {}}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t in tables(conn):
            if t in SECRET_TABLES and not include_secrets:
                continue
            out = io.BytesIO()
            with conn.cursor().copy(f'copy public."{t}" to stdout with (format csv, header true)') as cp:
                for chunk in cp:
                    out.write(chunk)
            data = out.getvalue()
            z.writestr(f"{t}.csv", data)
            manifest["tables"][t] = max(0, data.count(b"\n") - 1)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buf.getvalue()


def restore(conn, blob: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(blob))
    manifest = json.loads(z.read("manifest.json"))
    order = [t for t in tables(conn) if t in manifest["tables"]]
    missing = set(manifest["tables"]) - set(order)
    if missing:
        raise RuntimeError(f"tables in the backup but not in this database: {sorted(missing)} "
                           "(run the migrations first)")
    with conn.transaction():
        conn.execute("set constraints all deferred")
        conn.execute("truncate " + ", ".join(f'public."{t}"' for t in order) + " restart identity cascade")
        for t in order:
            data = z.read(f"{t}.csv")
            header = data.split(b"\n", 1)[0].decode()
            cols = ", ".join(f'"{c.strip().strip(chr(34))}"' for c in header.split(","))
            with conn.cursor().copy(f'copy public."{t}" ({cols}) from stdin with (format csv, header true)') as cp:
                cp.write(data)
        # Identity counters continue after the restored ids.
        for t, col in conn.execute(
                """select table_name, column_name from information_schema.columns
                   where table_schema = 'public' and is_identity = 'YES'""").fetchall():
            if t in order:
                conn.execute(f"""select setval(pg_get_serial_sequence('public."{t}"', '{col}'),
                                 coalesce((select max("{col}") from public."{t}"), 0) + 1, false)""")
    return manifest["tables"]


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("export", "restore"):
        print(__doc__)
        return 2
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set", file=sys.stderr)
        return 1
    with psycopg.connect(url, connect_timeout=20) as conn:
        if argv[0] == "export":
            blob = export(conn, include_secrets="--with-secrets" in argv)
            with open(argv[1], "wb") as f:
                f.write(blob)
            print(f"wrote {argv[1]} ({len(blob) // 1024} KB)")
        else:
            with open(argv[1], "rb") as f:
                counts = restore(conn, f.read())
            print("restored: " + ", ".join(f"{t} {n}" for t, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
