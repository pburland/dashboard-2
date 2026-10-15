# Training Console: build your own

This is the complete code of Patrick's training app with his personal data and every
API key removed. Your own Claude can turn it into your app in about an hour, most of
it waiting for accounts.

## What it does
- **Plans your season:** Friel periodization (base, build, peak, race). Each Sunday a
  report on your week sets next week's volume, and the planner rebuilds the next 3 weeks.
- **Strength placed around endurance:** never heavy legs within 2 days of a long run or
  ride; 3/2/1/0 sessions a week by phase.
- **Safety first:** a 10% ramp limit, long-run caps, heat checks, and a
  readiness/resting-heart-rate gate. A health hold pauses training until you're cleared,
  then brings you back gradually.
- **Best time to train:** for each session, from the forecast and your work calendar.
- **Coach chat** (Claude): answers from your data; can move or change workouts, but only
  after you confirm, and never past a safety rule.
- **3-tap check-in after workouts;** missed key sessions re-planned automatically (7-day undo).
- **Phone app** (installs on iPhone) with notifications, Garmin + Oura + Hevy sync,
  weekly reports, fuel targets, travel-aware plans, encrypted weekly backups.

## Architecture (one picture)
```
 iPhone (web app on the Home Screen)
        |  HTTPS, signed-in cookie
        v
 FastAPI server on Railway (Python 3.13) ----> Anthropic API (coach chat, report text)
   - serves the app (app/web)                ---> Open-Meteo (weather, free, no key)
   - REST API (/api/...)                     ---> Google Calendar (busy times, ICS link)
   - built-in scheduler: syncs, plans,       ---> Apple/Google push services (notifications)
     reports, notifications                  <--- Garmin (activities), Oura (sleep,
        |                                          readiness), Hevy (lifts)
        v
 Supabase Postgres (all data; schema in db/migrations, applied automatically)

 GitHub Actions: weekly encrypted database backup (.github/workflows/backup.yml)
```

## Code map
| Path | What it is |
|---|---|
| `app/main.py` | Web server and every API endpoint |
| `app/web/` | The phone app (HTML/CSS/JS, service worker, icons) |
| `app/planning/` | Plan generator (`generator.py`), change checks and audit (`changes.py`, `sync.py`), best-time picker (`timing.py`), workout briefs |
| `app/health/state.py` | Health gate: clear, caution, hold, return |
| `app/analysis/` | Safety rules: ramp, long-run jump, load share, heat, decoupling, validator |
| `app/ingest/` | Garmin/Oura/Hevy sync, scheduler, morning re-plan (`rebase.py`) |
| `app/integrations/` | Garmin, Oura (OAuth), Hevy, weather, calendar, web push |
| `app/chat.py`, `app/reports.py`, `app/llm.py` | Coach chat, weekly report, Anthropic access |
| `app/notify.py`, `app/checkins.py`, `app/nutrition.py`, `app/travel.py` | Notifications, check-ins, fuel targets, trips |
| `db/migrations/` | Database schema (runs on every deploy, once per file) |
| `db/seed/001_athlete.sql` | **Your** profile, races, goals and season: the main thing to edit |
| `scripts/` | Migrations, backup/restore, Garmin login |
| `tests/` | ~110 tests. Database tests use example data in `tests/fixtures/` |
| `docs/SETUP.md` | Step-by-step account setup, in order |

## The database
Postgres on Supabase. The main tables: `profile`, `races`, `goals`, `phases` +
`phase_days` (the season), `planned_workouts`, `activities` + `laps` (Garmin),
`strength_sets` (Hevy), `recovery` (Oura), `health_episodes`, `check_ins`, `flags`,
`plan_changes` (audit trail), `plan_proposals`, `weekly_summaries`, `conversations` +
`messages` (chat), `notifications`, `push_subscriptions`, `travel`, `integrations`
(provider tokens). You never run SQL by hand: the server applies `db/migrations` and
`db/seed` on start, each file once.

## Accounts you need (and rough monthly cost)
| Service | Why | Cost |
|---|---|---|
| GitHub | Holds your copy of the code | Free |
| Railway (railway.app) | Runs the server | Hobby plan, about $5 |
| Supabase (supabase.com) | Database | Free plan is enough |
| Anthropic Console (console.anthropic.com) | Coach chat + weekly reports | Pay as you go, about $3-8 |
| Garmin Connect | Your workouts | Free |
| Oura + an Oura developer app (cloud.ouraring.com) | Sleep and readiness | Needs Oura membership |
| Hevy | Lifts | API needs Hevy Pro |
| Google Calendar | Avoids meetings when suggesting times | Optional |

