"""Audit log - the system's black box recorder.

Every signal, order, fill, risk decision, error, and state change is written here
with a UTC timestamp and a JSON payload. If anything ever looks wrong in paper
trading, this table is how you reconstruct exactly what happened and why. It is
append-only by convention (we never UPDATE or DELETE rows in normal operation).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

VALID_CATEGORIES = {
    "signal", "order", "fill", "decision", "risk", "error", "info", "reconcile", "kill",
}


class AuditStore:
    def __init__(self, path: str | Path = "fxlab_audit.sqlite"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc     TEXT NOT NULL,
                category   TEXT NOT NULL,
                symbol     TEXT,
                strategy   TEXT,
                message    TEXT NOT NULL,
                data_json  TEXT
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_cat ON audit_log(category)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts_utc)")
        self.conn.commit()

    def log(
        self,
        category: str,
        message: str,
        *,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
        ts_utc: Optional[datetime] = None,
    ) -> int:
        if category not in VALID_CATEGORIES:
            category = "info"
        ts = (ts_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO audit_log (ts_utc, category, symbol, strategy, message, data_json) "
            "VALUES (?,?,?,?,?,?)",
            (ts, category, symbol, strategy, message,
             json.dumps(data, default=str) if data else None),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def recent(self, limit: int = 20, category: Optional[str] = None) -> list[dict]:
        if category:
            rows = self.conn.execute(
                "SELECT * FROM audit_log WHERE category=? ORDER BY id DESC LIMIT ?",
                (category, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def count(self, category: Optional[str] = None) -> int:
        if category:
            r = self.conn.execute(
                "SELECT COUNT(*) c FROM audit_log WHERE category=?", (category,)).fetchone()
        else:
            r = self.conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()
        return int(r["c"])

    def close(self) -> None:
        self.conn.close()
