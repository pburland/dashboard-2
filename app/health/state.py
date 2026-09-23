"""Health state: the gate that runs before any prescription.

States
  CLEAR    normal training.
  CAUTION  set automatically from morning signals (Oura readiness, resting
           HR, temperature). Caps intensity at Z2 and freezes long-run
           growth for the day. It does not need to be cleared by hand.
  HOLD     an open illness/injury episode. No prescriptions at all: the
           generator emits nothing and the UI shows the exit criteria.
           Only an explicit action with every criterion recorded exits it;
           the chat model can log a note that opens a hold but can never
           close one.
  RETURN   graded re-entry after a hold. Volume ramps from 50%, intensity
           capped at Z2, long run capped below the pre-hold longest.
           When it ends the plan is rebased from that date instead of
           resuming the original schedule.

This module is pure: callers pass in the episode and today's signals, and
get back a status and a gate. Persistence lives in the database layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from enum import Enum


class Status(str, Enum):
    CLEAR = "clear"
    CAUTION = "caution"
    HOLD = "hold"
    RETURN = "return"


# Every one must be recorded (with the date it was met) to leave HOLD.
EXIT_CRITERIA: dict[str, str] = {
    "fever_free_48h": "Fever-free for at least 48 hours without fever-reducing medication",
    "physician_clearance": "Physician has cleared a return to exercise (for a suspected tick-borne illness, ask specifically about the heart)",
    "rhr_near_baseline_3d": "Resting HR within 5 bpm of pre-illness baseline for 3 consecutive days",
}

RETURN_MIN_DAYS = 7
RETURN_MAX_DAYS = 21
RETURN_START_VOLUME = 0.5
RETURN_END_VOLUME = 0.9
RETURN_LONG_RUN_CAP = 0.7   # fraction of the pre-hold longest run


@dataclass(frozen=True)
class Episode:
    started_on: date
    reason: str
    kind: str = "illness"                       # illness | injury
    criteria_met: dict[str, date] = field(default_factory=dict)
    return_started_on: date | None = None
    return_ends_on: date | None = None
    closed_on: date | None = None
    id: int | None = None


@dataclass(frozen=True)
class MorningSignals:
    """Today's readiness inputs. Any field may be missing."""
    readiness: int | None = None
    resting_hr: int | None = None
    resting_hr_baseline: int | None = None
    temp_deviation_c: float | None = None     # Oura body-temperature deviation


@dataclass(frozen=True)
class Gate:
    status: Status
    prescriptions_allowed: bool
    intensity_ceiling: str | None     # zone name; None = phase default
    volume_multiplier: float
    long_run_growth_allowed: bool
    reasons: tuple[str, ...]


class HoldExitRefused(RuntimeError):
    def __init__(self, missing: list[str]):
        super().__init__("criteria not met: " + ", ".join(missing))
        self.missing = missing


def caution_reasons(s: MorningSignals) -> list[str]:
    reasons = []
    if s.readiness is not None and s.readiness < 70:
        reasons.append(f"Oura readiness {s.readiness} (<70)")
    if (s.resting_hr is not None and s.resting_hr_baseline is not None
            and s.resting_hr >= s.resting_hr_baseline + 5):
        reasons.append(f"resting HR {s.resting_hr} vs baseline {s.resting_hr_baseline} (+5 or more)")
    if s.temp_deviation_c is not None and s.temp_deviation_c >= 0.5:
        reasons.append(f"body temperature +{s.temp_deviation_c:.1f}°C vs baseline — possible illness, log it if you feel unwell")
    return reasons


def status(episode: Episode | None, signals: MorningSignals, as_of: date) -> Status:
    if episode is not None and episode.closed_on is None:
        if episode.return_started_on is None:
            return Status.HOLD
        if episode.return_ends_on is not None and as_of <= episode.return_ends_on:
            return Status.RETURN
    if caution_reasons(signals):
        return Status.CAUTION
    return Status.CLEAR


def missing_criteria(episode: Episode) -> list[str]:
    return [k for k in EXIT_CRITERIA if k not in episode.criteria_met]


def record_criterion(episode: Episode, key: str, met_on: date) -> Episode:
    if key not in EXIT_CRITERIA:
        raise KeyError(f"unknown criterion '{key}'")
    return replace(episode, criteria_met={**episode.criteria_met, key: met_on})


def return_length_days(episode: Episode, return_start: date) -> int:
    hold_days = (return_start - episode.started_on).days
    return max(RETURN_MIN_DAYS, min(RETURN_MAX_DAYS, hold_days))


def begin_return(episode: Episode, on: date) -> Episode:
    """Leave HOLD. Refuses unless every exit criterion is recorded."""
    missing = missing_criteria(episode)
    if missing:
        raise HoldExitRefused(missing)
    if on < max(episode.criteria_met.values()):
        raise ValueError("return cannot start before the last criterion was met")
    length = return_length_days(episode, on)
    return replace(episode, return_started_on=on,
                   return_ends_on=on + timedelta(days=length - 1))


def return_volume(episode: Episode, as_of: date) -> float:
    """Linear ramp from RETURN_START_VOLUME to RETURN_END_VOLUME."""
    assert episode.return_started_on and episode.return_ends_on
    span = (episode.return_ends_on - episode.return_started_on).days or 1
    progress = min(1.0, max(0.0, (as_of - episode.return_started_on).days / span))
    return round(RETURN_START_VOLUME + (RETURN_END_VOLUME - RETURN_START_VOLUME) * progress, 2)


def gate(episode: Episode | None, signals: MorningSignals, as_of: date) -> Gate:
    st = status(episode, signals, as_of)
    if st is Status.HOLD:
        missing = missing_criteria(episode)
        return Gate(st, False, None, 0.0, False, tuple(
            [f"health hold since {episode.started_on}: {episode.reason}"]
            + [f"to exit: {EXIT_CRITERIA[k]}" for k in missing]))
    if st is Status.RETURN:
        vol = return_volume(episode, as_of)
        return Gate(st, True, "Z2", vol, False, (
            f"return to training until {episode.return_ends_on}: {int(vol * 100)}% volume, Z2 only",
            f"long run capped at {int(RETURN_LONG_RUN_CAP * 100)}% of pre-hold longest",
        ))
    if st is Status.CAUTION:
        return Gate(st, True, "Z2", 1.0, False, tuple(caution_reasons(signals)))
    return Gate(st, True, None, 1.0, True, ())
