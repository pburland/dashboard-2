"""Regression cases built from Patrick's real August–September 2026 runs."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.analysis import heat, overreach
from app.analysis.flags import Severity
from app.analysis.load import session_share, trimp
from app.analysis.overreach import Lap, decoupling, parse_pace

RUNS = [  # (date, miles) from the Garmin export
    (date(2026, 8, 23), 3.20), (date(2026, 8, 25), 4.40), (date(2026, 8, 27), 4.65),
    (date(2026, 8, 29), 8.12), (date(2026, 9, 1), 4.05), (date(2026, 9, 4), 10.05),
    (date(2026, 9, 6), 6.49), (date(2026, 9, 9), 4.08), (date(2026, 9, 10), 4.10),
]


def test_sep13_long_run_is_flagged_before_it_happens():
    f = overreach.long_run_jump(12.5, date(2026, 9, 13), RUNS)
    assert f.severity is Severity.STOP
    assert f.data["prior_longest_mi"] == 10.05
    assert round(f.data["jump"], 2) == 0.24
    assert f.data["suggested_cap_mi"] == 11.1


def test_sep4_long_run_was_also_a_jump():
    f = overreach.long_run_jump(10.05, date(2026, 9, 4), RUNS)
    assert f and f.data["prior_longest_mi"] == 8.12


def test_modest_long_run_passes():
    assert overreach.long_run_jump(11.0, date(2026, 9, 13), RUNS) is None


def test_sep13_session_share_from_heart_rate():
    # Week of Sep 7-13 runs + swim from Garmin: (minutes, avg HR). Resting HR 55
    # is a placeholder until Oura supplies the real baseline; max 190 observed.
    rest, mx = 55, 190
    long_run = trimp(130.0, 144, rest, mx)
    others = [trimp(40.3, 151, rest, mx), trimp(43.6, 143, rest, mx), trimp(25.9, 144, rest, mx)]
    share = session_share(long_run, others).share
    assert share > 0.5
    assert overreach.session_share_flag(share).severity is Severity.STOP


def test_decoupling_mile1_133_to_mile12_153():
    # Even pace, HR climbing 133 -> 153 across 12 one-mile laps. That is a 15%
    # rise first mile to last, but Friel's half-vs-half decoupling is ~7%:
    # still over the 5% aerobic limit, so the run is flagged.
    laps = [Lap(1609.3, 624, 133 + i * (20 / 11)) for i in range(12)]
    d = decoupling(laps)
    assert 0.06 < d < 0.08
    assert overreach.decoupling_flag(d).severity is Severity.WARN


def test_steady_run_does_not_decouple():
    laps = [Lap(1609.3, 620, 140) for _ in range(8)]
    assert decoupling(laps) == 0.0
    assert overreach.decoupling_flag(0.0) is None


def test_easy_run_too_fast():
    # Sep 9: 9:52/mi logged as easy against a 10:15-11:00 easy range.
    f = overreach.easy_too_fast(parse_pace("9:52"), parse_pace("10:15"))
    assert f and "23s/mi faster" in f.message
    assert overreach.easy_too_fast(parse_pace("10:20"), parse_pace("10:15")) is None


def test_planned_27_after_20_7_is_a_ramp():
    f = overreach.weekly_ramp(27, [17.2, 20.6, 20.7])
    assert f and round(f.data["ramp"], 2) == 0.30


ET = ZoneInfo("America/New_York")


def _day(temps_rh):
    return [heat.HourlyWeather(datetime(2026, 9, 13, h, tzinfo=ET), t, rh)
            for h, (t, rh) in temps_rh.items()]


def test_heat_index_matches_nws_table():
    assert abs(heat.heat_index_f(90, 60) - 100) <= 1
    assert abs(heat.heat_index_f(85, 50) - 86) <= 1


def test_sep13_start_is_no_go_with_earlier_start_suggested():
    hours = _day({5: (68, 85), 6: (69, 85), 7: (72, 78), 8: (76, 70), 9: (80, 62),
                  10: (83, 56), 11: (85, 52), 12: (87, 48), 13: (88, 46)})
    f = heat.go_no_go(hours, datetime(2026, 9, 13, 10, 9, tzinfo=ET), 130, kind="long")
    assert f.severity is Severity.STOP
    assert "Start by 6:30 AM" in f.message   # latest start that stays under 78°F


def test_cool_morning_is_go():
    hours = _day({6: (62, 70), 7: (64, 68), 8: (66, 65), 9: (68, 60)})
    assert heat.go_no_go(hours, datetime(2026, 9, 13, 6, 30, tzinfo=ET), 120, kind="long") is None


def test_thresholds_tighten_during_return():
    hours = _day({8: (80, 50), 9: (81, 50)})
    start = datetime(2026, 9, 13, 8, 0, tzinfo=ET)
    assert heat.go_no_go(hours, start, 45, kind="easy") is None
    assert heat.go_no_go(hours, start, 45, kind="easy", returning=True) is not None
