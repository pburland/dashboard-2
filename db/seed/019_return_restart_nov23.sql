-- 2026-11-22: the return to training restarts now (outside review, Card 1).
-- Cleared Nov 2, but Nov 7-21 was the Asia trip with almost no training, so the
-- 21-day return that began Nov 2 ran out on paper. It starts again on Nov 23,
-- the first day back, for 21 days; trip days from here on pause it.
update health_episodes
   set return_started_on = '2026-11-23',
       return_days = 21,
       return_ends_on = '2026-12-13',
       notes = coalesce(notes, '') || ' Return restarted Nov 23 (the Nov 2 return elapsed during the Asia trip).'
 where started_on = '2026-09-15' and closed_on is null;
