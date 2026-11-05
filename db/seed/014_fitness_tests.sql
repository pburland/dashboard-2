-- Fitness tests to set zones from his own data (Nov 5 2026, after clearance).
-- The run test replaces the generic easy-run HR cap (145) with zones from his LTHR.
insert into plan_events (event_date, sport, kind, title, duration_min, zone, notes) values
  ('2026-12-01', 'run', 'test', 'Run test: 30-min heart-rate (LTHR)', 50, 'Z4',
   '15 min easy with 3 strides, then 30 min as hard as you can hold evenly (flat route, no stops), 5 min easy. '
   'Your average heart rate over the last 20 minutes is your lactate threshold heart rate (LTHR); the zones get set from it.'),
  ('2026-12-07', 'swim', 'test', 'Swim test: CSS (400 + 200)', 45, 'Z4',
   '400 yd easy, drills, then a 400 yd time trial, 5 min easy, a 200 yd time trial, easy cool-down. '
   'CSS pace per 100 yd = (400 time - 200 time) / 2. Sets your swim threshold pace.'),
  ('2026-12-16', 'bike', 'test', 'Bike test: 20-min FTP', 60, 'Z4',
   '20 min easy with 3 x 1 min hard, 5 min all-out effort to clear the legs, 10 min easy, then 20 min as hard as you can '
   'hold evenly, 10 min easy. FTP = 95% of the 20-min average power (or note average heart rate if no power).')
on conflict (event_date, sport) do nothing;
