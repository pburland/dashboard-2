"""Weekly body-weight check and calorie correction (app/bodycomp.py)."""
from datetime import date, timedelta

import pytest

from app import bodycomp, nutrition
from tests.test_ingest import _fresh_db, needs_db


@pytest.fixture
def conn(monkeypatch):
    with _fresh_db(monkeypatch, None) as c:
        yield c


def _weigh(conn, start, lbs):
    for i, lb in enumerate(lbs):
        conn.execute("insert into body_metrics (day, weight_lb, source) values (%s, %s, 'hevy') "
                     "on conflict (day) do update set weight_lb = excluded.weight_lb", (start + timedelta(days=i), lb))


def _adjust(conn):
    t = conn.execute("select target from goals where name = 'Daily targets'").fetchone()["target"]
    return t["nutrition_plan"].get("kcal_adjust", 0)


@needs_db
def test_too_fast_loss_adds_calories_once(conn):
    # Base deficit 1 starts Nov 30; week 3 starts Dec 14. Two weeks of ~1.5 lb/wk loss (target ~0.8).
    _weigh(conn, date(2026, 11, 30), [159.0] * 7)
    _weigh(conn, date(2026, 12, 7), [157.5] * 7)
    _weigh(conn, date(2026, 12, 14), [156.0] * 7)
    c = bodycomp.check(conn, date(2026, 12, 14))
    assert c["adjust"] == 175 and _adjust(conn) == 175 and "0.7%" in c["why"]
    again = bodycomp.check(conn, date(2026, 12, 14))       # report re-run: no double count
    assert again["adjust"] == 0 and _adjust(conn) == 175
    plan = conn.execute("select target from goals where name = 'Daily targets'").fetchone()["target"]["nutrition_plan"]
    t = nutrition.targets(1958, 156, [], health="clear", phase_kind="base", deficit_goal=True,
                          day=date(2026, 12, 15), plan=plan, ffm_kg=58.3)
    assert any("weekly weight check" in w for w in t["why"])


@needs_db
def test_early_block_weeks_and_missing_data_change_nothing(conn):
    assert "Not enough weigh-ins" in bodycomp.check(conn, date(2026, 12, 7))["why"]
    _weigh(conn, date(2026, 11, 30), [159.0] * 7)
    _weigh(conn, date(2026, 12, 7), [156.0] * 7)          # big early drop: water
    c = bodycomp.check(conn, date(2026, 12, 7))
    assert c["adjust"] == 0 and "Week 2" in c["why"] and _adjust(conn) == 0
    assert "7-day average 156" in bodycomp.markdown(c)
