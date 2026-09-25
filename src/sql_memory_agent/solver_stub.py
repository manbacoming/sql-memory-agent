"""Deterministic testing stub, not a real model or real SQL Agent."""
from __future__ import annotations
from .models import DatabaseVersion, MemoryRecord, SolverOutcome, TaskRecord
from .sqlite_eval import execute_sql

GROSS_SQL = """
SELECT c.city_name FROM cities c
JOIN stores s ON s.city_id = c.city_id
JOIN orders o ON o.store_id = s.store_id
GROUP BY c.city_name
ORDER BY SUM(o.order_amount) DESC
LIMIT 1
"""

V1_REFUND_SQL = """
SELECT c.city_name FROM cities c
JOIN stores s ON s.city_id = c.city_id
JOIN orders o ON o.store_id = s.store_id
LEFT JOIN refunds r ON r.order_id = o.order_id
GROUP BY c.city_name
ORDER BY SUM(o.order_amount - COALESCE(r.refund_amount, 0)) DESC
LIMIT 1
"""

V2_REFUND_SQL = """
SELECT c.city_name FROM cities c
JOIN stores s ON s.city_id = c.city_id
JOIN orders o ON o.store_id = s.store_id
LEFT JOIN refund_events r ON r.order_id = o.order_id AND r.approved = 1
GROUP BY c.city_name
ORDER BY SUM(o.order_amount - COALESCE(r.returned_amount, 0)) DESC
LIMIT 1
"""

class DeterministicTestingSolver:
    """Transparent protocol stub; never report it as real model performance."""
    name = "deterministic-testing-stub"

    def solve(self, task: TaskRecord, db: DatabaseVersion, memories: list[MemoryRecord], budget_turns: int) -> SolverOutcome:
        del budget_turns
        memory_text = "\n".join(memory.content for memory in memories)
        if db.version_id == "retail_v1" and "refunds.refund_amount" in memory_text:
            sql, turns = V1_REFUND_SQL, 2
        elif db.version_id == "retail_v2" and "refund_events.returned_amount" in memory_text:
            sql, turns = V2_REFUND_SQL, 2
        elif task.task_id == "task_v1_learn_refund_rule":
            sql, turns = V1_REFUND_SQL, 4
        else:
            sql, turns = GROSS_SQL, 1
        result, error = execute_sql(db.path, sql)
        return SolverOutcome(
            task_id=task.task_id,
            db_version_id=db.version_id,
            sql=sql,
            result=result,
            correct=(result == task.expected_result and error is None),
            turns=turns,
            memory_count=len(memories),
            error=error,
        )
