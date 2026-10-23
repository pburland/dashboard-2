-- Patrick, Oct 22 2026: the goal for both races is to finish strong, not a time.
update races set goal_time = null, stretch_time = null,
       notes = notes || ' 2026-10-22: goal is to finish strong (no time goal).'
 where name in ('IRONMAN 70.3 Puerto Rico', 'IRONMAN Lake Placid');
