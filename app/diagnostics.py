"""Integration checks, runnable from Railway to validate every source.

    python -m app.diagnostics         # prints JSON
    GET /admin/diagnostics            # same, over HTTP (needs ADMIN_TOKEN)

Each check is independent: one failing source never hides another.
"""
from __future__ import annotations

import json
import sys
import traceback
from contextlib import ExitStack

from app.config import MissingConfig


def _run(fn) -> dict:
    try:
        return fn()
    except MissingConfig as e:
        return {"ok": False, "not_configured": list(e.names)}
    except Exception as e:  # report, never raise: this is a diagnostic
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "where": traceback.extract_tb(e.__traceback__)[-1].name}


def run_all() -> dict:
    from app import db
    from app.integrations import garmin, hevy, oura, weather

    results: dict = {}
    with ExitStack() as stack:
        conn = None
        try:
            conn = stack.enter_context(db.connect())
            conn.execute("select 1")
            results["database"] = {"ok": True}
        except MissingConfig as e:
            results["database"] = {"ok": False, "not_configured": list(e.names)}
        except Exception as e:
            results["database"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        results["garmin"] = _run(lambda: garmin.check(conn))
        if conn is not None:
            conn.commit()     # keep a renewed Garmin token even if a later check fails
        results["hevy"] = _run(hevy.check)
        results["oura"] = (_run(lambda: oura.check(conn)) if conn is not None else
                           {"ok": False, "not_configured": ["database (Oura tokens live there)"]})
        results["weather"] = _run(weather.check)

    results["all_ok"] = all(v.get("ok") for v in results.values())
    return results


if __name__ == "__main__":
    out = run_all()
    print(json.dumps(out, indent=2, default=str))
    sys.exit(0 if out["all_ok"] else 1)
