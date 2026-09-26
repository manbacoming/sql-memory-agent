from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sql_memory_agent.bird import default_bird_dev_root, load_bird_dev, load_bird_train, sqlite_path_for_db
from sql_memory_agent.driver import run_sequential_demo


class BirdReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dev_root = default_bird_dev_root()
        if not (self.dev_root / "dev.json").is_file():
            self.skipTest(f"BIRD dev data not staged: {self.dev_root}")

    def test_db_id_maps_to_sqlite_file(self) -> None:
        bundle = load_bird_dev(self.dev_root, limit=5)
        self.assertGreater(len(bundle.tasks), 0)
        for task in bundle.tasks:
            path = sqlite_path_for_db(self.dev_root, task.agent_input.db_id)
            self.assertTrue(path.is_file())
            self.assertEqual(str(path), task.agent_input.sqlite_path)
            self.assertTrue(path.name.endswith(".sqlite"))

    def test_agent_input_serialization_excludes_gold_sql(self) -> None:
        bundle = load_bird_dev(self.dev_root, limit=1)
        task = bundle.tasks[0]
        agent_payload = task.agent_input.to_dict()
        serialized = json.dumps(agent_payload, sort_keys=True)
        self.assertNotIn("SQL", agent_payload)
        self.assertNotIn("gold", serialized.lower())
        self.assertNotIn(task.gold.gold_sql, serialized)
        self.assertIn("question", agent_payload)
        self.assertIn("sqlite_path", agent_payload)

    def test_current_task_still_cannot_use_own_memory(self) -> None:
        result = run_sequential_demo()
        first = next(e for e in result.events if e.event_type == "memory_selection_once" and e.task_id == "task_v1_learn_refund_rule")
        self.assertEqual(first.payload["selected_memory_ids"], [])

    def test_train_records_without_question_id_use_stable_file_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_dir = root / "train_databases" / "shop"
            db_dir.mkdir(parents=True)
            sqlite_path = db_dir / "shop.sqlite"
            sqlite_path.write_bytes(b"SQLite format 3\x00")
            (root / "train.json").write_text(
                json.dumps(
                    [
                        {"db_id": "shop", "question": "first", "evidence": "", "SQL": "SELECT 1"},
                        {"db_id": "shop", "question": "second", "evidence": "", "SQL": "SELECT 2"},
                    ]
                ),
                encoding="utf-8",
            )
            bundle = load_bird_train(root)
        self.assertEqual([task.agent_input.question_id for task in bundle.tasks], [0, 1])
        self.assertEqual([task.gold.question_id for task in bundle.tasks], [0, 1])


if __name__ == "__main__":
    unittest.main()
