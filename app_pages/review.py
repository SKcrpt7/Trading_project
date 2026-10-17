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

ui_common.intro("review")

# ---- the guard ------------------------------------------------------------ #
with st.container(horizontal=True):
    st.badge(f"{name} · v{version}", icon=":material/tune:", color="blue")
    if uses == 0:
        st.badge("Hold-out untouched", icon=":material/lock:", color="green")
    else:
        st.badge(f"Hold-out used {uses}x", icon=":material/lock_open:", color="orange",
                 help=f"Last: v{past[-1]['version']} → {past[-1]['decision']}")

ack = True
if uses:
    st.warning("Re-running after changing settings *because of* a past review fits the strategy "
               "to the hold-out. Fine to reproduce a report; not to tune.",
               icon=":material/warning:")
    ack = st.checkbox("I understand - log this re-use.")
if not dev_runs:
    st.caption(":material/info: This version hasn't been dev-tested yet.")

run_key = f"review:{st.session_state.strategy_file}:{version}:{ui_common.data_path()}"
if st.button("Run final review", icon=":material/gavel:", type="primary", disabled=not ack,
             key="run_review"):
    with st.status("Running the review (about 10-30 s)...", expanded=True) as status:
        st.write("Hold-out · walk-forward · sensitivity · doubled costs")
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
        st.subheader("Last saved review", icon=":material/history:")
        meta = Path(config.REPORTS_DIR) / f"review_{name}.json"
        if meta.exists():
            j = json.loads(meta.read_text(encoding="utf-8"))
            ui_common.decision_banner(j["decision"], j["reasons"])
            st.caption(f"Saved report for v{j.get('version', '?')}.")
        with st.expander("Full saved report", icon=":material/article:"):
            st.markdown(saved.read_text(encoding="utf-8"))
    else:
        st.caption("No review yet for this strategy.")
else:
    rv = out.review
    ui_common.decision_banner(rv.decision.value, rv.reasons)
    st.caption("A pass means *paper trading only* - never permission to trade real money."
               + (" Judged on mock data." if rv.is_mock else ""))

    st.subheader("Hold-out results", icon=":material/lock:")
    ui_common.metric_row(out.eval_metrics)

    st.subheader("Gates", icon=":material/rule:",
                 help="Thresholds live in config/review_thresholds.yaml. Loosening them to get a "
                      "pass defeats their purpose.")
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Reject** · any failure rejects")
        st.dataframe(pd.DataFrame([{"pass": g.passed, "gate": g.name, "detail": g.detail}
                                   for g in rv.reject_gates]),
                     hide_index=True, alt="Reject gates and whether each passed",
                     column_config={"pass": st.column_config.CheckboxColumn()})
    with g2:
        st.markdown("**Eligibility** · all must pass")
        st.dataframe(pd.DataFrame([{"pass": g.passed, "gate": g.name, "detail": g.detail}
                                   for g in rv.eligible_gates]),
                     hide_index=True, alt="Eligibility gates and whether each passed",
                     column_config={"pass": st.column_config.CheckboxColumn()})

    st.subheader("Development vs hold-out", icon=":material/compare_arrows:",
                 help="A big drop from development to hold-out is the classic sign of overfitting.")
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

    st.subheader("Robustness", icon=":material/shield:")
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
        if cs is not None:
            st.metric("Doubled costs → net return", f"{cs.net_return_pct:+.2f}%",
                      help="Hold-out re-run with doubled spread and slippage. Far worse than "
                           "normal means costs are eating the edge.", border=True)
        st.markdown("**Sensitivity** · nearby settings",
                    help="Each parameter nudged ±10-20% on the development data. A strategy that "
                         "only works at one exact setting is fragile.")
        sens = pd.DataFrame([r.__dict__ for r in out.sensitivity])
        if len(sens):
            st.dataframe(sens, hide_index=True, alt="Results with each parameter nudged up or down")

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

ui_common.next_step("review")
