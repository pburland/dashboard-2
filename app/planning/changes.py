"""The one path that changes planned workouts after they're written.

Chat edits, the generator's re-plans and automatic rebases all come here:

  resolve(actions)   -> concrete operations on rows (supersede / insert)
  check(...)         -> health gate + validator + travel + calendar on the
                        hypothetical week(s); flags only for what changed
  propose(...)       -> stored, waits for Patrick's confirmation
  apply(...)         -> re-checks against the current plan, refuses on any
                        STOP, needs every WARN accepted, then writes and
                        records each change in plan_changes
  undo(batch)        -> restores the rows a change replaced (7 days)

History is never deleted: a changed row is marked 'superseded' (or
'skipped' when removed) and a new row is inserted.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from app import db, travel
from app.analysis.flags import Severity
from app.analysis.load import estimate_planned_load
from app.analysis.validator import PlannedSession, validate_week
from app.periodization.phases import NoPhaseDefined, phase_for

LIVE = ("planned", "done")
UNDO_DAYS = 7
EDITABLE_FIELDS = ("sport", "title", "duration_min", "distance_mi", "max_zone", "is_long")
ROW_FIELDS = ("plan_date", "sport", "title", "phase_id", "planned_start", "duration_min", "distance_mi",
              "max_zone", "is_long", "is_key", "structure", "est_load", "status", "source", "notes")


class ChangeError(ValueError):
    """A request that can't become a change (bad id, past date, ...)."""


@dataclass
class Op:
    action: str                   # move | swap | remove | add | modify
    before: dict | None           # existing row (dict with id) or None for add
    after: dict | None            # new row (no id) or None for remove
    note: str = ""
    remove_status: str = "skipped"   # what a removed row becomes (superseded when re-planned away)


@dataclass
class Checked:
    ops: list[Op]
    flags: list[dict]             # [{key, kind, severity, message, date}]
    weeks: list[date] = field(default_factory=list)

    @property
    def stops(self) -> list[dict]:
        return [f for f in self.flags if f["severity"] == "stop"]

    @property
    def warns(self) -> list[dict]:
        return [f for f in self.flags if f["severity"] == "warn"]


# ── rows ─────────────────────────────────────────────────────────────────
def _row(conn, wid: int) -> dict:
    r = conn.execute("select * from planned_workouts where id = %s", (wid,)).fetchone()
    if not r:
        raise ChangeError(f"workout {wid} doesn't exist")
    if r["status"] not in ("planned",):
        raise ChangeError(f"'{r['title']}' on {r['plan_date']:%a %b %-d} is {r['status']}; only planned sessions can change")
    return dict(r)


def fingerprint(r: dict) -> str:
    keep = {k: r.get(k) for k in ("id", "plan_date", "sport", "title", "duration_min", "distance_mi",
                                  "max_zone", "is_long", "status")}
    return hashlib.sha1(json.dumps(keep, default=str, sort_keys=True).encode()).hexdigest()[:16]


def _copy(r: dict, **changes) -> dict:
    new = {k: r.get(k) for k in ROW_FIELDS}
    new.update(changes)
    new["status"] = "planned"
    new["planned_start"] = None if "plan_date" in changes else r.get("planned_start")
    return new


def _parse_date(s) -> date:
    try:
        return s if isinstance(s, date) else date.fromisoformat(str(s))
    except ValueError:
        raise ChangeError(f"bad date {s!r}")


