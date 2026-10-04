"""Open-Meteo hourly forecast (free, no key) for the heat go/no-go and the
best-time suggestion. Forecasts where the athlete is (home or a trip stop)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.analysis.heat import HourlyWeather
from app.config import load_settings

URL = "https://api.open-meteo.com/v1/forecast"


def hourly_forecast(days: int = 2, place=None) -> list[HourlyWeather]:
    """``place`` is an app.travel.Place; default home. Up to 16 days ahead."""
    if place is None:
        s = load_settings()
        lat, lng, tz_name = s.home_lat, s.home_lng, s.tz_name
    else:
        lat, lng, tz_name = place.lat, place.lng, place.tz_name
    r = httpx.get(URL, timeout=20, params={
        "latitude": lat, "longitude": lng,
        "hourly": "temperature_2m,relative_humidity_2m",
        "temperature_unit": "fahrenheit", "timezone": tz_name,
        "forecast_days": min(days, 16),
    })
    r.raise_for_status()
    h = r.json()["hourly"]
    zone = ZoneInfo(tz_name)
    return [HourlyWeather(datetime.fromisoformat(t).replace(tzinfo=zone), temp, rh)
            for t, temp, rh in zip(h["time"], h["temperature_2m"], h["relative_humidity_2m"])]


def check() -> dict:
    hours = hourly_forecast(1)
    from app.analysis.heat import heat_index_f
    peak = max(hours, key=lambda h: heat_index_f(h.temp_f, h.rel_humidity))
    return {"ok": True, "hours": len(hours),
            "peak_heat_index_f": heat_index_f(peak.temp_f, peak.rel_humidity),
            "peak_at": peak.time.isoformat()}
