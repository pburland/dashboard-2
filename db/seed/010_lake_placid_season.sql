-- Season plan of record, Oct 23 2026: one season peaking for IRONMAN Lake Placid
-- (A race, Jul 25 2027), with 70.3 Puerto Rico (Mar 14) as a B-race dress rehearsal.
-- Weekly template adapted from Felipe's: lift Tue Push / Wed Pull / Thu Legs, long
-- ride Saturday, long run Sunday; weekday training after 4:30 PM.
-- Sources: reports "Strength plan while cutting" and "Recomp and fueling plan" (Oct 2026).

-- ── races ────────────────────────────────────────────────────────────────
update races set priority = 1,
       notes = coalesce(notes, '') || ' 2026-10-23: A race. Goal: finish strong.'
 where name = 'IRONMAN Lake Placid';
update races set priority = 2,
       notes = notes || ' 2026-10-23: B race, a dress rehearsal for Lake Placid (mini-taper). Goal: finish strong.'
 where name = 'IRONMAN 70.3 Puerto Rico';
update races set status = 'dropped', notes = notes || ' 2026-10-23: dropped; the season is built for Lake Placid.'
 where name = 'January marathon (race TBD)';

-- ── goals ────────────────────────────────────────────────────────────────
update goals set due_date = '2028-06-30', status = 'active',
       notes = 'Strength report (Oct 2026): 225 before Lake Placid is unlikely (<1 in 5). Checkpoints for the smoothed '
               'bench e1RM: >=170 by Nov 24, >=185 by Dec 15, >=195 (stretch 200) by Mar 1, hold >=190 Apr-Jul. '
               'Go/no-go for a pre-race attempt Apr 1 2027 (trend >=215). After Lake Placid: bench block, 225 about mid-2028.'
 where name = 'Bench press 225 lb';
update goals set notes = 'Nutrition report (Oct 2026): 150 lb at 12% needs about -13 lb fat and +3 lb lean; 13-15% '
               'is the realistic landing, 12% the best case. Deficit only on non-key days, in blocks: maintenance '
               'until ~Nov 29, then Nov 30-Feb 14 and Mar 22-May 23. Never below 0.7% of bodyweight a week.'
 where name = 'Recomposition to visible abs';
update goals set target = target || '{"protein_g":160,"creatine_g":{"maintenance":4}}',
       notes = 'Protein 160 g every day (4 x 35-40 g plus ~40 g before bed). Creatine 3-5 g/day; no change in race week.'
 where name = 'Daily targets';

-- ── phases: rewrite from Base 3 on ───────────────────────────────────────
update planned_workouts set phase_id = null
 where phase_id in (select id from phases where start_date >= '2026-12-21');
delete from phases where start_date >= '2026-12-21';

insert into phases (name, kind, start_date, end_date, note) values
  ('Base 3', 'base', '2026-12-21', '2027-01-31',
   'Aerobic volume, main strength-building and cutting window. Long run to ~10-11 mi, long ride to 2.5 h.'),
  ('Build 1 (70.3)', 'build', '2027-02-01', '2027-02-28',
   'Bike threshold, run tempo, bricks. Brick weeks: legs move to Tuesday at a maintenance dose. Gut training at race carb rates.'),
  ('70.3 taper', 'peak', '2027-03-01', '2027-03-07',
   'Half lifting volume; last heavy legs Thu Mar 4. Race rehearsal brick Saturday.'),
  ('70.3 race week', 'race', '2027-03-08', '2027-03-14',
   'IRONMAN 70.3 Puerto Rico (B race). Upper-body primer Tuesday only.'),
  ('Recovery after the 70.3', 'transition', '2027-03-15', '2027-03-28',
   'Easy volume; lifting restarts light.'),
  ('Build 2 (Ironman)', 'build', '2027-03-29', '2027-05-30',
   'Long ride grows toward 5 h, bricks, race-pace work. Lifting 2x/wk: push + squat Tue, pull + hinge Thu.'),
  ('Peak (Ironman)', 'peak', '2027-05-31', '2027-07-11',
   'Highest load. One heavy full-body maintenance session a week, plus optional short upper/core. Calories at maintenance.'),
  ('Ironman taper', 'peak', '2027-07-12', '2027-07-18',
   'Volume down, intensity kept. Last heavy lifting Tue Jul 13.'),
  ('Ironman race week', 'race', '2027-07-19', '2027-07-25',
   'IRONMAN Lake Placid (A race). Carb-load the last 36-48 h.'),
  ('Transition', 'transition', '2027-07-26', '2027-08-22',
   'Recovery. Then a bench-specialization block.');

