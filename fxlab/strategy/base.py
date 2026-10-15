"""Strategy base class and specification.

A Strategy turns bars into *intents*: for each closed bar it says whether it
wants to be long, short, or flat, and how far away the protective stop and the
target should sit. It never decides position SIZE (that is the risk manager's
job) and it never executes (that is the engine's / broker's job). This strict
separation is what lets the same strategy run in a backtest and in paper trading.

Anti-look-ahead contract: generate() must fill row i using ONLY data up to and
including bar i. The engine will act on that intent no earlier than bar i+1.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import time
from typing import Any

import pandas as pd

from fxlab.data.interface import PriceData


@dataclass
class StrategySpec:
    """Parsed, typed view of a strategy YAML config."""
    name: str
    version: str
    kind: str
    symbol: str
    timeframe: str
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "StrategySpec":
        return cls(
            name=cfg["name"], version=str(cfg.get("version", "0")),
            kind=cfg.get("kind", "unknown"),
            symbol=cfg["symbol"], timeframe=cfg["timeframe"], raw=cfg,
        )

    # --- session helpers ---
    @property
    def session_enabled(self) -> bool:
        return bool(self.raw.get("session", {}).get("enabled", False))

    def _session_bounds(self) -> tuple[time, time]:
        s = self.raw["session"]
        sh, sm = map(int, s["start_utc"].split(":"))
        eh, em = map(int, s["end_utc"].split(":"))
        return time(sh, sm), time(eh, em)

    @property
    def session_days(self) -> set[str]:
        return set(self.raw.get("session", {}).get("trade_days",
                   ["Mon", "Tue", "Wed", "Thu", "Fri"]))

    def in_session(self, ts: pd.Timestamp) -> bool:
        """ts must be tz-aware UTC."""
        if not self.session_enabled:
            return True
        day = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][ts.weekday()]
        if day not in self.session_days:
            return False
        start, end = self._session_bounds()
        return start <= ts.timetz().replace(tzinfo=None) <= end


class Strategy(ABC):
    def __init__(self, spec: StrategySpec):
        self.spec = spec

    @property
    def name(self) -> str:
        return self.spec.name

    @abstractmethod
    def generate(self, data: PriceData) -> pd.DataFrame:
        """Return a DataFrame indexed exactly like data.df with columns:
            signal         : int   (+1 long, -1 short, 0 flat/no-action)
            stop_distance  : float (price distance from entry to protective stop; >0)
            target_distance: float (price distance from entry to target; >0 or NaN)
            reason         : str   (human-readable justification for the audit log)
        The engine executes a non-zero signal on the NEXT bar's open.
        """
        ...
