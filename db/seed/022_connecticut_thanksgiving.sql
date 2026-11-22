-- 2026-11-22: Patrick is in Connecticut for Thanksgiving until Sat Nov 28, then drives
-- home to Arlington (full setup from Nov 29). Runs and lifting while away; the drive
-- day has no training. Coordinates are central Connecticut, for the weather only.
insert into travel (start_date, end_date, place, lat, lng, tz_name, sports, note) values
  ('2026-11-22', '2026-11-27', 'Connecticut', 41.76, -72.67, 'America/New_York', '{run,strength}',
   'Thanksgiving with family. No bike trainer or pool assumed; tell Coach if there is one.'),
  ('2026-11-28', '2026-11-28', 'Drive home', 41.76, -72.67, 'America/New_York', '{}',
   'Driving back to Arlington.');
