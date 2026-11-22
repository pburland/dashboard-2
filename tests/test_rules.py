"""The rules of record (app/rules.py). Changing a threshold means changing this file too."""
from app import rules

# Every rule's value, pinned. If a number changes on purpose: update it here, bump
# rules.VERSION, and note why in the rule's ``changed`` field.
PINNED = {
    "return_min_days": 7, "return_max_days": 21, "return_start_volume": 0.5, "return_end_volume": 0.9,
    "return_long_run_cap": 0.7, "caution_readiness_below": 70, "caution_rhr_rise": 5, "caution_temp_c": 0.5,
    "checkin_caution_days": 2, "watch_rhr_rise": 5, "watch_decoupling": 0.05, "watch_hrv_sd": 0.5,
    "watch_signals_for_caution": 2, "easy_hr_cap": 145, "easy_hr_walk": 155, "weekly_ramp_max": 0.10,
    "recovery_every_weeks": 4, "recovery_week_factor": 0.8, "long_run_share": 0.33,
    "long_run_jump_warn": 0.10, "long_run_jump_stop": 0.20, "session_share_warn": 0.35,
    "session_share_stop": 0.45, "decoupling_warn": 0.05, "decoupling_stop": 0.08, "legs_before_long_days": 1,
    "heat_index_thresholds": {"easy": (85.0, 95.0), "quality": (80.0, 88.0), "long": (78.0, 85.0)},
    "heat_illness_offset_f": 5.0, "ea_deficit_floor": 30, "ea_hard_floor": 25,
    "carbs_g_per_kg": {"rest": 3.5, "lift": 3.75, "easy": 4.5, "lift_easy": 5.0, "key": 6.0,
                       "long_run": 7.0, "long_ride": 9.0},
    "weight_step_kcal": 175, "weight_max_adjust_kcal": 400, "strength_backoff": 0.90,
    "strength_cut_cap_lb": 5.0, "strength_reentry": (0.75, 0.85, 0.925, 0.975), "strength_gap_days": 21,
    "run_hr_zones": (("Z1", 0.00, 0.85), ("Z2", 0.85, 0.90), ("Z3", 0.90, 0.95), ("Z4", 0.95, 1.00),
                     ("Z5a", 1.00, 1.03), ("Z5b", 1.03, 1.07), ("Z5c", 1.07, 2.00)),
    "bike_hr_zones": (("Z1", 0.00, 0.81), ("Z2", 0.81, 0.90), ("Z3", 0.90, 0.94), ("Z4", 0.94, 1.00),
                      ("Z5a", 1.00, 1.03), ("Z5b", 1.03, 1.07), ("Z5c", 1.07, 2.00)),
}


def test_every_rule_is_pinned():
    assert {r.id: r.value for r in rules.RULES} == PINNED


def test_every_rule_has_units_a_source_and_a_grade():
    ids = [r.id for r in rules.RULES]
    assert len(ids) == len(set(ids))
    for r in rules.RULES:
        assert r.units and r.what and r.source and r.grade in "ABCD", r.id


def test_modules_use_the_registry():
    from app.analysis import heat, overreach, validator
    from app.health import state, watch
    from app.ingest import evaluate
    from app.periodization import zones
    from app.planning import generator
    from app import bodycomp, checkins, nutrition, strength
    assert overreach.LONG_RUN_JUMP_WARN == rules.value("long_run_jump_warn")
    assert overreach.SESSION_SHARE_STOP == rules.value("session_share_stop")
    assert validator.LEGS_BEFORE_LONG_DAYS == rules.value("legs_before_long_days")
    assert heat.THRESHOLDS is rules.value("heat_index_thresholds")
    assert state.RETURN_MAX_DAYS == rules.value("return_max_days")
    assert watch.RHR_RISE == rules.value("watch_rhr_rise")
    assert evaluate.EASY_HR_CAP == generator.HR_CAP == rules.value("easy_hr_cap")
    assert generator.MAX_RAMP == 1 + rules.value("weekly_ramp_max")
    assert zones.RUN_ZONES is rules.value("run_hr_zones")
    assert nutrition.CARBS_G_PER_KG is rules.value("carbs_g_per_kg")
    assert bodycomp.STEP_KCAL == rules.value("weight_step_kcal")
    assert checkins.CAUTION_DAYS == rules.value("checkin_caution_days")
    assert strength.REENTRY == rules.value("strength_reentry")


def test_pat_gpt_sees_the_rules_and_is_told_not_to_invent():
    text = rules.render()
    assert rules.VERSION in text and "no rule on file" in text
    assert "easy_hr_cap = 145 bpm" in text and "PROVISIONAL" in text
