"""The coming week's workouts as an .ics feed on its own calendar (app/calendar_feed.py)."""
from datetime import timedelta

from app import calendar_feed as cf
from tests.test_garmin_push import MON, _plan, conn  # noqa: F401  (fixture)
from tests.test_ingest import needs_db


def test_key_is_stable_and_not_the_token():
    assert cf.key("abc") == cf.key("abc") != cf.key("abd")
    assert len(cf.key("abc")) == 32 and "abc" not in cf.key("abc")


@needs_db
def test_feed_holds_only_approved_weeks_as_time_blocks_without_alerts(conn):  # noqa: F811
    from app import approval
    conn.execute("delete from plan_approvals")                            # the shared fixture pre-approves
    run = _plan(conn, MON, "run", "Easy run, with strides; relaxed", 40)
    _plan(conn, MON + timedelta(days=2), "strength", "Strength: Push", 45)
    _plan(conn, MON + timedelta(days=7), "bike", "Long ride", 120)      # next week: not approved
    assert "BEGIN:VEVENT" not in cf.build(conn, MON)                      # nothing approved yet
    conn.execute("""insert into plan_approvals (week_start, sessions) values (%s, %s::jsonb)""",
                 (MON, '{"%d": {"date": "2026-11-30", "start": "2026-11-30T17:00:00-05:00", '
                       '"end": "2026-11-30T17:40:00-05:00", "label": "5–5:40 PM"}}' % run))
    ics = cf.build(conn, MON)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "X-WR-CALNAME:Training" in ics and "VALARM" not in ics
    assert ics.count("BEGIN:VEVENT") == 2 and "Long ride" not in ics
    assert "DTSTART:20261130T220000Z" in ics and "DTEND:20261130T224000Z" in ics     # 5 PM Eastern
    assert "Easy run\\, with strides\\; relaxed" in ics
    assert ics.count("DTSTART:") == 2                                     # the lift got a time worked out too
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    assert approval.week_to_approve(MON - timedelta(days=1)) == MON       # Sunday -> next week


def test_api_route_rejects_a_wrong_key(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setenv("ADMIN_TOKEN", "secret-token")
    c = TestClient(main.app)
    assert c.get("/calendar/wrong/training.ics").status_code == 404
