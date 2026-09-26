"""Read-only SQLite evaluator helpers for BIRD integration checks."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class SqlExecutionStatus(str, Enum):
    """Outcome categories for a read-only SQL execution attempt."""

    EXECUTION_FAILED = "execution_failed"
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"


@dataclass(frozen=True)
class SqlExecution:
    rows: list[tuple[Any, ...]] | None
    error: str | None
    truncated: bool
    timed_out: bool = False
    incomplete_reason: str | None = None

    @property
    def status(self) -> SqlExecutionStatus:
        if self.error is not None:
            return SqlExecutionStatus.EXECUTION_FAILED
        if self.truncated or self.timed_out or self.incomplete_reason is not None:
            return SqlExecutionStatus.INCOMPLETE
        return SqlExecutionStatus.COMPLETE

    @property
    def evaluable(self) -> bool:
        return self.status is SqlExecutionStatus.COMPLETE


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
    timed_out = False

    try:
        with sqlite3.connect(uri, uri=True) as con:
            con.execute("PRAGMA query_only = ON")

            def progress() -> int:
                nonlocal calls, timed_out
                calls += 1
                if calls > deadline_steps:
                    timed_out = True
                    return 1
                return 0

            con.set_progress_handler(progress, progress_steps)
            cur = con.execute(sql)
            rows = cur.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            return SqlExecution(
                rows=rows[:max_rows],
                error=None,
                truncated=truncated,
                incomplete_reason="max_rows_exceeded" if truncated else None,
            )
    except sqlite3.Error as exc:
        if timed_out:
            return SqlExecution(
                rows=None,
                error=None,
                truncated=False,
                timed_out=True,
                incomplete_reason="timeout",
            )
        return SqlExecution(rows=None, error=str(exc), truncated=False)
