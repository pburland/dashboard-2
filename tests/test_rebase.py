"""Feature 4: missed-session and travel auto-rebase (needs TEST_DATABASE_URL)."""
from datetime import date, timedelta

import pytest

from app.ingest import rebase
from app.planning import changes, generator as g
from tests.test_ingest import _fresh_db, needs_db

TRIP_WS = date(2026, 11, 9)          # Base 1, Asia trip: runs only, Sunday is rest
HOME_WS = date(2026, 11, 30)         # Base 2 at home


@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        c.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                     "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                     return_started_on = '2026-10-15', return_ends_on = '2026-11-04' where closed_on is null""")
        d = date(2026, 10, 12)
        while d < date(2026, 12, 7):
            for off, mi in ((1, 4), (3, 4), (5, 6.5)):
                dd = d + timedelta(days=off)
                c.execute("""insert into activities (provider, external_id, start_local, local_date, sport,
                             distance_m, duration_s, avg_hr) values ('manual', %s, %s, %s, 'run', %s, %s, 136)""",
                          (f"h{dd}", dd, dd, mi * 1609.344, mi * 660))
            d += timedelta(days=7)
        c.commit()
        yield c


def _live(c, ws):
    return c.execute("""select id, plan_date, sport, title, is_long, is_key, status from planned_workouts
                        where plan_date between %s and %s and status = 'planned' order by plan_date, id""",
                     (ws, ws + timedelta(days=6))).fetchall()


def _unmatch(c, ws):
    """Clear the fixture's runs in the plan week; _do() records what was really done."""
    c.execute("delete from activities where local_date between %s and %s", (ws, ws + timedelta(days=6)))
    c.commit()


def _do(c, ws, until, skip_long=True):
    """Everything planned before ``until`` was done, except the long run."""
    from app.ingest import evaluate
    for r in _live(c, ws):
        if r["plan_date"] >= until or (skip_long and r["is_long"]):
            continue
        if r["sport"] == "strength":
            c.execute("""insert into strength_sets (workout_id, performed_on, exercise, set_index, weight_lb, reps)
                         values (%s, %s, 'Push-up', 0, 0, 20)""", (f"w{r['id']}", r["plan_date"]))
        else:
            c.execute("""insert into activities (provider, external_id, start_local, local_date, sport,
                         distance_m, duration_s, avg_hr) values ('manual', %s, %s, %s, %s, 6400, 2400, 135)""",
                      (f"d{r['id']}", r["plan_date"], r["plan_date"], r["sport"]))
    evaluate.match_planned(c, ws, until)
    c.commit()


@needs_db
def test_missed_long_run_moves_to_free_sunday_and_undo_restores(conn):
    _unmatch(conn, TRIP_WS)
    g.generate(conn, TRIP_WS, weeks=1, today=TRIP_WS - timedelta(days=1), use_calendar=False)
    before = {(r["plan_date"], r["title"]) for r in _live(conn, TRIP_WS)}
    sat = TRIP_WS + timedelta(days=5)
    assert any(r["is_long"] and r["plan_date"] == sat for r in _live(conn, TRIP_WS))
    sun = sat + timedelta(days=1)
    _do(conn, TRIP_WS, sun)
    out = rebase.run(conn, sun, use_calendar=False)
    prop = conn.execute("select id, actions, flags from plan_proposals where status = 'pending'").fetchone()
    if prop:                       # a warning (e.g. load share): Patrick confirms on Today
        assert any(a["after"] and a["after"]["plan_date"] == str(sun) and a["after"]["is_long"]
                   for a in prop["actions"]), out
        assert not [r for r in _live(conn, TRIP_WS) if r["is_long"]]          # nothing applied yet
        acks = [f["key"] for f in prop["flags"] if f["severity"] == "warn"]
        batch = changes.apply(conn, str(prop["id"]), acks, sun)["batch_id"]
    else:                          # clean: applied automatically with an info flag
        f = conn.execute("select message, data from flags where kind = 'auto_rebase'").fetchone()
        assert "Long run" in f["message"] and "Sun" in f["message"]
        batch = f["data"]["batch_id"]
    assert [r["plan_date"] for r in _live(conn, TRIP_WS) if r["is_long"]] == [sun]
    assert conn.execute("select count(*) n from plan_changes where source = 'system'").fetchone()["n"] >= 2
    changes.undo(conn, batch, sun)
    # Undone: the Sunday long run is gone again (the missed Saturday stays recorded as skipped).
    assert not [r for r in _live(conn, TRIP_WS) if r["plan_date"] == sun and r["is_long"]]


