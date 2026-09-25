-- Ingest support: idempotent flags, planned <-> actual matching, sync runs.

-- One flag per (kind, subject, day): re-running a sync never duplicates it.
create unique index flags_dedupe on flags (kind, flag_date, subject_type, subject_id) nulls not distinct;

-- Which completed activity satisfied a planned session.
alter table planned_workouts add column activity_id bigint references activities(id) on delete set null;

-- Every sync run, for the dashboard's "last synced" line and debugging.
create table sync_runs (
  id           bigint generated always as identity primary key,
  kind         text not null,            -- nightly | morning | backfill | manual
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  ok           boolean,
  summary      jsonb not null default '{}'::jsonb
);
alter table sync_runs enable row level security;
