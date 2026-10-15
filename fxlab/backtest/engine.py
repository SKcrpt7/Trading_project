"""Event-driven backtester.

Core anti-look-ahead rule enforced here:
    A signal is computed on bar i (using only data <= i) and is EXECUTED at the
    OPEN of bar i+1. The engine never peeks at bar i+1's close to decide bar i.

Exit priority within a bar:
    1. Signal-based exit (opposite signal / time stop) fills at this bar's OPEN.
    2. Otherwise, intrabar stop/target. If BOTH are inside the bar's range we
       assume the STOP filled first (pessimistic - we cannot see tick order).
    The entry bar counts too: a trade filled at a bar's open is checked against
    that same bar's high/low, because that price action happens after the fill.

The paper runner follows this exact order; tests/test_parity.py proves the two
produce identical trades on the same data.

All fills cross the spread and (for market/stop fills) pay slippage. See costs.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from fxlab.backtest.costs import CostModel
from fxlab.data.interface import PriceData
from fxlab.risk.sizing import position_size
from fxlab.strategy.base import Strategy
from fxlab.types import Side, Trade


def count_rollovers(entry: datetime, exit: datetime, rollover_hour: int) -> int:
    """Number of daily rollover moments strictly between entry and exit (UTC)."""
    if exit <= entry:
        return 0
    nights = 0
    cur = entry.replace(minute=0, second=0, microsecond=0)
    # step hour by hour is fine for H1-scale backtests; cheap and unambiguous
    cur = cur + pd.Timedelta(hours=1)
    while cur <= exit:
        if cur.hour == rollover_hour:
            nights += 1
        cur = cur + pd.Timedelta(hours=1)
    return nights


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    timeframe: str
    source: str
    trades: list[Trade]
    equity_curve: pd.Series            # indexed by exit time, realized equity
    starting_equity: float
    assumptions: list[str] = field(default_factory=list)
    n_signals: int = 0
    n_blocked_news: int = 0
    n_blocked_session: int = 0
    n_blocked_risk: int = 0

    @property
    def ending_equity(self) -> float:
        return float(self.equity_curve.iloc[-1]) if len(self.equity_curve) else self.starting_equity

    def trades_dataframe(self) -> pd.DataFrame:
        rows = [t.__dict__ for t in self.trades]
        return pd.DataFrame(rows)


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        cost_model: CostModel,
        starting_equity: float,
        risk_per_trade_pct: float,
        max_risk_pct: float,
        blackout=None,                 # optional NewsBlackout
        use_session: bool = True,
        time_stop_bars: int = 0,
        exit_on_opposite_signal: bool = True,
    ):
        self.strategy = strategy
        self.cost = cost_model
        self.starting_equity = starting_equity
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_risk_pct = max_risk_pct
        self.blackout = blackout
        self.use_session = use_session
        self.time_stop_bars = time_stop_bars
        self.exit_on_opposite = exit_on_opposite_signal

    def run(self, data: PriceData) -> BacktestResult:
        df = data.df
        sig = self.strategy.generate(data)
        idx = df.index
        n = len(df)

        hs = self.cost.half_spread_price
        slip = self.cost.slippage_price

        equity = self.starting_equity
        trades: list[Trade] = []
        eq_times: list[datetime] = []
        eq_values: list[float] = []

        pos: Optional[dict] = None
        n_signals = int((sig["signal"] != 0).sum())
        n_block_news = n_block_sess = n_block_risk = 0

        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()
        signals = sig["signal"].to_numpy()
        stop_dist = sig["stop_distance"].to_numpy()
        tgt_dist = sig["target_distance"].to_numpy()
        reasons = sig["reason"].to_numpy()

        def close_trade(exit_time, raw_exit, exit_fill, exit_reason):
            nonlocal equity, pos
            direction = 1 if pos["side"] == Side.LONG else -1
            units = pos["units"]
            gross = (raw_exit - pos["raw_entry"]) * units * direction
            fill_pnl = (exit_fill - pos["entry_fill"]) * units * direction
            nights = count_rollovers(pos["entry_time"], exit_time, self.cost.rollover_hour_utc)
            swap = self.cost.swap(units, direction, nights)
            commission = self.cost.commission(units)
            net = fill_pnl + swap - commission
            costs = gross - net
            equity += net
            trades.append(Trade(
                symbol=data.symbol, side=pos["side"],
                entry_time=pos["entry_time"], exit_time=exit_time,
                entry_price=pos["entry_fill"], exit_price=exit_fill,
                quantity=units, gross_pnl=gross, costs=costs, net_pnl=net,
                bars_held=pos["bars_held"], exit_reason=exit_reason,
                mae=pos["mae"], mfe=pos["mfe"],
            ))
            eq_times.append(exit_time)
            eq_values.append(equity)
            pos = None

        def check_intrabar(ts, h, l) -> bool:
            """Intrabar stop/target check (pessimistic: stop first if both are inside
            the bar), then excursion tracking if still open. Returns True if exited."""
            direction = 1 if pos["side"] == Side.LONG else -1
            stop_px, tgt_px = pos["stop"], pos["target"]
            if direction > 0:
                stop_hit = l <= stop_px
                tgt_hit = (tgt_px is not None) and (h >= tgt_px)
            else:
                stop_hit = h >= stop_px
                tgt_hit = (tgt_px is not None) and (l <= tgt_px)

            if stop_hit:
                exit_fill = (stop_px - (hs + slip)) if direction > 0 else (stop_px + (hs + slip))
                close_trade(ts, stop_px, exit_fill, "stop")
                return True
            if tgt_hit:
                exit_fill = (tgt_px - hs) if direction > 0 else (tgt_px + hs)
                close_trade(ts, tgt_px, exit_fill, "target")
                return True

            adverse = ((l - pos["entry_fill"]) if direction > 0
                       else (pos["entry_fill"] - h)) * pos["units"]
            favour = ((h - pos["entry_fill"]) if direction > 0
                      else (pos["entry_fill"] - l)) * pos["units"]
            pos["mae"] = min(pos["mae"], adverse)
            pos["mfe"] = max(pos["mfe"], favour)
            return False

        for i in range(1, n):
            ts = idx[i]
            o, h, l = opens[i], highs[i], lows[i]

            # ---- manage existing position ----
            if pos is not None:
                pos["bars_held"] += 1
                direction = 1 if pos["side"] == Side.LONG else -1

                # 1) signal-based exit at this bar's OPEN (opposite signal / time stop)
                opp = (signals[i - 1] == -direction) and self.exit_on_opposite
                timed = self.time_stop_bars > 0 and pos["bars_held"] >= self.time_stop_bars
                if opp or timed:
                    reason = "opposite_signal" if opp else "time_stop"
                    exit_fill = o - (hs + slip) if direction > 0 else o + (hs + slip)
                    close_trade(ts, o, exit_fill, reason)
                else:
                    # 2) intrabar stop/target, 3) excursions if still open
                    check_intrabar(ts, h, l)

            # ---- consider a new entry (only if flat right now) ----
            if pos is None and signals[i - 1] != 0:
                desired = int(signals[i - 1])
                sd = float(stop_dist[i - 1])
                td = float(tgt_dist[i - 1])

                # session gate (checked at EXECUTION time)
                if self.use_session and not self.strategy.spec.in_session(ts):
                    n_block_sess += 1
                    self._record_equity_if_empty(eq_times, eq_values, ts, equity)
                    continue
                # news blackout gate
                if self.blackout is not None:
                    dec = self.blackout.check(ts.to_pydatetime())
                    if dec.blocked:
                        n_block_news += 1
                        continue
                # sizing / risk gate
                sizing = position_size(equity, self.risk_per_trade_pct, sd, self.max_risk_pct)
                if not sizing.is_tradeable:
                    n_block_risk += 1
                    continue

                side = Side.LONG if desired > 0 else Side.SHORT
                entry_fill = o + (hs + slip) if desired > 0 else o - (hs + slip)
                stop_px = entry_fill - sd if desired > 0 else entry_fill + sd
                tgt_px = (entry_fill + td if desired > 0 else entry_fill - td) if td > 0 else None
                pos = {
                    "side": side, "units": sizing.units,
                    "raw_entry": o, "entry_fill": entry_fill,
                    "stop": stop_px, "target": tgt_px,
                    "entry_time": ts, "bars_held": 0, "mae": 0.0, "mfe": 0.0,
                    "reason": str(reasons[i - 1]),
                }
                # The fill happened at the OPEN; this bar's high/low come AFTER it, so
                # the stop/target can already be hit on the entry bar. Skipping this
                # check would quietly flatter results.
                check_intrabar(ts, h, l)

        # close any open position at the last bar's close
        if pos is not None:
            direction = 1 if pos["side"] == Side.LONG else -1
            last_close = closes[-1]
            exit_fill = last_close - (hs + slip) if direction > 0 else last_close + (hs + slip)
            close_trade(idx[-1], last_close, exit_fill, "end_of_data")

        equity_curve = pd.Series(eq_values, index=pd.DatetimeIndex(eq_times), name="equity")

        assumptions = [
            "Signals execute at the next bar's OPEN (no same-bar look-ahead).",
            "When stop and target are both inside one bar, the STOP is assumed to fill first.",
            f"Spread assumed constant at {self.cost.spread_pips} pips; slippage "
            f"{self.cost.slippage_pips} pips on market/stop fills.",
            "Equity curve is realized (marked only when trades close); open-trade "
            "drawdown is captured separately via MAE, not in the equity curve.",
            "Position sizing assumes quote currency == account currency (USD).",
        ]
        if data.source.upper() == "MOCK":
            assumptions.insert(0, "*** RESULTS COMPUTED ON MOCK/SYNTHETIC DATA - NOT REAL MARKETS ***")

        return BacktestResult(
            strategy_name=self.strategy.name, symbol=data.symbol,
            timeframe=data.timeframe, source=data.source, trades=trades,
            equity_curve=equity_curve, starting_equity=self.starting_equity,
            assumptions=assumptions, n_signals=n_signals,
            n_blocked_news=n_block_news, n_blocked_session=n_block_sess,
            n_blocked_risk=n_block_risk,
        )

    @staticmethod
    def _record_equity_if_empty(times, values, ts, equity):
        # keep an initial anchor point so equity curves are never empty
        if not times:
            times.append(ts)
            values.append(equity)
