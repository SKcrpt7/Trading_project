"""Robustness checks: walk-forward, parameter sensitivity, and cost stress.

A single backtest number is easy to fool yourself with. These checks ask three
harder questions:
  * Walk-forward : does it hold up across many out-of-sample windows, or did one
                   lucky period carry the whole result?
  * Sensitivity  : if I nudge a parameter slightly, does performance collapse?
                   (A result that only works at one exact setting is suspicious.)
  * Cost stress  : does it survive materially worse trading costs?

NOTE on this example: the EUR/USD example uses FIXED parameters (no optimization),
so walk-forward here measures OUT-OF-SAMPLE STABILITY rather than re-fitting. A
strategy that DID optimize would re-fit on each train window. This limitation is
stated in the report so the walk-forward result is not over-interpreted.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from fxlab.backtest import metrics
from fxlab.data.interface import PriceData
from fxlab.pipeline import run_backtest


@dataclass
class WindowResult:
    index: int
    start: str
    end: str
    trades: int
    net_return_pct: float
    profit_factor: float


@dataclass
class WalkForwardReport:
    windows: list[WindowResult] = field(default_factory=list)

    @property
    def positive_fraction(self) -> float:
        if not self.windows:
            return 0.0
        pos = sum(1 for w in self.windows if w.net_return_pct > 0)
        return round(pos / len(self.windows), 3)


def walk_forward(data: PriceData, scfg, risk_cfg, bt_cfg) -> WalkForwardReport:
    wf = bt_cfg["evaluation"]["walk_forward"]
    if not wf.get("enabled", False):
        return WalkForwardReport()
    train = int(wf["train_bars"])
    test = int(wf["test_bars"])
    step = int(wf["step_bars"])
    df = data.df
    n = len(df)

    report = WalkForwardReport()
    idx = 0
    start_pos = train
    while start_pos + test <= n:
        window_df = df.iloc[start_pos:start_pos + test]
        wdata = PriceData(data.symbol, data.timeframe, data.source, window_df.copy(),
                          data.timezone, data.has_bid_ask)
        res = run_backtest(wdata, scfg, risk_cfg, bt_cfg, use_blackout=False)
        m = metrics.compute(res)
        report.windows.append(WindowResult(
            index=idx, start=str(window_df.index[0]), end=str(window_df.index[-1]),
            trades=m.trade_count, net_return_pct=m.net_return_pct,
            profit_factor=(m.profit_factor if m.profit_factor != float("inf") else 999.0),
        ))
        idx += 1
        start_pos += step
    return report


@dataclass
class SensitivityRow:
    param: str
    change_pct: float
    value: float
    trades: int
    net_return_pct: float
    profit_factor: float


def _set_param(scfg: dict, param: str, value):
    """Place a parameter into the right config sub-section."""
    for section in ("entry", "exit", "sizing"):
        if param in scfg.get(section, {}):
            scfg[section][param] = value
            return
    raise KeyError(f"Parameter '{param}' not found in entry/exit/sizing config.")


def _get_param(scfg: dict, param: str):
    for section in ("entry", "exit", "sizing"):
        if param in scfg.get(section, {}):
            return scfg[section][param]
    raise KeyError(f"Parameter '{param}' not found.")


def sensitivity(data: PriceData, scfg, risk_cfg, bt_cfg) -> list[SensitivityRow]:
    s = bt_cfg["evaluation"]["sensitivity"]
    if not s.get("enabled", False):
        return []
    rows: list[SensitivityRow] = []
    for param in s["params"]:
        base = _get_param(scfg, param)
        is_int = isinstance(base, int)
        for pct in s["pct_steps"]:
            trial = copy.deepcopy(scfg)
            new_val = base * (1 + pct)
            new_val = int(round(new_val)) if is_int else round(new_val, 4)
            if new_val == base or new_val <= 0:
                continue
            _set_param(trial, param, new_val)
            res = run_backtest(data, trial, risk_cfg, bt_cfg, use_blackout=False)
            m = metrics.compute(res)
            rows.append(SensitivityRow(
                param=param, change_pct=round(pct * 100, 1), value=new_val,
                trades=m.trade_count, net_return_pct=m.net_return_pct,
                profit_factor=(m.profit_factor if m.profit_factor != float("inf") else 999.0),
            ))
    return rows


def cost_stress(data: PriceData, scfg, risk_cfg, bt_cfg):
    cs = bt_cfg["evaluation"]["cost_stress"]
    if not cs.get("enabled", False):
        return None
    res = run_backtest(
        data, scfg, risk_cfg, bt_cfg, use_blackout=False,
        spread_mult=float(cs.get("spread_multiplier", 2.0)),
        slippage_mult=float(cs.get("slippage_multiplier", 2.0)),
    )
    return metrics.compute(res)
