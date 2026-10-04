-- 2026-10-04: doctor expects Patrick to be fine by Oct 15. The generator
-- previews the weeks after that as provisional; nothing is prescribed until
-- clearance is recorded. Mono gets the full 21-day return whatever the hold length.
update health_episodes set expected_clear_on = '2026-10-15', return_days = 21
 where started_on = '2026-10-03' and closed_on is null;

-- Marathon taper template the generator can read unambiguously: the race
-- itself comes from the races table, not from a label.
update phase_days set endurance_label = 'Run easy short'
 where day_of_week = 5 and phase_id = (select id from phases where name = 'Marathon taper');
update phase_days set endurance_label = 'Long run'
 where day_of_week = 6 and phase_id = (select id from phases where name = 'Marathon taper');
update phase_days set endurance_label = 'Rest'
 where day_of_week = 6 and phase_id = (select id from phases where name = '70.3 Race week');
