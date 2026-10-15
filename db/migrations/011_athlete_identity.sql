-- Who the app is for, so prompts and the header aren't hardcoded.
alter table profile
  add column assistant_name text not null default 'Coach',
  add column athlete_blurb  text not null default '';
