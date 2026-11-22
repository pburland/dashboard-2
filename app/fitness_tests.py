"""Fitness tests -> zones (outside review, Card 2).

After each sync, a planned test session with a matched activity is read:

  run LTHR   LTHR = average HR over the last 20 minutes of the 30-minute effort;
             threshold pace = average pace over all 30 minutes (Friel). Found as a ~20-min lap (the watch workout
             splits 10 + 20 min); otherwise approximated from per-mile laps.
  bike FTP   the ~20-min lap with power: FTP = 95% of its average power (indoor,
             KICKR CORE), bike LTHR = 95% of its average HR.
  swim       Friel's 1000 time trial: T-pace = time / 10 per 100 (Patrick chose this
             Nov 23 2026). A 400 + 200 CSS test is still read if that's what he swam.

Validity (rules registry): HR on 90%+ of the effort, a flat run (<= 30 m/mi
climbing), RPE 8+ if a check-in was logged. An invalid test keeps the old zones
and schedules a re-test 7 days later. A run test that moves the top of easy HR by
more than 8 bpm waits for Patrick's OK before it applies.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from app import rules
from app.periodization import zones

MI = 1609.344
YD = 0.9144
KINDS = {"run": "run_lthr", "bike": "bike_ftp", "swim": "swim_css"}
SPORT = {v: k for k, v in KINDS.items()}
NAMES = {"run_lthr": "run test (LTHR)", "bike_ftp": "bike test (FTP)", "swim_css": "swim test (T-pace)"}


def _w(laps, key):
    """Time-weighted mean of a lap field."""
    num = sum((l[key] or 0) * (l["duration_s"] or 0) for l in laps if l[key])
    den = sum(l["duration_s"] or 0 for l in laps if l[key])
    return num / den if den else None


def _hr_coverage(laps) -> float:
    total = sum(l["duration_s"] or 0 for l in laps)
    with_hr = sum(l["duration_s"] or 0 for l in laps if l["avg_hr"])
    return with_hr / total if total else 0.0


def run_result(laps: list[dict]) -> dict | None:
    twenty = [l for l in laps if 1080 <= (l["duration_s"] or 0) <= 1320 and l["distance_m"]]
    if twenty:
        lap = max(twenty, key=lambda l: l["avg_hr"] or 0)
        seg, approx = [lap], False
        i = laps.index(lap)
        before = laps[i - 1] if i > 0 else None
        whole = [before, lap] if before and 480 <= (before["duration_s"] or 0) <= 720 and before["distance_m"] else [lap]
    else:
        # Per-mile laps: the fastest contiguous 27-36 min, then its last ~20 min.
        best = None
        for i in range(len(laps)):
            t = d = 0.0
            for j in range(i, len(laps)):
                t += laps[j]["duration_s"] or 0
                d += laps[j]["distance_m"] or 0
                if t > 36 * 60:
                    break
                if t >= 27 * 60 and d and (best is None or d / t > best[0]):
                    best = (d / t, i, j)
        if not best:
            return None
        window = laps[best[1]:best[2] + 1]
        whole = window
        seg, t = [], 0.0
        for l in reversed(window):
            seg.insert(0, l)
            t += l["duration_s"] or 0
            if t >= 19 * 60:
                break
        approx = True
    hr = _w(seg, "avg_hr")                          # LTHR: the last 20 minutes
    dist = sum(l["distance_m"] or 0 for l in whole)  # threshold pace: the whole 30 minutes (Friel)
    secs = sum(l["duration_s"] or 0 for l in whole)
    if not hr or not dist:
        return None
    return {"lthr": round(hr), "threshold_pace_s_per_mi": round(secs / (dist / MI)), "approx": approx,
            "hr_coverage": round(_hr_coverage(seg), 2)}


def bike_result(laps: list[dict]) -> dict | None:
    twenty = [l for l in laps if 1080 <= (l["duration_s"] or 0) <= 1320 and l["avg_power_w"]]
    if not twenty:
        return None
    lap = max(twenty, key=lambda l: l["avg_power_w"])
    out = {"ftp_w": round(rules.value("ftp_factor") * lap["avg_power_w"]), "test_power_w": round(lap["avg_power_w"]),
           "hr_coverage": round(_hr_coverage([lap]), 2)}
    if lap["avg_hr"]:
        out["bike_lthr"] = round(rules.value("bike_lthr_factor") * lap["avg_hr"])
    return out


def swim_result(laps: list[dict]) -> dict | None:
    for unit, size in (("yd", YD), ("m", 1.0)):           # Friel: one 1000 time trial
        c = [l for l in laps if l["distance_m"] and abs(l["distance_m"] - 1000 * size) <= 0.04 * 1000 * size]
        if c:
            t = min(c, key=lambda l: l["duration_s"])["duration_s"]
            return {"css_s_per_100": round(t / 10, 1), "unit": unit, "method": "1000 time trial (Friel T-pace)",
                    "t1000_s": round(t)}
    for unit, size in (("yd", YD), ("m", 1.0)):           # fallback: a 400 + 200 CSS test
        def near(target):
            c = [l for l in laps if l["distance_m"] and abs(l["distance_m"] - target * size) <= 0.06 * target * size]
            return min(c, key=lambda l: l["duration_s"]) if c else None
        a, b = near(400), near(200)
        if a and b and a["duration_s"] > b["duration_s"]:
            css = (a["duration_s"] - b["duration_s"]) / 2
            return {"css_s_per_100": round(css, 1), "unit": unit, "method": "400 + 200 (CSS)",
                    "t400_s": round(a["duration_s"]), "t200_s": round(b["duration_s"])}
    return None


def invalid_reason(kind: str, result: dict | None, activity: dict | None, rpe: int | None) -> str | None:
    if result is None:
        return {"run_lthr": "couldn't find the 30-minute effort in the laps",
                "bike_ftp": "couldn't find a 20-minute lap with power (was the KICKR paired?)",
                "swim_css": "couldn't find the 1000 time trial (press lap right before and after it)"}[kind]
    if kind in ("run_lthr", "bike_ftp"):
        if kind == "run_lthr" or result.get("bike_lthr"):
            if result.get("hr_coverage", 1) < rules.value("test_hr_coverage"):
                return f"heart rate missing on part of the effort ({int(result['hr_coverage'] * 100)}% covered)"
        if rpe is not None and rpe < rules.value("test_min_rpe"):
            return f"effort logged as RPE {rpe}, below {rules.value('test_min_rpe')}"
    if kind == "run_lthr" and activity and activity.get("distance_m"):
        climb = (activity.get("elevation_gain_m") or 0) / (activity["distance_m"] / MI)
        if climb > rules.value("test_max_climb_m_per_mi"):
            return f"too hilly for a threshold test ({climb:.0f} m of climbing per mile)"
    return None


def _status_for(kind: str, result: dict) -> str:
    """'pending' when a run test moves easy HR a lot (Patrick confirms), else 'applied'."""
    if kind != "run_lthr":
        return "applied"
    old_top = zones.easy_hr_range("run")[1]
    new_top = zones.zone_bounds(result["lthr"], "run")["Z2"][1]
    return "pending" if abs(new_top - old_top) > rules.value("zone_change_confirm_bpm") else "applied"


def _retest(conn, kind: str, when: date, why: str) -> None:
    sport = SPORT[kind]
    src = conn.execute("select title, duration_min, notes from plan_events where sport = %s and kind = 'test' "
                       "order by event_date desc limit 1", (sport,)).fetchone()
    if not src:
        return
    near_race = conn.execute("select 1 from races where status not in ('dropped', 'deferred') "
                             "and race_date between %s and %s", (when, when + timedelta(days=7))).fetchone()
    if near_race:
        return
    conn.execute("""insert into plan_events (event_date, sport, kind, title, duration_min, zone, notes)
                    values (%s, %s, 'test', %s, %s, 'Z4', %s) on conflict (event_date, sport) do nothing""",
                 (when, sport, src["title"], src["duration_min"], f"Re-test ({why}). " + src["notes"]))


def save(conn, kind: str, test_date: date, result: dict | None, reason: str | None, *,
         planned_workout_id=None, activity_id=None, source="auto") -> dict:
    status = "invalid" if reason else _status_for(kind, result)
    row = conn.execute(
        """insert into fitness_tests (kind, test_date, planned_workout_id, activity_id, source, result, status, reason)
           values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s) returning *""",
        (kind, test_date, planned_workout_id, activity_id, source, json.dumps(result or {}), status, reason)).fetchone()
    if status == "invalid":
        _retest(conn, kind, test_date + timedelta(days=7), reason)
    zones.refresh(conn)
    return dict(row)


def process(conn, since: date) -> list[dict]:
    """Read every finished planned test that hasn't been read yet."""
    rows = conn.execute(
        """select w.id, w.plan_date, w.sport, a.id as act_id, a.distance_m, a.elevation_gain_m,
                  (select rpe from check_ins c where c.planned_workout_id = w.id) as rpe
           from planned_workouts w join activities a on a.id = w.activity_id
           where w.plan_date >= %s and w.structure->>'gen_key' like '%%:test#%%'
             and not exists (select 1 from fitness_tests f where f.planned_workout_id = w.id)""",
        (since,)).fetchall()
    out = []
    for r in rows:
        kind = KINDS.get(r["sport"])
        if not kind:
            continue
        laps = conn.execute("select * from laps where activity_id = %s order by lap_index", (r["act_id"],)).fetchall()
        result = {"run_lthr": run_result, "bike_ftp": bike_result, "swim_css": swim_result}[kind](laps)
        reason = invalid_reason(kind, result, r, r["rpe"])
        out.append(save(conn, kind, r["plan_date"], result, reason, planned_workout_id=r["id"],
                        activity_id=r["act_id"]))
    if out:
        conn.commit()
    return out


