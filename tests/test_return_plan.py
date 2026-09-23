"""The first two weeks after the Sep 23, 2026 clearance, checked by the same
validator every generated plan goes through. Mirrors db/seed/002."""
from datetime import date

from app.analysis.flags import Severity
from app.analysis.overreach import long_run_jump
from app.analysis.validator import History, PlannedSession as S, validate_week
from app.health.state import EXIT_CRITERIA, Episode, MorningSignals, Status, begin_return, gate, record_criterion

CLEARED = date(2026, 9, 23)
RUNS = [(date(2026, 8, 29), 8.12), (date(2026, 9, 4), 10.05), (date(2026, 9, 6), 6.49),
        (date(2026, 9, 9), 4.08), (date(2026, 9, 10), 4.10), (date(2026, 9, 13), 12.5)]
HIST = History(runs=RUNS, weekly_run_mi=[17.2, 20.6, 20.7])


def episode() -> Episode:
    ep = Episode(started_on=date(2026, 9, 13), reason="heat strain + fever")
    for k in EXIT_CRITERIA:
        ep = record_criterion(ep, k, CLEARED)
    return begin_return(ep, CLEARED)


WEEK1 = [
    S(date(2026, 9, 23), "run", "Easy return run", 27, distance_mi=2.5),
    S(date(2026, 9, 24), "strength", "Upper body", 45, zone="Z1"),
    S(date(2026, 9, 25), "run", "Easy run", 33, distance_mi=3.0),
    S(date(2026, 9, 26), "run", "Long run (easy)", 57, distance_mi=5.0, is_long=True),
    S(date(2026, 9, 27), "swim", "Easy swim", 25),
]
WEEK2 = [
    S(date(2026, 9, 28), "strength", "Lower (light)", 40, zone="Z1", heavy_lower=True),
    S(date(2026, 9, 29), "run", "Easy run", 38, distance_mi=3.5),
    S(date(2026, 9, 30), "run", "Easy run", 33, distance_mi=3.0),
    S(date(2026, 9, 30), "strength", "Upper body", 45, zone="Z1"),
    S(date(2026, 10, 1), "run", "Easy run", 38, distance_mi=3.5),
    S(date(2026, 10, 3), "run", "Long run (easy)", 90, distance_mi=8.0, is_long=True),
    S(date(2026, 10, 4), "bike", "Easy spin", 30),
]


def test_return_phase_is_ten_days():
    ep = episode()
    assert ep.return_ends_on == date(2026, 10, 2)
    g = gate(ep, MorningSignals(), CLEARED)
    assert g.status is Status.RETURN and g.volume_multiplier == 0.5


def test_week1_passes_with_no_flags():
    v = validate_week(WEEK1, HIST, gate(episode(), MorningSignals(), CLEARED))
    assert not v.suppressed
    assert all(fl == [] for fl in v.flags.values()), v.flags
    assert v.week_flags == []


def test_week2_passes_with_no_flags():
    v = validate_week(WEEK2, HIST, gate(episode(), MorningSignals(), date(2026, 9, 28)))
    assert all(fl == [] for fl in v.flags.values()), v.flags


def test_long_run_over_return_cap_is_stopped():
    v = validate_week([S(date(2026, 9, 26), "run", "Long", 100, distance_mi=9.0, is_long=True)],
                      HIST, gate(episode(), MorningSignals(), date(2026, 9, 26)))
    assert "long_run_cap" in {f.kind for f in v.flags[0]}      # 9.0 > 8.75


def test_sixteen_miles_by_oct7_is_stopped():
    f = long_run_jump(16.0, date(2026, 10, 7), RUNS)
    assert f.severity is Severity.STOP
    assert f.data["prior_longest_mi"] == 12.5
    assert round(f.data["jump"], 2) == 0.28
