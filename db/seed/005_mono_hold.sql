-- 2026-10-04: Patrick has mono (infectious mononucleosis). All training is
-- suspended; his doctor expects him to be fine by about Oct 15.
--   * The Sep 13 illness episode is closed (its return phase ended Oct 2).
--   * A new hold opens. It exits only on recorded criteria, physician
--     clearance included: Oct 15 is an estimate, the system never ends a
--     hold by date. Mono enlarges the spleen, which can rupture under impact
--     or straining, so running AND lifting wait for the doctor.
--   * Marine Corps Marathon dropped. A January marathon (Jan 17-31, race TBD)
--     is added as a B race inside the Puerto Rico build.
--   * Asia trip Nov 6-23: run only, weather and time zone follow the itinerary.
--   * Phases from Oct 3 are rebased. Dates after the hold are provisional
--     until clearance is recorded; the return phase moves with it.

update health_episodes set closed_on = '2026-10-02'
 where started_on = '2026-09-13' and closed_on is null;

insert into health_episodes (kind, started_on, reason, notes) values
  ('illness', '2026-10-03',
   'Mono (infectious mononucleosis). All training suspended; doctor expects clearance around Oct 15.',
   'Reported 2026-10-04. Spleen risk: no running, lifting or straining until the physician clears it. '
   'Ask the doctor specifically: (1) is the spleen back to normal size, (2) is running OK, '
   '(3) is heavy lifting OK, or only light weights for a while. Mono fatigue can linger for weeks; '
   'the return phase uses the full 21 days.');

-- Plan rows from Oct 3 belonged to the MCM rebuild. Keep any that a real
-- activity was matched to (history stays honest); drop the rest.
update planned_workouts set phase_id = null where plan_date >= '2026-10-03';
delete from planned_workouts where plan_date >= '2026-10-03' and activity_id is null;

delete from phases where start_date >= '2026-10-03';

with p as (
  insert into phases (name, kind, start_date, end_date, note) values
  ('Health hold (mono)', 'hold', '2026-10-03', '2026-10-14',
   'Mono. No training prescribed. Ends only when the doctor clears you (expected ~Oct 15).'),
  ('Return to training (mono)', 'return', '2026-10-15', '2026-11-04',
   'Provisional: starts the day clearance is recorded. 21 days. Easy run/walk, Z2 only, volume 50% -> 90%. '
   'Light strength only (no heavy or straining lifts) until the doctor OKs heavy lifting.'),
  ('Base 1 (Asia trip, run only)', 'base', '2026-11-05', '2026-11-23',
   'Taipei, Tokyo, Hiroshima, Kyoto, Osaka. Easy aerobic running; bodyweight strength. '
   'Flight days are rest. Long run builds no more than 10% a week.'),
  ('Base 2', 'base', '2026-11-24', '2026-12-20',
   'Back home: swim and bike return alongside running. Marathon long runs build; bike fit before bike volume grows.'),
  ('Marathon build', 'build', '2026-12-21', '2027-01-10',
   'Peak long runs for the January marathon (18 mi at most). Swim and bike held at maintenance.'),
  ('Marathon taper', 'race', '2027-01-11', '2027-01-24',
   'Two-week taper. Race date is a placeholder (Jan 24) until the race is chosen. No lower-body strength race week.'),
  ('Marathon recovery', 'transition', '2027-01-25', '2027-01-31',
   'Easy swim and bike only. No running for 5 days.'),
  ('70.3 Build', 'build', '2027-02-01', '2027-02-21',
   'Bike-led: threshold work, bricks. Strength 1x/wk maintenance.'),
  ('70.3 Peak', 'peak', '2027-02-22', '2027-03-07',
   'Race-specific intensity, longest bricks. Strength injury-prevention only.'),
  ('70.3 Race week', 'race', '2027-03-08', '2027-03-14',
   'Sharpen, reduce volume, stay fresh. No strength. Race Mar 14.')
  returning id, name
)
insert into phase_days (phase_id, day_of_week, strength_label, endurance_label)
select p.id, d.dow, d.strength, d.endurance
from p join (values
  ('Health hold (mono)',0,null,'Hold'), ('Health hold (mono)',1,null,'Hold'), ('Health hold (mono)',2,null,'Hold'),
  ('Health hold (mono)',3,null,'Hold'), ('Health hold (mono)',4,null,'Hold'), ('Health hold (mono)',5,null,'Hold'),
  ('Health hold (mono)',6,null,'Hold'),
  ('Return to training (mono)',0,'Light full-body (RPE 6, no straining)',null),
  ('Return to training (mono)',1,null,'Run/walk easy'), ('Return to training (mono)',2,null,'Easy swim or bike'),
  ('Return to training (mono)',3,null,'Run/walk easy'), ('Return to training (mono)',4,'Light upper (RPE 6)','Rest'),
  ('Return to training (mono)',5,null,'Longest run/walk of the week'), ('Return to training (mono)',6,null,'Rest or walk'),
  ('Base 1 (Asia trip, run only)',0,'Bodyweight strength 20 min',null),
  ('Base 1 (Asia trip, run only)',1,null,'Run easy'), ('Base 1 (Asia trip, run only)',2,null,'Run easy + strides'),
  ('Base 1 (Asia trip, run only)',3,'Bodyweight strength 20 min','Rest'), ('Base 1 (Asia trip, run only)',4,null,'Run easy'),
  ('Base 1 (Asia trip, run only)',5,null,'Long run easy'), ('Base 1 (Asia trip, run only)',6,null,'Rest or walk'),
  ('Base 2',0,'Lower + calves',null), ('Base 2',1,null,'Run easy + strides; swim'),
  ('Base 2',2,'Upper (bench focus)','Bike Z2'), ('Base 2',3,null,'Run easy'),
  ('Base 2',4,null,'Swim technique'), ('Base 2',5,null,'Long run'), ('Base 2',6,null,'Long bike Z2'),
  ('Marathon build',0,'Lower maintenance',null), ('Marathon build',1,null,'Run tempo / MP intervals'),
  ('Marathon build',2,'Upper (bench focus)','Bike Z2'), ('Marathon build',3,null,'Run easy'),
  ('Marathon build',4,null,'Swim'), ('Marathon build',5,null,'Long run'), ('Marathon build',6,null,'Easy bike or rest'),
  ('Marathon taper',0,'Upper, light',null), ('Marathon taper',1,null,'Run with MP segments'),
  ('Marathon taper',2,null,'Swim or bike easy'), ('Marathon taper',3,null,'Run easy'),
  ('Marathon taper',4,null,'Rest'), ('Marathon taper',5,null,'Shakeout or long run (week 1)'),
  ('Marathon taper',6,null,'Long run (week 1) / RACE (week 2)'),
  ('Marathon recovery',0,null,'Rest'), ('Marathon recovery',1,null,'Easy swim'), ('Marathon recovery',2,null,'Easy bike'),
  ('Marathon recovery',3,null,'Easy swim'), ('Marathon recovery',4,null,'Rest'), ('Marathon recovery',5,null,'Easy bike'),
  ('Marathon recovery',6,null,'Easy run 3 mi'),
  ('70.3 Build',0,'Full-body maintenance','Swim CSS set'), ('70.3 Build',1,null,'Bike threshold'),
  ('70.3 Build',2,null,'Run easy + swim'), ('70.3 Build',3,null,'Bike Z2 + run off the bike'),
  ('70.3 Build',4,null,'Swim endurance'), ('70.3 Build',5,null,'Long bike + brick run'), ('70.3 Build',6,null,'Long run'),
  ('70.3 Peak',0,'Mobility + core','Swim race pace'), ('70.3 Peak',1,null,'Bike race-pace intervals'),
  ('70.3 Peak',2,null,'Run with race-pace miles'), ('70.3 Peak',3,null,'Swim + easy bike'),
  ('70.3 Peak',4,null,'Rest'), ('70.3 Peak',5,null,'Race-rehearsal brick'), ('70.3 Peak',6,null,'Long run (shortening)'),
  ('70.3 Race week',0,null,'Easy swim 20 min'), ('70.3 Race week',1,null,'Short bike with race-pace bursts'),
  ('70.3 Race week',2,null,'Short run with race-pace bursts'), ('70.3 Race week',3,null,'Rest / travel'),
  ('70.3 Race week',4,null,'Shakeout swim/bike'), ('70.3 Race week',5,null,'Rest, bike check-in'),
  ('70.3 Race week',6,null,'RACE — IM 70.3 Puerto Rico')
) as d(phase, dow, strength, endurance) on d.phase = p.name;

