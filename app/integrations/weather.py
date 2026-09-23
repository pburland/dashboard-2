"""Open-Meteo hourly forecast (free, no key) for the heat go/no-go."""
from __future__ import annotations

from datetime import datetime

import httpx

from app.analysis.heat import HourlyWeather
from app.config import load_settings

URL = "https://api.open-meteo.com/v1/forecast"


def hourly_forecast(days: int = 2) -> list[HourlyWeather]:
    s = load_settings()
    r = httpx.get(URL, timeout=20, params={
        "latitude": s.home_lat, "longitude": s.home_lng,
        "hourly": "temperature_2m,relative_humidity_2m",
        "temperature_unit": "fahrenheit", "timezone": s.tz_name,
        "forecast_days": days,
    })
    r.raise_for_status()
    h = r.json()["hourly"]
    from app.clock import tz
    zone = tz()
    return [HourlyWeather(datetime.fromisoformat(t).replace(tzinfo=zone), temp, rh)
            for t, temp, rh in zip(h["time"], h["temperature_2m"], h["relative_humidity_2m"])]


def check() -> dict:
    hours = hourly_forecast(1)
    from app.analysis.heat import heat_index_f
    peak = max(hours, key=lambda h: heat_index_f(h.temp_f, h.rel_humidity))
    return {"ok": True, "hours": len(hours),
            "peak_heat_index_f": heat_index_f(peak.temp_f, peak.rel_humidity),
            "peak_at": peak.time.isoformat()}
