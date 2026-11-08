"""Planned sessions -> Garmin calendar (app/integrations/garmin_push.py), with a fake Garmin."""
from datetime import date, timedelta

import pytest

from app.integrations import garmin_push as gp
from tests.test_ingest import _fresh_db, needs_db

MON = date(2026, 11, 30)


class FakeGarmin:
    def __init__(self):
        self.workouts, self.scheduled, self.deleted, self.next_id = {}, {}, [], 100

    def upload_workout(self, w):
        self.next_id += 1
        self.workouts[self.next_id] = w
        return {"workoutId": self.next_id}

    def schedule_workout(self, wid, day):
        self.scheduled[wid] = day

    def delete_workout(self, wid):
        self.deleted.append(wid)
        self.workouts.pop(wid, None)
        self.scheduled.pop(wid, None)


@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        c.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                     "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                     return_started_on = '2026-10-15', return_ends_on = '2026-11-04'""")
        yield c


def _plan(c, d, sport, title, minutes, zone="Z2"):
    return c.execute("""insert into planned_workouts (plan_date, sport, title, duration_min, max_zone, status, source)
                        values (%s, %s, %s, %s, %s, 'planned', 'generator') returning id""",
                     (d, sport, title, minutes, zone)).fetchone()["id"]


def test_workout_shape():
    w = gp.build({"plan_date": MON, "sport": "run", "title": "Easy run", "duration_min": 44, "max_zone": "Z2"})
    steps = w["workoutSegments"][0]["workoutSteps"]
    assert w["workoutName"] == "TC Mon Nov 30 - Easy run" and w["sportType"]["sportTypeKey"] == "running"
    assert [s["stepType"]["stepTypeKey"] for s in steps] == ["warmup", "interval", "cooldown"]
    assert (steps[1]["targetValueOne"], steps[1]["targetValueTwo"]) == (125, 145)
    assert sum(s["endConditionValue"] for s in steps) == 44 * 60
    hard = gp.build({"plan_date": MON, "sport": "run", "title": "Run test", "duration_min": 50, "max_zone": "Z4"})
    assert "targetValueOne" not in hard["workoutSegments"][0]["workoutSteps"][1]


@needs_db
def test_sync_creates_updates_removes_and_stays_quiet(conn):
    g = FakeGarmin()
    assert gp.sync(conn, MON, client=g)["created"] == 0 and not g.workouts      # nothing planned yet
    run = _plan(conn, MON + timedelta(days=1), "run", "Easy run", 40)
    ride = _plan(conn, MON + timedelta(days=5), "bike", "Long ride", 120)
    lift = _plan(conn, MON + timedelta(days=1), "strength", "Strength: Push", 45)
    r = gp.sync(conn, MON, client=g)
    assert r["created"] == 2 and not r["errors"] and len(g.scheduled) == 2      # strength isn't sent
    assert gp.sync(conn, MON, client=FakeGarmin()) == {"created": 0, "updated": 0, "removed": 0,
                                                       "unchanged": 2, "errors": []}   # nothing changed: no calls
    # A re-plan lengthens the ride and supersedes the run (moved to Thursday).
    conn.execute("update planned_workouts set duration_min = 150 where id = %s", (ride,))
    conn.execute("update planned_workouts set status = 'superseded' where id = %s", (run,))
    _plan(conn, MON + timedelta(days=3), "run", "Easy run", 40)
    r = gp.sync(conn, MON, client=g)
    assert (r["created"], r["updated"], r["removed"]) == (1, 1, 1) and len(g.deleted) == 2
    assert sorted(g.scheduled.values()) == ["2026-12-03", "2026-12-05"]
    assert conn.execute("select count(*) n from garmin_pushed").fetchone()["n"] == 2
    assert lift


@needs_db
def test_off_or_before_the_start_date_sends_nothing(conn):
    g = FakeGarmin()
    _plan(conn, date(2026, 11, 17), "run", "Easy run", 40)
    assert gp.sync(conn, date(2026, 11, 16), days=7, client=g)["skipped"] == "starts 2026-11-23"
    conn.execute("""update profile set user_prefs = user_prefs || '{"garmin_push": {"enabled": false}}'""")
    assert gp.sync(conn, MON, client=g)["skipped"] == "turned off" and not g.workouts


@needs_db
def test_one_failure_does_not_block_the_rest(conn):
    class Flaky(FakeGarmin):
        def upload_workout(self, w):
            if "swim" in w["sportType"]["sportTypeKey"]:
                raise RuntimeError("Garmin said no")
            return super().upload_workout(w)
    _plan(conn, MON + timedelta(days=1), "swim", "Easy swim", 35)
    _plan(conn, MON + timedelta(days=2), "bike", "Easy ride (Z2)", 50)
    r = gp.sync(conn, MON, client=Flaky())
    assert r["created"] == 1 and len(r["errors"]) == 1 and "Garmin said no" in r["errors"][0]
