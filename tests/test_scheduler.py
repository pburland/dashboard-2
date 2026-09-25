from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.ingest.scheduler import due

ET = ZoneInfo("America/New_York")


def at(h, m):
    return datetime(2026, 9, 25, h, m, tzinfo=ET)


def test_morning_check_runs_in_its_window_only():
    assert not due("morning", time(5, 30), at(5, 29), set())
    assert due("morning", time(5, 30), at(5, 30), set())
    assert due("morning", time(5, 30), at(8, 29), set())
    assert not due("morning", time(5, 30), at(8, 31), set())     # too late to catch up
    assert not due("morning", time(5, 30), at(21, 28), set())    # the 9:28 PM restart case


def test_runs_once_a_day():
    assert not due("nightly", time(3, 0), at(3, 5), {"nightly"})
