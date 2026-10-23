"""Next week's lifting weights, from logged Hevy sets (weight, reps, RPE).

Rules from the strength report "Strength plan while cutting" (Oct 2026). They
are coaching defaults, not tested formulas; tune them after a training cycle.

  e1RM per set   reps-to-failure RTF = reps + (10 - RPE) + bias (+0.5, or +1.0
                 at RPE < 8 or reps > 8); mean of Epley and Brzycki. Only sets
                 of <= 10 reps at RPE >= 7 count. No RPE logged: RPE 8 assumed.
  trend          weekly best e1RM, smoothed T = 0.3 x week + 0.7 x T (0.15 when
                 the week jumps > 5%).
  top set        load = T / (1 + (reps + 10 - target RPE) / 30), then nudged by
                 last week's RPE gap (logged - target): <= -1.5 +4%, -1..-0.5
                 +2%, 0 +1-2%, +0.5 same, >= +1 -2% per point; missed reps
                 -7.5%. Never more than +5 lb a week while cutting.
  back-offs      90% of the top set.
  accessories    double progression: every set at the top of the rep range at
                 RPE <= 8 -> +5 lb and back to the bottom; a set below the range
                 (or RPE >= 9.5) -> -7.5%; otherwise same load, one more rep.
  re-entry       three weeks or more without the lift: 75 / 85 / 92.5 / 97.5% of
                 the last working load over the first four weeks back.
  deload         flags: e1RM trend flat or falling for 3 weeks; top-set reps
                 missed twice in 3 weeks; the endurance plan's recovery week.
                 Two flags (or a recovery week): half the sets, top set RPE <= 7.
Weights are pounds; dumbbells are per dumbbell (as logged in Hevy).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

ALPHA, ALPHA_NOISY, NOISE = 0.3, 0.15, 0.05
BACKOFF = 0.90
CUT_CAP_LB = 5.0
REENTRY = (0.75, 0.85, 0.925, 0.975)
GAP_DAYS = 21
# Bench e1RM checkpoints (strength report, Oct 2026): date -> smoothed trend to reach.
BENCH_CHECKPOINTS = [(date(2026, 11, 24), 170), (date(2026, 12, 15), 185), (date(2027, 3, 1), 195),
                     (date(2027, 7, 25), 190)]


@dataclass(frozen=True)
class Lift:
    exercise: str                  # Hevy exercise title
    role: str                      # "top" (top set + back-offs), "volume" (sets from the trend) or "acc"
    sets: int
    reps: int | tuple[int, int]    # top: target reps; acc: (low, high)
    rpe: float = 8.0               # target RPE for the top set / ceiling for accessories
    backoffs: int = 0
    bodyweight: bool = False


# One fixed Push / Pull / Legs routine with crossover sets (bench twice a week),
# adapted from Felipe's; exercises from Patrick's Hevy log. Sets are the Base dose.
ROUTINE: dict[str, list[Lift]] = {
    "Push (Tue)": [
        Lift("Bench Press (Barbell)", "top", 1, 5, 8.0, backoffs=3),
        Lift("Overhead Press (Barbell)", "acc", 3, (6, 8)),
        Lift("Incline Bench Press (Dumbbell)", "acc", 3, (8, 12)),
        Lift("Triceps Pushdown", "acc", 3, (10, 15)),
        Lift("Lateral Raise (Dumbbell)", "acc", 3, (12, 20)),
    ],
    "Pull (Wed)": [
        Lift("Bent Over Row (Barbell)", "top", 1, 6, 8.0, backoffs=2),
        Lift("Pull Up", "acc", 3, (6, 10), bodyweight=True),
        Lift("Romanian Deadlift (Barbell)", "acc", 2, (6, 8)),
        Lift("Face Pull", "acc", 3, (12, 20)),
        Lift("Bicep Curl (Dumbbell)", "acc", 3, (10, 15)),
    ],
    "Legs (Thu)": [
        Lift("Squat (Barbell)", "top", 1, 5, 8.0, backoffs=2),
        Lift("Bench Press (Barbell)", "volume", 3, 8, 7.5),          # crossover: second, lighter bench
        Lift("Leg Press (Machine)", "acc", 3, (8, 12)),
        Lift("Seated Leg Curl (Machine)", "acc", 3, (10, 15)),
        Lift("Standing Calf Raise (Machine)", "acc", 3, (10, 15)),
    ],
}
# Hard sets fall as triathlon hours rise; loads stay heavy (share of the Base dose).
PHASE_SETS = {"return": 0.6, "prep": 1.0, "base": 1.0, "build": 0.6, "peak": 0.35,
              "race": 0.25, "transition": 0.5}


def round_to(x: float, step: float = 5.0) -> float:
    return round(x / step) * step


def e1rm(load: float, reps: int, rpe: float | None) -> float | None:
    """Estimated 1RM from one set, or None if the set doesn't qualify."""
    if not load or not reps or reps > 10:
        return None
    r = 8.0 if rpe is None else float(rpe)
    if r < 7:
        return None
    bias = 0.5 if (r >= 8 and reps <= 8) else 1.0
    rtf = reps + (10 - r) + bias
    return (load * (1 + rtf / 30) + load * 36 / (37 - min(rtf, 36))) / 2


