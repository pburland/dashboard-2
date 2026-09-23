"""Runtime configuration, read from environment variables only.

No secret ever has a default. Missing secrets surface as clear errors at
the point of use, not at import time, so the server can start and report
which integrations are unconfigured.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


@dataclass(frozen=True)
class Settings:
    tz_name: str
    home_lat: float
    home_lng: float
    public_base_url: str | None
    db_url: str | None
    admin_token: str | None
    anthropic_api_key: str | None
    anthropic_model: str | None
    garmin_tokens: str | None
    hevy_api_key: str | None
    oura_client_id: str | None
    oura_client_secret: str | None
    oura_scopes: str


def load_settings() -> Settings:
    return Settings(
        tz_name=_get("TZ_NAME", "America/New_York"),
        home_lat=float(_get("HOME_LAT", "38.8816")),
        home_lng=float(_get("HOME_LNG", "-77.0910")),
        public_base_url=(_get("PUBLIC_BASE_URL") or "").rstrip("/") or None,
        db_url=_get("SUPABASE_DB_URL"),
        admin_token=_get("ADMIN_TOKEN"),
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        anthropic_model=_get("ANTHROPIC_MODEL"),
        garmin_tokens=_get("GARMIN_TOKENS"),
        hevy_api_key=_get("HEVY_API_KEY"),
        oura_client_id=_get("OURA_CLIENT_ID"),
        oura_client_secret=_get("OURA_CLIENT_SECRET"),
        oura_scopes=_get("OURA_SCOPES", "personal daily heartrate session"),
    )


class MissingConfig(RuntimeError):
    """Raised when an operation needs a setting that isn't configured."""

    def __init__(self, *names: str):
        super().__init__("Not configured: " + ", ".join(names))
        self.names = names
