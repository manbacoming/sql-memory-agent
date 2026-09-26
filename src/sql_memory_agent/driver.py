"""Deterministic sequential toy experiment driver."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from .branching import AgentVisibleTaskContext, select_memories_for_task
from .example_data import DEFAULT_DATA_ROOT, ensure_toy_databases, toy_tasks
from .memory import MemoryStore
from .models import DatabaseVersion, MemoryRecord, TaskRecord
from .paired_eval import evaluate_empty_vs_memories
from .solver_stub import DeterministicTestingSolver

@dataclass
class EventLogEntry:
    event_type: str
    task_id: str | None
    db_version_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass
class SequentialRunResult:
    events: list[EventLogEntry]
    memory_store: MemoryStore
    paired_evaluations: list[Any]

def _timestamp(step: int) -> str:
    return f"toy-step-{step:04d}"

def _refund_memory_v1(source_task_id: str, timestamp: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id="mem_v1_refund_rule",
        content="For retail_v1 net sales subtract refunds.refund_amount from orders.order_amount.",
        source_task_id=source_task_id,
        created_at=timestamp,
        applies_to_db_version="retail_v1",
        depends_on_tables=["orders", "refunds"],
        depends_on_columns=["orders.order_amount", "refunds.refund_amount"],
    )

def _refund_memory_v2(source_task_id: str, timestamp: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id="mem_v2_refund_rule",
        content="For retail_v2 net sales subtract approved refund_events.returned_amount from orders.order_amount.",
        source_task_id=source_task_id,
        created_at=timestamp,
        applies_to_db_version="retail_v2",
        depends_on_tables=["orders", "refund_events"],
        depends_on_columns=["orders.order_amount", "refund_events.returned_amount", "refund_events.approved"],
    )

def _task_context(task: TaskRecord, db: DatabaseVersion) -> AgentVisibleTaskContext:
    return AgentVisibleTaskContext(
        task_id=task.task_id,
        db_version_id=db.version_id,
        question=task.question,
        schema_text=db.description,
    )

def run_sequential_demo(data_root: Path = DEFAULT_DATA_ROOT) -> SequentialRunResult:
    dbs: dict[str, DatabaseVersion] = ensure_toy_databases(data_root)
    tasks: list[TaskRecord] = toy_tasks()
    store = MemoryStore()
    solver = DeterministicTestingSolver()
    events: list[EventLogEntry] = []
    paired = []
    step = 0
    current_db: str | None = None
    for task in tasks:
        db = dbs[task.db_version_id]
        if current_db is not None and current_db != db.version_id:
            step += 1
            ops = store.quarantine_affected(
                changed_tables={"refunds"},
                changed_columns={"refunds.refund_amount"},
                timestamp=_timestamp(step),
                reason="database switched to v2; v1 refund table/column removed",
            )
            events.append(EventLogEntry("database_switch_quarantine", task.task_id, db.version_id, {"operations": [op.to_dict() for op in ops]}))
        current_db = db.version_id

        step += 1
        selection = select_memories_for_task(context=_task_context(task, db), store=store)
        retrieved = selection.selected_memories
        events.append(EventLogEntry("memory_selection_once", task.task_id, db.version_id, selection.to_log_payload()))

        step += 1
        outcome = solver.solve(task, db, retrieved, budget_turns=4)
        events.append(EventLogEntry("answer", task.task_id, db.version_id, outcome.to_dict()))

        step += 1
        events.append(EventLogEntry("verify", task.task_id, db.version_id, {"correct": outcome.correct, "expected_result": task.expected_result, "actual_result": outcome.result}))

        comparison = evaluate_empty_vs_memories(task=task, db=db, memories=retrieved, solver=solver, budget_turns=4)
        paired.append(comparison)
        events.append(EventLogEntry("paired_eval", task.task_id, db.version_id, {
            "same_database_snapshot": comparison.same_database_snapshot,
            "empty_correct": comparison.empty_memory.correct,
            "selected_correct": comparison.selected_memory.correct,
            "empty_turns": comparison.empty_memory.turns,
            "selected_turns": comparison.selected_memory.turns,
        }))

        step += 1
        if task.task_id == "task_v1_learn_refund_rule":
            op = store.add(_refund_memory_v1(task.task_id, _timestamp(step)), timestamp=_timestamp(step), reason="verified v1 task taught refund deduction rule")
            events.append(EventLogEntry("memory_operation", task.task_id, db.version_id, op.to_dict()))
        elif task.task_id == "task_v2_refund_schema_changed":
            op = store.add(_refund_memory_v2(task.task_id, _timestamp(step)), timestamp=_timestamp(step), reason="verified v2 schema uses refund_events.returned_amount")
            events.append(EventLogEntry("memory_operation", task.task_id, db.version_id, op.to_dict()))
        else:
            for memory in retrieved:
                op = store.keep(memory.memory_id, timestamp=_timestamp(step), reason="retrieved memory remained valid for this v1 task")
                events.append(EventLogEntry("memory_operation", task.task_id, db.version_id, op.to_dict()))
    return SequentialRunResult(events, store, paired)

def summarize_run(result: SequentialRunResult) -> dict[str, Any]:
    return {
        "events": [event.to_dict() for event in result.events],
        "memories": [memory.to_dict() for memory in result.memory_store.all_records()],
        "operations": [operation.to_dict() for operation in result.memory_store.operations],
    }