def pct(reps: int, rpe_target: float) -> float:
    return 1 / (1 + (reps + 10 - rpe_target) / 30)


def gap_change(gap: float) -> float:
    """Load change for next week from last week's RPE gap (logged - target)."""
    if gap <= -1.5:
        return 0.04
    if gap <= -0.5:
        return 0.02
    if gap < 0.5:
        return 0.015
    if gap < 1.0:
        return 0.0
    return -0.02 * gap


@dataclass
class Rec:
    exercise: str
    sets: int
    reps: str
    load_lb: float | None
    rpe: float | None = None
    note: str = ""
    backoff: tuple[int, int, float] | None = None     # (sets, reps, load)
    bodyweight: bool = False

    def line(self) -> str:
        load = ("bodyweight" if self.bodyweight else "a weight you choose") if self.load_lb is None \
            else f"{self.load_lb:g} lb"
        s = f"**{self.exercise}**: {self.sets} × {self.reps} @ {load}"
        if self.rpe:
            s += f" (RPE {self.rpe:g})"
        if self.backoff:
            n, r, w = self.backoff
            s += f", then {n} × {r} @ {w:g} lb"
        return s + (f". {self.note}" if self.note else "")


@dataclass
class Plan:
    week_start: date
    phase_kind: str
    days: dict[str, list[Rec]] = field(default_factory=dict)
    deload: bool = False
    flags: list[str] = field(default_factory=list)
    trends: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"week_start": self.week_start.isoformat(), "phase_kind": self.phase_kind, "deload": self.deload,
                "flags": self.flags, "trends": {k: round(v, 1) for k, v in self.trends.items()},
                "days": {d: [r.__dict__ | {"line": r.line()} for r in rs] for d, rs in self.days.items()}}

    def markdown(self) -> str:
        out = ["**Next week's weights** (enter them in Hevy; log an RPE for every working set)"]
        if self.deload:
            out.append("_Deload week: half the sets, same or 10% lighter, top sets no harder than RPE 7._")
        for f in self.flags:
            out.append(f"_{f}_")
        for day, recs in self.days.items():
            out.append(f"**{day}**")
            out += [f"- {r.line()}" for r in recs]
        return "\n".join(out)


def _sets_by_week(conn, exercise: str, before: date) -> list[tuple[date, list[dict]]]:
    rows = conn.execute(
        """select performed_on, weight_lb, reps, rpe from strength_sets
           where exercise = %s and performed_on < %s and not excluded
             and coalesce(set_type, 'normal') not in ('warmup')
           order by performed_on, set_index""", (exercise, before)).fetchall()
    weeks: dict[date, list[dict]] = {}
    for r in rows:
        ws = r["performed_on"] - timedelta(days=r["performed_on"].weekday())
        weeks.setdefault(ws, []).append(r)
    return sorted(weeks.items())


