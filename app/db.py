"""Database access. Plain SQL over psycopg; the schema lives in db/migrations."""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import date
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import MissingConfig, load_settings
from app.health.state import Episode
from app.periodization.phases import Phase


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    """One small pool per process. Opening a TLS connection to Supabase costs
    several round trips; reusing connections keeps each request to its queries."""
    global _pool
    with _pool_lock:
        if _pool is None:
            url = load_settings().db_url
            if not url:
                raise MissingConfig("SUPABASE_DB_URL")
            _pool = ConnectionPool(
                url, min_size=1, max_size=6, timeout=15, max_idle=240, open=True,
                kwargs={"row_factory": dict_row, "connect_timeout": 10},
                check=ConnectionPool.check_connection, name="training")
        return _pool


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """A pooled connection; commits on success, rolls back on error."""
    with _get_pool().connection() as conn:
        yield conn


def load_phases(conn: psycopg.Connection) -> list[Phase]:
    rows = conn.execute(
        "select id, name, kind, start_date, end_date, note from phases order by start_date"
    ).fetchall()
    days = conn.execute(
        "select phase_id, day_of_week, strength_label, endurance_label "
        "from phase_days order by phase_id, day_of_week"
    ).fetchall()
    by_phase: dict[int, list] = {}
    for d in days:
        by_phase.setdefault(d["phase_id"], []).append(
            (d["day_of_week"], d["strength_label"], d["endurance_label"]))
    return [Phase(r["name"], r["kind"], r["start_date"], r["end_date"], r["note"],
                  r["id"], tuple(by_phase.get(r["id"], ()))) for r in rows]


def open_episode(conn: psycopg.Connection) -> Episode | None:
    r = conn.execute(
        "select * from health_episodes where closed_on is null"
    ).fetchone()
    if not r:
        return None
    return Episode(
        id=r["id"], kind=r["kind"], started_on=r["started_on"], reason=r["reason"],
        criteria_met={k: date.fromisoformat(v) for k, v in (r["criteria_met"] or {}).items()},
        return_started_on=r["return_started_on"], return_ends_on=r["return_ends_on"],
        closed_on=r["closed_on"],
    )


def races(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "select id, name, race_date, distance, priority, goal_time::text, "
        "stretch_time::text, status, decision_date, decision_rule "
        "from races order by race_date"
    ).fetchall()


def get_integration(conn: psycopg.Connection, provider: str) -> dict | None:
    return conn.execute(
        "select * from integrations where provider = %s", (provider,)
    ).fetchone()


def save_integration(conn: psycopg.Connection, provider: str, *, access_token=None,
                     refresh_token=None, expires_at=None, extra: dict | None = None,
                     last_error: str | None = None, synced: bool = False) -> None:
    conn.execute(
        """
        insert into integrations (provider, access_token, refresh_token, expires_at,
                                  extra, last_error, last_sync_at, updated_at)
        values (%s, %s, %s, %s, %s::jsonb, %s, case when %s then now() end, now())
        on conflict (provider) do update set
          access_token  = coalesce(excluded.access_token, integrations.access_token),
          refresh_token = coalesce(excluded.refresh_token, integrations.refresh_token),
          expires_at    = coalesce(excluded.expires_at, integrations.expires_at),
          extra         = integrations.extra || excluded.extra,
          last_error    = excluded.last_error,
          last_sync_at  = coalesce(excluded.last_sync_at, integrations.last_sync_at),
          updated_at    = now()
        """,
        (provider, access_token, refresh_token, expires_at, json.dumps(extra or {}),
         last_error, synced),
    )
