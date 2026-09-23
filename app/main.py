"""Web service: API now, the phone app later.

Until Supabase Auth is wired in (phone-app step), everything that returns
personal data requires the ADMIN_TOKEN, sent as the ``X-Admin-Token``
header. Felipe's server served its whole project directory, credentials
included; this one serves only explicit routes.
"""
from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app import clock
from app.config import MissingConfig, load_settings

app = FastAPI(title="Training system", docs_url=None, redoc_url=None, openapi_url=None)


def _check_token(supplied: str | None) -> None:
    expected = load_settings().admin_token
    if not expected:
        raise HTTPException(503, "ADMIN_TOKEN is not configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "unauthorized")


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    _check_token(x_admin_token)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "today": clock.today().isoformat(), "now": clock.now().isoformat()}


@app.get("/api/state", dependencies=[Depends(require_admin)])
def state() -> dict:
    """Today as the server sees it: phase, health gate, races."""
    from app import db
    from app.health.state import MorningSignals, gate as health_gate
    from app.periodization.phases import NoPhaseDefined, PhaseTableError, phase_for, validate_phases

    today = clock.today()
    try:
        with db.connect() as conn:
            phases = db.load_phases(conn)
            episode = db.open_episode(conn)
            races = db.races(conn)
    except MissingConfig as e:
        raise HTTPException(503, str(e))

    try:
        validate_phases(phases)
        p = phase_for(phases, today)
        phase = {"name": p.name, "kind": p.kind, "start": p.start_date, "end": p.end_date}
    except PhaseTableError as e:
        phase = {"error": "phase table invalid", "problems": e.problems}
    except NoPhaseDefined as e:
        phase = {"error": str(e)}

    # Morning signals arrive with Oura ingest; until then the gate runs on
    # the health episode alone.
    g = health_gate(episode, MorningSignals(), today)
    return {
        "today": today,
        "phase": phase,
        "health": {"status": g.status.value, "prescriptions_allowed": g.prescriptions_allowed,
                   "reasons": list(g.reasons)},
        "races": [{**r, "days_until": clock.days_until(r["race_date"], today)} for r in races],
    }


@app.get("/admin/diagnostics", dependencies=[Depends(require_admin)])
def diagnostics() -> dict:
    from app.diagnostics import run_all
    return run_all()


@app.get("/oauth/oura/start")
def oura_start(key: str | None = Query(default=None)):
    """Open in a browser: /oauth/oura/start?key=<ADMIN_TOKEN>"""
    _check_token(key)
    from app.integrations import oura
    try:
        return RedirectResponse(oura.authorize_url())
    except MissingConfig as e:
        raise HTTPException(503, str(e))


@app.get("/oauth/oura/callback", response_class=HTMLResponse)
def oura_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    from app import db
    from app.integrations import oura
    if error:
        raise HTTPException(400, f"Oura returned an error: {error}")
    if not code or not state or not oura.verify_state(state):
        raise HTTPException(400, "invalid or expired authorization request; start again")
    tok = oura.exchange_code(code)
    with db.connect() as conn:
        db.save_integration(conn, "oura", access_token=tok["access_token"],
                            refresh_token=tok.get("refresh_token"),
                            expires_at=tok["expires_at"],
                            extra={"scope": tok.get("scope")})
    return "<h1>Oura connected.</h1><p>You can close this tab.</p>"
