"""Phase table: validation and lookup.

Lesson from the prototype: a gap between phases made the current-phase
lookup silently return the wrong phase. Felipe's build has the same bug
class (an unknown phase name silently falls back to "Build"). Here:

  * ``validate_phases`` rejects gaps, overlaps and inverted ranges. The
    database enforces the same rules (see db/migrations/001_schema.sql).
  * ``phase_for`` never guesses. A date outside the table raises
    ``NoPhaseDefined`` instead of returning a neighbouring phase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.periodization.friel import PERIODS


@dataclass(frozen=True)
class Phase:
    name: str
    kind: str            # a key of friel.PERIODS
    start_date: date     # inclusive
    end_date: date       # inclusive
    note: str = ""
    id: int | None = None
    days: tuple = field(default_factory=tuple)


class PhaseTableError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class NoPhaseDefined(LookupError):
    pass


def validate_phases(phases: list[Phase]) -> None:
    """Raise PhaseTableError listing every problem found (not just the first)."""
    problems: list[str] = []
    if not phases:
        raise PhaseTableError(["phase table is empty"])

    for p in phases:
        if p.start_date > p.end_date:
            problems.append(f"{p.name}: starts {p.start_date} after it ends {p.end_date}")
        if p.kind not in PERIODS:
            problems.append(f"{p.name}: unknown kind '{p.kind}'")

    ordered = sorted(phases, key=lambda p: p.start_date)
    for prev, cur in zip(ordered, ordered[1:]):
        expected = prev.end_date + timedelta(days=1)
        if cur.start_date > expected:
            problems.append(
                f"gap: {prev.name} ends {prev.end_date}, {cur.name} starts "
                f"{cur.start_date} ({(cur.start_date - expected).days} day(s) uncovered)"
            )
        elif cur.start_date < expected:
            problems.append(f"overlap: {prev.name} and {cur.name} share {cur.start_date}")

    if problems:
        raise PhaseTableError(problems)


def phase_for(phases: list[Phase], d: date) -> Phase:
    for p in phases:
        if p.start_date <= d <= p.end_date:
            return p
    first = min(p.start_date for p in phases)
    last = max(p.end_date for p in phases)
    raise NoPhaseDefined(
        f"no phase covers {d}; the table runs {first} to {last}"
    )


def coverage_warnings(phases: list[Phase], through: date) -> list[str]:
    """Non-fatal: the table should reach the last goal race."""
    last = max(p.end_date for p in phases)
    if last < through:
        return [f"phase table ends {last}; nothing is planned from {last + timedelta(days=1)} to {through}"]
    return []
