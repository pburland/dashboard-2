"""Feature 5: the plan generator (DB tests need TEST_DATABASE_URL)."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.analysis import overreach
from app.planning import generator as g
from tests.test_ingest import _fresh_db, _history, needs_db

ET = ZoneInfo("America/New_York")


# ── ladder solver (pure) ─────────────────────────────────────────────────
def test_ladder_18_weeks_to_a_70_3_from_6_miles():
    race = date(2027, 3, 14)
    start = race - timedelta(days=race.weekday()) - timedelta(weeks=17)
    lad = g.long_run_ladder(start, race, "70.3", 6.0)
    mi = [m for _, m in lad]
    assert len(mi) == 18
    window = [6.0]
    for i, m in enumerate(mi[:-2]):                      # no jump the validator would flag
        prev = max(window[-4:])
        assert m <= max(prev * 1.1, prev + overreach.LONG_RUN_JUMP_FREE_MI) + 0.25, (i, m, prev)
        window.append(m)
    cut = [i for i in range(1, 15) if mi[i] < mi[i - 1]]
    assert cut and all(b - a in (3, 4) for a, b in zip(cut, cut[1:]))      # cutbacks every 3-4 weeks
    peak_week = max(range(len(mi)), key=lambda i: (mi[i], -i))
    assert len(mi) - 1 - peak_week in (2, 3) or mi[-3] == max(mi)          # peak 2-3 weeks out
    assert max(mi) == g.PEAK_LONG_MI["70.3"]
    assert mi[-1] < mi[-2] < mi[-3]                                        # taper


def test_next_long_rules():
    assert g.next_long(10, 0, None, 12.5) == 11.0          # +10%
    assert g.next_long(4, 1, None, 12.5) == 5.0            # +1 mi floor on a short base
    assert g.next_long(10, 3, None, 12.5) == 8.0           # 4th week: cutback
    assert g.next_long(12.5, 3, 2, 12.5) == 12.5           # no cutback in the peak weeks
    assert g.next_long(12.5, 5, 1, 12.5) == 7.5            # taper


# ── generator against the database ───────────────────────────────────────
@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        c.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-15",
                     "fever_free_48h":"2026-10-15","rhr_near_baseline_3d":"2026-10-15"}',
                     return_started_on = '2026-10-15', return_ends_on = '2026-11-04' where closed_on is null""")
        # Five weeks of base running before Nov 30.
        d, i = date(2026, 10, 26), 0
        while d < date(2026, 11, 30):
            for off, mi in ((1, 4), (3, 4), (5, 6 + i * 0.5)):
                dd = d + timedelta(days=off)
                c.execute("""insert into activities (provider, external_id, start_local, local_date, sport,
                             distance_m, duration_s, avg_hr) values ('manual', %s, %s, %s, 'run', %s, %s, 136)""",
                          (f"h{dd}", dd, dd, mi * 1609.344, mi * 660))
            d += timedelta(days=7)
            i += 1
        c.commit()
        yield c


WS = date(2026, 11, 30)      # Base 2 at home


def _live(c, ws):
    return c.execute("""select * from planned_workouts where plan_date between %s and %s and status = 'planned'
                        order by plan_date, id""", (ws, ws + timedelta(days=6))).fetchall()


@needs_db
def test_base_week_is_clean_and_long_run_within_rule(conn):
    from app.analysis.validator import validate_week
    wp = g.generate(conn, WS, weeks=1, today=WS - timedelta(days=1), use_calendar=False)[0]
    assert not [f for f in wp.flags if f["severity"] == "stop"]
    rows = _live(conn, WS)
    longest_prior = 8.0
    long_runs = [r for r in rows if r["sport"] == "run" and r["is_long"]]
    assert long_runs and long_runs[0]["distance_mi"] <= max(longest_prior * 1.1, longest_prior + 1)
    hist = g.history(conn, WS)
    v = validate_week([g.PlannedSession(r["plan_date"], r["sport"], r["title"], r["duration_min"], r["max_zone"] or "Z2",
                                        r["distance_mi"], r["is_long"], (r["structure"] or {}).get("heavy_lower", False))
                       for r in rows], hist, g.day_gate(conn, WS - timedelta(days=1), WS))
    assert not [f for fl in v.flags.values() for f in fl if f.severity.value == "stop"]
    gen = conn.execute("select trigger, validator_pass from plan_generations").fetchall()
    assert gen == [{"trigger": "weekly", "validator_pass": True}]


@needs_db
def test_strength_follows_concurrent_rules(conn):
    g.generate(conn, WS, weeks=1, today=WS - timedelta(days=1), use_calendar=False)
    rows = _live(conn, WS)
    strength = [r for r in rows if r["sport"] == "strength"]
    assert len(strength) == g.STRENGTH_PER_WEEK["base"]
    key_days = {r["plan_date"] for r in rows if r["is_key"]}
    long_days = {r["plan_date"] for r in rows if r["is_long"]}
    for s in strength:
        assert s["plan_date"] not in key_days
        if (s["structure"] or {}).get("heavy_lower"):
            assert not any(0 <= (L - s["plan_date"]).days <= 2 for L in long_days)


