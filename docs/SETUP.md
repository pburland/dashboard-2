# Setup: accounts, secrets and first deploy

Written for doing this once, in order. Each step says what success looks
like. Never paste a secret into a chat, an issue, or a file in this repo;
secrets go only into Railway → Variables.

## 1. Garmin token (done once on your Mac)

Already done if `~/garmin-login/garmin_tokens.json` exists and
`python login.py` printed your name. Run it again right before step 3 so
Railway gets a fresh token:

```bash
cd ~/garmin-login && source .venv/bin/activate && python login.py
```

The two "returned 429" warnings are normal: Garmin rate-limits the first
login methods and the library falls through to one that works.

## 2. Supabase (database)

1. supabase.com → **New project**. Name: `training`. Region: East US (North Virginia).
   Set a database password and save it in your password manager.
2. When it's ready: **Connect** (top of the project page) → **Session pooler**
   → copy the URI. Replace `[YOUR-PASSWORD]` with the password from step 1.
   *Use Session pooler, not "Direct connection": Railway can't reach the
   direct address.*
3. That URI is `SUPABASE_DB_URL`. You don't run any SQL yourself: every
   deploy applies `db/migrations` and the seed automatically.

## 3. Railway (the server)

1. railway.app → sign in with GitHub → **New Project** → **Deploy from
   GitHub repo** → `pburland/dashboard-2`. If Railway asks for access to
   the repo, grant it.
   Then service → **Settings → Source → Branch**: choose
   `claude/training-system-handoff-awyg4h` (until it's merged to `main`).
   The first deploy may fail before step 3.3 is done: that's expected, it
   has no database address yet.
2. Service → **Settings → Networking → Generate Domain**. Copy the
   `https://…up.railway.app` address.
3. Service → **Variables** → add each of these:

| Variable | Value |
|---|---|
| `SUPABASE_DB_URL` | from step 2 |
| `ADMIN_TOKEN` | run `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` in Terminal, paste the output. Save it in your password manager. |
| `PUBLIC_BASE_URL` | the Railway address from 3.2 |
| `HEVY_API_KEY` | a **new** key from Hevy (the one shared in chat should be regenerated) |
| `GARMIN_TOKENS` | run `pbcopy < ~/garmin-login/garmin_tokens.json`, then paste. Looks like `{"di_token": …}` |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys (used from the chat step onward) |

4. Railway redeploys. **Success:** opening `https://<your-domain>/healthz`
   shows today's date.

## 4. Oura

1. cloud.ouraring.com → sign in → **API Applications** (developer section)
   → **New application**.
   (You already have one: open it and edit it instead.)
2. Redirect URI: `https://<your-domain>/oauth/oura/callback` exactly:
   `https`, no trailing slash, nothing after `callback`.
3. **Regenerate the client secret** (the old one was shared in chat), then
   add `OURA_CLIENT_ID` and the new `OURA_CLIENT_SECRET` to Railway
   Variables and wait for the redeploy.
4. In your browser open
   `https://<your-domain>/oauth/oura/start?key=<ADMIN_TOKEN>` and approve.
   **Success:** "Oura connected."

## 5. Check everything

```bash
curl -s -H "X-Admin-Token: <ADMIN_TOKEN>" https://<your-domain>/admin/diagnostics
```

Paste that into Terminal with your real token and domain. Each source
reports `"ok": true` or says exactly what's missing. The
important one is `garmin`: it proves Railway can renew your Garmin token
without logging in. If it fails, send the `garmin` part of the output
(it contains no secrets).

## 6. Data sync (automatic)

On its first start with the database connected, the server backfills 12
months of Garmin activities (with per-mile laps), all Hevy sets and Oura
recovery. Then it syncs nightly at 3:00 AM and again at 5:30 AM with the
heat and readiness checks. To see what it has done:

```bash
read -s TOKEN
curl -s -H "X-Admin-Token: $TOKEN" https://dashboard-2-production-6f5f.up.railway.app/admin/sync/status | python3 -m json.tool
```

Today's view as the phone app will see it: `/api/today` (same header).
To force a sync now: `curl -s -X POST -H "X-Admin-Token: $TOKEN" ".../admin/sync?days=3"`.
