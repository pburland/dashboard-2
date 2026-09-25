"""In-process scheduler (one background thread in the web service).

  03:00 ET  nightly   sync the last 3 days
  05:30 ET  morning   sync the last 2 days, then heat + readiness checks
  startup   backfill  once, 365 days, if no backfill has ever succeeded

Runs are recorded in ``sync_runs``; "already ran today" is read from there,
so a restart never repeats a job. A separate Railway cron service would work
too, but this keeps the whole system to one service.
"""
from __future__ import annotations

import logging
import os
import threading
import time as _time
from datetime import datetime, time

from app import clock, db
from app.ingest import runner

log = logging.getLogger("training.scheduler")
JOBS = (("nightly", time(3, 0), 3, False), ("morning", time(5, 30), 2, True))
BACKFILL_DAYS = 365
TICK_S = 60


def due(kind: str, at: time, now: datetime, ran_today: set[str]) -> bool:
    return now.time() >= at and kind not in ran_today


def _ran_today(conn, today) -> set[str]:
    rows = conn.execute(
        """select distinct kind from sync_runs
           where finished_at is not null and (started_at at time zone %s)::date = %s""",
        (clock.tz().key, today)).fetchall()
    return {r["kind"] for r in rows}


BACKFILL_RETRY_HOURS = 6


def _backfill_needed(conn) -> bool:
    """No successful backfill yet, and none attempted recently (a failing
    provider must not be retried every minute)."""
    return not conn.execute(
        """select 1 from sync_runs where kind = 'backfill'
           and (ok or started_at > now() - make_interval(hours => %s))""",
        (BACKFILL_RETRY_HOURS,)).fetchone()


def tick() -> list[str]:
    now = clock.now()
    with db.connect() as conn:
        if _backfill_needed(conn):
            todo = [("backfill", BACKFILL_DAYS, False)]
        else:
            done = _ran_today(conn, now.date())
            todo = [(k, d, m) for k, at, d, m in JOBS if due(k, at, now, done)]
    for kind, days, morning in todo:
        log.warning("running %s sync", kind)
        runner.run(kind, days=days, morning=morning)
    return [k for k, _, _ in todo]


def _loop() -> None:
    while True:
        try:
            tick()
        except Exception:
            log.exception("scheduler tick failed")
        _time.sleep(TICK_S)


def start() -> bool:
    if os.environ.get("SCHEDULER", "on").lower() == "off":
        return False
    threading.Thread(target=_loop, name="scheduler", daemon=True).start()
    return True
