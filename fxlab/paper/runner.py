"""Paper-trading runner (local simulation mode).

This replays bars through the SAME pieces that would run live: the strategy makes
a signal, the risk manager approves or blocks it, the broker fills it (simulated),
and every step is written to the audit log. The sim broker models the same costs
as the backtester and the runner applies exits in the same order (signal exit at
the open, then intrabar stop/target - including on the entry bar), so with no
risk gate firing, paper and backtest produce IDENTICAL trades
(tests/test_parity.py). Any gap in the end-of-run comparison is then explained by
the extra live-style gates below, not by the engines disagreeing.

Safety behaviours demonstrated here:
  * kill switch (file present -> no new entries)
  * stale-data detection (a data gap larger than one bar blocks entries)
  * duplicate-order prevention (client order ids)
  * spread limit, daily loss limit, max open positions, max risk per trade
  * protective-stop failure -> flatten immediately AND latch-block new entries
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from fxlab.audit.store import AuditStore
from fxlab.backtest.costs import CostModel
from fxlab.backtest.engine import count_rollovers
from fxlab.data.interface import PriceData
from fxlab.data.quality import timeframe_delta
from fxlab.econ.blackout import NewsBlackout
from fxlab.paper.sim_broker import SimBroker
from fxlab.risk.manager import RiskConfig, RiskManager
from fxlab.strategy.base import Strategy
from fxlab.types import Side, Trade


@dataclass
class PaperRunResult:
    strategy_name: str
    symbol: str
    starting_equity: float
    ending_equity: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    entries_blocked_latched: bool = False
    block_reason: str = ""
    counts: dict = field(default_factory=dict)

    @property
    def net_return_pct(self) -> float:
        if not self.starting_equity:
            return 0.0
        return round(100.0 * (self.ending_equity - self.starting_equity) / self.starting_equity, 2)


class PaperRunner:
    def __init__(
        self,
        strategy: Strategy,
        cost_model: CostModel,
        risk_config: RiskConfig,
        audit: AuditStore,
        blackout: Optional[NewsBlackout] = None,
        use_session: bool = True,
        time_stop_bars: int = 0,
        exit_on_opposite_signal: bool = True,
        inject_protective_failure_at: Optional[int] = None,  # test hook: bar index
    ):
        self.strategy = strategy
        self.cost = cost_model
        self.risk = RiskManager(risk_config)
        self.audit = audit
        self.blackout = blackout
        self.use_session = use_session
        self.time_stop_bars = time_stop_bars
        self.exit_on_opposite = exit_on_opposite_signal
        self.inject_fail_at = inject_protective_failure_at
        self._fail_used = False
        self._trades: list[Trade] = []

    def run(self, data: PriceData) -> PaperRunResult:
        df = data.df
        sig = self.strategy.generate(data)
        broker = SimBroker(self.cost, data.symbol)
        broker.connect()
        self.audit.log("info", f"Paper run started on {broker.name}", symbol=data.symbol,
                       strategy=self.strategy.name,
                       data={"source": data.source, "bars": len(df),
                             "WARNING": "SIMULATED FILLS" + (" ON MOCK DATA" if data.source.upper()=="MOCK" else "")})

        tf_secs = timeframe_delta(data.timeframe).total_seconds()
        idx = df.index
        pip = self.cost.pip_size

        eq_times, eq_values = [idx[0]], [self.risk.equity]
        current: Optional[dict] = None   # open trade bookkeeping
        prev_ts = idx[0]
        n_signals = int((sig["signal"] != 0).sum())
        c = {"entries": 0, "exits": 0, "blocked_news": 0, "blocked_session": 0,
             "blocked_risk": 0, "blocked_stale": 0, "blocked_kill": 0,
             "protective_failures": 0, "duplicates": 0}

        signals = sig["signal"].to_numpy()
        stop_dist = sig["stop_distance"].to_numpy()
        tgt_dist = sig["target_distance"].to_numpy()
        reasons = sig["reason"].to_numpy()

        def record_exit(exit_fill, ts):
            # book P&L, audit it, and free the position slot
            nonlocal current
            self._finalize_trade(current, exit_fill, broker, eq_times, eq_values, data)
            reason = getattr(broker, "_last_close_meta", {}).get("reason", "exit")
            self.audit.log("fill", f"EXIT ({reason}) {exit_fill.side.value} "
                           f"{exit_fill.quantity:.0f} @ {exit_fill.price}", symbol=data.symbol,
                           strategy=self.strategy.name, ts_utc=ts,
                           data={"simulated": True, "reason": reason})
            self.risk.open_positions = max(0, self.risk.open_positions - 1)
            c["exits"] += 1
            current = None

        for i in range(1, len(df)):
            ts = idx[i]
            bar = {k: float(df[k].iloc[i]) for k in ("open", "high", "low", "close")}
            broker.set_bar(ts, bar)   # simulated clock is now at this bar's OPEN

            # ---- 1. exits, in the SAME priority order as the backtester ----
            if current is not None:
                current["bars_held"] += 1
                direction = 1 if current["side"] == Side.LONG else -1
                # 1a. signal-based exit at the OPEN (opposite signal / time stop)
                opp = self.exit_on_opposite and signals[i - 1] == -direction
                timed = self.time_stop_bars > 0 and current["bars_held"] >= self.time_stop_bars
                if opp or timed:
                    exit_fill = broker.flatten(data.symbol, "opposite_signal" if opp else "time_stop")
                    if exit_fill is not None:
                        record_exit(exit_fill, ts)
                # 1b. otherwise the broker checks the protective stop / target intrabar
                if current is not None:
                    exit_fill = broker.check_exits()
                    if exit_fill is not None:
                        record_exit(exit_fill, ts)

            # ---- 2. reconciliation: our view must match the broker's ----
            broker_pos = len(broker.open_positions())
            our_pos = 1 if current is not None else 0
            if broker_pos != our_pos:
                self.audit.log("reconcile", f"Position mismatch broker={broker_pos} runner={our_pos}; "
                               "re-syncing to broker.", symbol=data.symbol, ts_utc=ts)
                if broker_pos == 0:
                    current = None
                    self.risk.open_positions = 0

            # ---- 3. staleness: gap since previous bar beyond one interval ----
            gap = (ts - prev_ts).total_seconds()
            data_age = max(0.0, gap - tf_secs)
            prev_ts = ts

            # ---- 4. consider entry (flat only) ----
            if current is None and signals[i - 1] != 0:
                desired = int(signals[i - 1])
                sd = float(stop_dist[i - 1])
                td = float(tgt_dist[i - 1])
                side = Side.LONG if desired > 0 else Side.SHORT
                client_id = f"{self.strategy.name}-{ts.isoformat()}"
                quote = broker.get_quote(data.symbol)
                spread_pips = (quote.ask - quote.bid) / pip

                self.audit.log("signal", f"{side.value} signal: {reasons[i-1]}",
                               symbol=data.symbol, strategy=self.strategy.name, ts_utc=ts,
                               data={"stop_distance": sd, "target_distance": td})

                # gates that are cheap / informational first
                if self.risk.kill_switch_active():
                    c["blocked_kill"] += 1
                    self.audit.log("kill", "Entry blocked: kill switch active.", ts_utc=ts, symbol=data.symbol)
                    continue
                if self.use_session and not self.strategy.spec.in_session(ts):
                    c["blocked_session"] += 1
                    continue
                if self.blackout is not None:
                    dec = self.blackout.check(ts.to_pydatetime())
                    if dec.blocked:
                        c["blocked_news"] += 1
                        self.audit.log("decision", f"Entry blocked by {dec.reason}",
                                       symbol=data.symbol, ts_utc=ts)
                        continue

                check = self.risk.pre_trade_check(
                    now=ts.to_pydatetime(), symbol=data.symbol,
                    risk_pct=float(self.strategy.spec.raw["sizing"]["risk_per_trade_pct"]),
                    stop_distance=sd, has_stop=True, has_target=(td > 0),
                    spread_pips=spread_pips, data_age_seconds=data_age, client_order_id=client_id,
                )
                if not check.approved:
                    if any("stale" in r for r in check.reasons):
                        c["blocked_stale"] += 1
                    elif any("duplicate" in r for r in check.reasons):
                        c["duplicates"] += 1
                    else:
                        c["blocked_risk"] += 1
                    self.audit.log("decision", f"Entry blocked: {check.rejection_summary}",
                                   symbol=data.symbol, ts_utc=ts)
                    continue

                # ---- submit bracket ----
                if (self.inject_fail_at is not None and i >= self.inject_fail_at
                        and not self._fail_used):
                    broker.force_reject_protective = True
                    self._fail_used = True
                units = check.sizing.units
                entry_raw = bar["open"]
                entry_fill_px = entry_raw + (self.cost.half_spread_price + self.cost.slippage_price) \
                    if desired > 0 else entry_raw - (self.cost.half_spread_price + self.cost.slippage_price)
                stop_px = entry_fill_px - sd if desired > 0 else entry_fill_px + sd
                tgt_px = (entry_fill_px + td if desired > 0 else entry_fill_px - td) if td > 0 else None

                result = broker.submit_bracket(data.symbol, side, units, stop_px, tgt_px, client_id)
                self.audit.log("order", f"Submitted bracket {side.value} {units:.0f} "
                               f"stop={stop_px:.5f} target={tgt_px}", symbol=data.symbol,
                               strategy=self.strategy.name, ts_utc=ts,
                               data={"accepted": result.accepted, "stop_accepted": result.stop_accepted})

                if not result.accepted:
                    self.audit.log("error", f"Entry rejected: {result.reject_reason}",
                                   symbol=data.symbol, ts_utc=ts)
                    continue

                self.audit.log("fill", f"ENTRY {side.value} {units:.0f} @ {result.entry_fill.price}",
                               symbol=data.symbol, strategy=self.strategy.name, ts_utc=ts,
                               data={"simulated": True})

                current = {
                    "side": side, "units": units, "raw_entry": entry_raw,
                    "entry_fill": result.entry_fill.price, "entry_time": ts, "bars_held": 0,
                }

                # ---- protective-stop failure path ----
                if not result.stop_accepted:
                    c["protective_failures"] += 1
                    self.audit.log("error", "PROTECTIVE STOP REJECTED -> flattening and "
                                   "blocking all further entries (kill condition).",
                                   symbol=data.symbol, ts_utc=ts)
                    flat = broker.flatten(data.symbol, "protective_stop_rejected")
                    if flat is not None:
                        self.audit.log("fill", f"EMERGENCY FLATTEN @ {flat.price}",
                                       symbol=data.symbol, ts_utc=ts, data={"simulated": True})
                        # The flatten is a real (simulated) round trip: it costs spread,
                        # slippage and commission, so it MUST hit equity like any trade.
                        # It is not counted in c["entries"], which counts protected entries.
                        self._finalize_trade(current, flat, broker, eq_times, eq_values, data)
                    self.risk.block_entries("protective stop was rejected by broker")
                    current = None
                    continue

                self.risk.open_positions += 1
                c["entries"] += 1

                # ---- the entry bar itself: the price can reach the stop/target in the
                # remainder of this bar, after our fill at the open ----
                exit_fill = broker.check_exits()
                if exit_fill is not None:
                    record_exit(exit_fill, ts)

        # close any residual position at the last bar's CLOSE (same as the backtester)
        if current is not None:
            broker.mark_bar_close()
            flat = broker.flatten(data.symbol, "end_of_data")
            if flat is not None:
                record_exit(flat, idx[-1])

        equity_curve = pd.Series(eq_values, index=pd.DatetimeIndex(eq_times), name="equity")
        self.audit.log("info", "Paper run finished.", symbol=data.symbol,
                       strategy=self.strategy.name,
                       data={"ending_equity": self.risk.equity, **c})

        return PaperRunResult(
            strategy_name=self.strategy.name, symbol=data.symbol,
            starting_equity=self.risk.config.starting_equity, ending_equity=self.risk.equity,
            trades=self._trades, equity_curve=equity_curve,
            entries_blocked_latched=self.risk.entries_blocked, block_reason=self.risk.block_reason,
            counts={"signals": n_signals, **c},
        )

    def _finalize_trade(self, current, exit_fill, broker, eq_times, eq_values, data):
        direction = 1 if current["side"] == Side.LONG else -1
        units = current["units"]
        entry_fill = current["entry_fill"]
        fill_pnl = (exit_fill.price - entry_fill) * units * direction
        nights = count_rollovers(current["entry_time"], exit_fill.timestamp, self.cost.rollover_hour_utc)
        swap = self.cost.swap(units, direction, nights)
        commission = self.cost.commission(units)
        net = fill_pnl + swap - commission
        gross = (exit_fill.price - current["raw_entry"]) * units * direction
        self.risk.register_fill_pnl(net)
        self._trades.append(Trade(
            symbol=data.symbol, side=current["side"], entry_time=current["entry_time"],
            exit_time=exit_fill.timestamp, entry_price=entry_fill, exit_price=exit_fill.price,
            quantity=units, gross_pnl=gross, costs=gross - net, net_pnl=net,
            bars_held=current["bars_held"], exit_reason=getattr(broker, "_last_close_meta", {}).get("reason", "exit"),
        ))
        eq_times.append(exit_fill.timestamp)
        eq_values.append(self.risk.equity)
