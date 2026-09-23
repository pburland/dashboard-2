"""Flag record shared by every check."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    STOP = "stop"      # the session should not go ahead as planned


@dataclass(frozen=True)
class Flag:
    kind: str
    severity: Severity
    message: str
    data: dict = field(default_factory=dict)
