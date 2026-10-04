-- When the doctor expects clearance. Only used to draw a provisional
-- preview of the weeks after a hold; it never ends the hold.
alter table health_episodes add column expected_clear_on date;
-- Override for the return-phase length (default: days in hold, 7-21).
alter table health_episodes add column return_days integer check (return_days between 7 and 42);
