from datetime import date, datetime
from zoneinfo import ZoneInfo

from app import travel

STOPS = [
    {"start_date": date(2026, 11, 6), "end_date": date(2026, 11, 6), "place": "Flight", "lat": 0, "lng": 0,
     "tz_name": "America/New_York", "sports": [], "note": ""},
    {"start_date": date(2026, 11, 7), "end_date": date(2026, 11, 9), "place": "Taipei", "lat": 25.03,
     "lng": 121.57, "tz_name": "Asia/Taipei", "sports": ["run"], "note": ""},
    {"start_date": date(2026, 11, 22), "end_date": date(2026, 11, 23), "place": "Osaka", "lat": 34.69,
     "lng": 135.5, "tz_name": "Asia/Tokyo", "sports": ["run"], "note": ""},
]
UTC = ZoneInfo("UTC")


def test_place_for_home_and_trip():
    assert travel.place_for(STOPS, date(2026, 11, 5)).name == "Home"
    assert not travel.place_for(STOPS, date(2026, 11, 5)).away
    p = travel.place_for(STOPS, date(2026, 11, 8))
    assert (p.name, p.sports, p.away) == ("Taipei", ("run",), True)
    assert travel.place_for(STOPS, date(2026, 11, 6)).sports == ()


def test_today_follows_the_trip():
    # 8 AM Nov 7 in Taipei is still Nov 6 evening at home: Taipei wins.
    assert travel.tz_for_now(STOPS, datetime(2026, 11, 7, 0, 0, tzinfo=UTC)) == "Asia/Taipei"
    # Before landing day starts in Taipei, home time applies.
    assert travel.tz_for_now(STOPS, datetime(2026, 11, 5, 12, 0, tzinfo=UTC)) == "America/New_York"
    # Back in NYC on Nov 23 evening: it is already Nov 24 in Osaka, so home.
    assert travel.tz_for_now(STOPS, datetime(2026, 11, 23, 23, 0, tzinfo=UTC)) == "America/New_York"
    # Morning of Nov 23 in Osaka (Nov 22 evening at home): Osaka.
    assert travel.tz_for_now(STOPS, datetime(2026, 11, 22, 23, 0, tzinfo=UTC)) == "Asia/Tokyo"
