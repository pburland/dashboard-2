"""Season checkpoints toward the 70.3 (Nov 5 2026 roadmap): what the weekly
report checks, and the Jan 31 go/no-go for Puerto Rico vs a later 70.3.

Each checkpoint compares the longest sessions in the 4 weeks before the report
with a target. Swim distance is the longest swim session (Garmin can't tell
whether it was continuous). Resting HR is the 7-day average vs the baseline.
"""
from __future__ import annotations

from datetime import date, timedelta

MI = 1609.344
YD = 0.9144

CHECKPOINTS = [
    {"date": date(2026, 12, 20), "name": "Dec 20 checkpoint",
     "targets": {"week_hours": 7.0}},
    {"date": date(2027, 1, 31), "name": "Jan 31 go/no-go for 70.3 Puerto Rico",
     "targets": {"long_ride_min": 180, "long_run_mi": 9.0, "swim_yd": 2000},
     "if_missed": "Consider switching to 70.3 Texas (Apr 4) or Oceanside (Apr 3) for three more weeks of build; "
                  "check Puerto Rico's transfer policy."},
    {"date": date(2027, 2, 21), "name": "Feb 21 checkpoint",
     "targets": {"long_ride_min": 210, "long_run_mi": 11.0, "swim_yd": 2000}},
]
LABELS = {"week_hours": ("best training week", "h"), "long_ride_min": ("longest ride", "min"),
          "long_run_mi": ("longest run", "mi"), "swim_yd": ("longest swim", "yd")}


def progress(conn, through: date) -> dict:
    """Best values in the 4 weeks ending ``through``."""
    start = through - timedelta(days=27)
    acts = conn.execute(
        """select local_date, sport, distance_m, duration_s from activities
           where local_date between %s and %s""", (start, through)).fetchall()
    by_week: dict[date, float] = {}
    for a in acts:
        ws = a["local_date"] - timedelta(days=a["local_date"].weekday())
        by_week[ws] = by_week.get(ws, 0) + (a["duration_s"] or 0) / 3600
    strength = conn.execute(
        """select performed_on, count(distinct workout_id) as n from strength_sets
           where performed_on between %s and %s group by performed_on""", (start, through)).fetchall()
    for s in strength:                         # ~45 min per lifting session counts toward the week
        ws = s["performed_on"] - timedelta(days=s["performed_on"].weekday())
        by_week[ws] = by_week.get(ws, 0) + 0.75 * s["n"]
    longest = lambda sport, f: max((f(a) for a in acts if a["sport"] == sport), default=0.0)
    return {
        "week_hours": round(max(by_week.values(), default=0.0), 1),
        "long_ride_min": round(longest("bike", lambda a: (a["duration_s"] or 0) / 60)),
        "long_run_mi": round(longest("run", lambda a: (a["distance_m"] or 0) / MI), 1),
        "swim_yd": round(longest("swim", lambda a: (a["distance_m"] or 0) / YD)),
    }


def rhr_vs_baseline(conn, through: date) -> tuple[float | None, float | None]:
    r = conn.execute("""select avg(resting_hr) as a from recovery where day between %s and %s
                        and resting_hr is not null""", (through - timedelta(days=6), through)).fetchone()
    base = (conn.execute("select resting_hr_baseline from profile where id = 1").fetchone() or {}).get(
        "resting_hr_baseline")
    return (round(r["a"], 1) if r and r["a"] else None), base


def check(conn, today: date) -> dict | None:
    """The next checkpoint (or one passed in the last 7 days), with status."""
    cp = next((c for c in CHECKPOINTS if c["date"] >= today - timedelta(days=7)), None)
    if not cp:
        return None
    through = min(today, cp["date"])
    got = progress(conn, through)
    rows = []
    for k, target in cp["targets"].items():
        label, unit = LABELS[k]
        rows.append({"what": label, "target": target, "unit": unit, "now": got[k], "met": got[k] >= target})
    rhr, base = rhr_vs_baseline(conn, through)
    rhr_ok = None if rhr is None or base is None else rhr <= base + 5
    due = cp["date"] <= today
    met = all(r["met"] for r in rows) and rhr_ok is not False
    return {"name": cp["name"], "date": cp["date"], "due": due, "met": met, "rows": rows,
            "rhr": rhr, "rhr_baseline": base, "rhr_ok": rhr_ok,
            "advice": cp.get("if_missed") if due and not met else None}


def markdown(c: dict | None) -> str:
    if not c:
        return ""
    head = f"**{c['name']}** ({c['date']:%b %-d})" + (": met" if c["due"] and c["met"] else
                                                       ": not met" if c["due"] else "")
    lines = [head]
    for r in c["rows"]:
        lines.append(f"- {r['what']}: {r['now']:g} {r['unit']} of {r['target']:g} {'✓' if r['met'] else '…'}")
    if c["rhr"] is not None and c["rhr_baseline"]:
        lines.append(f"- resting HR (7-day): {c['rhr']:g} vs baseline {c['rhr_baseline']:g} "
                     f"{'✓' if c['rhr_ok'] else '(high: hold volume)'}")
    if c["advice"]:
        lines.append(f"_{c['advice']}_")
    return "\n".join(lines)
