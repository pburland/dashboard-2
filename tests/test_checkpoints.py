"""Season checkpoints and fixed-date fitness tests."""
from datetime import date, timedelta

import pytest

from app import checkpoints
from tests.test_ingest import _fresh_db, needs_db


@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        c.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                     "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                     return_started_on = '2026-10-15', return_ends_on = '2026-11-04'""")
        yield c


def _act(c, d, sport, meters, minutes):
    c.execute("""insert into activities (provider, external_id, start_local, local_date, sport, distance_m, duration_s)
                 values ('manual', %s, %s, %s, %s, %s, %s)""", (f"{d}{sport}", d, d, sport, meters, minutes * 60))


@needs_db
def test_jan31_go_no_go(conn):
    _act(conn, date(2027, 1, 23), "bike", 80000, 185)
    _act(conn, date(2027, 1, 24), "run", 9.5 * 1609.344, 105)
    _act(conn, date(2027, 1, 18), "swim", 1500, 40)
    c = checkpoints.check(conn, date(2027, 1, 31))
    assert c["name"].startswith("Jan 31") and c["due"] and not c["met"]
    assert [r["met"] for r in c["rows"]] == [True, True, False]          # swim short of 2,000 yd
    assert "Texas" in c["advice"] and "longest swim: 1640 yd" in checkpoints.markdown(c)
    _act(conn, date(2027, 1, 28), "swim", 1900, 45)
    assert checkpoints.check(conn, date(2027, 1, 31))["met"]


@needs_db
def test_fitness_tests_replace_the_template_session(conn):
    from app.planning import generator as g
    # Tests sit after the return to training (seed 021): swim Fri Dec 18, run Sat Dec 19.
    wp = g.plan_week(conn, date(2026, 12, 14), basis_mi=16, today=date(2026, 12, 13))
    sat = [x for x in wp.drafts if x.date == date(2026, 12, 19) and x.sport == "run"]
    assert len(sat) == 1 and sat[0].title.startswith("Run test") and sat[0].is_key and sat[0].duration_min == 50
    assert "LTHR" in sat[0].notes
    assert any(x.title.startswith("Swim test") for x in wp.drafts if x.date == date(2026, 12, 18))
    assert any(x.title.startswith("Bike test") for x in wp.drafts if x.date == date(2026, 12, 16))
    # During the return the hard tests would be skipped (Z2 cap): none planned the week of Nov 30.
    early = g.plan_week(conn, date(2026, 11, 30), basis_mi=16, today=date(2026, 11, 29))
    assert not any("test" in x.title.lower() for x in early.drafts)
