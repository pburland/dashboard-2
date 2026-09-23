-- Patrick's starting state. Only his own goals and plan: no training history
-- is seeded here (that arrives through ingest), and nothing from Felipe.
-- scripts/migrate.py runs this file inside one transaction.

insert into profile (name, timezone, home_lat, home_lng, max_hr_observed)
values ('Patrick', 'America/New_York', 38.8816, -77.0910, 190);
-- 190 = highest HR in Garmin data (2026-09-01 run). Observed, not tested; not used for zones.

insert into races (name, race_date, distance, priority, goal_time, stretch_time,
                   target_splits, baseline, status, decision_date, decision_rule, notes)
values
  ('IRONMAN 70.3 Puerto Rico', '2027-03-14', '70.3', 1,
   '6:23:00', '6:00:00',
   '{"swim":"0:40:00","t1":"0:03:00","bike":"3:20:00","t2":"0:03:00","run":"2:17:00",
     "run_pace_per_mi":"10:27",
     "stretch_run":"1:54:00","stretch_run_pace_per_mi":"8:42"}',
   '{"race":"Eagleman 70.3","total":"7:19:30","swim":"0:42:41","t1":"0:07:54",
     "bike":"3:40:29","t2":"0:08:42","run":"2:39:46","run_pace_per_mi":"12:10"}',
   'planned', null, null,
   'Primary goal. Run split depends on a bike fit fixing the pain that wrecked the Eagleman run. '
   'Gate: an open half-marathon or threshold test in January decides whether 6:00 is in play.'),
  ('IRONMAN Lake Placid', '2027-07-25', '140.6', 2,
   null, null, null, null, 'planned', null, null,
   'Finish time deliberately unset until Puerto Rico calibrates it. Do not invent a target.'),
  ('Marine Corps Marathon', '2026-10-25', 'marathon', 3,
   '4:35:00', null, '{"pace_per_mi":"10:30"}', null,
   'uncertain', '2026-10-04',
   'Go only if cleared from the health hold by Oct 4 and a 10-mile easy run at normal HR is completed by Oct 11. '
   'Otherwise drop or defer; never compress the build to fit.',
   'Uncertain after the Sep 13 heat strain and fever.');

insert into goals (kind, name, target, due_date, status, notes) values
  ('strength', 'Bench press 225 lb', '{"exercise":"Bench Press","one_rm_lb":225,"planning_one_rm_lb":195}',
   '2026-12-31', 'off_track',
   'Jul 27–Sep 3: estimated 1RM flat at ~181 lb, slope -0.6 lb/wk. 225 needs ~+3 lb/wk with training paused. Plan against ~195.'),
  ('body_comp', 'Recomposition to visible abs', '{"bodyweight_lb":160}', null, 'active',
   'Yields to goal #1. No calorie deficit while in a health hold; calories scale with planned volume.'),
  ('nutrition', 'Daily targets', '{"kcal":2550,"protein_g":180,"creatine_g":{"loading":20,"maintenance":8}}', null, 'active',
   'Maintenance creatine above the usual 3-5 g/day; harmless but more than needed.');

