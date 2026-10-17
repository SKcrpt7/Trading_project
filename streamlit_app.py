"""PipLab dashboard - entry point.

Run it by double-clicking run_dashboard.bat, or:
    .venv\\Scripts\\streamlit run streamlit_app.py --server.address 127.0.0.1

That serves http://127.0.0.1:8501 to this computer only. The same code also runs
online on Streamlit Community Cloud. It drives fxlab/workflow.py (shared with the
CLI), never places a real order, and cannot: live trading is disabled at the
broker-interface level.
"""
import streamlit as st

import ui_common
from ui_common import APP_NAME, ASSETS, STEPS

st.set_page_config(page_title=APP_NAME, page_icon=str(ASSETS / "icon.svg"), layout="wide")
ui_common.init_state()
ui_common.render_brand()

pages = {s.key: st.Page(s.page, title=f"{s.num} · {s.title}", icon=s.icon) for s in STEPS}
page = st.navigation(
    {
        "": [st.Page("app_pages/home.py", title="Home", icon=":material/home:", default=True)],
        "Research": [pages[k] for k in ("data", "strategy", "dev", "review")],
        "Forward test": [pages[k] for k in ("paper", "monitor")],
        "Notes": [pages["log"]],
    },
    position="sidebar",
)

ui_common.render_sidebar()
if page.title != "Home":          # Home draws its own hero header
    st.title(page.title, icon=page.icon)
ui_common.show_flash()
page.run()
