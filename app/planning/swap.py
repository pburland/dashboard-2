"""Swap button: 2-4 ready-made alternatives for a planned session, no chat needed.

Options are built by rules, then each is checked exactly like any other plan
change (health gate, validator, travel, calendar: changes.check). Only options
with no STOP are offered; warnings are shown on the option and accepted by the
tap. Applying goes through changes.propose/apply with source 'swap', so a
substitution marks the old session 'replaced' (linked both ways), the change
log keeps it, Garmin updates in the background, and undo works.

  other sport   the same time, easy, in a sport he can do where he is that day
  shorter       the same session at ~60% of the time (at least 15 min)
  move          the same session on the next free day this week
  skip          take it off today (counts as skipped)
"""
from __future__ import annotations

from datetime import date, timedelta

from app import travel
from app.planning import changes

EASY_TITLE = {"run": "Easy run", "bike": "Easy ride (Z2)", "swim": "Easy swim"}
SPORT_WORD = {"run": "run", "bike": "ride", "swim": "swim", "strength": "lift"}


def _sports_at(conn, d: date) -> tuple[str, ...]:
    place = travel.place_for(travel.load(conn), d)
    if place.away:
        return tuple(place.sports or ())
    return ("run", "bike", "swim", "strength")


def candidates(conn, s: dict, today: date) -> list[dict]:
    """Every option worth checking, as {key, label, actions}."""
    d, sport, mins = s["plan_date"], s["sport"], int(round(s["duration_min"] or 30))
    out = []
    allowed = _sports_at(conn, d)
    if sport in EASY_TITLE:
        for other in ("run", "bike", "swim"):
            if other != sport and other in allowed:
                out.append({"key": f"sport:{other}", "label": f"{EASY_TITLE[other]}, {mins} min instead",
                            "actions": [{"action": "remove", "workout_id": s["id"], "reason": f"swapped for an easy {SPORT_WORD[other]}"},
                                        {"action": "add", "plan_date": str(d), "sport": other,
                                         "title": EASY_TITLE[other], "duration_min": mins, "max_zone": "Z2"}]})
    elif sport == "strength":
        out.append({"key": "mobility", "label": "Mobility + core, 20 min instead",
                    "actions": [{"action": "remove", "workout_id": s["id"], "reason": "swapped for mobility"},
                                {"action": "add", "plan_date": str(d), "sport": "strength",
                                 "title": "Mobility + core (light)", "duration_min": 20, "max_zone": "Z1"}]})
    short = max(15, int(round(mins * 0.6 / 5)) * 5)
    if short < mins:
        mod = {"action": "modify", "workout_id": s["id"], "duration_min": short}
        if s.get("distance_mi"):
            mod["distance_mi"] = round(s["distance_mi"] * short / mins * 2) / 2
        out.append({"key": "shorter", "label": f"Shorter: {short} min", "actions": [mod]})
    ws = d - timedelta(days=d.weekday())
    for k in range(1, 7):
        to = d + timedelta(days=k)
        if to > ws + timedelta(days=6):
            break
        if to >= today and sport in _sports_at(conn, to):
            out.append({"key": f"move:{to}", "label": f"Move to {to:%a %b %-d}",
                        "actions": [{"action": "move", "workout_id": s["id"], "to": str(to)}]})
    out.append({"key": "skip", "label": "Skip today",
                "actions": [{"action": "remove", "workout_id": s["id"], "reason": "skipped with the Swap button"}]})
    return out


def options(conn, workout_id: int, today: date, limit_moves: int = 1) -> dict:
    """The options that pass the checks (at most one move, the earliest that works)."""
    s = conn.execute("select * from planned_workouts where id = %s", (workout_id,)).fetchone()
    if not s or s["status"] != "planned":
        raise changes.ChangeError("only planned sessions can be swapped")
    if s["plan_date"] < today:
        raise changes.ChangeError("that day has passed")
    out, moves = [], 0
    for c in candidates(conn, dict(s), today):
        if c["key"].startswith("move:") and moves >= limit_moves:
            continue
        try:
            ops = changes.resolve(conn, c["actions"], today)
            checked = changes.check(conn, ops, today)
        except changes.ChangeError:
            continue
        if checked.stops:
            continue
        if c["key"].startswith("move:"):
            moves += 1
        out.append({"key": c["key"], "label": c["label"],
                    "warnings": [w["message"] for w in checked.warns]})
    return {"workout_id": workout_id, "title": s["title"], "date": s["plan_date"], "options": out}


def apply(conn, workout_id: int, key: str, today: date) -> dict:
    s = conn.execute("select * from planned_workouts where id = %s", (workout_id,)).fetchone()
    if not s or s["status"] != "planned":
        raise changes.ChangeError("that session already changed; reload Today")
    pick = next((c for c in candidates(conn, dict(s), today) if c["key"] == key), None)
    if not pick:
        raise changes.ChangeError("that option isn't available any more")
    p = changes.propose(conn, pick["actions"], source="swap", reason=f"Swap button: {pick['label']}", today=today)
    if not p["pass"]:
        return {"applied": False, "message": "; ".join(f["message"] for f in p["flags"] if f["severity"] == "stop")}
    return changes.apply(conn, p["proposal_id"], p.get("needs_ack") or [], today) | {"label": pick["label"]}
