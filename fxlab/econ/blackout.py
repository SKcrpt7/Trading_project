"""News blackout rule.

"Do not open a new trade shortly before or after a selected high-impact release."
The window is fully configurable and testable. If an event's time is only
CONVENTIONAL (time_is_exact=False), the window is widened by a safety margin on
each side because we are not certain of the precise minute.

IMPORTANT: this rule only ever BLOCKS trading. A news summary may inform you, but
no AI prediction is allowed to place a trade. The blackout is a pure safety gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fxlab.econ.events import EventCalendar
from fxlab.types import EconomicEvent

_IMPACT_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass
class BlackoutConfig:
    enabled: bool = True
    block_minutes_before: int = 30
    block_minutes_after: int = 30
    min_impact: str = "high"
    uncertain_time_extra_minutes: int = 30

    @classmethod
    def from_config(cls, cfg: dict) -> "BlackoutConfig":
        b = cfg.get("blackout", cfg)  # accept either the whole news cfg or the sub-dict
        return cls(
            enabled=bool(b.get("enabled", True)),
            block_minutes_before=int(b.get("block_minutes_before", 30)),
            block_minutes_after=int(b.get("block_minutes_after", 30)),
            min_impact=str(b.get("min_impact", "high")),
            uncertain_time_extra_minutes=int(b.get("uncertain_time_extra_minutes", 30)),
        )


@dataclass
class BlackoutDecision:
    blocked: bool
    reason: str = ""
    event: Optional[EconomicEvent] = None


class NewsBlackout:
    def __init__(self, calendar: EventCalendar, config: BlackoutConfig):
        self.calendar = calendar
        self.config = config
        self._floor = _IMPACT_ORDER.get(config.min_impact.lower(), 2)

    def _window(self, event: EconomicEvent) -> tuple[datetime, datetime]:
        extra = 0 if event.time_is_exact else self.config.uncertain_time_extra_minutes
        start = event.time_utc - timedelta(minutes=self.config.block_minutes_before + extra)
        end = event.time_utc + timedelta(minutes=self.config.block_minutes_after + extra)
        return start, end

    def check(self, now: datetime) -> BlackoutDecision:
        """Is `now` (tz-aware UTC) inside a blackout window for a qualifying event?"""
        if not self.config.enabled:
            return BlackoutDecision(False, "blackout disabled")
        # Only need to scan events near `now`; widen generously to be safe.
        span = timedelta(hours=6)
        for e in self.calendar.between(now - span, now + span):
            if _IMPACT_ORDER.get(e.impact.lower(), 0) < self._floor:
                continue
            start, end = self._window(e)
            if start <= now <= end:
                exact = "exact" if e.time_is_exact else "CONVENTIONAL time (window widened)"
                reason = (f"news blackout: {e.country} {e.title} at "
                          f"{e.time_utc:%Y-%m-%d %H:%M}Z [{exact}] "
                          f"window {start:%H:%M}-{end:%H:%M}Z")
                return BlackoutDecision(True, reason, e)
        return BlackoutDecision(False, "no qualifying event in window")
