-- Patrick, Nov 8 2026: no running Sun Nov 8 (Taipei), Mon Nov 9 (early flight) or Tue Nov 10
-- (first day in Tokyo), or on the Hiroshima -> Kyoto move (Wed Nov 18). Runs: Wed/Fri/Sat, then Tue/Fri/Sat.
update travel set sports = '{}', note = 'Rest day: just arrived. Walk around.' where place = 'Taipei';
update travel set start_date = '2026-11-11', note = 'Runs Wed, Fri and Sat (long).' where place = 'Tokyo';
insert into travel (start_date, end_date, place, lat, lng, tz_name, sports, note) values
  ('2026-11-09', '2026-11-10', 'Tokyo (travel and arrival)', 35.6762, 139.6503, 'Asia/Tokyo', '{}',
   'Early flight from Taipei Monday, settle in Tuesday. No running.');
update travel set start_date = '2026-11-19', note = 'Runs Fri and Sat (long).' where place = 'Kyoto';
insert into travel (start_date, end_date, place, lat, lng, tz_name, sports, note) values
  ('2026-11-18', '2026-11-18', 'Hiroshima to Kyoto', 35.0116, 135.7681, 'Asia/Tokyo', '{}', 'Travel day. No running.');
