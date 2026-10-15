# Setup: accounts, secrets and first deploy

Do this once, in order. Each step says what success looks like. Never paste a
secret into a chat, an issue, or a file in this repo: secrets go only into
Railway → Variables (and GitHub → Actions secrets for backups).

You'll need: a computer with Python 3.12 or newer (python.org → Downloads) for
step 1, and about an hour, mostly waiting.

## 1. Garmin token (once, on your own computer)

Garmin blocks password logins from cloud servers, so you log in once on your
computer and give the server the resulting token (it renews itself after that).

Download `scripts/garmin_login.py` from your GitHub repo (open the file →
"Download raw file"). Then in Terminal (Mac) or PowerShell (Windows), from the
folder it downloaded to:

```bash
python3 -m venv garmin-venv
source garmin-venv/bin/activate          # Windows: garmin-venv\Scripts\activate
pip install "garminconnect>=0.3.16"
python garmin_login.py
```

Enter your Garmin email, password and the code Garmin sends you. **Success:** it
prints your name and three recent activities, and `garmin_tokens.json` appears
in that folder. Keep it for step 3, then delete it. Two "returned 429" warnings
are normal.

## 2. Supabase (database)

1. supabase.com → **New project**. Name: `training`. Pick the region nearest you.
   Set a database password and save it in your password manager.
2. When it's ready: **Connect** (top of the project page) → **Session pooler**
   → copy the URI. Replace `[YOUR-PASSWORD]` with the password from step 1.
   *Use Session pooler, not "Direct connection": Railway can't reach the
   direct address.*
3. That URI is `SUPABASE_DB_URL`. You don't run any SQL yourself: every
   deploy applies `db/migrations` and `db/seed` automatically.

## 3. Railway (the server)

1. railway.app → sign in with GitHub → **New Project** → **Deploy from
   GitHub repo** → your repo (branch `main`). If Railway asks for access to the
   repo, grant it. The first deploy may fail until step 3.3 is done: that's
   expected, it has no database address yet.
2. Service → **Settings → Networking → Generate Domain**. Copy the
   `https://…up.railway.app` address.
3. Service → **Variables** → add each of these:

| Variable | Value |
|---|---|
| `SUPABASE_DB_URL` | from step 2 |
| `ADMIN_TOKEN` | a long random string; it's the app's password. Make one with `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`. Save it in your password manager. |
| `PUBLIC_BASE_URL` | the Railway address from 3.2 |
| `TZ_NAME` | your time zone, e.g. `America/New_York` |
| `HOME_LAT`, `HOME_LNG` | your home coordinates (Google Maps → right-click your area → the numbers at the top) |
| `GARMIN_TOKENS` | the whole contents of `garmin_tokens.json` (Mac: `pbcopy < garmin_tokens.json`, then paste; Windows: open it in Notepad and copy). Looks like `{"di_token": …}` |
| `HEVY_API_KEY` | Hevy app → Settings → Developer (needs Hevy Pro). Skip if you don't use Hevy. |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys (Coach chat and weekly report text). Add a few dollars of credit. |
| `GOOGLE_CALENDAR_ICS_URL` | optional. Google Calendar → Settings → your calendar → "Secret address in iCal format". If your work account hides that, use "Make available to public → See only free/busy" and its public address. |

4. Railway redeploys. **Success:** opening `https://<your-domain>/healthz`
   shows today's date.

## 4. Oura

1. cloud.ouraring.com → sign in → **API Applications** (developer section)
   → **New application**.
2. Redirect URI: `https://<your-domain>/oauth/oura/callback` exactly:
   `https`, no trailing slash, nothing after `callback`.
3. Add `OURA_CLIENT_ID` and `OURA_CLIENT_SECRET` to Railway Variables and wait
   for the redeploy.
4. In your browser open
   `https://<your-domain>/oauth/oura/start?key=<ADMIN_TOKEN>` and approve.
   **Success:** "Oura connected."

## 5. Sign in and check everything

1. On your phone, open `https://<your-domain>` in Safari and paste your
   `ADMIN_TOKEN` into the sign-in box. It stays signed in. Do the same on any
   other browser you use (Chrome and Safari keep separate sign-ins).
2. Bottom of the Today tab → **Check connections**. Each source shows ok, or
   says exactly what's missing. Or from Terminal:

```bash
curl -s -H "X-Admin-Token: <ADMIN_TOKEN>" https://<your-domain>/admin/diagnostics
```

The important one is `garmin`: it proves the server can renew your Garmin
token without logging in.

## 6. Data sync (automatic)

On its first start with the database connected, the server backfills 12
months of Garmin activities (with per-mile laps), all Hevy sets and Oura
recovery. Then it syncs nightly at 3:00 AM and again at 5:30 AM with the
heat and readiness checks. The refresh button at the top of the app syncs on
demand.

## 7. Weekly report, plan and Coach
- **Sunday 7 PM** (where you are): the server syncs the week, writes a report
  (Reports tab), and re-plans the next 3 weeks from it. Week one is the plan;
  weeks two and three are a preview and get rebuilt the next Sunday.
- To write one now: `curl -X POST -H "X-Admin-Token: <ADMIN_TOKEN>" "https://<your-domain>/admin/report"`.
- **Coach** (tab in the app) answers from your data. It can move workouts
  after you confirm, save notes, and start a health hold if you report being
  sick; it can never end one.

## 8. Backups (free)
- **Automatic, weekly (encrypted):** a GitHub Action exports the database
  every Monday and keeps each copy 90 days. One-time setup: GitHub → the repo →
  **Settings → Secrets and variables → Actions → New repository secret**, add
  `SUPABASE_DB_URL` (same as Railway) and `BACKUP_PASSPHRASE` (a long phrase;
  store it in your password manager, since without it the backups can't be opened).
  Test it: **Actions → Weekly backup → Run workflow**. Copies appear under each
  run's **Artifacts**.
- **Any time, from the app:** "Download backup" at the bottom of Today saves
  a zip of CSVs (opens in Excel). Provider tokens are left out.
- **Open an encrypted copy:**
  `openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in backup.zip.enc -out backup.zip`
- **Restore** (replaces all data): `SUPABASE_DB_URL=... python -m scripts.backup restore backup.zip`

## 9. Phone app and notifications (iPhone)
1. In Safari open the app (signed in, step 5), tap **Share → Add to Home Screen**,
   then open it from the Home Screen.
2. Bottom of Today → **Notifications → Turn on notifications**, allow them.
   (iPhone only allows this from the Home Screen app, iOS 16.4 or newer.)
3. Tap **Send test notification**: a notification arrives. Switch types on/off in the same panel.
Nothing to configure on Railway: the server creates its own push signing key on first use.