def resolve(conn, actions: list[dict], today: date) -> list[Op]:
    """Turn requested actions into row operations. Raises ChangeError."""
    ops: list[Op] = []
    for a in actions:
        kind = a.get("action")
        if kind == "move":
            r = _row(conn, int(a["workout_id"]))
            to = _parse_date(a["to"])
            ops.append(Op("move", r, _copy(r, plan_date=to)))
        elif kind == "swap":
            ra, rb = _row(conn, int(a["workout_id_a"])), _row(conn, int(a["workout_id_b"]))
            ops.append(Op("swap", ra, _copy(ra, plan_date=rb["plan_date"])))
            ops.append(Op("swap", rb, _copy(rb, plan_date=ra["plan_date"])))
        elif kind == "remove":
            ops.append(Op("remove", _row(conn, int(a["workout_id"])), None, a.get("reason") or ""))
        elif kind == "modify":
            r = _row(conn, int(a["workout_id"]))
            changes = {k: a[k] for k in EDITABLE_FIELDS if k in a}
            if not changes:
                raise ChangeError("modify needs at least one field to change")
            ops.append(Op("modify", r, _copy(r, **changes)))
        elif kind == "add":
            d = _parse_date(a["plan_date"])
            ops.append(Op("add", None, {
                "plan_date": d, "sport": a["sport"], "title": a.get("title") or a["sport"].title(),
                "phase_id": None, "planned_start": None, "duration_min": a.get("duration_min"),
                "distance_mi": a.get("distance_mi"), "max_zone": a.get("max_zone") or "Z2",
                "is_long": bool(a.get("is_long")), "is_key": bool(a.get("is_long")),
                "structure": {}, "est_load": None, "status": "planned", "source": "chat", "notes": None}))
        else:
            raise ChangeError(f"unknown action {kind!r}")
    for op in ops:
        if op.after and op.after["plan_date"] < today:
            raise ChangeError(f"{op.after['plan_date']:%a %b %-d} is in the past")
        if op.after and not op.after.get("duration_min"):
            raise ChangeError(f"'{op.after['title']}' needs a duration")
    return ops


# ── checking ─────────────────────────────────────────────────────────────
def _session(r: dict) -> PlannedSession:
    return PlannedSession(r["plan_date"], r["sport"], r["title"], r.get("duration_min") or 0,
                          r.get("max_zone") or "Z2", r.get("distance_mi"), bool(r.get("is_long")),
                          bool((r.get("structure") or {}).get("heavy_lower")))


def _week_rows(conn, ws: date) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "select * from planned_workouts where plan_date between %s and %s and status in ('planned', 'done') "
        "order by plan_date, id", (ws, ws + timedelta(days=6))).fetchall()]


def _flag_key(kind: str, d: date | None) -> str:
    return f"{kind}:{d.isoformat() if d else 'week'}"


def check(conn, ops: list[Op], today: date) -> Checked:
    from app.integrations import calendar
    from app.planning import generator, timing
    removed = {op.before["id"] for op in ops if op.before}
    added = [op.after for op in ops if op.after]
    weeks = sorted({d - timedelta(days=d.weekday()) for d in
                    [op.before["plan_date"] for op in ops if op.before] + [r["plan_date"] for r in added]})
    gate_for = generator.day_gate(conn, today, min(weeks) if weeks else today)
    flags: list[dict] = []

    def add(kind, sev, msg, d):
        key = _flag_key(kind, d)
        if not any(f["key"] == key and f["message"] == msg for f in flags):
            flags.append({"key": key, "kind": kind, "severity": sev, "message": msg, "date": d})

    stops = travel.load(conn)
    for r in added:
        d = r["plan_date"]
        g = gate_for(d)
        if not g.prescriptions_allowed:
            add("health_hold", "stop", f"{d:%a %b %-d} is inside your health hold ({g.reasons[0]}).", d)
        place = travel.place_for(stops, d)
        if place.away and r["sport"] not in (place.sports or ()) and not (
                r["sport"] == "strength" and "bodyweight" in (r.get("title") or "").lower() and place.sports):
            what = "a travel day with no training" if not place.sports else f"in {place.name} (only {', '.join(place.sports)})"
            add("travel", "stop", f"{d:%a %b %-d} you're {what}.", d)
    # Calendar: is there a window long enough that day? (warn: he may know better)
    try:
        cal_days = sorted({r["plan_date"] for r in added})
        from zoneinfo import ZoneInfo
        busy = calendar.busy(min(cal_days), max(cal_days), ZoneInfo(travel.home().tz_name)) if cal_days else []
        for r in added:
            place = travel.place_for(stops, r["plan_date"])
            slots = timing.free_slots(r["plan_date"], ZoneInfo(place.tz_name), [] if place.away else busy, place.away)
            need = timedelta(minutes=r.get("duration_min") or 30)
            if not any(e - s >= need for s, e in slots):
                add("calendar", "warn", f"No free {int(need.total_seconds() // 60)}-min window on "
                                        f"{r['plan_date']:%a %b %-d} in your usual training times.", r["plan_date"])
    except Exception:
        pass            # calendar not connected or unreachable: windows only

    caps = conn.execute("select daily_minutes from profile where id = 1").fetchone()
    cap = ((caps or {}).get("daily_minutes") or {}).get("default", 210)
    for ws in weeks:
        current = _week_rows(conn, ws)
        hypo = [r for r in current if r["id"] not in removed] + \
               [r for r in added if ws <= r["plan_date"] <= ws + timedelta(days=6)]
        hist = generator.history(conn, ws, planned_from=today)
        base_v = validate_week([_session(r) for r in current], hist, gate_for) if current else None
        new_v = validate_week([_session(r) for r in hypo], hist, gate_for) if hypo else None
        if not new_v:
            continue
        base_msgs = set()
        if base_v:
            base_msgs = {(f.kind, f.message) for fl in base_v.flags.values() for f in fl} | \
                        {(f.kind, f.message) for f in base_v.week_flags}
        for i, fl in new_v.flags.items():
            r = hypo[i]
            if "id" in r and r["id"] not in removed:         # unchanged session: its flags aren't news
                continue
            for f in fl:
                if (f.kind, f.message) in base_msgs:
                    continue
                add(f.kind, f.severity.value, f.message, r["plan_date"])
        returning = gate_for(ws + timedelta(days=3)).status.value == "return"
        for f in new_v.week_flags:
            if returning and f.kind == "weekly_ramp":
                continue                     # the return phase's own ramp (50% -> 90%) governs
            if (f.kind, f.message) not in base_msgs:
                add(f.kind, f.severity.value, f.message, None)
        for d in {r["plan_date"] for r in added if ws <= r["plan_date"] <= ws + timedelta(days=6)}:
            total = sum(r.get("duration_min") or 0 for r in hypo if r["plan_date"] == d)
            if total > cap:
                add("daily_cap", "warn", f"{d:%a %b %-d} would total {int(total)} min (your cap is {cap}).", d)
    return Checked(ops, flags, weeks)


