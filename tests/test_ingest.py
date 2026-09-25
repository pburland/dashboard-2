"""Ingest: pure parsing tests, plus database tests against a real Postgres
(set TEST_DATABASE_URL to an empty database; skipped otherwise)."""
import os
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.rows import dict_row

from app.ingest import evaluate, garmin as g, hevy as h, oura as o

ET = ZoneInfo("America/New_York")

# Shaped like Garmin's raw activity list and splits (camelCase).
SEP23 = {"activityId": 24474801626, "activityName": "Arlington County Running",
         "startTimeLocal": "2026-09-23 16:46:09", "startTimeGMT": "2026-09-23 20:46:09",
         "activityType": {"typeKey": "running"}, "distance": 4098.67, "duration": 1825.28,
         "movingDuration": 1815.0, "averageHR": 134.0, "maxHR": 152.0, "elevationGain": 46.0,
         "calories": 294.0}
SEP23_SPLITS = {"lapDTOs": [
    {"lapIndex": 1, "distance": 1609.34, "duration": 720.1, "averageHR": 127.0, "maxHR": 143.0},
    {"lapIndex": 2, "distance": 1609.34, "duration": 707.1, "averageHR": 138.0, "maxHR": 152.0},
    {"lapIndex": 3, "distance": 879.99, "duration": 398.1, "averageHR": 139.0, "maxHR": 147.0}]}
LONG = {"activityId": 900, "activityName": "Long", "startTimeLocal": "2026-09-26 07:05:00",
        "startTimeGMT": "2026-09-26 11:05:00", "activityType": {"typeKey": "running"},
        "distance": 6 * 1609.34, "duration": 66 * 60, "averageHR": 139.0, "maxHR": 150.0}
LONG_SPLITS = {"lapDTOs": [{"lapIndex": i + 1, "distance": 1609.34, "duration": 660,
                            "averageHR": 128 + i * 4} for i in range(6)]}   # drifts 128 -> 148
HEVY_WORKOUT = {"id": "w1", "title": "Upper", "start_time": "2026-09-24T22:10:00Z",
                "exercises": [{"title": "Bench Press (Barbell)", "exercise_template_id": "t1",
                               "sets": [{"index": 0, "type": "warmup", "weight_kg": 40, "reps": 8},
                                        {"index": 1, "type": "normal", "weight_kg": 67.5, "reps": 5, "rpe": 7}]}]}


def test_parse_activity_and_laps():
    a = g.parse_activity(SEP23)
    assert (a["external_id"], a["sport"], a["local_date"]) == ("24474801626", "run", date(2026, 9, 23))
    assert a["start_utc"].isoformat() == "2026-09-23T20:46:09+00:00"
    laps = g.parse_laps(SEP23_SPLITS)
    assert [l["avg_hr"] for l in laps] == [127.0, 138.0, 139.0]
    # snake_case payloads (as other tools present them) parse the same way
    snake = g.parse_laps({"laps": [{"lap_number": 1, "distance_meters": 1609.34,
                                    "duration_seconds": 720.1, "avg_hr_bpm": 127.0}]})
    assert snake[0]["avg_hr"] == 127.0


def test_short_run_has_no_decoupling_long_run_does():
    assert g.activity_decoupling(g.parse_activity(SEP23), g.parse_laps(SEP23_SPLITS)) is None
    d = g.activity_decoupling(g.parse_activity(LONG), g.parse_laps(LONG_SPLITS))
    assert d > 0.05


def test_sport_mapping():
    assert g.sport_of({"activityType": {"typeKey": "tennis_v2"}}) == "tennis"
    assert g.sport_of({"activityType": {"typeKey": "lap_swimming"}}) == "swim"
    assert g.sport_of({"activityType": {"typeKey": "paddleboarding"}}) == "other"


def test_hevy_sets_in_pounds_on_local_date():
    rows = h.parse_workout(HEVY_WORKOUT, ET)
    assert [r["weight_lb"] for r in rows] == [88.2, 148.8]
    assert rows[0]["performed_on"] == date(2026, 9, 24)       # 22:10Z is 6:10 PM ET


def test_oura_merge_prefers_main_sleep():
    days = o.merge_days(
        [{"day": "2026-09-24", "score": 80, "temperature_deviation": -0.11}],
        [{"day": "2026-09-24", "score": 77}],
        [{"day": "2026-09-24", "type": "sleep", "lowest_heart_rate": 70, "total_sleep_duration": 1800},
         {"day": "2026-09-24", "type": "long_sleep", "lowest_heart_rate": 52, "average_hrv": 61,
          "total_sleep_duration": 26000}])
    d = days["2026-09-24"]
    assert (d["readiness"], d["sleep_score"], d["resting_hr"], d["hrv_ms"]) == (80, 77, 52, 61)


def test_pace_parsing():
    assert evaluate.fast_end_of("10:45–11:30") == 645
    assert evaluate.fast_end_of("10:40-11:20") == 640
    assert evaluate.fast_end_of(None) is None


