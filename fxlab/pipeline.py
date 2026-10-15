"""Assembly helpers.

One place that knows how to turn config dicts into runnable objects, so the CLI,
the review, walk-forward, and sensitivity tests all build the backtest the same
way. This prevents subtle "the review ran a different setup than the CLI" bugs.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

from fxlab.backtest.costs import CostModel
from fxlab.backtest.engine import Backtester, BacktestResult
from fxlab.data.interface import PriceData
from fxlab.econ.blackout import BlackoutConfig, NewsBlackout
from fxlab.econ.events import EventCalendar
from fxlab.strategy.base import StrategySpec
from fxlab.strategy.eurusd_trend import EurUsdTrendStrategy

# Registry so new strategies can be wired by name from config ("kind"/"name").
STRATEGY_REGISTRY = {
    "eurusd_trend_ema": EurUsdTrendStrategy,
    "trend_following": EurUsdTrendStrategy,   # default implementation for the 'kind'
}


def build_strategy(scfg: dict):
    spec = StrategySpec.from_config(scfg)
    cls = STRATEGY_REGISTRY.get(scfg.get("name")) or STRATEGY_REGISTRY.get(scfg.get("kind"))
    if cls is None:
        raise ValueError(
            f"No strategy class registered for name='{scfg.get('name')}' / "
            f"kind='{scfg.get('kind')}'. Add it to STRATEGY_REGISTRY."
        )
    return cls(spec)


def build_blackout(news_cfg: dict, sample_events_path: str | Path) -> NewsBlackout:
    cal = EventCalendar.from_config(news_cfg, sample_events_path)
    return NewsBlackout(cal, BlackoutConfig.from_config(news_cfg))


def build_strategy_blackout(
    scfg: dict, news_cfg: Optional[dict], sample_events_path: Optional[str | Path],
) -> Optional[NewsBlackout]:
    """The news blackout a strategy should trade under, or None if it opted out.
    The strategy's own news window overrides the global news config. Backtest AND
    paper both build it here, so they can never block different bars."""
    if news_cfg is None or sample_events_path is None \
            or not scfg.get("news", {}).get("blackout_enabled", False):
        return None
    merged = copy.deepcopy(news_cfg)
    merged.setdefault("blackout", {})
    sn = scfg["news"]
    merged["blackout"].update({
        "enabled": sn.get("blackout_enabled", True),
        "block_minutes_before": sn.get("block_minutes_before", 30),
        "block_minutes_after": sn.get("block_minutes_after", 30),
        "min_impact": sn.get("min_impact", "high"),
    })
    return build_blackout(merged, sample_events_path)


def run_backtest(
    data: PriceData,
    scfg: dict,
    risk_cfg: dict,
    bt_cfg: dict,
    news_cfg: Optional[dict] = None,
    sample_events_path: Optional[str | Path] = None,
    spread_mult: float = 1.0,
    slippage_mult: float = 1.0,
    use_blackout: bool = True,
) -> BacktestResult:
    strat = build_strategy(scfg)
    pip = risk_cfg["pip_size"][scfg["symbol"]]
    cost = CostModel.from_config(bt_cfg, pip, spread_mult=spread_mult, slippage_mult=slippage_mult)

    blackout = build_strategy_blackout(scfg, news_cfg, sample_events_path) if use_blackout else None

    engine = Backtester(
        strategy=strat, cost_model=cost,
        starting_equity=float(risk_cfg["account"]["starting_equity"]),
        risk_per_trade_pct=float(scfg["sizing"]["risk_per_trade_pct"]),
        max_risk_pct=float(risk_cfg["limits"]["max_risk_per_trade_pct"]),
        blackout=blackout,
        use_session=bool(scfg.get("session", {}).get("enabled", True)),
        time_stop_bars=int(scfg["exit"].get("time_stop_bars", 0)),
        exit_on_opposite_signal=bool(scfg["exit"].get("exit_on_opposite_signal", True)),
    )
    return engine.run(data)
