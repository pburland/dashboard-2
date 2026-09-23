from datetime import date

import pytest

from app.health.state import (EXIT_CRITERIA, Episode, HoldExitRefused, MorningSignals,
                              Status, begin_return, gate, record_criterion, return_volume)

HOLD = Episode(started_on=date(2026, 9, 13), reason="heat strain + fever")
NONE = MorningSignals()


def met(ep: Episode, on: date) -> Episode:
    for k in EXIT_CRITERIA:
        ep = record_criterion(ep, k, on)
    return ep


def test_hold_suppresses_all_prescriptions():
    g = gate(HOLD, NONE, date(2026, 9, 23))
    assert g.status is Status.HOLD
    assert not g.prescriptions_allowed
    assert any("Fever-free" in r for r in g.reasons)


def test_good_morning_signals_do_not_lift_a_hold():
    g = gate(HOLD, MorningSignals(readiness=90), date(2026, 9, 23))
    assert g.status is Status.HOLD


def test_exit_refused_until_every_criterion_recorded():
    partial = record_criterion(HOLD, "fever_free_48h", date(2026, 9, 25))
    with pytest.raises(HoldExitRefused) as e:
        begin_return(partial, date(2026, 9, 26))
    assert set(e.value.missing) == {"physician_clearance", "rhr_near_baseline_3d"}


def test_unknown_criterion_rejected():
    with pytest.raises(KeyError):
        record_criterion(HOLD, "feels_fine", date(2026, 9, 25))


def test_return_ramps_and_caps_then_ends():
    ep = begin_return(met(HOLD, date(2026, 9, 30)), date(2026, 10, 1))
    # 18-day hold -> 18-day return (within the 7-21 day bounds)
    assert ep.return_ends_on == date(2026, 10, 18)
    first = gate(ep, NONE, date(2026, 10, 1))
    assert first.status is Status.RETURN
    assert first.intensity_ceiling == "Z2"
    assert first.volume_multiplier == 0.5
    assert not first.long_run_growth_allowed
    assert return_volume(ep, date(2026, 10, 18)) == 0.9
    assert gate(ep, NONE, date(2026, 10, 19)).status is Status.CLEAR


def test_return_cannot_predate_clearance():
    with pytest.raises(ValueError):
        begin_return(met(HOLD, date(2026, 10, 2)), date(2026, 10, 1))


def test_caution_from_morning_signals():
    g = gate(None, MorningSignals(resting_hr=58, resting_hr_baseline=52,
                                  temp_deviation_c=0.7), date(2026, 11, 1))
    assert g.status is Status.CAUTION
    assert g.intensity_ceiling == "Z2"
    assert len(g.reasons) == 2


def test_clear():
    assert gate(None, MorningSignals(readiness=85), date(2026, 11, 1)).status is Status.CLEAR
