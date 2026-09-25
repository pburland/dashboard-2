"""Garmin activities + laps -> activities / laps tables.

Parsing is pure (``parse_activity``, ``parse_laps``) so it is tested without
a network. Field names are read defensively: Garmin's raw API uses camelCase
(``averageHR``), and a few payloads seen through other tools use snake_case
(``avg_hr_bpm``); both are accepted.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone

from app.analysis.load import trimp
from app.analysis.overreach import Lap, decoupling

SPORT = {
    "running": "run", "trail_running": "run", "treadmill_running": "run", "track_running": "run",
    "street_running": "run", "indoor_running": "run",
    "cycling": "bike", "road_biking": "bike", "indoor_cycling": "bike", "virtual_ride": "bike",
    "gravel_cycling": "bike", "mountain_biking": "bike",
    "lap_swimming": "swim", "open_water_swimming": "swim", "swimming": "swim",
    "strength_training": "strength",
    "walking": "walk", "hiking": "walk",
    "tennis": "tennis", "tennis_v2": "tennis",
}
LAP_SPORTS = {"run", "bike"}
LAP_DELAY_S = 0.4          # be gentle with Garmin between per-activity calls
DECOUPLING_MIN_S = 45 * 60


def _get(d: dict, *keys, default=None):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


def sport_of(raw: dict) -> str:
    t = raw.get("activityType")
    key = (t.get("typeKey") if isinstance(t, dict) else t) or raw.get("type") or "other"
    return SPORT.get(key, "other")


def parse_activity(raw: dict) -> dict:
    start_local = _get(raw, "startTimeLocal", "start_time")
    start_local_dt = datetime.fromisoformat(str(start_local).replace("T", " ")[:19])
    gmt = _get(raw, "startTimeGMT")
    start_utc = (datetime.fromisoformat(str(gmt).replace("T", " ")[:19]).replace(tzinfo=timezone.utc)
                 if gmt else None)
    return {
        "provider": "garmin",
        "external_id": str(_get(raw, "activityId", "id")),
        "start_local": start_local_dt,
        "start_utc": start_utc,
        "local_date": start_local_dt.date(),
        "sport": sport_of(raw),
        "title": _get(raw, "activityName", "name"),
        "distance_m": _get(raw, "distance", "distance_meters"),
        "duration_s": _get(raw, "duration", "duration_seconds"),
        "moving_s": _get(raw, "movingDuration", "moving_duration_seconds"),
        "avg_hr": _get(raw, "averageHR", "avg_hr_bpm"),
        "max_hr": _get(raw, "maxHR", "max_hr_bpm"),
        "elevation_gain_m": _get(raw, "elevationGain", "elevation_gain_meters"),
        "calories": _get(raw, "calories"),
        "aerobic_te": _get(raw, "aerobicTrainingEffect"),
        "avg_power_w": _get(raw, "avgPower", "averagePower"),
        "norm_power_w": _get(raw, "normPower"),
        "raw": raw,
    }


def parse_laps(splits: dict) -> list[dict]:
    laps = _get(splits, "lapDTOs", "laps", default=[]) or []
    out = []
    for i, l in enumerate(laps):
        out.append({
            "lap_index": int(_get(l, "lapIndex", "lap_number", default=i + 1)),
            "distance_m": _get(l, "distance", "distance_meters"),
            "duration_s": _get(l, "duration", "duration_seconds"),
            "avg_hr": _get(l, "averageHR", "avg_hr_bpm"),
            "max_hr": _get(l, "maxHR", "max_hr_bpm"),
            "avg_power_w": _get(l, "averagePower", "avg_power_watts"),
        })
    return out


def activity_decoupling(act: dict, laps: list[dict]) -> float | None:
    if act["sport"] not in LAP_SPORTS or (act.get("duration_s") or 0) < DECOUPLING_MIN_S:
        return None
    usable = [Lap(l["distance_m"] or 0, l["duration_s"] or 0, l["avg_hr"] or 0) for l in laps]
    usable = [l for l in usable if l.distance_m > 0 and l.duration_s > 0 and l.avg_hr > 0]
    if len(usable) < 4:
        return None
    return decoupling(usable)


def activity_load(act: dict, rest_hr: int | None, max_hr: int | None) -> float | None:
    if not (act.get("avg_hr") and act.get("duration_s") and rest_hr and max_hr):
        return None
    return round(trimp(act["duration_s"] / 60, act["avg_hr"], rest_hr, max_hr), 1)


UPSERT = """
insert into activities (provider, external_id, start_local, start_utc, local_date, sport, title,
  distance_m, duration_s, moving_s, avg_hr, max_hr, elevation_gain_m, calories, aerobic_te,
  avg_power_w, norm_power_w, load_trimp, decoupling, raw)
values (%(provider)s, %(external_id)s, %(start_local)s, %(start_utc)s, %(local_date)s, %(sport)s,
  %(title)s, %(distance_m)s, %(duration_s)s, %(moving_s)s, %(avg_hr)s, %(max_hr)s,
  %(elevation_gain_m)s, %(calories)s, %(aerobic_te)s, %(avg_power_w)s, %(norm_power_w)s,
  %(load_trimp)s, %(decoupling)s, %(raw)s::jsonb)
on conflict (provider, external_id) do update set
  title = excluded.title, distance_m = excluded.distance_m, duration_s = excluded.duration_s,
  moving_s = excluded.moving_s, avg_hr = excluded.avg_hr, max_hr = excluded.max_hr,
  elevation_gain_m = excluded.elevation_gain_m, calories = excluded.calories,
  aerobic_te = excluded.aerobic_te, avg_power_w = excluded.avg_power_w,
  norm_power_w = excluded.norm_power_w,
  load_trimp = coalesce(excluded.load_trimp, activities.load_trimp),
  decoupling = coalesce(excluded.decoupling, activities.decoupling),
  raw = excluded.raw, ingested_at = now()
returning id
"""


def store(conn, act: dict, laps: list[dict]) -> int:
    row = {**act, "raw": json.dumps(act["raw"], default=str)}
    act_id = conn.execute(UPSERT, row).fetchone()["id"]
    if laps:
        conn.execute("delete from laps where activity_id = %s", (act_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "insert into laps (activity_id, lap_index, distance_m, duration_s, avg_hr, max_hr, avg_power_w) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                [(act_id, l["lap_index"], l["distance_m"], l["duration_s"], l["avg_hr"],
                  l["max_hr"], l["avg_power_w"]) for l in laps])
    return act_id


def sync(conn, client, start: date, end: date, rest_hr: int | None, max_hr: int | None,
         fetch_laps: bool = True) -> dict:
    """Fetch activities in [start, end] and upsert them. Returns counts."""
    raws = client.get_activities_by_date(start.isoformat(), end.isoformat())
    have_laps = {r["external_id"] for r in conn.execute(
        "select a.external_id from activities a where a.provider = 'garmin' "
        "and exists (select 1 from laps l where l.activity_id = a.id)").fetchall()}
    n = n_laps = 0
    for raw in raws:
        act = parse_activity(raw)
        laps: list[dict] = []
        if fetch_laps and act["sport"] in LAP_SPORTS and act["external_id"] not in have_laps:
            laps = parse_laps(client.get_activity_splits(act["external_id"]))
            time.sleep(LAP_DELAY_S)
        act["decoupling"] = activity_decoupling(act, laps) if laps else None
        act["load_trimp"] = activity_load(act, rest_hr, max_hr)
        store(conn, act, laps)
        n += 1
        n_laps += len(laps)
    return {"activities": n, "laps": n_laps}
