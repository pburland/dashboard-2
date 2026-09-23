"""Friel periodization framework (Triathlete's Training Bible), as data.

Kept from Felipe's build: the *structure* of a period definition (active
abilities, prohibited work, strength phase, intensity ceiling, volume
trend) and Friel's concurrent strength sequencing. Removed: all of his
athlete-specific numbers (lab HR zones, CSS pace, volume targets). Nothing
here is tied to one athlete; ceilings are zone names, resolved against the
athlete's own zones (see ``zones.py``) or pace when zones are untested.

Abilities: AE aerobic endurance, MF muscular force, SS speed skills,
ME muscular endurance, ANE anaerobic endurance, SP sprint power.
Strength phases: AA anatomical adaptation, MT maximum transition,
MS maximum strength, SM strength maintenance.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Period:
    kind: str
    label: str
    active_abilities: tuple[str, ...]
    prohibited: tuple[str, ...]
    strength_phase: str | None       # AA / MT / MS / SM / None
    strength_per_week: tuple[int, int]
    intensity_ceiling: str           # highest zone allowed in the period
    volume_trend: str


PERIODS: dict[str, Period] = {
    "prep": Period(
        "prep", "Preparation",
        ("AE", "SS"), ("ME", "ANE", "SP"),
        "AA", (2, 3), "Z2",
        "Low and rising; cross-training welcome.",
    ),
    "base": Period(
        "base", "Base",
        ("AE", "MF", "SS"), ("ANE", "SP", "sustained Z4+"),
        "MS", (2, 3), "Z3",
        "Progressive volume, +<=10% per loading week, 3:1 load:recovery.",
    ),
    "build": Period(
        "build", "Build",
        ("AE", "ME", "MF", "SS"), ("SP",),
        "SM", (1, 2), "Z5a",
        "Volume holds; race-specific intensity rises. 3:1 load:recovery.",
    ),
    "peak": Period(
        "peak", "Peak",
        ("ME", "ANE", "AE"), ("new modalities", "long unstructured volume"),
        "SM", (1, 1), "Z5b",
        "Volume down, race-simulation sessions.",
    ),
    "race": Period(
        "race", "Race / taper",
        ("ME", "SS"), ("new loading", "heavy strength", "long sessions"),
        None, (0, 0), "Z4",
        "Volume down ~40-50%; short race-pace touches keep sharpness.",
    ),
    "transition": Period(
        "transition", "Transition",
        ("AE",), ("structured intensity",),
        "AA", (0, 2), "Z2",
        "Unstructured, low; recovery from the previous race.",
    ),
    # Not a Friel period: the return-to-training block the health hold
    # inserts when a hold ends. Rebasing starts from here.
    "return": Period(
        "return", "Return to training",
        ("AE",), ("ME", "ANE", "SP", "long-run growth", "heavy lower-body strength"),
        "AA", (1, 2), "Z2",
        "Starts at ~50% of pre-hold volume and ramps; see app.health.state.",
    ),
}

# Friel's guidance for concurrent strength + endurance, applied as rules by
# the plan validator rather than left as prompt text.
CONCURRENT_RULES = (
    "Heavy strength and key endurance sessions go on separate days, or >=6h apart.",
    "No heavy lower-body strength within 2 days before a long run or long ride.",
    "Strength frequency steps down toward the A race: 3x base, 2x build, 1x peak, 0 race week.",
    "Strength load stays flat or drops during endurance loading weeks.",
)

# Recovery-week rule of thumb from Friel's 3:1 mesocycle.
LOADING_WEEKS_PER_RECOVERY = 3
RECOVERY_WEEK_VOLUME = 0.6
