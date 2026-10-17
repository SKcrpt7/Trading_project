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

ui_common.intro("dev")
with st.container(horizontal=True, vertical_alignment="center"):
    st.badge(f"Dev data: {dev.df.index[0]:%Y-%m-%d} → {dev.df.index[-1]:%Y-%m-%d}",
             icon=":material/science:", color="blue")
    st.badge(f"Hold-out locked from {hold.df.index[0]:%Y-%m-%d}", icon=":material/lock:", color="gray")

run_key = f"dev:{st.session_state.strategy_file}:{version}:{ui_common.data_path()}"
autorun = st.session_state.pop("autorun_dev", False)    # set by Home's quick action
if st.button(f"Run dev backtest · v{version}", icon=":material/play_arrow:",
             type="primary", key="run_dev") or autorun:
    with st.spinner("Backtesting the development data..."):
        st.session_state.dev_run = (run_key, workflow.run_dev_backtest(c, data))

stored = st.session_state.get("dev_run")
run = stored[1] if stored and stored[0] == run_key else None

if run is None:
    st.caption("Press **Run** to test the current version.")
else:
    m, res = run.metrics, run.result
    ui_common.metric_row(m)
    if m.trade_count < 50:
        st.warning(f"Only {m.trade_count} trades. With this few, luck dominates the result.",
                   icon=":material/warning:")
    st.caption(f"{res.n_signals} signals · blocked: session {res.n_blocked_session}, "
               f"news {res.n_blocked_news}, risk {res.n_blocked_risk}")

    trades = ui_common.trades_frame(res.trades)
    tab_eq, tab_tr, tab_br, tab_as = st.tabs([":material/show_chart: Equity", ":material/list: Trades",
                                              ":material/bar_chart: Breakdown", ":material/info: Assumptions"])
    with tab_eq:
        ui_common.equity_chart(res.equity_curve, res.starting_equity,
                               alt_text=f"Realized equity over the development slice, ending at "
                                        f"${res.ending_equity:,.2f}")
        st.caption("Changes only when a trade closes. Gray line = starting balance.")
    with tab_tr:
        st.dataframe(trades, hide_index=True, alt="Trade log for the development slice",
                     column_config=ui_common.TRADE_COLUMNS)
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
    with tab_as:
        for a_ in res.assumptions:
            st.markdown(f"- {a_}")

# ---- run history ---------------------------------------------------------- #
st.subheader("Compare versions", icon=":material/compare_arrows:")
fp = journal.data_fingerprint(data)
hist = [r for r in journal.runs("dev", s["name"]) if r.get("data") == fp]
if not hist:
    st.caption("Every dev run appears here, so you can see which change helped.")
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
                 column_order=["version", "net %", "PF", "trades", "max DD %", "EMA", "stop xATR",
                               "R:R", "time stop", "risk %", "time (UTC)"],
                 column_config={"net %": st.column_config.NumberColumn(format="%+.2f")})
    st.caption("Found a version you like? Take it to the Final review, once.")

ui_common.next_step("dev")
