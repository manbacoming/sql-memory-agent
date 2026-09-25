"""In-memory store with auditable long-term-memory operations."""
from __future__ import annotations
from copy import deepcopy
from .models import MemoryHistoryEntry, MemoryOperation, MemoryOperationType, MemoryRecord, MemoryStatus

class MemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self.operations: list[MemoryOperation] = []

    def all_records(self) -> list[MemoryRecord]:
        return list(self._records.values())

    def get(self, memory_id: str) -> MemoryRecord:
        return self._records[memory_id]

    def add(self, record: MemoryRecord, timestamp: str, reason: str) -> MemoryOperation:
        if record.memory_id in self._records:
            raise ValueError(f"duplicate memory id: {record.memory_id}")
        op = MemoryOperation(MemoryOperationType.ADD, record.memory_id, timestamp, reason)
        record.history.append(MemoryHistoryEntry(op.op_type.value, timestamp, reason, after=record.to_dict()))
        self._records[record.memory_id] = record
        self.operations.append(op)
        return op

    def update(self, memory_id: str, *, timestamp: str, reason: str, content: str | None = None,
               applies_to_db_version: str | None = None, depends_on_tables: list[str] | None = None,
               depends_on_columns: list[str] | None = None, status: MemoryStatus | None = None) -> MemoryOperation:
        rec = self._records[memory_id]
        before = deepcopy(rec.to_dict())
        if content is not None: rec.content = content
        if applies_to_db_version is not None: rec.applies_to_db_version = applies_to_db_version
        if depends_on_tables is not None: rec.depends_on_tables = depends_on_tables
        if depends_on_columns is not None: rec.depends_on_columns = depends_on_columns
        if status is not None: rec.status = status
        op = MemoryOperation(MemoryOperationType.UPDATE, memory_id, timestamp, reason)
        rec.history.append(MemoryHistoryEntry(op.op_type.value, timestamp, reason, before=before, after=rec.to_dict()))
        self.operations.append(op)
        return op

    def keep(self, memory_id: str, *, timestamp: str, reason: str) -> MemoryOperation:
        rec = self._records[memory_id]
        op = MemoryOperation(MemoryOperationType.KEEP, memory_id, timestamp, reason)
        rec.history.append(MemoryHistoryEntry(op.op_type.value, timestamp, reason, before=rec.to_dict(), after=rec.to_dict()))
        self.operations.append(op)
        return op

    def quarantine(self, memory_id: str, *, timestamp: str, reason: str) -> MemoryOperation:
        rec = self._records[memory_id]
        before = deepcopy(rec.to_dict())
        rec.status = MemoryStatus.QUARANTINED
        op = MemoryOperation(MemoryOperationType.QUARANTINE, memory_id, timestamp, reason)
        rec.history.append(MemoryHistoryEntry(op.op_type.value, timestamp, reason, before=before, after=rec.to_dict()))
        self.operations.append(op)
        return op

    def delete(self, memory_id: str, *, timestamp: str, reason: str) -> MemoryOperation:
        rec = self._records[memory_id]
        before = deepcopy(rec.to_dict())
        rec.status = MemoryStatus.DELETED
        op = MemoryOperation(MemoryOperationType.DELETE, memory_id, timestamp, reason)
        rec.history.append(MemoryHistoryEntry(op.op_type.value, timestamp, reason, before=before, after=rec.to_dict()))
        self.operations.append(op)
        return op

    def retrieve(self, *, db_version_id: str, query_tables: set[str] | None = None) -> list[MemoryRecord]:
        matches: list[MemoryRecord] = []
        for rec in self._records.values():
            if rec.status is not MemoryStatus.ACTIVE:
                continue
            if rec.applies_to_db_version != db_version_id:
                continue
            if query_tables is not None and not (set(rec.depends_on_tables) & query_tables):
                continue
            matches.append(rec)
        return sorted(matches, key=lambda r: r.created_at)

    def quarantine_affected(self, *, changed_tables: set[str], changed_columns: set[str], timestamp: str, reason: str) -> list[MemoryOperation]:
        ops: list[MemoryOperation] = []
        for rec in list(self._records.values()):
            if rec.status is not MemoryStatus.ACTIVE:
                continue
            if set(rec.depends_on_tables) & changed_tables or set(rec.depends_on_columns) & changed_columns:
                ops.append(self.quarantine(rec.memory_id, timestamp=timestamp, reason=reason))
        return ops
