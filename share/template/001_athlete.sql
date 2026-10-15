-- The athlete's starting state. Applied once, on the first deploy.
-- EDIT EVERY LINE MARKED "EDIT" (your Claude will do this with you).
-- Dates are YYYY-MM-DD. The phase table must cover every day with no gaps
-- or overlaps (the database refuses it otherwise).

-- EDIT: name, IANA time zone, home coordinates (for weather), highest HR you've seen.
insert into profile (name, timezone, home_lat, home_lng, max_hr_observed, assistant_name, athlete_blurb)
values ('Felipe', 'America/New_York', 40.7128, -74.0060, 190, 'Coach',
        'an amateur triathlete who also lifts.');

-- EDIT: races. priority 1 = the A race. distance: '70.3', '140.6', 'marathon', 'half', ...
-- goal_time / stretch_time like '5:30:00' or null. status: planned | uncertain | deferred | dropped.
insert into races (name, race_date, distance, priority, goal_time, stretch_time, status, notes) values
  ('A race (EDIT)', '2027-06-06', '70.3', 1, '5:30:00', null, 'planned', ''),
  ('B race (EDIT)', '2027-09-12', '140.6', 2, null, null, 'planned', '');

-- EDIT: goals. kind: strength | body_comp | nutrition. status: active | off_track | met | retired.
insert into goals (kind, name, target, due_date, status, notes) values
  ('strength', 'Bench press 225 lb', '{"exercise":"Bench Press","one_rm_lb":225}', '2027-03-31', 'active', ''),
  ('nutrition', 'Daily targets', '{"protein_g":160}', null, 'active', 'Calories follow the day''s training.');

-- EDIT: the season, as contiguous Friel phases ending on the A race.
-- kind: prep | base | build | peak | race | transition | return | hold
-- phase_days: one row per weekday (0 = Monday). endurance_label is read by the planner
-- (words it understands: run, long run, tempo, strides, swim, CSS, bike, long bike,
-- threshold, brick, rest). strength_label: 'Lower ...', 'Upper ...', 'Full-body', 'light',
-- 'bodyweight' (heavy lower-body is kept 2+ days away from long sessions automatically).
with p as (
  insert into phases (name, kind, start_date, end_date, note) values
  ('Base 1',   'base',  '2026-11-02', '2026-12-27', 'Aerobic volume; strength 3x/week.'),
  ('Base 2',   'base',  '2026-12-28', '2027-02-21', 'Long run and long ride grow; bike fit before volume.'),
  ('Build',    'build', '2027-02-22', '2027-04-25', 'Threshold work, bricks; strength 2x/week.'),
  ('Peak',     'peak',  '2027-04-26', '2027-05-30', 'Race-specific intensity; strength 1x/week.'),
  ('Race week','race',  '2027-05-31', '2027-06-06', 'Sharpen and rest. Race Sunday.')
  returning id, name, kind
)
insert into phase_days (phase_id, day_of_week, strength_label, endurance_label)
select p.id, d.dow, d.strength, d.endurance from p join (values
  ('base', 0, 'Lower + calves', 'Swim technique'), ('base', 1, null, 'Run easy + strides'),
  ('base', 2, 'Upper (bench focus)', 'Bike Z2'), ('base', 3, null, 'Swim endurance'),
  ('base', 4, null, 'Run easy'), ('base', 5, null, 'Long bike Z2'), ('base', 6, null, 'Long run'),
  ('build', 0, 'Full-body maintenance', 'Swim CSS set'), ('build', 1, null, 'Bike threshold'),
  ('build', 2, null, 'Run easy + swim'), ('build', 3, null, 'Bike Z2 + run off the bike'),
  ('build', 4, null, 'Swim endurance'), ('build', 5, null, 'Long bike + brick run'), ('build', 6, null, 'Long run'),
  ('peak', 0, 'Mobility + core', 'Swim race pace'), ('peak', 1, null, 'Bike race-pace intervals'),
  ('peak', 2, null, 'Run with race-pace miles'), ('peak', 3, null, 'Swim + easy bike'),
  ('peak', 4, null, 'Rest'), ('peak', 5, null, 'Race-rehearsal brick'), ('peak', 6, null, 'Long run'),
  ('race', 0, null, 'Easy swim 20 min'), ('race', 1, null, 'Short bike with race-pace bursts'),
  ('race', 2, null, 'Short run with race-pace bursts'), ('race', 3, null, 'Rest / travel'),
  ('race', 4, null, 'Shakeout swim/bike'), ('race', 5, null, 'Rest'), ('race', 6, null, 'Rest')
) as d(kind, dow, strength, endurance) on d.kind = p.kind;
