"""Data-quality checks.

A strategy is only as trustworthy as its data. Before any backtest we record,
in plain terms, what the data does and does not support: where bars are missing,
whether bid/ask is available, and whether any bars look structurally broken
(e.g. high < low). These findings are printed and stored so you are never
silently trusting bad data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

import pandas as pd


@dataclass
class DataQualityReport:
    symbol: str
    timeframe: str
    source: str
    timezone: str
    start: Optional[pd.Timestamp]
    end: Optional[pd.Timestamp]
    n_bars: int
    has_bid_ask: bool
    expected_bars: int
    missing_periods: list[tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list)
    n_duplicate_timestamps: int = 0
    n_nonmonotonic: int = 0
    n_bad_ohlc: int = 0          # high<low, or close outside [low,high], etc.
    n_nonpositive_price: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def completeness_pct(self) -> float:
        if self.expected_bars <= 0:
            return 0.0
        return round(100.0 * self.n_bars / self.expected_bars, 2)

    def summary(self) -> str:
        lines = [
            f"Data quality report: {self.symbol} {self.timeframe}  (source={self.source}, tz={self.timezone})",
            f"  Range        : {self.start}  ->  {self.end}",
            f"  Bars         : {self.n_bars:,}  (expected ~{self.expected_bars:,}, "
            f"completeness {self.completeness_pct}%)",
            f"  Bid/Ask      : {'available' if self.has_bid_ask else 'NOT available (mid only)'}",
            f"  Missing gaps : {len(self.missing_periods)}",
            f"  Duplicates   : {self.n_duplicate_timestamps}   Non-monotonic: {self.n_nonmonotonic}",
            f"  Bad OHLC     : {self.n_bad_ohlc}   Non-positive prices: {self.n_nonpositive_price}",
        ]
        for gap_start, gap_end in self.missing_periods[:10]:
            lines.append(f"    gap: {gap_start}  ..  {gap_end}")
        if len(self.missing_periods) > 10:
            lines.append(f"    ... and {len(self.missing_periods) - 10} more gaps")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


_TIMEFRAME_TO_DELTA = {
    "M1": timedelta(minutes=1),
    "M5": timedelta(minutes=5),
    "M15": timedelta(minutes=15),
    "M30": timedelta(minutes=30),
    "H1": timedelta(hours=1),
    "H4": timedelta(hours=4),
    "D1": timedelta(days=1),
}


def timeframe_delta(timeframe: str) -> timedelta:
    if timeframe not in _TIMEFRAME_TO_DELTA:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Known: {list(_TIMEFRAME_TO_DELTA)}")
    return _TIMEFRAME_TO_DELTA[timeframe]


def assess_quality(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    source: str,
    timezone: str,
    weekdays_only: bool = True,
) -> DataQualityReport:
    """Inspect an OHLC(+bid/ask) DataFrame indexed by UTC timestamp.

    Gap detection: we only flag gaps LARGER than one bar between *consecutive
    weekday* bars, so normal weekend closes are not reported as missing.
    """
    has_bid_ask = {"bid", "ask"}.issubset(df.columns)
    n = len(df)
    if n == 0:
        return DataQualityReport(symbol, timeframe, source, timezone, None, None, 0,
                                 has_bid_ask, 0, notes=["empty dataset"])

    ts = df.index
    start, end = ts.min(), ts.max()
    delta = timeframe_delta(timeframe)

    # Duplicate / ordering checks.
    n_dupes = int(ts.duplicated().sum())
    n_nonmono = int((ts.to_series().diff().dropna() <= pd.Timedelta(0)).sum())

    # Structural OHLC checks.
    bad_ohlc = (
        (df["high"] < df["low"])
        | (df["close"] > df["high"]) | (df["close"] < df["low"])
        | (df["open"] > df["high"]) | (df["open"] < df["low"])
    )
    n_bad = int(bad_ohlc.sum())
    price_cols = [c for c in ["open", "high", "low", "close", "bid", "ask"] if c in df.columns]
    n_nonpos = int((df[price_cols] <= 0).any(axis=1).sum())

    # Gap detection across consecutive bars, skipping weekend boundaries.
    missing: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    diffs = ts.to_series().diff()
    for i in range(1, n):
        gap = diffs.iloc[i]
        prev, cur = ts[i - 1], ts[i]
        # Skip the normal Friday->Monday weekend jump.
        if weekdays_only and prev.weekday() == 4 and cur.weekday() == 0:
            continue
        if gap > delta:
            # number of missing intervals
            if gap > delta * 1.5:
                missing.append((prev + delta, cur - delta))

    # Expected bar count: weekday hours across the range (approx, for completeness %).
    if weekdays_only and timeframe == "H1":
        bdays = pd.bdate_range(start.normalize(), end.normalize())
        expected = len(bdays) * 24
    else:
        span = (end - start)
        expected = int(span / delta) + 1

    notes = []
    if source.upper() == "MOCK":
        notes.append("SOURCE IS MOCK/SYNTHETIC DATA - not real market data.")
    if not has_bid_ask:
        notes.append("No bid/ask columns: spread must be assumed, not observed.")

    return DataQualityReport(
        symbol=symbol, timeframe=timeframe, source=source, timezone=timezone,
        start=start, end=end, n_bars=n, has_bid_ask=has_bid_ask,
        expected_bars=expected, missing_periods=missing,
        n_duplicate_timestamps=n_dupes, n_nonmonotonic=n_nonmono,
        n_bad_ohlc=n_bad, n_nonpositive_price=n_nonpos, notes=notes,
    )
