"""Feature 3: post-workout check-in (needs TEST_DATABASE_URL)."""
from datetime import date, timedelta

import pytest

from tests.test_ingest import DB, _fresh_db, needs_db  # noqa: F401  (shared DB fixture helpers)

MON = date(2026, 11, 9)      # after the return phase ends Nov 4


@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        # Cleared: the return phase is running, so workouts are prescribed.
        c.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                     "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                     return_started_on = '2026-10-15', return_ends_on = '2026-11-04' where closed_on is null""")
        yield c


def _session(c, d, zone="Z2", sport="run", title="Easy run"):
    a = c.execute("""insert into activities (provider, external_id, start_local, local_date, sport, distance_m,
                     duration_s, avg_hr) values ('manual', %s, %s, %s, %s, 6000, 2000, 135) returning id""",
                  (f"{d}{sport}{zone}", d, d, sport)).fetchone()["id"]
    return c.execute("""insert into planned_workouts (plan_date, sport, title, duration_min, distance_mi, max_zone,
                        status, activity_id, source) values (%s, %s, %s, 40, 3.5, %s, 'done', %s, 'generator')
                        returning id""", (d, sport, title, zone, a)).fetchone()["id"]


@needs_db
def test_bad_with_pain_caps_next_48h_then_expires(conn):
    from app import checkins, today as view
    pid = _session(conn, MON)
    assert view.build(conn, MON)["pending_checkin"]["planned_workout_id"] == pid
    r = checkins.submit(conn, planned_workout_id=pid, rpe=6, felt="bad", pain=True, pain_detail="shin")
    assert "through Wednesday" in r["effects"][0]
    tue = view.build(conn, MON + timedelta(days=1))
    assert tue["health"]["status"] == "caution" and tue["health"]["intensity_ceiling"] == "Z2"
    assert "Yesterday's check-in: felt bad + shin pain" in tue["health"]["reasons"][0]
    assert tue["pending_checkin"] is None                      # card gone for good
    assert view.build(conn, MON + timedelta(days=3))["health"]["status"] != "caution"   # Thursday: expired


@needs_db
def test_recurring_shin_pain_flags_and_notes(conn):
    from app import checkins
    a = _session(conn, MON)
    b = _session(conn, MON + timedelta(days=3), title="Long run")
    checkins.submit(conn, planned_workout_id=a, rpe=5, felt="fine", pain=True, pain_detail="Shin")
    assert not conn.execute("select 1 from flags where kind = 'recurring_pain'").fetchone()
    checkins.submit(conn, planned_workout_id=b, rpe=6, felt="fine", pain=True, pain_detail="left shin")
    f = conn.execute("select severity, message from flags where kind = 'recurring_pain'").fetchone()
    assert f["severity"] == "warn" and "left shin" in f["message"]
    n = conn.execute("select type, text from weekly_notes where source = 'checkin'").fetchall()
    assert len(n) == 1 and n[0]["type"] == "injury"


@needs_db
def test_rpe_mismatch_only_on_easy_sessions(conn):
    from app import checkins
    easy = _session(conn, MON)
    hard = _session(conn, MON + timedelta(days=1), zone="Z4", title="Intervals")
    checkins.submit(conn, planned_workout_id=easy, rpe=9, felt="fine")
    checkins.submit(conn, planned_workout_id=hard, rpe=9, felt="fine")
    rows = conn.execute("select subject_id, severity from flags where kind = 'rpe_mismatch'").fetchall()
    assert rows == [{"subject_id": easy, "severity": "warn"}]


@needs_db
def test_resubmit_is_an_upsert(conn):
    from app import checkins
    pid = _session(conn, MON)
    checkins.submit(conn, planned_workout_id=pid, rpe=9, felt="fine")
    checkins.submit(conn, planned_workout_id=pid, rpe=4, felt="good")
    assert conn.execute("select count(*) n, max(rpe) r from check_ins").fetchone() == {"n": 1, "r": 4}
    assert not conn.execute("select 1 from flags where kind = 'rpe_mismatch'").fetchone()   # corrected


@needs_db
def test_extra_activity_gets_a_card_next_morning(conn):
    from app import checkins
    a = conn.execute("""insert into activities (provider, external_id, start_local, local_date, sport, distance_m,
                        duration_s) values ('manual', 'x', %s, %s, 'bike', 20000, 3600) returning id""",
                     (MON, MON)).fetchone()["id"]
    p = checkins.pending(conn, MON + timedelta(days=1))
    assert p["activity_id"] == a and p["planned_workout_id"] is None
    checkins.submit(conn, activity_id=a, rpe=5, felt="good")
    assert checkins.pending(conn, MON + timedelta(days=1)) is None


@needs_db
def test_checkin_reason_shows_during_return_too(conn):
    from app import checkins, today as view
    d = date(2026, 10, 26)
    pid = _session(conn, d)
    checkins.submit(conn, planned_workout_id=pid, rpe=5, felt="bad")
    h = view.build(conn, d + timedelta(days=1))["health"]
    assert h["status"] == "return" and h["reasons"][0].startswith("Yesterday's check-in: felt bad")
