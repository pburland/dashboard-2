"""Heart-rate zones from a tested lactate threshold heart rate (LTHR).

Friel's zones are percentages of LTHR, found with a 30-minute solo time
trial (average HR of the final 20 minutes). Until a test exists the athlete
has no zones, and every check that would use them falls back to pace and
says so. Nothing here invents zones from age or a max-HR formula.
"""
from __future__ import annotations

from app import rules

# (zone, low %, high %) of LTHR. High bound exclusive except the last zone.
RUN_ZONES = rules.value("run_hr_zones")
BIKE_ZONES = rules.value("bike_hr_zones")

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


# ── zones as a system (outside review, Card 2) ─────────────────────────────
# The latest applied fitness test of each kind (fitness_tests) sets that sport's
# zones; until a test exists the provisional rules apply and say so.
RUN_PACE_ZONES = rules.value("run_pace_zones")
POWER_ZONES = rules.value("power_zones")
_CURRENT: dict = {}


def refresh(conn) -> dict:
    """Load the latest applied test per kind (call before planning or pushing)."""
    rows = conn.execute(
        """select distinct on (kind) * from fitness_tests where status = 'applied'
           order by kind, test_date desc, id desc""").fetchall()
    _CURRENT.clear()
    _CURRENT.update({r["kind"]: dict(r) for r in rows})
    return dict(_CURRENT)


def current() -> dict:
    return dict(_CURRENT)


def run_lthr() -> int | None:
    t = _CURRENT.get("run_lthr")
    return t and t["result"].get("lthr")


def bike_lthr() -> int | None:
    t = _CURRENT.get("bike_ftp")
    return t and t["result"].get("bike_lthr")


def easy_hr_range(sport: str = "run") -> tuple[int, int, bool]:
    """(low, high, provisional) average-HR range for easy (Z2) work."""
    lthr = run_lthr() if sport == "run" else bike_lthr()
    if lthr:
        lo, hi = zone_bounds(lthr, sport)["Z2"]
        return lo, hi, False
    cap = rules.value("easy_hr_cap")
    if sport == "run":
        return rules.value("easy_hr_floor"), cap, True
    return 110, cap - 5, True


def run_pace_zones(threshold_s_per_mi: float) -> dict[str, tuple[int, int]]:
    """{zone: (fast, slow)} seconds per mile from threshold pace (Friel)."""
    return {z: (round(threshold_s_per_mi * fast), round(threshold_s_per_mi * min(slow, 2.0)))
            for z, fast, slow in RUN_PACE_ZONES}


def css_targets(css_s_per_100: float) -> dict[str, int]:
    return {z: round(css_s_per_100 + off) for z, off in rules.value("css_zone_offsets").items()}


def power_zones(ftp_w: float) -> dict[str, tuple[int, int]]:
    return {z: (round(ftp_w * lo), round(ftp_w * min(hi, 2.0)) - 1) for z, lo, hi in POWER_ZONES}


def fmt_pace(s: float) -> str:
    s = round(s)
    return f"{s // 60}:{s % 60:02d}"


def summary() -> list[str]:
    """Plain-language lines: what zones are set and from which test."""
    out = []
    t = _CURRENT.get("run_lthr")
    if t:
        lo, hi, _ = easy_hr_range("run")
        r = t["result"]
        tp = r.get("threshold_pace_s_per_mi")
        out.append(f"Run zones from {t['test_date']:%b %-d}: LTHR {r['lthr']} bpm, easy runs {lo}-{hi} bpm"
                   + (f", threshold pace {fmt_pace(tp)}/mi" if tp else "") + ".")
    else:
        out.append(f"Run zones not set yet: easy runs use the provisional cap of {rules.value('easy_hr_cap')} bpm "
                   "until the run test.")
    t = _CURRENT.get("bike_ftp")
    if t:
        r = t["result"]
        bits = [f"FTP {r['ftp_w']} W (indoor only)"] if r.get("ftp_w") else []
        if r.get("bike_lthr"):
            bits.append(f"bike LTHR {r['bike_lthr']} bpm")
        out.append(f"Bike zones from {t['test_date']:%b %-d}: " + ", ".join(bits) + ".")
    t = _CURRENT.get("swim_css")
    if t:
        r = t["result"]
        out.append(f"Swim CSS from {t['test_date']:%b %-d}: {fmt_pace(r['css_s_per_100'])} per 100 {r.get('unit', 'yd')}.")
    return out
