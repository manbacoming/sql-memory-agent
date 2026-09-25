"""Paired evaluation for empty-memory versus selected-memory combinations."""
from __future__ import annotations
from dataclasses import dataclass
from .models import DatabaseVersion, MemoryRecord, SolverOutcome, TaskRecord
from .solver_stub import DeterministicTestingSolver

@dataclass(frozen=True)
class PairedEvaluation:
    task_id: str
    db_version_id: str
    empty_memory: SolverOutcome
    selected_memory: SolverOutcome
    @property
    def same_database_snapshot(self) -> bool:
        return self.empty_memory.db_version_id == self.selected_memory.db_version_id == self.db_version_id

def evaluate_empty_vs_memories(*, task: TaskRecord, db: DatabaseVersion, memories: list[MemoryRecord], solver: DeterministicTestingSolver, budget_turns: int) -> PairedEvaluation:
    empty = solver.solve(task, db, [], budget_turns)
    selected = solver.solve(task, db, memories, budget_turns)
    return PairedEvaluation(task.task_id, db.version_id, empty, selected)
