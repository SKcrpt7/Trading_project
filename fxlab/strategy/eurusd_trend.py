"""EUR/USD EMA-crossover trend follower - the RESEARCH EXAMPLE.

This is a teaching example, NOT a profitable-strategy claim. Its purpose is to
show the full lifecycle: specify -> backtest -> review -> paper. All parameters
come from config/strategy_eurusd_trend.yaml.

Rules (evaluated on CLOSED bars only):
  LONG  when fast EMA crosses ABOVE slow EMA and close > slow EMA.
  SHORT when fast EMA crosses BELOW slow EMA and close < slow EMA.
  Protective stop = stop_atr_mult * ATR away from entry.
  Target          = reward_risk * stop distance away from entry.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from fxlab.data.interface import PriceData
from fxlab.strategy import indicators as ind
from fxlab.strategy.base import Strategy, StrategySpec


class EurUsdTrendStrategy(Strategy):
    def __init__(self, spec: StrategySpec):
        super().__init__(spec)
        e = spec.raw["entry"]
        x = spec.raw["exit"]
        self.fast_ema = int(e["fast_ema"])
        self.slow_ema = int(e["slow_ema"])
        self.allow_long = bool(e.get("allow_long", True))
        self.allow_short = bool(e.get("allow_short", True))
        self.atr_period = int(x["atr_period"])
        self.stop_atr_mult = float(x["stop_atr_mult"])
        self.reward_risk = float(x["reward_risk"])

    def generate(self, data: PriceData) -> pd.DataFrame:
        df = data.df
        close = df["close"]

        fast = ind.ema(close, self.fast_ema)
        slow = ind.ema(close, self.slow_ema)
        atr = ind.atr(df, self.atr_period)

        cross_up = ind.crossover(fast, slow) & (close > slow)
        cross_dn = ind.crossunder(fast, slow) & (close < slow)

        signal = pd.Series(0, index=df.index, dtype="int64")
        if self.allow_long:
            signal = signal.mask(cross_up, 1)
        if self.allow_short:
            signal = signal.mask(cross_dn, -1)

        stop_distance = self.stop_atr_mult * atr
        target_distance = self.reward_risk * stop_distance

        reason = pd.Series("", index=df.index, dtype="object")
        reason = reason.mask(
            signal == 1,
            "EMA" + str(self.fast_ema) + " crossed above EMA" + str(self.slow_ema)
            + " with close>slowEMA (uptrend entry)",
        )
        reason = reason.mask(
            signal == -1,
            "EMA" + str(self.fast_ema) + " crossed below EMA" + str(self.slow_ema)
            + " with close<slowEMA (downtrend entry)",
        )

        out = pd.DataFrame(
            {
                "signal": signal,
                "stop_distance": stop_distance,
                "target_distance": target_distance,
                "reason": reason,
                "fast_ema": fast,
                "slow_ema": slow,
                "atr": atr,
            },
            index=df.index,
        )
        # Where indicators are not yet warmed up, force no-action.
        warmup = atr.isna() | slow.isna() | fast.isna()
        out.loc[warmup, "signal"] = 0
        # A signal with an undefined stop is unusable - drop it defensively.
        out.loc[out["stop_distance"].isna() | (out["stop_distance"] <= 0), "signal"] = 0
        return out
