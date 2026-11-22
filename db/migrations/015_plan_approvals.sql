-- Weekly plan approval (Patrick, Nov 22 2026): on Sunday he approves the coming
-- week; only then do its sessions go to Garmin and to the Training calendar, as
-- time blocks at the suggested best time (snapshotted here when he approves).
create table plan_approvals (
  week_start   date primary key,           -- a Monday
  approved_at  timestamptz not null default now(),
  sessions     jsonb not null default '{}'::jsonb   -- planned_workout_id -> {date, start, end, label, title}
);

alter table notifications drop constraint if exists notifications_kind_check;
alter table notifications add constraint notifications_kind_check
  check (kind in ('workout','update','checkin','report','plan','safety','clearance','test','approval'));