def record_manual(conn, kind: str, test_date: date, *, lthr=None, threshold_pace_s_per_mi=None, ftp_w=None,
                  test_power_w=None, bike_lthr=None, css_s_per_100=None, unit="yd") -> dict:
    """A result Patrick reads off his watch (Coach chat, or when laps didn't sync)."""
    if kind == "run_lthr":
        result = {"lthr": int(lthr), "threshold_pace_s_per_mi": threshold_pace_s_per_mi and int(threshold_pace_s_per_mi)}
    elif kind == "bike_ftp":
        ftp = ftp_w or (test_power_w and round(rules.value("ftp_factor") * test_power_w))
        result = {"ftp_w": ftp and int(ftp), "bike_lthr": bike_lthr and int(bike_lthr)}
    else:
        result = {"css_s_per_100": float(css_s_per_100), "unit": unit, "method": "entered by hand"}
    result = {k: v for k, v in result.items() if v is not None}
    row = save(conn, kind, test_date, result, None, source="manual")
    conn.commit()
    return row


def decide(conn, test_id: int, apply: bool) -> dict | None:
    """Patrick's answer to a pending test: apply its zones, or keep the old ones."""
    row = conn.execute("update fitness_tests set status = %s where id = %s and status = 'pending' returning *",
                       ("applied" if apply else "rejected", test_id)).fetchone()
    conn.commit()
    zones.refresh(conn)
    return row and dict(row)


