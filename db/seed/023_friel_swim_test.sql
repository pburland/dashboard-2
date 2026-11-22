-- 2026-11-23: the swim test becomes Friel's 1000 time trial (Patrick's choice), so the
-- swim zones and workouts from his book apply directly. T-pace per 100 = time / 10.
update plan_events
   set title = 'Swim test: 1000 time trial (T-pace)', duration_min = 50,
       notes = '300-400 easy with a few drills and 4 x 50 building, 2-3 min rest, then 1000 as fast as you can hold '
               'evenly (start controlled for the first 300, then build). Press lap right before and right after it. '
               'Easy cool-down. T-pace per 100 = 1000 time / 10; it sets your swim zones.'
 where sport = 'swim' and kind = 'test' and event_date = '2026-12-18';
