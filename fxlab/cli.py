"""Command-line interface for the whole workflow.

Commands:
  fxlab gen-sample            Generate the MOCK sample dataset.
  fxlab quality               Print the data-quality report.
  fxlab events                Show upcoming economic events (UTC + America/Toronto).
  fxlab dev                   Backtest on the DEVELOPMENT slice only - use this to tune.
  fxlab backtest              Backtest on ALL data (includes the hold-out; not for tuning).
  fxlab report                Run the full review (split, walk-forward, sensitivity,
                              cost stress) and emit a reject/investigate/eligible report.
                              This judges the hold-out - run it once per idea.
  fxlab paper                 Run the paper-trading simulation (labelled simulated fills)
                              and compare it to the backtest.
  fxlab status                Show the operational status view.

Every command accepts --strategy <file> (any config/strategy_*.yaml; default:
strategy_eurusd_trend.yaml). Nothing here places a real order.

The logic lives in fxlab/workflow.py, shared with the dashboard (streamlit_app.py).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fxlab import config, journal, workflow
from fxlab.config import DISPLAY_TZ, REPORTS_DIR


def _cfg(args) -> dict:
    return workflow.load_configs(getattr(args, "strategy", None) or workflow.DEFAULT_STRATEGY)


def _data(args, cfg):
    return workflow.load_data(cfg, getattr(args, "data", None),
                              start=getattr(args, "start", None), end=getattr(args, "end", None))


def _print_backtest(res, m):
    print(f"  Signals={res.n_signals}  blocked(news/session/risk)="
          f"{res.n_blocked_news}/{res.n_blocked_session}/{res.n_blocked_risk}")
    print(f"  Trades={m.trade_count}  NetReturn={m.net_return_pct}%  PF={m.profit_factor}  "
          f"MaxDD={m.max_drawdown_pct}%")
    print(f"  WinRate={m.win_rate_pct}%  Avg/trade={m.avg_pnl_per_trade}  "
          f"WorstLosingStreak={m.max_losing_streak}  Costs={m.total_costs}")
    print("  By year:", m.by_year)
    print("\nAssumptions:")
    for a in res.assumptions:
        print(f"   - {a}")


# --------------------------------------------------------------------------- #
def cmd_gen_sample(args):
    import runpy
    runpy.run_path(str(config.PROJECT_ROOT / "scripts" / "generate_sample_data.py"),
                   run_name="__main__")


def cmd_quality(args):
    cfg = _cfg(args)
    print(_data(args, cfg).quality().summary())


def cmd_events(args):
    cfg = _cfg(args)
    cal = workflow.event_calendar(cfg)
    now = datetime.now(timezone.utc)
    print(f"Loaded {len(cal)} events. Showing next {args.hours}h from now (UTC + {DISPLAY_TZ}).")
    upcoming = cal.upcoming(now, within_hours=args.hours, min_impact="high")
    if not upcoming:
        # fall back to showing the first few in the file (sample data may be historical)
        print("(no future events within window; showing first 10 events in the dataset)")
        upcoming = cal.events[:10]
    tz = ZoneInfo(DISPLAY_TZ)
    for e in upcoming:
        local = e.time_utc.astimezone(tz)
        exact = "exact" if e.time_is_exact else "CONVENTIONAL"
        print(f"  {e.time_utc:%Y-%m-%d %H:%M}Z | {local:%Y-%m-%d %H:%M %Z} | "
              f"{e.country} {e.title} [{e.impact}] ({exact}, src={e.source})")


def cmd_dev(args):
    cfg = _cfg(args)
    run = workflow.run_dev_backtest(cfg, _data(args, cfg))
    s = cfg["strategy"]
    print(f"\nDEV backtest: {s['name']} v{s['version']}  {s['symbol']} {s['timeframe']}  "
          f"(source={run.result.source})")
    print(f"  Development slice: {run.dev_start:%Y-%m-%d %H:%M} -> {run.dev_end:%Y-%m-%d %H:%M} UTC"
          f"   (hold-out from {run.holdout_start:%Y-%m-%d %H:%M} is NOT used)")
    if run.result.source.upper() == "MOCK":
        print("  *** MOCK DATA - not real markets ***")
    _print_backtest(run.result, run.metrics)


def cmd_backtest(args):
    from fxlab.backtest import metrics
    cfg = _cfg(args)
    data = _data(args, cfg)
    res = workflow.backtest(data, cfg)
    m = metrics.compute(res)
    print(f"\nBacktest: {res.strategy_name}  {res.symbol} {res.timeframe}  (source={res.source})")
    print("  NOTE: this run INCLUDES the hold-out slice. Tune with `fxlab dev` instead.")
    if res.source.upper() == "MOCK":
        print("  *** MOCK DATA - not real markets ***")
    _print_backtest(res, m)
    if args.save:
        out = REPORTS_DIR / "backtest_trades.csv"
        res.trades_dataframe().to_csv(out, index=False)
        print(f"\nTrade log saved -> {out}")


def cmd_report(args):
    cfg = _cfg(args)
    data = _data(args, cfg)
    dev, evl = workflow.split(data, cfg)
    print(f"Chronological split: dev={len(dev.df)} bars, evaluation(hold-out)={len(evl.df)} bars")
    out = workflow.run_review(cfg, data)
    if out.prior_holdout_uses:
        print(f"  WARNING: '{cfg['strategy']['name']}' had already been judged on this hold-out "
              f"{out.prior_holdout_uses} time(s). Each re-run after tweaking weakens the result.")

    print("\n" + "=" * 70)
    print(f"DECISION: {out.review.decision.value}")
    print("=" * 70)
    for r in out.review.reasons:
        print(f"  - {r}")
    print(f"\nFull report -> {out.md_path}")
    print(f"Evidence    -> {out.json_path}")


def cmd_paper(args):
    cfg = _cfg(args)
    out = workflow.run_paper(cfg, _data(args, cfg), full=getattr(args, "full", False),
                             inject_failure_at=getattr(args, "inject_failure_at", None))
    res, btm, pm = out.result, out.backtest_metrics, out.paper_metrics

    print(f"\nPAPER (SIMULATED FILLS) - {res.strategy_name} {res.symbol}")
    if out.backtest_result.source.upper() == "MOCK":
        print("  *** MOCK DATA + SIMULATED FILLS - not real ***")
    print(f"  Start equity: {res.starting_equity}  End equity: {round(res.ending_equity,2)}  "
          f"Net: {res.net_return_pct}%")
    print(f"  Counts: {res.counts}")
    if res.entries_blocked_latched:
        print(f"  !! ENTRIES LATCH-BLOCKED: {res.block_reason}")

    print("\n  Expected (backtest) vs Observed (paper) on this slice:")
    print(f"    trades        : backtest {btm.trade_count:>6}  | paper {pm.trade_count:>6}")
    print(f"    net return %  : backtest {btm.net_return_pct:>6}  | paper {pm.net_return_pct:>6}")
    print(f"    profit factor : backtest {btm.profit_factor:>6}  | paper {pm.profit_factor:>6}")

    if len(out.daily):
        print("\n  Daily summary (most recent active days):")
        for r in out.daily.tail(10).itertuples():
            print(f"    {r.date}  trades={r.trades:>2}  net={r.net:>9}")
    print(f"\n  Audit log rows: {out.audit_rows} (db: {config.AUDIT_DB.name})")


def cmd_status(args):
    from fxlab.audit.store import AuditStore
    cfg = _cfg(args)
    s = cfg["strategy"]
    print("=" * 66)
    print(" fxlab status view")
    print("=" * 66)
    print(f" Strategy      : {s['name']} v{s['version']} ({s['symbol']} {s['timeframe']})")
    print(" Live trading  : DISABLED (paper/simulation only)")
    try:
        data = _data(args, cfg)
        q = data.quality()
        print(f" Data health   : {q.n_bars:,} bars, completeness {q.completeness_pct}%, "
              f"gaps={len(q.missing_periods)}, source={q.source}")
        last = journal.latest_decision(s["name"], data_fp=journal.data_fingerprint(data))
        print(f" Last review   : " + (f"{last['decision']} (v{last['version']}, {last['ts_utc']})"
                                       if last else "none yet - run `fxlab report`"))
    except Exception as exc:
        print(f" Data health   : ERROR {exc}")
    ks = workflow.kill_switch_active(cfg)
    print(f" Kill switch   : {'ACTIVE (new entries halted)' if ks else 'inactive'}")
    up = workflow.event_calendar(cfg).upcoming(datetime.now(timezone.utc), 48, "high")
    print(f" Next events   : {len(up)} high-impact in 48h"
          + (f" (next: {up[0].title} {up[0].time_utc:%Y-%m-%d %H:%M}Z)" if up else ""))
    if config.AUDIT_DB.exists():
        audit = AuditStore(config.AUDIT_DB)
        print(f" Audit rows    : {audit.count()}  "
              f"(signals={audit.count('signal')}, orders={audit.count('order')}, "
              f"fills={audit.count('fill')}, errors={audit.count('error')})")
        errs = audit.recent(3, "error")
        if errs:
            print(" Recent errors :")
            for e in errs:
                print(f"    [{e['ts_utc']}] {e['message']}")
        audit.close()
    else:
        print(" Audit rows    : (none yet - run `fxlab paper`)")
    print("=" * 66)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fxlab", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def add_strategy(sp):
        sp.add_argument("--strategy", help="strategy file in config/ (default: "
                        f"{workflow.DEFAULT_STRATEGY})")

    def add_common(sp):
        add_strategy(sp)
        sp.add_argument("--data", help="path to a price CSV (default: bundled sample)")
        sp.add_argument("--start", help="UTC start (e.g. 2022-01-01)")
        sp.add_argument("--end", help="UTC end")

    sub.add_parser("gen-sample", help="generate MOCK sample data").set_defaults(func=cmd_gen_sample)
    sp = sub.add_parser("quality", help="data-quality report"); add_common(sp); sp.set_defaults(func=cmd_quality)
    sp = sub.add_parser("events", help="show upcoming economic events"); add_strategy(sp)
    sp.add_argument("--hours", type=int, default=72); sp.set_defaults(func=cmd_events)
    sp = sub.add_parser("dev", help="backtest on the development slice only (for tuning)")
    add_common(sp); sp.set_defaults(func=cmd_dev)
    sp = sub.add_parser("backtest", help="run a backtest on all data"); add_common(sp)
    sp.add_argument("--save", action="store_true", help="save trade log CSV"); sp.set_defaults(func=cmd_backtest)
    sp = sub.add_parser("report", help="run full review -> decision"); add_common(sp); sp.set_defaults(func=cmd_report)
    sp = sub.add_parser("paper", help="run paper simulation"); add_common(sp)
    sp.add_argument("--full", action="store_true", help="run on all data (default: hold-out slice)")
    sp.add_argument("--inject-failure-at", type=int, dest="inject_failure_at",
                    help="(test) force a protective-stop rejection at this bar index")
    sp.set_defaults(func=cmd_paper)
    sp = sub.add_parser("status", help="operational status view"); add_common(sp); sp.set_defaults(func=cmd_status)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
