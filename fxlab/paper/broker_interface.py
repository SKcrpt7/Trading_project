"""Broker interface - the seam for paper now, and a real broker (MT5 / QC / etc.) later.

This file defines the contract every execution backend must satisfy. Today only
the SimBroker implements it. A future MetaTrader 5 or broker adapter would
implement the SAME methods, so the paper runner and risk manager would not change.

LIVE TRADING BOUNDARY
---------------------
LIVE_TRADING_SUPPORTED is False and this module NEVER sends real orders. Even if a
subclass claimed live support, `assert_not_live()` is the single checkpoint the
runner calls before trading; it raises unless the backend is a simulator. See
docs/live_trading_boundary.md for exactly what a future live connection requires.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from fxlab.types import Fill, Side

# Hard global switch. This project is paper/simulation only. Do not flip this
# without implementing, testing, and separately authorizing a real broker adapter.
LIVE_TRADING_SUPPORTED = False


@dataclass
class Quote:
    time: datetime
    symbol: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pips_for(self) -> float:
        # caller supplies pip size; kept simple here
        return self.ask - self.bid


@dataclass
class BracketResult:
    """Outcome of submitting an entry together with its protective stop and target."""
    accepted: bool
    entry_fill: Optional[Fill] = None
    stop_accepted: bool = False
    target_accepted: bool = False
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    reject_reason: str = ""
    client_order_id: str = ""
    extra: dict = field(default_factory=dict)


class BrokerInterface(ABC):
    is_simulated: bool = True

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def submit_bracket(
        self, symbol: str, side: Side, quantity: float,
        stop_price: float, target_price: Optional[float], client_order_id: str,
    ) -> BracketResult:
        """Submit a market entry together with a protective stop and optional target.
        A real broker may reject the protective stop even if the entry fills; the
        runner MUST treat that as an emergency (close/flatten + block entries)."""
        ...

    @abstractmethod
    def open_positions(self) -> list[dict]: ...

    @abstractmethod
    def flatten(self, symbol: str, reason: str) -> Optional[Fill]:
        """Market-close the position now: signal-based exits (opposite signal, time
        stop), end of data, and emergencies (e.g. after a rejected protective stop)."""
        ...

    def assert_not_live(self) -> None:
        """The single live-trading checkpoint. Raises unless this is a simulator."""
        if not self.is_simulated or LIVE_TRADING_SUPPORTED:
            raise RuntimeError(
                "Live trading is disabled in this project. Refusing to proceed. "
                "See docs/live_trading_boundary.md."
            )
