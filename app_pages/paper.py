"""Step 5 - Paper trading: simulated fills through the full live-style safety stack."""
import pandas as pd
import streamlit as st

import ui_common
from fxlab import journal, workflow

c = ui_common.cfg()
s = c["strategy"]
name, version = s["name"], str(s.get("version", "0"))
data = ui_common.data(c)
fp = journal.data_fingerprint(data)
decision = journal.latest_decision(name, version, fp)
kill_on = workflow.kill_switch_active(c)

st.caption("Replays bars through the same strategy, **risk manager** (daily loss limit, spread "
           "limit, stale data, duplicates, kill switch) and a **simulated broker**, logging "
           "every step to the audit log. All fills are simulated; nothing reaches a real broker.")

allowed = True
if decision is None or decision["decision"] != "ELIGIBLE_FOR_PAPER":
    status = decision["decision"] if decision else "not reviewed"
    st.warning(f"v{version} is **{status}**. In the real workflow only strategies marked "
               "ELIGIBLE move on to paper trading. You can still run it to see how paper "
               "trading works.", icon=":material/warning:", title="Not eligible for paper")
    allowed = st.checkbox("Run anyway as a demo")
if kill_on:
    st.error("Kill switch is ON, so every entry will be blocked. Turn it off on the Monitor page.",
             icon=":material/power_settings_new:", title="Kill switch active")

with st.container(border=True):
    o1, o2 = st.columns(2, vertical_alignment="bottom")
    slice_ = o1.segmented_control("Data", ["Hold-out (forward)", "Full history"],
                                  default="Hold-out (forward)",
                                  help="Paper normally runs on the hold-out, which stands in for future data.")
    drill = o2.toggle("Failure drill: broker rejects a protective stop",
                      help="Forces the emergency path once: flatten the position, then block all new entries.")
    drill_at = (st.number_input("Inject the failure at bar index", min_value=1, value=50, step=10)
                if drill else None)

run_key = f"paper:{st.session_state.strategy_file}:{version}:{ui_common.data_path()}"
if st.button("Run paper simulation", icon=":material/play_arrow:", type="primary",
             disabled=not allowed, key="run_paper"):
    with st.spinner("Simulating..."):
        out = workflow.run_paper(c, data, full=(slice_ == "Full history"), inject_failure_at=drill_at)
    st.session_state.paper_run = (run_key, out)

stored = st.session_state.get("paper_run")
out = stored[1] if stored and stored[0] == run_key else None
if out is None:
    st.stop()

res, btm, pm = out.result, out.backtest_metrics, out.paper_metrics
if res.entries_blocked_latched:
    st.error(f"{res.block_reason}. The position was flattened and every later entry was "
             "blocked - this is the emergency path working as intended.",
             icon=":material/gpp_bad:", title="Entries latch-blocked")

ui_common.metric_row(pm)

st.subheader("Backtest vs paper on the same bars")
cmp = pd.DataFrame([
    {"metric": "Trades", "backtest": btm.trade_count, "paper": pm.trade_count},
    {"metric": "Net return %", "backtest": btm.net_return_pct, "paper": pm.net_return_pct},
    {"metric": "Profit factor", "backtest": btm.profit_factor, "paper": pm.profit_factor},
    {"metric": "Max drawdown %", "backtest": btm.max_drawdown_pct, "paper": pm.max_drawdown_pct},
])
st.dataframe(cmp, hide_index=True, alt="Backtest versus paper metrics")
if btm.trade_count == pm.trade_count and abs(btm.net_return_pct - pm.net_return_pct) < 0.01:
    st.success("Paper matches the backtest: the engines agree and no extra safety gate fired.",
               icon=":material/check_circle:")
else:
    st.info("Paper differs from the backtest. That's expected only when the paper-only safety "
            "gates fired (counts below). Any other difference would be a bug.",
            icon=":material/info:")

curves = {"Backtest": out.backtest_result.equity_curve, "Paper": res.equity_curve}
ui_common.compare_equity_chart(
    {k: v for k, v in curves.items() if len(v)},
    alt_text="Realized equity of the backtest and the paper simulation on the same bars")

c1, c2 = st.columns([1, 2])
with c1:
    st.markdown("**Decision counts**")
    st.dataframe(pd.DataFrame([{"event": k.replace("_", " "), "count": v}
                               for k, v in res.counts.items()]),
                 hide_index=True, alt="Signals, entries, exits and blocked entries by reason")
with c2:
    st.markdown("**Daily summary**")
    st.dataframe(out.daily.iloc[::-1], hide_index=True, alt="Trades and net P&L per day",
                 column_config={"net": st.column_config.NumberColumn(format="$%.2f")})

with st.expander(f"Paper trades ({len(res.trades)})", icon=":material/receipt_long:"):
    st.dataframe(ui_common.trades_frame(res.trades), hide_index=True, alt="Paper trade log")
st.caption(f"Audit log now holds {out.audit_rows:,} rows. Inspect them on the Monitor page.")
