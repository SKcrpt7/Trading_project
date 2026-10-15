"""Trading-cost model.

Every real trade pays: the spread (you buy at ask, sell at bid), commission,
slippage (price moves against you between decision and fill), and swap/financing
if held overnight. We model each explicitly and in account currency so a trade's
"costs" line is never a mystery.

Assumptions we CANNOT fully support from bar data, stated plainly:
  * We assume spread is symmetric around the mid and constant per config
    (real spread widens around news and session edges).
  * Slippage is a fixed pip amount on market/stop fills; limit (target) fills
    assume no slippage but still cross the spread.
  * When both stop and target fall inside one bar, we PESSIMISTICALLY assume the
    stop filled first (we cannot see intrabar order from OHLC).
"""
from __future__ import annotations

from dataclasses import dataclass

from fxlab.risk.sizing import STANDARD_LOT


@dataclass
class CostModel:
    pip_size: float
    spread_pips: float
    commission_per_lot_per_side: float
    slippage_pips: float
    swap_long_per_lot_per_night: float
    swap_short_per_lot_per_night: float
    rollover_hour_utc: int

    @classmethod
    def from_config(cls, bt_cfg: dict, pip_size: float,
                    spread_mult: float = 1.0, slippage_mult: float = 1.0) -> "CostModel":
        c = bt_cfg["costs"]
        return cls(
            pip_size=pip_size,
            spread_pips=float(c["spread_pips"]) * spread_mult,
            commission_per_lot_per_side=float(c["commission_per_lot_per_side"]),
            slippage_pips=float(c["slippage_pips"]) * slippage_mult,
            swap_long_per_lot_per_night=float(c["swap_long_per_lot_per_night"]),
            swap_short_per_lot_per_night=float(c["swap_short_per_lot_per_night"]),
            rollover_hour_utc=int(c.get("rollover_hour_utc", 21)),
        )

    @property
    def half_spread_price(self) -> float:
        return 0.5 * self.spread_pips * self.pip_size

    @property
    def slippage_price(self) -> float:
        return self.slippage_pips * self.pip_size

    def commission(self, units: float) -> float:
        """Round-trip commission (both sides) for `units`."""
        lots = abs(units) / STANDARD_LOT
        return lots * self.commission_per_lot_per_side * 2.0

    def swap(self, units: float, direction: int, nights: int) -> float:
        """Financing cost (negative = you pay) for holding `nights` rollovers."""
        lots = abs(units) / STANDARD_LOT
        rate = self.swap_long_per_lot_per_night if direction > 0 else self.swap_short_per_lot_per_night
        return lots * rate * nights
