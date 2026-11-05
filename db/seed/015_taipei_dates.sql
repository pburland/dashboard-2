-- Patrick, Nov 5 2026: lands in Taipei Saturday Nov 7 around 8 PM and flies to Japan early Monday Nov 9.
-- Saturday is a travel day (no run); one full day in Taipei (Sun Nov 8); Tokyo from Monday.
update travel set start_date = '2026-11-08', end_date = '2026-11-08',
       note = 'One full day in Taipei: easy run, short (jet lag).'
 where place = 'Taipei';
insert into travel (start_date, end_date, place, lat, lng, tz_name, sports, note) values
  ('2026-11-07', '2026-11-07', 'Arrive Taipei (8 PM)', 25.0330, 121.5654, 'Asia/Taipei', '{}',
   'Travel day: lands about 8 PM. Rest; walk around if you want.');
update travel set start_date = '2026-11-09',
       note = 'Early flight from Taipei Monday: an easy evening run only if you feel good.'
 where place = 'Tokyo';
