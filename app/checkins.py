"""Post-workout check-in: RPE, how it felt, any pain. Three taps.

What the answers do:
  * felt bad or pain -> the check-in day and the next two run under caution
    (intensity capped at Z2, no long-run growth), with the reason shown;
  * RPE 8+ on a session prescribed Z2 or easier -> flag ``rpe_mismatch``;
  * pain twice in 7 days (same place, or any pain if no place given) ->
    flag ``recurring_pain`` plus an injury note the weekly report and
    Pat-GPT both read.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.analysis.flags import Flag, Severity

CAUTION_DAYS = 2           # the check-in day plus the next two
RPE_MISMATCH = 8
EASY_ZONES = (None, "Z1", "Z2")
RECURRING_WINDOW = 7
SPORT_WORD = {"run": "run", "bike": "ride", "swim": "swim", "strength": "session"}


# ── what is waiting for a check-in ───────────────────────────────────────
def pending(conn, today: date) -> dict | None:
    """The most recent finished session without a check-in: a matched planned
    session from the last 2 days, else yesterday's extra (unplanned) activity."""
    r = conn.execute(
        """select w.id as planned_workout_id, w.activity_id, w.plan_date as date, w.title, w.sport
           from planned_workouts w
           where w.activity_id is not null and w.plan_date between %s and %s
             and not exists (select 1 from check_ins c where c.planned_workout_id = w.id)
           order by w.plan_date desc, w.id desc limit 1""",
        (today - timedelta(days=2), today)).fetchone()
    if r:
        return dict(r)
    r = conn.execute(
        """select null::bigint as planned_workout_id, a.id as activity_id, a.local_date as date,
                  coalesce(a.title, a.sport) as title, a.sport
           from activities a
           where a.local_date = %s
             and not exists (select 1 from planned_workouts w where w.activity_id = a.id)
             and not exists (select 1 from check_ins c where c.activity_id = a.id)
           order by a.start_local desc limit 1""", (today - timedelta(days=1),)).fetchone()
    return dict(r) if r else None


# ── the gate's subjective input ──────────────────────────────────────────
def _describe(ci: dict) -> str:
    bits = []
    if ci["felt"] == "bad":
        bits.append("felt bad")
    if ci["pain"]:
        bits.append(f"{ci['pain_detail'].strip()} pain" if ci.get("pain_detail") else "pain")
    return " + ".join(bits)


def caution_reason(rows: list[dict], d: date) -> str | None:
    """Reason text if a bad/pain check-in covers day ``d``, else None."""
    hits = [r for r in rows if (r["felt"] == "bad" or r["pain"])
            and r["check_in_on"] <= d <= r["check_in_on"] + timedelta(days=CAUTION_DAYS)]
    if not hits:
        return None
    ci = max(hits, key=lambda r: (r["check_in_on"], r["id"]))
    when = ("Today's" if ci["check_in_on"] == d else "Yesterday's" if ci["check_in_on"] == d - timedelta(days=1)
            else f"{ci['check_in_on']:%b %-d}")
    until = ci["check_in_on"] + timedelta(days=CAUTION_DAYS)
    return f"{when} check-in: {_describe(ci)}. Easy only through {until:%A}."


def recent(conn, since: date) -> list[dict]:
    return conn.execute("select * from check_ins where check_in_on >= %s order by check_in_on, id",
                        (since,)).fetchall()


def reason_for(conn, d: date) -> str | None:
    return caution_reason(recent(conn, d - timedelta(days=CAUTION_DAYS)), d)


