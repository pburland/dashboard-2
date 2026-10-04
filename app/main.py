"""Web service: API now, the phone app later.

Until Supabase Auth is wired in (phone-app step), everything that returns
personal data requires the ADMIN_TOKEN, sent as the ``X-Admin-Token``
header. Felipe's server served its whole project directory, credentials
included; this one serves only explicit routes.
"""
from __future__ import annotations

import hmac
import json
import logging
from datetime import timedelta
from contextlib import asynccontextmanager

import time

from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app import clock
from app.config import MissingConfig, load_settings

log = logging.getLogger("training")
MIGRATIONS: dict = {"status": "not run"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Bring the database schema up to date before serving. Railway's
    pre-deploy hook is not relied on: the server does it itself."""
    from scripts import migrate
    url = load_settings().db_url
    if not url:
        MIGRATIONS.update(status="skipped", reason="SUPABASE_DB_URL not set")
    else:
        try:
            applied = migrate.run(url, seed=True)
            MIGRATIONS.update(status="ok", applied=applied)
            log.warning("migrations applied: %s", applied or "none (up to date)")
        except Exception as e:  # keep serving so /healthz can report it
            MIGRATIONS.update(status="error", error=f"{type(e).__name__}: {e}")
            log.exception("migrations failed")
    if MIGRATIONS.get("status") == "ok":
        from app import travel
        clock.set_resolver(travel.current_tz)
        if any(a.startswith("seed/") for a in MIGRATIONS.get("applied", [])):
            _replan_in_background()
        from app.ingest import scheduler
        MIGRATIONS["scheduler"] = "on" if scheduler.start() else "off"
    yield


def _replan_in_background(trigger: str = "manual") -> None:
    """A new seed can move phases or the health hold: rebuild this week and
    the two after it so the app never shows a plan from the old rules."""
    import threading

    def go():
        from app import db
        from app.planning import generator
        try:
            t = clock.today()
            with db.connect() as conn:
                generator.generate(conn, t - timedelta(days=t.weekday()), weeks=3, today=t, trigger=trigger)
                conn.commit()
            log.warning("re-planned after seed change")
        except Exception:
            log.exception("re-plan after seed change failed")
    threading.Thread(target=go, daemon=True).start()


app = FastAPI(title="Training system", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)


WEB = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from the root so it controls the whole app; never cached, so
    # updates reach the phone.
    return FileResponse(WEB / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")


def _check_token(supplied: str | None) -> None:
    expected = load_settings().admin_token
    if not expected:
        raise HTTPException(503, "ADMIN_TOKEN is not configured")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "unauthorized")


SESSION_COOKIE = "training_token"
SESSION_DAYS = 400


def require_admin(x_admin_token: str | None = Header(default=None),
                  training_token: str | None = Cookie(default=None)) -> None:
    """Admin token from the header (curl) or the session cookie (the app)."""
    _check_token(x_admin_token or training_token)


@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    response.headers["Server-Timing"] = f"app;dur={ms:.0f}"
    if request.url.path.startswith("/api/") and ms > 1500:
        log.warning("slow %s %s: %.0f ms", request.method, request.url.path, ms)
    return response


@app.post("/api/session")
def create_session(response: Response, token: str = Body(..., embed=True)) -> dict:
    """Trade the admin token for a long-lived HttpOnly cookie, so the phone
    doesn't depend on page storage (which iOS can clear or separate)."""
    _check_token(token.strip())
    response.set_cookie(SESSION_COOKIE, token.strip(), max_age=SESSION_DAYS * 86400,
                        httponly=True, secure=True, samesite="strict", path="/")
    return {"ok": True}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "today": clock.today().isoformat(), "now": clock.now().isoformat(),
            "database": {k: v for k, v in MIGRATIONS.items() if k != "applied"}
                        | {"applied_now": len(MIGRATIONS.get("applied", []))}}


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
            episode = db.open_episode(conn, today)
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


