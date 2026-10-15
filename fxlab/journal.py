"""Research journal - the project's memory of what you tried and what happened.

Three append-only JSON-lines files under reports/:

  review_ledger.jsonl  every FINAL review (one line per hold-out use). This is the
                       hold-out guard's evidence: if a strategy has already been
                       judged on a dataset's hold-out, judging it again after
                       tweaking is how overfitting sneaks in, so the dashboard and
                       CLI warn about it.
  runs.jsonl           every dev backtest and paper run, with the parameters used
                       and headline metrics, so versions can be compared later.
  research_log.jsonl   free-text notes you write ("tried X, rejected because Y").

Why JSON lines? One self-contained record per line: easy to append safely, easy
to read in any text editor, and a crash mid-write can only damage the last line.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fxlab import config

LEDGER_FILE = "review_ledger.jsonl"
RUNS_FILE = "runs.jsonl"
NOTES_FILE = "research_log.jsonl"


def _path(name: str) -> Path:
    return Path(config.REPORTS_DIR) / name


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(name: str, record: dict[str, Any]) -> dict[str, Any]:
    p = _path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts_utc": _now(), **record}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return record


def _read(name: str) -> list[dict[str, Any]]:
    p = _path(name)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn last line must not hide every other record
    return out


# --------------------------------------------------------------------------- #
# Data identity
# --------------------------------------------------------------------------- #
def data_fingerprint(data) -> str:
    """A short identity for a dataset: source + symbol + range + bar count.
    Two runs with the same fingerprint used the same hold-out slice."""
    df = data.df
    if len(df) == 0:
        return f"{data.source}:{data.symbol}:empty"
    return (f"{data.source}:{data.symbol}:{data.timeframe}:"
            f"{df.index[0]:%Y-%m-%d}..{df.index[-1]:%Y-%m-%d}:{len(df)}")


# --------------------------------------------------------------------------- #
# Review ledger (hold-out guard)
# --------------------------------------------------------------------------- #
def record_review(*, strategy: str, version: str, data_fp: str, decision: str,
                  reasons: list[str]) -> dict[str, Any]:
    return _append(LEDGER_FILE, {"strategy": strategy, "version": version,
                                 "data": data_fp, "decision": decision, "reasons": reasons})


def reviews(strategy: Optional[str] = None, data_fp: Optional[str] = None) -> list[dict[str, Any]]:
    rows = _read(LEDGER_FILE)
    if strategy is not None:
        rows = [r for r in rows if r.get("strategy") == strategy]
    if data_fp is not None:
        rows = [r for r in rows if r.get("data") == data_fp]
    return rows


def holdout_uses(strategy: str, data_fp: str) -> int:
    """How many times this strategy (ANY version) has been judged on this hold-out.
    Counted per strategy name, not per version: bumping the version after seeing
    the hold-out result does not make the hold-out fresh again."""
    return len(reviews(strategy, data_fp))


def latest_decision(strategy: str, version: Optional[str] = None,
                    data_fp: Optional[str] = None) -> Optional[dict[str, Any]]:
    rows = reviews(strategy, data_fp)
    if version is not None:
        rows = [r for r in rows if r.get("version") == version]
    return rows[-1] if rows else None


# --------------------------------------------------------------------------- #
# Run history (dev backtests + paper runs)
# --------------------------------------------------------------------------- #
def record_run(*, kind: str, strategy: str, version: str, data_fp: str,
               params: dict[str, Any], metrics: dict[str, Any],
               extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return _append(RUNS_FILE, {"kind": kind, "strategy": strategy, "version": version,
                               "data": data_fp, "params": params, "metrics": metrics,
                               **(extra or {})})


def runs(kind: Optional[str] = None, strategy: Optional[str] = None) -> list[dict[str, Any]]:
    rows = _read(RUNS_FILE)
    if kind is not None:
        rows = [r for r in rows if r.get("kind") == kind]
    if strategy is not None:
        rows = [r for r in rows if r.get("strategy") == strategy]
    return rows


# --------------------------------------------------------------------------- #
# Free-text research notes
# --------------------------------------------------------------------------- #
NOTE_KINDS = ["idea", "observation", "decision", "rejected", "todo"]


def add_note(*, strategy: str, version: str, kind: str, text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("note text is empty")
    if kind not in NOTE_KINDS:
        raise ValueError(f"unknown note kind '{kind}' (use one of {NOTE_KINDS})")
    return _append(NOTES_FILE, {"strategy": strategy, "version": version,
                                "kind": kind, "text": text})


def notes(strategy: Optional[str] = None) -> list[dict[str, Any]]:
    rows = _read(NOTES_FILE)
    if strategy is not None:
        rows = [r for r in rows if r.get("strategy") == strategy]
    return rows
