-- One-off sessions on a fixed date (fitness tests, a race rehearsal): they replace
-- that day's template session of the same sport. Plan of record, edited by seed.
create table plan_events (
  id            bigint generated always as identity primary key,
  event_date    date not null,
  sport         text not null check (sport in ('run', 'bike', 'swim')),
  kind          text not null default 'test',
  title         text not null,
  duration_min  real not null,
  zone          text not null default 'Z4',
  notes         text not null default '',
  unique (event_date, sport)
);
