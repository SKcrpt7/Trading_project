"""Strategy files: list, validate, and save - without destroying your comments.

Convention: every `config/strategy_*.yaml` is a strategy. Saving follows two
rules that keep research honest and reproducible:

  1. Changing an existing strategy REQUIRES a new version number. The previous
     file is archived to config/strategy_history/<name>_v<old>.yaml first, so
     every result you ever saw can be traced to the exact parameters behind it.
  2. Edits are applied IN PLACE to the YAML text (value replaced, comment kept).
     A plain yaml.dump() would silently strip every explanatory comment in the
     file - and those comments are the documentation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any, Optional

import yaml

from fxlab import config

HISTORY_DIRNAME = "strategy_history"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class Field:
    """One editable strategy parameter, as the dashboard form should show it."""
    section: str
    key: str
    kind: str          # int | float | bool | time | days | choice
    label: str
    help: str
    min: Optional[float] = None
    max: Optional[float] = None
    choices: tuple = ()


# The parameters the dashboard lets you edit. Everything else (name, kind,
# symbol, description, invalidation list) is edited in the YAML file itself.
EDITABLE_FIELDS: list[Field] = [
    Field("entry", "fast_ema", "int", "Fast EMA", "Bars in the fast moving average.", 2, 500),
    Field("entry", "slow_ema", "int", "Slow EMA", "Bars in the slow moving average. Must be > fast.", 3, 1000),
    Field("entry", "allow_long", "bool", "Allow longs", "Take buy signals."),
    Field("entry", "allow_short", "bool", "Allow shorts", "Take sell signals."),
    Field("exit", "atr_period", "int", "ATR period", "Bars used to measure volatility (ATR).", 2, 200),
    Field("exit", "stop_atr_mult", "float", "Stop (x ATR)", "Protective stop distance in ATRs.", 0.1, 20.0),
    Field("exit", "reward_risk", "float", "Reward : risk", "Target distance as a multiple of the stop distance.", 0.1, 20.0),
    Field("exit", "time_stop_bars", "int", "Time stop (bars)", "Exit after N bars if neither stop nor target hit. 0 = off.", 0, 5000),
    Field("exit", "exit_on_opposite_signal", "bool", "Exit on opposite signal", "Close when the strategy signals the other way."),
    Field("sizing", "risk_per_trade_pct", "float", "Risk per trade (%)", "Equity lost if the stop is hit. Capped by risk.yaml.", 0.01, 5.0),
    Field("session", "enabled", "bool", "Session filter", "Only enter during the hours below."),
    Field("session", "start_utc", "time", "Session start (UTC)", "No entries before this time."),
    Field("session", "end_utc", "time", "Session end (UTC)", "No entries after this time."),
    Field("session", "trade_days", "days", "Trade days", "Weekdays on which entries are allowed."),
    Field("news", "blackout_enabled", "bool", "News blackout", "Block entries around high-impact events."),
    Field("news", "block_minutes_before", "int", "Block before (min)", "Minutes before an event.", 0, 1440),
    Field("news", "block_minutes_after", "int", "Block after (min)", "Minutes after an event.", 0, 1440),
    Field("news", "min_impact", "choice", "Minimum impact", "Smallest event impact that blocks.",
          choices=("low", "medium", "high")),
]


# --------------------------------------------------------------------------- #
# Listing & loading
# --------------------------------------------------------------------------- #
def config_dir() -> Path:
    return Path(config.CONFIG_DIR)


def list_strategy_files() -> list[str]:
    return sorted(p.name for p in config_dir().glob("strategy_*.yaml"))


def load(filename: str) -> dict[str, Any]:
    return config.load_yaml(config_dir() / filename)


def read_text(filename: str) -> str:
    return (config_dir() / filename).read_text(encoding="utf-8")


def history(name: str) -> list[Path]:
    d = config_dir() / HISTORY_DIRNAME
    return sorted(d.glob(f"{name}_v*.yaml")) if d.exists() else []


def get_value(cfg: dict, section: str, key: str):
    return cfg.get(section, {}).get(key)


def bump_version(version: str) -> str:
    """0.1.0 -> 0.2.0 (minor bump = 'changed parameters'). Non-semver gets '.1'."""
    parts = str(version).split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{int(parts[1]) + 1}.0"
    return f"{version}.1"


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return s


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _parse_hhmm(v) -> Optional[time]:
    try:
        h, m = map(int, str(v).split(":"))
        return time(h, m)
    except (ValueError, TypeError):
        return None


def validate(cfg: dict, risk_cfg: Optional[dict] = None) -> list[str]:
    """Return a list of human-readable problems (empty = valid)."""
    errs: list[str] = []
    for f in EDITABLE_FIELDS:
        v = get_value(cfg, f.section, f.key)
        if v is None:
            errs.append(f"{f.section}.{f.key} is missing")
            continue
        if f.kind in ("int", "float"):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                errs.append(f"{f.label} must be a number")
            elif f.kind == "int" and not isinstance(v, int):
                errs.append(f"{f.label} must be a whole number")
            elif (f.min is not None and v < f.min) or (f.max is not None and v > f.max):
                errs.append(f"{f.label} must be between {f.min} and {f.max} (got {v})")
        elif f.kind == "bool" and not isinstance(v, bool):
            errs.append(f"{f.label} must be true/false")
        elif f.kind == "time" and _parse_hhmm(v) is None:
            errs.append(f"{f.label} must look like HH:MM (got {v!r})")
        elif f.kind == "days" and (not isinstance(v, list) or not v or any(d not in DAYS for d in v)):
            errs.append(f"{f.label} must be a non-empty list of {DAYS}")
        elif f.kind == "choice" and v not in f.choices:
            errs.append(f"{f.label} must be one of {list(f.choices)}")
    if errs:
        return errs

    e, s = cfg["entry"], cfg["session"]
    if e["fast_ema"] >= e["slow_ema"]:
        errs.append("Fast EMA must be smaller than slow EMA")
    if not (e["allow_long"] or e["allow_short"]):
        errs.append("Allow longs and/or shorts - with both off the strategy never trades")
    if s["enabled"] and _parse_hhmm(s["start_utc"]) >= _parse_hhmm(s["end_utc"]):
        errs.append("Session start must be before session end (overnight sessions are not supported)")
    if risk_cfg is not None:
        cap = float(risk_cfg["limits"]["max_risk_per_trade_pct"])
        if cfg["sizing"]["risk_per_trade_pct"] > cap:
            errs.append(f"Risk per trade exceeds the account limit in risk.yaml ({cap}%)")
    return errs


# --------------------------------------------------------------------------- #
# Comment-preserving YAML edits
# --------------------------------------------------------------------------- #
def _fmt(value) -> str:
    """Render a Python value as a YAML scalar / inline list."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return json.dumps(str(value))  # double-quoted strings are always valid YAML


