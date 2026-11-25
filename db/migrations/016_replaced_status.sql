-- A session swapped out by a substitution (chat: "do a run and Pull instead of the ride")
-- becomes 'replaced' and points at its replacements, instead of 'skipped': it was not
-- missed, so it stays out of the compliance count. Skips from the "Didn't do it" button
-- are logged with their own source.
alter table planned_workouts drop constraint if exists planned_workouts_status_check;
alter table planned_workouts add constraint planned_workouts_status_check
  check (status in ('planned','done','skipped','moved','superseded','replaced'));
alter table plan_changes drop constraint if exists plan_changes_source_check;
alter table plan_changes add constraint plan_changes_source_check
  check (source in ('chat','generator','coach','system','checkin'));
