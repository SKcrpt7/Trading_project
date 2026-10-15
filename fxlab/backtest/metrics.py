"""Performance metrics.

Each metric is paired with a short note on what it CANNOT tell you, because the
most dangerous number is one you trust blindly. None of these metrics predict
the future; they only describe the sample you tested on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


METRIC_LIMITATIONS = {
    "trade_count": "Few trades = high luck component. Dozens is not statistically strong.",
    "net_return_pct": "Path-dependent and sample-specific; says nothing about the future.",
    "max_drawdown_pct": "Realized worst peak-to-trough on THIS sample; the future can be worse.",
    "profit_factor": "Sensitive to a few big wins; can look great on a tiny, lucky sample.",
    "avg_pnl_per_trade": "An average hides the distribution; check the losing streaks too.",
    "win_rate_pct": "A high win rate with large losers can still lose money overall.",
    "max_losing_streak": "Backtest streaks are a floor, not a ceiling, for live psychology.",
    "expectancy": "Depends on reward:risk staying stable; regimes change.",
    "sharpe_like": "Per-trade, not annualized; assumes returns are comparable across time.",
}


@dataclass
class Metrics:
    trade_count: int
    net_pnl: float
    net_return_pct: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    win_rate_pct: float
    avg_pnl_per_trade: float
    avg_win: float
    avg_loss: float
    expectancy: float
    max_drawdown_pct: float
    max_losing_streak: int
    max_winning_streak: int
    total_costs: float
    sharpe_like: float
    by_year: dict = field(default_factory=dict)
    by_session: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        return d


def _max_drawdown_pct(equity: pd.Series, starting_equity: float) -> float:
    if len(equity) == 0:
        return 0.0
    curve = pd.concat([pd.Series([starting_equity]), equity.reset_index(drop=True)])
    running_max = curve.cummax()
    drawdown = (curve - running_max) / running_max
    return float(abs(drawdown.min()) * 100.0)


def _streaks(pnls: list[float]) -> tuple[int, int]:
    max_loss = max_win = cur_loss = cur_win = 0
    for p in pnls:
        if p < 0:
            cur_loss += 1
            cur_win = 0
        elif p > 0:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss = cur_win = 0
        max_loss = max(max_loss, cur_loss)
        max_win = max(max_win, cur_win)
    return max_loss, max_win


def _session_bucket(hour_utc: int) -> str:
    # rough FX sessions in UTC
    if 0 <= hour_utc < 7:
        return "Asia"
    if 7 <= hour_utc < 12:
        return "London"
    if 12 <= hour_utc < 16:
        return "London/NY overlap"
    if 16 <= hour_utc < 21:
        return "New York"
    return "Late/Off"


def compute(result) -> Metrics:
    """result: BacktestResult"""
    trades = result.trades
    start_eq = result.starting_equity
    net_pnls = [t.net_pnl for t in trades]
    n = len(trades)

    net_pnl = float(sum(net_pnls))
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p < 0]
    gross_profit = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    win_rate = (100.0 * len(wins) / n) if n else 0.0
    avg_pnl = (net_pnl / n) if n else 0.0
    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (-gross_loss / len(losses)) if losses else 0.0
    expectancy = avg_pnl
    max_dd = _max_drawdown_pct(result.equity_curve, start_eq)
    max_loss_streak, max_win_streak = _streaks(net_pnls)
    total_costs = float(sum(t.costs for t in trades))

    arr = np.array(net_pnls, dtype=float)
    sharpe_like = float(arr.mean() / arr.std()) if n > 1 and arr.std() > 0 else 0.0

    # by year / by session (entry time based)
    by_year: dict = {}
    by_session: dict = {}
    for t in trades:
        y = t.entry_time.year
        by_year.setdefault(y, {"trades": 0, "net_pnl": 0.0})
        by_year[y]["trades"] += 1
        by_year[y]["net_pnl"] += t.net_pnl

        s = _session_bucket(t.entry_time.hour)
        by_session.setdefault(s, {"trades": 0, "net_pnl": 0.0})
        by_session[s]["trades"] += 1
        by_session[s]["net_pnl"] += t.net_pnl

    for d in (*by_year.values(), *by_session.values()):
        d["net_pnl"] = round(float(d["net_pnl"]), 2)

    return Metrics(
        trade_count=n, net_pnl=round(net_pnl, 2),
        net_return_pct=round(100.0 * net_pnl / start_eq, 2) if start_eq else 0.0,
        gross_profit=round(gross_profit, 2), gross_loss=round(gross_loss, 2),
        profit_factor=round(profit_factor, 3) if profit_factor != float("inf") else float("inf"),
        win_rate_pct=round(win_rate, 2), avg_pnl_per_trade=round(avg_pnl, 2),
        avg_win=round(avg_win, 2), avg_loss=round(avg_loss, 2),
        expectancy=round(expectancy, 2), max_drawdown_pct=round(max_dd, 2),
        max_losing_streak=max_loss_streak, max_winning_streak=max_win_streak,
        total_costs=round(total_costs, 2), sharpe_like=round(sharpe_like, 3),
        by_year=dict(sorted(by_year.items())), by_session=by_session,
    )
