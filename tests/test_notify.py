"""Phone notifications: rules, timing and content (needs TEST_DATABASE_URL)."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from psycopg.types.json import Jsonb

from app import notify
from tests.test_ingest import _fresh_db, _history, needs_db

ET = ZoneInfo("America/New_York")
SENT: list[dict] = []


def fake_send(conn, sub, msg, contact):
    SENT.append(msg)


@pytest.fixture
def conn(monkeypatch):
    SENT.clear()
    monkeypatch.setattr("app.integrations.webpush.send", fake_send)
    with _fresh_db(monkeypatch, None) as c:
        c.execute("""insert into push_subscriptions (endpoint, keys) values ('https://web.push.apple.com/x',
                     '{"p256dh":"x","auth":"y"}')""")
        c.commit()
        yield c


def at(d, h, m=0):
    return datetime.combine(d, time(h, m), ET)


D = date(2026, 11, 30)


@needs_db
def test_quiet_hours_and_daily_limit_fold_extras(conn):
    for i in range(6):
        notify.queue(conn, "safety", f"Alert {i}", "x", dedupe=f"a{i}")
    conn.commit()
    assert notify.dispatch(conn, at(D, 22)) == []                  # quiet hours: waits
    out = notify.dispatch(conn, at(D, 7))
    assert len(out) == 4 and out[-1]["title"] == "3 training updates"     # 3 singles + 1 folded
    notify.queue(conn, "safety", "Late", "x", dedupe="late")
    conn.commit()
    assert notify.dispatch(conn, at(D, 12)) == []                  # 4 already sent today
    assert notify.dispatch(conn, at(D + timedelta(days=1), 6))[0]["title"] == "Late"


@needs_db
def test_switched_off_kinds_and_duplicates_are_not_queued(conn):
    conn.execute("""update profile set notification_prefs = notification_prefs || '{"report": false}'""")
    assert not notify.queue(conn, "report", "Report", "x", dedupe="r1")
    assert notify.queue(conn, "safety", "S", "x", dedupe="s1")
    assert not notify.queue(conn, "safety", "S", "x", dedupe="s1")


@needs_db
def test_test_button_ignores_quiet_hours_but_sends_nothing_else(conn):
    notify.queue(conn, "safety", "Queued alert", "x", dedupe="q")
    notify.queue(conn, "test", "Test notification", "x")
    conn.commit()
    out = notify.dispatch(conn, at(D, 23), only_tests=True)
    assert [m["title"] for m in out] == ["Test notification"]


@needs_db
def test_evening_workout_and_checkin_reminder(conn, monkeypatch):
    from app.planning import generator as g
    conn.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                    "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                    return_started_on = '2026-10-15', return_ends_on = '2026-11-04'""")
    _history(conn)
    monkeypatch.setattr("app.clock.today", lambda: D)
    g.generate(conn, D, weeks=1, today=D - timedelta(days=1), use_calendar=False)
    tue = D + timedelta(days=1)
    n = notify.evening(conn, D)
    w = conn.execute("select title, body from notifications where kind = 'workout'").fetchone()
    assert w["title"] == "Tomorrow" and "best" in w["body"]
    rem = conn.execute("select not_before, url, data from notifications where kind = 'checkin'").fetchall()
    assert n == 1 + len(rem) and rem and all(r["url"].startswith("/?checkin=") for r in rem)
    # Checked in already: the reminder is dropped when due.
    pid = rem[0]["data"]["planned_workout_id"]
    conn.execute("insert into check_ins (planned_workout_id, check_in_on, rpe, felt) values (%s, %s, 4, 'good')",
                 (pid, tue))
    conn.commit()
    notify.dispatch(conn, max(r["not_before"] for r in rem) + timedelta(minutes=1))
    status = conn.execute("select status from notifications where kind = 'checkin' and (data->>'planned_workout_id')::int = %s",
                          (pid,)).fetchone()["status"]
    assert status == "skipped"


