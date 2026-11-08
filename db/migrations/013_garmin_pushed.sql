-- Workouts the app put on the Garmin calendar, one per planned session, so a
-- re-plan can update or remove exactly its own workouts and nothing else.
create table garmin_pushed (
  planned_workout_id  bigint primary key,
  plan_date           date not null,
  sport               text not null,
  workout_id          bigint not null,
  fingerprint         text not null,
  pushed_at           timestamptz not null default clock_timestamp()
);
create index on garmin_pushed (plan_date);
alter table garmin_pushed enable row level security;
