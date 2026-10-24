# CLAUDE.md — working rules for this project

This file is loaded automatically at the start of every session in this repo.
It tells Claude how to behave here so you don't have to re-explain each time.
Add a line any time you catch yourself repeating an instruction.

## What this project is
- **PipLab / fxlab** — a learning-first toolkit for designing, backtesting,
  reviewing, and **paper**-trading rule-based forex strategies.
- Python package name: `fxlab`. The dashboard brand name: **PipLab** (Streamlit).
- **Educational only. Live-money trading is disabled by design.** Never add it,
  and never remove the safety rails (kill switch, hold-out split, risk limits).
- Bundled data is **synthetic/MOCK** and must stay clearly labelled as such.

## How the owner works
- Not from a computer-science background — explain in plain language, define
  jargon the first time it appears.
- Prefers short, option-style replies over long walls of text. Give choices,
  wait for a pick, then go deep on the one chosen.
- Likes work kept organized so projects don't get scrambled.

## House rules for Claude
- Keep the honest-research features intact: no look-ahead, hold-out judged only
  in Final Review, costs always explicit.
- When adding a strategy, follow the 6-step path in README.md (spec → config →
  rules → register → test → backtest/review).
- Run `python -m pytest -q` before calling a change done; tests write only to a
  temp folder, never to real `config/` or `reports/`.
- Don't commit or push unless asked. Develop on the branch the task names.
- Update PLAN.md when a milestone is finished or the roadmap changes.

## Pointers
- Full tour of the system: `README.md`
- Roadmap / what's next: `PLAN.md`
- Portable project summary for other AI tools: `HANDOFF.md`
