"""Fitness tests -> zones (outside review, Card 2)."""
from datetime import date, timedelta

import pytest

from app import fitness_tests as ft
from app.periodization import zones
from tests.test_ingest import _fresh_db, needs_db

MI = 1609.344


def lap(i, dist, secs, hr=None, power=None):
    return {"lap_index": i, "distance_m": dist, "duration_s": secs, "avg_hr": hr, "max_hr": None,
            "avg_power_w": power}


def test_run_result_from_the_20_minute_lap():
    laps = [lap(0, 2400, 900, 130), lap(1, 2000, 600, 160), lap(2, 4300, 1200, 168), lap(3, 600, 300, 140)]
    r = ft.run_result(laps)
    assert r["lthr"] == 168 and not r["approx"]
    assert r["threshold_pace_s_per_mi"] == round(1200 / (4300 / MI))


def test_run_result_approximated_from_per_mile_laps():
    laps = ([lap(0, MI, 660, 135), lap(1, MI, 650, 138)]          # warm-up
            + [lap(i, MI, 470, 160 + i) for i in range(2, 6)]      # ~31 min hard
            + [lap(6, MI, 700, 140)])
    r = ft.run_result(laps)
    assert r["approx"] and 162 <= r["lthr"] <= 165 and r["threshold_pace_s_per_mi"] == 470


def test_bike_and_swim_results():
    b = ft.bike_result([lap(0, 0, 1200, 130, 150), lap(1, 0, 300, 165, 300), lap(2, 0, 1200, 170, 210)])
    assert b["ftp_w"] == 200 and b["bike_lthr"] == 162          # 95% of 210 W and of 170 bpm
    s = ft.swim_result([lap(0, 365.76, 440), lap(1, 182.88, 210), lap(2, 100, 200)])
    assert s == {"css_s_per_100": 115.0, "unit": "yd", "t400_s": 440, "t200_s": 210}


def test_validity_gate():
    ok = {"lthr": 168, "threshold_pace_s_per_mi": 480, "hr_coverage": 1.0}
    assert ft.invalid_reason("run_lthr", ok, {"distance_m": 8000, "elevation_gain_m": 40}, 9) is None
    assert "hilly" in ft.invalid_reason("run_lthr", ok, {"distance_m": 8000, "elevation_gain_m": 300}, 9)
    assert "RPE 6" in ft.invalid_reason("run_lthr", ok, None, 6)
    assert "heart rate missing" in ft.invalid_reason("run_lthr", ok | {"hr_coverage": 0.7}, None, None)
    assert "KICKR" in ft.invalid_reason("bike_ftp", None, None, None)


def test_zone_math():
    p = zones.run_pace_zones(480)                                  # 8:00/mi threshold
    assert p["Z2"] == (547, 619) and p["Z4"] == (485, 509)
    assert zones.power_zones(200)["Z2"] == (112, 151)
    assert zones.css_targets(115) == {"Z1": 125, "Z2": 120, "Z3": 115, "Z4": 112, "Z5": 109}


@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        yield c


def _test_session(conn, d, sport, laps, elev=20.0, rpe=None):
    act = conn.execute("""insert into activities (provider, external_id, start_local, local_date, sport, distance_m,
                          duration_s, elevation_gain_m) values ('garmin', %s, %s, %s, %s, %s, %s, %s) returning id""",
                       (f"t{d}{sport}", f"{d} 17:00", d, sport, sum(l["distance_m"] for l in laps),
                        sum(l["duration_s"] for l in laps), elev)).fetchone()["id"]
    for l in laps:
        conn.execute("""insert into laps (activity_id, lap_index, distance_m, duration_s, avg_hr, avg_power_w)
                        values (%s, %s, %s, %s, %s, %s)""",
                     (act, l["lap_index"], l["distance_m"], l["duration_s"], l["avg_hr"], l["avg_power_w"]))
    pw = conn.execute("""insert into planned_workouts (plan_date, sport, title, duration_min, max_zone, status,
                         source, structure, activity_id) values (%s, %s, %s, 50, 'Z4', 'done', 'generator',
                         %s::jsonb, %s) returning id""",
                      (d, sport, f"{sport} test", f'{{"gen_key": "{sport}:test#1"}}', act)).fetchone()["id"]
    if rpe:
        conn.execute("insert into check_ins (planned_workout_id, check_in_on, rpe, felt) values (%s, %s, %s, 'fine')",
                     (pw, d, rpe))
    return pw


@needs_db
def test_a_close_run_test_applies_and_sets_easy_hr_everywhere(conn):
    d = date(2026, 12, 15)
    _test_session(conn, d, "run", [lap(0, 2400, 900, 130), lap(1, 2000, 600, 155), lap(2, 4300, 1200, 162),
                                   lap(3, 600, 300, 140)], rpe=9)
    (t,) = ft.process(conn, d - timedelta(days=1))
    assert t["status"] == "applied" and t["result"]["lthr"] == 162
    assert zones.easy_hr_range("run") == (138, 145, False)          # 85-89% of 162: within 8 of 145
    from app.integrations import garmin_push
    w = garmin_push.build({"plan_date": d, "sport": "run", "title": "Easy run", "duration_min": 40, "max_zone": "Z2"})
    step = w["workoutSegments"][0]["workoutSteps"][1]
    assert (step["targetValueOne"], step["targetValueTwo"]) == (138, 145)
    assert ft.process(conn, d - timedelta(days=1)) == []            # read once


@needs_db
def test_a_big_change_waits_for_ok_and_an_invalid_test_schedules_a_retest(conn):
    d = date(2026, 12, 15)
    _test_session(conn, d, "run", [lap(0, 2400, 900, 130), lap(1, 2000, 600, 170), lap(2, 4300, 1200, 178)])
    (t,) = ft.process(conn, d)
    assert t["status"] == "pending" and zones.easy_hr_range("run")[2]          # still provisional
    assert ft.decide(conn, t["id"], True)["status"] == "applied"
    assert zones.easy_hr_range("run")[:2] == (151, 159)
    b = date(2026, 12, 16)
    _test_session(conn, b, "bike", [lap(0, 0, 1200, 130), lap(1, 0, 1200, 170)])   # no power: KICKR not paired
    (bt,) = ft.process(conn, b)
    assert bt["status"] == "invalid" and "KICKR" in bt["reason"]
    assert conn.execute("select 1 from plan_events where sport = 'bike' and event_date = %s",
                        (b + timedelta(days=7),)).fetchone()


@needs_db
def test_manual_entry_and_retest_reminder(conn):
    ft.record_manual(conn, "swim_css", date(2026, 12, 7), css_s_per_100=115, unit="yd")
    assert "1:55 per 100 yd" in " ".join(zones.summary())
    assert ft.due_notes(conn, date(2027, 1, 28)) == ["The swim test (CSS) is due around Feb 1 (8 weeks since the last one)."]
    assert ft.due_notes(conn, date(2027, 1, 10)) == []


@needs_db
def test_tests_sit_after_the_return(conn):
    rows = {r["sport"]: r["event_date"] for r in conn.execute(
        "select sport, event_date from plan_events where kind = 'test'").fetchall()}
    assert rows == {"run": date(2026, 12, 19), "swim": date(2026, 12, 18), "bike": date(2026, 12, 16)}