-- ── weekly templates (0 = Monday) ────────────────────────────────────────
-- Strength labels: "Push"/"Pull" are upper body and may share a key endurance day
-- (key session first); "Legs"/"squat"/"full-body" are heavy lower unless marked light.
create temporary table _tpl (phase text, dow int, strength text, endurance text) on commit drop;
insert into _tpl values
  ('Return to training (mono)', 0, null, 'Easy swim or bike'),
  ('Return to training (mono)', 1, 'Push (light, RPE 6-7)', 'Run/walk easy'),
  ('Return to training (mono)', 2, 'Pull (light, RPE 6-7)', 'Easy swim or bike'),
  ('Return to training (mono)', 3, 'Legs (light, RPE 6, no lunges)', 'Rest'),
  ('Return to training (mono)', 4, null, 'Run/walk easy'),
  ('Return to training (mono)', 5, null, 'Longest run/walk of the week'),
  ('Return to training (mono)', 6, null, 'Rest or walk'),

  ('Base 2', 0, null, 'Swim technique'),
  ('Base 2', 1, 'Push (bench heavy)', 'Run easy + strides'),
  ('Base 2', 2, 'Pull (row heavy + RDL 2 sets)', 'Bike Z2'),
  ('Base 2', 3, 'Legs (squat heavy)', 'Swim endurance'),
  ('Base 2', 4, null, 'Run easy'),
  ('Base 2', 5, null, 'Long bike Z2'),
  ('Base 2', 6, null, 'Long run'),

  ('Build 1 (70.3)', 0, null, 'Swim CSS set'),
  ('Build 1 (70.3)', 1, 'Push + squat (bench heavy; squat 2-3 heavy sets)', 'Run easy'),
  ('Build 1 (70.3)', 2, 'Pull (row heavy)', 'Bike threshold'),
  ('Build 1 (70.3)', 3, 'Upper accessories + core (moderate)', 'Run tempo'),
  ('Build 1 (70.3)', 4, null, 'Swim endurance'),
  ('Build 1 (70.3)', 5, null, 'Long bike + brick run'),
  ('Build 1 (70.3)', 6, null, 'Long run'),

  ('70.3 taper', 0, null, 'Swim race pace'),
  ('70.3 taper', 1, 'Push (light: half sets)', 'Bike race-pace intervals'),
  ('70.3 taper', 2, 'Pull (light: half sets)', 'Run with race-pace miles'),
  ('70.3 taper', 3, 'Legs (last heavy: 2 x 3 at ~80%)', 'Swim + easy bike'),
  ('70.3 taper', 4, null, 'Rest'),
  ('70.3 taper', 5, null, 'Race-rehearsal brick'),
  ('70.3 taper', 6, null, 'Long run (shortening)'),

  ('70.3 race week', 0, null, 'Easy swim 20 min'),
  ('70.3 race week', 1, 'Upper (light primer)', 'Short bike with race-pace bursts'),
  ('70.3 race week', 2, null, 'Short run with race-pace bursts'),
  ('70.3 race week', 3, null, 'Rest / travel'),
  ('70.3 race week', 4, null, 'Shakeout swim/bike'),
  ('70.3 race week', 5, null, 'Rest, bike check-in'),
  ('70.3 race week', 6, null, 'Rest'),

  ('Recovery after the 70.3', 0, null, 'Rest'),
  ('Recovery after the 70.3', 1, null, 'Swim easy'),
  ('Recovery after the 70.3', 2, 'Full-body (light restart)', 'Bike easy'),
  ('Recovery after the 70.3', 3, null, 'Run easy'),
  ('Recovery after the 70.3', 4, 'Push + pull (moderate)', 'Swim easy'),
  ('Recovery after the 70.3', 5, null, 'Bike Z2'),
  ('Recovery after the 70.3', 6, null, 'Run easy'),

  ('Build 2 (Ironman)', 0, null, 'Swim CSS set'),
  ('Build 2 (Ironman)', 1, 'Push + squat (heavy, 2-3 sets each)', 'Run easy'),
  ('Build 2 (Ironman)', 2, null, 'Bike threshold'),
  ('Build 2 (Ironman)', 3, 'Pull (row heavy) + hinge 2 sets', 'Run tempo'),
  ('Build 2 (Ironman)', 4, null, 'Swim endurance'),
  ('Build 2 (Ironman)', 5, null, 'Long bike + brick run'),
  ('Build 2 (Ironman)', 6, null, 'Long run'),

  ('Peak (Ironman)', 0, null, 'Swim CSS set'),
  ('Peak (Ironman)', 1, 'Full-body heavy (2 x 3-5 at 80-85%)', 'Run easy'),
  ('Peak (Ironman)', 2, null, 'Bike race-pace intervals'),
  ('Peak (Ironman)', 3, 'Upper + core (short)', 'Run with race-pace miles'),
  ('Peak (Ironman)', 4, null, 'Swim endurance'),
  ('Peak (Ironman)', 5, null, 'Long bike + brick run'),
  ('Peak (Ironman)', 6, null, 'Long run'),

  ('Ironman taper', 0, null, 'Swim race pace'),
  ('Ironman taper', 1, 'Full-body (last heavy: 2 x 3 at ~80%)', 'Run easy'),
  ('Ironman taper', 2, null, 'Bike race-pace intervals'),
  ('Ironman taper', 3, null, 'Run with race-pace miles'),
  ('Ironman taper', 4, null, 'Swim endurance'),
  ('Ironman taper', 5, null, 'Long bike Z2 (shortening)'),
  ('Ironman taper', 6, null, 'Long run (shortening)'),

  ('Ironman race week', 0, null, 'Easy swim 20 min'),
  ('Ironman race week', 1, 'Upper (light primer, optional)', 'Short bike with race-pace bursts'),
  ('Ironman race week', 2, null, 'Short run with race-pace bursts'),
  ('Ironman race week', 3, null, 'Rest / travel'),
  ('Ironman race week', 4, null, 'Shakeout swim/bike'),
  ('Ironman race week', 5, null, 'Rest, bike check-in'),
  ('Ironman race week', 6, null, 'Rest'),

  ('Transition', 0, null, 'Rest'),
  ('Transition', 1, null, 'Swim easy'),
  ('Transition', 2, null, 'Bike easy'),
  ('Transition', 3, 'Full-body (light)', 'Run easy'),
  ('Transition', 4, null, 'Rest'),
  ('Transition', 5, null, 'Bike Z2'),
  ('Transition', 6, null, 'Run easy');

