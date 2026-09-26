from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from sql_memory_agent.driver import run_sequential_demo
from sql_memory_agent.example_data import ensure_toy_databases, toy_tasks
from sql_memory_agent.models import MemoryRecord, MemoryStatus, SolverOutcome
from sql_memory_agent.paired_eval import evaluate_empty_vs_memories
from sql_memory_agent.solver_stub import DeterministicTestingSolver

class ToyProtocolTests(unittest.TestCase):
    def test_current_task_cannot_retrieve_memory_it_just_wrote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_sequential_demo(Path(tmp))
        first = next(e for e in result.events if e.event_type == "memory_selection_once" and e.task_id == "task_v1_learn_refund_rule")
        self.assertEqual(first.payload["selected_memory_ids"], [])
        self.assertIn("mem_v1_refund_rule", {m.memory_id for m in result.memory_store.all_records()})

    def test_v1_memory_is_not_retrievable_after_v2_schema_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_sequential_demo(Path(tmp))
        v2 = next(e for e in result.events if e.event_type == "memory_selection_once" and e.task_id == "task_v2_refund_schema_changed")
        self.assertNotIn("mem_v1_refund_rule", v2.payload["selected_memory_ids"])
        self.assertIs(result.memory_store.get("mem_v1_refund_rule").status, MemoryStatus.QUARANTINED)

    def test_paired_eval_uses_same_database_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dbs = ensure_toy_databases(Path(tmp))
            task = toy_tasks()[1]
            memory = MemoryRecord(
                memory_id="m",
                content="For retail_v1 net sales subtract refunds.refund_amount from orders.order_amount.",
                source_task_id="source",
                created_at="test",
                applies_to_db_version="retail_v1",
                depends_on_tables=["orders", "refunds"],
                depends_on_columns=["orders.order_amount", "refunds.refund_amount"],
            )
            paired = evaluate_empty_vs_memories(task=task, db=dbs["retail_v1"], memories=[memory], solver=DeterministicTestingSolver(), budget_turns=4)
        self.assertTrue(paired.same_database_snapshot)
        self.assertEqual(paired.empty_memory.db_version_id, paired.selected_memory.db_version_id)
        self.assertFalse(paired.empty_memory.correct)
        self.assertTrue(paired.selected_memory.correct)

    def test_wrong_fast_answer_scores_below_correct_slower_answer(self) -> None:
        wrong_fast = SolverOutcome("t", "retail_v1", "SELECT 'Metropolis'", [("Metropolis",)], False, 1, 0)
        correct_slower = SolverOutcome("t", "retail_v1", "SELECT 'Gotham'", [("Gotham",)], True, 4, 2)
        self.assertLess(wrong_fast.score, correct_slower.score)

if __name__ == "__main__":
    unittest.main()
