from __future__ import annotations

import json
import unittest

from sql_memory_agent.bird import default_bird_dev_root, load_bird_dev, sqlite_schema_summary
from sql_memory_agent.branching import AgentVisibleTaskContext, generate_semantic_branches, select_memories_for_task
from sql_memory_agent.memory import MemoryStore
from sql_memory_agent.models import MemoryRecord, MemoryStatus


def _memory(memory_id: str, *, status: MemoryStatus = MemoryStatus.ACTIVE, db_version: str = "retail_v1") -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        content="For retail_v1 net sales subtract refunds.refund_amount from orders.order_amount.",
        source_task_id="source",
        created_at=memory_id,
        applies_to_db_version=db_version,
        depends_on_tables=["orders", "refunds"],
        depends_on_columns=["orders.order_amount", "refunds.refund_amount"],
        status=status,
    )


class BranchingTests(unittest.TestCase):
    def test_empty_memory_store_allows_empty_combination(self) -> None:
        store = MemoryStore()
        context = AgentVisibleTaskContext(
            task_id="t",
            db_version_id="retail_v1",
            question="Which city has the highest net sales after refunds?",
            schema_text="orders(order_amount); cities(city_name); refunds(refund_amount)",
        )
        result = select_memories_for_task(context=context, store=store)
        self.assertEqual(result.selected_memory_ids, [])
        self.assertGreaterEqual(len(result.branches), 1)

    def test_duplicate_candidates_are_deduplicated_in_final_combination(self) -> None:
        store = MemoryStore()
        store.add(_memory("mem_refund"), timestamp="t1", reason="test")
        context = AgentVisibleTaskContext(
            task_id="t",
            db_version_id="retail_v1",
            question="Which city has the highest net sales after refunds?",
            schema_text="orders(order_amount); stores(store_id); cities(city_name); refunds(refund_amount)",
        )
        result = select_memories_for_task(context=context, store=store)
        self.assertGreaterEqual(len(result.candidates), 2)
        self.assertEqual(result.selected_memory_ids, ["mem_refund"])

    def test_quarantined_deleted_and_wrong_version_memories_are_filtered(self) -> None:
        store = MemoryStore()
        store.add(_memory("active"), timestamp="t1", reason="test")
        store.add(_memory("quarantined", status=MemoryStatus.QUARANTINED), timestamp="t2", reason="test")
        store.add(_memory("deleted", status=MemoryStatus.DELETED), timestamp="t3", reason="test")
        store.add(_memory("v2", db_version="retail_v2"), timestamp="t4", reason="test")
        context = AgentVisibleTaskContext(
            task_id="t",
            db_version_id="retail_v1",
            question="Which city has the highest net sales after refunds?",
            schema_text="orders(order_amount); stores(store_id); cities(city_name); refunds(refund_amount)",
        )
        result = select_memories_for_task(context=context, store=store)
        self.assertEqual(result.selected_memory_ids, ["active"])


    def test_time_and_filter_question_gets_specific_branches(self) -> None:
        branches = generate_semantic_branches(
            question="Please list the phone numbers of direct charter-funded schools opened after 2000/1/1.",
            schema_text="schools(Phone, FundingType, OpenDate, Charter, School)",
        )
        ids = {branch.branch_id for branch in branches}
        self.assertIn("requested_output", ids)
        self.assertIn("filter_conditions", ids)
        self.assertIn("time_conditions", ids)



    def test_column_matching_uses_boundaries_for_powerful_foil(self) -> None:
        branches = generate_semantic_branches(
            question="Which are the cards that have incredibly powerful foils?",
            schema_text="cards(power, cardKingdomFoilId, cardKingdomId)",
            evidence="incredibly powerful foils refers to cardKingdomFoilId is not null AND cardKingdomId is not null",
        )
        fields = {field for branch in branches for field in branch.related_columns}
        self.assertIn("cards.cardKingdomFoilId", fields)
        self.assertIn("cards.cardKingdomId", fields)
        self.assertNotIn("cards.power", fields)

    def test_from_city_schools_is_filter_condition(self) -> None:
        branches = generate_semantic_branches(
            question="What is the average number of test takers from Fresno schools that opened between 1/1/1980 and 12/31/1980?",
            schema_text="schools(OpenDate, City, School); satscores(NumTstTakr)",
        )
        ids = {branch.branch_id for branch in branches}
        self.assertIn("filter_conditions", ids)
        self.assertIn("time_conditions", ids)
        self.assertIn("metric_or_aggregation", ids)

    def test_generic_count_does_not_attach_every_schema_table(self) -> None:
        branches = generate_semantic_branches(
            question="How many accounts are staying in East Bohemia region?",
            schema_text="account(account_id, district_id, frequency, date); district(district_id, A3); loan(loan_id, amount, date)",
            evidence="A3 contains the data of region.",
        )
        metric = next(branch for branch in branches if branch.branch_id == "metric_or_aggregation")
        self.assertIn("account", metric.related_tables)
        self.assertNotIn("loan", metric.related_tables)


    def test_non_fallback_branch_without_tables_does_not_retrieve_everything(self) -> None:
        store = MemoryStore()
        store.add(_memory("mem_refund"), timestamp="t1", reason="test")
        context = AgentVisibleTaskContext(
            task_id="t",
            db_version_id="retail_v1",
            question="What is the answer?",
            schema_text="mystery_table(id, note)",
        )
        result = select_memories_for_task(context=context, store=store)
        self.assertEqual(result.selected_memory_ids, [])
        self.assertEqual(result.candidates, [])

    def test_unreliable_branch_split_falls_back_to_full_question(self) -> None:
        branches = generate_semantic_branches(
            question="What is unusual here?",
            schema_text="mystery_table(id, note)",
        )
        self.assertEqual(len(branches), 1)
        self.assertTrue(branches[0].fallback)
        self.assertEqual(branches[0].branch_id, "full_question_fallback")

    def test_bird_agent_input_selection_does_not_serialize_gold(self) -> None:
        dev_root = default_bird_dev_root()
        if not (dev_root / "dev.json").is_file():
            self.skipTest(f"BIRD dev data not staged: {dev_root}")
        task = load_bird_dev(dev_root, limit=1).tasks[0]
        context = AgentVisibleTaskContext(
            task_id=str(task.agent_input.question_id),
            db_version_id=task.agent_input.db_id,
            question=task.agent_input.question,
            schema_text=sqlite_schema_summary(task.agent_input.sqlite_path),
            evidence=task.agent_input.evidence,
        )
        result = select_memories_for_task(context=context, store=MemoryStore())
        serialized = json.dumps(result.to_log_payload(), sort_keys=True)
        self.assertNotIn(task.gold.gold_sql, serialized)
        self.assertNotIn("gold", serialized.lower())
        self.assertGreaterEqual(len(result.branches), 1)


if __name__ == "__main__":
    unittest.main()
