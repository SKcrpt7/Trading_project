"""Step 4 - Final review: the ONE place the hold-out is judged. Guarded and logged."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import ui_common
from fxlab import config, journal, workflow

c = ui_common.cfg()
s = c["strategy"]
name, version = s["name"], str(s.get("version", "0"))
data = ui_common.data(c)
fp = journal.data_fingerprint(data)
uses = journal.holdout_uses(name, fp)
past = journal.reviews(name, fp)
dev_runs = [r for r in journal.runs("dev", name) if r["version"] == version and r["data"] == fp]

# ---- the guard ------------------------------------------------------------ #
with st.container(border=True):
    st.markdown(f"**{name} v{version}** on `{ui_common.data_path().name}`")
    if uses == 0:
        st.markdown(":material/lock: The hold-out is **untouched** for this strategy. "
                    "The review is your one honest look at unseen data.")
    else:
        st.markdown(f":material/lock_open: The hold-out has already been judged **{uses} time(s)** "
                    f"for this strategy (last: v{past[-1]['version']} → {past[-1]['decision']}).")

ack = True
if uses:
    st.warning("If you changed parameters *because of* an earlier review, running it again "
               "fits the strategy to the hold-out, and a pass would no longer mean much. "
               "Re-running is fine to reproduce a report, or after a change you decided on "
               "for reasons that had nothing to do with that result.",
               icon=":material/warning:", title="Re-using the hold-out")
    ack = st.checkbox("I understand this re-uses the hold-out, and the run will be logged.")
if not dev_runs:
    st.caption(":material/info: You haven't dev-tested this version yet. Usually you'd tune on "
               "the *Dev backtest* page first.")

run_key = f"review:{st.session_state.strategy_file}:{version}:{ui_common.data_path()}"
if st.button("Run final review", icon=":material/gavel:", type="primary", disabled=not ack,
             key="run_review"):
    with st.status("Running the review...", expanded=True) as status:
        st.write("Backtesting the development and hold-out slices, walk-forward windows, "
                 "parameter sensitivity and doubled costs...")
        out = workflow.run_review(c, data)
        status.update(label=f"Review finished: {out.review.decision.value}", state="complete",
                      expanded=False)
    st.session_state.review_run = (run_key, out)
    st.rerun()   # redraw so the guard above reflects this run being in the ledger

stored = st.session_state.get("review_run")
out = stored[1] if stored and stored[0] == run_key else None

# ---- results -------------------------------------------------------------- #
if out is None:
    saved = Path(config.REPORTS_DIR) / f"review_{name}.md"
    if saved.exists():
        st.subheader("Last saved review")
        meta = Path(config.REPORTS_DIR) / f"review_{name}.json"
        if meta.exists():
            j = json.loads(meta.read_text(encoding="utf-8"))
            ui_common.decision_banner(j["decision"], j["reasons"])
            st.caption(f"Saved report for v{j.get('version', '?')}. Run the review again "
                       "only for the reasons above.")
        with st.expander("Full saved report", icon=":material/article:"):
            st.markdown(saved.read_text(encoding="utf-8"))
    else:
        st.caption("No review yet for this strategy.")
else:
    rv = out.review
    if rv.is_mock:
        st.caption(":material/warning: Judged on MOCK data - a demonstration of the gates, not a verdict on a real edge.")
    ui_common.decision_banner(rv.decision.value, rv.reasons)
    st.caption("A pass only means the strategy may move on to **paper** trading. It is not "
               "permission to trade real money and not a prediction of profit.")

    st.subheader("Evaluation (hold-out) results")
    ui_common.metric_row(out.eval_metrics)

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Reject gates** (any failure → REJECT)")
        st.dataframe(pd.DataFrame([{"pass": g.passed, "gate": g.name, "detail": g.detail}
                                   for g in rv.reject_gates]),
                     hide_index=True, alt="Reject gates and whether each passed",
                     column_config={"pass": st.column_config.CheckboxColumn()})
    with g2:
        st.markdown("**Eligibility gates** (all must pass → eligible)")
        st.dataframe(pd.DataFrame([{"pass": g.passed, "gate": g.name, "detail": g.detail}
                                   for g in rv.eligible_gates]),
                     hide_index=True, alt="Eligibility gates and whether each passed",
                     column_config={"pass": st.column_config.CheckboxColumn()})
    st.caption("Thresholds live in `config/review_thresholds.yaml`. Loosening them to get a "
               "pass defeats their purpose.")

    st.subheader("Development vs hold-out")
    keys = [("trade_count", "Trades"), ("net_return_pct", "Net return %"),
            ("profit_factor", "Profit factor"), ("max_drawdown_pct", "Max drawdown %"),
            ("win_rate_pct", "Win rate %"), ("avg_pnl_per_trade", "Avg P&L / trade"),
            ("max_losing_streak", "Worst losing streak")]
    dm, em = out.dev_metrics.as_dict(), out.eval_metrics.as_dict()
    from fxlab.backtest.metrics import METRIC_LIMITATIONS
    st.dataframe(pd.DataFrame([{"metric": lbl, "development": dm[k], "hold-out": em[k],
                                "what it can't tell you": METRIC_LIMITATIONS.get(k, "")}
                               for k, lbl in keys]),
                 hide_index=True, alt="Development versus hold-out metrics")
    st.caption("A big drop from development to hold-out is the classic sign of overfitting.")

    w1, w2 = st.columns(2)
    with w1:
        st.markdown(f"**Walk-forward** · {out.walk_forward.positive_fraction:.0%} of "
                    f"{len(out.walk_forward.windows)} windows profitable")
        wf = pd.DataFrame([w.__dict__ for w in out.walk_forward.windows])
        if len(wf):
            wf["window"] = wf["index"] + 1
            ui_common.signed_bar_chart(wf, "window", "net_return_pct", "Window", "Net return %",
                                       alt_text="Net return of each walk-forward window")
            st.dataframe(wf[["window", "start", "end", "trades", "net_return_pct", "profit_factor"]],
                         hide_index=True, alt="Walk-forward windows")
    with w2:
        cs = out.cost_stress
        st.markdown("**Cost stress** · doubled spread and slippage on the hold-out")
        if cs is not None:
            st.metric("Net return with doubled costs", f"{cs.net_return_pct:+.2f}%",
                      help="If this is far worse than normal, costs are eating the edge.",
                      border=True)
        st.markdown("**Sensitivity** · nearby parameter values (development slice)")
        sens = pd.DataFrame([r.__dict__ for r in out.sensitivity])
        if len(sens):
            st.dataframe(sens, hide_index=True, alt="Results with each parameter nudged up or down")
        st.caption("A strategy that only works at one exact setting is fragile.")

    d1, d2 = st.columns(2)
    d1.download_button("Download report (Markdown)", out.markdown, f"review_{name}_v{version}.md",
                       "text/markdown", icon=":material/download:", width="stretch")
    if out.json_path and out.json_path.exists():
        d2.download_button("Download evidence (JSON)", out.json_path.read_text(encoding="utf-8"),
                           f"review_{name}_v{version}.json", "application/json",
                           icon=":material/download:", width="stretch")

if past:
    with st.expander(f"Review ledger for {name} ({len(past)})", icon=":material/receipt_long:"):
        st.dataframe(pd.DataFrame([{"time (UTC)": r["ts_utc"].replace("T", " ")[:16],
                                    "version": r["version"], "decision": r["decision"]}
                                   for r in reversed(past)]),
                     hide_index=True, alt="Every final review of this strategy on this dataset")
