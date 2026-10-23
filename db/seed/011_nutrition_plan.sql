-- Nutrition plan of record (report "Recomp and fueling plan", Oct 2026), read by
-- app/nutrition.py. Deficit only on rest, lift and easy weekdays inside a block;
-- maintenance on key and long days, weekends, recovery weeks, taper and race weeks.
update goals set target = target || '{"nutrition_plan":{"rmr_working_kcal":1850,"protein_g":160,
  "note":"Working RMR is the midpoint of the mono-time measurement (1958) and the predicted 1748; replace after a healthy re-test.",
  "deficit_blocks":[
    {"name":"base deficit 1","from":"2026-11-30","to":"2026-12-20","kcal":475},
    {"name":"base deficit 2","from":"2026-12-28","to":"2027-01-17","kcal":475},
    {"name":"base deficit 3","from":"2027-01-25","to":"2027-02-14","kcal":400},
    {"name":"70.3 run-in","from":"2027-02-15","to":"2027-02-28","kcal":250},
    {"name":"build deficit 1","from":"2027-03-22","to":"2027-04-11","kcal":275},
    {"name":"build deficit 2","from":"2027-04-19","to":"2027-05-09","kcal":275},
    {"name":"build deficit 3","from":"2027-05-17","to":"2027-05-23","kcal":275}]}}'::jsonb
 where name = 'Daily targets';
