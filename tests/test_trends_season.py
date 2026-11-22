"""Trends that change a decision and the season page (outside review, Card 11)."""
from datetime import date, timedelta

from app import today as view
from tests.test_ingest import needs_db, conn_now  # noqa: F401  (fixture)

MI = 1609.344
D = date(2026, 12, 20)


def _run(conn, d, miles, secs, hr, load=60.0, elev=10.0):
    conn.execute("""insert into activities (provider, external_id, start_local, local_date, sport, distance_m, duration_s,
                    avg_hr, elevation_gain_m, load_trimp) values ('garmin', %s, %s, %s, 'run', %s, %s, %s, %s, %s)""",
                 (f"r{d}{miles}", f"{d} 17:00", d, miles * MI, secs, hr, elev * miles, load))


@needs_db
def test_load_weight_and_efficiency_trends(conn_now):  # noqa: F811
    for i in range(28):
        d = D - timedelta(days=27 - i)
        if i % 2 == 0:
            _run(conn_now, d, 4, 4 * (600 - i), 140)            # getting faster at the same HR
        conn_now.execute("insert into body_metrics (day, weight_lb) values (%s, %s) on conflict (day) do nothing",
                         (d, 160 - i * 0.05))
    _run(conn_now, D - timedelta(days=3), 5, 3000, 140, elev=40)   # hilly: left out of efficiency
    t = view.trends(conn_now, D)
    last = t["load"]["days"][-1]
    assert last["fitness"] > 0 and last["form"] == round(last["fitness"] - last["fatigue"], 1)
    assert t["weight"]["days"][-1]["avg7"] < t["weight"]["days"][0]["avg7"]
    runs = t["efficiency"]["runs"]
    assert len(runs) == 14 and runs[-1]["rolling_pace_s"] < runs[0]["rolling_pace_s"]   # faster at 140 bpm
    assert t["bench_goal"] == 185


@needs_db
def test_season_page(conn_now):  # noqa: F811
    s = view.season(conn_now, date(2026, 11, 23))
    tests = {e["sport"]: e["event_date"] for e in s["events"] if e["kind"] == "test"}
    assert tests == {"bike": date(2026, 12, 16), "swim": date(2026, 12, 18), "run": date(2026, 12, 19)}
    assert s["return"] == {"start": date(2026, 11, 23), "end": date(2026, 12, 14)}
    assert any(r["name"].startswith("IRONMAN Lake Placid") for r in s["races"])
    assert {l["lift"] for l in s["lift_checkpoints"]} == {"Bench", "Squat"}
    assert s["deficit_blocks"][0]["from"] == "2026-11-30"
