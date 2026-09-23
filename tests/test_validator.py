from datetime import date

from app.analysis.validator import History, PlannedSession, validate_week
from app.health.state import (EXIT_CRITERIA, Episode, MorningSignals, begin_return, gate,
                              record_criterion)

HIST = History(runs=[(date(2026, 8, 29), 8.12), (date(2026, 9, 4), 10.05)],
               weekly_run_mi=[17.2, 20.6, 20.7])
HOLD = Episode(started_on=date(2026, 9, 13), reason="fever")


def week(long_mi=12.5, long_zone="Z2"):
    return [
        PlannedSession(date(2026, 9, 7), "strength", "Lower", 50, heavy_lower=True),
        PlannedSession(date(2026, 9, 9), "run", "Easy", 40, distance_mi=4),
        PlannedSession(date(2026, 9, 10), "run", "Easy", 42, distance_mi=4),
        PlannedSession(date(2026, 9, 11), "strength", "Lower (moved)", 45, heavy_lower=True),
        PlannedSession(date(2026, 9, 13), "run", "Long run", 130, zone=long_zone,
                       distance_mi=long_mi, is_long=True),
    ]


def test_hold_returns_no_sessions_at_all():
    v = validate_week(week(), HIST, gate(HOLD, MorningSignals(), date(2026, 9, 21)))
    assert v.suppressed and v.sessions == []
    assert v.week_flags and v.week_flags[0].kind == "health_hold"


def test_sep13_week_flags_before_the_run():
    v = validate_week(week(), HIST, gate(None, MorningSignals(), date(2026, 9, 7)))
    kinds = {f.kind for f in v.flags[4]}
    assert {"long_run_jump", "session_load_share"} <= kinds
    assert [f.kind for f in v.flags[3]] == ["strength_before_long"]
    assert v.flags[0] == []          # Monday lower body is 6 days clear


def test_return_caps_intensity_and_long_run():
    ep = HOLD
    for k in EXIT_CRITERIA:
        ep = record_criterion(ep, k, date(2026, 9, 30))
    ep = begin_return(ep, date(2026, 10, 1))
    v = validate_week(week(long_mi=9, long_zone="Z3"), HIST,
                      gate(ep, MorningSignals(), date(2026, 10, 4)))
    kinds = {f.kind for f in v.flags[4]}
    assert {"intensity_cap", "long_run_cap"} <= kinds   # 9 mi > 70% of 10.05


def test_caution_freezes_long_run_growth_without_return_cap():
    g = gate(None, MorningSignals(readiness=60), date(2026, 11, 7))
    ok = validate_week([PlannedSession(date(2026, 11, 7), "run", "Long run", 100,
                                       distance_mi=10.0, is_long=True)], HIST, g)
    assert "long_run_cap" not in {f.kind for f in ok.flags[0]}      # 10.0 <= 10.05
    grow = validate_week([PlannedSession(date(2026, 11, 7), "run", "Long run", 110,
                                         distance_mi=10.5, is_long=True)], HIST, g)
    assert "long_run_cap" in {f.kind for f in grow.flags[0]}
