"""Configuration loading.

Design choice: every tunable lives in a YAML file under config/, never hard-coded
in a strategy. That way you can see, diff, and version every assumption. Secrets
(API keys) never live in YAML - they come from environment variables only.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
SAMPLE_PRICES = DATA_DIR / "sample" / "EURUSD_H1_sample.csv"
SAMPLE_EVENTS = DATA_DIR / "sample" / "economic_events_sample.csv"
USER_DATA_DIR = DATA_DIR / "user"          # CSVs uploaded through the dashboard
AUDIT_DB = PROJECT_ROOT / "fxlab_audit.sqlite"
# NOTE: code that writes files (workflow, journal, strategy_store) reads these as
# `config.X` at CALL time rather than importing the names, so tests can point
# them at a temporary folder with monkeypatch and never touch your real files.
DISPLAY_TZ = "America/Toronto"   # how times are shown to the user
STORAGE_TZ = "UTC"               # how times are stored, always


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML config file into a plain dict."""
    p = Path(path)
    if not p.is_absolute():
        p = CONFIG_DIR / p
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_env_file(path: str | Path = PROJECT_ROOT / ".env") -> None:
    """Minimal .env loader (no external dependency). Only sets vars that are not
    already present in the environment, so real env vars always win."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_secret(name: str, default: str | None = None) -> str | None:
    """Read a secret from the environment. Never logs or prints the value."""
    load_env_file()
    return os.environ.get(name, default)
