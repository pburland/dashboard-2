"""Monthly audit agent support (Patrick, Nov 28 2026).

A scheduled Claude session audits the code, the data and new research once a
month. It reaches the app only with the AUDIT KEY, a value derived from
ADMIN_TOKEN (like the calendar feed key) that unlocks exactly three things:

  GET  /admin/audit/snapshot   data-quality summary: counts, coverage, failures
  GET  /admin/audit/reports    its earlier reports (its memory between runs)
  POST /admin/audit/reports    save this month's report

It can't read or change the plan, settings, chat, or anything else, and it
never touches the code: proposed fixes go in the report, and Patrick decides.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, timedelta


def key(admin_token: str) -> str:
    return hmac.new(admin_token.encode(), b"audit-agent-read-only", hashlib.sha256).hexdigest()[:40]


def snapshot(conn, today: date) -> dict:
    """Aggregates only: what's healthy, what's missing, what failed. No chat or note text."""
    from app import rules
    since28, since30 = today - timedelta(days=28), today - timedelta(days=30)
    one = lambda q, *a: conn.execute(q, a).fetchone()                                   # noqa: E731
    many = lambda q, *a: [dict(r) for r in conn.execute(q, a).fetchall()]               # noqa: E731
    syncs = many("""select kind, started_at, finished_at, ok, left(summary::text, 300) as summary
                    from sync_runs order by started_at desc limit 15""")
    return {
        "generated_for": today,
        "rules_version": rules.VERSION,
        "migrations": [r["name"] for r in conn.execute(
            "select name from schema_migrations order by name desc limit 5").fetchall()]
            if one("select to_regclass('schema_migrations') as t")["t"] else [],
        "sync": {"recent": syncs,
                 "failed_30d": one("select count(*) as n from sync_runs where ok is false and started_at >= %s",
                                   since30)["n"],
                 "never_finished_30d": one("""select count(*) as n from sync_runs where finished_at is null
                                              and started_at >= %s and started_at < now() - interval '2 hours'""",
                                           since30)["n"]},
        "coverage_28d": {
            "recovery_days": one("select count(*) as n from recovery where day >= %s", since28)["n"],
            "recovery_days_with_hrv": one("select count(*) as n from recovery where day >= %s and hrv_ms is not null",
                                          since28)["n"],
            "weigh_in_days": one("select count(*) as n from body_metrics where day >= %s and weight_lb is not null",
                                 since28)["n"],
            "activities_by_sport": many("""select sport, count(*) as n, count(*) filter (where avg_hr is null) as no_hr
                                           from activities where local_date >= %s group by sport""", since28),
            "activities_not_matched_to_plan": one(
                """select count(*) as n from activities a where a.local_date >= %s and a.sport in ('run','bike','swim')
                   and not exists (select 1 from planned_workouts w where w.activity_id = a.id)""", since28)["n"],
            "strength_sessions": one("select count(distinct performed_on) as n from strength_sets where performed_on >= %s",
                                     since28)["n"],
            "check_ins": one("select count(*) as n, count(*) filter (where pain) as pain from check_ins "
                             "where check_in_on >= %s", since28),
        },
        "plan_28d": {
            "by_status": many("""select status, count(*) as n from planned_workouts
                                 where plan_date between %s and %s group by status""", since28, today),
            "past_still_planned": one("""select count(*) as n from planned_workouts where status = 'planned'
                                         and plan_date < %s - 1 and plan_date >= %s""", today, since28)["n"],
            "changes_by_source": many("""select source, action, count(*) as n from plan_changes
                                         where created_at >= %s group by 1, 2 order by 3 desc""", since28),
            "proposals": many("""select status, source, count(*) as n from plan_proposals
                                 where created_at >= %s group by 1, 2""", since28),
            "approved_weeks": [r["week_start"] for r in conn.execute(
                "select week_start from plan_approvals where week_start >= %s order by 1", (since28,)).fetchall()],
        },
        "flags_30d": many("""select kind, severity, count(*) as n from flags where flag_date >= %s
                             group by 1, 2 order by 3 desc""", since30),
        "notifications_30d": many("""select status, count(*) as n from notifications
                                     where created_at >= %s and kind <> 'test' group by 1""", since30),
        "garmin_pushed_upcoming": one("select count(*) as n from garmin_pushed where plan_date >= %s", today)["n"],
        "fitness_tests": many("""select kind, test_date, status, reason from fitness_tests
                                 order by test_date desc limit 10"""),
        "health": many("""select kind, started_on, return_started_on, return_ends_on, closed_on
                          from health_episodes order by started_on desc limit 2"""),
    }


def reports(conn, limit: int = 12) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "select id, created_at, title, summary, findings, followups from audit_reports order by created_at desc limit %s",
        (limit,)).fetchall()]


def save(conn, title: str, summary: str, findings: list, followups: list) -> dict:
    if not title.strip() or not summary.strip():
        raise ValueError("a report needs a title and a summary")
    if len(summary) > 60000:
        raise ValueError("summary too long (60k characters max)")
    r = conn.execute("""insert into audit_reports (title, summary, findings, followups)
                        values (%s, %s, %s::jsonb, %s::jsonb) returning id, created_at""",
                     (title.strip()[:200], summary, json.dumps(findings or []), json.dumps(followups or []))).fetchone()
    conn.commit()
    return dict(r)