def _trend(weeks: list[tuple[date, list[dict]]]) -> tuple[float | None, list[float]]:
    """Smoothed weekly best e1RM. Restarts after a layoff (3+ weeks off) and tracks the
    comeback weeks directly (re-baselining, as the report specifies); then a jump of
    more than 5% counts as noise (alpha 0.15) unless the week before jumped the
    same way, which makes it a real change (alpha 0.3)."""
    t, series, prev_ws, prev_dir, since = None, [], None, 0, 0
    for ws, sets in weeks:
        best = max((e for s in sets if (e := e1rm(s["weight_lb"], s["reps"], s["rpe"]))), default=None)
        if best is None:
            continue
        restart = t is None or (prev_ws and (ws - prev_ws).days > GAP_DAYS + 7)
        since = 0 if restart else since + 1
        if restart or since < len(REENTRY):
            t, prev_dir = best, 0            # the comeback weeks re-baseline the trend; smoothing starts after
        else:
            jump = (best - t) / t
            d = (jump > NOISE) - (jump < -NOISE)
            a = ALPHA_NOISY if d and d != prev_dir else ALPHA
            t = a * best + (1 - a) * t
            prev_dir = d
        prev_ws = ws
        series.append(t)
    return t, series


def _reentry_week(weeks: list[tuple[date, list[dict]]], ws: date) -> int | None:
    """Weeks back after a gap of 3+ weeks (0 = first week back), else None."""
    if not weeks:
        return None
    dates = [w for w, _ in weeks]
    if (ws - dates[-1]).days > GAP_DAYS:
        return 0
    back = 0
    for i in range(len(dates) - 1, 0, -1):
        back += 1
        if (dates[i] - dates[i - 1]).days > GAP_DAYS:
            return back if back < len(REENTRY) else None
    return None


def _last_working(weeks: list[tuple[date, list[dict]]]) -> float | None:
    for _, sets in reversed(weeks):
        loads = [s["weight_lb"] for s in sets if s["weight_lb"]]
        if loads:
            return max(loads)
    return None


def _top(lift: Lift, weeks, ws: date, cutting: bool, n_sets: int, flags: list[str]) -> Rec:
    reps = lift.reps if isinstance(lift.reps, int) else lift.reps[0]
    t, series = _trend(weeks)
    re = _reentry_week(weeks, ws)
    if re is not None:
        last = _last_working(weeks)
        load = round_to(last * REENTRY[re]) if last else None
        return Rec(lift.exercise, n_sets, str(reps), load, min(lift.rpe, 7.0),
                   f"Re-entry week {re + 1} of {len(REENTRY)}: {int(REENTRY[re] * 100)}% of your last working weight",
                   (lift.backoffs, reps, round_to(load * BACKOFF)) if load and lift.backoffs else None)
    if t is None:
        return Rec(lift.exercise, n_sets, str(reps), None, lift.rpe, "No logged sets yet: pick a weight you could lift 2 more times")
    load = t * pct(reps, lift.rpe)
    note = f"trend e1RM {t:.0f} lb"
    last_sets = weeks[-1][1] if weeks else []
    top = max(last_sets, key=lambda s: (s["weight_lb"] or 0, s["reps"] or 0), default=None)
    if top and top["weight_lb"]:
        if top["reps"] is not None and top["reps"] < reps:
            load = top["weight_lb"] * 0.925
            note += "; reps missed last week"
        elif top["rpe"] is not None:
            g = float(top["rpe"]) - lift.rpe
            load = top["weight_lb"] * (1 + gap_change(g))
            note += f"; last top set {top['weight_lb']:g} × {top['reps']} @ RPE {float(top['rpe']):g}"
        if cutting and load > top["weight_lb"] + CUT_CAP_LB:
            load = top["weight_lb"] + CUT_CAP_LB
    if len(series) >= 4 and series[-1] <= series[-4]:
        flags.append(f"{lift.exercise}: e1RM trend flat or falling for 3 weeks.")
    load = round_to(load)
    return Rec(lift.exercise, n_sets, str(reps), load, lift.rpe, note,
               (lift.backoffs, reps, round_to(load * BACKOFF)) if lift.backoffs else None)


