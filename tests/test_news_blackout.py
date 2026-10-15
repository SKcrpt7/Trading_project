"""The news blackout must block inside the window and allow outside it, must widen
for uncertain (conventional) times, and must respect the impact filter."""
from datetime import datetime, timezone, timedelta

from fxlab.econ.events import EventCalendar
from fxlab.econ.blackout import NewsBlackout, BlackoutConfig
from fxlab.types import EconomicEvent


def _cal(event):
    return EventCalendar([event])


def _event(impact="high", exact=True, hour=13, minute=30):
    return EconomicEvent(
        time_utc=datetime(2022, 6, 10, hour, minute, tzinfo=timezone.utc),
        country="US", title="CPI", impact=impact, source="TEST", time_is_exact=exact,
    )


def test_blocks_inside_window_allows_outside():
    ev = _event()
    cfg = BlackoutConfig(enabled=True, block_minutes_before=30, block_minutes_after=30,
                         min_impact="high", uncertain_time_extra_minutes=0)
    nb = NewsBlackout(_cal(ev), cfg)
    assert nb.check(ev.time_utc).blocked                                  # at the event
    assert nb.check(ev.time_utc - timedelta(minutes=15)).blocked          # just before
    assert nb.check(ev.time_utc + timedelta(minutes=29)).blocked          # just after
    assert not nb.check(ev.time_utc - timedelta(minutes=31)).blocked      # outside before
    assert not nb.check(ev.time_utc + timedelta(minutes=31)).blocked      # outside after


def test_uncertain_time_widens_window():
    ev = _event(exact=False)
    cfg = BlackoutConfig(True, 30, 30, "high", uncertain_time_extra_minutes=30)
    nb = NewsBlackout(_cal(ev), cfg)
    # 50 min before would be OUTSIDE a 30-min window, but INSIDE a widened 60-min one
    assert nb.check(ev.time_utc - timedelta(minutes=50)).blocked
    assert not nb.check(ev.time_utc - timedelta(minutes=61)).blocked


def test_impact_filter_ignores_low_impact():
    ev = _event(impact="low")
    cfg = BlackoutConfig(True, 30, 30, min_impact="high", uncertain_time_extra_minutes=0)
    nb = NewsBlackout(_cal(ev), cfg)
    assert not nb.check(ev.time_utc).blocked  # low impact, high filter -> not blocked


def test_disabled_never_blocks():
    ev = _event()
    nb = NewsBlackout(_cal(ev), BlackoutConfig(enabled=False))
    assert not nb.check(ev.time_utc).blocked
