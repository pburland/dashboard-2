# Build report: features 2, 3, 4, 5

## Deviations from the brief (read first)
1. **Brief 1 (medical restrictions) does not exist.** Patrick confirmed: ignore it and every medical date in
   the brief (incl. "no big workouts until Nov 10"). The existing **health hold** (mono, Sep 15 -> clearance,
   expected ~Oct 15, then a 21-day return) is the only medical rule. Feature 2's "medical input via chat" is
   therefore not built; chat can still *start* a health hold, never end one.
2. **"Ask Patrick" is Pat-GPT** (`app/chat.py`, `/api/chat`). Calendar sync is **free/busy only**
   (`app/integrations/calendar.py`): it cannot see travel. Travel comes from the `travel` table (the Asia
   trip) and from chat (`add_travel` tool). There is no `get_travel_days()`; `travel.place_for()` is used.
3. **Generator lives in `app/planning/generator.py`** (not `app/plan/`), with `sync.py` (diff/apply) and
   `changes.py` (the single write path). It existed before this brief; it was extended, not rewritten.
4. **`validate_proposal` is not a separate tool**: `propose_change` always validates and returns the result.
   Extra chat tools: `replan_week`, `add_travel`, `save_preference`.
5. **Undo endpoint is `POST /api/plan/undo/{batch_id}`** (cookie auth like the app), undoing a whole batch
   (e.g. both halves of a swap), not `/admin/rebase/undo/{plan_change_id}`.
6. **Generator previews**: the Sunday run writes the coming week plus two preview weeks (re-planned each Sunday).
7. **Daily cap is 3.5 h any day** (Patrick's answer), not 2 h. Long sessions prefer weekends.
8. **Hevy strength now completes planned strength sessions** (same-day sets), otherwise every planned
   lift would count as "missed" for Feature 4.
9. **`plan_changes.batch_id`, `undone_at` and a `plan_proposals` table** were added to support
   per-proposal confirmation, stale detection and batch undo.

## What was built
- **F3 check-in:** `check_ins` table, "How was it?" card on Today, `POST /api/checkin`,
  `pending_checkin` in `/api/today`; bad/pain -> 48h caution with the reason shown; `rpe_mismatch`,
  `recurring_pain` (+ injury note); 7-day RPE line on Trends.
- **F2 chat edits:** propose -> validate -> confirm -> apply (re-validated, stale check, per-warning
  acknowledgment, STOP never overridable), audit in `plan_changes`, proposal cards in chat and on Today,
  "moved by you" marker with reason and Undo on the Plan tab, thread summaries past ~20 messages,
  `profile.user_prefs`.
- **F5 generator:** ladder solver, `phase_volume_targets`, Friel strength placement, free-time and travel
  placement, 3-step relax loop + `needs_review`, idempotent diff writes, `plan_generations` log.
- **F4 auto-rebase:** `app/ingest/rebase.py` in the 05:30 job: easy misses -> skipped; key misses, trips,
  health/check-in/calendar changes -> week re-planned; clean applied with an info flag, warn -> proposal,
  stop -> left alone + flag; 7-day undo.

## Tests
96 passing (`pytest`; DB tests need `TEST_DATABASE_URL`). New: `test_checkins.py`, `test_plan_changes.py`,
`test_generator.py`, `test_rebase.py`, covering every test listed in the brief plus regressions below.

## Walkthrough actually run (local server, scratch database, real HTTP endpoints)
- **F3:** `/api/today` showed `pending_checkin` (Sat run) -> `POST /api/checkin {felt: bad, pain: shin, rpe: 9}`
  -> `{"effects": ["This caps intensity at Z2 and holds your long run through Monday.", "Flagged: an easy session felt hard."]}`
  -> `/api/today`: card gone, first reason "Yesterday's check-in: felt bad + shin pain. Easy only through Monday.",
  `rpe_mismatch` warn flag written.
- **F5:** generated 3 weeks; regenerating changed nothing (plan_changes 21 -> 21).
- **F2:** "move Saturday's long run to Sunday" -> **refused** (+83% over the 4-week longest once the window
  shifts a day) -> Friday proposed -> same-turn apply refused -> after "yes, do it" applied; audit row
  `move | 2026-10-09 | dinner Saturday | chat`; Plan tab shows "moved by you · Oct 4 / Why: dinner Saturday".
  Long run onto a flight day -> refused: "Sun Oct 18 you're a travel day with no training."
- **F4:** Friday long run missed -> morning rebase: "Re-planned (missed Long run/walk on Fri): Add Long
  run/walk on Sat Oct 10 (60 min). Safety rules kept." -> `POST /api/plan/undo/{batch}` -> `{"undone":1}`;
  second undo refused.

## Bugs the walkthrough found (fixed, with regression tests)
1. Chat could apply a proposal in the same turn (DB transaction clock); guard now requires a later user message.
2. Clearance before the hold block in the phase table ended -> only stray strength was planned.
3. Preview weeks were checked against actual runs only -> normal +1 mi steps were dropped as +50% jumps.
4. A mid-week re-plan dragged completed sessions forward and re-added done strength.
5. A missed key session avoided its template day instead of the day it was missed.
6. Mid-week long runs were sized from the remaining miles (shrank to 2.5 mi) and return weeks got a
   weekly-ramp warning the return ramp replaces.

## Seen while building, not built (scope)
- Recording doctor clearance is still a seed/SQL step; an in-app "I've been cleared" button (that records
  the criteria and starts the return) would remove that.
- Push notifications for proposals and the check-in (the brief's 30-min nudge) wait on push sending.
