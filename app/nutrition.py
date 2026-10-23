"""Daily fuel targets from resting metabolic rate and the day's plan.

Rules from the nutrition report "Recomp and fueling plan" (Oct 2026), held as
data in the "Daily targets" goal (goals.target.nutrition_plan), so the plan of
record can change without code:

  calories = working RMR x 1.45 (daily life) + the day's training
             - the block's deficit on rest, lift and easy days inside a
               deficit block (never on key or long days, weekends, during a
               hold or the return, or below the energy-availability floor)
  energy availability = (calories - training) / fat-free mass:
             >= 30 kcal/kg on a deficit day, never planned below 25
  protein  = 160 g every day (or ~1 g/lb without a plan)
  carbs    = g/kg by day type: rest 3.5, lift 3.75, easy 4.5, lift + easy 5,
             key 6, long run 7, long ride 3 h+ 9
Training calories: run ~1 kcal/kg/km, bike ~600 kcal/h (Z2) / ~800 (harder),
swim ~600 kcal/h, lifting ~6 kcal/min. Rough; the 7-day weight trend corrects.
"""
from __future__ import annotations

from datetime import date

NEAT_FACTOR = 1.45
KM_PER_MI = 1.609344
KCAL_PER_KG_PER_KM = 1.0           # running, gross (net ~0.95)
KCAL_PER_MIN = {"bike": 10.0, "swim": 10.0, "strength": 6.0, "walk": 4.0}
HARD_ZONES = ("Z3", "Z4", "Z5a", "Z5b", "Z5c")
EA_DEFICIT_FLOOR = 30              # kcal per kg fat-free mass, on a deficit day
EA_HARD_FLOOR = 25                 # never plan below this
CARBS_G_PER_KG = {"rest": 3.5, "lift": 3.75, "easy": 4.5, "lift_easy": 5.0, "key": 6.0,
                  "long_run": 7.0, "long_ride": 9.0}
FAT_MIN_G = 65


def session_kcal(s: dict, weight_lb: float) -> float:
    kg = weight_lb / 2.2046
    if s.get("sport") == "run" and s.get("distance_mi"):
        return s["distance_mi"] * KM_PER_MI * kg * KCAL_PER_KG_PER_KM
    rate = KCAL_PER_MIN.get(s.get("sport"), 6.0)
    if s.get("max_zone") in HARD_ZONES and s.get("sport") in ("bike", "swim", "run"):
        rate *= 1.3
    return (s.get("duration_min") or 0) * rate


def day_type(sessions: list[dict]) -> str:
    sports = {s.get("sport") for s in sessions}
    minutes = sum(s.get("duration_min") or 0 for s in sessions if s.get("sport") not in ("strength", None))
    if any(s.get("is_long") and s.get("sport") == "bike" for s in sessions) or \
            any(s.get("sport") == "bike" and (s.get("duration_min") or 0) >= 180 for s in sessions):
        return "long_ride"
    if any(s.get("is_long") for s in sessions):
        return "long_run"
    if any(s.get("is_key") or s.get("max_zone") in HARD_ZONES for s in sessions if s.get("sport") != "strength") \
            or minutes >= 90:
        return "key"
    if "strength" in sports:
        return "lift_easy" if minutes else "lift"
    return "easy" if minutes else "rest"


def _block(plan: dict | None, day: date | None) -> dict | None:
    if not plan or not day:
        return None
    for b in plan.get("deficit_blocks") or []:
        if date.fromisoformat(b["from"]) <= day <= date.fromisoformat(b["to"]):
            return b
    return None


def targets(rmr: int | None, weight_lb: float | None, sessions: list[dict], *, health: str,
            phase_kind: str | None, deficit_goal: bool, day: date | None = None,
            plan: dict | None = None, ffm_kg: float | None = None) -> dict | None:
    """``plan``: goals.target.nutrition_plan (working RMR, protein, deficit blocks).
    Without one, the older flat rule applies: -300 on easy base days."""
    rmr = (plan or {}).get("rmr_working_kcal") or rmr
    if not rmr or not weight_lb:
        return None
    kg = weight_lb / 2.2046
    ffm = ffm_kg or kg * 0.81
    sessions = [s for s in sessions if not s.get("suppressed") and s.get("sport") != "race"]
    train = sum(session_kcal(s, weight_lb) for s in sessions)
    kind = day_type(sessions)
    maintenance = rmr * NEAT_FACTOR + train
    kcal, why = maintenance, []
    weekend = day is not None and day.weekday() >= 5
    hard_day = kind in ("key", "long_run", "long_ride")
    if health in ("hold", "return"):
        why.append("no deficit while recovering")
    elif deficit_goal and health == "clear" and not hard_day and not weekend:
        if plan is not None:
            b = _block(plan, day)
            if b:
                kcal -= b["kcal"]
                why.append(f"{b['kcal']} under maintenance ({b.get('name', 'deficit block')})")
            else:
                why.append("maintenance (no deficit block today)")
        elif phase_kind == "base":
            kcal -= 300
            why.append("300 under maintenance for the body-comp goal (easy base day)")
    elif hard_day:
        why.append("fuel the key or long session, no deficit")
    # Energy availability: never plan below the floor.
    floor = (EA_DEFICIT_FLOOR if kcal < maintenance else EA_HARD_FLOOR) * ffm + train
    if kcal < floor:
        kcal = floor
        why.append("raised to the energy-availability floor")
    protein = (plan or {}).get("protein_g") or round(weight_lb, -1)
    carbs = kg * CARBS_G_PER_KG[kind]
    return {"kcal": int(round(kcal, -1)), "protein_g": int(protein),
            "carbs_g": int(round(carbs, -1)), "fat_min_g": FAT_MIN_G,
            "training_kcal": int(round(train, -1)), "day_type": kind,
            "ea_kcal_per_kg_ffm": round((kcal - train) / ffm, 1), "why": why}