_KEY_LINE = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z_][\w-]*):(?P<rest>.*)$")


def _split_comment(rest: str) -> tuple[str, str]:
    """Split ' value   # comment' into (' value', '   # comment'), ignoring '#'
    inside quotes."""
    quote = None
    for i, ch in enumerate(rest):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or rest[i - 1].isspace()):
            j = i
            while j > 0 and rest[j - 1].isspace():
                j -= 1
            return rest[:j], rest[j:]
    return rest, ""


def update_yaml_text(text: str, updates: dict[tuple[str, ...], Any]) -> str:
    """Replace values at top-level `(key,)` or one-level-nested `(section, key)`
    paths, keeping every comment and blank line. Raises KeyError if a path is not
    found as a simple `key: value` line (block scalars / nested maps are refused)."""
    lines = text.splitlines(keepends=True)
    pending = dict(updates)
    section = None
    for i, raw in enumerate(lines):
        body = raw.rstrip("\r\n")
        eol = raw[len(body):]
        if not body.strip() or body.lstrip().startswith("#"):
            continue
        m = _KEY_LINE.match(body)
        if not m:
            continue
        indent, key, rest = len(m["indent"]), m["key"], m["rest"]
        if indent == 0:
            section = key
            path = (key,)
        elif indent == 2 and section is not None:
            path = (section, key)
        else:
            continue
        if path not in pending:
            continue
        value_part, comment = _split_comment(rest)
        if value_part.strip() in ("", ">", "|", ">-", "|-"):
            raise KeyError(f"{'.'.join(path)} is not a simple value; edit it in the file")
        lines[i] = f"{m['indent']}{key}: {_fmt(pending.pop(path))}{comment}{eol}"
    if pending:
        raise KeyError(f"not found in strategy file: {['.'.join(p) for p in pending]}")
    new_text = "".join(lines)

    # Belt and braces: re-parse and confirm every value landed exactly as intended.
    parsed = yaml.safe_load(new_text)
    for path, want in updates.items():
        got = parsed
        for k in path:
            got = got[k]
        if (list(got) if isinstance(want, (list, tuple)) else got) != (list(want) if isinstance(want, (list, tuple)) else want):
            raise ValueError(f"YAML round-trip mismatch at {'.'.join(path)}: {got!r} != {want!r}")
    return new_text


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #
def save_new_version(filename: str, params: dict[tuple[str, str], Any], new_version: str,
                     risk_cfg: Optional[dict] = None) -> Path:
    """Save edited parameters into the SAME strategy under a NEW version, archiving
    the old file first."""
    path = config_dir() / filename
    old_text = path.read_text(encoding="utf-8")
    old_cfg = yaml.safe_load(old_text)
    old_version = str(old_cfg.get("version", "0"))
    new_version = str(new_version).strip()
    if not new_version or new_version == old_version:
        raise ValueError(f"Choose a new version number (current is {old_version}). Every "
                         "parameter change gets its own version so results stay traceable.")
    if (config_dir() / HISTORY_DIRNAME / f"{old_cfg['name']}_v{new_version}.yaml").exists():
        raise ValueError(f"Version {new_version} already exists in the history. Pick another.")

    new_text = update_yaml_text(old_text, {**params, ("version",): new_version})
    errs = validate(yaml.safe_load(new_text), risk_cfg)
    if errs:
        raise ValueError("; ".join(errs))

    hist = config_dir() / HISTORY_DIRNAME
    hist.mkdir(exist_ok=True)
    (hist / f"{old_cfg['name']}_v{old_version}.yaml").write_text(old_text, encoding="utf-8")
    path.write_text(new_text, encoding="utf-8")
    return path


def save_as_new_strategy(source_filename: str, params: dict[tuple[str, str], Any],
                         new_name: str, risk_cfg: Optional[dict] = None) -> Path:
    """Fork a strategy under a new name (starts at version 0.1.0)."""
    slug = slugify(new_name)
    if not slug:
        raise ValueError("Give the new strategy a name (letters, numbers, underscores).")
    target = config_dir() / f"strategy_{slug}.yaml"
    if target.exists():
        raise ValueError(f"{target.name} already exists. Pick a different name.")
    text = (config_dir() / source_filename).read_text(encoding="utf-8")
    new_text = update_yaml_text(text, {**params, ("name",): slug, ("version",): "0.1.0"})
    errs = validate(yaml.safe_load(new_text), risk_cfg)
    if errs:
        raise ValueError("; ".join(errs))
    target.write_text(new_text, encoding="utf-8")
    return target
