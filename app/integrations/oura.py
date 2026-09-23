"""Oura API v2 over OAuth2.

Oura stopped issuing personal access tokens in December 2025, so this is
a registered application: Patrick approves it once in the browser
(/oauth/oura/start), the server stores the tokens, and refreshes them.
Oura refresh tokens are single-use: every refresh returns a new one that
must replace the old one, which is why tokens live in the database.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import MissingConfig, load_settings

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
API = "https://api.ouraring.com/v2/usercollection"
STATE_TTL_S = 900


def redirect_uri() -> str:
    base = load_settings().public_base_url
    if not base:
        raise MissingConfig("PUBLIC_BASE_URL")
    return f"{base}/oauth/oura/callback"


def _client_creds() -> tuple[str, str]:
    s = load_settings()
    missing = [n for n, v in (("OURA_CLIENT_ID", s.oura_client_id),
                              ("OURA_CLIENT_SECRET", s.oura_client_secret)) if not v]
    if missing:
        raise MissingConfig(*missing)
    return s.oura_client_id, s.oura_client_secret


def _sign(ts: str) -> str:
    key = load_settings().admin_token
    if not key:
        raise MissingConfig("ADMIN_TOKEN")
    return hmac.new(key.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]


def make_state() -> str:
    ts = str(int(time.time()))
    return f"{ts}.{_sign(ts)}"


def verify_state(state: str) -> bool:
    try:
        ts, sig = state.split(".", 1)
    except ValueError:
        return False
    fresh = 0 <= time.time() - int(ts) <= STATE_TTL_S
    return fresh and hmac.compare_digest(sig, _sign(ts))


def authorize_url() -> str:
    client_id, _ = _client_creds()
    return AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "scope": load_settings().oura_scopes,
        "state": make_state(),
    })


def _token_request(data: dict) -> dict:
    client_id, secret = _client_creds()
    r = httpx.post(TOKEN_URL, data={**data, "client_id": client_id,
                                    "client_secret": secret}, timeout=20)
    r.raise_for_status()
    tok = r.json()
    tok["expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 0)))
    return tok


def exchange_code(code: str) -> dict:
    return _token_request({"grant_type": "authorization_code", "code": code,
                           "redirect_uri": redirect_uri()})


def refresh(refresh_token: str) -> dict:
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


def access_token(conn) -> str:
    """A valid access token, refreshing (and persisting) when near expiry."""
    from app import db
    row = db.get_integration(conn, "oura")
    if not row or not row.get("refresh_token"):
        raise MissingConfig("Oura authorization (open /oauth/oura/start)")
    exp = row.get("expires_at")
    if row.get("access_token") and exp and exp - datetime.now(timezone.utc) > timedelta(minutes=5):
        return row["access_token"]
    tok = refresh(row["refresh_token"])
    db.save_integration(conn, "oura", access_token=tok["access_token"],
                        refresh_token=tok.get("refresh_token"), expires_at=tok["expires_at"])
    conn.commit()
    return tok["access_token"]


def get(conn, path: str, **params) -> dict:
    r = httpx.get(f"{API}/{path}", params=params, timeout=20,
                  headers={"Authorization": f"Bearer {access_token(conn)}"})
    r.raise_for_status()
    return r.json()


def check(conn) -> dict:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=7)
    readiness = get(conn, "daily_readiness", start_date=start.isoformat(),
                    end_date=end.isoformat()).get("data", [])
    last = readiness[-1] if readiness else None
    return {
        "ok": True,
        "readiness_days_last_week": len(readiness),
        "latest": last and {
            "day": last.get("day"),
            "score": last.get("score"),
            "temperature_deviation": last.get("temperature_deviation"),
        },
    }
