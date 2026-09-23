"""Heart-rate zones from a tested lactate threshold heart rate (LTHR).

Friel's zones are percentages of LTHR, found with a 30-minute solo time
trial (average HR of the final 20 minutes). Until a test exists the athlete
has no zones, and every check that would use them falls back to pace and
says so. Nothing here invents zones from age or a max-HR formula.
"""
from __future__ import annotations

# (zone, low %, high %) of LTHR. High bound exclusive except the last zone.
RUN_ZONES = (
    ("Z1", 0.00, 0.85),
    ("Z2", 0.85, 0.90),
    ("Z3", 0.90, 0.95),
    ("Z4", 0.95, 1.00),
    ("Z5a", 1.00, 1.03),
    ("Z5b", 1.03, 1.07),
    ("Z5c", 1.07, 2.00),
)

BIKE_ZONES = (
    ("Z1", 0.00, 0.81),
    ("Z2", 0.81, 0.90),
    ("Z3", 0.90, 0.94),
    ("Z4", 0.94, 1.00),
    ("Z5a", 1.00, 1.03),
    ("Z5b", 1.03, 1.07),
    ("Z5c", 1.07, 2.00),
)

ZONE_ORDER = [z for z, _, _ in RUN_ZONES]


def zone_bounds(lthr: int, sport: str = "run") -> dict[str, tuple[int, int]]:
    table = RUN_ZONES if sport == "run" else BIKE_ZONES
    return {z: (round(lthr * lo), round(lthr * hi) - 1) for z, lo, hi in table}


def zone_for_hr(hr: float, lthr: int, sport: str = "run") -> str:
    table = RUN_ZONES if sport == "run" else BIKE_ZONES
    ratio = hr / lthr
    for z, lo, hi in table:
        if lo <= ratio < hi:
            return z
    return table[-1][0]


def at_or_below(zone: str, ceiling: str) -> bool:
    return ZONE_ORDER.index(zone) <= ZONE_ORDER.index(ceiling)
