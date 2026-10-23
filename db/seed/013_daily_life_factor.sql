-- Oct 23 2026: 3,300+ kcal on return-phase run days felt high to Patrick. The report's
-- 1.45 daily-life multiplier is unvalidated; the GWU lab's own estimate for him was
-- RMR x 1.3 (office job). Use 1.35; the weekly weight check corrects either way.
update goals set target = jsonb_set(target, '{nutrition_plan,neat_factor}', '1.35'::jsonb)
 where name = 'Daily targets' and target ? 'nutrition_plan';
