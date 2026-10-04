"""Turn a generated week into changes against what's already planned.

Unchanged sessions are left alone (their brief and labels refresh in
place). Everything else becomes move / modify / add / remove operations
that go through app/planning/changes.py, so every generated row passes the
same checks as a chat edit and leaves a plan_changes row.

Apply policies:
  apply    weekly generation, manual runs, re-plans after the health state
           changes: write everything that passes (warnings are information)
  clean    automatic rebase: write only if nothing warns; otherwise store a
           proposal for Patrick to confirm; never write a STOP
  propose  chat "replan my week": always a proposal
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from psycopg.types.json import Jsonb

from app.analysis.flags import Flag, Severity
from app.planning import changes, generator

OWNED_SOURCES = ("generator", "system")
COMPARE = ("sport", "title", "duration_min", "distance_mi", "max_zone", "is_long")
REASONS = {"weekly": "weekly plan", "rebase": "re-plan after a change in health, travel or schedule",
           "chat": "re-plan you asked for", "manual": "manual re-plan"}


def _draft_row(x: generator.Draft, preview: bool) -> dict:
    st = dict(x.structure)
    if preview:
        st["preview"] = True
    else:
        st.pop("preview", None)
    return {"plan_date": x.date, "sport": x.sport, "title": x.title, "phase_id": None, "planned_start": None,
            "duration_min": x.duration_min, "distance_mi": x.distance_mi,
            "max_zone": x.zone if x.zone != "race" else None, "is_long": x.is_long, "is_key": x.is_key,
            "structure": st, "est_load": None, "status": "planned", "source": "generator", "notes": x.notes}


def _same(a: dict, b: dict) -> bool:
    def norm(v):
        return round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    return all(norm(a.get(k)) == norm(b.get(k)) for k in COMPARE)


def week_context(conn, ws: date, today: date) -> tuple[list[dict], list[str]]:
    """(rows Patrick changed himself, gen_keys of key sessions missed so far)."""
    end = ws + timedelta(days=6)
    fixed = [dict(r) for r in conn.execute(
        """select * from planned_workouts where plan_date between %s and %s and status in ('planned','done')
           and source = 'chat'""", (ws, end)).fetchall()]
    missed = [r["structure"]["gen_key"] for r in conn.execute(
        """select structure from planned_workouts where plan_date between %s and %s and plan_date < %s
           and activity_id is null and status in ('planned', 'skipped') and is_key
           and structure ? 'gen_key'""", (ws, end, today)).fetchall()]
    return fixed, missed


def diff(conn, wp: generator.WeekPlan, today: date, preview: bool) -> tuple[list[changes.Op], list[tuple[int, dict]]]:
    """(operations, metadata-only refreshes [(row id, structure)])."""
    start, end = max(wp.week_start, today), wp.week_start + timedelta(days=6)
    current = [dict(r) for r in conn.execute(
        """select * from planned_workouts where plan_date between %s and %s and status = 'planned'
           and activity_id is null and source = any(%s) order by plan_date, id""",
        (start, end, list(OWNED_SOURCES))).fetchall()]
    coach_days = {r["plan_date"] for r in conn.execute(
        "select distinct plan_date from planned_workouts where plan_date between %s and %s "
        "and status in ('planned','done') and source = 'coach'", (start, end)).fetchall()}
    by_key = {(r["structure"] or {}).get("gen_key"): r for r in current if (r["structure"] or {}).get("gen_key")}
    ops: list[changes.Op] = []
    refresh: list[tuple[int, dict]] = []
    matched: set[int] = set()
    for x in wp.drafts:
        if x.date < start or x.date in coach_days or x.sport == "race":
            continue
        new = _draft_row(x, preview)
        old = by_key.get(x.structure.get("gen_key"))
        if old is None or old["id"] in matched:
            ops.append(changes.Op("add", None, new))
            continue
        matched.add(old["id"])
        if _same(old, new) and old["plan_date"] == new["plan_date"]:
            st = {**(old["structure"] or {}), **new["structure"]}
            if not new["structure"].get("flags"):
                st.pop("flags", None)
            if preview is False:
                st.pop("preview", None)
            if st != (old["structure"] or {}):
                refresh.append((old["id"], st))
            continue
        if _same(old, new):
            why = (x.structure.get("moved_from") or {}).get("why") or "re-plan"
            ops.append(changes.Op("move", old, new, why))
        else:
            ops.append(changes.Op("modify", old, new))
    for r in current:
        if r["id"] not in matched:
            ops.append(changes.Op("remove", r, None, "no longer in the plan", remove_status="superseded"))
    return ops, refresh


def plan_and_sync(conn, ws: date, *, basis_mi: float, factor: float, hist, today: date, cal,
                  preview: bool, trigger: str, policy: str = "apply") -> generator.WeekPlan:
    fixed, missed = week_context(conn, ws, today)
    wp = generator.plan_week(conn, ws, basis_mi=basis_mi, factor=factor, hist=hist, today=today, cal=cal,
                             fixed=fixed, missed_keys=missed)
    sync(conn, wp, today, preview=preview, trigger=trigger, policy=policy)
    return wp


def sync(conn, wp: generator.WeekPlan, today: date, *, preview: bool, trigger: str,
         policy: str = "apply", conversation_id: int | None = None) -> dict:
    ops, refresh = diff(conn, wp, today, preview)
    for rid, st in refresh:
        conn.execute("update planned_workouts set structure = %s where id = %s", (Jsonb(st), rid))
    result: dict = {"week_start": wp.week_start, "ops": len(ops), "applied": False}
    checked = changes.check(conn, ops, today) if ops else changes.Checked([], [])
    if checked.stops:          # never write what the rules stop: drop those sessions, flag the week
        bad_days = {f["date"] for f in checked.stops}
        kept = [o for o in ops if not (o.after and o.after["plan_date"] in bad_days) and None not in bad_days]
        for f in checked.stops:
            wp.needs_review.append(f"Left out: {f['message']}")
        ops = kept
        checked = changes.check(conn, ops, today) if ops else changes.Checked([], [])
    reason = REASONS.get(trigger, trigger)
    if ops and not checked.stops:
        if policy == "propose" or (policy == "clean" and checked.warns):
            p = changes.store_proposal(conn, ops, checked, source="chat" if policy == "propose" else "system",
                                       reason=reason, conversation_id=conversation_id)
            result.update(proposal=p)
        else:
            source = "system" if policy == "clean" else "generator"
            result["batch_id"] = changes.write(conn, ops, checked, source=source, reason=reason)
            result["applied"] = True
            result["changes"] = changes.describe(ops)
    for msg in wp.needs_review:
        generator_flag(conn, wp.week_start, "needs_review", Severity.WARN, msg)
    conn.execute(
        """insert into plan_generations (week_start, trigger, inputs_hash, validator_pass, flags)
           values (%s, %s, %s, %s, %s::jsonb)""",
        (wp.week_start, trigger, wp.inputs_hash,
         not any(f["severity"] == "stop" for f in wp.flags) and not checked.stops,
         json.dumps(wp.flags + [dict(f, date=str(f["date"])) for f in checked.flags], default=str)))
    conn.commit()
    return result


def generator_flag(conn, ws: date, kind: str, sev: Severity, msg: str) -> None:
    from app.ingest import evaluate
    import hashlib
    sid = int(hashlib.sha1(msg.encode()).hexdigest()[:7], 16)       # stable across runs (dedupe)
    evaluate.save_flag(conn, Flag(kind, sev, msg, {}), ws, "week", sid)


def last_hash(conn, ws: date) -> str | None:
    r = conn.execute("select inputs_hash from plan_generations where week_start = %s order by id desc limit 1",
                     (ws,)).fetchone()
    return r["inputs_hash"] if r else None
