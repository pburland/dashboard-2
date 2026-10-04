"""In-process scheduler (one background thread in the web service).

  03:00 ET  nightly   sync the last 3 days
  05:30 ET  morning   sync the last 2 days, then heat + readiness checks
  startup   backfill  once, 365 days, if no backfill has ever succeeded
  Sun 19:00 weekly    sync the week, write the weekly report, re-plan the
                      next 3 weeks (catches up the next day if missed)

Runs are recorded in ``sync_runs``; "already ran today" is read from there,
so a restart never repeats a job. A separate Railway cron service would work
too, but this keeps the whole system to one service.
"""
from __future__ import annotations

import logging
import os
import threading
import time as _time
from datetime import datetime, time, timedelta

from app import clock, db
from app.ingest import runner

log = logging.getLogger("training.scheduler")
JOBS = (("nightly", time(3, 0), 3, False), ("morning", time(5, 30), 2, True))
BACKFILL_DAYS = 365
TICK_S = 60


CATCH_UP_HOURS = 3


def due(kind: str, at: time, now: datetime, ran_today: set[str]) -> bool:
    """Due from its scheduled time until CATCH_UP_HOURS later, once a day.
    A restart at 9 PM must not run the 05:30 morning check."""
    start = datetime.combine(now.date(), at, tzinfo=now.tzinfo)
    return start <= now < start + timedelta(hours=CATCH_UP_HOURS) and kind not in ran_today


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


WEEKLY_AT = time(19, 0)


def report_week_due(now: datetime, have: set) -> date | None:
    """Monday of the week to report on, if its report is due and missing.
    The latest week ending on a Sunday is due from Sunday 19:00."""
    d = now.date()
    sunday = d - timedelta(days=(d.weekday() + 1) % 7)       # today if Sunday, else last Sunday
    if sunday == d and now.time() < WEEKLY_AT:
        sunday -= timedelta(days=7)
    ws = sunday - timedelta(days=6)
    return None if ws in have else ws


def _weekly(ws) -> None:
    from app import notify, reports
    runner.run("weekly", days=8)
    with db.connect() as conn:
        reports.build(conn, ws)
        notify.report_ready(conn, ws)


def tick() -> list[str]:
    now = clock.now()
    weekly = None
    with db.connect() as conn:
        if _backfill_needed(conn):
            todo = [("backfill", BACKFILL_DAYS, False)]
        else:
            done = _ran_today(conn, now.date())
            todo = [(k, d, m) for k, at, d, m in JOBS if due(k, at, now, done)]
            have = {r["week_start"] for r in conn.execute(
                "select week_start from weekly_summaries where week_start >= %s",
                (now.date() - timedelta(days=21),)).fetchall()}
            tried = conn.execute("select 1 from sync_runs where kind = 'weekly' and started_at > now() - interval '6 hours'").fetchone()
            weekly = None if tried else report_week_due(now, have)
    for kind, days, morning in todo:
        log.warning("running %s sync", kind)
        runner.run(kind, days=days, morning=morning)
    if weekly:
        log.warning("weekly report for %s", weekly)
        _weekly(weekly)
    return [k for k, _, _ in todo] + (["weekly"] if weekly else [])


def _loop() -> None:
    from app import notify
    while True:
        try:
            tick()
        except Exception:
            log.exception("scheduler tick failed")
        try:
            with db.connect() as conn:
                notify.tick(conn)
        except Exception:
            log.exception("notification tick failed")
        _time.sleep(TICK_S)


def start() -> bool:
    if os.environ.get("SCHEDULER", "on").lower() == "off":
        return False
    threading.Thread(target=_loop, name="scheduler", daemon=True).start()
    return True