# ── proposals ────────────────────────────────────────────────────────────
def _jsonable(x):
    return json.loads(json.dumps(x, default=str))


def _ops_json(ops: list[Op]) -> list[dict]:
    return _jsonable([{"action": o.action, "before": o.before, "after": o.after, "note": o.note,
                       "remove_status": o.remove_status} for o in ops])


def _ops_from_json(conn, items: list[dict]) -> list[Op]:
    ops = []
    for o in items:
        before = None
        if o.get("before"):
            before = conn.execute("select * from planned_workouts where id = %s", (o["before"]["id"],)).fetchone()
            before = dict(before) if before else None
        after = dict(o["after"]) if o.get("after") else None
        if after:
            after["plan_date"] = _parse_date(after["plan_date"])
        ops.append(Op(o["action"], before, after, o.get("note") or "", o.get("remove_status") or "skipped"))
    return ops


def store_proposal(conn, ops: list[Op], checked: Checked, *, source: str, reason: str,
                   conversation_id: int | None = None) -> dict:
    status = "refused" if checked.stops else "pending"
    row = conn.execute(
        """insert into plan_proposals (source, conversation_id, actions, base, flags, explanation, reason, status)
           values (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s) returning id""",
        (source, conversation_id, json.dumps(_ops_json(ops)),
         json.dumps({str(o.before["id"]): fingerprint(o.before) for o in ops if o.before}),
         json.dumps(_jsonable(checked.flags)), "; ".join(describe(ops)), reason, status)).fetchone()
    return {"proposal_id": str(row["id"]), "status": status, "changes": describe(ops),
            "flags": _jsonable(checked.flags), "pass": not checked.stops,
            "needs_ack": [f["key"] for f in checked.warns], "reason": reason}


def describe(ops: list[Op]) -> list[str]:
    out = []
    for o in ops:
        b, a = o.before, o.after
        if o.action in ("move", "swap"):
            out.append(f"{b['title']}: {b['plan_date']:%a %b %-d} -> {a['plan_date']:%a %b %-d}")
        elif o.action == "remove":
            out.append(f"Drop {b['title']} on {b['plan_date']:%a %b %-d}")
        elif o.action == "add":
            out.append(f"Add {a['title']} on {a['plan_date']:%a %b %-d} ({int(a['duration_min'])} min)")
        else:
            diffs = [f"{k} {b.get(k)} -> {a.get(k)}" for k in EDITABLE_FIELDS if b.get(k) != a.get(k)]
            out.append(f"{b['title']} on {b['plan_date']:%a %b %-d}: " + ", ".join(diffs))
    return out


