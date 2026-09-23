-- 2026-09-23 (later): the fever was most likely viral, not heat-related, and
-- Patrick has recovered. Heat strain is removed as a cause. Consequences:
--   * no heat-illness tightening of the heat thresholds (app/analysis/heat.py)
--   * Sep 13 counts as a valid 12.5 mi base run; its HR drift is explained by
--     ~85°F heat, not by a fitness ceiling, so the long-run ladder is raised
-- Unchanged: the 10-day return phase (it follows the illness, whatever its
-- cause) and the 10% long-run jump rule (it applies to any athlete).

update health_episodes
   set reason = 'Viral illness: low-grade fever from Sep 15, recovered. Not heat-related.',
       notes  = 'Physician clearance reported by Patrick on 2026-09-23. Fever-free 48h taken from '
                'that clearance visit. Resting HR not yet measured by the system (Oura not '
                'connected): verify once connected. Sep 13 long run (12.5 mi, 10:09 start, ~85°F) '
                'was a hot-weather run, not the cause of the fever.'
 where started_on = '2026-09-13';

update phases set note = 'Viral illness, fever from Sep 15. No training prescribed.'
 where name = 'Health hold';
update phases set note = 'Long runs 10 -> 13.5 -> 15 mi. MCM gate: 10+ mi easy at normal HR by Oct 11. '
                         '16 is possible on Oct 17 only as a flagged +19% jump, 8 days before the race.'
 where name = 'MCM Rebuild';

update planned_workouts
   set distance_mi = 10.0, duration_min = 112,
       structure = '{"pace":"10:45-11:15","hr_avg_max":145,"walk_if_hr_over":155,"start_by":"heat check","fuel":"gel at 45 and 90 min"}',
       notes = 'First long run after the return phase. Well within your 12.5 base. If HR climbs past 150 at the same pace, walk 2 min and finish at 8.'
 where plan_date = '2026-10-03' and sport = 'run';

update planned_workouts
   set duration_min = 45, title = 'Easy spin'
 where plan_date = '2026-10-04' and sport = 'bike';

update races
   set notes = 'Uncertain after a viral illness (Sep 15-22). Longest run before race day: 15 mi on Oct 17 '
               '(16 possible as a flagged jump). 4:35 needs 10:30/mi for 26.2 on that build: decide the goal '
               'after the Oct 10 13.5 mi run.'
 where name = 'Marine Corps Marathon';