-- Base 3 shares Base 2's template. Base 1 (the Asia trip) keeps its run-only template.
insert into _tpl select 'Base 3', dow, strength, endurance from _tpl where phase = 'Base 2';

delete from phase_days where phase_id in (select p.id from phases p where p.name in (select phase from _tpl));
insert into phase_days (phase_id, day_of_week, strength_label, endurance_label)
select p.id, t.dow, t.strength, t.endurance from _tpl t join phases p on p.name = t.phase;

-- ── volume bounds for an Ironman season (hours a week) ───────────────────
insert into phase_volume_targets (phase_kind, sport, min_hours, max_hours) values
  ('base',  'run', 1.5, 5.0), ('base',  'bike', 1.0, 6.0),  ('base',  'swim', 0.5, 2.5), ('base',  'strength', 0.5, 2.5),
  ('build', 'run', 2.0, 6.0), ('build', 'bike', 2.0, 9.0),  ('build', 'swim', 1.0, 3.0), ('build', 'strength', 0.5, 2.5),
  ('peak',  'run', 2.0, 6.5), ('peak',  'bike', 2.5, 10.0), ('peak',  'swim', 1.0, 3.0), ('peak',  'strength', 0, 1.5)
on conflict (phase_kind, sport) do update set min_hours = excluded.min_hours, max_hours = excluded.max_hours;

-- Weekdays stay at 3.5 h; long weekend days can run to 6.5 h (Ironman long rides).
update profile set daily_minutes = '{"default": 210, "weekend": 390}' where id = 1;
