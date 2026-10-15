"""Look-ahead bias is the classic way to fool yourself into a 'profitable' backtest.
We test it two ways:
  1. Signal generation is CAUSAL: changing a FUTURE bar cannot change a PAST signal.
  2. The engine EXECUTES at the next bar's OPEN, never at the signal bar's close.
"""
import numpy as np

from fxlab.backtest.costs import CostModel
from fxlab.backtest.engine import Backtester
from fxlab.config import load_yaml
from fxlab.strategy.base import StrategySpec
from fxlab.strategy.eurusd_trend import EurUsdTrendStrategy
from fxlab.types import Side


def _strategy():
    spec = StrategySpec.from_config(load_yaml("strategy_eurusd_trend.yaml"))
    return EurUsdTrendStrategy(spec)


def _trending_series():
    flat = [1.1000] * 70
    ramp = [1.1000 + 0.0004 * i for i in range(1, 80)]
    return flat + ramp


def test_future_bars_do_not_change_past_signals(sample_data_factory):
    closes = _trending_series()
    data = sample_data_factory(closes)
    strat = _strategy()
    sig_full = strat.generate(data)

    # Corrupt the LAST 5 bars drastically, regenerate, compare the earlier portion.
    corrupted = closes.copy()
    for k in range(1, 6):
        corrupted[-k] = 5.0  # absurd value in the future
    data2 = sample_data_factory(corrupted)
    sig_corrupt = strat.generate(data2)

    cutoff = len(closes) - 6
    earlier_full = sig_full["signal"].to_numpy()[:cutoff]
    earlier_corrupt = sig_corrupt["signal"].to_numpy()[:cutoff]
    assert np.array_equal(earlier_full, earlier_corrupt), \
        "A future bar changed a past signal => look-ahead bias!"


def test_entry_executes_at_next_bar_open_not_signal_close(sample_data_factory):
    closes = _trending_series()
    data = sample_data_factory(closes)
    strat = _strategy()
    # session disabled so the test is purely about timing
    strat.spec.raw["session"]["enabled"] = False

    cost = CostModel.from_config(load_yaml("backtest.yaml"), pip_size=0.0001)
    bt = Backtester(strat, cost, starting_equity=10_000, risk_per_trade_pct=0.5,
                    max_risk_pct=1.0, use_session=False, time_stop_bars=0)
    res = bt.run(data)
    assert len(res.trades) >= 1, "expected at least one trade on a trending series"

    t = res.trades[0]
    df = data.df
    # entry fill price must equal the OPEN of the execution bar (+ costs), not any close
    exec_open = float(df.loc[t.entry_time, "open"])
    expected_fill = exec_open + (cost.half_spread_price + cost.slippage_price) \
        if t.side == Side.LONG else exec_open - (cost.half_spread_price + cost.slippage_price)
    assert abs(t.entry_price - expected_fill) < 1e-6, \
        "entry price does not match next-bar OPEN execution"
