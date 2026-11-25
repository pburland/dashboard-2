-- 2026-11-25: Patrick's bug report. The Nov 25 ride (workout 140) was swapped for an easy
-- run/walk (173) and Pull (174) by Coach chat (batch 780ecf2d), but stayed 'skipped' and
-- kept showing on Today. Relink it as 'replaced' the way new substitutions now work.
-- Only if the rows still look exactly as reported.
update planned_workouts w
   set status = 'replaced',
       structure = coalesce(w.structure, '{}'::jsonb) || jsonb_build_object(
         'replaced_by', jsonb_build_array(173, 174),
         'changed_by', jsonb_build_object('by', 'you (Coach chat)', 'on', '2026-11-25',
           'reason', 'swapped for an easy run/walk and Pull (no bike in Connecticut)',
           'batch', '780ecf2d-f8f1-4a12-bce8-452ab2c030a6'))
 where w.id = 140 and w.status = 'skipped' and w.sport = 'bike'
   and (select count(*) from planned_workouts n
         where n.id in (173, 174) and n.status = 'planned' and n.plan_date = w.plan_date) = 2;

update planned_workouts n
   set structure = coalesce(n.structure, '{}'::jsonb) || '{"replaces": 140}'::jsonb
 where n.id in (173, 174)
   and exists (select 1 from planned_workouts w where w.id = 140 and w.status = 'replaced');
