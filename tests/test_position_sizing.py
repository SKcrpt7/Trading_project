"""Position sizing is the single most important risk control. These tests pin
down its exact behaviour so it can never silently change."""
from fxlab.risk.sizing import position_size, STANDARD_LOT


def test_basic_sizing_matches_formula():
    # risk 1% of 10,000 = $100. Stop 20 pips = 0.0020 price. units = 100/0.0020 = 50,000.
    r = position_size(equity=10_000, risk_pct=1.0, stop_distance=0.0020, max_risk_pct=2.0)
    assert r.is_tradeable
    assert abs(r.risk_amount - 100.0) < 1e-9
    assert abs(r.units - 50_000) < 1e-6
    assert abs(r.lots - 0.5) < 1e-9


def test_risk_pct_is_capped_to_max():
    # strategy asks for 5% but max is 1% -> must clamp to 1%.
    r = position_size(equity=10_000, risk_pct=5.0, stop_distance=0.0010, max_risk_pct=1.0)
    assert "capped" in r.capped_reason
    # risk amount should reflect 1%, not 5%
    assert abs(r.risk_amount - 100.0) < 1e-9


def test_wider_stop_means_smaller_size():
    narrow = position_size(10_000, 1.0, 0.0010, 2.0)
    wide = position_size(10_000, 1.0, 0.0040, 2.0)
    assert wide.units < narrow.units


def test_zero_or_negative_inputs_are_not_tradeable():
    assert not position_size(0, 1.0, 0.0020, 2.0).is_tradeable
    assert not position_size(10_000, 1.0, 0.0, 2.0).is_tradeable
    assert not position_size(10_000, 1.0, -0.001, 2.0).is_tradeable


def test_tiny_size_below_minimum_is_rejected():
    # huge stop distance -> sub-1-unit size -> no trade
    r = position_size(equity=100, risk_pct=0.1, stop_distance=5.0, max_risk_pct=1.0, min_units=1.0)
    assert not r.is_tradeable
