-- Fitness test results (outside review, Card 2). The latest applied test of each
-- kind sets that sport's zones; an invalid test changes nothing.
create table fitness_tests (
  id                  bigint generated always as identity primary key,
  kind                text not null check (kind in ('run_lthr', 'bike_ftp', 'swim_css')),
  test_date           date not null,
  planned_workout_id  bigint references planned_workouts(id) on delete set null,
  activity_id         bigint references activities(id) on delete set null,
  source              text not null default 'auto' check (source in ('auto', 'manual')),
  result              jsonb not null default '{}'::jsonb,
  status              text not null check (status in ('applied', 'pending', 'invalid', 'rejected')),
  reason              text,
  created_at          timestamptz not null default now()
);
create unique index on fitness_tests (planned_workout_id) where planned_workout_id is not null;
create index on fitness_tests (kind, test_date);
