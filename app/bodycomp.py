"""Weekly body-weight check and calorie correction (nutrition report rules R1-R5, R8).

From 7-day averages of morning weigh-ins:
  R1  first two weeks of a deficit block: report only (early loss is water and glycogen)
  R2  losing > 0.15 kg/wk faster than target two weeks running, or R4 more than
      0.7% of bodyweight in one week: +175 kcal/day
  R3  losing > 0.15 kg/wk slower than target two weeks running: -175 kcal/day
      (taken from rest and easy days; the energy-availability floor still applies)
  R5  at maintenance: drift > 0.5 kg over two weeks -> +/-175 kcal/day
  R8  race weeks: no change
The adjustment is stored in the nutrition plan (goals."Daily targets".target.
nutrition_plan.kcal_adjust), bounded to +/-400, and the daily targets add it.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean

from psycopg.types.json import Jsonb

LB_PER_KG = 2.20462
STEP_KCAL = 175
MAX_ADJUST = 400
TOL_KG = 0.15


def weekly_avgs(conn, ws: date, weeks: int = 3) -> list[float | None]:
    """7-day average weight (lb) for the week starting ``ws`` and the ``weeks - 1`` before it, oldest first."""
    out = []
    for k in range(weeks - 1, -1, -1):
        a = ws - timedelta(weeks=k)
        rows = conn.execute("select weight_lb from body_metrics where day between %s and %s and weight_lb is not null",
                            (a, a + timedelta(days=6))).fetchall()
        out.append(round(mean(r["weight_lb"] for r in rows), 1) if rows else None)
    return out


def _plan(conn) -> dict:
    t = (conn.execute("select target from goals where name = 'Daily targets'").fetchone() or {}).get("target") or {}
    return t.get("nutrition_plan") or {}


def _block(plan: dict, d: date) -> dict | None:
    for b in plan.get("deficit_blocks") or []:
        if date.fromisoformat(b["from"]) <= d <= date.fromisoformat(b["to"]):
            return b
    return None


def target_loss_kg(block: dict | None, weight_lb: float) -> float:
    """Planned weekly loss: ~0.5% of bodyweight in base blocks, ~0.35% later, 0 at maintenance."""
    if not block:
        return 0.0
    rate = 0.005 if block.get("name", "").startswith("base") else 0.0035
    return weight_lb / LB_PER_KG * rate


def check(conn, ws: date, phase_kind: str | None = None, apply: bool = True) -> dict:
    """Weigh the week starting ``ws`` against the plan; maybe adjust calories."""
    plan = _plan(conn)
    avgs = weekly_avgs(conn, ws, 3)
    out = {"avg_lb": avgs[-1], "prev_lb": avgs[-2], "change_lb": None, "target_change_lb": None,
           "adjust": 0, "kcal_adjust": plan.get("kcal_adjust", 0), "why": ""}
    if None in avgs[-2:]:
        out["why"] = "Not enough weigh-ins for a 7-day average yet (weigh in most mornings in Hevy)."
        return out
    mid = ws + timedelta(days=3)
    block, prev_block = _block(plan, mid), _block(plan, mid - timedelta(days=7))
    target = target_loss_kg(block, avgs[-1])
    loss = [(a - b) / LB_PER_KG for a, b in zip(avgs, avgs[1:]) if a is not None and b is not None]
    out["change_lb"] = round(avgs[-1] - avgs[-2], 1)
    out["target_change_lb"] = round(-target * LB_PER_KG, 1)
    step = 0
    if phase_kind == "race":
        out["why"] = "Race week: no calorie changes (expect +1-2 lb from carb loading)."
    elif block:
        week_in = (ws - date.fromisoformat(block["from"])).days // 7 + 1
        both = len(loss) == 2 and prev_block is not None
        if week_in <= 2:
            out["why"] = f"Week {week_in} of {block['name']}: early loss is mostly water; no change yet."
        elif loss[-1] > avgs[-1] / LB_PER_KG * 0.007:
            step, out["why"] = STEP_KCAL, "Lost more than 0.7% of bodyweight this week: too fast."
        elif both and all(x - target > TOL_KG for x in loss):
            step, out["why"] = STEP_KCAL, "Losing faster than planned two weeks running."
        elif both and all(target - x > TOL_KG for x in loss):
            step, out["why"] = -STEP_KCAL, "Losing slower than planned two weeks running."
        else:
            out["why"] = "On track."
    elif avgs[0] is not None and abs(avgs[-1] - avgs[0]) / LB_PER_KG > 0.5:
        step = STEP_KCAL if avgs[-1] < avgs[0] else -STEP_KCAL
        out["why"] = "Maintenance phase: weight drifted more than 0.5 kg over two weeks."
    else:
        out["why"] = "Maintenance phase: weight steady." if not block else "On track."
    if step and plan.get("kcal_adjust_week") == ws.isoformat():
        step = 0                                          # this week was already applied (report re-run)
        out["why"] += " (Adjustment already applied for this week.)"
    if step:
        new = max(-MAX_ADJUST, min(MAX_ADJUST, plan.get("kcal_adjust", 0) + step))
        out["adjust"] = new - plan.get("kcal_adjust", 0)
        out["kcal_adjust"] = new
        if apply and out["adjust"]:
            conn.execute("""update goals set target = jsonb_set(jsonb_set(target, '{nutrition_plan,kcal_adjust}', %s),
                                                         '{nutrition_plan,kcal_adjust_week}', %s)
                            where name = 'Daily targets' and target ? 'nutrition_plan'""",
                         (Jsonb(new), Jsonb(ws.isoformat())))
    return out


def markdown(c: dict) -> str:
    if c.get("avg_lb") is None or c.get("change_lb") is None:
        return f"**Body weight**: {c['why']}"
    s = f"**Body weight**: 7-day average {c['avg_lb']:g} lb ({c['change_lb']:+g} lb; plan {c['target_change_lb']:+g}). {c['why']}"
    if c["adjust"]:
        s += f" Daily calories {c['adjust']:+d} from now on (total adjustment {c['kcal_adjust']:+d})."
    return s
