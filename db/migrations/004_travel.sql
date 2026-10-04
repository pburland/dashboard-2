-- Where the athlete is on a given day. Weather, the best-time suggestion and
-- "today" follow the itinerary; days not covered use HOME_LAT/HOME_LNG/TZ_NAME.
create table travel (
  id          bigint generated always as identity primary key,
  start_date  date not null,
  end_date    date not null,
  place       text not null,
  lat         double precision not null,
  lng         double precision not null,
  tz_name     text not null,
  sports      text[] not null default '{run}',   -- what can be trained there; '{}' = none (flight day)
  note        text not null default '',
  check (start_date <= end_date),
  constraint travel_no_overlap exclude using gist (daterange(start_date, end_date, '[]') with &&)
);
alter table travel enable row level security;
