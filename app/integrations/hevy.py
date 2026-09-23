"""Hevy REST API (requires Hevy Pro). The MCP connector is not used."""
from __future__ import annotations

import httpx

from app.config import MissingConfig, load_settings

BASE = "https://api.hevyapp.com/v1"


def _headers() -> dict:
    key = load_settings().hevy_api_key
    if not key:
        raise MissingConfig("HEVY_API_KEY")
    return {"api-key": key, "accept": "application/json"}


def get(path: str, **params) -> dict:
    r = httpx.get(f"{BASE}{path}", headers=_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def check() -> dict:
    count = get("/workouts/count")
    page = get("/workouts", page=1, pageSize=1)
    latest = (page.get("workouts") or [None])[0]
    return {
        "ok": True,
        "workout_count": count.get("workout_count"),
        "latest_workout": latest and {
            "start": latest.get("start_time"),
            "title": latest.get("title"),
            "exercises": [e.get("title") for e in latest.get("exercises", [])],
        },
    }
