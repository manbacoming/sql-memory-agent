from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sql_memory_agent.bird_eval import SqlExecutionStatus, execute_readonly_sql


class BirdEvalTests(unittest.TestCase):
    def test_truncated_standard_sql_is_not_evaluable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rows.sqlite"
            with sqlite3.connect(db_path) as con:
                con.execute("CREATE TABLE numbers(value INTEGER)")
                con.executemany("INSERT INTO numbers(value) VALUES (?)", [(1,), (2,), (3,)])

            execution = execute_readonly_sql(
                db_path,
                "SELECT value FROM numbers ORDER BY value",
                max_rows=1,
            )

        self.assertEqual(execution.status, SqlExecutionStatus.INCOMPLETE)
        self.assertFalse(execution.evaluable)
        self.assertTrue(execution.truncated)
        self.assertEqual(execution.incomplete_reason, "max_rows_exceeded")
        self.assertEqual(execution.rows, [(1,)])

    def test_invalid_sql_is_execution_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rows.sqlite"
            with sqlite3.connect(db_path) as con:
                con.execute("CREATE TABLE numbers(value INTEGER)")

            execution = execute_readonly_sql(db_path, "SELECT missing FROM numbers")

        self.assertEqual(execution.status, SqlExecutionStatus.EXECUTION_FAILED)
        self.assertFalse(execution.evaluable)
        self.assertIsNotNone(execution.error)


if __name__ == "__main__":
    unittest.main()
