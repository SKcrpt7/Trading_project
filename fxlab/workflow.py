"""The research workflow as plain functions - one per step.

Both front ends call THIS module: the CLI (fxlab/cli.py) prints the results, the
dashboard (streamlit_app.py) draws them. Keeping the logic here means the two can
never disagree about how a review or paper run is assembled.

    load_configs -> load_data -> run_dev_backtest -> run_review -> run_paper

Hold-out discipline is built in:
  * run_dev_backtest only ever sees the development slice (first dev_fraction).
  * run_review is the single place the hold-out is judged, and every call is
    written to the review ledger (fxlab/journal.py) so re-use is visible.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from fxlab import config, journal
from fxlab.backtest import metrics as metrics_mod
from fxlab.backtest.engine import BacktestResult
from fxlab.backtest.metrics import Metrics
from fxlab.data.interface import CsvPriceProvider, PriceData
from fxlab.pipeline import run_backtest

DEFAULT_STRATEGY = "strategy_eurusd_trend.yaml"


# --------------------------------------------------------------------------- #
# Configs & data
# --------------------------------------------------------------------------- #
def load_configs(strategy_file: str = DEFAULT_STRATEGY) -> dict[str, dict]:
    return {
        "strategy_file": strategy_file,
        "strategy": config.load_yaml(strategy_file),
        "risk": config.load_yaml("risk.yaml"),
        "backtest": config.load_yaml("backtest.yaml"),
        "news": config.load_yaml("news.yaml"),
        "thresholds": config.load_yaml("review_thresholds.yaml"),
    }


def load_data(cfg: dict, data_path: Optional[str | Path] = None,
              start: Optional[str] = None, end: Optional[str] = None) -> PriceData:
    path = Path(data_path) if data_path else config.SAMPLE_PRICES
    s = cfg["strategy"]
    return CsvPriceProvider(path).load(s["symbol"], s["timeframe"], start=start, end=end)


def split(data: PriceData, cfg: dict) -> tuple[PriceData, PriceData]:
    """(development, hold-out) - chronological, using backtest.yaml's dev_fraction."""
    return data.split_chronological(cfg["backtest"]["evaluation"]["dev_fraction"])


def strategy_params(cfg: dict) -> dict[str, Any]:
    """The parameter snapshot stored with every run (what produced this result?)."""
    s = cfg["strategy"]
    return {k: s.get(k) for k in ("entry", "exit", "sizing", "session", "news")}


def backtest(data: PriceData, cfg: dict, use_blackout: bool = True) -> BacktestResult:
    return run_backtest(data, cfg["strategy"], cfg["risk"], cfg["backtest"],
                        news_cfg=cfg["news"], sample_events_path=config.SAMPLE_EVENTS,
                        use_blackout=use_blackout)


def metrics_dict(m: Metrics) -> dict[str, Any]:
    d = m.as_dict()
    if d.get("profit_factor") == float("inf"):
        d["profit_factor"] = 999.0   # JSON has no infinity
    return d


# --------------------------------------------------------------------------- #
# Step: dev backtest (tuning) - never sees the hold-out
# --------------------------------------------------------------------------- #
@dataclass
class DevRun:
    result: BacktestResult
    metrics: Metrics
    dev_start: pd.Timestamp
    dev_end: pd.Timestamp
    holdout_start: pd.Timestamp


def run_dev_backtest(cfg: dict, data: PriceData, record: bool = True) -> DevRun:
    dev, hold = split(data, cfg)
    res = backtest(dev, cfg)
    m = metrics_mod.compute(res)
    if record:
        journal.record_run(kind="dev", strategy=cfg["strategy"]["name"],
                           version=str(cfg["strategy"].get("version", "0")),
                           data_fp=journal.data_fingerprint(data),
                           params=strategy_params(cfg), metrics=metrics_dict(m))
    return DevRun(res, m, dev.df.index[0], dev.df.index[-1], hold.df.index[0])


# --------------------------------------------------------------------------- #
# Step: final review - the ONE place the hold-out is judged
# --------------------------------------------------------------------------- #
@dataclass
class ReviewOutcome:
    review: Any                    # fxlab.review.report.StrategyReview
    dev_metrics: Metrics
    eval_metrics: Metrics
    eval_result: BacktestResult
    walk_forward: Any              # WalkForwardReport
    sensitivity: list
    cost_stress: Optional[Metrics]
    markdown: str
    prior_holdout_uses: int        # uses BEFORE this run
    md_path: Optional[Path] = None
    json_path: Optional[Path] = None


