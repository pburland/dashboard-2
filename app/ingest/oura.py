"""Oura daily readiness + sleep -> recovery (one row per day)."""
from __future__ import annotations

import json
from datetime import date, timedelta


def merge_days(readiness: list[dict], daily_sleep: list[dict], sleeps: list[dict]) -> dict[str, dict]:
    """Combine three Oura collections into one record per day.

    Resting HR and HRV come from the night's main sleep period
    (``type == 'long_sleep'``; the longest period if none is marked)."""
    days: dict[str, dict] = {}

    def day(d: str) -> dict:
        return days.setdefault(d, {"day": d, "raw": {}})

    for r in readiness:
        rec = day(r["day"])
        rec["readiness"] = r.get("score")
        rec["temp_deviation_c"] = r.get("temperature_deviation")
        rec["raw"]["readiness"] = r
    for s in daily_sleep:
        rec = day(s["day"])
        rec["sleep_score"] = s.get("score")
        rec["raw"]["daily_sleep"] = s
    def rank(p: dict) -> tuple:
        return (p.get("type") == "long_sleep", p.get("total_sleep_duration") or 0)

    main: dict[str, dict] = {}
    for p in sleeps:
        d = p.get("day")
        if d and (d not in main or rank(p) > rank(main[d])):
            main[d] = p
    for d, p in main.items():
        rec = day(d)
        rec["resting_hr"] = p.get("lowest_heart_rate")
        rec["hrv_ms"] = p.get("average_hrv")
        rec["total_sleep_s"] = p.get("total_sleep_duration")
        rec["raw"]["sleep"] = {k: p.get(k) for k in ("id", "type", "lowest_heart_rate", "average_hrv",
                                                     "average_heart_rate", "total_sleep_duration")}
    return days


UPSERT = """
insert into recovery (day, sleep_score, readiness, hrv_ms, resting_hr, temp_deviation_c,
                      total_sleep_s, raw, synced_at)
values (%(day)s, %(sleep_score)s, %(readiness)s, %(hrv_ms)s, %(resting_hr)s, %(temp_deviation_c)s,
        %(total_sleep_s)s, %(raw)s::jsonb, now())
on conflict (day) do update set
  sleep_score = coalesce(excluded.sleep_score, recovery.sleep_score),
  readiness = coalesce(excluded.readiness, recovery.readiness),
  hrv_ms = coalesce(excluded.hrv_ms, recovery.hrv_ms),
  resting_hr = coalesce(excluded.resting_hr, recovery.resting_hr),
  temp_deviation_c = coalesce(excluded.temp_deviation_c, recovery.temp_deviation_c),
  total_sleep_s = coalesce(excluded.total_sleep_s, recovery.total_sleep_s),
  raw = recovery.raw || excluded.raw, synced_at = now()
"""

FIELDS = ("sleep_score", "readiness", "hrv_ms", "resting_hr", "temp_deviation_c", "total_sleep_s")


def sync(conn, start: date, end: date, get) -> dict:
    """``get(path, **params)`` is app.integrations.oura.get bound to a connection."""
    # Oura's end_date is exclusive for some collections; ask for one extra day.
    params = {"start_date": start.isoformat(), "end_date": (end + timedelta(days=1)).isoformat()}
    readiness = get("daily_readiness", **params).get("data", [])
    daily_sleep = get("daily_sleep", **params).get("data", [])
    sleeps = get("sleep", **params).get("data", [])
    days = merge_days(readiness, daily_sleep, sleeps)
    with conn.cursor() as cur:
        cur.executemany(UPSERT, [{**{f: None for f in FIELDS}, **r, "raw": json.dumps(r["raw"])}
                                 for r in days.values()])
    return {"days": len(days)}


def resting_hr_baseline(conn, before: date, window_days: int = 28) -> int | None:
    """Median resting HR over the window ending the day before ``before``."""
    r = conn.execute(
        "select percentile_cont(0.5) within group (order by resting_hr) as m from recovery "
        "where resting_hr is not null and day >= %s and day < %s",
        (before - timedelta(days=window_days), before)).fetchone()
    return round(r["m"]) if r and r["m"] is not None else None
