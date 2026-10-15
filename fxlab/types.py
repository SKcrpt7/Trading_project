"""Shared data models used across the whole system.

Keeping these in one place means a signal looks the same whether it was produced
by the local engine, the paper simulator, or (one day) a real broker adapter.
Every field is explicit so there is no hidden state behind a trading decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderType(str, Enum):
    MARKET = "MARKET"
    STOP = "STOP"          # protective stop-loss
    LIMIT = "LIMIT"        # take-profit target


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Decision(str, Enum):
    """The three allowed outcomes of a strategy review. Note what is NOT here:
    there is deliberately no 'eligible for LIVE trading' outcome."""
    REJECT = "REJECT"
    NEEDS_INVESTIGATION = "NEEDS_INVESTIGATION"
    ELIGIBLE_FOR_PAPER = "ELIGIBLE_FOR_PAPER"


@dataclass
class Signal:
    """A strategy's intent at a point in time. A signal is NOT an order - the
    risk manager must approve it and attach protective orders first."""
    timestamp: datetime            # UTC, the bar that PRODUCED the signal (already closed)
    symbol: str
    side: Side
    reason: str                    # human-readable 'why', for the audit log
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    reference_price: Optional[float] = None   # price the rule was evaluated against
    meta: dict = field(default_factory=dict)


@dataclass
class Order:
    timestamp: datetime
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float                # in units of base currency (e.g. EUR for EUR/USD)
    price: Optional[float] = None  # for STOP/LIMIT; None for MARKET
    status: OrderStatus = OrderStatus.PENDING
    client_order_id: str = ""      # used for duplicate-order prevention
    parent_signal_reason: str = ""


@dataclass
class Fill:
    timestamp: datetime
    symbol: str
    side: Side
    quantity: float
    price: float                   # the price actually transacted (after slippage)
    commission: float = 0.0
    is_simulated: bool = True      # ALWAYS true in this project - no live fills
    order_client_id: str = ""


@dataclass
class Trade:
    """A completed round-trip (entry + exit), the unit of performance analysis."""
    symbol: str
    side: Side
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float               # before costs, in account currency
    costs: float                   # spread + commission + slippage + swap
    net_pnl: float                 # gross_pnl - costs
    bars_held: int
    exit_reason: str               # 'stop', 'target', 'signal', 'session_close', 'end_of_data'
    mae: float = 0.0               # maximum adverse excursion (account ccy)
    mfe: float = 0.0               # maximum favourable excursion (account ccy)


@dataclass
class EconomicEvent:
    """A scheduled economic release. time_utc is when it becomes public.
    time_is_exact distinguishes a verified timestamp from a conventional one."""
    time_utc: datetime
    country: str
    title: str
    impact: str                    # 'high', 'medium', 'low'
    source: str                    # provenance, e.g. 'FRED', 'conventional_schedule', 'sample'
    time_is_exact: bool = False    # False => release TIME is conventional, only the DATE is official
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None
