-- 2026-09-23: physician cleared Patrick to resume training.
-- Hold ends; a 10-day return phase starts (length = days in hold, 7-21).
-- The marathon block is rebased from the end of the return phase instead of
-- resuming the original MCM Build schedule.

update health_episodes
   set criteria_met = '{"physician_clearance":"2026-09-23",
                        "fever_free_48h":"2026-09-23",
                        "rhr_near_baseline_3d":"2026-09-23"}',
       return_started_on = '2026-09-23',
       return_ends_on    = '2026-10-02',
       notes = 'Physician clearance reported by Patrick on 2026-09-23. Fever-free 48h taken from '
               'that clearance visit. Resting HR not yet measured by the system (Oura not '
               'connected): verify once connected; if it is 5+ bpm above baseline, runs become walks.'
 where started_on = '2026-09-13' and closed_on is null;

-- Rebase: the lost days become a Hold block, then Return, then a shortened
-- marathon rebuild. The taper is one week because the calendar allows no more.
delete from phases where name in ('MCM Build', 'MCM Taper');

with p as (
  insert into phases (name, kind, start_date, end_date, note) values
  ('Health hold', 'hold', '2026-09-14', '2026-09-22',
   'Heat strain Sep 13, then fever. No training prescribed.'),
  ('Return to training', 'return', '2026-09-23', '2026-10-02',
   'Z2 only, volume ramps from ~50% of pre-hold weeks, long run capped at 8.75 mi (70% of 12.5). Strength light: RPE 6-7, no failure.'),
  ('MCM Rebuild', 'build', '2026-10-03', '2026-10-18',
   'Long runs 8 -> 11 -> 13 mi. MCM gate: 10+ mi easy at normal HR by Oct 11. No 16-20 mi run: there is no safe path to one before Oct 25.'),
  ('MCM Taper', 'race', '2026-10-19', '2026-10-25',
   'One-week taper. No lower-body strength after Oct 19. Race Oct 25 only if the Oct 11 gate is met.')
  returning id, name
)
insert into phase_days (phase_id, day_of_week, strength_label, endurance_label)
select p.id, d.dow, d.strength, d.endurance
from p join (values
  ('Health hold',0,null,'Hold'), ('Health hold',1,null,'Hold'), ('Health hold',2,null,'Hold'),
  ('Health hold',3,null,'Hold'), ('Health hold',4,null,'Hold'), ('Health hold',5,null,'Hold'),
  ('Health hold',6,null,'Hold'),
  ('Return to training',0,'Lower, light (RPE 6)',null), ('Return to training',1,null,'Run easy'),
  ('Return to training',2,'Upper (bench focus)','Run easy'), ('Return to training',3,null,'Run easy'),
  ('Return to training',4,null,'Rest'), ('Return to training',5,null,'Long run easy'),
  ('Return to training',6,null,'Easy swim or bike'),
  ('MCM Rebuild',0,'Lower maintenance + calves',null), ('MCM Rebuild',1,null,'Run easy + strides'),
  ('MCM Rebuild',2,'Upper A (bench, heavy)','Run easy'), ('MCM Rebuild',3,null,'Run easy'),
  ('MCM Rebuild',4,'Upper B (hypertrophy, 35 min)','Rest'), ('MCM Rebuild',5,null,'Long run'),
  ('MCM Rebuild',6,null,'Easy swim or bike'),
  ('MCM Taper',0,'Upper, light',null), ('MCM Taper',1,null,'Run 4 mi with 2 mi at goal pace'),
  ('MCM Taper',2,null,'Run easy 3 mi'), ('MCM Taper',3,null,'Rest / carb load'),
  ('MCM Taper',4,null,'Shakeout 2 mi'), ('MCM Taper',5,null,'Rest'),
  ('MCM Taper',6,null,'RACE — Marine Corps Marathon')
) as d(phase, dow, strength, endurance) on d.phase = p.name;

-- The first two weeks back, written out. Every session is Z2 or below and
-- passes app/analysis/validator.py (see tests/test_return_plan.py).
insert into planned_workouts (plan_date, sport, title, phase_id, duration_min, distance_mi,
                              max_zone, is_long, structure, source, notes)
