"""Garmin Connect via the unofficial ``garminconnect`` library (>= 0.3.16).

Garmin has no API for individuals, so this logs in the way the Garmin
Connect phone app does. Two rules keep it working from a server:

  1. The server never logs in with a password. Garmin rate-limits and
     blocks logins from cloud IPs. The login happens once on Patrick's Mac
     (see docs/SETUP.md) and produces a token; the server only renews it.
  2. Every renewal produces a new token, and Railway can't rewrite its own
     environment variables, so the newest token is saved to the
     ``integrations`` table. GARMIN_TOKENS is only the first bootstrap.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.config import MissingConfig, load_settings

TOKEN_FILE = "garmin_tokens.json"


def _current_tokens(conn) -> tuple[str, str]:
    """Return (token_json, source). Database copy wins over the env var."""
    if conn is not None:
        from app import db
        row = db.get_integration(conn, "garmin")
        if row and row.get("access_token"):
            return row["access_token"], "database"
    env = load_settings().garmin_tokens
    if env:
        return env, "GARMIN_TOKENS"
    raise MissingConfig("GARMIN_TOKENS")


def client(conn=None):
    """Logged-in Garmin client plus a callback that persists renewed tokens."""
    from garminconnect import Garmin

    tokens, source = _current_tokens(conn)
    json.loads(tokens)  # fail early with a clear error if the value was mangled
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / TOKEN_FILE
    path.write_text(tokens)
    g = Garmin()
    g.login(tokenstore=str(path))

    def persist() -> bool:
        latest = g.client.dumps()
        changed = latest != tokens
        if conn is not None:
            from app import db
            db.save_integration(conn, "garmin", access_token=latest, synced=True,
                                extra={"token_source": source})
        return changed

    g._training_tmpdir = tmp   # keep the directory alive as long as the client
    return g, source, persist


def check(conn=None) -> dict:
    g, source, persist = client(conn)
    acts = g.get_activities(0, 1)
    renewed = persist()
    latest = acts[0] if acts else None
    return {
        "ok": True,
        "token_source": source,
        "token_renewed": renewed,
        "account": g.get_full_name(),
        "latest_activity": latest and {
            "start": latest.get("startTimeLocal"),
            "type": (latest.get("activityType") or {}).get("typeKey"),
            "distance_mi": round((latest.get("distance") or 0) / 1609.344, 2),
        },
    }
