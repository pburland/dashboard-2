"""Weekly plan generator.

Builds each week from data, never from a model:
  1. the phase's weekly template (phase_days) says which kind of endurance
     session goes on which day;
  2. the health gate (episode + recent check-ins) decides whether anything
     is prescribed and caps intensity/volume during a return or caution;
  3. weekly run volume = last week x the report's factor, a taper/recovery
     factor, the 10% ramp cap, clamped to phase_volume_targets;
  4. the long run follows the ladder (``long_run_ladder``): +10% or +1 mi a
     building week, a cutback every 4th, peak 2-3 weeks before the A race,
     then taper;
  5. sessions go into real free time (training windows minus the work
     calendar); travel moves key sessions and drops easy ones;
  6. strength is placed by Friel's concurrent rules (friel.CONCURRENT_RULES);
  7. the validator checks the week; a STOP is relaxed (shorter long run,
     key work made easy, volume cut) up to 3 times, then the offending
     session is dropped and the week flagged for review.

Writes go through app/planning/sync.py and changes.py: unchanged sessions
are left alone, changed ones are superseded (never deleted) with a
plan_changes row.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from app import db, travel
from app.analysis import overreach
from app.analysis.flags import Severity
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
# Run long-run caps by phase kind for a 70.3 build (a marathon block would raise build/peak).
LONG_CAP_MI = {"base": 12.0, "build": 13.0, "peak": 13.0, "race": 8.0, "return": 8.0, "transition": 3.0}
# Longest run worth doing before a race, by distance (conservative).
PEAK_LONG_MI = {"70.3": 12.5, "140.6": 18.0, "marathon": 20.0, "half": 12.0}
RECOVERY_EVERY = 4            # 3 weeks building, 1 lighter (Friel)
RECOVERY_FACTOR = 0.8
PHASE_FACTOR = {"race": 0.7, "transition": 0.3}
PREVIEW_FACTOR = 1.08         # previews assume the week goes to plan
MIN_WEEK_MI = 6.0
STRENGTH_PER_WEEK = {"prep": 3, "base": 3, "build": 2, "peak": 1, "race": 0, "transition": 1, "return": 2}
KEY_KINDS = {("run", "long"), ("run", "tempo"), ("run", "race_pace"), ("bike", "long"),
             ("bike", "threshold"), ("swim", "css")}
RELAX_ATTEMPTS = 3


@dataclass(eq=False)
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
    label: str = ""

    @property
    def is_key(self) -> bool:
        return (self.sport, self.kind) in KEY_KINDS or self.sport == "race" or self.label == "brick"


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
    light = "light" in t or "rpe 6" in t or "mobility" in t or "maintenance" in t or "moderate" in t
    return ("light" if light else "heavy", ("lower" in t or "full-body" in t) and not light)


# ── long-run ladder ──────────────────────────────────────────────────────
def next_long(prev_max: float, week_index: int, weeks_to_race: int | None, peak: float) -> float:
    """Long run for one week. ``prev_max``: longest run in the previous 4
    weeks; ``week_index``: building weeks so far (0-based); ``weeks_to_race``:
    0 in race week. Growth never exceeds +10% or +1 mi over ``prev_max`` (the
    validator's free growth), so the validator never stops it."""
    if weeks_to_race is not None and weeks_to_race <= 1:
        return round(max(3.0, peak * (0.6 if weeks_to_race == 1 else 0.45)) * 2) / 2
    grow = max(prev_max * MAX_RAMP, prev_max + overreach.LONG_RUN_JUMP_FREE_MI)
    if weeks_to_race is not None and weeks_to_race in (2, 3):
        target = min(grow, peak)              # peak weeks: no cutback this close to the race
    elif week_index % RECOVERY_EVERY == RECOVERY_EVERY - 1:
        target = prev_max * RECOVERY_FACTOR
    else:
        target = min(grow, peak)
    return max(2.0, round(target * 2) / 2)


def long_run_ladder(start: date, race_date: date, distance: str, current_longest: float) -> list[tuple[date, float]]:
    """Week-by-week long run from ``start`` (a Monday) through race week."""
    peak = PEAK_LONG_MI.get(distance, 12.0)
    out, window = [], [current_longest]
    ws, i = start, 0
    race_ws = race_date - timedelta(days=race_date.weekday())
    while ws <= race_ws:
        to_race = (race_ws - ws).days // 7
        mi = next_long(max(window[-4:]), i, to_race, peak)
        out.append((ws, mi))
        window.append(mi)
        ws += timedelta(days=7)
        i += 1
    return out


# ── volume ───────────────────────────────────────────────────────────────
def _week_run_mi(conn, ws: date) -> tuple[float, float]:
    """(actual, planned) run miles for the week starting ``ws``."""
    a = conn.execute("""select coalesce(sum(distance_m), 0) / %s as mi from activities
                        where sport = 'run' and local_date between %s and %s""",
                     (MI, ws, ws + timedelta(days=6))).fetchone()["mi"]
    p = conn.execute("""select coalesce(sum(distance_mi), 0) as mi from planned_workouts
                        where sport = 'run' and plan_date between %s and %s
                          and status in ('planned', 'done')""", (ws, ws + timedelta(days=6))).fetchone()["mi"]
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


def volume_bounds(conn, kind: str) -> dict[str, tuple[float, float]]:
    rows = conn.execute("select sport, min_hours, max_hours from phase_volume_targets where phase_kind = %s",
                        (kind,)).fetchall()
    return {r["sport"]: (r["min_hours"], r["max_hours"]) for r in rows}


def _round_half(x: float) -> float:
    return round(x * 2) / 2


def day_gate(conn, today: date, since: date):
    """Health gate for any day: the episode as of ``today`` (previewing
    clearance on the expected date for future days) plus recent check-ins.
    The generator, chat edits and rebases all judge days with this."""
    from app import checkins
    episode = db.open_episode(conn, today)
    recent_checkins = checkins.recent(conn, since - timedelta(days=checkins.CAUTION_DAYS))

    def gate_for(d: date):
        ep = provisional(episode, d) if d > today else episode
        why = checkins.caution_reason(recent_checkins, d) if d >= today else None
        return gate(ep, MorningSignals(checkin_reason=why), d)
    return gate_for


# ── calendar ─────────────────────────────────────────────────────────────
class Calendar:
    """Free time per day: training windows minus work events (home only)."""

    def __init__(self, conn, start: date, end: date, use_calendar: bool = True, busy: list | None = None):
        from app.integrations import calendar
        self.stops = travel.load(conn)
        self.busy: list = busy or []
        self.available = busy is not None
        if use_calendar and busy is None:
            try:
                self.busy = calendar.busy(start, end, ZoneInfo(travel.home().tz_name))
                self.available = True
            except Exception:
                pass

    def free_minutes(self, d: date) -> int:
        """Longest free block that day, in minutes."""
        from app.planning import timing
        place = travel.place_for(self.stops, d)
        slots = timing.free_slots(d, ZoneInfo(place.tz_name), [] if place.away else self.busy, place.away)
        return int(max(((e - s).total_seconds() / 60 for s, e in slots), default=0))

    def fingerprint(self, start: date, end: date) -> str:
        blocks = [(s.isoformat(), e.isoformat()) for s, e in self.busy if start <= s.date() <= end]
        return hashlib.sha1(json.dumps(blocks).encode()).hexdigest()[:12]


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
    inputs: dict = field(default_factory=dict)
    needs_review: list[str] = field(default_factory=list)

    @property
    def inputs_hash(self) -> str:
        return hashlib.sha1(json.dumps(self.inputs, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _a_race(conn, d: date) -> dict | None:
    rows = [r for r in db.races(conn) if r["race_date"] >= d]
    return min(rows, key=lambda r: (r["priority"], r["race_date"])) if rows else None


def plan_week(conn, ws: date, *, basis_mi: float, factor: float = 1.0, hist: History | None = None,
              today: date | None = None, cal: Calendar | None = None,
              fixed: list[dict] | None = None, missed_keys: list[str] | None = None) -> WeekPlan:
    """Draft one week. ``fixed``: rows Patrick changed himself (kept as they
    are). ``missed_keys``: gen_keys of key sessions missed earlier this week,
    to be re-placed on a remaining day if a compliant one exists."""
    phases = db.load_phases(conn)
    stops = travel.load(conn)
    races = {r["race_date"]: r for r in db.races(conn)}
    today = today or ws
    episode = db.open_episode(conn, today)
    hist = hist or history(conn, ws)
    gate_for = day_gate(conn, today, ws - timedelta(days=7))
    cal = cal or Calendar(conn, ws, ws + timedelta(days=6), use_calendar=False)
    fixed = fixed or []

    is_prov = any(gate_for(ws + timedelta(days=i)).status is not Status.HOLD
                  and episode is not None and episode.return_started_on is None
                  for i in range(7))

    mid = ws + timedelta(days=3)
    try:
        ph_mid = phase_for(phases, mid)
    except NoPhaseDefined:
        return WeekPlan(ws, [], 0.0, 0.0, [{"kind": "no_phase", "severity": "stop",
                                            "message": f"No phase covers {mid}."}], True, False)
    g_mid = gate_for(mid)
    ep_mid = provisional(episode, mid) if mid > today else episode
    back = (ep_mid.return_ends_on + timedelta(days=1)) if ep_mid and ep_mid.return_ends_on else None
    weeks_in = max(0, (ws - back).days // 7) if back and back <= ws + timedelta(days=6) else 8
    recovery = False
    kind = "return" if g_mid.status is Status.RETURN else ph_mid.kind
    bounds = volume_bounds(conn, kind)
    if g_mid.status is Status.RETURN:
        start = ep_mid.started_on if ep_mid else ws
        target = reference_week_mi(conn, start) * return_volume(ep_mid, mid)
        week_idx = 0
    else:
        # 3:1 counted from the end of the latest return phase (or this phase's start).
        anchor = ph_mid.start_date
        if ep_mid and ep_mid.return_ends_on and ep_mid.return_ends_on < ws + timedelta(days=7):
            anchor = max(anchor, ep_mid.return_ends_on + timedelta(days=1)) if ph_mid.kind == "race" else \
                ep_mid.return_ends_on + timedelta(days=1)
        week_idx = max(0, (ws - anchor).days // 7)
        f = min(factor, MAX_RAMP) * PHASE_FACTOR.get(ph_mid.kind, 1.0)
        if ph_mid.kind in ("base", "build") and week_idx % RECOVERY_EVERY == RECOVERY_EVERY - 1:
            f *= RECOVERY_FACTOR
            recovery = True
        target = max(basis_mi * f, MIN_WEEK_MI if ph_mid.kind in ("base", "build", "peak") else 0)
        target = min(target, max(basis_mi, MIN_WEEK_MI) * MAX_RAMP)      # the 10% ramp is a hard cap
    if "run" in bounds:
        lo, hi = (h * 60 / EASY_MIN_PER_MI for h in bounds["run"])
        target = min(max(target, lo if g_mid.status is not Status.RETURN else 0), hi)
    open_days = sum(gate_for(ws + timedelta(days=i)).prescriptions_allowed for i in range(7))
    target = _round_half(target * open_days / 7)      # a week that starts mid-hold gets its share

    # Endurance sessions (and template strength) from the phase template.
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
        if d in races:
            r = races[d]
            drafts.append(Draft(d, "race", "race", r["name"], zone="race", notes=f"Race day: {r['name']}."))
            continue
        row = next((x for x in ph.days if x[0] == d.weekday()), None)
        if not row:
            continue
        _, strength_label, endurance_label = row
        parts = parse_endurance(endurance_label)
        long_brick = False
        if ("brick", "brick") in parts:
            long_brick = ("bike", "long") in parts or "long" in (endurance_label or "").lower()
            parts = [p for p in parts if p[0] != "bike"]
        for sport, k in parts:
            if sport == "brick":
                drafts.append(Draft(d, "bike", "long" if long_brick else "easy", "Brick: bike", label="brick"))
                drafts.append(Draft(d, "run", "brick", "Brick: run off the bike", distance_mi=2.0))
            else:
                drafts.append(Draft(d, sport, k, ""))
        if strength_label:
            drafts.append(Draft(d, "strength", "template", f"Strength: {strength_label}", label=strength_label))
    _key_ids(drafts)

    # Sessions Patrick moved himself win; the generator doesn't re-add them.
    fixed_keys = {(r.get("structure") or {}).get("gen_key") for r in fixed} - {None}
    drafts = [x for x in drafts if x.structure.get("gen_key") not in fixed_keys]

    # Sizing: runs by the ladder and volume, other sports by phase.
    a_race = _a_race(conn, ws)
    weeks_to_race = ((a_race["race_date"] - timedelta(days=a_race["race_date"].weekday()) - ws).days // 7
                     if a_race else None)
    peak = PEAK_LONG_MI.get(a_race["distance"], 12.0) if a_race else 12.0
    _size_runs(drafts, target, kind, hist, gate_for, recovery, week_idx, weeks_to_race, peak)
    _size_other(drafts, kind, gate_for, weeks_in, recovery, bounds)

    # Placement: travel, missed key sessions, free time, strength rules, daily cap.
    review: list[str] = []
    drafts = _place(drafts, ws, today, gate_for, cal, stops, missed_keys or [], review)
    drafts = _place_strength(drafts, ws, today, kind, gate_for, stops, returning=g_mid.status is Status.RETURN)
    cap = ((conn.execute("select daily_minutes from profile where id = 1").fetchone() or {})
           .get("daily_minutes") or {}).get("default", 210)
    _daily_cap(drafts, cap)

    for x in drafts:
        g = gate_for(x.date)
        if g.intensity_ceiling == "Z2" and x.zone not in ("Z1", "Z2", "race"):
            x.zone, x.kind = "Z2", ("easy" if x.sport in ("run", "bike", "swim") else x.kind)
        _finish(x, g.status is Status.RETURN, is_prov and x.date > today, travel.place_for(stops, x.date))

    flags, drafts = _validate_and_relax(drafts, hist, gate_for, review, today, stops, is_prov)
    if open_days < 5:     # a few sessions in a part-week: load shares mean nothing
        flags = [f for f in flags if f["kind"] != "session_load_share"]
        for x in drafts:
            if "flags" in x.structure:
                x.structure["flags"] = [f for f in x.structure["flags"] if f["kind"] != "session_load_share"]
                if not x.structure["flags"]:
                    x.structure.pop("flags")
    if g_mid.status is Status.RETURN:
        flags = [f for f in flags if f["kind"] != "weekly_ramp"]     # the return ramp governs instead
    run_mi = sum(x.distance_mi or 0 for x in drafts if x.sport == "run")
    days = [ws + timedelta(days=i) for i in range(7)]
    inputs = {"week": ws, "kind": kind, "basis": round(basis_mi, 1), "factor": round(factor, 2),
              "gates": [gate_for(d).status.value for d in days],
              "reasons": [list(gate_for(d).reasons)[:1] for d in days],
              "travel": [travel.place_for(stops, d).name for d in days],
              "fixed": sorted(fixed_keys), "missed": sorted(missed_keys or []),
              "calendar": cal.fingerprint(ws, ws + timedelta(days=6)) if cal.available else None}
    return WeekPlan(ws, drafts, target, round(run_mi, 1), flags, not drafts, is_prov, ph_mid.kind,
                    inputs, review)


def _key_ids(drafts: list[Draft]) -> None:
    """A stable identity per session within its week (sport:kind#n), used to
    match re-plans to existing rows and to respect Patrick's own moves."""
    seen: dict[str, int] = {}
    for x in drafts:
        if x.sport == "strength":
            continue                     # numbered after placement
        base = f"{x.sport}:{'brick' if x.label == 'brick' else x.kind}"
        seen[base] = seen.get(base, 0) + 1
        x.structure["gen_key"] = f"{base}#{seen[base]}"


def _as_session(x: Draft) -> PlannedSession:
    return PlannedSession(x.date, x.sport, x.title, x.duration_min or 0, x.zone if x.zone != "race" else "Z3",
                          x.distance_mi, x.is_long, x.heavy_lower)


def _size_runs(drafts: list[Draft], target: float, kind: str, hist: History, gate_for,
               recovery: bool, week_idx: int, weeks_to_race: int | None, peak: float) -> None:
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
        if kind in ("base", "build", "peak", "race") and not returning:
            # The ladder. After a race or a break, restart near 85% of the last 8 weeks' longest.
            older = [mi for d, mi in hist.runs if x.date - timedelta(days=56) <= d < x.date]
            base_prev = prev if recovery else max(prev, 0.85 * max(older, default=0.0))
            want = next_long(base_prev, week_idx, weeks_to_race, peak)
            if not recovery:
                want = min(want, cap)
        else:
            want = min(left * LONG_SHARE, cap)
        x.distance_mi = max(2.0, _round_half(want))
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
# Long ride: starts at 75 min, +15 min a building week, up to the phase cap.
LONG_BIKE_START, LONG_BIKE_STEP = 75, 15
LONG_BIKE_CAP = {"base": 150, "build": 180, "peak": 210, "race": 60, "transition": 60}


def _size_other(drafts: list[Draft], kind: str, gate_for, weeks_in: int, recovery: bool,
                bounds: dict[str, tuple[float, float]]) -> None:
    for x in drafts:
        returning = gate_for(x.date).status is Status.RETURN
        k = "return" if returning else kind
        if x.sport == "swim":
            x.duration_min = SWIM_MIN.get(k, 35)
            x.zone = "Z3" if x.kind == "css" else "Z2"
        elif x.sport == "bike":
            if x.kind == "long" and not returning:
                build = min(LONG_BIKE_CAP.get(k, 120), LONG_BIKE_START + LONG_BIKE_STEP * weeks_in)
                x.duration_min = round(build * (0.75 if recovery else 1.0) / 5) * 5
            else:
                x.duration_min = BIKE_MIN.get(k, 45)
            x.zone = "Z4" if x.kind == "threshold" else "Z2"
            x.is_long = x.kind == "long" and not returning
    # Weekly ceilings per sport (phase_volume_targets): trim the easy sessions first.
    for sport in ("bike", "swim"):
        if sport not in bounds:
            continue
        cap = bounds[sport][1] * 60
        items = sorted([x for x in drafts if x.sport == sport], key=lambda x: (x.is_key, x.duration_min or 0))
        total = sum(x.duration_min or 0 for x in items)
        for x in items:
            if total <= cap:
                break
            cut = min(total - cap, (x.duration_min or 0) - 20)
            if cut > 0:
                x.duration_min -= cut
                total -= cut


def _allowed(x: Draft, d: date, gate_for, stops) -> bool:
    if not gate_for(d).prescriptions_allowed:
        return False
    place = travel.place_for(stops, d)
    if not place.away:
        return True
    ok = set(place.sports or ())
    return x.sport in ok or (x.sport == "strength" and bool(ok))


def _place(drafts: list[Draft], ws: date, today: date, gate_for, cal: Calendar, stops,
           missed_keys: list[str], review: list[str]) -> list[Draft]:
    """Travel, missed key sessions and free time. Key sessions move to the
    nearest compliant day (weekends first for long ones); easy sessions that
    can't happen where planned are dropped."""
    days = [ws + timedelta(days=i) for i in range(7)]
    out: list[Draft] = []
    endurance = [x for x in drafts if x.sport != "strength"]
    bricks = {x.date: x for x in endurance if x.kind == "brick"}

    def key_days():
        return {x.date for x in out if x.is_key}

    def fits(x: Draft, d: date) -> bool:
        return (not cal.available) or cal.free_minutes(d) >= (x.duration_min or 30) + (
            bricks[x.date].duration_min if x.label == "brick" and x.date in bricks else 0)

    for x in sorted(endurance, key=lambda x: (not x.is_key, x.date)):
        if x.kind == "brick":
            continue                                    # travels with its ride
        missed = x.structure.get("gen_key") in missed_keys
        ok_here = (_allowed(x, x.date, gate_for, stops) and not missed and x.date >= today
                   and (not x.is_key or (fits(x, x.date) and x.date not in key_days())))
        if ok_here or (not x.is_key and _allowed(x, x.date, gate_for, stops)):
            out.append(x)
            if x.label == "brick" and x.date in bricks:
                out.append(bricks[x.date])
            continue
        if not x.is_key:
            continue                                    # an easy session that can't happen is dropped
        weekend = [d for d in days if d.weekday() >= 5] if x.is_long or x.label == "brick" else []
        near = sorted(days, key=lambda d: (abs((d - x.date).days), d))
        for d in dict.fromkeys(weekend + near):
            if d < today or (d == x.date and (missed or x.date < today)):
                continue
            if _allowed(x, d, gate_for, stops) and d not in key_days() and fits(x, d):
                why = ("missed" if missed else "travel" if not _allowed(x, x.date, gate_for, stops)
                       else "no free time" if not fits(x, x.date) else "clash with another key session")
                x.structure["moved_from"] = {"date": x.date.isoformat(), "why": why}
                if x.label == "brick" and x.date in bricks:
                    bricks[x.date].date = d
                    out.append(bricks[x.date])
                x.date = d
                out.append(x)
                break
        else:
            review.append(f"No compliant day this week for {TITLES.get((x.sport, x.kind), x.sport)} "
                          f"(planned {x.date:%a %b %-d}); left out.")
    return out + [x for x in drafts if x.sport == "strength"]


def _place_strength(drafts: list[Draft], ws: date, today: date, kind: str, gate_for, stops,
                    returning: bool) -> list[Draft]:
    """Friel's concurrent rules as constraints: N sessions a week for the
    phase; never on a key-endurance day; heavy lower body never within 2
    days before a long run or ride. If a template day breaks a rule, the
    strength session moves, not the endurance session."""
    template = [x for x in drafts if x.sport == "strength"]
    endurance = [x for x in drafts if x.sport != "strength"]
    n = STRENGTH_PER_WEEK.get("return" if returning else kind, 2)
    days = [ws + timedelta(days=i) for i in range(7)]
    key_days = {x.date for x in endurance if x.is_key}
    long_days = {x.date for x in endurance if x.is_long or (x.sport == "bike" and x.kind == "long")}

    def ok(d: date, heavy_lower: bool, used: set) -> bool:
        if d in used or d in key_days or not gate_for(d).prescriptions_allowed:
            return False
        place = travel.place_for(stops, d)
        if place.away and not place.sports:
            return False
        if heavy_lower and any(0 <= (L - d).days <= 2 for L in long_days):
            return False
        return True

    wanted = list(template[:n])
    filler = 0
    while len(wanted) < n and filler < 7:
        filler += 1
        wanted.append(Draft(ws + timedelta(days=2), "strength", "template", "Strength: Full-body",
                            label="Full-body (moderate)"))
    placed: list[Draft] = []
    used: set = set()
    for x in wanted:
        k, heavy = parse_strength(x.label) or ("light", False)
        if returning and k == "heavy":
            k, heavy = "light", False
        cands = [x.date] + sorted([d for d in days if d != x.date], key=lambda d: (abs((d - x.date).days), d))
        for d in cands:
            away = travel.place_for(stops, d).away
            kk, hh = ("bodyweight", False) if away else (k, heavy)
            if d >= today and ok(d, hh, used):
                x.date, x.kind, x.heavy_lower = d, kk, hh
                x.duration_min = 20 if kk == "bodyweight" else (35 if kk == "light" else 45)
                if kk == "bodyweight":
                    x.title = "Strength: bodyweight"
                placed.append(x)
                used.add(d)
                break
    for i, x in enumerate(sorted(placed, key=lambda x: x.date)):
        x.structure["gen_key"] = f"strength:{x.kind}#{i + 1}"
    return sorted(endurance + placed, key=lambda x: (x.date, x.sport == "strength"))


def _daily_cap(drafts: list[Draft], cap: int) -> None:
    by_day: dict[date, list[Draft]] = {}
    for x in drafts:
        by_day.setdefault(x.date, []).append(x)
    for items in by_day.values():
        total = sum(x.duration_min or 0 for x in items)
        for x in sorted(items, key=lambda x: (x.is_key, -(x.duration_min or 0))):
            if total <= cap:
                break
            cut = min(total - cap, (x.duration_min or 0) - 20)
            if cut > 0:
                x.duration_min -= cut
                if x.sport == "run" and x.distance_mi:
                    x.distance_mi = _round_half(x.duration_min / EASY_MIN_PER_MI)
                total -= cut


def _validate_and_relax(drafts: list[Draft], hist: History, gate_for, review: list[str],
                        today: date, stops, is_prov: bool) -> tuple[list[dict], list[Draft]]:
    """Validate; on a STOP relax up to 3 times, then drop what still stops."""
    def run():
        sess = [x for x in drafts if x.sport != "race" and x.duration_min]
        return sess, (validate_week([_as_session(x) for x in sess], hist, gate_for) if sess else None)

    sess, v = run()
    for attempt in range(RELAX_ATTEMPTS + 1):
        if not v:
            break
        stopped = [(sess[i], f) for i, fl in v.flags.items() for f in fl if f.severity is Severity.STOP]
        if not stopped:
            break
        if attempt == RELAX_ATTEMPTS:
            for x, f in stopped:
                review.append(f"{x.title} on {x.date:%a %b %-d} left out: {f.message}")
                if x in drafts:
                    drafts.remove(x)
            sess, v = run()
            break
        for x, f in stopped:
            if attempt == 0 and x.is_long and x.sport == "run":          # 1: shorten the long run 10%
                x.distance_mi = _round_half((x.distance_mi or 2) * 0.9)
                x.duration_min = round(x.distance_mi * EASY_MIN_PER_MI)
            elif attempt <= 1 and x.zone not in ("Z1", "Z2"):            # 2: key work becomes easy
                x.zone, x.kind = "Z2", "easy"
            elif x.sport == "run" and x.distance_mi:                    # 3: cut the volume
                x.distance_mi = max(2.0, _round_half(x.distance_mi * 0.75))
                x.duration_min = round(x.distance_mi * EASY_MIN_PER_MI)
            elif x.duration_min:
                x.duration_min = max(20, round(x.duration_min * 0.75))
            _finish(x, gate_for(x.date).status is Status.RETURN, is_prov and x.date > today,
                    travel.place_for(stops, x.date))
        sess, v = run()
    flags = []
    if v:
        for idx, fl in v.flags.items():
            for f in fl:
                flags.append({"date": sess[idx].date, "title": sess[idx].title, "kind": f.kind,
                              "severity": f.severity.value, "message": f.message})
        for f in v.week_flags:
            flags.append({"date": None, "title": None, "kind": f.kind,
                          "severity": f.severity.value, "message": f.message})
    for x in drafts:
        fl = [f for f in flags if f["date"] == x.date and f["title"] == x.title]
        x.structure.pop("flags", None)
        if fl:
            x.structure["flags"] = [{k: val for k, val in f.items() if k not in ("date", "title")} for f in fl]
    for msg in review:
        flags.append({"date": None, "title": None, "kind": "needs_review", "severity": "warn", "message": msg})
    return flags, drafts


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
        if x.label == "brick":
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
    if x.sport == "strength":
        st["heavy_lower"] = x.heavy_lower
    st["brief"] = brief(x.sport, x.kind, zone=x.zone, distance_mi=x.distance_mi, duration_min=x.duration_min,
                        hr_cap=st.get("hr_avg_max"), walk_over=st.get("walk_if_hr_over"),
                        returning=returning, provisional=prov,
                        place_note=(f"In {place.name}." if place.away and place.sports else ""))
    for k in ("pace", "hr_avg_max", "walk_if_hr_over", "walk_breaks", "provisional"):
        x.structure.pop(k, None)
    if prov:
        st["provisional"] = True
    x.structure = {**x.structure, **st}


# ── several weeks, written through the change path ───────────────────────
def generate(conn, first_ws: date, weeks: int = 3, factor: float = 1.0, today: date | None = None,
             trigger: str = "weekly", use_calendar: bool = True) -> list[WeekPlan]:
    """Plan ``weeks`` weeks from ``first_ws`` and write them (the first is
    the plan, the rest previews). Only differences are written."""
    from app.planning import sync
    today = today or first_ws
    hist = history(conn, first_ws)
    actual, planned = _week_run_mi(conn, first_ws - timedelta(days=7))
    basis = actual if actual > 0 else planned
    cal = Calendar(conn, first_ws, first_ws + timedelta(days=7 * weeks), use_calendar)
    out: list[WeekPlan] = []
    training_basis = basis          # last week before a taper or recovery
    for w in range(weeks):
        ws = first_ws + timedelta(days=7 * w)
        if out and out[-1].kind in ("race", "transition"):
            basis = max(basis, training_basis * RECOVERY_FACTOR)    # back to training after a race
        wp = sync.plan_and_sync(conn, ws, basis_mi=basis, factor=factor if w == 0 else PREVIEW_FACTOR,
                                hist=hist, today=today, cal=cal, preview=w > 0, trigger=trigger)
        out.append(wp)
        basis = wp.target_run_mi or basis
        if wp.kind in ("base", "build", "peak"):
            training_basis = wp.target_run_mi
        hist = History(hist.runs + [(x.date, x.distance_mi) for x in wp.drafts
                                    if x.sport == "run" and x.distance_mi],
                       hist.weekly_run_mi[1:] + [wp.run_mi])
    return out