update races
   set status = 'dropped',
       notes = 'Dropped 2026-10-04: mono. Training resumes ~Oct 15, too late for an Oct 25 marathon.'
 where name = 'Marine Corps Marathon';

insert into races (name, race_date, distance, priority, status, decision_date, decision_rule, notes) values
  ('January marathon (race TBD)', '2027-01-24', 'marathon', 3, 'uncertain', '2026-12-01',
   'Pick a race between Jan 17 and 31 by Dec 1. Run it only if the long run reaches 16+ mi at easy HR by Jan 3.',
   'Date is a placeholder. B race inside the Puerto Rico build, 7 weeks before it: run it easy-to-steady, '
   'not all out. About 14 weeks from a mono return is enough to finish, not to race a time.');

update races
   set notes = notes || ' 2026-10-04: swim and bike resume late November after mono and the Asia trip, '
                        'so the bike-heavy work is compressed into Feb. 6:23 is still the goal; re-check it in January.'
 where name = 'IRONMAN 70.3 Puerto Rico';

update goals
   set status = 'retired',
       notes = notes || ' Retired 2026-10-04: mono rules out heavy lifting for weeks. Revisit with a new date.'
 where name = 'Bench press 225 lb';

insert into travel (start_date, end_date, place, lat, lng, tz_name, sports, note) values
  ('2026-11-06', '2026-11-06', 'Flight to Taipei',   38.8816, -77.0910, 'America/New_York', '{}', 'Travel day. Rest; walk the airport.'),
  ('2026-11-07', '2026-11-09', 'Taipei',             25.0330, 121.5654, 'Asia/Taipei',  '{run}', 'Arrive Nov 7. First run easy and short (jet lag).'),
  ('2026-11-10', '2026-11-14', 'Tokyo',              35.6762, 139.6503, 'Asia/Tokyo',   '{run}', 'Travel from Taipei Nov 10.'),
  ('2026-11-15', '2026-11-17', 'Hiroshima',          34.3853, 132.4553, 'Asia/Tokyo',   '{run}', ''),
  ('2026-11-18', '2026-11-21', 'Kyoto',              35.0116, 135.7681, 'Asia/Tokyo',   '{run}', ''),
  ('2026-11-22', '2026-11-22', 'Osaka',              34.6937, 135.5023, 'Asia/Tokyo',   '{run}', ''),
  ('2026-11-23', '2026-11-23', 'Flight Osaka to NYC', 34.6937, 135.5023, 'Asia/Tokyo',  '{}', 'Travel day. Rest.');
