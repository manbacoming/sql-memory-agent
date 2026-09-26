"""Read-only SQLite evaluator helpers for BIRD integration checks."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SqlExecution:
    rows: list[tuple[Any, ...]] | None
    error: str | None
    truncated: bool


def execute_readonly_sql(
    db_path: str | Path,
    sql: str,
    *,
    timeout_ms: int = 2000,
    max_rows: int = 1000,
    progress_steps: int = 1000,
) -> SqlExecution:
    """Execute SQL against a SQLite DB opened read-only, with timeout and row cap."""

    db = Path(db_path)
    uri = f"file:{db.as_posix()}?mode=ro"
    deadline_steps = max(1, timeout_ms)
    calls = 0

    try:
        with sqlite3.connect(uri, uri=True) as con:
            con.execute("PRAGMA query_only = ON")

            def progress() -> int:
                nonlocal calls
                calls += 1
                return 1 if calls > deadline_steps else 0

            con.set_progress_handler(progress, progress_steps)
            cur = con.execute(sql)
            rows = cur.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            return SqlExecution(rows=rows[:max_rows], error=None, truncated=truncated)
    except sqlite3.Error as exc:
        return SqlExecution(rows=None, error=str(exc), truncated=False)
