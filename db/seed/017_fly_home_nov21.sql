-- From his calendar (Nov 8 2026): Sat Nov 21 is all-day travel, Osaka (KIX) -> Taipei (BR 131) ->
-- New York (BR 32), landing about 9 PM. No Osaka stay or Nov 23 flight. Week 2's long run moves
-- to Fri Nov 20; Thu Nov 19 gets the strides run.
delete from travel where place in ('Osaka', 'Flight Osaka to NYC');
update travel set end_date = '2026-11-20', note = 'Easy run + strides Thu, long run Fri (Saturday is all travel).'
 where place = 'Kyoto';
insert into travel (start_date, end_date, place, lat, lng, tz_name, sports, note) values
  ('2026-11-21', '2026-11-21', 'Flights Osaka -> Taipei -> New York', 34.6937, 135.5023, 'Asia/Tokyo', '{}',
   'All-day travel, lands in New York about 9 PM. Rest.');
insert into plan_events (event_date, sport, kind, title, duration_min, zone, notes) values
  ('2026-11-19', 'run', 'strides', 'Easy run 35 min + strides', 35, 'Z2',
   'Easy, average HR 125-145. Finish with 4 x 20 s relaxed strides, full recovery between.'),
  ('2026-11-20', 'run', 'long', 'Long run 60 min', 60, 'Z2',
   'Easy the whole way, average HR 125-145. Moved from Saturday: Saturday is all-day travel home.')
on conflict (event_date, sport) do nothing;
