"""Indicator functions.

All indicators are CAUSAL: the value at bar i uses only bars <= i. This is the
first line of defence against look-ahead bias. We implement them by hand (no
TA-Lib dependency) so you can read exactly what each one does.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average. adjust=False gives the standard recursive EMA
    used by charting platforms (each value depends only on the past)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
    prev_close = df["close"].shift(1)
    hl = df["high"] - df["low"]
    hc = (df["high"] - prev_close).abs()
    lc = (df["low"] - prev_close).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range via Wilder's smoothing (an EMA with alpha=1/period)."""
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def donchian_high(series: pd.Series, period: int) -> pd.Series:
    """Highest high over the PRIOR `period` bars (shifted by 1 so the current
    bar is excluded - this is what a breakout rule should compare against)."""
    return series.rolling(period, min_periods=period).max().shift(1)


def donchian_low(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).min().shift(1)


def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True on bars where `fast` crosses from <= to > `slow`."""
    was_below = fast.shift(1) <= slow.shift(1)
    now_above = fast > slow
    return was_below & now_above


def crossunder(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True on bars where `fast` crosses from >= to < `slow`."""
    was_above = fast.shift(1) >= slow.shift(1)
    now_below = fast < slow
    return was_above & now_below