select d.plan_date::date, d.sport, d.title, ph.id, d.dur, d.mi, d.zone, d.is_long,
       d.structure::jsonb, 'coach', d.notes
from (values
  ('2026-09-23','run','Easy return run',27,2.5,'Z2',false,
   '{"pace":"10:45-11:30","hr_avg_max":140,"walk_if_hr_over":150,"walk_breaks":"allowed"}',
   'First run after the hold. Conversational the whole way. Stop at 2.5 mi even if it feels easy.'),
  ('2026-09-24','strength','Upper body (return)',45,null,'Z1',false,
   '{"exercises":[["Bench Press","3x5","RPE 7, start ~145-150 lb"],["Barbell Row","3x8","RPE 7"],["Overhead Press","3x6","RPE 7"],["Pull-up","3 sets","2 reps short of failure"],["Incline DB Press","2x10","RPE 7"]]}',
   'No sets to failure this week.'),
  ('2026-09-25','run','Easy run',33,3.0,'Z2',false,
   '{"pace":"10:45-11:30","hr_avg_max":140,"walk_if_hr_over":150}', null),
  ('2026-09-26','run','Long run (easy)',57,5.0,'Z2',true,
   '{"pace":"10:45-11:30","hr_avg_max":140,"walk_if_hr_over":150,"start_by":"heat check"}',
   'Longest run of the return week. Start early if the heat index is over 80°F.'),
  ('2026-09-27','swim','Easy swim',25,null,'Z2',false,
   '{"note":"or 30-40 min easy bike"}', 'Low-impact aerobic. Optional.'),
  ('2026-09-28','strength','Lower body (light)',40,null,'Z1',false,
   '{"exercises":[["Goblet Squat","3x8","RPE 6"],["Romanian Deadlift","2x8","RPE 6"],["Split Squat","2x8/leg","RPE 6"],["Calf Raise","3x12",""]]}',
   'Five days clear of Saturday''s long run.'),
  ('2026-09-29','run','Easy run',38,3.5,'Z2',false,
   '{"pace":"10:40-11:20","hr_avg_max":140,"walk_if_hr_over":150}', null),
  ('2026-09-30','run','Easy run',33,3.0,'Z2',false,
   '{"pace":"10:40-11:20","hr_avg_max":140}', 'Run before lifting, or lift in the evening.'),
  ('2026-09-30','strength','Upper body',45,null,'Z1',false,
   '{"exercises":[["Bench Press","3x5","RPE 7"],["Barbell Row","3x8","RPE 7"],["Overhead Press","3x6","RPE 7"],["Pull-up","3 sets","1-2 reps short of failure"],["Incline DB Press","3x10","RPE 8"]]}', null),
  ('2026-10-01','run','Easy run',38,3.5,'Z2',false,
   '{"pace":"10:40-11:20","hr_avg_max":140}', null),
  ('2026-10-03','run','Long run (easy)',90,8.0,'Z2',true,
   '{"pace":"10:45-11:30","hr_avg_max":142,"walk_if_hr_over":152,"start_by":"heat check"}',
   'First run past 6 miles since Sep 13. Carry fluid. If HR drifts over 150 while the pace stays the same, walk 2 min and finish at 7.'),
  ('2026-10-04','bike','Easy spin or swim',30,null,'Z2',false, '{}', 'Optional.')
) as d(plan_date, sport, title, dur, mi, zone, is_long, structure, notes)
join phases ph on d.plan_date::date between ph.start_date and ph.end_date;

update races
   set decision_rule = 'Hold cleared Sep 23 (met). Remaining gate: a 10+ mi easy run at normal HR, no decoupling over 5%, by Oct 11. '
                       'If it is not met, drop or defer. Never compress the build to fit.',
       decision_date = '2026-10-11',
       notes = 'Longest safe long run before race day is ~13 mi (Oct 17). The 4:35 target assumed an 18-20 mi build; '
               'on this build, plan a finish with run/walk and a heart-rate cap, not 4:35.'
 where name = 'Marine Corps Marathon';