@app.get("/api/today", dependencies=[Depends(require_admin)])
def api_today(checkin: int | None = Query(default=None)) -> dict:
    """Today's sessions, the next 4 days, health gate, go/no-go, recent activity.
    ``checkin``: a session id from a "How was it?" notification."""
    from app import db, today as today_view
    try:
        with db.connect() as conn:
            return today_view.build(conn, clock.today(), checkin_id=checkin)
    except MissingConfig as e:
        raise HTTPException(503, str(e))


@app.post("/api/checkin", dependencies=[Depends(require_admin)])
def api_checkin(planned_workout_id: int | None = Body(default=None, embed=True),
                activity_id: int | None = Body(default=None, embed=True),
                rpe: int | None = Body(default=None, embed=True, ge=1, le=10),
                felt: str | None = Body(default=None, embed=True, pattern="^(good|fine|bad)$"),
                pain: bool = Body(default=False, embed=True),
                pain_detail: str | None = Body(default=None, embed=True, max_length=200),
                note: str | None = Body(default=None, embed=True, max_length=1000)) -> dict:
    """Save a post-workout check-in; returns its effect on the next 48 hours."""
    from app import checkins, db
    try:
        with db.connect() as conn:
            r = checkins.submit(conn, planned_workout_id=planned_workout_id, activity_id=activity_id, rpe=rpe,
                                felt=felt, pain=pain, pain_detail=pain_detail, note=note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "effects": r["effects"], "check_in_on": r["check_in"]["check_in_on"]}


@app.post("/api/checkin/skip", dependencies=[Depends(require_admin)])
def api_checkin_skip(planned_workout_id: int = Body(..., embed=True),
                     reason: str | None = Body(default=None, embed=True, pattern="^(busy|tired|sick|weather)$")) -> dict:
    from app import checkins, db
    try:
        with db.connect() as conn:
            return checkins.skip(conn, planned_workout_id, reason, clock.today())
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/health/clear", dependencies=[Depends(require_admin)])
def api_health_clear(physician_clearance: bool = Body(..., embed=True),
                     fever_free_48h: bool = Body(..., embed=True),
                     rhr_near_baseline_3d: bool = Body(..., embed=True)) -> dict:
    """"I've been cleared": record all three exit criteria (Patrick confirms
    each) and start the return phase today; then re-plan."""
    from app import db
    from app.health.state import begin_return, record_criterion
    if not (physician_clearance and fever_free_48h and rhr_near_baseline_3d):
        raise HTTPException(400, "All three must be true to end the hold.")
    today = clock.today()
    with db.connect() as conn:
        ep = db.open_episode(conn)
        if ep is None or ep.return_started_on is not None:
            raise HTTPException(409, "There is no health hold to clear.")
        for k in ("physician_clearance", "fever_free_48h", "rhr_near_baseline_3d"):
            ep = record_criterion(ep, k, today)
        ep = begin_return(ep, today)
        conn.execute(
            """update health_episodes set criteria_met = %s::jsonb, return_started_on = %s, return_ends_on = %s,
               notes = coalesce(notes, '') || %s where id = %s""",
            (json.dumps({k: v.isoformat() for k, v in ep.criteria_met.items()}), ep.return_started_on,
             ep.return_ends_on, f" Cleared in the app on {today}: all three criteria confirmed by Patrick.", ep.id))
        conn.commit()
    _replan_in_background(trigger="rebase")
    return {"ok": True, "return_started_on": ep.return_started_on, "return_ends_on": ep.return_ends_on,
            "message": f"Hold ended. Easy comeback through {ep.return_ends_on:%b %-d}; your plan is being rebuilt."}


@app.get("/api/push/key", dependencies=[Depends(require_admin)])
def api_push_key() -> dict:
    from app import db
    from app.integrations import webpush
    with db.connect() as conn:
        return {"public_key": webpush.keys(conn)[1]}


