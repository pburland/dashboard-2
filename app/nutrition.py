"""Daily fuel targets from measured resting metabolic rate and the day's plan.

  calories = RMR x 1.3 (daily life, the lab's own estimate) + planned training
             - 300 on easy days in base phases while the body-comp goal is
               active (never during a hold, the return, peak or race weeks,
               or on a long-session day)
  protein  = ~1 g per lb of bodyweight
  carbs    = 3 / 5 / 7 g per kg for a light / moderate / long day
Training calories are rough estimates; the point is to eat for the work.
"""
from __future__ import annotations

NEAT_FACTOR = 1.3
DEFICIT_KCAL = 300
KCAL_PER_LB_PER_MI = 0.72          # running, gross
KCAL_PER_MIN = {"bike": 8.0, "swim": 9.0, "strength": 5.0, "walk": 4.0}


def session_kcal(s: dict, weight_lb: float) -> float:
    if s.get("sport") == "run" and s.get("distance_mi"):
        return s["distance_mi"] * weight_lb * KCAL_PER_LB_PER_MI
    rate = KCAL_PER_MIN.get(s.get("sport"), 6.0)
    if s.get("max_zone") in ("Z3", "Z4", "Z5a", "Z5b", "Z5c"):
        rate *= 1.25
    return (s.get("duration_min") or 0) * rate


def targets(rmr: int | None, weight_lb: float | None, sessions: list[dict], *, health: str,
            phase_kind: str | None, deficit_goal: bool) -> dict | None:
    if not rmr or not weight_lb:
        return None
    sessions = [s for s in sessions if not s.get("suppressed") and s.get("sport") != "race"]
    train = sum(session_kcal(s, weight_lb) for s in sessions)
    minutes = sum(s.get("duration_min") or 0 for s in sessions if s.get("sport") != "strength")
    long_day = any(s.get("is_long") for s in sessions) or minutes >= 90
    kcal = rmr * NEAT_FACTOR + train
    why = []
    if (deficit_goal and health == "clear" and phase_kind == "base" and not long_day):
        kcal -= DEFICIT_KCAL
        why.append(f"{DEFICIT_KCAL} under maintenance for the body-comp goal (easy base day)")
    elif health in ("hold", "return"):
        why.append("no deficit while recovering")
    elif long_day:
        why.append("fuel the long session, no deficit")
    kg = weight_lb / 2.2046
    carbs_per_kg = 7 if long_day else (5 if minutes >= 45 else 3)
    return {"kcal": int(round(kcal, -1)), "protein_g": int(round(weight_lb, -1)),
            "carbs_g": int(round(kg * carbs_per_kg, -1)), "training_kcal": int(round(train, -1)),
            "why": why}
