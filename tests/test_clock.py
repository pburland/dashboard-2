from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app import clock


def test_today_is_the_local_calendar_date(monkeypatch):
    # 11:30 PM in Arlington is already the next day in UTC.
    fixed = datetime(2026, 9, 24, 3, 30, tzinfo=timezone.utc)

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz)

    monkeypatch.setattr(clock, "datetime", FakeDT)
    monkeypatch.setenv("TZ_NAME", "America/New_York")
    assert clock.today() == date(2026, 9, 23)
    assert clock.now().tzinfo == ZoneInfo("America/New_York")


def test_week_start_is_monday():
    assert clock.week_start(date(2026, 9, 13)) == date(2026, 9, 7)
    assert clock.week_start(date(2026, 9, 14)) == date(2026, 9, 14)