def run_review(cfg: dict, data: PriceData, save: bool = True) -> ReviewOutcome:
    from fxlab.backtest.robustness import cost_stress, sensitivity, walk_forward
    from fxlab.review.report import build_review, render_markdown

    s = cfg["strategy"]
    fp = journal.data_fingerprint(data)
    prior = journal.holdout_uses(s["name"], fp)

    dev, evl = split(data, cfg)
    dev_res, eval_res = backtest(dev, cfg), backtest(evl, cfg)
    dev_m, eval_m = metrics_mod.compute(dev_res), metrics_mod.compute(eval_res)
    wf = walk_forward(data, s, cfg["risk"], cfg["backtest"])
    sens = sensitivity(dev, s, cfg["risk"], cfg["backtest"])
    cs = cost_stress(evl, s, cfg["risk"], cfg["backtest"])

    review = build_review(scfg=s, thresholds=cfg["thresholds"], dev_metrics=dev_m,
                          eval_metrics=eval_m, walk_forward=wf, sensitivity_rows=sens,
                          cost_stress_metrics=cs, data_source=data.source)
    md = render_markdown(review, eval_res.assumptions)
    out = ReviewOutcome(review, dev_m, eval_m, eval_res, wf, sens, cs, md, prior)

    if save:
        rdir = Path(config.REPORTS_DIR)
        rdir.mkdir(parents=True, exist_ok=True)
        out.md_path = rdir / f"review_{s['name']}.md"
        out.json_path = rdir / f"review_{s['name']}.json"
        out.md_path.write_text(md, encoding="utf-8")
        out.json_path.write_text(json.dumps({
            "decision": review.decision.value, "reasons": review.reasons,
            "version": str(s.get("version", "0")), "data": fp,
            "evidence": review.evidence,
        }, indent=2, default=str), encoding="utf-8")
        journal.record_review(strategy=s["name"], version=str(s.get("version", "0")),
                              data_fp=fp, decision=review.decision.value,
                              reasons=review.reasons)
    return out


# --------------------------------------------------------------------------- #
# Step: paper simulation
# --------------------------------------------------------------------------- #
@dataclass
class PaperOutcome:
    result: Any                    # PaperRunResult
    backtest_result: BacktestResult
    backtest_metrics: Metrics
    paper_metrics: Metrics
    daily: pd.DataFrame
    on_holdout: bool
    audit_rows: int = 0


def run_paper(cfg: dict, data: PriceData, full: bool = False,
              inject_failure_at: Optional[int] = None, record: bool = True) -> PaperOutcome:
    from fxlab.audit.store import AuditStore
    from fxlab.backtest.costs import CostModel
    from fxlab.paper.runner import PaperRunner
    from fxlab.pipeline import build_strategy, build_strategy_blackout
    from fxlab.risk.manager import RiskConfig

    s = cfg["strategy"]
    fp = journal.data_fingerprint(data)
    if not full:
        _, data = split(data, cfg)   # default: the hold-out slice, i.e. "forward" data

    cost = CostModel.from_config(cfg["backtest"], cfg["risk"]["pip_size"][s["symbol"]])
    audit = AuditStore(config.AUDIT_DB)
    try:
        runner = PaperRunner(
            strategy=build_strategy(s), cost_model=cost,
            risk_config=RiskConfig.from_config(cfg["risk"]), audit=audit,
            blackout=build_strategy_blackout(s, cfg["news"], config.SAMPLE_EVENTS),
            use_session=s["session"]["enabled"],
            time_stop_bars=s["exit"]["time_stop_bars"],
            exit_on_opposite_signal=s["exit"]["exit_on_opposite_signal"],
            inject_protective_failure_at=inject_failure_at,
        )
        res = runner.run(data)

        bt = backtest(data, cfg)
        btm = metrics_mod.compute(bt)
        pm = metrics_mod.compute(type("R", (), {
            "trades": res.trades, "starting_equity": res.starting_equity,
            "equity_curve": res.equity_curve})())
        audit.log("info", "Backtest-vs-paper comparison",
                  data={"backtest": metrics_dict(btm), "paper": metrics_dict(pm)})

        rows = [{"date": t.exit_time.date(), "net": t.net_pnl} for t in res.trades]
        daily = (pd.DataFrame(rows).groupby("date").agg(trades=("net", "size"), net=("net", "sum"))
                 .reset_index() if rows else pd.DataFrame(columns=["date", "trades", "net"]))
        if len(daily):
            daily["net"] = daily["net"].round(2)
            audit.log("info", "Daily summary",
                      data={str(r.date): {"trades": int(r.trades), "net": float(r.net)}
                            for r in daily.itertuples()})
        n_rows = audit.count()
    finally:
        audit.close()

    if record:
        journal.record_run(kind="paper", strategy=s["name"], version=str(s.get("version", "0")),
                           data_fp=fp, params=strategy_params(cfg), metrics=metrics_dict(pm),
                           extra={"slice": "full" if full else "holdout",
                                  "counts": res.counts,
                                  "entries_blocked_latched": res.entries_blocked_latched})
    return PaperOutcome(res, bt, btm, pm, daily, not full, n_rows)


# --------------------------------------------------------------------------- #
# Operations: kill switch, status
# --------------------------------------------------------------------------- #
def kill_switch_path(cfg: dict) -> Path:
    return config.PROJECT_ROOT / cfg["risk"]["controls"]["kill_switch_file"]


def kill_switch_active(cfg: dict) -> bool:
    return kill_switch_path(cfg).exists()


def set_kill_switch(cfg: dict, active: bool, who: str = "dashboard") -> None:
    """Create/remove the kill-switch file and record the change in the audit log."""
    from fxlab.audit.store import AuditStore
    p = kill_switch_path(cfg)
    if active:
        p.write_text(f"Kill switch activated from {who} at "
                     f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\n",
                     encoding="utf-8")
    elif p.exists():
        p.unlink()
    audit = AuditStore(config.AUDIT_DB)
    try:
        audit.log("kill", f"Kill switch {'ACTIVATED' if active else 'deactivated'} ({who})")
    finally:
        audit.close()


def event_calendar(cfg: dict):
    from fxlab.econ.events import EventCalendar
    return EventCalendar.from_config(cfg["news"], config.SAMPLE_EVENTS)
