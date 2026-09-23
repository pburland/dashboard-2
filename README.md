# Training system

Patrick's concurrent strength + triathlon training system: Garmin, Hevy
and Oura in; Friel periodization with a hard health gate; a phone app out.

- `docs/SETUP.md` — accounts, secrets, first deploy (step by step)
- `docs/DECISIONS.md` — what was kept from Felipe's build, what changed, why

## Layout
```
app/clock.py              the only source of "today"
app/periodization/        phase table validation, Friel periods, HR zones
app/health/state.py       CLEAR / CAUTION / HOLD / RETURN gate
app/analysis/             overreach checks, heat go/no-go, TRIMP load, plan validator
app/integrations/         Garmin, Hevy, Oura (OAuth2), Open-Meteo
app/main.py               web service
db/migrations, db/seed    schema and Patrick's starting state (applied on deploy)
```

## Local development
```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

No secret is ever committed. Credentials live only in Railway variables;
`.env.example` lists their names.
