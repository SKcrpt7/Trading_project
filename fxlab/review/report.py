"""Strategy review: turn evidence into a decision, with reasons shown.

Three outcomes only: REJECT, NEEDS_INVESTIGATION, ELIGIBLE_FOR_PAPER.
There is no 'eligible for live' - promotion to live is a human decision made
outside this tool, after extended paper trading. A passing review is NOT proof
of future profitability; it only means the strategy cleared conservative,
configurable evidence gates on the data we had.

Decision logic:
  1. If ANY hard reject gate trips (evaluated on the HOLD-OUT evaluation data)
     -> REJECT.
  2. Else if ALL eligibility gates pass -> ELIGIBLE_FOR_PAPER.
  3. Else -> NEEDS_INVESTIGATION (shows exactly which gates failed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fxlab.backtest.metrics import METRIC_LIMITATIONS, Metrics
from fxlab.types import Decision


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


@dataclass
class StrategyReview:
    strategy_name: str
    strategy_version: str
    symbol: str
    timeframe: str
    data_source: str
    decision: Decision
    reject_gates: list[GateResult] = field(default_factory=list)
    eligible_gates: list[GateResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return self.data_source.upper() == "MOCK"


def _pf(m: Metrics) -> float:
    return 999.0 if m.profit_factor == float("inf") else m.profit_factor


def build_review(
    *,
    scfg: dict,
    thresholds: dict,
    dev_metrics: Metrics,
    eval_metrics: Metrics,
    walk_forward,          # WalkForwardReport
    sensitivity_rows,      # list[SensitivityRow]
    cost_stress_metrics,   # Metrics | None
    data_source: str,
) -> StrategyReview:
    rej = thresholds["reject_if"]
    elig = thresholds["eligible_if"]
    m = eval_metrics  # gates are judged on the untouched evaluation slice

    # ----- hard reject gates -----
    reject_gates = [
        GateResult("min_trades", m.trade_count >= rej["min_trades_lt"],
                   f"{m.trade_count} trades (reject if < {rej['min_trades_lt']})"),
        GateResult("net_return_positive", m.net_return_pct > rej["net_return_pct_lt"],
                   f"net return {m.net_return_pct}% (reject if <= {rej['net_return_pct_lt']}%)"),
        GateResult("max_drawdown", m.max_drawdown_pct <= rej["max_drawdown_pct_gt"],
                   f"max drawdown {m.max_drawdown_pct}% (reject if > {rej['max_drawdown_pct_gt']}%)"),
        GateResult("profit_factor", _pf(m) >= rej["profit_factor_lt"],
                   f"profit factor {_pf(m)} (reject if < {rej['profit_factor_lt']})"),
    ]
    reject_triggered = [g for g in reject_gates if not g.passed]

    # ----- eligibility gates -----
    wf_frac = walk_forward.positive_fraction if walk_forward else 0.0
    cs_ret = cost_stress_metrics.net_return_pct if cost_stress_metrics else None
    oos_pf = _pf(eval_metrics)

    eligible_gates = [
        GateResult("min_trades", m.trade_count >= elig["min_trades_gte"],
                   f"{m.trade_count} >= {elig['min_trades_gte']}"),
        GateResult("net_return", m.net_return_pct >= elig["net_return_pct_gte"],
                   f"{m.net_return_pct}% >= {elig['net_return_pct_gte']}%"),
        GateResult("profit_factor", oos_pf >= elig["profit_factor_gte"],
                   f"{oos_pf} >= {elig['profit_factor_gte']}"),
        GateResult("max_drawdown", m.max_drawdown_pct <= elig["max_drawdown_pct_lte"],
                   f"{m.max_drawdown_pct}% <= {elig['max_drawdown_pct_lte']}%"),
        GateResult("oos_profit_factor", oos_pf >= elig["oos_profit_factor_gte"],
                   f"OOS PF {oos_pf} >= {elig['oos_profit_factor_gte']}"),
        GateResult("walk_forward", wf_frac >= elig["walk_forward_positive_window_fraction_gte"],
                   f"{wf_frac} of windows positive >= "
                   f"{elig['walk_forward_positive_window_fraction_gte']}"),
    ]
    if cs_ret is not None:
        eligible_gates.append(GateResult(
            "cost_stress", cs_ret >= elig["cost_stress_net_return_pct_gte"],
            f"stressed net return {cs_ret}% >= {elig['cost_stress_net_return_pct_gte']}%"))

    # ----- decide -----
    reasons: list[str] = []
    if reject_triggered:
        decision = Decision.REJECT
        reasons = [f"REJECT gate failed: {g.detail}" for g in reject_triggered]
    elif all(g.passed for g in eligible_gates):
        decision = Decision.ELIGIBLE_FOR_PAPER
        reasons = ["All eligibility gates passed on the hold-out evaluation data."]
    else:
        decision = Decision.NEEDS_INVESTIGATION
        reasons = [f"eligibility gate not met: {g.detail}"
                   for g in eligible_gates if not g.passed]

    evidence = {
        "dev": dev_metrics.as_dict(),
        "evaluation": eval_metrics.as_dict(),
        "walk_forward_positive_fraction": wf_frac,
        "walk_forward_windows": len(walk_forward.windows) if walk_forward else 0,
        "cost_stress_net_return_pct": cs_ret,
        "sensitivity": [r.__dict__ for r in (sensitivity_rows or [])],
    }

    return StrategyReview(
        strategy_name=scfg["name"], strategy_version=str(scfg.get("version", "0")),
        symbol=scfg["symbol"], timeframe=scfg["timeframe"], data_source=data_source,
        decision=decision, reject_gates=reject_gates, eligible_gates=eligible_gates,
        reasons=reasons, evidence=evidence,
    )


def render_markdown(review: StrategyReview, assumptions: list[str]) -> str:
    m = review.evidence["evaluation"]
    dev = review.evidence["dev"]
    L = []
    L.append(f"# Strategy Review — {review.strategy_name} v{review.strategy_version}")
    L.append("")
    if review.is_mock:
        L.append("> ⚠️ **MOCK DATA** — results come from synthetic sample data, "
                 "not real markets. For demonstration only.")
        L.append("")
    L.append(f"**Decision: `{review.decision.value}`**")
    L.append("")
    L.append("_A passing review means a strategy may advance to PAPER trading only. "
             "It is not permission to trade live money, and not a prediction of profit._")
    L.append("")
    L.append("## Why")
    for r in review.reasons:
        L.append(f"- {r}")
    L.append("")
    L.append(f"## Evidence (judged on untouched EVALUATION slice — {review.symbol} {review.timeframe})")
    L.append("")
    L.append("| Metric | Development | Evaluation (hold-out) | What it cannot tell you |")
    L.append("|---|---|---|---|")
    def row(key, label, limkey):
        L.append(f"| {label} | {dev.get(key)} | {m.get(key)} | {METRIC_LIMITATIONS.get(limkey,'')} |")
    row("trade_count", "Trade count", "trade_count")
    row("net_return_pct", "Net return %", "net_return_pct")
    row("max_drawdown_pct", "Max drawdown %", "max_drawdown_pct")
    row("profit_factor", "Profit factor", "profit_factor")
    row("avg_pnl_per_trade", "Avg P&L / trade", "avg_pnl_per_trade")
    row("win_rate_pct", "Win rate %", "win_rate_pct")
    row("max_losing_streak", "Max losing streak", "max_losing_streak")
    L.append("")
    L.append(f"- Walk-forward: {review.evidence['walk_forward_positive_fraction']} of "
             f"{review.evidence['walk_forward_windows']} out-of-sample windows positive.")
    L.append(f"- Cost stress (worse costs): net return "
             f"{review.evidence['cost_stress_net_return_pct']}%.")
    L.append("")
    L.append("### By year (evaluation)")
    for y, d in m.get("by_year", {}).items():
        L.append(f"- {y}: {d['trades']} trades, net {d['net_pnl']}")
    L.append("")
    L.append("### By session (evaluation)")
    for s, d in m.get("by_session", {}).items():
        L.append(f"- {s}: {d['trades']} trades, net {d['net_pnl']}")
    L.append("")
    L.append("## Reject gates")
    for g in review.reject_gates:
        L.append(f"- {'✅ pass' if g.passed else '❌ FAIL'} — {g.name}: {g.detail}")
    L.append("")
    L.append("## Eligibility gates")
    for g in review.eligible_gates:
        L.append(f"- {'✅' if g.passed else '⬜'} {g.name}: {g.detail}")
    L.append("")
    L.append("## Backtest assumptions & limitations")
    for a in assumptions:
        L.append(f"- {a}")
    L.append("")
    L.append("## Sensitivity (nearby parameter values)")
    L.append("| Param | Change | Value | Trades | Net % | PF |")
    L.append("|---|---|---|---|---|---|")
    for r in review.evidence["sensitivity"]:
        L.append(f"| {r['param']} | {r['change_pct']}% | {r['value']} | "
                 f"{r['trades']} | {r['net_return_pct']} | {r['profit_factor']} |")
    L.append("")
    return "\n".join(L)
