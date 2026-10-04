-- What each generation was built from, so a morning rebase can tell what changed.
alter table plan_generations add column inputs jsonb not null default '{}'::jsonb;
