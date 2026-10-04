-- Feature 3: post-workout check-in (RPE, feel, pain).
create table check_ins (
  id                 bigint generated always as identity primary key,
  activity_id        bigint references activities(id) on delete set null,
  planned_workout_id bigint references planned_workouts(id) on delete set null,
  check_in_on        date not null,
  rpe                smallint check (rpe between 1 and 10),
  felt               text check (felt in ('good','fine','bad')),
  pain               boolean not null default false,
  pain_detail        text,
  note               text,
  created_at         timestamptz not null default now(),
  unique (planned_workout_id)
);
-- An extra (unplanned) activity gets at most one check-in too.
create unique index check_ins_one_per_extra on check_ins (activity_id) where planned_workout_id is null;
alter table check_ins enable row level security;

-- Feature 2/4/5: every plan change, from any source, with the reason.
create table plan_changes (
  id              bigint generated always as identity primary key,
  batch_id        uuid not null default gen_random_uuid(),   -- one user action / one regeneration
  action          text not null check (action in ('move','swap','remove','add','modify')),
  plan_date       date not null,
  before          jsonb not null default '{}'::jsonb,         -- the row as it was (with its id)
  after           jsonb not null default '{}'::jsonb,         -- the row as it is now (with its id)
  reason          text not null,
  validator_flags jsonb not null default '[]'::jsonb,
  accepted_warns  jsonb not null default '[]'::jsonb,
  source          text not null default 'chat' check (source in ('chat','generator','coach','system')),
  undone_at       timestamptz,
  created_at      timestamptz not null default now()
);
create index on plan_changes (batch_id);
create index on plan_changes (plan_date);
alter table plan_changes enable row level security;

-- Proposed changes waiting for Patrick's confirmation (chat and rebase).
create table plan_proposals (
  id              uuid primary key default gen_random_uuid(),
  source          text not null check (source in ('chat','system','generator')),
  conversation_id bigint references conversations(id) on delete set null,
  actions         jsonb not null,             -- resolved actions with before/after rows
  base            jsonb not null,             -- {row_id: fingerprint} the proposal was built on
  flags           jsonb not null default '[]'::jsonb,
  explanation     text not null default '',
  reason          text not null default '',
  status          text not null default 'pending'
                  check (status in ('pending','applied','cancelled','stale','refused')),
  plan_change_batch uuid,
  created_at      timestamptz not null default now(),
  decided_at      timestamptz
);
alter table plan_proposals enable row level security;

-- Feature 5: one row per generated week, for debugging.
create table plan_generations (
  id             bigint generated always as identity primary key,
  week_start     date not null,
  trigger        text not null check (trigger in ('weekly','rebase','chat','manual')),
  inputs_hash    text not null,
  validator_pass boolean not null,
  flags          jsonb not null default '[]'::jsonb,
  created_at     timestamptz not null default now()
);
create index on plan_generations (week_start, created_at desc);
alter table plan_generations enable row level security;

-- Weekly volume bounds per phase kind and sport (hours). Patrick-tunable.
create table phase_volume_targets (
  phase_kind  text not null,
  sport       text not null check (sport in ('run','bike','swim','strength')),
  min_hours   real not null,
  max_hours   real not null,
  primary key (phase_kind, sport),
  check (min_hours <= max_hours)
);
alter table phase_volume_targets enable row level security;

alter table planned_workouts add column is_key boolean not null default false;
alter table profile
  add column user_prefs    jsonb not null default '{}'::jsonb,
  add column daily_minutes jsonb not null default '{"default": 210}'::jsonb;
alter table conversations
  add column summary          text,
  add column summary_upto_id  bigint;
