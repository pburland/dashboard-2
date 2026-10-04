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


def test_weekly_report_due_sunday_evening_and_catches_up():
    from datetime import date
    from app.ingest.scheduler import report_week_due
    sun = lambda h: datetime(2026, 10, 11, h, 0, tzinfo=ET)
    assert report_week_due(sun(18), set()) == date(2026, 9, 28)        # before 7 PM: last week's
    assert report_week_due(sun(18), {date(2026, 9, 28)}) is None
    assert report_week_due(sun(19), {date(2026, 9, 28)}) == date(2026, 10, 5)
    tue = datetime(2026, 10, 13, 9, 0, tzinfo=ET)                      # missed Sunday: catch up
    assert report_week_due(tue, set()) == date(2026, 10, 5)
    assert report_week_due(tue, {date(2026, 10, 5)}) is None
