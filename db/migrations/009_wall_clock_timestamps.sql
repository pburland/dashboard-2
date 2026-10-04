-- Confirmation order must follow real time, not transaction start time.
alter table plan_proposals alter column created_at set default clock_timestamp();
alter table messages alter column created_at set default clock_timestamp();
