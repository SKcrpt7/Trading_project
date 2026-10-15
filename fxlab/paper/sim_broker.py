"""Simulated broker - clearly-labelled fake fills for paper trading.

Every Fill it returns has is_simulated=True. It replays bars handed to it by the
paper runner and models the SAME costs as the backtester (spread + slippage), so
paper behaviour is comparable to backtest behaviour by construction.

Testing hook: set force_reject_protective=True to make the next bracket's
protective stop be rejected while the entry still fills. This exercises the
emergency path (flatten + block further entries), which must be proven to work.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fxlab.backtest.costs import CostModel
from fxlab.paper.broker_interface import BracketResult, BrokerInterface, Quote
from fxlab.types import Fill, Side


class SimBroker(BrokerInterface):
    is_simulated = True

    def __init__(self, cost_model: CostModel, symbol: str):
        self.cost = cost_model
        self.symbol = symbol
        self._connected = False
        self._bar: Optional[dict] = None
        self._ts: Optional[datetime] = None
        self._position: Optional[dict] = None
        self._phase = "open"                  # where in the current bar the clock is
        self.force_reject_protective = False  # test hook

    @property
    def name(self) -> str:
        return "SimBroker(PAPER/SIMULATED)"

    def connect(self) -> None:
        self.assert_not_live()
        self._connected = True

    def set_bar(self, ts: datetime, bar: dict) -> None:
        """Called by the runner at the START of each bar. The simulated clock is now
        at this bar's OPEN - the bar's high/low/close have not 'happened' yet."""
        self._ts, self._bar = ts, bar
        self._phase = "open"

    def mark_bar_close(self) -> None:
        """Advance the simulated clock to the CLOSE of the current bar (used at end of
        data, where the backtester also exits at the last close)."""
        self._phase = "close"

    def get_quote(self, symbol: str) -> Quote:
        # The quote reflects the CURRENT simulated moment. Decisions are made at the
        # bar's open, so pricing them off the bar's close would be look-ahead.
        assert self._bar is not None, "no current bar set"
        hs = self.cost.half_spread_price
        mid = self._bar[self._phase]
        return Quote(time=self._ts, symbol=symbol, bid=mid - hs, ask=mid + hs)

    # ---- bracket entry ----
    def submit_bracket(self, symbol, side, quantity, stop_price, target_price,
                       client_order_id) -> BracketResult:
        self.assert_not_live()
        if self._position is not None:
            return BracketResult(accepted=False, reject_reason="position already open",
                                 client_order_id=client_order_id)

        hs = self.cost.half_spread_price
        slip = self.cost.slippage_price
        raw = self._bar["open"]
        direction = 1 if side == Side.LONG else -1
        entry_fill_px = raw + (hs + slip) if direction > 0 else raw - (hs + slip)

        entry_fill = Fill(
            timestamp=self._ts, symbol=symbol, side=side, quantity=quantity,
            price=round(entry_fill_px, 6), commission=self.cost.commission(quantity) / 2.0,
            is_simulated=True, order_client_id=client_order_id,
        )

        stop_ok = not self.force_reject_protective
        self.force_reject_protective = False  # one-shot
        target_ok = target_price is not None

        if not stop_ok:
            # Entry filled but protective stop REJECTED. Record the position so the
            # runner can flatten it; signal the failure to the caller.
            self._position = {
                "side": side, "quantity": quantity, "entry_price": entry_fill_px,
                "stop": None, "target": target_price, "entry_time": self._ts,
                "client_order_id": client_order_id, "unprotected": True,
            }
            return BracketResult(
                accepted=True, entry_fill=entry_fill, stop_accepted=False,
                target_accepted=target_ok, stop_price=stop_price, target_price=target_price,
                reject_reason="PROTECTIVE STOP REJECTED by broker", client_order_id=client_order_id,
            )

        self._position = {
            "side": side, "quantity": quantity, "entry_price": entry_fill_px,
            "stop": stop_price, "target": target_price, "entry_time": self._ts,
            "client_order_id": client_order_id, "unprotected": False,
        }
        return BracketResult(
            accepted=True, entry_fill=entry_fill, stop_accepted=True,
            target_accepted=target_ok, stop_price=stop_price, target_price=target_price,
            client_order_id=client_order_id,
        )

    # ---- per-bar fill checking ----
    def on_bar(self, ts: datetime, bar: dict) -> Optional[Fill]:
        """Start a new bar and check stop/target against it."""
        self.set_bar(ts, bar)
        return self.check_exits()

    def check_exits(self) -> Optional[Fill]:
        """Check stop/target against the CURRENT bar's range; return an exit Fill if
        triggered. Also called right after an entry: the entry fills at the open,
        and the rest of that bar's range happens after it, so the stop can be hit
        on the entry bar itself."""
        if self._position is None or self._position.get("stop") is None:
            return None
        p = self._position
        direction = 1 if p["side"] == Side.LONG else -1
        ts, bar = self._ts, self._bar
        h, l = bar["high"], bar["low"]
        hs, slip = self.cost.half_spread_price, self.cost.slippage_price

        stop_px, tgt_px = p["stop"], p["target"]
        if direction > 0:
            stop_hit, tgt_hit = l <= stop_px, (tgt_px is not None and h >= tgt_px)
        else:
            stop_hit, tgt_hit = h >= stop_px, (tgt_px is not None and l <= tgt_px)

        if stop_hit:  # pessimistic: stop before target
            px = (stop_px - (hs + slip)) if direction > 0 else (stop_px + (hs + slip))
            return self._close(ts, px, "stop")
        if tgt_hit:
            px = (tgt_px - hs) if direction > 0 else (tgt_px + hs)
            return self._close(ts, px, "target")
        return None

    def _close(self, ts, price, reason) -> Fill:
        p = self._position
        exit_side = Side.SHORT if p["side"] == Side.LONG else Side.LONG
        fill = Fill(timestamp=ts, symbol=self.symbol, side=exit_side, quantity=p["quantity"],
                    price=round(price, 6), commission=self.cost.commission(p["quantity"]) / 2.0,
                    is_simulated=True, order_client_id=p["client_order_id"] + "_exit")
        fill_meta = {"reason": reason, "entry_price": p["entry_price"], "side": p["side"].value}
        self._last_close_meta = fill_meta
        self._position = None
        return fill

    def flatten(self, symbol: str, reason: str) -> Optional[Fill]:
        """Market-close the position at the current quote. Like any market order it
        crosses the spread AND pays slippage - the same cost the backtester charges
        for its market exits, so the two stay comparable."""
        self.assert_not_live()
        if self._position is None:
            return None
        quote = self.get_quote(symbol)
        p = self._position
        slip = self.cost.slippage_price
        price = quote.bid - slip if p["side"] == Side.LONG else quote.ask + slip
        return self._close(self._ts, price, reason)

    def open_positions(self) -> list[dict]:
        return [dict(self._position)] if self._position else []