def _volume(lift: Lift, weeks, ws: date, n_sets: int) -> Rec:
    """A lighter second exposure: straight sets from the e1RM trend."""
    reps = lift.reps if isinstance(lift.reps, int) else lift.reps[0]
    re = _reentry_week(weeks, ws)
    t, _ = _trend(weeks)
    if re is not None or t is None:
        last = _last_working(weeks)
        load = round_to(last * REENTRY[re or 0] * 0.85) if last else None
        return Rec(lift.exercise + " (volume)", n_sets, str(reps), load, 7.0, "lighter second session")
    return Rec(lift.exercise + " (volume)", n_sets, str(reps), round_to(t * pct(reps, lift.rpe)), lift.rpe,
               "lighter second session; add 5 lb once all sets reach 8 at RPE 8 or easier")


def _acc(lift: Lift, weeks, ws: date, n_sets: int) -> Rec:
    lo, hi = lift.reps if isinstance(lift.reps, tuple) else (lift.reps, lift.reps)
    rng = f"{lo}-{hi}"
    if lift.bodyweight:
        return Rec(lift.exercise, n_sets, rng, None, None, "add a rep a week; add weight once every set reaches the top",
                   bodyweight=True)
    re = _reentry_week(weeks, ws)
    last = _last_working(weeks)
    if re is not None:
        return Rec(lift.exercise, n_sets, rng, round_to(last * REENTRY[re], 2.5) if last else None, 7.0,
                   f"Re-entry week {re + 1}")
    if not weeks or last is None:
        return Rec(lift.exercise, n_sets, rng, None, 8.0, "New: start where the top of the range feels like RPE 8")
    sets = [s for s in weeks[-1][1] if s["weight_lb"]]
    work = max(s["weight_lb"] for s in sets)
    at_work = [s for s in sets if s["weight_lb"] == work]
    if at_work and all((s["reps"] or 0) >= hi and (s["rpe"] is None or float(s["rpe"]) <= 8) for s in at_work):
        return Rec(lift.exercise, n_sets, f"{lo}", work + 5, 8.0, f"hit {hi} on every set: +5 lb, back to {lo} reps")
    if any((s["reps"] or 0) < lo or (s["rpe"] is not None and float(s["rpe"]) >= 9.5) for s in at_work):
        return Rec(lift.exercise, n_sets, rng, round_to(work * 0.925, 2.5), 8.0, "below the range last week: -7.5%")
    return Rec(lift.exercise, n_sets, rng, work, 8.0, "same weight, one more rep than last week")


