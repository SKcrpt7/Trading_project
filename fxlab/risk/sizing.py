"""Position sizing.

Fixed-fractional-risk sizing answers one question: given my equity, how many
units can I buy so that IF my protective stop is hit, I lose exactly R% of equity?

    risk_amount = equity * risk_pct / 100
    loss_per_unit_if_stopped = stop_distance_in_price   (quote currency per unit)
    units = risk_amount / loss_per_unit_if_stopped

This is deliberately simple and transparent. It assumes the quote currency equals
the account currency (true for EUR/USD with a USD account). For other pairs a
currency-conversion factor would be needed - documented, not silently wrong.
"""
from __future__ import annotations

from dataclasses import dataclass

STANDARD_LOT = 100_000  # units of base currency in one standard lot


@dataclass
class SizingResult:
    units: float
    lots: float
    risk_amount: float            # account currency at risk if stopped
    stop_distance: float          # price distance used
    capped_reason: str = ""       # non-empty if a cap reduced the size

    @property
    def is_tradeable(self) -> bool:
        return self.units > 0


def position_size(
    equity: float,
    risk_pct: float,
    stop_distance: float,
    max_risk_pct: float,
    quote_per_account_ccy: float = 1.0,
    min_units: float = 1.0,
) -> SizingResult:
    """Compute units to trade.

    Args:
        equity: current account equity (account currency).
        risk_pct: percent of equity to risk on this trade (strategy request).
        stop_distance: distance from entry to stop, in PRICE (e.g. 0.0030 = 30 pips).
        max_risk_pct: hard ceiling from risk.yaml; the request is clamped to this.
        quote_per_account_ccy: units of quote currency per 1 account currency
            (1.0 when quote == account currency, e.g. USD-quoted pair, USD account).
        min_units: smallest tradeable size; below this we return 0 (no trade).
    """
    if equity <= 0 or stop_distance <= 0:
        return SizingResult(0.0, 0.0, 0.0, stop_distance, "non-positive equity or stop distance")

    capped_reason = ""
    effective_pct = risk_pct
    if risk_pct > max_risk_pct:
        effective_pct = max_risk_pct
        capped_reason = f"risk {risk_pct}% capped to max {max_risk_pct}%"

    risk_amount = equity * effective_pct / 100.0
    # loss per unit if stopped, expressed in account currency
    loss_per_unit = stop_distance * quote_per_account_ccy
    units = risk_amount / loss_per_unit

    if units < min_units:
        return SizingResult(0.0, 0.0, risk_amount, stop_distance,
                            capped_reason or "computed size below minimum")

    return SizingResult(
        units=units, lots=units / STANDARD_LOT,
        risk_amount=risk_amount, stop_distance=stop_distance, capped_reason=capped_reason,
    )
