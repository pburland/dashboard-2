-- 2026-10-04: corrections from Patrick.
--   * Mono is one hold from Sep 15 to (expected) Oct 15. The Sep 23
--     clearance and the Sep 23 - Oct 2 return phase are superseded: the
--     two episodes become one, and nothing counts as cleared yet.
--   * The January marathon is on hold; the build goes straight at
--     IRONMAN 70.3 Puerto Rico (Mar 14).
--   * DEXA (Sep 18) and resting metabolic rate (Sep 23) from GWU.

-- ── one mono episode, Sep 15 -> clearance ───────────────────────────────
delete from health_episodes where started_on = '2026-10-03';
update health_episodes
   set started_on = '2026-09-15',
       reason = 'Mono (infectious mononucleosis). All training suspended; doctor expects clearance around Oct 15.',
       criteria_met = '{}', return_started_on = null, return_ends_on = null, closed_on = null,
       expected_clear_on = '2026-10-15', return_days = 21,
       notes = 'Fever from Sep 15; later diagnosed as mono. A Sep 23 clearance and runs Sep 23 - Oct 2 '
               'came before the diagnosis and are superseded. Spleen risk: no running, lifting or straining '
               'until the physician clears it. Ask the doctor: (1) is the spleen back to normal size, '
               '(2) is running OK, (3) is heavy lifting OK or only light weights for a while.'
 where started_on = '2026-09-13';

-- Phases: MCM Base runs to Sep 14, one hold Sep 15 - Oct 14.
update planned_workouts set phase_id = null
 where phase_id in (select id from phases where start_date >= '2026-09-14');
update planned_workouts set status = 'superseded'
 where plan_date >= '2026-09-15' and activity_id is null and status = 'planned' and source <> 'generator';
delete from phases where start_date >= '2026-09-14' and start_date < '2026-10-15';
update phases set end_date = '2026-09-14' where name = 'MCM Base';
with p as (
  insert into phases (name, kind, start_date, end_date, note) values
  ('Health hold (mono)', 'hold', '2026-09-15', '2026-10-14',
   'Mono. No training prescribed. Ends only when the doctor clears you (expected ~Oct 15).')
  returning id
)
insert into phase_days (phase_id, day_of_week, strength_label, endurance_label)
select p.id, d, null, 'Hold' from p, generate_series(0, 6) as d;

-- ── marathon on hold; Base 3 replaces the marathon block ─────────────────
update races set status = 'deferred',
       notes = 'On hold (2026-10-04): focus on IRONMAN 70.3 Puerto Rico. Revisit after the Asia trip.'
 where name = 'January marathon (race TBD)';

update planned_workouts set phase_id = null
 where phase_id in (select id from phases where name in ('Marathon build', 'Marathon taper', 'Marathon recovery'));
delete from phases where name in ('Marathon build', 'Marathon taper', 'Marathon recovery');
update phases set start_date = '2027-01-18',
       note = 'Bike-led: threshold work, bricks, swim CSS sets. Long run to ~12-13 mi. Strength 1x/wk maintenance.'
 where name = '70.3 Build';
update phases set note = 'Back home: swim and bike return alongside running. Get the bike fit done before bike volume grows.'
 where name = 'Base 2';
with p as (
  insert into phases (name, kind, start_date, end_date, note) values
  ('Base 3', 'base', '2026-12-21', '2027-01-17',
   'Aerobic volume on the bike and in the pool; long run grows to ~10-11 mi. Strength 2x/wk.')
  returning id
)
insert into phase_days (phase_id, day_of_week, strength_label, endurance_label)
select p.id, d.dow, d.strength, d.endurance from p, (values
  (0, 'Lower + calves', 'Swim technique'), (1, null, 'Run easy + strides'),
  (2, 'Upper (bench focus)', 'Bike Z2'), (3, null, 'Swim endurance'),
  (4, null, 'Run easy'), (5, null, 'Long bike Z2'), (6, null, 'Long run')
) as d(dow, strength, endurance);

update races
   set notes = notes || ' 2026-10-04: marathon on hold; Base 3 (Dec 21 - Jan 17) replaces the marathon block, '
                        'so the bike and swim get six more weeks.'
 where name = 'IRONMAN 70.3 Puerto Rico';

-- ── DEXA + RMR ──────────────────────────────────────────────────────────
insert into body_metrics (day, weight_lb, bf_pct, lean_lb, fat_lb, bmd, source, detail) values
  ('2026-09-18', 160.0, 19.4, 123.9, 31.4, 1.191, 'dexa',
   '{"lab":"GWU Metabolism & Exercise Testing (Lunar iDXA)","scan_total_mass_lb":161.5,"bmc_lb":6.1,
     "bmd_t_score":-0.1,"bmd_z_score":-0.1,
     "region_pct_fat":{"arms":17.6,"legs":18.5,"trunk":20.7},
     "lean_lb":{"arm_right":7.8,"arm_left":7.7,"leg_right":22.1,"leg_left":20.7,"trunk":58.4},
     "note":"Scanned during the mono illness. Left leg carries 1.4 lb (6%) less lean mass than the right."}')
on conflict (day) do update set weight_lb = excluded.weight_lb, bf_pct = excluded.bf_pct,
  lean_lb = excluded.lean_lb, fat_lb = excluded.fat_lb, bmd = excluded.bmd,
  source = excluded.source, detail = excluded.detail;

update profile set rmr_kcal = 1958, rmr_measured_on = '2026-09-23',
       rmr_note = 'ReeVue indirect calorimetry, GWU. Predicted 1748 (+12%). Measured during mono, which can raise '
                  'resting burn: retest in January. Lab estimate of daily total without exercise: 2543.'
 where id = 1;

update goals set target = '{"bodyweight_lb":150,"bf_pct":12}',
       notes = 'DEXA Sep 18: 160 lb, 19.4% fat (31.4 lb fat, 124 lb lean). About 12% means losing ~12 lb of fat '
               'while keeping lean mass. Yields to goal #1: no calorie deficit during the hold, the return phase, '
               'peak or race weeks, or on long-session days.'
 where name = 'Recomposition to visible abs';
update goals set target = target || '{"kcal":"from RMR and the day''s training","protein_g":160}',
       notes = 'Calories follow the day: measured RMR x 1.3 plus the planned training, minus at most 300 on easy '
               'days in base phases. Protein ~1 g per lb of bodyweight.'
 where name = 'Daily targets';

-- Re-attach plan rows to whichever phase now covers their date.
update planned_workouts w set phase_id = p.id from phases p
 where w.phase_id is null and w.plan_date between p.start_date and p.end_date;
