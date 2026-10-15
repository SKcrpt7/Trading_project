"""A rejected protective stop is an emergency. The system must: (a) report the
rejection, (b) flatten the unprotected position, and (c) stop opening new trades.
We also confirm the live-trading guard refuses to run."""
from datetime import datetime, timezone

import pytest

from fxlab.backtest.costs import CostModel
from fxlab.config import load_yaml
from fxlab.paper.sim_broker import SimBroker
from fxlab.paper.broker_interface import LIVE_TRADING_SUPPORTED
from fxlab.types import Side


def _broker():
    cost = CostModel.from_config(load_yaml("backtest.yaml"), pip_size=0.0001)
    b = SimBroker(cost, "EURUSD")
    b.connect()
    b.set_bar(datetime(2022, 6, 10, 10, 0, tzinfo=timezone.utc),
              {"open": 1.1000, "high": 1.1010, "low": 1.0990, "close": 1.1000})
    return b


def test_bracket_normally_accepts_protective_stop():
    b = _broker()
    res = b.submit_bracket("EURUSD", Side.LONG, 50_000, 1.0980, 1.1030, "oid-1")
    assert res.accepted and res.stop_accepted
    assert res.entry_fill is not None and res.entry_fill.is_simulated


def test_forced_protective_rejection_leaves_unprotected_position():
    b = _broker()
    b.force_reject_protective = True
    res = b.submit_bracket("EURUSD", Side.LONG, 50_000, 1.0980, 1.1030, "oid-2")
    assert res.accepted          # entry still filled
    assert not res.stop_accepted  # but the stop was rejected
    assert "REJECTED" in res.reject_reason
    # position exists and is flagged unprotected -> runner must flatten it
    pos = b.open_positions()
    assert len(pos) == 1 and pos[0]["unprotected"] is True


def test_flatten_closes_the_position():
    b = _broker()
    b.force_reject_protective = True
    b.submit_bracket("EURUSD", Side.LONG, 50_000, 1.0980, 1.1030, "oid-3")
    fill = b.flatten("EURUSD", "protective_stop_rejected")
    assert fill is not None and fill.is_simulated
    assert b.open_positions() == []


def test_live_trading_is_disabled():
    assert LIVE_TRADING_SUPPORTED is False


def test_runner_latch_blocks_after_protective_failure():
    """End-to-end: inject a protective failure and confirm NO further entries."""
    from fxlab.audit.store import AuditStore
    from fxlab.pipeline import build_strategy
    from fxlab.paper.runner import PaperRunner
    from fxlab.risk.manager import RiskConfig
    from fxlab.data.interface import CsvPriceProvider
    from fxlab.config import PROJECT_ROOT

    scfg = load_yaml("strategy_eurusd_trend.yaml")
    data = CsvPriceProvider(PROJECT_ROOT / "data" / "sample" / "EURUSD_H1_sample.csv") \
        .load(scfg["symbol"], scfg["timeframe"])
    _, evl = data.split_chronological(0.7)

    cost = CostModel.from_config(load_yaml("backtest.yaml"), 0.0001)
    audit = AuditStore(":memory:")
    runner = PaperRunner(
        strategy=build_strategy(scfg), cost_model=cost,
        risk_config=RiskConfig.from_config(load_yaml("risk.yaml")), audit=audit,
        use_session=True, time_stop_bars=scfg["exit"]["time_stop_bars"],
        inject_protective_failure_at=1,  # fail the very first entry attempt
    )
    res = runner.run(evl)
    assert res.counts["protective_failures"] == 1
    assert res.entries_blocked_latched is True
    assert res.counts["entries"] == 0  # no successful entries after the latch
    audit.close()