def recommend(conn, ws: date, *, phase_kind: str = "base", cutting: bool = False,
              recovery_week: bool = False) -> Plan:
    """Weights for the week starting ``ws`` (a Monday)."""
    plan = Plan(ws, phase_kind)
    share = PHASE_SETS.get(phase_kind, 1.0)
    missed = 0
    for day, lifts in ROUTINE.items():
        recs = []
        for lift in lifts:
            weeks = _sets_by_week(conn, lift.exercise, ws)
            n = max(1, round(lift.sets * share)) if lift.role == "acc" or lift.sets > 1 else lift.sets
            if lift.role == "volume":
                r = _volume(lift, weeks, ws, n)
            elif lift.role == "top":
                r = _top(lift, weeks, ws, cutting, n, plan.flags)
                if "reps missed" in r.note:
                    missed += 1
                if r.backoff:
                    r.backoff = (max(1, round(r.backoff[0] * share)), r.backoff[1], r.backoff[2])
            else:
                r = _acc(lift, weeks, ws, n)
            recs.append(r)
            t, _ = _trend(weeks)
            if t and lift.role == "top":
                plan.trends[lift.exercise] = t
        plan.days[day] = recs
    if missed >= 2:
        plan.flags.append("Top-set reps missed on two lifts last week.")
    if recovery_week:
        plan.flags.append("Recovery week in the endurance plan: lifting deloads with it.")
    plan.deload = recovery_week or len(plan.flags) >= 2
    if plan.deload:
        for recs in plan.days.values():
            for r in recs:
                r.sets = max(1, r.sets // 2) if r.sets > 1 else r.sets
                if r.backoff:
                    r.backoff = (max(1, r.backoff[0] // 2), r.backoff[1], r.backoff[2])
                if r.rpe:
                    r.rpe = min(r.rpe, 7.0)
    return plan


def for_week(conn, ws: date) -> Plan:
    """recommend() with the week's phase, deficit block and recovery week filled in."""
    from app import db, nutrition
    from app.periodization.phases import NoPhaseDefined, phase_for
    mid = ws + timedelta(days=3)
    try:
        ph = phase_for(db.load_phases(conn), mid)
        kind, idx = ph.kind, (ws - ph.start_date).days // 7
    except NoPhaseDefined:
        kind, idx = "base", 0
    ep = db.open_episode(conn, mid)
    if ep and ep.return_ends_on and ep.return_ends_on >= ws:
        kind = "return"
    target = (conn.execute("select target from goals where name = 'Daily targets'").fetchone() or {}).get("target") or {}
    cutting = nutrition._block(target.get("nutrition_plan"), mid) is not None
    recovery = kind in ("base", "build") and idx % 4 == 3
    return recommend(conn, ws, phase_kind=kind, cutting=cutting, recovery_week=recovery)


def session_lifts(plan: Plan, title: str) -> list[list[str]]:
    """Rows [exercise, sets x reps, weight] for one planned strength session,
    picked from the week's recommendations by the session's name."""
    t = (title or "").lower()
    if "bodyweight" in t or "mobility" in t:
        return []
    push, pull, legs = (plan.days.get(k, []) for k in ("Push (Tue)", "Pull (Wed)", "Legs (Thu)"))
    tops = {r.exercise: r for r in push + pull + legs if r.rpe and r.backoff}
    picks: list[Rec] = []
    if "full-body" in t:
        picks = [tops[e] for e in ("Bench Press (Barbell)", "Squat (Barbell)", "Bent Over Row (Barbell)") if e in tops]
    else:
        if "push" in t:
            picks += push
        if "pull" in t:
            picks += pull if "hinge" not in t else [r for r in pull if "Deadlift" not in r.exercise] + \
                [r for r in pull if "Deadlift" in r.exercise][:1]
        if "legs" in t:
            picks += legs
        if "squat" in t and "legs" not in t:
            picks += [r for r in legs if r.exercise == "Squat (Barbell)"]
        if "upper" in t and not picks:
            picks = [r for r in push + pull if r.backoff or r.exercise in ("Overhead Press (Barbell)", "Pull Up")]
    rows = []
    seen: set[int] = set()
    for r in picks:
        if id(r) in seen:
            continue
        seen.add(id(r))
        load = ("bodyweight" if r.bodyweight else "your choice") if r.load_lb is None else f"{r.load_lb:g} lb"
        reps = f"{r.sets} × {r.reps}" + (f" @ RPE {r.rpe:g}" if r.rpe else "")
        rows.append([r.exercise, reps, load])
        if r.backoff:
            n, rp, w = r.backoff
            rows.append(["  back-off", f"{n} × {rp}", f"{w:g} lb"])
    return rows


def attach(conn, days: list[dict]) -> None:
    """Fill structure.exercises on planned strength sessions (Today and Plan tabs)."""
    cache: dict[date, Plan] = {}
    for d in days:
        for s in d.get("sessions") or []:
            if s.get("sport") != "strength" or s.get("suppressed") or s.get("status") == "done":
                continue
            day = s["date"] if isinstance(s["date"], date) else date.fromisoformat(str(s["date"]))
            ws = day - timedelta(days=day.weekday())
            if ws not in cache:
                cache[ws] = for_week(conn, ws)
            rows = session_lifts(cache[ws], s.get("title") or "")
            if rows:
                s["structure"] = dict(s.get("structure") or {}) | {"exercises": rows}


def bench_checkpoint(plan: Plan, today: date) -> str:
    """One line: the bench trend against the next checkpoint."""
    t = plan.trends.get("Bench Press (Barbell)")
    nxt = next(((d, v) for d, v in BENCH_CHECKPOINTS if d >= today), None)
    if not nxt:
        return ""
    d, v = nxt
    if t is None:
        return f"**Bench**: next checkpoint {v} lb e1RM by {d:%b %-d}; log RPE so the trend can be computed."
    status = "on track" if t >= v else f"{v - t:.0f} lb to go"
    return f"**Bench**: trend e1RM {t:.0f} lb; checkpoint {v} by {d:%b %-d}: {status}."
