"""Backtest <-> paper parity.

The paper runner exists to show how a strategy behaves "forward", and its report
compares itself to the backtest. That comparison is only meaningful if the two
engines agree when nothing extra (kill switch, daily-loss halt, ...) intervenes.
A past bug - the paper runner silently ignored opposite-signal and time-stop
exits - went unnoticed because nothing checked this. These tests do.
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from fxlab.audit.store import AuditStore
from fxlab.backtest.costs import CostModel
from fxlab.backtest.engine import Backtester
from fxlab.config import PROJECT_ROOT, load_yaml
from fxlab.data.interface import CsvPriceProvider
from fxlab.paper.runner import PaperRunner
from fxlab.pipeline import build_strategy, build_strategy_blackout, run_backtest
from fxlab.risk.manager import RiskConfig
from fxlab.types import Side

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


def _cost():
    return CostModel.from_config(load_yaml("backtest.yaml"), pip_size=0.0001)


def _trade_key(t):
    return (t.entry_time, t.exit_time, t.side, t.exit_reason,
            round(t.entry_price, 6), round(t.exit_price, 6))


# The sim broker rounds fill prices to 6 decimals (like real broker quotes); the
# backtester does not. That moves P&L by a fraction of a cent per trade - real but
# immaterial - so P&L is compared to the cent rather than exactly.
PNL_TOL = 0.01


def _paper(strategy, data, blackout=None, use_session=False, time_stop_bars=0,
           exit_on_opposite_signal=True, inject_failure_at=None):
    audit = AuditStore(":memory:")
    runner = PaperRunner(
        strategy=strategy, cost_model=_cost(),
        risk_config=RiskConfig.from_config(load_yaml("risk.yaml")), audit=audit,
        blackout=blackout, use_session=use_session, time_stop_bars=time_stop_bars,
        exit_on_opposite_signal=exit_on_opposite_signal,
        inject_protective_failure_at=inject_failure_at,
    )
    res = runner.run(data)
    audit.close()
    return res


class FixedSignalStrategy:
    """Test stub: emits exactly the signals it is given (no indicators), so a test
    can place an entry on a precise bar."""
    name = "fixed_signal_stub"

    def __init__(self, signals, stop_distance, target_distance):
        self._sig = signals
        self._sd, self._td = stop_distance, target_distance
        self.spec = SimpleNamespace(raw={"sizing": {"risk_per_trade_pct": 0.5}},
                                    in_session=lambda ts: True)

    def generate(self, data):
        n = len(data.df)
        sig = np.zeros(n, dtype=int)
        sig[:len(self._sig)] = self._sig
        return pd.DataFrame({"signal": sig, "stop_distance": self._sd,
                             "target_distance": self._td, "reason": "stub"},
                            index=data.df.index)


def test_backtest_and_paper_produce_identical_trades():
    """Real strategy, real config, sample hold-out slice: trade-for-trade identical."""
    scfg = load_yaml("strategy_eurusd_trend.yaml")
    risk_cfg, bt_cfg, news_cfg = load_yaml("risk.yaml"), load_yaml("backtest.yaml"), load_yaml("news.yaml")
    events = SAMPLE_DIR / "economic_events_sample.csv"
    data = CsvPriceProvider(SAMPLE_DIR / "EURUSD_H1_sample.csv").load(scfg["symbol"], scfg["timeframe"])
    _, hold = data.split_chronological(bt_cfg["evaluation"]["dev_fraction"])

    bt = run_backtest(hold, scfg, risk_cfg, bt_cfg, news_cfg, events)
    paper = _paper(build_strategy(scfg), hold,
                   blackout=build_strategy_blackout(scfg, news_cfg, events),
                   use_session=scfg["session"]["enabled"],
                   time_stop_bars=scfg["exit"]["time_stop_bars"],
                   exit_on_opposite_signal=scfg["exit"]["exit_on_opposite_signal"])

    # guard against a vacuous pass: the slice must exercise every exit type
    reasons = {t.exit_reason for t in bt.trades}
    assert {"opposite_signal", "time_stop", "stop", "target"} <= reasons, reasons

    assert [_trade_key(t) for t in paper.trades] == [_trade_key(t) for t in bt.trades]
    for p, b in zip(paper.trades, bt.trades):
        assert p.net_pnl == pytest.approx(b.net_pnl, abs=PNL_TOL)
    assert paper.ending_equity == pytest.approx(bt.ending_equity, abs=PNL_TOL * len(bt.trades))


@pytest.mark.parametrize("engine", ["backtest", "paper"])
def test_stop_is_checked_on_the_entry_bar(sample_data_factory, engine):
    """Long signal on bar 0 -> entry at bar 1's open. Bar 1 then trades down
    through the stop. The trade must be stopped out ON bar 1, not survive it."""
    closes = [1.1000, 1.0985, 1.0990, 1.0995, 1.1000]
    lows = [1.0995, 1.0980, 1.0985, 1.0990, 1.0995]   # bar 1 low pierces the stop
    data = sample_data_factory(closes, lows=lows, opens=[1.1000] * 5)
    strat = FixedSignalStrategy([1], stop_distance=0.0010, target_distance=0.0030)

    if engine == "backtest":
        trades = Backtester(strat, _cost(), starting_equity=10_000, risk_per_trade_pct=0.5,
                            max_risk_pct=1.0, use_session=False).run(data).trades
    else:
        trades = _paper(strat, data).trades

    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "stop"
    assert t.entry_time == t.exit_time == data.df.index[1]


def test_emergency_flatten_is_booked_and_priced_at_the_open(sample_data_factory):
    """A rejected protective stop forces an immediate close. That close happens at
    the entry bar's OPEN (not its close, which hasn't happened yet) and its cost
    must reduce equity."""
    cost = _cost()
    # bar 1 opens at 1.1000 then rallies hard: pricing the flatten off the CLOSE
    # would show a fake profit
    data = sample_data_factory([1.1000, 1.1050, 1.1050, 1.1050], opens=[1.1000] * 4,
                               highs=[1.1005, 1.1055, 1.1055, 1.1055])
    strat = FixedSignalStrategy([1], stop_distance=0.0010, target_distance=0.0100)

    res = _paper(strat, data, inject_failure_at=1)

    assert res.counts["protective_failures"] == 1 and res.entries_blocked_latched
    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.exit_reason == "protective_stop_rejected"
    open_px = float(data.df["open"].iloc[1])
    assert t.exit_price == pytest.approx(open_px - (cost.half_spread_price + cost.slippage_price))
    assert t.net_pnl < 0
    assert res.ending_equity == pytest.approx(res.starting_equity + t.net_pnl)


def test_paper_honours_signal_based_exits(sample_data_factory):
    """Long on bar 0, opposite (short) signal on bar 2 -> the long must close at
    bar 3's open with reason 'opposite_signal' (then reverse into the short)."""
    closes = [1.1000] * 8
    data = sample_data_factory(closes)
    strat = FixedSignalStrategy([1, 0, -1], stop_distance=0.0050, target_distance=0.0100)

    trades = _paper(strat, data).trades
    assert trades[0].side == Side.LONG
    assert trades[0].exit_reason == "opposite_signal"
    assert trades[0].exit_time == data.df.index[3]
    assert trades[1].side == Side.SHORT and trades[1].entry_time == data.df.index[3]

    timed = _paper(FixedSignalStrategy([1], 0.0050, 0.0100), data, time_stop_bars=3).trades
    assert timed[0].exit_reason == "time_stop"
    assert timed[0].exit_time == data.df.index[1 + 3]
