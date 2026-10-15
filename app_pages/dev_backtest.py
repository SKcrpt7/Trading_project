"""Step 3 - Dev backtest: tune on the development slice. The hold-out is never used here."""
import pandas as pd
import streamlit as st

import ui_common
from fxlab import journal, workflow

c = ui_common.cfg()
s = c["strategy"]
version = str(s.get("version", "0"))
data = ui_common.data(c)
dev, hold = workflow.split(data, c)

st.info(f"Runs on the **development slice only**: {dev.df.index[0]:%Y-%m-%d} → "
        f"{dev.df.index[-1]:%Y-%m-%d %H:%M} UTC ({len(dev.df):,} bars). The hold-out from "
        f"{hold.df.index[0]:%Y-%m-%d %H:%M} is fenced off, so iterate here as often as you like.",
        icon=":material/lock:")

run_key = f"dev:{st.session_state.strategy_file}:{version}:{ui_common.data_path()}"
if st.button(f"Run dev backtest · {s['name']} v{version}", icon=":material/play_arrow:",
             type="primary", key="run_dev"):
    with st.spinner("Backtesting the development slice..."):
        st.session_state.dev_run = (run_key, workflow.run_dev_backtest(c, data))

stored = st.session_state.get("dev_run")
run = stored[1] if stored and stored[0] == run_key else None

if run is None:
    st.caption("Press **Run** to backtest the current version. Results and the run history "
               "below update after each run.")
else:
    m, res = run.metrics, run.result
    if res.source.upper() == "MOCK":
        st.caption(":material/warning: Mock data - this shows the machinery, not an edge.")
    ui_common.metric_row(m)
    if m.trade_count < 50:
        st.warning(f"Only {m.trade_count} trades. With this few, luck dominates the result.",
                   icon=":material/warning:")
    st.caption(f"Signals {res.n_signals} · blocked by session {res.n_blocked_session}, "
               f"news {res.n_blocked_news}, risk {res.n_blocked_risk}")

    trades = ui_common.trades_frame(res.trades)
    tab_eq, tab_tr, tab_br, tab_as = st.tabs(["Equity curve", "Trades", "Breakdown", "Assumptions"])
    with tab_eq:
        ui_common.equity_chart(res.equity_curve, res.starting_equity,
                               alt_text=f"Realized equity over the development slice, ending at "
                                        f"${res.ending_equity:,.2f}")
        st.caption("Realized equity (changes only when a trade closes). The gray line is the "
                   "starting balance.")
    with tab_tr:
        st.dataframe(trades, hide_index=True, alt="Trade log for the development slice",
                     column_config={"net_pnl": st.column_config.NumberColumn(format="$%.2f"),
                                    "costs": st.column_config.NumberColumn(format="$%.2f")})
        st.download_button("Download trades (CSV)", trades.to_csv(index=False),
                           f"dev_trades_{s['name']}_v{version}.csv", "text/csv",
                           icon=":material/download:")
    with tab_br:
        a, b, e = st.columns(3)
        with a:
            st.markdown("**By year**")
            by_year = ui_common.breakdown_frame(m.by_year, "year")
            ui_common.signed_bar_chart(by_year.astype({"year": str}), "year", "net_pnl", "Year",
                                       "Net P&L ($)", alt_text="Net profit or loss by year")
            st.dataframe(by_year, hide_index=True, alt="Net P&L by year")
        with b:
            st.markdown("**By session (entry time)**")
            by_sess = ui_common.breakdown_frame(m.by_session, "session")
            ui_common.signed_bar_chart(by_sess, "session", "net_pnl", "Session", "Net P&L ($)",
                                       alt_text="Net profit or loss by trading session")
            st.dataframe(by_sess, hide_index=True, alt="Net P&L by session")
        with e:
            st.markdown("**By exit reason**")
            if len(trades):
                by_exit = (trades.groupby("exit_reason")
                           .agg(trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum"))
                           .round(2).reset_index())
                ui_common.signed_bar_chart(by_exit, "exit_reason", "net_pnl", "Exit reason",
                                           "Net P&L ($)", alt_text="Net profit or loss by exit reason")
                st.dataframe(by_exit, hide_index=True, alt="Net P&L by exit reason")
        st.caption("If one year or one session carries all the profit, that's usually luck, "
                   "not an edge.")
    with tab_as:
        for a_ in res.assumptions:
            st.markdown(f"- {a_}")

# ---- run history ---------------------------------------------------------- #
st.subheader("Compare versions")
fp = journal.data_fingerprint(data)
hist = [r for r in journal.runs("dev", s["name"]) if r.get("data") == fp]
if not hist:
    st.caption("Each dev run is logged here, so you can see which change helped and which hurt.")
else:
    rows = []
    for r in reversed(hist):
        p, mm = r["params"], r["metrics"]
        rows.append({
            "time (UTC)": r["ts_utc"].replace("T", " ")[:16], "version": r["version"],
            "EMA": f"{p['entry']['fast_ema']}/{p['entry']['slow_ema']}",
            "stop xATR": p["exit"]["stop_atr_mult"], "R:R": p["exit"]["reward_risk"],
            "time stop": p["exit"]["time_stop_bars"], "risk %": p["sizing"]["risk_per_trade_pct"],
            "trades": mm["trade_count"], "net %": mm["net_return_pct"],
            "PF": mm["profit_factor"], "max DD %": mm["max_drawdown_pct"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, alt="History of development backtests",
                 column_config={"net %": st.column_config.NumberColumn(format="%+.2f")})
    st.caption("All runs here use only the development slice, so comparing them is safe. "
               "When one version looks good, take it to the **Final review** once.")