## Secrets (Railway → Variables). Never put them in the code or a chat
| Variable | Where it comes from |
|---|---|
| `SUPABASE_DB_URL` | Supabase → Connect → **Session pooler** URI (with your DB password) |
| `ADMIN_TOKEN` | Make up a long random string; it's the app's password |
| `ANTHROPIC_API_KEY` | Anthropic Console → API Keys |
| `GARMIN_TOKENS` | Run `scripts/garmin_login.py` on your own computer, paste the file's contents |
| `HEVY_API_KEY` | Hevy app → Settings → Developer |
| `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET` | cloud.ouraring.com → My Applications → new app, redirect URL `https://<your-app>.up.railway.app/oauth/oura/callback` |
| `PUBLIC_BASE_URL` | Your Railway address, e.g. `https://<your-app>.up.railway.app` |
| `GOOGLE_CALENDAR_ICS_URL` | Optional. Calendar settings → "Secret address in iCal format" (or public free/busy address) |
| `TZ_NAME`, `HOME_LAT`, `HOME_LNG` | Your time zone and home coordinates (weather) |
| `ANTHROPIC_MODEL` | Optional. Empty = newest Sonnet |

GitHub → Settings → Secrets → Actions, for the weekly backup: `SUPABASE_DB_URL` and
`BACKUP_PASSPHRASE` (a long phrase you keep in a password manager).
Push notifications need no keys: the server creates its own on first use.

## Things that are personal to Patrick (your Claude will change them)
- `db/seed/001_athlete.sql`: profile, races, goals, season phases and weekly templates.
- `app/planning/timing.py` → `WINDOWS`: when you can train (his: weekdays before 8 AM
  and after 6 PM; Sundays not 9 AM-1 PM).
- `app/notify.py`: notification times and quiet hours (8:30 PM, 5:45 AM, 9:30 PM-5:30 AM).
- `app/planning/generator.py`: `PEAK_LONG_MI` / `LONG_CAP_MI` long-run caps by race distance.
- `app/web/manifest.webmanifest` / icons: app name and icon.

## Before you start
- **A Claude Pro or Max plan** (Claude Code is included; about $20/month for Pro).
- **A GitHub account.**
- **A computer with Python 3.12 or newer** (python.org → Downloads), only for the
  one-time Garmin login.
- **About an hour,** mostly waiting for accounts and deploys.

## Three steps
1. **Make the repo and upload the kit.** On github.com: **New repository** → name it
   (e.g. `training-console`) → **Private** → tick **Add a README** → Create. Then
   **Add file → Upload files** → drag in `training-console-kit.zip` (don't unzip it) →
   **Commit changes**. Start the accounts above while step 2 runs.
2. **Open Claude Code** at claude.ai/code, connect GitHub if asked, pick that repo, and
   paste the prompt below.
3. **Answer its questions and follow its setup walkthrough** (it follows
   `docs/SETUP.md`). It asks about your races, goals and weekly schedule, fills in your
   profile, pushes the code, and walks you through Supabase, Railway, keys, Garmin, Oura
   and installing the app on your phone.

## The prompt to paste
```
This repository contains training-console-kit.zip: the full code of a friend's personal
training app (FastAPI on Railway + Supabase Postgres + a phone web app), with his personal
data and all API keys removed. Build my own version of it in this repository.

1. Unzip it, move everything inside its training-console/ folder (hidden files too, like
   .github and .gitignore) to the repository root, delete the zip and the empty folder,
   and keep my README only if the kit's README isn't better. Then read START_HERE.md and
   docs/SETUP.md.
2. Interview me, one question at a time with a recommended answer, about everything in
   START_HERE.md's "Things that are personal" list: my name, time zone and home city, my
   races (date, distance, goal time, priority), strength and body goals, when I can train
   each day, notification times, and what I want my coach chat to be called. Then edit
   db/seed/001_athlete.sql, app/planning/timing.py WINDOWS and anything else needed. Keep
   the season's phases contiguous and ending on my A race.
3. Run the tests with a local Postgres for the database tests (TEST_DATABASE_URL). They
   must all pass before you push.
4. Commit and push to this repository's main branch (open and merge a pull request if you
   can't push to main directly). Never put a secret in any file, commit or chat message.
5. Walk me through docs/SETUP.md in plain language, one step at a time, waiting for me
   after each, and tell me exactly which value goes in which Railway variable. Never ask
   me to paste a key or password to you; I type them into Railway myself.
6. Finish with a short list of anything still not connected.
Explain things simply; I'll ask if I want detail.
```
