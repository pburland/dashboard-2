"""The rules of record: every training threshold the app acts on, in one place.

Each rule carries its value, units, what it does, where it comes from and how
strong that evidence is (outside review, Card 10):

  A  meta-analyses or randomised trials
  B  controlled studies or strong expert consensus (IOC / ACSM statements)
  C  coaching convention or expert opinion
  D  this system's own conservative default, or reasoning without direct evidence

Modules read their numbers from here, Pat-GPT is shown this list and may quote
it but never invent a threshold, and tests/test_rules.py pins every value: a
changed number without a changed test fails the build. Bump VERSION with any
change and say why in the rule's ``changed`` note.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VERSION = "2026-11-22.2"


@dataclass(frozen=True)
class Rule:
    id: str
    value: Any
    units: str
    what: str
    source: str
    grade: str                  # A | B | C | D
    changed: str = "2026-11-22: moved into the registry"


FRIEL = "Friel, The Triathlete's Training Bible"
POST_MONO = "conservative post-viral graded return (clinical consensus); outside review Card 1"

RULES: tuple[Rule, ...] = (
    # ── health gate and return to training ─────────────────────────────────
    Rule("return_min_days", 7, "days", "Shortest return to training after a hold.", POST_MONO, "C"),
    Rule("return_max_days", 21, "days", "Longest return to training (holds longer than this still get 21). "
         "Trip days pause it.", POST_MONO, "C"),
    Rule("return_start_volume", 0.5, "fraction", "Training volume on day 1 of the return.", POST_MONO, "C"),
    Rule("return_end_volume", 0.9, "fraction", "Training volume on the last day of the return.", POST_MONO, "C"),
    Rule("return_long_run_cap", 0.7, "fraction", "Long run during the return, as a share of the longest run "
         "before the hold.", POST_MONO, "D"),
    Rule("caution_readiness_below", 70, "Oura score", "Morning readiness below this sets CAUTION (Z2 only, "
         "no long-run growth).", "Oura readiness guidance; system default", "D"),
    Rule("caution_rhr_rise", 5, "bpm", "Morning resting HR this far above baseline sets CAUTION.",
         "Plews et al. 2013 (HRV/RHR as fatigue signals); system default", "C"),
    Rule("caution_temp_c", 0.5, "°C", "Oura temperature deviation that sets CAUTION (possible illness).",
         "System default", "D"),
    Rule("checkin_caution_days", 2, "days", "After a 'felt bad' or pain check-in: CAUTION that day and the "
         "next two.", "System default (stricter than the outside review's proposal)", "D"),
    # ── relapse watch ──────────────────────────────────────────────────────
    Rule("watch_rhr_rise", 5, "bpm", "Relapse watch: 7-day mean resting HR above baseline by this much, "
         "3 days running. Loosen to 7 if it fires most days.", POST_MONO, "D"),
    Rule("watch_decoupling", 0.05, "fraction", "Relapse watch: pace:HR drift above this on 2 easy runs "
         "(30+ min) within 7 days.", f"{FRIEL} (decoupling 5%)", "C"),
    Rule("watch_hrv_sd", 0.5, "SD", "Relapse watch: 7-day mean ln(HRV) below the 60-day mean minus this "
         "many SDs, 2 nights running (needs 21+ nights outside the hold).",
         "Plews et al. 2013; Kiviniemi et al. 2007", "B"),
    Rule("watch_signals_for_caution", 2, "signals", "Different watch signals within 7 days that ease off "
         "for 2 days. Jet lag (5+ time zones, 3 days) doesn't count.", POST_MONO, "D"),
    # ── load and plan checks ───────────────────────────────────────────────
    Rule("easy_hr_cap", 145, "bpm", "PROVISIONAL easy-run average HR cap until the Dec 1 LTHR test sets "
         "Z2. From his pre-illness easy runs.", "Athlete history; replaced by LTHR zones", "D"),
    Rule("easy_hr_walk", 155, "bpm", "Walk if HR passes this on an easy run (provisional, as above).",
         "System default", "D"),
    Rule("weekly_ramp_max", 0.10, "fraction", "Weekly run volume grows at most this much; also the "
         "warning level for a week that did.", f"{FRIEL}; coaching convention", "C"),
    Rule("recovery_every_weeks", 4, "weeks", "Every 4th week is lighter (3 building, 1 recovery).", FRIEL, "C"),
    Rule("recovery_week_factor", 0.8, "fraction", "Volume of a recovery week vs the week before.", FRIEL, "C"),
    Rule("long_run_share", 0.33, "fraction", "Long run as a share of weekly run volume.",
         "Coaching convention", "C"),
    Rule("long_run_jump_warn", 0.10, "fraction", "Long run longer than the 4-week longest by this much "
         "warns (growth of 1 mi or less is never flagged).", "Coaching convention", "C"),
    Rule("long_run_jump_stop", 0.20, "fraction", "Long-run jump that stops the plan.", "System default", "D"),
    Rule("session_share_warn", 0.35, "fraction", "One session above this share of the week's load warns.",
         "System default (prototype lesson, Sep 13 2026)", "D"),
    Rule("session_share_stop", 0.45, "fraction", "One session above this share of the week's load stops.",
         "System default", "D"),
    Rule("decoupling_warn", 0.05, "fraction", "Pace:HR decoupling that warns.", FRIEL, "C"),
    Rule("decoupling_stop", 0.08, "fraction", "Pace:HR decoupling that stops.", "System default", "D"),
    Rule("legs_before_long_days", 1, "days", "Heavy legs never this close before a long run or ride.",
         f"{FRIEL} (concurrent strength)", "C"),
    # ── heat ───────────────────────────────────────────────────────────────
    Rule("heat_index_thresholds", {"easy": (85.0, 95.0), "quality": (80.0, 88.0), "long": (78.0, 85.0)},
         "°F heat index (warn, stop)", "Heat go/no-go by session kind. NOT ACSM-aligned (ACSM uses WBGT); to "
         "convert to WBGT when humidity data allows. Loosen +5°F only while heat-acclimated.",
         "System default; see ACSM (Armstrong 2007), Racinais 2015", "D"),
    Rule("heat_illness_offset_f", 5.0, "°F", "Thresholds drop this much after a heat illness.",
         "System default", "D"),
    # ── nutrition ──────────────────────────────────────────────────────────
    Rule("ea_deficit_floor", 30, "kcal/kg FFM", "Planned energy availability on a deficit day never below "
         "this (planned, not measured).", "Loucks et al. 2011; Mountjoy et al. 2018 (IOC RED-S)", "B"),
    Rule("ea_hard_floor", 25, "kcal/kg FFM", "Planned energy availability is never below this.",
         "Mountjoy et al. 2018 (IOC RED-S)", "B"),
    Rule("carbs_g_per_kg", {"rest": 3.5, "lift": 3.75, "easy": 4.5, "lift_easy": 5.0, "key": 6.0,
                            "long_run": 7.0, "long_ride": 9.0}, "g/kg/day",
         "Daily carbohydrate by day type.", "Thomas et al. 2016 (ACSM nutrition position stand)", "B"),
    Rule("weight_step_kcal", 175, "kcal/day", "Weekly calorie correction step when weight moves too fast or "
         "too slow two weeks running.", "Nutrition report (Oct 2026); coaching convention", "C"),
    Rule("weight_max_adjust_kcal", 400, "kcal/day", "Largest total calorie correction.",
         "Nutrition report (Oct 2026)", "C"),
    # ── strength ───────────────────────────────────────────────────────────
    Rule("strength_backoff", 0.90, "fraction", "Back-off sets at this share of the top set.",
         "Strength report (Oct 2026)", "C"),
    Rule("strength_cut_cap_lb", 5.0, "lb/week", "Largest weekly top-set increase while in a deficit.",
         "Strength report (Oct 2026)", "C"),
    Rule("strength_reentry", (0.75, 0.85, 0.925, 0.975), "fraction by week",
         "Return to a lift after 3+ weeks off: these shares of the last working load over 4 weeks.",
         "Strength report (Oct 2026)", "C"),
    Rule("strength_gap_days", 21, "days", "A lift not done this long restarts with re-entry loads.",
         "Strength report (Oct 2026)", "C"),
    # ── zones (Friel, % of LTHR; high bound exclusive) ─────────────────────
    Rule("run_hr_zones", (("Z1", 0.00, 0.85), ("Z2", 0.85, 0.90), ("Z3", 0.90, 0.95), ("Z4", 0.95, 1.00),
                          ("Z5a", 1.00, 1.03), ("Z5b", 1.03, 1.07), ("Z5c", 1.07, 2.00)),
         "fraction of run LTHR", "Run heart-rate zones from the 30-min LTHR test.", FRIEL, "C"),
    Rule("bike_hr_zones", (("Z1", 0.00, 0.81), ("Z2", 0.81, 0.90), ("Z3", 0.90, 0.94), ("Z4", 0.94, 1.00),
                           ("Z5a", 1.00, 1.03), ("Z5b", 1.03, 1.07), ("Z5c", 1.07, 2.00)),
         "fraction of bike LTHR", "Bike heart-rate zones (outdoor rides).", FRIEL, "C"),
    # ── zones and fitness tests (outside review, Card 2) ─────────────────────
    Rule("easy_hr_floor", 125, "bpm", "PROVISIONAL bottom of the easy-run HR range on the watch until the "
         "LTHR test.", "System default", "D"),
    Rule("run_pace_zones", (("Z1", 1.29, 9.99), ("Z2", 1.14, 1.29), ("Z3", 1.06, 1.14), ("Z4", 1.01, 1.06),
                            ("Z5a", 0.97, 1.01), ("Z5b", 0.90, 0.97), ("Z5c", 0.00, 0.90)),
         "time per mile as a fraction of threshold pace (fast, slow)",
         "Run pace zones from the LTHR test's threshold pace (Z1 slower than 129%).", FRIEL, "C"),
    Rule("css_zone_offsets", {"Z1": 10, "Z2": 5, "Z3": 0, "Z4": -3, "Z5": -6}, "s per 100 vs CSS",
         "Swim target pace per zone from CSS (Z3 is CSS ±2 s).", "Coaching convention; CSS method "
         "(Wakayoshi et al.)", "C"),
    Rule("power_zones", (("Z1", 0.00, 0.56), ("Z2", 0.56, 0.76), ("Z3", 0.76, 0.91), ("Z4", 0.91, 1.06),
                         ("Z5", 1.06, 1.21), ("Z6", 1.21, 9.99)), "fraction of FTP",
         "Indoor bike power zones (KICKR CORE only; outdoor rides use bike HR zones).",
         "Coggan & Allen, Training and Racing with a Power Meter (2019)", "C"),
    Rule("ftp_factor", 0.95, "fraction", "FTP = this share of the 20-minute test's average power.",
         "Coggan & Allen 2019", "C"),
    Rule("bike_lthr_factor", 0.95, "fraction", "Bike LTHR = this share of the 20-minute test's average HR.",
         f"{FRIEL} (approximation)", "C"),
    Rule("retest_weeks", 8, "weeks", "Re-test each sport this often (never in race week).",
         "Coaching convention", "C"),
    Rule("test_hr_coverage", 0.9, "fraction", "A run or bike test needs heart rate on at least this share "
         "of the effort, or it doesn't count.", "System default", "D"),
    Rule("test_max_climb_m_per_mi", 30, "m per mile", "A run test with more climbing than this doesn't count "
         "(threshold pace needs flat ground).", "System default", "D"),
    Rule("test_min_rpe", 8, "RPE", "A run or bike test logged below this effort doesn't count.",
         "System default", "D"),
    Rule("zone_change_confirm_bpm", 8, "bpm", "If a run test moves the top of easy HR by more than this, "
         "Patrick confirms before the new zones apply.", "Outside review, Card 2", "D"),
)

_BY_ID = {r.id: r for r in RULES}


def get(rule_id: str) -> Rule:
    return _BY_ID[rule_id]


def value(rule_id: str) -> Any:
    return _BY_ID[rule_id].value


def render() -> str:
    """The registry as plain text for Pat-GPT's prompt."""
    lines = [f"RULES ON FILE (version {VERSION}). Quote these by name with their source and grade; never "
             "invent a threshold. If a question needs a number that isn't here or in his data, say "
             "'no rule on file' and suggest asking Claude to add one."]
    for r in RULES:
        lines.append(f"- {r.id} = {r.value} {r.units}: {r.what} Source: {r.source} (grade {r.grade}).")
    return "\n".join(lines)
