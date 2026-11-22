"""The coming week's planned workouts as a calendar feed (.ics) on its own calendar.

He subscribes to the feed's address once (Google Calendar "From URL", or iPhone
Settings → Calendar → Subscribed Calendars). It shows up as a separate
"Training" calendar he can hide or colour, apart from his normal one, and it
follows every re-plan by itself. Only the next 7 days are in it, so a change in
the plan never leaves weeks of stale events behind. Events are all-day and carry
no alerts, so they never notify.

The address carries a key derived from ADMIN_TOKEN (not the token itself), so
sharing a calendar link never gives away the app's password.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone

DAYS = 7
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


def build(conn, today: date, days: int = DAYS) -> str:
    rows = conn.execute(
        """select id, plan_date, sport, title, duration_min, structure, notes from planned_workouts
           where plan_date between %s and %s and status = 'planned' order by plan_date, id""",
        (today, today + timedelta(days=days - 1))).fetchall()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//training app//workouts//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{NAME}", "X-WR-CALDESC:The coming week's planned workouts",
             "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for s in rows:
        d = s["plan_date"]
        lines += ["BEGIN:VEVENT", f"UID:tc-{s['id']}@training-app", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_esc(_summary(s))}", f"DESCRIPTION:{_esc(_description(s))}",
                  "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"