def propose(conn, actions: list[dict], *, source: str, reason: str, today: date,
            conversation_id: int | None = None) -> dict:
    """Validate requested actions and store them for confirmation. Writes no plan rows."""
    ops = resolve(conn, actions, today)
    c = check(conn, ops, today)
    out = store_proposal(conn, ops, c, source=source, reason=reason, conversation_id=conversation_id)
    conn.commit()
    return out


def apply(conn, proposal_id: str, accepted_warns: list[str], today: date) -> dict:
    """Apply a pending proposal after confirmation. Fails closed."""
    p = conn.execute("select * from plan_proposals where id = %s for update", (proposal_id,)).fetchone()
    if not p:
        raise ChangeError("no such proposal")
    if p["status"] != "pending":
        raise ChangeError(f"this proposal is {p['status']}")
    for wid, fp in (p["base"] or {}).items():
        cur = conn.execute("select * from planned_workouts where id = %s", (int(wid),)).fetchone()
        if not cur or fingerprint(dict(cur)) != fp or cur["status"] != "planned":
            conn.execute("update plan_proposals set status = 'stale', decided_at = now() where id = %s", (proposal_id,))
            conn.commit()
            if p["source"] != "chat":
                return {"applied": False, "stale": True,
                        "message": "The plan changed since this was proposed; the morning check will re-plan."}
            try:
                fresh = propose(conn, _actions_from(p["actions"]), source=p["source"], reason=p["reason"],
                                today=today, conversation_id=p["conversation_id"])
            except ChangeError as e:
                fresh = {"error": str(e)}
            return {"applied": False, "stale": True,
                    "message": "The plan changed since this was proposed. Here is the updated proposal.",
                    "new_proposal": fresh}
    ops = _ops_from_json(conn, p["actions"])
    for op in ops:
        if op.after and op.after["plan_date"] < today:
            conn.execute("update plan_proposals set status = 'stale', decided_at = now() where id = %s", (proposal_id,))
            conn.commit()
            return {"applied": False, "stale": True, "message": f"{op.after['plan_date']:%a %b %-d} has passed."}
    c = check(conn, ops, today)
    if c.stops:
        conn.execute("update plan_proposals set status = 'refused', flags = %s::jsonb, decided_at = now() "
                     "where id = %s", (json.dumps(_jsonable(c.flags)), proposal_id))
        conn.commit()
        return {"applied": False, "refused": True, "flags": _jsonable(c.stops)}
    missing = [f for f in c.warns if f["key"] not in set(accepted_warns or [])]
    if missing:
        return {"applied": False, "needs_ack": [f["key"] for f in missing], "flags": _jsonable(missing)}
    batch = write(conn, ops, c, source=p["source"], reason=p["reason"],
                  accepted=[f for f in c.warns])
    conn.execute("update plan_proposals set status = 'applied', plan_change_batch = %s, decided_at = now() "
                 "where id = %s", (batch, proposal_id))
    conn.commit()
    return {"applied": True, "batch_id": batch, "changes": describe(ops)}


def cancel(conn, proposal_id: str) -> None:
    conn.execute("update plan_proposals set status = 'cancelled', decided_at = now() "
                 "where id = %s and status = 'pending'", (proposal_id,))
    conn.commit()


def _actions_from(ops_json: list[dict]) -> list[dict]:
    """Rebuild the requested actions from a stored proposal."""
    out = []
    seen_swap = set()
    for o in ops_json:
        b, a = o["before"], o["after"]
        if o["action"] == "move":
            out.append({"action": "move", "workout_id": b["id"], "to": a["plan_date"]})
        elif o["action"] == "swap":
            if b["id"] in seen_swap:
                continue
            partner = next(x for x in ops_json if x["action"] == "swap" and x["before"]["id"] != b["id"]
                           and x["before"]["plan_date"] == a["plan_date"])
            seen_swap |= {b["id"], partner["before"]["id"]}
            out.append({"action": "swap", "workout_id_a": b["id"], "workout_id_b": partner["before"]["id"]})
        elif o["action"] == "remove":
            out.append({"action": "remove", "workout_id": b["id"], "reason": o.get("note")})
        elif o["action"] == "modify":
            out.append({"action": "modify", "workout_id": b["id"],
                        **{k: a[k] for k in EDITABLE_FIELDS if a.get(k) != b.get(k)}})
        else:
            out.append({"action": "add", **{k: a.get(k) for k in ("plan_date", "sport", "title", "duration_min",
                                                                 "distance_mi", "max_zone", "is_long")}})
    return out


