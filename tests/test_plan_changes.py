"""Feature 2: plan changes through the one validated path (needs TEST_DATABASE_URL)."""
from datetime import date, datetime, timedelta, timezone

import pytest
from psycopg.types.json import Jsonb

from tests.test_ingest import _fresh_db, needs_db

WS = date(2026, 11, 30)             # Base 2, at home
TODAY = WS - timedelta(days=1)


@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        c.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                     "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                     return_started_on = '2026-10-15', return_ends_on = '2026-11-04' where closed_on is null""")
        for i, (d, mi) in enumerate([(date(2026, 11, 14), 7), (date(2026, 11, 21), 7.5), (date(2026, 11, 28), 8)]):
            c.execute("""insert into activities (provider, external_id, start_local, local_date, sport, distance_m,
                         duration_s, avg_hr) values ('manual', %s, %s, %s, 'run', %s, %s, 138)""",
                      (f"r{i}", d, d, mi * 1609.344, mi * 660))
        c.commit()
        yield c


def _add(c, d, sport, title, mins, mi=None, long=False, zone="Z2"):
    return c.execute("""insert into planned_workouts (plan_date, sport, title, duration_min, distance_mi, max_zone,
                        is_long, structure, source) values (%s, %s, %s, %s, %s, %s, %s, %s, 'generator')
                        returning id""", (d, sport, title, mins, mi, zone, long, Jsonb({}))).fetchone()["id"]


@needs_db
def test_move_easy_run_applies_with_audit(conn):
    from app.planning import changes
    rid = _add(conn, WS + timedelta(days=1), "run", "Easy run", 40, 3.5)
    p = changes.propose(conn, [{"action": "move", "workout_id": rid, "to": str(WS + timedelta(days=3))}],
                        source="chat", reason="meeting Tuesday", today=TODAY)
    assert p["pass"] and p["status"] == "pending"
    assert conn.execute("select status from planned_workouts where id = %s", (rid,)).fetchone()["status"] == "planned"
    r = changes.apply(conn, p["proposal_id"], [], TODAY)
    assert r["applied"]
    rows = conn.execute("select plan_date, status, source, structure->'changed_by'->>'by' as by "
                        "from planned_workouts where title = 'Easy run' and plan_date >= %s order by id", (WS,)).fetchall()
    assert [(x["plan_date"], x["status"]) for x in rows] == [(WS + timedelta(days=1), "superseded"),
                                                             (WS + timedelta(days=3), "planned")]
    assert rows[1]["by"] == "you"
    audit = conn.execute("select action, reason, source from plan_changes").fetchall()
    assert audit == [{"action": "move", "reason": "meeting Tuesday", "source": "chat"}]


@needs_db
def test_long_run_onto_travel_day_is_refused(conn):
    from app.planning import changes
    lid = _add(conn, WS + timedelta(days=5), "run", "Long run", 95, 8.5, long=True)
    conn.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports)
                    values (%s, %s, 'Flight to Denver', 0, 0, 'America/New_York', '{}')""",
                 (WS + timedelta(days=6), WS + timedelta(days=6)))
    p = changes.propose(conn, [{"action": "move", "workout_id": lid, "to": str(WS + timedelta(days=6))}],
                        source="chat", reason="dinner Saturday", today=TODAY)
    assert p["status"] == "refused" and not p["pass"]
    assert any(f["kind"] == "travel" and f["severity"] == "stop" for f in p["flags"])
    with pytest.raises(changes.ChangeError):
        changes.apply(conn, p["proposal_id"], [], TODAY)
    assert not conn.execute("select 1 from plan_changes").fetchone()


@needs_db
def test_change_during_health_hold_is_refused(conn):
    from app.planning import changes
    conn.execute("update health_episodes set return_started_on = null, return_ends_on = null, expected_clear_on = null")
    p = changes.propose(conn, [{"action": "add", "plan_date": str(WS + timedelta(days=1)), "sport": "run",
                                "title": "Intervals", "duration_min": 50, "max_zone": "Z4"}],
                        source="chat", reason="wants intervals", today=TODAY)
    assert p["status"] == "refused" and p["flags"][0]["kind"] == "health_hold"


@needs_db
def test_stale_proposal_is_re_proposed(conn):
    from app.planning import changes
    rid = _add(conn, WS + timedelta(days=1), "run", "Easy run", 40, 3.5)
    p = changes.propose(conn, [{"action": "move", "workout_id": rid, "to": str(WS + timedelta(days=2))}],
                        source="chat", reason="x", today=TODAY)
    conn.execute("update planned_workouts set duration_min = 30 where id = %s", (rid,))     # the world changed
    r = changes.apply(conn, p["proposal_id"], [], TODAY)
    assert r["stale"] and not r["applied"] and r["new_proposal"]["status"] == "pending"
    assert conn.execute("select status from plan_proposals where id = %s", (p["proposal_id"],)).fetchone()["status"] == "stale"


@needs_db
def test_warn_needs_explicit_ack(conn):
    from app.planning import changes
    _add(conn, WS + timedelta(days=5), "run", "Long run", 95, 8.5, long=True)
    for i, (sport, mins) in enumerate([("swim", 45), ("run", 50), ("bike", 60), ("run", 50), ("swim", 45)]):
        _add(conn, WS + timedelta(days=i), sport, f"Easy {sport}", mins, 4.5 if sport == "run" else None)
    p = changes.propose(conn, [{"action": "add", "plan_date": str(WS + timedelta(days=5)), "sport": "bike",
                                "title": "Easy ride", "duration_min": 120}],
                        source="chat", reason="extra ride", today=TODAY)
    assert p["pass"] and "daily_cap:2026-12-05" in p["needs_ack"], p["flags"]
    r = changes.apply(conn, p["proposal_id"], [], TODAY)
    assert not r["applied"] and "daily_cap:2026-12-05" in r["needs_ack"]
    r = changes.apply(conn, p["proposal_id"], p["needs_ack"], TODAY)
    assert r["applied"]
    acc = conn.execute("select accepted_warns from plan_changes").fetchone()["accepted_warns"]
    assert "daily_cap:2026-12-05" in acc


@needs_db
def test_chat_cannot_apply_in_the_same_turn_and_undo_restores(conn):
    from app import chat
    from app.planning import changes
    rid = _add(conn, WS + timedelta(days=1), "run", "Easy run", 40, 3.5)
    turn = datetime.now(timezone.utc) - timedelta(seconds=5)
    p = chat.run_tool(conn, "propose_change", {"actions": [{"action": "move", "workout_id": rid,
                                                            "to": str(WS + timedelta(days=2))}], "reason": "x"},
                      TODAY, turn)
    same = chat.run_tool(conn, "apply_change", {"proposal_id": p["proposal_id"]}, TODAY, turn)
    assert not same["applied"] and "confirmed" in same["error"]
    later = chat.run_tool(conn, "apply_change", {"proposal_id": p["proposal_id"]}, TODAY,
                          datetime.now(timezone.utc) + timedelta(seconds=1))
    assert later["applied"]
    changes.undo(conn, later["batch_id"], TODAY)
    live = conn.execute("select plan_date from planned_workouts where status = 'planned'").fetchall()
    assert live == [{"plan_date": WS + timedelta(days=1)}]
