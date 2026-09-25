"""One sync run: Oura -> baseline -> Garmin -> Hevy -> evaluate.

Each source is isolated: a failure is recorded and the others still run.
A Postgres advisory lock stops two syncs overlapping (the scheduler and a
manual trigger, or two server instances).
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import date, timedelta

from app import clock, db
from app.ingest import evaluate, garmin as g_ingest, hevy as h_ingest, oura as o_ingest

log = logging.getLogger("training.sync")
SYNC_LOCK = 7_310_2027
ILLNESS_START = date(2026, 9, 13)     # baseline window ends before the hold


def _step(summary: dict, name: str, fn, conn) -> None:
    try:
        summary[name] = {"ok": True, **(fn() or {})}
        conn.commit()
    except Exception as e:
        conn.rollback()
        summary[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        log.error("sync step %s failed: %s", name, traceback.format_exc())
        try:
            if name in ("garmin", "hevy", "oura"):
                db.save_integration(conn, name, last_error=summary[name]["error"])
                conn.commit()
        except Exception:
            conn.rollback()


def run(kind: str = "manual", days: int = 3, morning: bool = False) -> dict:
    today = clock.today()
    start = today - timedelta(days=days)
    summary: dict = {"kind": kind, "from": start.isoformat(), "to": today.isoformat()}
    with db.connect() as conn:
        got = conn.execute("select pg_try_advisory_lock(%s) as ok", (SYNC_LOCK,)).fetchone()["ok"]
        if not got:
            return {**summary, "skipped": "another sync is running"}
        run_id = conn.execute("insert into sync_runs (kind) values (%s) returning id", (kind,)).fetchone()["id"]
        conn.commit()
        try:
            def oura():
                from app.integrations import oura as api
                return o_ingest.sync(conn, start, today, lambda path, **p: _oura_all(conn, api, path, p))

            def baseline():
                prof = evaluate.profile(conn)
                if prof.get("resting_hr_baseline") is None:
                    b = o_ingest.resting_hr_baseline(conn, ILLNESS_START)
                    if b:
                        conn.execute("update profile set resting_hr_baseline = %s, updated_at = now() where id = 1", (b,))
                        return {"resting_hr_baseline": b, "set": True}
                return {"resting_hr_baseline": prof.get("resting_hr_baseline")}

            def garmin():
                from app.integrations import garmin as api
                client, _source, persist = api.client(conn)
                prof = evaluate.profile(conn)
                out = g_ingest.sync(conn, client, start, today, prof.get("resting_hr_baseline"),
                                    prof.get("max_hr_observed"))
                out["token_renewed"] = persist()
                return out

            def hevy():
                return h_ingest.sync(conn, clock.tz())

            def evaluate_all():
                matched = evaluate.match_planned(conn, start, today)
                flagged = evaluate.activity_flags(conn, start)
                out = {"matched": matched, "activity_flags": flagged}
                if morning:
                    from app.integrations import weather
                    out["heat_flags"] = evaluate.heat_checks(conn, today, weather.hourly_forecast(1), clock.tz())
                return out

            for name, fn in (("oura", oura), ("baseline", baseline), ("garmin", garmin),
                             ("hevy", hevy), ("evaluate", evaluate_all)):
                _step(summary, name, fn, conn)
            for name in ("garmin", "hevy", "oura"):
                if summary.get(name, {}).get("ok"):
                    db.save_integration(conn, name, synced=True, last_error=None)
            ok = all(v.get("ok") for v in summary.values() if isinstance(v, dict))
            conn.execute("update sync_runs set finished_at = now(), ok = %s, summary = %s::jsonb where id = %s",
                         (ok, json.dumps(summary, default=str), run_id))
            conn.commit()
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (SYNC_LOCK,))
            conn.commit()
    return summary


def _oura_all(conn, api, path: str, params: dict) -> dict:
    """Follow Oura's next_token pagination and return one merged {'data': [...]}."""
    data, token = [], None
    for _ in range(50):
        page = api.get(conn, path, **params, **({"next_token": token} if token else {}))
        data += page.get("data", [])
        token = page.get("next_token")
        if not token:
            break
    return {"data": data}
