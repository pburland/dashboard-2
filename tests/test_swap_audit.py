"""Swap button (app/planning/swap.py) and the audit agent's read-only key (app/audit.py)."""
from datetime import date, timedelta

from tests.test_plan_changes import WS, TODAY, _add, conn  # noqa: F401  (fixture)
from tests.test_ingest import needs_db


def _week(conn):
    for k in (0, 1, 3, 4, 5, 6):
        _add(conn, WS + timedelta(days=k), "run", "Easy run", 45, 4)


@needs_db
def test_swap_offers_checked_options_and_a_substitution_replaces(conn):  # noqa: F811
    from app.planning import swap
    _week(conn)
    d = WS + timedelta(days=2)
    ride = _add(conn, d, "bike", "Easy ride (Z2)", 35)
    o = swap.options(conn, ride, TODAY)
    keys = [x["key"] for x in o["options"]]
    assert "sport:run" in keys and "shorter" in keys and "skip" in keys
    assert sum(k.startswith("move:") for k in keys) <= 1
    r = swap.apply(conn, ride, "sport:run", TODAY)
    assert r["applied"]
    old = conn.execute("select status, structure from planned_workouts where id = %s", (ride,)).fetchone()
    assert old["status"] == "replaced" and old["structure"]["changed_by"]["by"] == "you (Swap button)"
    new = conn.execute("select sport, duration_min from planned_workouts where id = %s",
                       (old["structure"]["replaced_by"][0],)).fetchone()
    assert (new["sport"], new["duration_min"]) == ("run", 35)
    assert conn.execute("select source from plan_changes order by id desc limit 1").fetchone()["source"] == "swap"


@needs_db
def test_swap_respects_where_he_is_and_shorter_modifies(conn):  # noqa: F811
    from app.planning import swap
    _week(conn)
    d = WS + timedelta(days=2)
    conn.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports)
                    values (%s, %s, 'Away', 41.7, -72.6, 'America/New_York', '{run,strength}')""", (d, d))
    ride = _add(conn, d, "bike", "Easy ride (Z2)", 50)
    keys = [x["key"] for x in swap.options(conn, ride, TODAY)["options"]]
    assert "sport:swim" not in keys and "sport:bike" not in keys          # no pool or bike there
    run = _add(conn, WS + timedelta(days=3), "run", "Easy run", 50, 4.5)
    assert swap.apply(conn, run, "shorter", TODAY)["applied"]
    assert conn.execute("select duration_min from planned_workouts where status = 'planned' and plan_date = %s "
                        "and sport = 'run' order by id desc limit 1", (WS + timedelta(days=3),)).fetchone()["duration_min"] == 30


@needs_db
def test_audit_key_only_unlocks_the_audit_endpoints(conn, monkeypatch):  # noqa: F811
    import os
    from fastapi.testclient import TestClient
    from app import audit, main
    monkeypatch.setenv("ADMIN_TOKEN", "secret-admin")
    monkeypatch.setenv("SCHEDULER", "off")
    monkeypatch.setenv("SUPABASE_DB_URL", os.environ["TEST_DATABASE_URL"])
    k = {"X-Audit-Key": audit.key("secret-admin")}
    c = TestClient(main.app)
    snap = c.get("/admin/audit/snapshot", headers=k)
    assert snap.status_code == 200 and "coverage_28d" in snap.json() and "rules_version" in snap.json()
    assert c.post("/admin/audit/reports", headers=k, json={"title": "Dec audit", "summary": "All good.",
                                                           "findings": [], "followups": ["recheck weigh-ins"]}).status_code == 200
    got = c.get("/admin/audit/reports", headers=k).json()
    assert got[0]["title"] == "Dec audit" and got[0]["followups"] == ["recheck weigh-ins"]
    # Nothing else: not Today, not plan changes, not settings.
    assert c.get("/api/today", headers=k).status_code == 401
    assert c.post("/api/plan/undo/x", headers=k).status_code == 401
    assert c.post("/api/garmin/push", headers=k, json={}).status_code == 401
    assert c.get("/admin/audit/snapshot", headers={"X-Audit-Key": "wrong"}).status_code == 401
    from app import db
    if db._pool is not None:                                   # don't leave pool threads running
        db._pool.close()
        db._pool = None