@app.post("/api/push/subscribe", dependencies=[Depends(require_admin)])
def api_push_subscribe(request: Request, subscription: dict = Body(..., embed=True)) -> dict:
    from app import db
    from app.integrations import webpush
    if not subscription.get("endpoint") or not (subscription.get("keys") or {}).get("p256dh"):
        raise HTTPException(400, "invalid subscription")
    base = load_settings().public_base_url or str(request.base_url).rstrip("/").replace("http://", "https://")
    with db.connect() as conn:
        webpush.keys(conn)
        conn.execute("update integrations set extra = extra || jsonb_build_object('contact', %s::text) "
                     "where provider = 'vapid'", (base,))
        conn.execute("""insert into push_subscriptions (endpoint, keys, user_agent) values (%s, %s::jsonb, %s)
                        on conflict (endpoint) do update set keys = excluded.keys, user_agent = excluded.user_agent""",
                     (subscription["endpoint"], json.dumps(subscription["keys"]), request.headers.get("user-agent")))
        conn.commit()
    return {"ok": True}


@app.post("/api/push/test", dependencies=[Depends(require_admin)])
def api_push_test() -> dict:
    from app import db, notify
    with db.connect() as conn:
        notify.queue(conn, "test", "Test notification", "Notifications are working.", url="/")
        conn.commit()
        sent = notify.dispatch(conn, only_tests=True)
        err = conn.execute("select error from notifications where kind = 'test' and title = 'Test notification' "
                           "order by id desc limit 1").fetchone()
    return {"sent": bool(sent), "error": None if sent else (err or {}).get("error")}


@app.get("/api/notify/prefs", dependencies=[Depends(require_admin)])
def api_notify_prefs() -> dict:
    from app import db, notify
    with db.connect() as conn:
        n = conn.execute("select count(*) as n from push_subscriptions").fetchone()["n"]
        return {"prefs": notify.prefs(conn), "phones": n}


@app.post("/api/notify/prefs", dependencies=[Depends(require_admin)])
def api_notify_prefs_set(prefs: dict = Body(..., embed=True)) -> dict:
    from app import db, notify
    clean = {k: bool(v) for k, v in prefs.items() if k in notify.KINDS}
    with db.connect() as conn:
        conn.execute("update profile set notification_prefs = notification_prefs || %s::jsonb where id = 1",
                     (json.dumps(clean),))
        conn.commit()
        return {"prefs": notify.prefs(conn)}


@app.get("/api/plan/proposals", dependencies=[Depends(require_admin)])
def api_proposals() -> list:
    from app import db
    with db.connect() as conn:
        return conn.execute("select id, source, explanation, reason, flags, created_at from plan_proposals "
                            "where status = 'pending' order by created_at desc limit 10").fetchall()


@app.post("/api/plan/proposals/{proposal_id}/apply", dependencies=[Depends(require_admin)])
def api_apply_proposal(proposal_id: str, accepted_warns: list[str] = Body(default=[], embed=True)) -> dict:
    """The Confirm button: applies a proposal if it still passes every rule."""
    from app import db
    from app.planning import changes
    try:
        with db.connect() as conn:
            return changes.apply(conn, proposal_id, accepted_warns, clock.today())
    except changes.ChangeError as e:
        raise HTTPException(409, str(e))


@app.post("/api/plan/proposals/{proposal_id}/cancel", dependencies=[Depends(require_admin)])
def api_cancel_proposal(proposal_id: str) -> dict:
    from app import db
    from app.planning import changes
    with db.connect() as conn:
        changes.cancel(conn, proposal_id)
    return {"cancelled": True}


@app.post("/api/plan/undo/{batch_id}", dependencies=[Depends(require_admin)])
def api_undo(batch_id: str) -> dict:
    """Undo a plan change (chat edit or auto-rebase) within 7 days."""
    from app import db
    from app.planning import changes
    try:
        with db.connect() as conn:
            return changes.undo(conn, batch_id, clock.today())
    except changes.ChangeError as e:
        raise HTTPException(409, str(e))


