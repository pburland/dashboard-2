-- Training system schema (Supabase / Postgres).
-- Base: Felipe's supabase_schema.sql (activities + laps, date-keyed recovery,
-- raw payloads, typed weekly notes, single-user with RLS on and no policies).
-- Added from Patrick's ARCHITECTURE.md where Felipe's shape couldn't support a
-- requirement: per-set strength, a real phase table, planned workouts, token
-- storage, chat history, weekly summaries. Added new: health episodes, flags,
-- goals, push subscriptions.
--
-- Dates: calendar fields are `date` (no time, no timezone). Instants are
-- `timestamptz`. The server clock (app/clock.py) decides what "today" is.

create extension if not exists btree_gist;

-- ── Identity & config ──────────────────────────────────────────────────
create table profile (
  id                   smallint primary key default 1 check (id = 1),
  name                 text not null,
  timezone             text not null,
  home_lat             double precision not null,
  home_lng             double precision not null,
  max_hr_observed      integer,          -- highest seen, not a test result
  lthr_run             integer,          -- from a Friel 30-min field test
  lthr_bike            integer,
  ftp_watts            integer,          -- power meter pending
  resting_hr_baseline  integer,
  zones_tested_on      date,
  updated_at           timestamptz not null default now()
);

-- OAuth / session tokens that providers rotate (Garmin, Oura). Env vars only
-- bootstrap; the newest token always lives here.
create table integrations (
  provider       text primary key check (provider in ('garmin','oura','hevy')),
  access_token   text,
  refresh_token  text,
  expires_at     timestamptz,
  extra          jsonb not null default '{}'::jsonb,
  last_sync_at   timestamptz,
  last_error     text,
  updated_at     timestamptz not null default now()
);

-- ── Goals ──────────────────────────────────────────────────────────────
create table races (
  id              bigint generated always as identity primary key,
  name            text not null,
  race_date       date not null,
  distance        text not null,
  priority        smallint not null,     -- 1 = most important
  goal_time       interval,              -- null = deliberately not set
  stretch_time    interval,
  target_splits   jsonb,
  baseline        jsonb,
  status          text not null default 'planned'
                  check (status in ('planned','uncertain','dropped','deferred','completed')),
  decision_date   date,
  decision_rule   text,
  result          jsonb,
  notes           text
);

create table goals (
  id          bigint generated always as identity primary key,
  kind        text not null,              -- strength | body_comp | nutrition
  name        text not null,
  target      jsonb not null,
  due_date    date,
  status      text not null default 'active'
              check (status in ('active','off_track','met','retired')),
  notes       text
);

-- ── Periodization ──────────────────────────────────────────────────────
create table phases (
  id          bigint generated always as identity primary key,
  name        text not null,
  kind        text not null check (kind in ('prep','base','build','peak','race','transition','return')),
  start_date  date not null,
  end_date    date not null,
  note        text not null default '',
  check (start_date <= end_date),
  -- No two phases may share a day.
  constraint phases_no_overlap exclude using gist (daterange(start_date, end_date, '[]') with &&)
);

-- No gaps: each phase must start the day after the previous one ends.
-- Deferred to commit so a rebase can rewrite several rows in one transaction.
create function phases_check_contiguous() returns trigger language plpgsql as $$
declare
  bad record;
begin
  select p.name as prev_name, p.end_date, n.name as next_name, n.start_date
    into bad
    from phases p
    join lateral (
      select name, start_date from phases q
       where q.start_date > p.start_date
       order by q.start_date limit 1
    ) n on true
   where n.start_date <> p.end_date + 1
   limit 1;
  if found then
    raise exception 'phase table not contiguous: % ends %, % starts %',
      bad.prev_name, bad.end_date, bad.next_name, bad.start_date;
  end if;
  return null;
end $$;

create constraint trigger phases_contiguous
  after insert or update or delete on phases
  deferrable initially deferred
  for each row execute function phases_check_contiguous();

create table phase_days (
  phase_id        bigint not null references phases(id) on delete cascade,
  day_of_week     smallint not null check (day_of_week between 0 and 6),  -- 0 = Monday
  strength_label  text,
  endurance_label text,
  primary key (phase_id, day_of_week)
);

-- What you're supposed to do. Rows are only written after the validator
-- (app/analysis/validator.py) has run; a health hold writes none.
create table planned_workouts (
  id               bigint generated always as identity primary key,
  plan_date        date not null,
  sport            text not null,
  title            text not null,
  phase_id         bigint references phases(id),
  planned_start    time,
  duration_min     real,
  distance_mi      real,
  max_zone         text,
  is_long          boolean not null default false,
  structure        jsonb not null default '{}'::jsonb,
  est_load         real,
  status           text not null default 'planned'
                   check (status in ('planned','done','skipped','moved','superseded')),
  source           text not null default 'generator',
  notes            text,
  created_at       timestamptz not null default now()
);
create index on planned_workouts (plan_date);

