"""Morning auto-rebase: missed sessions and changed circumstances.

Runs after the morning sync. It never invents move rules; it re-runs the
generator for the affected week with what changed (a missed key session,
a trip, the health state, a check-in, the calendar) and applies the result
by policy:

  validator clean   -> applied (source 'system'), an info flag says what moved
  any warning       -> a proposal Patrick confirms on the Today screen
  any STOP          -> nothing written; the conflict is flagged

A missed session is one whose day is over, with no matched activity, on a
day the health gate allowed training. Easy ones are just marked skipped;
missed key sessions trigger a re-plan of the rest of their week.
Every applied rebase can be undone for 7 days (POST /api/plan/undo/{batch}).
"""
from __future__ import annotations

from datetime import date, timedelta

from app.analysis.flags import Flag, Severity
from app.ingest import evaluate
from app.planning import changes, generator, sync

LOOKAHEAD_WEEKS = 2       # this week and next


def _missed(conn, today: date, gate_for) -> list[dict]:
    rows = conn.execute(
        """select * from planned_workouts where plan_date < %s and plan_date >= %s and status = 'planned'
           and activity_id is null and sport <> 'race' order by plan_date""",
        (today, today - timedelta(days=7))).fetchall()
    return [dict(r) for r in rows if gate_for(r["plan_date"]).prescriptions_allowed]


def run(conn, today: date, use_calendar: bool = True) -> dict:
    gate_for = generator.day_gate(conn, today, today - timedelta(days=8))
    actions: list[str] = []

    # 1. Missed sessions: easy ones are skipped; key ones mark their week for re-planning.
    weeks: dict[date, str] = {}
    for r in _missed(conn, today, gate_for):
        ws = r["plan_date"] - timedelta(days=r["plan_date"].weekday())
        op = changes.Op("remove", r, None, "missed", remove_status="skipped")
        changes.write(conn, [op], changes.Checked([op], []), source="system",
                      reason=f"missed {r['title']} on {r['plan_date']:%a %b %-d}")
        actions.append(f"skipped: {r['title']} {r['plan_date']}")
        if r["is_key"] and ws + timedelta(days=6) >= today:
            weeks[ws] = f"missed {r['title']} on {r['plan_date']:%a}"
    conn.commit()

    # 2. Anything the plan depends on changed (trip, health state, check-in, calendar)?
    this_ws = today - timedelta(days=today.weekday())
    cal = generator.Calendar(conn, this_ws, this_ws + timedelta(days=7 * LOOKAHEAD_WEEKS), use_calendar)
    hist = generator.history(conn, this_ws)
    plans: dict[date, generator.WeekPlan] = {}
    for w in range(LOOKAHEAD_WEEKS):
        ws = this_ws + timedelta(days=7 * w)
        last = sync.last_generation(conn, ws)
        if not last and ws not in weeks:
            continue                         # never generated: the weekly job owns it
        inp = (last or {}).get("inputs") or {}
        fixed, missed = sync.week_context(conn, ws, today)
        wp = generator.plan_week(conn, ws, basis_mi=float(inp.get("basis") or 0) or _basis(conn, ws),
                                 factor=float(inp.get("factor") or 1.0), hist=hist, today=today, cal=cal,
                                 fixed=fixed, missed_keys=missed)
        if ws in weeks or not last or wp.inputs_hash != last["inputs_hash"]:
            weeks.setdefault(ws, "your schedule or health changed")
            plans[ws] = wp

    # 3. Re-plan those weeks under the clean-or-confirm policy.
    for ws, why in sorted(weeks.items()):
        wp = plans.get(ws)
        if wp is None:
            fixed, missed = sync.week_context(conn, ws, today)
            wp = generator.plan_week(conn, ws, basis_mi=_basis(conn, ws), hist=hist, today=today, cal=cal,
                                     fixed=fixed, missed_keys=missed)
        conn.execute("""update plan_proposals set status = 'stale', decided_at = now()
                        where status = 'pending' and source = 'system' and exists (
                          select 1 from jsonb_array_elements(actions) a
                          where coalesce(a->'after'->>'plan_date', a->'before'->>'plan_date')::date
                                between %s and %s)""", (ws, ws + timedelta(days=6)))
        res = sync.sync(conn, wp, today, preview=bool((sync.last_generation(conn, ws) or {}).get("inputs", {})
                                                       .get("preview")) and ws > this_ws,
                        trigger="rebase", policy="clean")
        if res.get("applied") and res.get("changes"):
            msg = f"Re-planned ({why}): " + "; ".join(res["changes"]) + ". Safety rules kept."
            evaluate.save_flag(conn, Flag("auto_rebase", Severity.INFO, msg,
                                          {"batch_id": res["batch_id"]}), today, "week", int(ws.strftime("%Y%m%d")))
            actions.append(msg)
        elif res.get("proposal"):
            actions.append(f"proposed for confirmation ({why}): {res['proposal']['changes']}")
    conn.commit()
    return {"actions": actions}


def _basis(conn, ws: date) -> float:
    actual, planned = generator._week_run_mi(conn, ws - timedelta(days=7))
    return actual or planned