# ── database tests ───────────────────────────────────────────────────────
DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL not set")


class FakeGarmin:
    def __init__(self):
        self.split_calls = 0

    def get_activities_by_date(self, start, end):
        return [a for a in (SEP23, LONG) if start <= a["startTimeLocal"][:10] <= end]

    def get_activity_splits(self, aid):
        self.split_calls += 1
        return SEP23_SPLITS if str(aid) == "24474801626" else LONG_SPLITS


@pytest.fixture
def conn(monkeypatch):
    from scripts import migrate
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("drop schema public cascade; create schema public")
    migrate.run(DB, seed=True)
    monkeypatch.setattr("app.ingest.garmin.LAP_DELAY_S", 0)
    with psycopg.connect(DB, row_factory=dict_row) as c:
        yield c


def _oura_rows(start: date, n: int, rhr: int, temp: float = -0.1):
    days = [(start + timedelta(days=i)).isoformat() for i in range(n)]
    return ([{"day": d, "score": 80, "temperature_deviation": temp} for d in days], [],
            [{"day": d, "type": "long_sleep", "lowest_heart_rate": rhr, "total_sleep_duration": 25000}
             for d in days])


@needs_db
def test_garmin_sync_is_idempotent_and_matches_plan(conn):
    fake = FakeGarmin()
    for _ in range(2):
        g.sync(conn, fake, date(2026, 9, 20), date(2026, 9, 26), rest_hr=52, max_hr=190)
    conn.commit()
    counts = conn.execute("select (select count(*) from activities) a, (select count(*) from laps) l").fetchone()
    assert counts == {"a": 2, "l": 9}
    assert fake.split_calls == 2            # laps fetched once per activity, not per sync
    assert evaluate.match_planned(conn, date(2026, 9, 20), date(2026, 9, 26)) == 2
    assert evaluate.match_planned(conn, date(2026, 9, 20), date(2026, 9, 26)) == 0
    evaluate.activity_flags(conn, date(2026, 9, 20))
    evaluate.activity_flags(conn, date(2026, 9, 20))
    kinds = [r["kind"] for r in conn.execute("select kind from flags order by kind").fetchall()]
    assert kinds == ["decoupling"]          # the drifting 6-miler; Sep 23 was on plan


@needs_db
def test_hevy_sync_idempotent(conn):
    pages = {1: {"page": 1, "page_count": 1, "workouts": [HEVY_WORKOUT]}}
    for _ in range(2):
        h.sync(conn, ET, fetch=lambda path, page, pageSize: pages[page])
    assert conn.execute("select count(*) n from strength_sets").fetchone()["n"] == 2


@needs_db
def test_long_run_gate_go_pending_fallback(conn):
    plan = conn.execute("select * from planned_workouts where plan_date = '2026-10-03' and sport = 'run'").fetchone()
    conn.execute("update profile set resting_hr_baseline = 52")
    # Oct 2, every return run done at easy HR, 3 normal mornings -> GO
    for d in ("2026-09-23", "2026-09-25", "2026-09-26", "2026-09-29", "2026-09-30", "2026-10-01"):
        conn.execute("""insert into activities (provider, external_id, start_local, local_date, sport,
                        distance_m, duration_s, avg_hr) values ('garmin', %s, %s, %s, 'run', 5000, 2000, 136)""",
                     (d, d + " 07:00", d))
    conn.execute("update planned_workouts set status = 'done' where sport = 'run' and plan_date < '2026-10-03'")
    readiness, sleep_scores, sleeps = _oura_rows(date(2026, 9, 29), 3, rhr=54)
    conn.execute("select 1")
    for day in o.merge_days(readiness, sleep_scores, sleeps).values():
        conn.execute("insert into recovery (day, readiness, resting_hr, temp_deviation_c) values (%s, %s, %s, %s)",
                     (day["day"], day["readiness"], day["resting_hr"], day["temp_deviation_c"]))
    assert evaluate.long_run_gate(conn, plan, date(2026, 10, 2))["verdict"] == "go"
    # Earlier in the week -> pending (runs still to do)
    assert evaluate.long_run_gate(conn, plan, date(2026, 9, 28))["verdict"] == "pending"
    # A hard easy run -> fallback to 10
    conn.execute("update activities set avg_hr = 151 where local_date = '2026-09-30'")
    g2 = evaluate.long_run_gate(conn, plan, date(2026, 10, 2))
    assert g2["verdict"] == "fallback" and g2["fallback_mi"] == 10


@needs_db
def test_today_view(conn):
    from app import today as view
    t = view.build(conn, date(2026, 9, 25))
    assert t["phase"]["name"] == "Return to training"
    assert t["health"]["status"] == "return"
    assert [s["title"] for s in t["sessions"]] == ["Easy run"]
    assert [d["date"] for d in t["next_days"]] == [date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 28), date(2026, 9, 29)]
    # Oct 3's go/no-go is visible all week, and pending until the runs happen.
    gate = t["long_run_gate"]
    assert gate["date"] == date(2026, 10, 3) and gate["verdict"] == "pending"