def pending(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("select * from fitness_tests where status = 'pending' order by id").fetchall()]


def recent_invalid(conn, today: date) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "select * from fitness_tests where status = 'invalid' and test_date >= %s order by test_date",
        (today - timedelta(days=7),)).fetchall()]


def due_notes(conn, today: date) -> list[str]:
    """Re-test reminders: every 8 weeks after the last applied test of each kind."""
    weeks = rules.value("retest_weeks")
    notes = []
    for kind, t in zones.refresh(conn).items():
        due = t["test_date"] + timedelta(weeks=weeks)
        if due <= today + timedelta(days=7):
            notes.append(f"The {NAMES[kind]} is due around {due:%b %-d} ({weeks} weeks since the last one).")
    return notes


def describe(row: dict) -> str:
    r, kind = row["result"], row["kind"]
    if kind == "run_lthr":
        lo, hi = zones.zone_bounds(r["lthr"], "run")["Z2"]
        return f"LTHR {r['lthr']} bpm, so easy runs {lo}-{hi} bpm"
    if kind == "bike_ftp":
        return ", ".join(x for x in (r.get("ftp_w") and f"FTP {r['ftp_w']} W (indoor)",
                                      r.get("bike_lthr") and f"bike LTHR {r['bike_lthr']} bpm") if x)
    return f"T-pace {zones.fmt_pace(r['css_s_per_100'])} per 100 {r.get('unit', 'yd')}"