# ── writing ──────────────────────────────────────────────────────────────
def write(conn, ops: list[Op], checked: Checked, *, source: str, reason: str,
          accepted: list[dict] | None = None) -> str:
    """Write already-checked ops. Refuses if any STOP is present (the
    validator-first invariant: nothing failing it reaches the plan)."""
    if checked.stops:
        raise ChangeError("refused: " + "; ".join(f["message"] for f in checked.stops))
    phases = db.load_phases(conn)
    batch = conn.execute("select gen_random_uuid() as u").fetchone()["u"]
    stamp = datetime.now(timezone.utc).date().isoformat()
    for op in ops:
        before = op.before
        if before:
            conn.execute("update planned_workouts set status = %s where id = %s",
                         (op.remove_status if op.action == "remove" else "superseded", before["id"]))
        after_row = None
        if op.after:
            r = dict(op.after)
            try:
                r["phase_id"] = phase_for(phases, r["plan_date"]).id
            except NoPhaseDefined:
                r["phase_id"] = None
            st = dict(r.get("structure") or {})
            st["changed_by"] = {"by": {"chat": "you", "system": "auto-rebase", "generator": "planner",
                                       "coach": "coach"}[source], "on": stamp, "reason": reason,
                                "batch": str(batch)}
            if before and (before.get("structure") or {}).get("gen_key") and "gen_key" not in st:
                st["gen_key"] = before["structure"]["gen_key"]
            if source == "generator" and op.action != "move":
                st.pop("changed_by", None)          # routine planning isn't a "change" worth marking
            r["structure"] = st
            r["source"] = source if source in ("chat", "system") else r.get("source") or "generator"
            if r.get("duration_min") and r.get("max_zone") in ("Z1", "Z2", "Z3", "Z4"):
                r["est_load"] = round(estimate_planned_load(r["duration_min"], r["max_zone"]), 1)
            after_row = conn.execute(
                f"""insert into planned_workouts ({", ".join(ROW_FIELDS)})
                    values ({", ".join(["%s"] * len(ROW_FIELDS))}) returning *""",
                [Jsonb(_jsonable(r[k])) if k == "structure" else r.get(k) for k in ROW_FIELDS]).fetchone()
        d = (op.after or op.before)["plan_date"]
        fl = [f for f in checked.flags if f["date"] in (d, None)]
        conn.execute(
            """insert into plan_changes (batch_id, action, plan_date, before, after, reason, validator_flags,
                   accepted_warns, source)
               values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s)""",
            (batch, op.action, d, json.dumps(_jsonable(before or {})), json.dumps(_jsonable(dict(after_row) if after_row else {})),
             reason + (f" ({op.note})" if op.note else ""), json.dumps(_jsonable(fl)),
             json.dumps(_jsonable([f["key"] for f in accepted or []])), source))
    return str(batch)


def undo(conn, batch_id: str, today: date) -> dict:
    rows = conn.execute("select * from plan_changes where batch_id = %s and undone_at is null", (batch_id,)).fetchall()
    if not rows:
        raise ChangeError("nothing to undo (already undone, or no such change)")
    if min(r["created_at"] for r in rows) < datetime.now(timezone.utc) - timedelta(days=UNDO_DAYS):
        raise ChangeError(f"changes older than {UNDO_DAYS} days can't be undone")
    for r in rows:
        after, before = r["after"] or {}, r["before"] or {}
        if after.get("id"):
            cur = conn.execute("select status from planned_workouts where id = %s", (after["id"],)).fetchone()
            if cur and cur["status"] != "planned":
                raise ChangeError(f"'{after.get('title')}' has already happened or changed again; can't undo")
            conn.execute("update planned_workouts set status = 'superseded' where id = %s", (after["id"],))
        if before.get("id"):
            conn.execute("update planned_workouts set status = %s where id = %s",
                         (before.get("status") or "planned", before["id"]))
    conn.execute("update plan_changes set undone_at = now() where batch_id = %s", (batch_id,))
    conn.commit()
    return {"undone": len(rows)}