@needs_db
def test_regenerating_changes_nothing(conn):
    g.generate(conn, WS, weeks=2, today=WS - timedelta(days=1), use_calendar=False)
    n1 = conn.execute("select count(*) n from planned_workouts").fetchone()["n"]
    c1 = conn.execute("select count(*) n from plan_changes").fetchone()["n"]
    g.generate(conn, WS, weeks=2, today=WS - timedelta(days=1), use_calendar=False)
    assert conn.execute("select count(*) n from planned_workouts").fetchone()["n"] == n1
    assert conn.execute("select count(*) n from plan_changes").fetchone()["n"] == c1


@needs_db
def test_a_change_supersedes_and_audits(conn):
    g.generate(conn, WS, weeks=1, today=WS - timedelta(days=1), use_calendar=False)
    conn.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports)
                    values (%s, %s, 'Flight', 0, 0, 'America/New_York', '{}')""", (WS + timedelta(days=5),) * 2)
    g.generate(conn, WS, weeks=1, today=WS - timedelta(days=1), trigger="rebase", use_calendar=False)
    rows = _live(conn, WS)
    assert not [r for r in rows if r["plan_date"] == WS + timedelta(days=5)]          # nothing on the flight day
    lr = [r for r in rows if r["is_long"] and r["sport"] == "run"]
    assert lr and lr[0]["plan_date"] == WS + timedelta(days=6)                         # long run moved to Sunday
    audit = conn.execute("select action, source, reason from plan_changes").fetchall()
    assert any(a["action"] == "move" for a in audit) and all(a["source"] == "generator" for a in audit)
    assert conn.execute("select count(*) n from planned_workouts where status = 'superseded' "
                        "and plan_date >= %s", (WS,)).fetchone()["n"] > 0              # history kept


@needs_db
def test_busy_saturday_moves_the_long_session(conn):
    busy = [(datetime.combine(WS + timedelta(days=5), time(5, 0), ET),
             datetime.combine(WS + timedelta(days=5), time(22, 0), ET))]
    cal = g.Calendar(conn, WS, WS + timedelta(days=6), busy=busy)
    wp = g.plan_week(conn, WS, basis_mi=18, today=WS - timedelta(days=1), cal=cal)
    sat = [x for x in wp.drafts if x.date == WS + timedelta(days=5)]
    assert not [x for x in sat if x.is_key]
    lr = [x for x in wp.drafts if x.sport == "run" and x.is_long][0]
    assert lr.date == WS + timedelta(days=6) and lr.structure["moved_from"]["why"] == "no free time"


@needs_db
def test_return_after_hold_is_a_ramp_not_full_volume(conn):
    # Still on hold: nothing is written. Clearance recorded: the week is a return week.
    conn.execute("update health_episodes set return_started_on = null, return_ends_on = null, "
                 "expected_clear_on = null, criteria_met = '{}'")
    _history(conn)                                   # pre-illness running, Jul 27 - Sep 13
    ws = date(2026, 10, 19)
    assert g.generate(conn, ws, weeks=1, today=ws - timedelta(days=1), use_calendar=False)[0].drafts == []
    conn.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-10-18",
                    "fever_free_48h":"2026-10-18","rhr_near_baseline_3d":"2026-10-18"}',
                    return_started_on = '2026-10-18', return_ends_on = '2026-11-07'""")
    wp = g.generate(conn, ws, weeks=1, today=ws - timedelta(days=1), trigger="rebase", use_calendar=False)[0]
    assert wp.drafts and all(x.zone in ("Z1", "Z2") for x in wp.drafts)
    assert wp.kind == "return" or wp.inputs["kind"] == "return"
    ref = g.reference_week_mi(conn, date(2026, 9, 15))
    assert ref > 15 and 0 < wp.run_mi <= ref * 0.7        # about half volume, not a jump back to full


@needs_db
def test_no_compliant_day_is_flagged_for_review(conn):
    conn.execute("""insert into travel (start_date, end_date, place, lat, lng, tz_name, sports)
                    values (%s, %s, 'Work trip', 0, 0, 'America/New_York', '{swim}')""",
                 (WS, WS + timedelta(days=6)))
    wp = g.generate(conn, WS, weeks=1, today=WS - timedelta(days=1), use_calendar=False)[0]
    assert any("Long run" in m for m in wp.needs_review)
    assert conn.execute("select 1 from flags where kind = 'needs_review'").fetchone()


@needs_db
def test_cleared_inside_the_hold_block_uses_the_return_template(conn):
    # Cleared Sep 28 while the phase table still says "hold" until Oct 14.
    conn.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-09-28",
                    "fever_free_48h":"2026-09-28","rhr_near_baseline_3d":"2026-09-28"}',
                    return_started_on = '2026-09-28', return_ends_on = '2026-10-18'""")
    _history(conn)
    wp = g.generate(conn, date(2026, 10, 5), weeks=1, today=date(2026, 10, 4), use_calendar=False)[0]
    assert [x for x in wp.drafts if x.sport == "run"] and not wp.needs_review


@needs_db
def test_preview_weeks_are_checked_against_the_weeks_planned_before_them(conn):
    conn.execute("""update health_episodes set criteria_met = '{"physician_clearance":"2026-09-28",
                    "fever_free_48h":"2026-09-28","rhr_near_baseline_3d":"2026-09-28"}',
                    return_started_on = '2026-09-28', return_ends_on = '2026-10-18'""")
    _history(conn)
    wps = g.generate(conn, date(2026, 10, 5), weeks=3, today=date(2026, 10, 4), use_calendar=False)
    assert not [m for w in wps for m in w.needs_review]
    assert not conn.execute("select 1 from flags where kind = 'needs_review'").fetchone()
