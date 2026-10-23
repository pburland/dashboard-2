"""Next week's lifting weights from logged sets (app/strength.py)."""
from datetime import date, timedelta

import pytest

from app import strength as s
from tests.test_ingest import _fresh_db, needs_db


@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        yield c


def _log(conn, day, exercise, sets, workout="w"):
    for i, (lb, reps, rpe) in enumerate(sets):
        conn.execute("""insert into strength_sets (workout_id, workout_title, performed_on, exercise, set_index,
                        set_type, weight_lb, reps, rpe) values (%s, %s, %s, %s, %s, 'normal', %s, %s, %s)""",
                     (f"{workout}-{day}", workout, day, exercise, i, lb, reps, rpe))


def test_e1rm_and_load_math():
    # 5 reps at RPE 8 -> about 81% of e1RM; sets over 10 reps or under RPE 7 don't count.
    assert abs(s.pct(5, 8) - 0.811) < 0.001 and abs(s.pct(8, 7.5) - 0.741) < 0.001
    assert s.e1rm(155, 12, 8) is None and s.e1rm(155, 8, 6.5) is None
    assert 188 < s.e1rm(155, 5, 8) < 193
    assert s.gap_change(-2) == 0.04 and s.gap_change(0.5) == 0.0 and s.gap_change(2) == -0.04


@needs_db
def test_reentry_after_the_mono_layoff(conn):
    # Patrick's last bench sessions before mono (Sep 3 and 9), no RPE logged.
    _log(conn, date(2026, 9, 3), "Bench Press (Barbell)", [(125, 8, None), (145, 6, None), (165, 3, None)])
    _log(conn, date(2026, 9, 9), "Bench Press (Barbell)", [(135, 8, None), (155, 8, None)])
    p = s.recommend(conn, date(2026, 10, 26), phase_kind="return")
    bench = p.days["Push (Tue)"][0]
    assert bench.load_lb == s.round_to(155 * 0.75) and "Re-entry week 1" in bench.note
    assert bench.rpe == 7.0 and bench.backoff and bench.backoff[2] == s.round_to(bench.load_lb * 0.9)
    # One week back: 85%.
    _log(conn, date(2026, 10, 27), "Bench Press (Barbell)", [(115, 5, 6.5)])
    p2 = s.recommend(conn, date(2026, 11, 2), phase_kind="return")
    assert "Re-entry week 2" in p2.days["Push (Tue)"][0].note


@needs_db
def test_top_set_follows_the_rpe_gap_and_the_cut_cap(conn):
    ws = date(2027, 1, 4)
    for k, (lb, rpe) in enumerate([(140, 8), (145, 8), (150, 8), (155, 6.5)]):
        _log(conn, ws - timedelta(weeks=4 - k) + timedelta(days=1), "Bench Press (Barbell)", [(lb, 5, rpe)])
    p = s.recommend(conn, ws, phase_kind="base", cutting=True)
    bench = p.days["Push (Tue)"][0]
    # RPE 6.5 vs target 8 (gap -1.5) would add 4%, but the cut caps it at +5 lb.
    assert bench.load_lb == 160 and "RPE 6.5" in bench.note
    vol = p.days["Legs (Thu)"][1]
    assert vol.exercise.endswith("(volume)") and vol.load_lb < bench.load_lb
    p_bulk = s.recommend(conn, ws, phase_kind="base", cutting=False)
    assert p_bulk.days["Push (Tue)"][0].load_lb == s.round_to(155 * 1.04)


@needs_db
def test_accessory_double_progression_and_deload(conn):
    ws = date(2027, 1, 4)
    for k in range(2):
        _log(conn, ws - timedelta(weeks=3 - k) + timedelta(days=1), "Triceps Pushdown", [(50, 12, 8)] * 3)
    _log(conn, ws - timedelta(days=5), "Triceps Pushdown", [(50, 15, 8), (50, 15, 7.5), (50, 15, 8)])
    p = s.recommend(conn, ws, phase_kind="base")
    tri = next(r for r in p.days["Push (Tue)"] if r.exercise == "Triceps Pushdown")
    assert tri.load_lb == 55 and tri.reps == "10"
    deload = s.recommend(conn, ws, phase_kind="base", recovery_week=True)
    tri_d = next(r for r in deload.days["Push (Tue)"] if r.exercise == "Triceps Pushdown")
    assert deload.deload and tri_d.sets == 1 and "Next week's weights" in deload.markdown()


def test_coach_reads_the_research_digests():
    from app import chat
    text = chat.research_digests()
    if not text:
        pytest.skip("no research digests in this copy")
    assert "Strength digest" in text and "Nutrition digest" in text


@needs_db
def test_strength_sessions_show_their_lifts(conn):
    from app import today as view
    from app.planning import generator as g
    conn.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                    "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                    return_started_on = '2026-10-15', return_ends_on = '2026-11-04'""")
    _log(conn, date(2026, 11, 17), "Bench Press (Barbell)", [(150, 5, 8)])
    ws = date(2026, 11, 30)
    g.generate(conn, ws, weeks=1, today=ws - timedelta(days=1), use_calendar=False)
    days = view.plan(conn, ws, 7)["days"]
    lifts = {s["title"]: s["structure"].get("exercises") for d in days for s in d["sessions"] if s["sport"] == "strength"}
    push = next(v for k, v in lifts.items() if "Push" in k)
    assert push[0][0] == "Bench Press (Barbell)" and push[0][2].endswith("lb") and push[1][0].strip() == "back-off"
    legs = next(v for k, v in lifts.items() if "Legs" in k)
    assert legs[0][0] == "Squat (Barbell)"


def test_trend_restarts_after_a_layoff_and_follows_a_steady_climb():
    def wk(d, lb):
        return (d, [{"weight_lb": lb, "reps": 5, "rpe": 7.0}])
    old = [wk(date(2026, 8, 31), 165), wk(date(2026, 9, 7), 165)]
    back = [wk(date(2026, 10, 26), 115), wk(date(2026, 11, 2), 130), wk(date(2026, 11, 23), 145)]
    t, series = s._trend(old + back)
    # Restarted at the comeback (not dragged down by the pre-illness weeks) ...
    assert series[2] == s.e1rm(115, 5, 7)
    # ... and a repeated climb isn't damped as noise: within ~10% of the latest set.
    assert t > 0.9 * s.e1rm(145, 5, 7)