@needs_db
def test_missed_long_run_with_no_compliant_day_is_left_alone(conn):
    _unmatch(conn, TRIP_WS)
    g.generate(conn, TRIP_WS, weeks=1, today=TRIP_WS - timedelta(days=1), use_calendar=False)
    sun = TRIP_WS + timedelta(days=6)
    _do(conn, TRIP_WS, sun)
    conn.execute("update travel set sports = '{}' where start_date <= %s and end_date >= %s", (sun, sun))
    conn.execute("update travel set end_date = %s where end_date > %s and start_date < %s", (sun - timedelta(days=1), sun, sun))
    conn.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports)
                    values (%s, %s, 'Train to Hiroshima', 34, 132, 'Asia/Tokyo', '{}')
                    on conflict do nothing""", (sun, sun))
    rebase.run(conn, sun, use_calendar=False)
    assert not [r for r in _live(conn, TRIP_WS) if r["is_long"]]
    assert conn.execute("select 1 from flags where kind = 'needs_review' and message like %s",
                        ("%Long run%",)).fetchone()


@needs_db
def test_weekend_trip_moves_key_sessions_and_skips_easy_ones(conn):
    _unmatch(conn, HOME_WS)
    g.generate(conn, HOME_WS, weeks=1, today=HOME_WS - timedelta(days=1), use_calendar=False)
    fri = HOME_WS + timedelta(days=4)
    conn.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports)
                    values (%s, %s, 'Weekend away', 0, 0, 'America/New_York', '{}')""", (fri, fri + timedelta(days=2)))
    conn.commit()
    today = HOME_WS + timedelta(days=1)
    _do(conn, HOME_WS, today)
    out = rebase.run(conn, today, use_calendar=False)
    live = _live(conn, HOME_WS)
    prop = conn.execute("select actions from plan_proposals where status = 'pending'").fetchone()
    if prop:                                       # warnings: waits for confirmation, nothing moved yet
        moves = [a for a in prop["actions"] if a["action"] == "move"]
        assert any(m["before"]["is_long"] and m["after"]["plan_date"] < str(fri) for m in moves)
    else:
        assert not [r for r in live if r["plan_date"] >= fri], out
        assert [r for r in live if r["is_long"] and r["sport"] == "run"][0]["plan_date"] < fri
        skipped = conn.execute("select count(*) n from planned_workouts where status = 'skipped' "
                               "and plan_date >= %s", (fri,)).fetchone()["n"]
        assert skipped >= 1


@needs_db
def test_missed_easy_session_is_just_skipped(conn):
    _unmatch(conn, HOME_WS)
    g.generate(conn, HOME_WS, weeks=1, today=HOME_WS - timedelta(days=1), use_calendar=False)
    gens = conn.execute("select count(*) n from plan_generations").fetchone()["n"]
    tue = HOME_WS + timedelta(days=1)
    easy = [r for r in _live(conn, HOME_WS) if r["plan_date"] == tue and not r["is_key"]]
    assert easy
    rebase.run(conn, tue + timedelta(days=1), use_calendar=False)
    assert conn.execute("select status from planned_workouts where id = %s", (easy[0]["id"],)).fetchone()["status"] == "skipped"
    assert conn.execute("select count(*) n from plan_generations where trigger = 'rebase'").fetchone()["n"] == 0
    assert conn.execute("select count(*) n from plan_generations").fetchone()["n"] == gens


@needs_db
def test_mid_week_replan_keeps_done_sessions_in_the_past(conn):
    """Regression: a mid-week re-plan must not drag completed sessions (or
    already-done strength) into the remaining days."""
    _unmatch(conn, HOME_WS)
    g.generate(conn, HOME_WS, weeks=1, today=HOME_WS - timedelta(days=1), use_calendar=False)
    planned_strength = len([r for r in _live(conn, HOME_WS) if r["sport"] == "strength"])
    thu = HOME_WS + timedelta(days=3)
    _do(conn, HOME_WS, thu, skip_long=False)
    done_before = conn.execute("select count(*) n from planned_workouts where status = 'done'").fetchone()["n"]
    from app.planning import sync
    fixed, missed = sync.week_context(conn, HOME_WS, thu)
    wp = g.plan_week(conn, HOME_WS, basis_mi=18, today=thu, fixed=fixed, missed_keys=missed)
    assert all(x.date >= thu for x in wp.drafts)
    done_strength = conn.execute("select count(*) n from planned_workouts where status = 'done' "
                                 "and sport = 'strength'").fetchone()["n"]
    assert len([x for x in wp.drafts if x.sport == "strength"]) == max(0, g.STRENGTH_PER_WEEK["base"] - done_strength)
    assert conn.execute("select count(*) n from planned_workouts where status = 'done'").fetchone()["n"] == done_before


@needs_db
def test_missed_key_session_avoids_the_day_it_was_missed_not_its_template_day(conn):
    """Regression: a long run moved to Friday and missed there may go to Saturday."""
    _unmatch(conn, HOME_WS)
    g.generate(conn, HOME_WS, weeks=1, today=HOME_WS - timedelta(days=1), use_calendar=False)
    fri, sat = HOME_WS + timedelta(days=4), HOME_WS + timedelta(days=5)
    lr = [r for r in _live(conn, HOME_WS) if r["is_long"] and r["sport"] == "run"][0]
    conn.execute("update planned_workouts set plan_date = %s where id = %s", (fri, lr["id"]))
    _do(conn, HOME_WS, sat)
    from app.planning import sync
    from app.ingest import rebase as rb
    gate_for = g.day_gate(conn, sat, sat - timedelta(days=8))
    for r in rb._missed(conn, sat, gate_for):
        op = changes.Op("remove", r, None, "missed", remove_status="skipped")
        changes.write(conn, [op], changes.Checked([op], []), source="system", reason="missed")
    fixed, missed = sync.week_context(conn, HOME_WS, sat)
    assert missed == {lr_key: fri for lr_key in missed}
    wp = g.plan_week(conn, HOME_WS, basis_mi=18, today=sat, fixed=fixed, missed_keys=missed)
    longs = [x for x in wp.drafts if x.sport == "run" and x.is_long]
    assert longs and longs[0].date in (sat, sat + timedelta(days=1)) and longs[0].date != fri