@app.get("/api/plan", dependencies=[Depends(require_admin)])
def api_plan(days: int = Query(default=28, ge=1, le=60)) -> dict:
    from app import db, today as view
    with db.connect() as conn:
        t = clock.today()
        return view.plan(conn, t - timedelta(days=t.weekday()), days, today=t)


@app.get("/api/trends", dependencies=[Depends(require_admin)])
def api_trends() -> dict:
    from app import db, today as view
    with db.connect() as conn:
        return view.trends(conn, clock.today())


@app.get("/api/reports", dependencies=[Depends(require_admin)])
def api_reports() -> list:
    from app import db, reports
    with db.connect() as conn:
        return reports.list_reports(conn)


@app.post("/admin/report", dependencies=[Depends(require_admin)])
def admin_report(week: str | None = Query(default=None, description="Monday, YYYY-MM-DD; default last week")) -> dict:
    """Write (or rewrite) a weekly report and re-plan the next 3 weeks."""
    from datetime import date as _date
    from app import db, reports
    t = clock.today()
    ws = _date.fromisoformat(week) if week else t - timedelta(days=t.weekday() + 7)
    if ws.weekday() != 0:
        raise HTTPException(400, "week must be a Monday")
    with db.connect() as conn:
        r = reports.build(conn, ws, today=t)
    return {"week_start": r["week_start"], "model": r["model"], "next_week": r["summary"]["next_week"]}


@app.post("/api/chat", dependencies=[Depends(require_admin)])
def api_chat(message: str = Body(..., embed=True, max_length=4000),
             conversation_id: int | None = Body(default=None, embed=True)) -> dict:
    from app import chat, db
    if not message.strip():
        raise HTTPException(400, "empty message")
    try:
        with db.connect() as conn:
            return chat.ask(conn, message.strip(), conversation_id)
    except MissingConfig as e:
        raise HTTPException(503, str(e))


@app.get("/api/chat", dependencies=[Depends(require_admin)])
def api_conversations() -> list:
    from app import chat, db
    with db.connect() as conn:
        return chat.conversations(conn)


@app.get("/api/chat/{conversation_id}", dependencies=[Depends(require_admin)])
def api_conversation(conversation_id: int) -> list:
    from app import chat, db
    with db.connect() as conn:
        return chat.messages(conn, conversation_id)


@app.post("/admin/sync", dependencies=[Depends(require_admin)])
def admin_sync(days: int = Query(default=3, ge=1, le=730), morning: bool = False) -> dict:
    """Start a sync in the background; poll /admin/sync/status for the result."""
    import threading
    from app.ingest import runner
    kind = "backfill" if days >= 60 else "manual"
    threading.Thread(target=runner.run, kwargs={"kind": kind, "days": days, "morning": morning},
                     daemon=True).start()
    return {"started": kind, "days": days}


@app.get("/admin/sync/status", dependencies=[Depends(require_admin)])
def admin_sync_status() -> dict:
    from app import db
    with db.connect() as conn:
        runs = conn.execute("select id, kind, started_at, finished_at, ok, summary from sync_runs "
                            "order by id desc limit 5").fetchall()
        counts = conn.execute(
            """select (select count(*) from activities) as activities, (select count(*) from laps) as laps,
                      (select count(*) from strength_sets) as strength_sets,
                      (select count(*) from recovery) as recovery_days,
                      (select resting_hr_baseline from profile where id = 1) as resting_hr_baseline""").fetchone()
    return {"counts": counts, "runs": runs}


@app.get("/admin/backup", dependencies=[Depends(require_admin)])
def admin_backup():
    """Download every table as CSVs in one zip (provider tokens left out)."""
    from app import db
    from scripts import backup
    with db.connect() as conn:
        blob = backup.export(conn)
    name = f"training-backup-{clock.today().isoformat()}.zip"
    return Response(blob, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


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
