"""Risk limits are hard gates. Each test proves one gate actually blocks."""
from datetime import datetime, timezone, timedelta

import pytest

from fxlab.config import PROJECT_ROOT, load_yaml
from fxlab.risk.manager import RiskConfig, RiskManager


@pytest.fixture
def rm():
    return RiskManager(RiskConfig.from_config(load_yaml("risk.yaml")))


def _args(**overrides):
    base = dict(
        now=datetime(2022, 6, 10, 10, 0, tzinfo=timezone.utc), symbol="EURUSD",
        risk_pct=0.5, stop_distance=0.0020, has_stop=True, has_target=True,
        spread_pips=1.0, data_age_seconds=1.0, client_order_id="id-1",
    )
    base.update(overrides)
    return base


def test_happy_path_is_approved(rm):
    assert rm.pre_trade_check(**_args()).approved


def test_missing_protective_stop_blocks(rm):
    chk = rm.pre_trade_check(**_args(has_stop=False, client_order_id="id-nostop"))
    assert not chk.approved
    assert any("protective stop" in r for r in chk.reasons)


def test_wide_spread_blocks(rm):
    chk = rm.pre_trade_check(**_args(spread_pips=99.0, client_order_id="id-spread"))
    assert not chk.approved
    assert any("spread too wide" in r for r in chk.reasons)


def test_stale_data_blocks(rm):
    chk = rm.pre_trade_check(**_args(data_age_seconds=10_000, client_order_id="id-stale"))
    assert not chk.approved
    assert any("stale" in r for r in chk.reasons)


def test_duplicate_order_id_blocks(rm):
    first = rm.pre_trade_check(**_args(client_order_id="dup"))
    assert first.approved
    second = rm.pre_trade_check(**_args(client_order_id="dup"))
    assert not second.approved
    assert any("duplicate" in r for r in second.reasons)


def test_max_open_positions_blocks(rm):
    rm.open_positions = rm.config.max_open_positions
    chk = rm.pre_trade_check(**_args(client_order_id="id-maxpos"))
    assert not chk.approved
    assert any("max open positions" in r for r in chk.reasons)


def test_daily_loss_halts_trading(rm):
    # simulate a loss beyond the daily limit, then a check should be blocked
    loss = -rm.config.starting_equity * (rm.config.max_daily_loss_pct / 100.0) - 1
    rm._roll_day(datetime(2022, 6, 10, 9, 0, tzinfo=timezone.utc))
    rm.register_fill_pnl(loss)
    chk = rm.pre_trade_check(**_args(client_order_id="id-dayloss"))
    assert not chk.approved
    assert any("daily loss" in r for r in chk.reasons)


def test_kill_switch_blocks(rm, tmp_path, monkeypatch):
    # create the kill switch file in the project root the manager checks
    ks = PROJECT_ROOT / rm.config.kill_switch_file
    ks.write_text("halt")
    try:
        chk = rm.pre_trade_check(**_args(client_order_id="id-kill"))
        assert not chk.approved
        assert any("KILL SWITCH" in r for r in chk.reasons)
    finally:
        ks.unlink(missing_ok=True)


def test_latched_block_after_protective_failure(rm):
    rm.block_entries("protective stop was rejected by broker")
    chk = rm.pre_trade_check(**_args(client_order_id="id-latch"))
    assert not chk.approved
    assert any("latched-blocked" in r for r in chk.reasons)