@needs_db
def test_nothing_the_night_before_a_rest_or_hold_day(conn):
    assert notify.evening(conn, date(2026, 10, 5)) == 0             # mono hold
    assert not conn.execute("select 1 from notifications where kind = 'workout'").fetchone()


@needs_db
def test_clearance_nudge_on_the_day_and_every_3_days(conn):
    assert notify.clearance(conn, date(2026, 10, 14)) == 0
    assert notify.clearance(conn, date(2026, 10, 15)) == 1
    assert notify.clearance(conn, date(2026, 10, 16)) == 0
    assert notify.clearance(conn, date(2026, 10, 18)) == 1


@needs_db
def test_morning_update_only_when_something_changed(conn):
    d = date(2026, 12, 1)
    conn.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                    "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                    return_started_on = '2026-10-15', return_ends_on = '2026-11-04'""")
    assert notify.morning(conn, d, at(d, 0) - timedelta(hours=4)) == 0
    conn.execute("insert into recovery (day, readiness, resting_hr) values (%s, 62, 47)", (d,))
    assert notify.morning(conn, d, at(d, 0) - timedelta(hours=4)) == 1
    body = conn.execute("select title, body from notifications where dedupe_key = %s", (f"safety:{d}",)).fetchone()
    assert body["title"] == "Today: easy only" and "readiness 62" in body["body"]


@needs_db
def test_tick_runs_each_job_once_a_day(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "evening", lambda c, d: calls.append(d) or 0)
    notify.tick(conn, at(D, 20, 31))
    notify.tick(conn, at(D, 20, 45))
    assert calls == [D]


@needs_db
def test_skip_marks_skipped_and_notes_illness(conn):
    from app import checkins
    pid = conn.execute("""insert into planned_workouts (plan_date, sport, title, duration_min, distance_mi, is_key,
                          is_long, structure, source) values ('2026-12-05','run','Long run',90,8,true,true,'{}','generator')
                          returning id""").fetchone()["id"]
    r = checkins.skip(conn, pid, "sick", date(2026, 12, 5))
    assert "fit it in later" in r["message"] and "illness" in r["message"]
    assert conn.execute("select status from planned_workouts where id = %s", (pid,)).fetchone()["status"] == "skipped"
    assert conn.execute("select type from weekly_notes where source = 'checkin'").fetchone()["type"] == "illness"
    with pytest.raises(ValueError):
        checkins.skip(conn, pid, None, date(2026, 12, 5))


@needs_db
def test_clearance_button_needs_all_three_and_starts_the_return(conn, monkeypatch):
    from fastapi.testclient import TestClient
    from app import db, main
    from tests.test_ingest import DB
    monkeypatch.setenv("SUPABASE_DB_URL", DB)
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(main, "_replan_in_background", lambda trigger="manual": None)
    monkeypatch.setattr("app.clock.today", lambda: date(2026, 10, 15))
    client = TestClient(main.app)
    h = {"X-Admin-Token": "t"}
    r = client.post("/api/health/clear", headers=h, json={"physician_clearance": True, "fever_free_48h": True,
                                                         "rhr_near_baseline_3d": False})
    assert r.status_code == 400
    r = client.post("/api/health/clear", headers=h, json={"physician_clearance": True, "fever_free_48h": True,
                                                         "rhr_near_baseline_3d": True})
    assert r.status_code == 200, r.text
    assert r.json()["return_ends_on"] == "2026-11-04"              # 21 days for mono
    ep = conn.execute("select return_started_on, criteria_met from health_episodes where closed_on is null").fetchone()
    assert str(ep["return_started_on"]) == "2026-10-15" and len(ep["criteria_met"]) == 3
    assert client.post("/api/health/clear", headers=h, json={"physician_clearance": True, "fever_free_48h": True,
                                                            "rhr_near_baseline_3d": True}).status_code == 409
    db._pool.close()
