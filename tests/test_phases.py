from datetime import date

import pytest

from app.periodization.phases import (NoPhaseDefined, Phase, PhaseTableError,
                                      coverage_warnings, phase_for, validate_phases)

TABLE = [
    Phase("MCM Base", "base", date(2026, 8, 17), date(2026, 9, 13)),
    Phase("MCM Build", "build", date(2026, 9, 14), date(2026, 10, 11)),
    Phase("MCM Taper", "race", date(2026, 10, 12), date(2026, 10, 25)),
]


def test_valid_table_passes():
    validate_phases(TABLE)


def test_lookup_on_boundaries():
    assert phase_for(TABLE, date(2026, 9, 13)).name == "MCM Base"
    assert phase_for(TABLE, date(2026, 9, 14)).name == "MCM Build"
    assert phase_for(TABLE, date(2026, 10, 25)).name == "MCM Taper"


def test_gap_is_rejected_with_details():
    gapped = [TABLE[0], Phase("MCM Build", "build", date(2026, 9, 16), date(2026, 10, 11))]
    with pytest.raises(PhaseTableError) as e:
        validate_phases(gapped)
    assert "2 day(s) uncovered" in str(e.value)


def test_overlap_is_rejected():
    overl = [TABLE[0], Phase("MCM Build", "build", date(2026, 9, 13), date(2026, 10, 11))]
    with pytest.raises(PhaseTableError, match="overlap"):
        validate_phases(overl)


def test_unknown_kind_and_inverted_range_all_reported():
    bad = [Phase("X", "nonsense", date(2026, 9, 10), date(2026, 9, 1))]
    with pytest.raises(PhaseTableError) as e:
        validate_phases(bad)
    assert len(e.value.problems) == 2


def test_date_outside_table_never_returns_a_neighbour():
    # The prototype bug: a gap silently returned the wrong phase.
    with pytest.raises(NoPhaseDefined):
        phase_for(TABLE, date(2026, 10, 26))


def test_coverage_warning_when_table_stops_before_last_race():
    w = coverage_warnings(TABLE, date(2027, 7, 25))
    assert w and "2026-10-26" in w[0]
