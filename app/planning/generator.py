"""Weekly plan generator.

Builds each week from data, never from a model:
  1. the phase's weekly template (phase_days) says which kind of session
     goes on which day;
  2. the health gate decides whether anything is prescribed at all, and
     caps intensity and volume during a return;
  3. travel filters to what can be done where (e.g. run only);
  4. weekly run volume comes from last week (actual, or planned for a
     preview week) times the weekly report's factor, a taper/recovery
     factor, and the 10% ramp limit;
  5. the validator checks the result; a long run over a cap is cut to the
     cap rather than shipped with a STOP.

The coming week is written as the plan; the weeks after it are written as
a preview (``structure.preview``) and rebuilt every Sunday from that week's
report.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from app import db, travel
from app.analysis import overreach
from app.analysis.flags import Severity
from app.analysis.load import estimate_planned_load
from app.analysis.validator import History, PlannedSession, validate_week
from app.health.state import RETURN_LONG_RUN_CAP, MorningSignals, Status, gate, provisional, return_volume
from app.periodization.phases import NoPhaseDefined, phase_for
from app.planning.briefs import brief

MI = 1609.344
EASY_PACE = "10:45-11:30"
EASY_MIN_PER_MI = 11.0
HR_CAP, WALK_OVER = 140, 150
MAX_RAMP = 1.10
LONG_SHARE = 0.33
LONG_CAP_MI = {"base": 14.0, "build": 18.0, "peak": 18.0, "race": 13.0, "return": 8.0, "transition": 3.0}
RECOVERY_EVERY = 4            # 3 weeks building, 1 lighter (Friel)
RECOVERY_FACTOR = 0.8
PHASE_FACTOR = {"race": 0.7, "transition": 0.3}
PREVIEW_FACTOR = 1.08         # previews assume the week goes to plan
MIN_WEEK_MI = 6.0


@dataclass
class Draft:
    date: date
    sport: str
    kind: str
    title: str
    zone: str = "Z2"
    duration_min: float | None = None
    distance_mi: float | None = None
    is_long: bool = False
    heavy_lower: bool = False
    structure: dict = field(default_factory=dict)
    notes: str | None = None


# ── template labels -> sessions ──────────────────────────────────────────
def _part(text: str) -> tuple[str, str] | None:
    """One clause of a template label -> (sport, kind)."""
    t = text.strip().lower()
    if not t or t.startswith("rest") or t in ("hold",) or "carb load" in t:
        return None
    if "brick" in t or "off the bike" in t:
        return ("brick", "brick")
    first = re.split(r"\bor\b", t)[0]       # "easy swim or bike" -> swim
    if "swim" in first:
        return ("swim", "css" if ("css" in t or "race pace" in t) else "easy")
    if "bike" in first or "spin" in first:
        if "long" in t:
            return ("bike", "long")
        if "threshold" in t or "race-pace" in t or "interval" in t:
            return ("bike", "threshold")
        return ("bike", "easy")
    if "run" in first or "shakeout" in first:
        if "shakeout" in t:
            return ("run", "shakeout")
        if "long" in t or "longest" in t:
            return ("run", "long")
        if "tempo" in t or "mp " in t + " " or "threshold" in t:
            return ("run", "tempo")
        if "race-pace" in t or "race pace" in t:
            return ("run", "race_pace")
        if "strides" in t:
            return ("run", "strides")
        return ("run", "easy")
    return None


def parse_endurance(label: str | None) -> list[tuple[str, str]]:
    if not label or label.strip().lower() in ("hold", "rest", "rest or walk"):
        return []
    out = []
    for clause in re.split(r"[+;]", label):
        p = _part(clause)
        if p and p not in out:
            out.append(p)
    return out


def parse_strength(label: str | None) -> tuple[str, bool] | None:
    """-> (kind, heavy_lower)."""
    if not label:
        return None
    t = label.lower()
    if "bodyweight" in t:
        return ("bodyweight", False)
    light = "light" in t or "rpe 6" in t or "mobility" in t or "maintenance" in t
    return ("light" if light else "heavy", ("lower" in t or "full-body" in t) and not light)


# ── volume ───────────────────────────────────────────────────────────────
def _week_run_mi(conn, ws: date) -> tuple[float, float]:
    """(actual, planned) run miles for the week starting ``ws``."""
    a = conn.execute("""select coalesce(sum(distance_m), 0) / %s as mi from activities
                        where sport = 'run' and local_date between %s and %s""",
                     (MI, ws, ws + timedelta(days=6))).fetchone()["mi"]
    p = conn.execute("""select coalesce(sum(distance_mi), 0) as mi from planned_workouts
                        where sport = 'run' and plan_date between %s and %s
                          and status <> 'superseded'""", (ws, ws + timedelta(days=6))).fetchone()["mi"]
    return float(a), float(p)


def reference_week_mi(conn, before: date) -> float:
    """Pre-illness training volume: the best 4-week average run miles in the
    12 weeks before ``before``."""
    weeks = []
    ws = before - timedelta(days=before.weekday()) - timedelta(days=7 * 12)
    for i in range(12):
        weeks.append(_week_run_mi(conn, ws + timedelta(days=7 * i))[0])
    best = max((sum(weeks[i:i + 4]) / 4 for i in range(0, 9)), default=0.0)
    return round(best, 1)


def history(conn, before: date) -> History:
    runs = conn.execute("""select local_date, distance_m from activities where sport = 'run'
                           and local_date >= %s and local_date < %s and distance_m > 0""",
                        (before - timedelta(days=84), before)).fetchall()
    ws = before - timedelta(days=before.weekday())
    weekly = [_week_run_mi(conn, ws - timedelta(days=7 * i))[0] for i in (4, 3, 2, 1)]
    return History([(r["local_date"], r["distance_m"] / MI) for r in runs], weekly)


def _round_half(x: float) -> float:
    return round(x * 2) / 2


# ── one week ─────────────────────────────────────────────────────────────
@dataclass
class WeekPlan:
    week_start: date
    drafts: list[Draft]
    target_run_mi: float         # the week's volume target (carries into next week)
    run_mi: float                # what the sessions add up to (can be less: caps)
    flags: list[dict]
    suppressed: bool
    provisional: bool
    kind: str = ""               # phase kind mid-week


def plan_week(conn, ws: date, *, basis_mi: float, factor: float = 1.0, hist: History | None = None,
              today: date | None = None) -> WeekPlan:
    phases = db.load_phases(conn)
    stops = travel.load(conn)
    races = {r["race_date"]: r for r in db.races(conn)}
    today = today or ws
    episode = db.open_episode(conn, today)
    hist = hist or history(conn, ws)

    def gate_for(d: date):
        ep = provisional(episode, d) if d > today else episode
        return gate(ep, MorningSignals(), d)

    is_prov = any(gate_for(ws + timedelta(days=i)).status is not Status.HOLD
                  and episode is not None and episode.return_started_on is None
                  for i in range(7))

    # Volume target for the week.
    mid = ws + timedelta(days=3)
    try:
        ph_mid = phase_for(phases, mid)
    except NoPhaseDefined:
        return WeekPlan(ws, [], 0.0, 0.0, [{"kind": "no_phase", "severity": "stop",
                                            "message": f"No phase covers {mid}."}], True, False)
    g_mid = gate_for(mid)
    recovery = False
    if g_mid.status is Status.RETURN:
        ep = provisional(episode, mid) if mid > today else episode
        start = (ep or episode).started_on if (ep or episode) else ws
        target = reference_week_mi(conn, start) * return_volume(ep, mid)
    else:
        # 3:1 counted from the end of the latest return phase (or this phase's start).
        ep_now = provisional(episode, mid) if mid > today else episode
        anchor = ph_mid.start_date
        if ep_now and ep_now.return_ends_on and ep_now.return_ends_on < ws + timedelta(days=7):
            anchor = max(anchor, ep_now.return_ends_on + timedelta(days=1)) if ph_mid.kind == "race" else \
                ep_now.return_ends_on + timedelta(days=1)
        week_idx = max(0, (ws - anchor).days // 7)
        f = min(factor, MAX_RAMP) * PHASE_FACTOR.get(ph_mid.kind, 1.0)
        if ph_mid.kind in ("base", "build") and week_idx % RECOVERY_EVERY == RECOVERY_EVERY - 1:
            f *= RECOVERY_FACTOR
            recovery = True
        target = max(basis_mi * f, MIN_WEEK_MI if ph_mid.kind in ("base", "build", "peak") else 0)
        target = min(target, max(basis_mi, MIN_WEEK_MI) * MAX_RAMP)
    open_days = sum(gate_for(ws + timedelta(days=i)).prescriptions_allowed for i in range(7))
    target = _round_half(target * open_days / 7)      # a week that starts mid-hold gets its share

    drafts: list[Draft] = []
    for i in range(7):
        d = ws + timedelta(days=i)
        g = gate_for(d)
        if not g.prescriptions_allowed:
            continue
        try:
            ph = phase_for(phases, d)
        except NoPhaseDefined:
            continue
        place = travel.place_for(stops, d)
        if d in races:
            r = races[d]
            drafts.append(Draft(d, "race", "race", r["name"], zone="race",
                                notes=f"Race day: {r['name']}."))
            continue
        row = next((x for x in ph.days if x[0] == d.weekday()), None)
        if not row:
            continue
        _, strength_label, endurance_label = row
        returning = g.status is Status.RETURN
        for sport, kind in parse_endurance(endurance_label):
            if sport == "brick":
                drafts.append(Draft(d, "bike", "long", "Brick: bike", is_long=False))
                drafts.append(Draft(d, "run", "brick", "Brick: run off the bike", distance_mi=2.0))
            else:
                drafts.append(Draft(d, sport, kind, ""))
        s = parse_strength(strength_label)
        if s:
            kind, heavy = s
            if returning and kind == "heavy":
                kind, heavy = "light", False
            drafts.append(Draft(d, "strength", kind, f"Strength: {strength_label}", heavy_lower=heavy,
                                duration_min=20 if kind == "bodyweight" else (35 if kind == "light" else 45)))
        # Travel: only what can be done there.
        if place.away:
            allowed = set(place.sports or ())
            drafts = [x for x in drafts if x.date != d or x.sport in allowed
                      or (x.sport == "strength" and x.kind == "bodyweight" and allowed)]

    _size_runs(drafts, target, ph_mid.kind, hist, gate_for, recovery)
    _size_other(drafts, ph_mid.kind, gate_for)
    for x in drafts:
        g = gate_for(x.date)
        if g.intensity_ceiling == "Z2" and x.zone not in ("Z1", "Z2", "race"):
            x.zone, x.kind = "Z2", ("easy" if x.sport in ("run", "bike", "swim") else x.kind)
        _finish(x, g.status is Status.RETURN, is_prov and x.date > today, travel.place_for(stops, x.date))

    # Validate; cut any long run the rules stop, then re-check.
    sessions = [_as_session(x) for x in drafts if x.sport != "race" and x.duration_min]
    verdict = validate_week(sessions, hist, gate_for)
    for idx, fl in verdict.flags.items():
        for f in fl:
            if f.severity is Severity.STOP and f.kind == "session_load_share" and sessions[idx].is_long:
                x = next(x for x in drafts if _as_session(x) == sessions[idx])
                x.distance_mi = _round_half((x.distance_mi or 2) * 0.85)
                x.duration_min = round(x.distance_mi * EASY_MIN_PER_MI)
            if f.severity is Severity.STOP and f.kind in ("long_run_jump", "long_run_cap"):
                cap = f.data.get("suggested_cap_mi") if f.data else None
                if cap is None:
                    m = re.search(r"over the ([\d.]+) mi cap", f.message)
                    cap = float(m.group(1)) if m else None
                if cap:
                    x = next(x for x in drafts if _as_session(x) == sessions[idx])
                    x.distance_mi = _round_half(min(x.distance_mi or cap, cap) - 0.25) or 1.0
                    x.duration_min = round(x.distance_mi * EASY_MIN_PER_MI)
                    _finish(x, gate_for(x.date).status is Status.RETURN, is_prov and x.date > today,
                            travel.place_for(stops, x.date))
    sessions = [_as_session(x) for x in drafts if x.sport != "race" and x.duration_min]
    verdict = validate_week(sessions, hist, gate_for) if sessions else None
    flags = []
    if verdict:
        returning_week = g_mid.status is Status.RETURN
        for idx, fl in verdict.flags.items():
            for f in fl:
                flags.append({"date": sessions[idx].date, "title": sessions[idx].title, "kind": f.kind,
                              "severity": f.severity.value, "message": f.message})
        for f in verdict.week_flags:
            if returning_week and f.kind == "weekly_ramp":
                continue        # the return ramp (50% -> 90%) governs instead
            flags.append({"date": None, "title": None, "kind": f.kind,
                          "severity": f.severity.value, "message": f.message})
        for x in drafts:
            fl = [f for f in flags if f["date"] == x.date and f["title"] == x.title]
            if fl:
                x.structure["flags"] = [{k: v for k, v in f.items() if k not in ("date", "title")} for f in fl]
    if open_days < 5:     # a few sessions in a part-week: load shares mean nothing
        flags = [f for f in flags if f["kind"] != "session_load_share"]
        for x in drafts:
            if "flags" in x.structure:
                x.structure["flags"] = [f for f in x.structure["flags"] if f["kind"] != "session_load_share"]
    run_mi = sum(x.distance_mi or 0 for x in drafts if x.sport == "run")
    return WeekPlan(ws, drafts, target, round(run_mi, 1), flags, not drafts, is_prov, ph_mid.kind)


def _as_session(x: Draft) -> PlannedSession:
    return PlannedSession(x.date, x.sport, x.title, x.duration_min or 0, x.zone if x.zone != "race" else "Z3",
                          x.distance_mi, x.is_long, x.heavy_lower)


def _size_runs(drafts: list[Draft], target: float, kind: str, hist: History, gate_for,
               recovery: bool = False) -> None:
    runs = [x for x in drafts if x.sport == "run"]
    if not runs:
        return
    fixed = sum(x.distance_mi or 0 for x in runs if x.kind == "brick")
    longs = [x for x in runs if x.kind == "long"]
    rest = [x for x in runs if x.kind not in ("long", "brick")]
    left = max(0.0, target - fixed)
    for x in longs:
        g = gate_for(x.date)
        recent = [mi for d, mi in hist.runs if x.date - timedelta(days=28) <= d < x.date]
        prev = max(recent, default=0.0)
        returning = g.status is Status.RETURN
        cap = LONG_CAP_MI.get("return" if returning else kind, 14.0)
        if prev:
            cap = min(cap, max(prev * MAX_RAMP, prev + overreach.LONG_RUN_JUMP_FREE_MI))
        if returning and hist.runs:
            cap = min(cap, max(mi for _, mi in hist.runs) * RETURN_LONG_RUN_CAP)
        if kind in ("base", "build", "peak") and not returning:
            # Grow every building week; drop back in a recovery week. After
            # a race or a break, restart near 85% of the last 8 weeks' longest.
            older = [mi for d, mi in hist.runs if x.date - timedelta(days=56) <= d < x.date]
            want = prev * RECOVERY_FACTOR if recovery else max(cap, 0.85 * max(older, default=0.0))
        else:
            want = left * LONG_SHARE
        x.distance_mi = max(2.0, _round_half(min(want, cap if not recovery else want)))
        x.is_long = True
        left -= x.distance_mi
    longest = max((x.distance_mi for x in longs), default=None)
    for x in rest:
        share = left / len(rest) if rest else 0
        lo, hi = {"shakeout": (1.5, 3.0), "race_pace": (2.0, 5.0), "tempo": (3.0, 7.0)}.get(x.kind, (2.0, 8.0))
        if longest:
            hi = min(hi, longest * 0.75)        # no other run rivals the long run
        x.distance_mi = _round_half(min(hi, max(lo, share)))
    for x in runs:
        x.duration_min = round((x.distance_mi or 0) * EASY_MIN_PER_MI)
        if x.kind in ("tempo", "race_pace"):
            x.zone = "Z3"


SWIM_MIN = {"return": 25, "base": 35, "build": 45, "peak": 45, "race": 25, "transition": 30}
BIKE_MIN = {"return": 35, "base": 50, "build": 60, "peak": 60, "race": 35, "transition": 40}
LONG_BIKE_MIN = {"base": 90, "build": 120, "peak": 150, "race": 60}


def _size_other(drafts: list[Draft], kind: str, gate_for) -> None:
    for x in drafts:
        returning = gate_for(x.date).status is Status.RETURN
        k = "return" if returning else kind
        if x.sport == "swim":
            x.duration_min = SWIM_MIN.get(k, 35)
            x.zone = "Z3" if x.kind == "css" else "Z2"
        elif x.sport == "bike":
            x.duration_min = LONG_BIKE_MIN.get(k, 60) if x.kind == "long" else BIKE_MIN.get(k, 45)
            x.zone = "Z4" if x.kind == "threshold" else "Z2"
            x.is_long = x.kind == "long" and not returning


TITLES = {
    ("run", "easy"): "Easy run", ("run", "long"): "Long run", ("run", "strides"): "Easy run + strides",
    ("run", "tempo"): "Tempo run", ("run", "race_pace"): "Run with race-pace miles",
    ("run", "brick"): "Brick: run off the bike", ("run", "shakeout"): "Shakeout run",
    ("swim", "easy"): "Easy swim", ("swim", "css"): "Swim CSS set",
    ("bike", "easy"): "Easy ride (Z2)", ("bike", "long"): "Long ride", ("bike", "threshold"): "Bike threshold",
}


def _finish(x: Draft, returning: bool, prov: bool, place) -> None:
    if x.sport == "race":
        return
    if x.sport != "strength":
        title = TITLES.get((x.sport, x.kind), x.title or x.sport.title())
        if x.title.startswith("Brick: bike"):
            title = "Brick: bike"
        if returning and x.sport == "run":
            title = title.replace("Easy run", "Easy run/walk").replace("Long run", "Long run/walk")
        x.title = title
    st = {}
    if x.sport == "run":
        st.update(pace=EASY_PACE if x.zone in ("Z1", "Z2") else "by feel, comfortably hard",
                  hr_avg_max=HR_CAP if x.zone in ("Z1", "Z2") else None)
        if returning:
            st.update(walk_if_hr_over=WALK_OVER, walk_breaks="allowed")
        st = {k: v for k, v in st.items() if v is not None}
    st["brief"] = brief(x.sport, x.kind, zone=x.zone, distance_mi=x.distance_mi, duration_min=x.duration_min,
                        hr_cap=st.get("hr_avg_max"), walk_over=st.get("walk_if_hr_over"),
                        returning=returning, provisional=prov,
                        place_note=(f"In {place.name}." if place.away and place.sports else ""))
    if prov:
        st["provisional"] = True
    x.structure = {**x.structure, **st}


# ── several weeks, written to the database ───────────────────────────────
def generate(conn, first_ws: date, weeks: int = 3, factor: float = 1.0, today: date | None = None) -> list[WeekPlan]:
    """Plan ``weeks`` weeks from ``first_ws``. The first is the plan; the rest
    are previews. Replaces earlier generator rows that nothing has matched."""
    today = today or first_ws
    hist = history(conn, first_ws)
    actual, planned = _week_run_mi(conn, first_ws - timedelta(days=7))
    basis = actual if actual > 0 else planned
    out: list[WeekPlan] = []
    training_basis = basis          # last week before a taper or recovery
    for w in range(weeks):
        ws = first_ws + timedelta(days=7 * w)
        if out and out[-1].kind in ("race", "transition"):
            basis = max(basis, training_basis * RECOVERY_FACTOR)    # back to training after a race
        wp = plan_week(conn, ws, basis_mi=basis, factor=factor if w == 0 else PREVIEW_FACTOR, hist=hist, today=today)
        _write(conn, wp, preview=w > 0, today=today)
        out.append(wp)
        basis = wp.target_run_mi or basis
        if wp.kind in ("base", "build", "peak"):
            training_basis = wp.target_run_mi
        hist = History(hist.runs + [(x.date, x.distance_mi) for x in wp.drafts
                                    if x.sport == "run" and x.distance_mi],
                       hist.weekly_run_mi[1:] + [wp.run_mi])
    return out


def _write(conn, wp: WeekPlan, preview: bool, today: date) -> None:
    """Replace this week's unmatched generator rows from today on. The past
    is never rewritten."""
    end = wp.week_start + timedelta(days=6)
    start = max(wp.week_start, today)
    conn.execute("""delete from planned_workouts where plan_date between %s and %s
                    and source = 'generator' and status = 'planned' and activity_id is null""",
                 (start, end))
    coach_days = {r["plan_date"] for r in conn.execute(
        "select distinct plan_date from planned_workouts where plan_date between %s and %s and source <> 'generator'",
        (wp.week_start, end)).fetchall()}
    phases = db.load_phases(conn)
    for x in wp.drafts:
        if x.date < today or x.date in coach_days:
            continue                  # a hand-written session wins for that day
        try:
            ph_id = phase_for(phases, x.date).id
        except NoPhaseDefined:
            ph_id = None
        st = {**x.structure, **({"preview": True} if preview else {})}
        conn.execute(
            """insert into planned_workouts (plan_date, sport, title, phase_id, duration_min, distance_mi,
                   max_zone, is_long, structure, est_load, source, notes)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'generator', %s)""",
            (x.date, x.sport, x.title, ph_id, x.duration_min, x.distance_mi, x.zone if x.zone != "race" else None,
             x.is_long, json.dumps(st, default=str),
             round(estimate_planned_load(x.duration_min, x.zone), 1) if x.duration_min and x.zone in
             ("Z1", "Z2", "Z3", "Z4") else None, x.notes))
