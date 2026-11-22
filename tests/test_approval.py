"""Sunday approval: snapshot times, then Garmin + the Training calendar (app/approval.py)."""
from datetime import date, timedelta

from app import approval, notify
from tests.test_garmin_push import MON, _plan, conn  # noqa: F401  (fixture)
from tests.test_ingest import needs_db


def test_which_week_waits_for_approval():
    assert approval.week_to_approve(date(2026, 11, 22)) == date(2026, 11, 23)     # Sunday: next week
    assert approval.week_to_approve(date(2026, 11, 25)) == date(2026, 11, 23)     # midweek: this week


@needs_db
def test_approving_snapshots_times_and_queues_nothing_twice(conn, monkeypatch):  # noqa: F811
    nxt = MON + timedelta(days=7)
    run = _plan(conn, nxt + timedelta(days=1), "run", "Easy run", 40)
    sent = []
    monkeypatch.setattr("app.integrations.garmin_push.sync", lambda c, t: sent.append(t) or {"created": 1})
    p = approval.preview(conn, nxt, nxt - timedelta(days=1))
    assert p["approved_at"] is None and [s["id"] for s in p["sessions"]] == [run]
    assert p["sessions"][0]["start"]                                               # a suggested time block
    notify.approval_ready(conn, nxt)
    assert conn.execute("select count(*) n from notifications where kind = 'approval'").fetchone()["n"] == 1
    r = approval.approve(conn, nxt, nxt - timedelta(days=1))
    assert r["sessions"] == 1 and sent and r["garmin"] == {"created": 1}
    snap = approval.approved(conn, nxt)["sessions"][str(run)]
    assert snap["date"] == (nxt + timedelta(days=1)).isoformat() and snap["start"]
    notify.approval_ready(conn, nxt)                                              # already approved: no nudge
    assert conn.execute("select count(*) n from notifications where kind = 'approval'").fetchone()["n"] == 1
