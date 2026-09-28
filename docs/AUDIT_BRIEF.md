# Audit brief: Patrick's training system

You are reviewing a personal training system for one athlete (Patrick,
Arlington VA) who trains strength and triathlon concurrently. Please audit it
critically. Say what is wrong, risky or unjustified; don't summarize what works.

## What it is

A Python (FastAPI) service on Railway with a Supabase Postgres database and
a phone web app (PWA). It:

1. **Ingests** Garmin activities with per-mile laps (unofficial
   `garminconnect` library, token-based, no password on the server), Hevy
   strength sets (REST API) and Oura recovery (OAuth2): a 12-month backfill,
   then nightly at 03:00 and a morning check at 05:30 ET, via an in-process
   scheduler.
2. **Plans** with Friel-style periods (base, build, peak, race) in a phase
   table whose contiguity the database enforces.
3. **Gates** every prescription through a health state machine (CLEAR,
   CAUTION, HOLD, RETURN). A health hold suppresses all workouts and exits
   only when recorded clearance criteria are met.
4. **Flags prospectively:** long-run jump over 10%, one session over 35% of
   the week's load (HR-based TRIMP), pace:HR decoupling over 5% (Friel
   first-half vs second-half), easy runs faster than prescribed, weekly ramp
   over 10%, heat go/no-go (NWS heat index), heavy lower-body strength within
   2 days of a long run.
5. **Decides** a conditional long run from data: GO, PENDING or FALLBACK.
6. **Shows** Today, the next 4 days, Plan and Trends in the phone app.

Code decides the plan; a language model is meant only to explain it. The
chat layer is not built yet.

## Athlete context (drives the logic; please sanity-check it)

- **Goals, in priority order:**
  1. IRONMAN 70.3 Puerto Rico, Mar 14 2027: goal 6:23, stretch 6:00. Baseline Eagleman 7:19:30.
  2. IRONMAN Lake Placid, Jul 25 2027: finish time deliberately unset.
  3. Marine Corps Marathon, Oct 25 2026: uncertain, decided by a data gate.
  4. Bench press 225 lb by Dec 31 2026: marked off track (estimated 1RM ~181, flat).
  5. Body recomposition.
- **Illness:** a viral illness with low-grade fever from Sep 15 2026 (health
  hold from Sep 13). Physician clearance Sep 23; 10-day return phase to Oct 2.
- **Accepted compromise (see `docs/DECISIONS.md`):** long runs 6 (Sep 26),
  13.5 (Oct 3, conditional), 16 (Oct 10), 10 (Oct 17), then race. The athlete
  asked for 16 miles within ~2 weeks on outside advice. Two WARN flags are
  accepted on purpose: Oct 3 is 41% of its week's load, and 16 is +18.5% over
  13.5.

## Please focus on

1. **Training logic.** Are the thresholds, the return-to-training rules, the
   16-mile compromise and the MCM gate defensible for this athlete? Is
   anything unsafe or not backed by evidence?
2. **Correctness.** Look at dates and timezones (the prototype had real bugs
   here), plan/actual matching, idempotency of re-syncs, and the go/no-go
   conditions in `app/ingest/evaluate.py`.
3. **Security.** Admin-token auth and cookie handling, provider tokens stored
   in the database, what a leaked token exposes, and the OAuth state handling.
4. **Failure modes.** A provider down or its API changed, the Garmin session
   expiring, overlapping syncs, a restart mid-sync, the Supabase pooler
   dropping connections.
5. **Anything claimed in docs or comments that the code doesn't actually do.**

## Known weaknesses (already on our list: confirm, rank, or add to them)

- **Auth is a single shared admin token.** The app trades it for an HttpOnly
  cookie. There are no user accounts, and the token was shared in a chat and
  not rotated (the athlete chose not to).
- **The Oura OAuth start link takes the admin token as a query parameter.**
- **Garmin and Oura tokens are stored in plain text** in the `integrations`
  table. RLS is on with no policies; the server connects as the database owner.
- **Garmin access uses an unofficial API.** It can break without notice,
  and a login from a cloud IP is rate-limited, so the token is created on
  the athlete's Mac.
- **Plans are hand-written SQL seeds** (`db/seed/*.sql`). There is no
  generator yet, so "rebase the plan when a hold ends" was done by hand in
  seed 002, not by code.
- **Two of the three clearance criteria are self-reported.** Resting HR was
  recorded as met before Oura data existed.
- **Estimates and home-made defaults:**
  - TRIMP uses the male weighting constants.
  - Max HR 190 is observed, not tested.
  - HR zones don't exist yet (no threshold test).
  - Heat thresholds are the system's own conservative defaults, not a
    published standard.
- **The scheduler assumes one server instance.** Advisory locks guard overlap,
  but it is still one thread in the web process.
- **The Hevy mis-entry exclusion isn't implemented.** The prototype manually
  excluded one entry, 220.46 lb × 5.
- **Activity dates use the local time where the activity happened**, so
  travel across timezones shifts dates.
- **Not built yet:** push notifications, the chat layer, Supabase Auth.

## How to navigate

- `docs/DECISIONS.md`: every override and trade-off, dated.
- `app/health/state.py`: the health gate.
- `app/analysis/`: overreach checks, heat, load, validator.
- `app/ingest/`: sync, evaluation, scheduler.
- `db/migrations/`: schema.
- `db/seed/`: Patrick's plan and state.
- `tests/`: 55 tests. The database tests need `TEST_DATABASE_URL`.

Please return findings ranked by severity. For each, give the file and line,
what goes wrong, a concrete scenario, and a suggested fix.
