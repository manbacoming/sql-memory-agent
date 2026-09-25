"""Serializable records for the toy SQL-memory experiment."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal

class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    DELETED = "DELETED"

class MemoryOperationType(str, Enum):
    ADD = "ADD"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    KEEP = "KEEP"
    QUARANTINE = "QUARANTINE"

@dataclass(frozen=True)
class DatabaseVersion:
    version_id: str
    path: str
    description: str
    schema_epoch: int
    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    db_version_id: str
    question: str
    gold_sql: str
    expected_result: list[tuple[Any, ...]]
    split: Literal["toy"] = "toy"
    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass
class MemoryHistoryEntry:
    operation: str
    timestamp: str
    reason: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    def to_dict(self) -> dict[str, Any]: return asdict(self)

@dataclass
class MemoryRecord:
    memory_id: str
    content: str
    source_task_id: str
    created_at: str
    applies_to_db_version: str
    depends_on_tables: list[str]
    depends_on_columns: list[str]
    status: MemoryStatus = MemoryStatus.ACTIVE
    history: list[MemoryHistoryEntry] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["history"] = [entry.to_dict() for entry in self.history]
        return data

@dataclass
class MemoryOperation:
    op_type: MemoryOperationType
    memory_id: str
    timestamp: str
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["op_type"] = self.op_type.value
        return data

@dataclass(frozen=True)
class SolverOutcome:
    task_id: str
    db_version_id: str
    sql: str
    result: list[tuple[Any, ...]] | None
    correct: bool
    turns: int
    memory_count: int
    error: str | None = None
    @property
    def score(self) -> float:
        if not self.correct:
            return 0.0
        return 1000.0 - float(self.turns) - 0.01 * float(self.memory_count)
    def to_dict(self) -> dict[str, Any]: return asdict(self)
