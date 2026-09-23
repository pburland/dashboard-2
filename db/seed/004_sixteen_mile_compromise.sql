-- 2026-09-23: Patrick asked for a 16 mi long run within ~2 weeks with a real
-- taper (outside advice from Felipe). Compromise, checked by the validator:
--   Sep 26  6 mi     inside the return phase (cap 8.75)          passes
--   Oct 3   13.5 mi  +8% over the 12.5 base                       WARN: 41% of week's load
--   Oct 10  16 mi    +18.5% over Oct 3 (stop line is +20%)         WARN
--   Oct 17  10 mi    step-down; taper runs Oct 11-25 (15 days)
-- Both big runs are conditional (see notes). If Oct 3 isn't 13.5, 16 on
-- Oct 10 becomes a +28% STOP and the fallback ladder (10 / 13.5 / 15) applies.

update planned_workouts set distance_mi = 3.5, duration_min = 38
 where plan_date = '2026-09-25' and sport = 'run';
update planned_workouts set distance_mi = 6.0, duration_min = 66,
       notes = 'Inside the return phase. Easy the whole way.'
 where plan_date = '2026-09-26' and sport = 'run';
update planned_workouts set duration_min = 40, notes = 'Easy aerobic; or 45 min easy bike.'
 where plan_date = '2026-09-27' and sport = 'swim';
update planned_workouts set distance_mi = 3.0, duration_min = 33
 where plan_date in ('2026-09-29', '2026-10-01') and sport = 'run';
update planned_workouts
   set distance_mi = 13.5, duration_min = 150, title = 'Long run (run/walk)',
       structure = '{"pace":"11:00-11:20","run_walk":"9 min run / 1 min walk","hr_avg_max":145,
                     "fuel":"gel at 40, 80, 120 min","go_if":["all return-phase runs at avg HR <=140 with no drift",
                     "resting HR normal 3 mornings","no fever or unusual fatigue"],"fallback_mi":10}',
       notes = 'Go only if every go_if condition holds; otherwise run 10 and keep the fallback ladder. '
               'If HR passes 150 at the same pace after mile 9, walk 2 min and finish at 11.'
 where plan_date = '2026-10-03' and sport = 'run';
update planned_workouts set duration_min = 60, notes = 'Recovery spin, Z1-Z2.'
 where plan_date = '2026-10-04' and sport = 'bike';

-- Rebuild ends after the 16; the taper gets two weeks.
update phases set end_date = '2026-10-11',
       note = 'Long runs 13.5 (Oct 3) -> 16 (Oct 10), both run/walk and conditional. '
              'MCM gate is met by the Oct 3 run if HR stays normal.'
 where name = 'MCM Rebuild';
update phases set start_date = '2026-10-12',
       note = 'Two-week taper after the Oct 10 16-miler: 10 mi step-down Oct 17, race week from Oct 19. '
              'No lower-body strength after Oct 19.'
 where name = 'MCM Taper';

update races
   set decision_rule = 'Hold cleared Sep 23 (met). Remaining gate: the Oct 3 long run (13.5, or the 10 mi fallback) '
                       'at normal HR with decoupling under 5%. If not met by Oct 11, drop or defer.',
       notes = 'Peak long run 16 mi on Oct 10 (flagged +18.5% jump), 15-day taper. Decide the race goal after Oct 10: '
               '4:35 needs 10:30/mi for 26.2; a run/walk finish is the realistic default.'
 where name = 'Marine Corps Marathon';
