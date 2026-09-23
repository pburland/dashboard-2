"""Training load, computed the same way for every source.

Garmin's CSV export has no training-load column and Strava is out of the
picture, so load is computed here from heart rate: Banister TRIMP,
duration x heart-rate reserve fraction x exponential weighting. The
absolute number is not comparable to Strava's relative effort or Garmin's
training load, but shares and ratios (which is what the flags use) are.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Heart-rate-reserve fraction assumed for a planned session in each zone,
# used only to *estimate* the load of a session that hasn't happened yet.
PLANNED_ZONE_HRR = {"Z1": 0.50, "Z2": 0.62, "Z3": 0.72, "Z4": 0.82,
                    "Z5a": 0.88, "Z5b": 0.92, "Z5c": 0.95}


def hrr_fraction(avg_hr: float, rest_hr: float, max_hr: float) -> float:
    if max_hr <= rest_hr:
        raise ValueError("max HR must be above resting HR")
    return min(1.0, max(0.0, (avg_hr - rest_hr) / (max_hr - rest_hr)))


def trimp(duration_min: float, avg_hr: float, rest_hr: float, max_hr: float) -> float:
    """Banister TRIMP (male weighting constants 0.64, 1.92)."""
    x = hrr_fraction(avg_hr, rest_hr, max_hr)
    return duration_min * x * 0.64 * math.exp(1.92 * x)


def estimate_planned_load(duration_min: float, zone: str) -> float:
    x = PLANNED_ZONE_HRR[zone]
    return duration_min * x * 0.64 * math.exp(1.92 * x)


@dataclass(frozen=True)
class LoadShare:
    session_load: float
    week_load: float
    share: float


def session_share(session_load: float, other_loads: list[float]) -> LoadShare:
    total = session_load + sum(other_loads)
    share = session_load / total if total > 0 else 0.0
    return LoadShare(round(session_load, 1), round(total, 1), round(share, 3))
