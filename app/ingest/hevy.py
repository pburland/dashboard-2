"""Hevy workouts -> strength_sets (one row per set, pounds)."""
from __future__ import annotations

import json
from datetime import datetime

from app.integrations import hevy as api

KG_TO_LB = 2.20462
PAGE_SIZE = 10
MAX_PAGES = 100


def parse_workout(w: dict, tz) -> list[dict]:
    start = datetime.fromisoformat(w["start_time"].replace("Z", "+00:00"))
    performed_on = start.astimezone(tz).date()
    rows = []
    for ex in w.get("exercises", []):
        for s in ex.get("sets", []):
            kg = s.get("weight_kg")
            rows.append({
                "workout_id": w["id"],
                "workout_title": w.get("title"),
                "performed_on": performed_on,
                "exercise": ex.get("title"),
                "set_index": int(s.get("index", 0)),
                "set_type": s.get("type") or s.get("set_type"),
                "weight_lb": round(kg * KG_TO_LB, 1) if kg is not None else None,
                "reps": s.get("reps"),
                "rpe": s.get("rpe"),
                "raw": json.dumps({"exercise_template_id": ex.get("exercise_template_id"), **s}),
            })
    return rows


UPSERT = """
insert into strength_sets (provider, workout_id, workout_title, performed_on, exercise, set_index,
                           set_type, weight_lb, reps, rpe, raw)
values ('hevy', %(workout_id)s, %(workout_title)s, %(performed_on)s, %(exercise)s, %(set_index)s,
        %(set_type)s, %(weight_lb)s, %(reps)s, %(rpe)s, %(raw)s::jsonb)
on conflict (provider, workout_id, exercise, set_index) do update set
  workout_title = excluded.workout_title, performed_on = excluded.performed_on,
  set_type = excluded.set_type, weight_lb = excluded.weight_lb, reps = excluded.reps,
  rpe = excluded.rpe, raw = excluded.raw
"""


def sync(conn, tz, fetch=api.get) -> dict:
    """Walk every page (Hevy's order isn't by date) and upsert all sets.
    Cheap for a personal account; idempotent by (workout, exercise, set)."""
    workouts = sets = 0
    for page in range(1, MAX_PAGES + 1):
        data = fetch("/workouts", page=page, pageSize=PAGE_SIZE)
        batch = data.get("workouts") or []
        for w in batch:
            rows = parse_workout(w, tz)
            with conn.cursor() as cur:
                cur.executemany(UPSERT, rows)
            workouts += 1
            sets += len(rows)
        if page >= int(data.get("page_count") or 1) or not batch:
            break
    return {"workouts": workouts, "sets": sets}
