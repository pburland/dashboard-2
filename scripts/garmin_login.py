"""One-time Garmin login, run on your own computer (not the server).

Garmin blocks password logins from cloud servers, so you log in here once and
give the server the resulting token (it renews it by itself afterwards).

    python3 -m venv .venv && source .venv/bin/activate
    pip install "garminconnect>=0.3.16"          # needs Python 3.12+
    python scripts/garmin_login.py
    # then copy garmin_tokens.json's contents into Railway as GARMIN_TOKENS
    # (macOS: pbcopy < garmin_tokens.json). Delete the file afterwards.

Two "returned 429" warnings are normal: Garmin rate-limits the first login
methods and the library falls through to one that works.
"""
import getpass

from garminconnect import Garmin

email = input("Garmin email: ")
pw = getpass.getpass("Garmin password (typing is hidden): ")
g = Garmin(email, pw, prompt_mfa=lambda: input("Code Garmin just sent you: "))
g.login()
open("garmin_tokens.json", "w").write(g.client.dumps())
print("Logged in as:", g.get_full_name())
for a in g.get_activities(0, 3):
    print(a["startTimeLocal"], a["activityType"]["typeKey"], round(a.get("distance", 0) / 1609.34, 2), "mi")
