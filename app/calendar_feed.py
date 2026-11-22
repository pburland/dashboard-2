"""Approved weeks' workouts as a calendar feed (.ics) on its own calendar.

He subscribes to the feed's address once (Google Calendar "From URL", or iPhone
Settings → Calendar → Subscribed Calendars). It shows up as a separate
"Training" calendar he can hide or colour, apart from his normal one. Only weeks
he approved on Sunday are in it (app/approval.py), each session as a time block
at the suggested best time (all-day only if no time could be found). Changes the
app makes inside an approved week follow by themselves. No alerts, ever.

The address carries a key derived from ADMIN_TOKEN (not the token itself), so
sharing a calendar link never gives away the app's password.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone

DAYS = 14                       # look-ahead; only approved weeks inside it are shown
NAME = "Training"
ICON = {"run": "🏃", "bike": "🚴", "swim": "🏊", "strength": "🏋️", "brick": "🔁"}


def key(admin_token: str) -> str:
    return hmac.new(admin_token.encode(), b"calendar-feed", hashlib.sha256).hexdigest()[:32]


def _esc(s: str) -> str:
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r", "").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Lines over 75 bytes continue on the next line after a space (RFC 5545)."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > 74:
            out.append(cur)
            cur = " "
        cur += ch
    return "\r\n".join(out + [cur])


def _summary(s: dict) -> str:
    bits = [s["title"]]
    if s.get("duration_min") and str(int(s["duration_min"])) not in s["title"]:
        bits.append(f"{int(s['duration_min'])} min")
    return f"{ICON.get(s['sport'], '•')} " + " · ".join(bits)


def _description(s: dict) -> str:
    st = s.get("structure") or {}
    parts = [st.get("brief") or "", s.get("notes") or ""]
    lifts = st.get("exercises") or []
    if lifts:
        parts.append("\n".join(" ".join(str(x) for x in row if x) for row in lifts))
    parts.append("Planned by the training app. It updates when the plan changes.")
    return "\n\n".join(p for p in parts if p)


def _utc(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build(conn, today: date, days: int = DAYS) -> str:
    from app import approval
    end = today + timedelta(days=days - 1)
    weeks = approval.approved_weeks(conn, today, end)
    rows = [r for r in conn.execute(
        """select id, plan_date, sport, title, duration_min, max_zone, is_long, structure, notes from planned_workouts
           where plan_date between %s and %s and status = 'planned' order by plan_date, id""",
        (today, end)).fetchall() if approval.week_of(r["plan_date"]) in weeks]
    live = {}
    missing = [r for r in rows if str(r["id"]) not in weeks[approval.week_of(r["plan_date"])]["sessions"]]
    if missing:                                    # changed after approval: work out a time now
        from app.planning import timing
        days_ = {}
        for r in missing:
            days_.setdefault(r["plan_date"], []).append(
                {"id": r["id"], "sport": r["sport"], "duration_min": r["duration_min"], "status": "planned",
                 "max_zone": r["max_zone"], "is_long": r["is_long"]})
        try:
            timing.annotate(conn, [{"date": d, "sessions": v} for d, v in days_.items()], today)
        except Exception:
            pass
        live = {s["id"]: s.get("best_time") or {} for v in days_.values() for s in v}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//training app//workouts//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{NAME}", "X-WR-CALDESC:Your approved training weeks",
             "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for s in rows:
        d = s["plan_date"]
        snap = weeks[approval.week_of(d)]["sessions"].get(str(s["id"])) or {}
        t = snap if snap.get("date") == d.isoformat() else (live.get(s["id"]) or {})
        when = ([f"DTSTART:{_utc(t['start'])}", f"DTEND:{_utc(t['end'])}"] if t.get("start") and t.get("end")
                else [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"])
        lines += ["BEGIN:VEVENT", f"UID:tc-{s['id']}@training-app", f"DTSTAMP:{stamp}", *when,
                  f"SUMMARY:{_esc(_summary(s))}", f"DESCRIPTION:{_esc(_description(s))}",
                  "TRANSP:OPAQUE" if t.get("start") else "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"