-- ── Actuals ────────────────────────────────────────────────────────────
create table activities (
  id                bigint generated always as identity primary key,
  provider          text not null check (provider in ('garmin','garmin_csv','manual')),
  external_id       text not null,
  start_local       timestamp not null,     -- wall-clock time where it happened
  start_utc         timestamptz,
  local_date        date not null,
  sport             text not null,
  title             text,
  distance_m        real,
  duration_s        real,
  moving_s          real,
  avg_hr            real,
  max_hr            integer,
  elevation_gain_m  real,
  calories          integer,
  aerobic_te        real,
  avg_power_w       real,
  norm_power_w      real,
  load_trimp        real,
  decoupling        real,
  weather           jsonb,
  raw               jsonb not null default '{}'::jsonb,
  ingested_at       timestamptz not null default now(),
  unique (provider, external_id)
);
create index on activities (local_date);
create index on activities (sport);

create table laps (
  activity_id  bigint not null references activities(id) on delete cascade,
  lap_index    integer not null,
  distance_m   real,
  duration_s   real,
  avg_hr       real,
  max_hr       integer,
  avg_power_w  real,
  primary key (activity_id, lap_index)
);

create table strength_sets (
  id              bigint generated always as identity primary key,
  provider        text not null default 'hevy',
  workout_id      text not null,
  workout_title   text,
  performed_on    date not null,
  exercise        text not null,
  set_index       integer not null,
  set_type        text,                   -- normal | warmup | dropset | failure
  weight_lb       real,
  reps            integer,
  rpe             real,
  excluded        boolean not null default false,
  exclude_reason  text,
  raw             jsonb not null default '{}'::jsonb,
  unique (provider, workout_id, exercise, set_index)
);
create index on strength_sets (performed_on);
create index on strength_sets (exercise);

create table recovery (
  day                date primary key,
  sleep_score        integer,
  readiness          integer,
  hrv_ms             real,
  resting_hr         integer,
  temp_deviation_c   real,
  total_sleep_s      integer,
  raw                jsonb not null default '{}'::jsonb,
  synced_at          timestamptz not null default now()
);

create table body_metrics (
  day        date primary key,
  weight_lb  real,
  bf_pct     real,
  source     text not null default 'manual'
);

-- Felipe's typed-notes pattern, unchanged in shape.
create table weekly_notes (
  id           bigint generated always as identity primary key,
  week_start   date not null,
  note_date    date,
  type         text not null check (type in
               ('injury','illness','untracked_activity','context',
                'nutrition','travel','mental','equipment')),
  sport        text,
  duration_min real,
  text         text not null,
  source       text not null default 'manual',   -- manual | chat
  recorded_at  timestamptz not null default now()
);
create index on weekly_notes (week_start);

-- ── Health gate ────────────────────────────────────────────────────────
create table health_episodes (
  id                 bigint generated always as identity primary key,
  kind               text not null check (kind in ('illness','injury')),
  started_on         date not null,
  reason             text not null,
  criteria_met       jsonb not null default '{}'::jsonb,   -- criterion -> date met
  return_started_on  date,
  return_ends_on     date,
  closed_on          date,
  rebased_at         timestamptz,
  created_at         timestamptz not null default now(),
  check (return_started_on is null or return_ends_on >= return_started_on)
);
-- At most one open episode at a time.
create unique index health_one_open on health_episodes ((true)) where closed_on is null;

create table flags (
  id            bigint generated always as identity primary key,
  flag_date     date not null,
  kind          text not null,
  severity      text not null check (severity in ('info','warn','stop')),
  message       text not null,
  subject_type  text,           -- planned_workout | activity | week
  subject_id    bigint,
  data          jsonb not null default '{}'::jsonb,
  pushed_at     timestamptz,
  created_at    timestamptz not null default now()
);
create index on flags (flag_date);

-- ── Derived & chat ─────────────────────────────────────────────────────
create table weekly_summaries (
  week_start    date primary key,
  summary       jsonb not null,
  narrative     text,
  model         text,
  generated_at  timestamptz not null default now()
);

create table conversations (
  id          bigint generated always as identity primary key,
  title       text,
  created_at  timestamptz not null default now()
);

create table messages (
  id                bigint generated always as identity primary key,
  conversation_id   bigint not null references conversations(id) on delete cascade,
  role              text not null check (role in ('user','assistant')),
  content           text not null,
  context_snapshot  jsonb,
  model             text,
  created_at        timestamptz not null default now()
);
create index on messages (conversation_id, created_at);

create table push_subscriptions (
  endpoint    text primary key,
  keys        jsonb not null,
  created_at  timestamptz not null default now()
);

-- ── Row level security ─────────────────────────────────────────────────
-- The server connects as the database owner and bypasses RLS. Enabling it
-- with no policies means Supabase's public API keys can read nothing.
do $$
declare t text;
begin
  foreach t in array array['profile','integrations','races','goals','phases','phase_days',
    'planned_workouts','activities','laps','strength_sets','recovery','body_metrics',
    'weekly_notes','health_episodes','flags','weekly_summaries','conversations',
    'messages','push_subscriptions']
  loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;
