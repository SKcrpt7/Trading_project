# HANDOFF.md — portable project brief

Copy–paste this whole file into any AI assistant (ChatGPT/OpenAI, Gemini, a
fresh Claude chat, etc.) to bring it up to speed on this project cold, with no
other context. It is written in plain, tool-agnostic language on purpose.
Keep it updated when the project changes.

_Last updated: 2026-10-24_

---

## 1. One-paragraph summary
This is **PipLab / fxlab**, a learning-first toolkit for designing, backtesting,
reviewing, and **paper**-trading (simulated, no real money) rule-based forex
strategies. It is written in Python with a Streamlit web dashboard. Everything
runs offline on bundled synthetic ("MOCK") data with no broker and no paid
subscription. **Live-money trading is intentionally disabled** and must stay
that way. It is for education and research only, not financial advice.

## 2. Why it exists
To let a non-expert understand *every* decision the system makes and avoid
fooling themselves with over-optimistic backtests. It enforces honest research:
no look-ahead (a signal on one bar only executes on the next), a held-out
evaluation slice judged separately, explicit trading costs, and robustness
checks (walk-forward, sensitivity, cost-stress).

## 3. How it's organized (plain terms)
- **Data** — price history + an economic-events calendar; quality checks.
- **Strategy** — trading rules written as a config file plus a small code class.
- **Backtest** — replays history trade by trade with realistic costs.
- **Review** — outputs one of: REJECT / NEEDS_INVESTIGATION / ELIGIBLE_FOR_PAPER.
- **Paper trading** — simulated fills through a full risk-limit stack.
- **Audit log** — records every signal, order, fill, and decision.
- A dashboard (**PipLab**) and a command-line tool share the same code.

## 4. Hard rules (do not break)
- Never enable or add real-money / live trading.
- Never remove safety rails: kill switch, hold-out split, risk limits.
- Keep MOCK/synthetic data clearly labelled as fake.
- Don't introduce look-ahead; keep costs explicit.
- Run the test suite (`python -m pytest -q`) before considering a change done.

## 5. Tech facts
- Language: Python 3.10+ (Streamlit dashboard, YAML strategy configs,
  SQLite audit log, plain-text JSONL logs in `reports/`).
- Entry points: `streamlit_app.py` (dashboard), `python -m fxlab.cli <cmd>` (CLI).
- See `README.md` for the full workflow and commands; `PLAN.md` for the roadmap.

## 6. The owner
- Not a computer-science background — explain plainly, define jargon once.
- Prefers short, option-style answers over long text; offer choices, then go
  deep on the chosen one.

## 7. Other projects (context, not in this repo)
- A planned **remote CAD (computer-aided-design) jobs search engine** — a way to
  find remote CAD/design work. Separate project; will get its own repo.
