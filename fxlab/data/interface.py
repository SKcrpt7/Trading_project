"""Price-data interface.

PriceDataProvider is the seam that keeps the rest of the system independent of
where data comes from. Today we ship a CSV provider for the bundled sample data;
a Dukascopy / QuantConnect / broker provider can be added later by implementing
the same interface. Every PriceData object carries its own provenance so a
backtest can always answer "where did this data come from, and can I trust it?".
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from fxlab.data.quality import DataQualityReport, assess_quality

OHLC_COLUMNS = ["open", "high", "low", "close"]


@dataclass
class PriceData:
    """OHLC(+bid/ask) bars plus provenance. The DataFrame is indexed by a
    tz-aware UTC DatetimeIndex and sorted ascending."""
    symbol: str
    timeframe: str
    source: str
    df: pd.DataFrame
    timezone: str = "UTC"
    has_bid_ask: bool = False

    def quality(self) -> DataQualityReport:
        return assess_quality(self.df, self.symbol, self.timeframe, self.source, self.timezone)

    def slice(self, start: Optional[str] = None, end: Optional[str] = None) -> "PriceData":
        df = self.df
        if start is not None:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]
        return PriceData(self.symbol, self.timeframe, self.source, df.copy(),
                         self.timezone, self.has_bid_ask)

    def split_chronological(self, dev_fraction: float) -> tuple["PriceData", "PriceData"]:
        """Return (development, evaluation) split chronologically. The evaluation
        slice must be treated as untouched hold-out."""
        if not 0.0 < dev_fraction < 1.0:
            raise ValueError("dev_fraction must be in (0,1)")
        cut = int(len(self.df) * dev_fraction)
        dev = PriceData(self.symbol, self.timeframe, self.source,
                        self.df.iloc[:cut].copy(), self.timezone, self.has_bid_ask)
        evl = PriceData(self.symbol, self.timeframe, self.source,
                        self.df.iloc[cut:].copy(), self.timezone, self.has_bid_ask)
        return dev, evl


class PriceDataProvider(ABC):
    """Implement this to add a new data source (broker, QC, Dukascopy, ...)."""

    @abstractmethod
    def load(self, symbol: str, timeframe: str,
             start: Optional[str] = None, end: Optional[str] = None) -> PriceData:
        ...


class CsvPriceProvider(PriceDataProvider):
    """Loads OHLC bars from a CSV with a 'timestamp' column (UTC).

    Required columns: timestamp, open, high, low, close.
    Optional columns: bid, ask, spread, volume, source.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Price CSV not found: {self.path}")

    def load(self, symbol: str, timeframe: str,
             start: Optional[str] = None, end: Optional[str] = None) -> PriceData:
        df = pd.read_csv(self.path)
        missing = [c for c in ["timestamp", *OHLC_COLUMNS] if c not in df.columns]
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")

        source = str(df["source"].iloc[0]) if "source" in df.columns and len(df) else "unknown"
        has_bid_ask = {"bid", "ask"}.issubset(df.columns)

        pd_obj = PriceData(symbol, timeframe, source, df, "UTC", has_bid_ask)
        if start or end:
            pd_obj = pd_obj.slice(start, end)
        return pd_obj
