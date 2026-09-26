from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sql_memory_agent.bird import load_bird_train, same_db_task_flow
from sql_memory_agent.bird_eval import execute_readonly_sql
from sql_memory_agent.memory import MemoryStore
from sql_memory_agent.real_chain import (
    SqlAgentRun,
    assert_later_task_can_only_see_prior_memories,
    build_experience_candidate,
    evaluate_agent_run_against_gold,
    paired_runs_are_comparable,
    verify_experience_candidate,
    write_memory_after_task,
)


def _make_fake_bird_train(root: Path) -> Path:
    train_root = root / "train_root"
    db_dir = train_root / "train_databases" / "shop"
    db_dir.mkdir(parents=True)
    sqlite_path = db_dir / "shop.sqlite"
    with sqlite3.connect(sqlite_path) as con:
        con.executescript(
            """
            CREATE TABLE orders(order_id INTEGER PRIMARY KEY, city TEXT, amount INTEGER);
            INSERT INTO orders VALUES (1, 'A', 10), (2, 'B', 20);
            """
        )
    records = [
        {
            "question_id": 1,
            "db_id": "shop",
            "question": "How many orders are there?",
            "evidence": "",
            "difficulty": "simple",
            "SQL": "SELECT COUNT(*) FROM orders",
        },
        {
            "question_id": 2,
            "db_id": "shop",
            "question": "Which city has the largest order amount?",
            "evidence": "",
            "difficulty": "simple",
            "SQL": "SELECT city FROM orders ORDER BY amount DESC LIMIT 1",
        },
    ]
    (train_root / "train.json").write_text(json.dumps(records), encoding="utf-8")
    return train_root


class RealChainTests(unittest.TestCase):
    def test_train_loader_separates_agent_input_from_gold_and_selects_same_db_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            train_root = _make_fake_bird_train(Path(tmp))
            bundle = load_bird_train(train_root)
        self.assertEqual(len(bundle.tasks), 2)
        serialized_agent = json.dumps(bundle.tasks[0].agent_input.to_dict(), sort_keys=True)
        self.assertNotIn(bundle.tasks[0].gold.gold_sql, serialized_agent)
        self.assertNotIn("gold", serialized_agent.lower())
        flow = same_db_task_flow(bundle.tasks, min_tasks=2)
        self.assertEqual([task.agent_input.question_id for task in flow], [1, 2])

    def test_verified_generated_sql_experience_can_be_written_after_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            train_root = _make_fake_bird_train(Path(tmp))
            task = load_bird_train(train_root).tasks[0]
            candidate = build_experience_candidate(
                task.agent_input,
                db_snapshot=task.agent_input.db_id,
                generated_sql="SELECT COUNT(*) FROM orders",
            )
            verification = verify_experience_candidate(candidate, sqlite_path=task.agent_input.sqlite_path)
            store = MemoryStore()
            memory = write_memory_after_task(store=store, task=task, verification=verification, timestamp="t1")
        self.assertTrue(verification.passed)
        self.assertIsNotNone(memory)
        self.assertIn("orders", memory.depends_on_tables)
        self.assertNotIn(task.gold.gold_sql, memory.content)
        self.assertIn("Future utility is unknown", memory.content)

    def test_failed_experience_is_not_written_to_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            train_root = _make_fake_bird_train(Path(tmp))
            task = load_bird_train(train_root).tasks[0]
            candidate = build_experience_candidate(
                task.agent_input,
                db_snapshot=task.agent_input.db_id,
                generated_sql="SELECT missing_column FROM orders",
            )
            verification = verify_experience_candidate(candidate, sqlite_path=task.agent_input.sqlite_path)
            store = MemoryStore()
            memory = write_memory_after_task(store=store, task=task, verification=verification, timestamp="t1")
        self.assertFalse(verification.passed)
        self.assertIsNone(memory)
        self.assertEqual(store.all_records(), [])

    def test_current_task_memory_is_not_visible_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            train_root = _make_fake_bird_train(Path(tmp))
            task = load_bird_train(train_root).tasks[0]
            candidate = build_experience_candidate(
                task.agent_input,
                db_snapshot=task.agent_input.db_id,
                generated_sql="SELECT COUNT(*) FROM orders",
            )
            verification = verify_experience_candidate(candidate, sqlite_path=task.agent_input.sqlite_path)
            store = MemoryStore()
            write_memory_after_task(store=store, task=task, verification=verification, timestamp="t1")
        with self.assertRaises(AssertionError):
            assert_later_task_can_only_see_prior_memories(current_task=task, store=store)

    def test_paired_real_agent_runs_require_same_conditions_and_complete_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            train_root = _make_fake_bird_train(Path(tmp))
            task = load_bird_train(train_root).tasks[1]
            gold = execute_readonly_sql(task.agent_input.sqlite_path, task.gold.gold_sql)
            empty_exec = execute_readonly_sql(task.agent_input.sqlite_path, "SELECT city FROM orders ORDER BY amount ASC LIMIT 1")
            memory_exec = execute_readonly_sql(task.agent_input.sqlite_path, "SELECT city FROM orders ORDER BY amount DESC LIMIT 1")
        empty = SqlAgentRun(task.agent_input.question_id, task.agent_input.db_id, task.agent_input.db_id, "fixed-test-agent", "", empty_exec, 1, [], 0, seed=7)
        with_memory = SqlAgentRun(task.agent_input.question_id, task.agent_input.db_id, task.agent_input.db_id, "fixed-test-agent", "", memory_exec, 1, ["m1"], 10, seed=7)
        self.assertTrue(paired_runs_are_comparable(empty, with_memory))
        self.assertFalse(evaluate_agent_run_against_gold(empty, gold))
        self.assertTrue(evaluate_agent_run_against_gold(with_memory, gold))


if __name__ == "__main__":
    unittest.main()
