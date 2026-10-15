"""Risk manager - the gatekeeper between a strategy signal and a real order.

Every entry must pass EVERY check here. The checks are intentionally boring and
explicit; boring is what keeps an account alive. The manager is stateful (it
tracks daily P&L, open positions, and recently submitted orders) and is used by
the paper runner. Backtests use the same sizing math via position_size().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fxlab.config import PROJECT_ROOT
from fxlab.risk.sizing import SizingResult, position_size


@dataclass
class RiskConfig:
    starting_equity: float
    currency: str
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_open_positions: int
    max_position_risk_pct: float
    max_spread_pips: float
    stale_data_seconds: int
    require_protective_stop: bool
    require_take_profit: bool
    kill_switch_file: str
    pip_size: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict) -> "RiskConfig":
        acct, lim, ctl = cfg["account"], cfg["limits"], cfg["controls"]
        return cls(
            starting_equity=float(acct["starting_equity"]),
            currency=str(acct["currency"]),
            max_risk_per_trade_pct=float(lim["max_risk_per_trade_pct"]),
            max_daily_loss_pct=float(lim["max_daily_loss_pct"]),
            max_open_positions=int(lim["max_open_positions"]),
            max_position_risk_pct=float(lim["max_position_risk_pct"]),
            max_spread_pips=float(lim["max_spread_pips"]),
            stale_data_seconds=int(lim["stale_data_seconds"]),
            require_protective_stop=bool(ctl["require_protective_stop"]),
            require_take_profit=bool(ctl.get("require_take_profit", False)),
            kill_switch_file=str(ctl.get("kill_switch_file", "KILL_SWITCH")),
            pip_size=cfg.get("pip_size", {}),
        )


@dataclass
class RiskCheck:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    sizing: Optional[SizingResult] = None

    @property
    def rejection_summary(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "approved"


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self.equity = config.starting_equity
        self._day: Optional[date] = None
        self._day_start_equity = config.starting_equity
        self._realized_today = 0.0
        self.open_positions = 0
        self._halted_today = False
        self._recent_order_ids: set[str] = set()
        self.entries_blocked = False       # latched block after a protective-order failure
        self.block_reason = ""

    # ---------- daily roll ----------
    def _roll_day(self, now: datetime) -> None:
        d = now.date()
        if self._day != d:
            self._day = d
            self._day_start_equity = self.equity
            self._realized_today = 0.0
            self._halted_today = False

    # ---------- kill switch ----------
    def kill_switch_active(self) -> bool:
        return (PROJECT_ROOT / self.config.kill_switch_file).exists()

    # ---------- state updates ----------
    def register_fill_pnl(self, net_pnl: float) -> None:
        """Call when a position closes; updates equity and daily P&L."""
        self.equity += net_pnl
        self._realized_today += net_pnl

    def block_entries(self, reason: str) -> None:
        """Latch a hard stop on new entries (e.g. a protective order was rejected)."""
        self.entries_blocked = True
        self.block_reason = reason

    @property
    def daily_loss_pct(self) -> float:
        if self._day_start_equity <= 0:
            return 0.0
        return 100.0 * (self._day_start_equity - self.equity) / self._day_start_equity

    def daily_loss_breached(self) -> bool:
        return self.daily_loss_pct >= self.config.max_daily_loss_pct

    # ---------- the gate ----------
    def pre_trade_check(
        self,
        now: datetime,
        symbol: str,
        risk_pct: float,
        stop_distance: float,
        has_stop: bool,
        has_target: bool,
        spread_pips: Optional[float],
        data_age_seconds: Optional[float],
        client_order_id: str,
    ) -> RiskCheck:
        self._roll_day(now)
        reasons: list[str] = []

        if self.kill_switch_active():
            reasons.append(f"KILL SWITCH active (file '{self.config.kill_switch_file}' present)")
        if self.entries_blocked:
            reasons.append(f"entries latched-blocked: {self.block_reason}")
        if self._halted_today or self.daily_loss_breached():
            self._halted_today = True
            reasons.append(f"max daily loss reached ({self.daily_loss_pct:.2f}% >= "
                           f"{self.config.max_daily_loss_pct}%)")
        if self.open_positions >= self.config.max_open_positions:
            reasons.append(f"max open positions reached ({self.open_positions}/"
                           f"{self.config.max_open_positions})")
        if self.config.require_protective_stop and not has_stop:
            reasons.append("no protective stop attached (required)")
        if self.config.require_take_profit and not has_target:
            reasons.append("no take-profit attached (required)")
        if spread_pips is not None and spread_pips > self.config.max_spread_pips:
            reasons.append(f"spread too wide ({spread_pips:.2f} > "
                           f"{self.config.max_spread_pips} pips)")
        if data_age_seconds is not None and data_age_seconds > self.config.stale_data_seconds:
            reasons.append(f"market data is stale ({data_age_seconds:.0f}s > "
                           f"{self.config.stale_data_seconds}s)")
        if client_order_id and client_order_id in self._recent_order_ids:
            reasons.append(f"duplicate order id '{client_order_id}' (already submitted)")

        sizing = position_size(
            equity=self.equity, risk_pct=risk_pct, stop_distance=stop_distance,
            max_risk_pct=min(self.config.max_risk_per_trade_pct,
                             self.config.max_position_risk_pct),
        )
        if not sizing.is_tradeable:
            reasons.append(f"sizing not tradeable ({sizing.capped_reason})")

        approved = len(reasons) == 0
        if approved and client_order_id:
            self._recent_order_ids.add(client_order_id)
        return RiskCheck(approved=approved, reasons=reasons, sizing=sizing)
