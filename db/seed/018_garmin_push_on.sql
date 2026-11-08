-- Patrick, Nov 8 2026: send planned runs, rides and swims to the Garmin calendar every week,
-- starting when he's home (the Japan trip runs were put on Garmin by hand).
update profile set user_prefs = user_prefs || '{"garmin_push": {"enabled": true, "from": "2026-11-23"}}'::jsonb
 where id = 1;
