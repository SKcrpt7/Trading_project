# region imports
from AlgorithmImports import *
import os
import json
# endregion

# ===========================================================================
# EUR/USD EMA trend-follower for QuantConnect LEAN - the SAME research example
# as the local engine (fxlab), expressed in LEAN's API.
#
# This file is RUN BY LEAN, not by the local fxlab package. It mirrors the rules
# in config/strategy_eurusd_trend.yaml so backtests in both engines are
# comparable. It requires Docker (local LEAN) or a QuantConnect account (cloud).
#
#   Local : install Docker Desktop, `pip install lean`, then `lean backtest`.
#   Cloud : `lean cloud push` / `lean cloud backtest` with a QC account.
#
# Parameters are read from the shared YAML when available, with safe fallbacks,
# so you tune ONE place. Live trading is not configured here.
# ===========================================================================

DEFAULTS = {
    "fast_ema": 20, "slow_ema": 50, "atr_period": 14,
    "stop_atr_mult": 2.0, "reward_risk": 1.5,
    "risk_per_trade_pct": 0.5, "session_start": 7, "session_end": 20,
}


def _load_params():
    """Try to read the shared strategy YAML; fall back to DEFAULTS.
    (LEAN containers may not mount the repo; the fallback keeps this runnable.)"""
    params = dict(DEFAULTS)
    try:
        import yaml  # available in the LEAN research image
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "config", "strategy_eurusd_trend.yaml")
        with open(path, "r") as f:
            cfg = yaml.safe_load(f)
        params.update({
            "fast_ema": cfg["entry"]["fast_ema"],
            "slow_ema": cfg["entry"]["slow_ema"],
            "atr_period": cfg["exit"]["atr_period"],
            "stop_atr_mult": cfg["exit"]["stop_atr_mult"],
            "reward_risk": cfg["exit"]["reward_risk"],
            "risk_per_trade_pct": cfg["sizing"]["risk_per_trade_pct"],
            "session_start": int(cfg["session"]["start_utc"].split(":")[0]),
            "session_end": int(cfg["session"]["end_utc"].split(":")[0]),
        })
    except Exception:
        pass
    return params


class EURUSDTrendAlgorithm(QCAlgorithm):

    def initialize(self):
        self.set_start_date(2021, 1, 4)
        self.set_end_date(2023, 12, 29)
        self.set_cash(10_000)

        p = _load_params()
        self.p = p

        # OANDA EUR/USD, hourly bars (matches the local H1 example).
        self.pair = self.add_forex("EURUSD", Resolution.HOUR, Market.OANDA)
        self.symbol = self.pair.symbol

        # Model realistic-ish costs. Spread comes from the quote data; add slippage.
        self.set_brokerage_model(BrokerageName.OANDA_BROKERAGE)
        self.pair.set_slippage_model(ConstantSlippageModel(0.00005))  # ~0.5 pip

        self.fast = self.ema(self.symbol, p["fast_ema"], Resolution.HOUR)
        self.slow = self.ema(self.symbol, p["slow_ema"], Resolution.HOUR)
        self.atr = self.atr(self.symbol, p["atr_period"], MovingAverageType.WILDERS, Resolution.HOUR)

        self.set_warm_up(p["slow_ema"] + p["atr_period"], Resolution.HOUR)

        self._prev_fast = None
        self._prev_slow = None
        self._stop_ticket = None
        self._target_ticket = None

    def on_data(self, data: Slice):
        if self.is_warming_up or not (self.fast.is_ready and self.slow.is_ready and self.atr.is_ready):
            return
        if self.symbol not in data or data[self.symbol] is None:
            return

        hour = self.time.hour  # algorithm time; session filter in local hours ~ UTC on OANDA
        in_session = self.p["session_start"] <= hour <= self.p["session_end"]

        fast, slow = self.fast.current.value, self.slow.current.value
        price = data[self.symbol].close
        invested = self.portfolio[self.symbol].invested

        if self._prev_fast is not None and not invested and in_session:
            crossed_up = self._prev_fast <= self._prev_slow and fast > slow and price > slow
            crossed_dn = self._prev_fast >= self._prev_slow and fast < slow and price < slow
            if crossed_up:
                self._enter(1, price)
            elif crossed_dn:
                self._enter(-1, price)

        self._prev_fast, self._prev_slow = fast, slow

    def _enter(self, direction: int, price: float):
        atr = self.atr.current.value
        stop_dist = self.p["stop_atr_mult"] * atr
        if stop_dist <= 0:
            return
        # fixed-fractional risk sizing (quote ccy == account ccy for EUR/USD USD acct)
        risk_amount = self.portfolio.total_portfolio_value * self.p["risk_per_trade_pct"] / 100.0
        units = risk_amount / stop_dist
        quantity = units if direction > 0 else -units

        self.market_order(self.symbol, quantity)

        entry = price
        if direction > 0:
            stop_px = entry - stop_dist
            target_px = entry + self.p["reward_risk"] * stop_dist
        else:
            stop_px = entry + stop_dist
            target_px = entry - self.p["reward_risk"] * stop_dist

        # Protective stop + target as resting orders (a 'bracket'). If the stop
        # order fails to place, LEAN surfaces it in on_order_event -> we flatten.
        self._stop_ticket = self.stop_market_order(self.symbol, -quantity, stop_px)
        self._target_ticket = self.limit_order(self.symbol, -quantity, target_px)

    def on_order_event(self, order_event: OrderEvent):
        if order_event.status != OrderStatus.FILLED:
            # If a protective stop was rejected/canceled while we hold a position,
            # flatten immediately - never sit in an unprotected position.
            if (self._stop_ticket is not None
                    and order_event.order_id == self._stop_ticket.order_id
                    and order_event.status in (OrderStatus.CANCELED, OrderStatus.INVALID)
                    and self.portfolio[self.symbol].invested):
                self.log("PROTECTIVE STOP FAILED -> liquidating position.")
                self.liquidate(self.symbol)
            return
        # When one bracket leg fills, cancel the other (OCO behaviour).
        oid = order_event.order_id
        if self._stop_ticket and oid == self._stop_ticket.order_id and self._target_ticket:
            self._target_ticket.cancel()
        elif self._target_ticket and oid == self._target_ticket.order_id and self._stop_ticket:
            self._stop_ticket.cancel()