-- Pre-illness plan from the prototype. Contiguous; the health hold will rebase
-- everything from the return date. Fix vs. the prototype: Taper now includes
-- race day (it ended Mar 13 while its week template put the race on Mar 14).
with p as (
  insert into phases (name, kind, start_date, end_date, note) values
  ('Prep / Base 1', 'base', '2026-07-26', '2026-08-16',
   'Strength leads (max strength, bench 225 push). Tri stays easy aerobic only.'),
  ('MCM Base', 'base', '2026-08-17', '2026-09-13',
   'Marathon weeks 1-4. Strength 2x/wk placed to protect the long run: lower Monday, upper Wednesday, nothing heavy Thu-Fri.'),
  ('MCM Build', 'build', '2026-09-14', '2026-10-11',
   'Marathon weeks 5-8. Strength 2x/wk, same placement. Do not run this block in a deficit.'),
  ('MCM Taper', 'race', '2026-10-12', '2026-10-25',
   'Volume down ~40%, intensity in short doses. No strength race week. Race Oct 25.'),
  ('Reverse Taper / Base 2', 'transition', '2026-10-26', '2026-11-15',
   'Post-marathon recovery; no running Oct 26 - Nov 2. Resume Base for Puerto Rico Nov 3.'),
  ('Build 1-2', 'build', '2026-11-16', '2027-01-10',
   'Strength 1x/wk full-body maintenance. Threshold work, early bricks.'),
  ('Peak', 'peak', '2027-01-11', '2027-02-21',
   'Strength injury-prevention only. Highest race-specific intensity.'),
  ('Taper', 'race', '2027-02-22', '2027-03-14',
   'Sharpen, reduce volume, stay fresh. No strength. Race Mar 14.')
  returning id, name
)
insert into phase_days (phase_id, day_of_week, strength_label, endurance_label)
select p.id, d.dow, d.strength, d.endurance
from p join (values
  ('Prep / Base 1',0,'Upper',null), ('Prep / Base 1',1,'Lower','Easy swim 30min (Z1-2)'),
  ('Prep / Base 1',2,'Push',null), ('Prep / Base 1',3,'Pull','Easy bike 30-45min (Z2)'),
  ('Prep / Base 1',4,'Legs',null), ('Prep / Base 1',5,null,'Easy run 30-45min (Z2)'),
  ('Prep / Base 1',6,null,'Rest'),
  ('MCM Base',0,'Lower maintenance + calves',null), ('MCM Base',1,null,'RUN key session — tempo 8:45-9:05'),
  ('MCM Base',2,'Upper (bench focus)','RUN easy 4-5mi @10:15-11:00'), ('MCM Base',3,null,'RUN easy 4mi'),
  ('MCM Base',4,null,'Rest'), ('MCM Base',5,null,'RUN long 8-12mi @10:30-11:15'), ('MCM Base',6,null,'Rest'),
  ('MCM Build',0,'Lower maintenance + calves',null), ('MCM Build',1,null,'RUN key session — tempo/MP intervals'),
  ('MCM Build',2,'Upper (bench focus)','RUN easy 5-6mi'), ('MCM Build',3,null,'RUN easy 5mi'),
  ('MCM Build',4,null,'Rest'), ('MCM Build',5,null,'RUN long 11-18mi, MP finish'), ('MCM Build',6,null,'Rest'),
  ('MCM Taper',0,'Upper, light (wk9 only)','RUN easy 4-5mi'), ('MCM Taper',1,null,'RUN short @ marathon pace'),
  ('MCM Taper',2,null,'RUN easy 2-5mi'), ('MCM Taper',3,null,'Rest / begin carb load'),
  ('MCM Taper',4,null,'Rest / packet pickup'), ('MCM Taper',5,null,'Rest, sodium load, lay out kit'),
  ('MCM Taper',6,null,'RACE — Marine Corps Marathon'),
  ('Reverse Taper / Base 2',0,'Upper (resume)','Easy swim 30min'), ('Reverse Taper / Base 2',1,null,'Easy bike 45min Z2'),
  ('Reverse Taper / Base 2',2,'Lower (resume progression Nov 3)','Easy run 30min Z2'),
  ('Reverse Taper / Base 2',3,null,'Swim 40min'), ('Reverse Taper / Base 2',4,null,'Rest'),
  ('Reverse Taper / Base 2',5,null,'Long bike 90min'), ('Reverse Taper / Base 2',6,null,'Easy run 45-60min'),
  ('Build 1-2',0,'Full-body (maintenance)','Swim 40min'), ('Build 1-2',1,null,'Bike threshold intervals 60min'),
  ('Build 1-2',2,null,'Run threshold intervals 45min'), ('Build 1-2',3,null,'Easy recovery swim/bike 30min'),
  ('Build 1-2',4,null,'Rest'), ('Build 1-2',5,null,'Long bike 2hr + brick run 20min'), ('Build 1-2',6,null,'Long run 75min'),
  ('Peak',0,null,'Swim technique 30min'), ('Peak',1,null,'Bike race-pace intervals 60min'),
  ('Peak',2,null,'Run race-pace intervals 45min'), ('Peak',3,null,'Easy recovery swim 30min'),
  ('Peak',4,null,'Rest'), ('Peak',5,null,'Race-pace brick 90min'), ('Peak',6,null,'Endurance run 60min'),
  ('Taper',0,null,'Easy swim 20min'), ('Taper',1,null,'Short bike w/ race-pace bursts 30min'),
  ('Taper',2,null,'Short run w/ race-pace bursts 20min'), ('Taper',3,null,'Rest'),
  ('Taper',4,null,'Easy shakeout swim/bike 20min'), ('Taper',5,null,'Rest / travel'),
  ('Taper',6,null,'RACE — IM 70.3 Puerto Rico')
) as d(phase, dow, strength, endurance) on d.phase = p.name;

-- Health hold, open since the Sep 13 long run. Exits only through the
-- recorded criteria in app/health/state.py.
insert into health_episodes (kind, started_on, reason) values
  ('illness', '2026-09-13',
   'Heat strain on 12.5 mi long run (10:09 start, ~85°F), low-grade fever from Sep 15; suspected tick-borne illness under medical evaluation.');

