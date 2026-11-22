-- 2026-11-22: fitness tests move after the return to training (Nov 23 - Dec 13, easy only).
-- All-out tests inside the return would be skipped by the planner, and shouldn't happen
-- a week into a post-mono comeback. Bike stays Wed Dec 16; swim Fri Dec 18; run Sat Dec 19
-- (daylight, flat route). Confirmed by Patrick.
update plan_events set event_date = '2026-12-19' where sport = 'run' and kind = 'test' and event_date = '2026-12-01';
update plan_events set event_date = '2026-12-18' where sport = 'swim' and kind = 'test' and event_date = '2026-12-07';