# ── submit ───────────────────────────────────────────────────────────────
def submit(conn, *, planned_workout_id: int | None = None, activity_id: int | None = None,
           rpe: int | None, felt: str | None, pain: bool = False, pain_detail: str | None = None,
           note: str | None = None) -> dict:
    """Save (or replace) the check-in for one session and apply its effects.
    Returns what changed, so the app can say it in one sentence."""
    from app.ingest import evaluate
    if planned_workout_id is None and activity_id is None:
        raise ValueError("planned_workout_id or activity_id is required")
    plan = None
    if planned_workout_id is not None:
        plan = conn.execute("select * from planned_workouts where id = %s", (planned_workout_id,)).fetchone()
        if not plan:
            raise LookupError("no such planned workout")
        activity_id = activity_id or plan["activity_id"]
        on = plan["plan_date"]
    else:
        act = conn.execute("select * from activities where id = %s", (activity_id,)).fetchone()
        if not act:
            raise LookupError("no such activity")
        on = act["local_date"]
    pain_detail = (pain_detail or "").strip() or None if pain else None
    vals = (activity_id, planned_workout_id, on, rpe, felt, pain, pain_detail, note)
    if planned_workout_id is not None:
        ci = conn.execute(
            """insert into check_ins (activity_id, planned_workout_id, check_in_on, rpe, felt, pain, pain_detail, note)
               values (%s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (planned_workout_id) do update set activity_id = excluded.activity_id,
                 rpe = excluded.rpe, felt = excluded.felt, pain = excluded.pain,
                 pain_detail = excluded.pain_detail, note = excluded.note
               returning *""", vals).fetchone()
    else:
        ci = conn.execute(
            """insert into check_ins (activity_id, planned_workout_id, check_in_on, rpe, felt, pain, pain_detail, note)
               values (%s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (activity_id) where planned_workout_id is null do update set
                 rpe = excluded.rpe, felt = excluded.felt, pain = excluded.pain,
                 pain_detail = excluded.pain_detail, note = excluded.note
               returning *""", vals).fetchone()

    effects: list[str] = []
    if felt == "bad" or pain:
        until = on + timedelta(days=CAUTION_DAYS)
        effects.append(f"This caps intensity at Z2 and holds your long run through {until:%A}.")

    # RPE vs what was prescribed.
    flag_subject = ("planned_workout", planned_workout_id) if plan else ("activity", activity_id)
    if plan and rpe is not None and rpe >= RPE_MISMATCH and plan["max_zone"] in EASY_ZONES:
        word = SPORT_WORD.get(plan["sport"], "session")
        evaluate.save_flag(conn, Flag("rpe_mismatch", Severity.WARN,
                                      f"That easy {word} felt hard (RPE {rpe}). Fatigue or illness may be "
                                      "brewing; keep the next 48h easy.", {"rpe": rpe, "check_in_id": ci["id"]}),
                           on, *flag_subject)
        effects.append("Flagged: an easy session felt hard.")
    else:
        conn.execute("delete from flags where kind = 'rpe_mismatch' and flag_date = %s and subject_type = %s "
                     "and subject_id = %s", (on, *flag_subject))

    # Pain twice in a week.
    if pain:
        prior = conn.execute(
            """select * from check_ins where pain and id <> %s and check_in_on between %s and %s
               order by check_in_on desc""", (ci["id"], on - timedelta(days=RECURRING_WINDOW - 1), on)).fetchall()
        match = [p for p in prior if _same_pain(p["pain_detail"], pain_detail)]
        if match:
            where = pain_detail or match[0]["pain_detail"] or "unspecified"
            days = ", ".join(f"{d:%b %-d}" for d in sorted({on, *(p["check_in_on"] for p in match)}))
            msg = f"Pain twice in a week ({where}: {days}). Back off and get it looked at if it continues."
            evaluate.save_flag(conn, Flag("recurring_pain", Severity.WARN, msg, {"where": where}),
                               on, "check_in", ci["id"])
            exists = conn.execute(
                """select 1 from weekly_notes where source = 'checkin' and type = 'injury'
                   and note_date >= %s and lower(text) like %s""",
                (on - timedelta(days=RECURRING_WINDOW - 1), f"%{where.lower()}%")).fetchone()
            if not exists:
                conn.execute(
                    """insert into weekly_notes (week_start, note_date, type, text, source)
                       values (%s, %s, 'injury', %s, 'checkin')""",
                    (on - timedelta(days=on.weekday()), on, f"Recurring pain: {where} ({days})."))
            effects.append("Pain twice this week: flagged and noted as a possible injury.")
    conn.commit()
    return {"check_in": ci, "effects": effects}


def _same_pain(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    a, b = a.lower().strip(), b.lower().strip()
    return a in b or b in a


def rpe_trend(conn, start: date, end: date) -> list[dict]:
    """7-day rolling average RPE per day (days with no check-in in the
    window are left out)."""
    rows = conn.execute("select check_in_on, rpe from check_ins where rpe is not null and check_in_on between %s and %s",
                        (start - timedelta(days=6), end)).fetchall()
    out, d = [], start
    while d <= end:
        win = [r["rpe"] for r in rows if d - timedelta(days=6) <= r["check_in_on"] <= d]
        if win:
            out.append({"day": d, "rpe7": round(sum(win) / len(win), 1)})
        d += timedelta(days=1)
    return out
