# Setup: accounts, secrets and first deploy

Written for doing this once, in order. Each step says what success looks
like. Never paste a secret into a chat, an issue, or a file in this repo;
secrets go only into Railway → Variables.

## 1. Garmin token (done once on your Mac)

Already done if `~/garmin-login/garmin_tokens.json` exists and
`python login.py` printed your name. To refresh it later:

```bash
cd ~/garmin-login && source .venv/bin/activate && python login.py
```

The two "returned 429" warnings are normal: Garmin rate-limits the first
login methods and the library falls through to one that works.

## 2. Supabase (database)

1. supabase.com → **New project**. Name: `training`. Region: East US.
   Set a database password and save it in your password manager.
2. When it's ready: **Connect** (top of the project page) → **Session pooler**
   → copy the URI. Replace `[YOUR-PASSWORD]` with the password from step 1.
   *Use Session pooler, not "Direct connection": Railway can't reach the
   direct address.*
3. That URI is `SUPABASE_DB_URL`. You don't run any SQL yourself: every
   deploy applies `db/migrations` and the seed automatically.

## 3. Railway (the server)

1. railway.app → sign in with GitHub → **New Project** → **Deploy from
   GitHub repo** → `pburland/dashboard-2`. When asked, pick the branch
   this work is on (or `main` once merged).
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
2. Redirect URI: `https://<your-domain>/oauth/oura/callback` (exactly).
3. Add `OURA_CLIENT_ID` and `OURA_CLIENT_SECRET` to Railway Variables and
   wait for the redeploy.
4. In your browser open
   `https://<your-domain>/oauth/oura/start?key=<ADMIN_TOKEN>` and approve.
   **Success:** "Oura connected."

## 5. Check everything

```bash
curl -s -H "X-Admin-Token: <ADMIN_TOKEN>" https://<your-domain>/admin/diagnostics
```

Each source reports `"ok": true` or says exactly what's missing. The
important one is `garmin`: it proves Railway can renew your Garmin token
without logging in. If it fails, send the `garmin` part of the output
(it contains no secrets).
