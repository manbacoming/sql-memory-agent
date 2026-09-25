"""SQLite execution helpers for deterministic toy evaluation."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Any

def execute_sql(db_path: str | Path, sql: str) -> tuple[list[tuple[Any, ...]] | None, str | None]:
    try:
        with sqlite3.connect(str(db_path)) as con:
            return con.execute(sql).fetchall(), None
    except sqlite3.Error as exc:
        return None, str(exc)
