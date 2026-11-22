-- 2026-11-22: goals and calorie timing confirmed by Patrick (outside review, Cards 7 and 9).
-- Strength: rebuild from ~150 lb bench after mono; 185 bench and 185 squat by Lake Placid;
-- 225 / 315 are for the Aug-Dec 2027 off-season, when triathlon volume drops.
update goals set name = 'Bench press 185 lb', due_date = '2027-07-25', status = 'active',
       target = '{"exercise":"Bench Press (Barbell)","one_rm_lb":185,"stretch_lb":195,
                  "checkpoints":[["2026-12-31",160],["2027-03-01",175],["2027-05-01",180],["2027-07-25",185]]}',
       notes = 'Confirmed Nov 22 2026. About 150 now (detrained after mono). Back to ~175 by March, then slower '
               'while Ironman volume rises. Stretch 195. 225 waits for the Aug-Dec 2027 off-season.'
 where name = 'Bench press 225 lb';

insert into goals (kind, name, target, due_date, status, notes)
select 'strength', 'Squat 185 lb',
       '{"exercise":"Squat (Barbell)","one_rm_lb":185,"stretch_lb":205,
         "checkpoints":[["2027-03-01",155],["2027-05-01",170],["2027-07-25",185]]}',
       '2027-07-25', 'active',
       'Confirmed Nov 22 2026. Baseline ~115-125 working sets in Oct. Legs take the most interference from '
       'running and riding, so progress is slower than bench. Stretch 205.'
 where not exists (select 1 from goals where name = 'Squat 185 lb');

insert into goals (kind, name, target, due_date, status, notes)
select 'strength', 'Bench 225 / squat 315 (off-season)',
       '{"bench_lb":225,"squat_lb":315,"starts":"2027-08-01"}', '2027-12-31', 'active',
       'After Lake Placid: a dedicated strength block while triathlon volume is low.'
 where not exists (select 1 from goals where name = 'Bench 225 / squat 315 (off-season)');

-- Calorie timing: small deficit on easy/rest days until 4 weeks before the 70.3 (Feb 14 for
-- Puerto Rico), maintenance for the 4 weeks before it, a recomp block after it, then maintenance
-- and full fueling for the last ~11 weeks before Lake Placid. Built for the earlier race date
-- (Puerto Rico, Mar 14) until the 70.3 is chosen; Texas (Apr 4) would move it 3 weeks later.
update goals set target = jsonb_set(target, '{nutrition_plan,deficit_blocks}', '[
    {"name":"base deficit 1","from":"2026-11-30","to":"2026-12-20","kcal":475},
    {"name":"base deficit 2","from":"2026-12-28","to":"2027-01-17","kcal":475},
    {"name":"base deficit 3","from":"2027-01-25","to":"2027-02-14","kcal":400},
    {"name":"post-70.3 recomp 1","from":"2027-03-22","to":"2027-04-11","kcal":275},
    {"name":"post-70.3 recomp 2","from":"2027-04-19","to":"2027-05-09","kcal":275}]'::jsonb)
 where name = 'Daily targets';

update goals set notes = 'Recomp, not bulk (confirmed Nov 22 2026). Small deficit only on rest, lift and easy weekdays: '
               'Nov 30-Feb 14 (after the return ends), none in the 4 weeks before the 70.3, again Mar 22-May 9, '
               'then maintenance and full fueling through Lake Placid. Never below 0.7% of bodyweight a week.'
 where name = 'Recomposition to visible abs';
