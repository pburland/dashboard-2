-- Conservative weekly volume bounds (hours) by phase kind, for a 70.3 build.
-- Patrick-tunable: edit the rows; the generator reads them every run.
-- Daily cap: 3.5 h any day (Patrick, 2026-10-04); long sessions prefer weekends.
insert into phase_volume_targets (phase_kind, sport, min_hours, max_hours) values
  ('return',     'run', 0.5, 3.0), ('return',     'bike', 0, 1.5), ('return',     'swim', 0, 1.0), ('return',     'strength', 0, 1.5),
  ('base',       'run', 1.5, 4.5), ('base',       'bike', 1.0, 5.0), ('base',       'swim', 0.5, 2.0), ('base',       'strength', 0.5, 2.5),
  ('build',      'run', 2.0, 5.0), ('build',      'bike', 2.0, 6.5), ('build',      'swim', 1.0, 2.5), ('build',      'strength', 0.5, 1.5),
  ('peak',       'run', 2.0, 5.0), ('peak',       'bike', 2.5, 7.0), ('peak',       'swim', 1.0, 2.5), ('peak',       'strength', 0, 1.0),
  ('race',       'run', 0.5, 2.5), ('race',       'bike', 0.5, 3.0), ('race',       'swim', 0.3, 1.5), ('race',       'strength', 0, 0),
  ('transition', 'run', 0, 1.5),   ('transition', 'bike', 0, 2.0),   ('transition', 'swim', 0, 1.5),   ('transition', 'strength', 0, 1.0)
on conflict (phase_kind, sport) do nothing;
update profile set daily_minutes = '{"default": 210}' where id = 1;
