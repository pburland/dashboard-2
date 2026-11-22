"""Relapse watch and the trip-paused return (outside review, Card 1)."""
import math
from datetime import date, timedelta

from app.health import state, watch

D = date(2026, 12, 10)


def _days(n, end=D):
    return [end - timedelta(days=i) for i in range(n)]


def test_one_signal_is_shown_two_signals_ease_off():
    rhr = {d: 52 for d in _days(40)} | {d: 60 for d in _days(9)}            # baseline 52, up 8 for 9 days
    w = watch.assess(D, rhr=rhr, hrv={}, runs=[], baseline=52, hold=None, jet_lag=set())
    assert w.caution is None and len(w.notes) == 1 and "resting HR" in w.notes[0]
    runs = [(D - timedelta(days=3), 0.07), (D - timedelta(days=1), 0.06)]
    w2 = watch.assess(D, rhr=rhr, hrv={}, runs=runs, baseline=52, hold=None, jet_lag=set())
    assert w2.caution and "Easing off for 2 days" in w2.caution
    # Two days after the trigger it has run its course.
    w3 = watch.assess(D + timedelta(days=2), rhr={d: 52 for d in _days(40, D + timedelta(days=2))},
                      hrv={}, runs=runs, baseline=52, hold=None, jet_lag=set())
    assert w3.caution is None


def test_short_lived_or_single_signals_do_nothing():
    rhr = {d: 52 for d in _days(40)} | {D: 70}                              # one bad morning
    runs = [(D - timedelta(days=1), 0.09)]                                   # one drifting run
    w = watch.assess(D, rhr=rhr, hrv={}, runs=runs, baseline=52, hold=None, jet_lag=set())
    assert w.caution is None and w.notes == ()


def test_hrv_needs_a_baseline_outside_the_hold_and_jet_lag_does_not_count():
    hrv = {d: 70.0 for d in _days(80)}
    w = watch.assess(D, rhr={}, hrv=hrv, runs=[], baseline=None, hold=(D - timedelta(days=80), D),
                     jet_lag=set())
    assert w.learning_hrv and w.notes == ()                                  # all nights are in the hold
    low = hrv | {d: 40.0 + (i % 3) for i, d in enumerate(_days(8))}
    hi = {d: 70.0 + (i % 5) for i, d in enumerate(_days(80))} | {d: v for d, v in low.items() if d >= D - timedelta(days=7)}
    w2 = watch.assess(D, rhr={}, hrv=hi, runs=[], baseline=None, hold=None, jet_lag=set())
    assert not w2.learning_hrv and any("HRV" in n for n in w2.notes)
    rhr = {d: 52 for d in _days(40)} | {d: 60 for d in _days(9)}
    lagged = watch.assess(D, rhr=rhr, hrv=hi, runs=[], baseline=52, hold=None, jet_lag=set(_days(7)))
    assert lagged.caution is None and all("not counted" in n for n in lagged.notes)


def test_jet_lag_days_follow_big_time_zone_changes():
    stops = [{"start_date": date(2026, 11, 7), "end_date": date(2026, 11, 20), "place": "Kyoto", "lat": 35.0,
              "lng": 135.7, "tz_name": "Asia/Tokyo", "sports": ["run"], "note": ""}]
    days = [date(2026, 11, 21) + timedelta(days=i) for i in range(6)]
    lag = watch.jet_lag_days(stops, "America/New_York", days)
    assert lag == {date(2026, 11, 21), date(2026, 11, 22), date(2026, 11, 23)}


def test_trip_days_pause_the_return():
    start, ends = date(2026, 11, 23), date(2026, 12, 13)
    trip = {date(2026, 12, 4), date(2026, 12, 5), date(2026, 12, 6)}
    end, paused = state.extend_for_trips(start, ends, trip)
    assert end == date(2026, 12, 16) and paused == frozenset(trip)
    ep = state.Episode(started_on=date(2026, 9, 15), reason="mono", return_started_on=start,
                       return_ends_on=end, return_paused=paused)
    assert state.return_volume(ep, start) == 0.5
    # The ramp doesn't move over the trip.
    assert state.return_volume(ep, date(2026, 12, 4)) == state.return_volume(ep, date(2026, 12, 7))
    assert state.return_volume(ep, end) == 0.9
    assert state.status(ep, state.MorningSignals(), date(2026, 12, 15)) is state.Status.RETURN
    assert state.status(ep, state.MorningSignals(), date(2026, 12, 17)) is state.Status.CLEAR


def test_watch_reason_sets_caution_when_clear():
    g = state.gate(None, state.MorningSignals(watch_reason="Easing off for 2 days: x."), D)
    assert g.status is state.Status.CAUTION and g.intensity_ceiling == "Z2" and not g.long_run_growth_allowed


from tests.test_ingest import needs_db, conn_now  # noqa: E402,F401  (fixture)


@needs_db
def test_return_restarts_nov_23_and_trips_extend_it(conn_now):  # noqa: F811
    from app import db
    ep = db.open_episode(conn_now, date(2026, 11, 23))
    assert ep.return_started_on == date(2026, 11, 23) and ep.return_ends_on == date(2026, 12, 14)  # Nov 28 drive
    g = state.gate(ep, state.MorningSignals(), date(2026, 11, 23))
    assert g.status is state.Status.RETURN and g.volume_multiplier == 0.5 and g.intensity_ceiling == "Z2"
    # Trips where he can still train don't pause it (Connecticut, seed 022, ran Nov 22-27) ...
    conn_now.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports)
                        values ('2026-12-04', '2026-12-04', 'Boston', 42.36, -71.06, 'America/New_York', '{run}')""")
    # ... days with no training do: the Nov 28 drive, and these two flight days.
    conn_now.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports)
                        values ('2026-12-05', '2026-12-06', 'Flights', 42.36, -71.06, 'America/New_York', '{}')""")
    assert db.open_episode(conn_now, date(2026, 11, 23)).return_ends_on == date(2026, 12, 16)
    assert watch.load(conn_now, date(2026, 11, 23)).caution is None
