"""Small real-data chain primitives with strict gold isolation.

These helpers are resource-light. They do not download data, load a model, or
start GPU work. They prepare the BIRD train task-flow and memory protocol so a
real SQL Agent can be plugged in only when train databases and a model are
explicitly staged outside Git.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .bird import BirdAgentTaskInput, BirdTaskRecord
from .bird_eval import SqlExecution, execute_readonly_sql
from .memory import MemoryStore
from .models import MemoryRecord


@dataclass(frozen=True)
class SqlAgentRun:
    question_id: int
    db_id: str
    db_snapshot: str
    model_name: str
    generated_sql: str
    execution: SqlExecution
    turns: int
    memory_ids: list[str]
    memory_token_count: int
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["execution"]["status"] = self.execution.status.value
        data["execution"]["evaluable"] = self.execution.evaluable
        return data


@dataclass(frozen=True)
class ExperienceCandidate:
    source_question_id: int
    db_id: str
    db_snapshot: str
    generated_sql: str
    referenced_tables: list[str]
    referenced_columns: list[str]
    verification_notes: list[str] = field(default_factory=list)

    def to_memory_content(self) -> str:
        tables = ", ".join(self.referenced_tables) or "unknown tables"
        columns = ", ".join(self.referenced_columns) or "unknown columns"
        return (
            f"Source task {self.source_question_id} produced a verified read-only SQL experience over {self.db_id}. "
            f"Referenced tables: {tables}. Referenced columns: {columns}. "
            "The generated SQL text is intentionally not stored in memory to avoid leaking evaluator gold strings. "
            "Future utility is unknown."
        )


@dataclass(frozen=True)
class ExperienceVerification:
    candidate: ExperienceCandidate
    passed: bool
    reason: str
    execution: SqlExecution | None = None


def _sqlite_catalog(sqlite_path: str | Path) -> tuple[set[str], set[str]]:
    path = Path(sqlite_path)
    uri = f"file:{path.as_posix()}?mode=ro"
    tables: set[str] = set()
    columns: set[str] = set()
    with sqlite3.connect(uri, uri=True) as con:
        con.execute("PRAGMA query_only = ON")
        for (table_name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall():
            table = str(table_name)
            tables.add(table)
            quoted = '"' + table.replace('"', '""') + '"'
            for row in con.execute(f"PRAGMA table_info({quoted})").fetchall():
                columns.add(f"{table}.{row[1]}")
    return tables, columns


def _sql_identifier_hits(sql: str, sqlite_path: str | Path) -> tuple[list[str], list[str]]:
    lowered = sql.lower()
    tables, columns = _sqlite_catalog(sqlite_path)
    table_hits = [table for table in sorted(tables) if re.search(rf"(?<![a-z0-9_]){re.escape(table.lower())}(?![a-z0-9_])", lowered)]
    column_hits: list[str] = []
    for column in sorted(columns):
        _, col = column.split(".", 1)
        if re.search(rf"(?<![a-z0-9_]){re.escape(col.lower())}(?![a-z0-9_])", lowered):
            column_hits.append(column)
    return table_hits, column_hits


def build_experience_candidate(agent_input: BirdAgentTaskInput, *, db_snapshot: str, generated_sql: str) -> ExperienceCandidate:
    tables, columns = _sql_identifier_hits(generated_sql, agent_input.sqlite_path)
    return ExperienceCandidate(
        source_question_id=agent_input.question_id,
        db_id=agent_input.db_id,
        db_snapshot=db_snapshot,
        generated_sql=generated_sql,
        referenced_tables=tables,
        referenced_columns=columns,
    )


def verify_experience_candidate(
    candidate: ExperienceCandidate,
    *,
    sqlite_path: str | Path,
    timeout_ms: int = 2000,
    max_rows: int = 1000,
) -> ExperienceVerification:
    if not candidate.referenced_tables:
        return ExperienceVerification(candidate, False, "no_referenced_tables")
    execution = execute_readonly_sql(sqlite_path, candidate.generated_sql, timeout_ms=timeout_ms, max_rows=max_rows)
    if execution.error is not None:
        return ExperienceVerification(candidate, False, "sql_execution_failed", execution)
    if not execution.evaluable:
        return ExperienceVerification(candidate, False, execution.incomplete_reason or "sql_result_incomplete", execution)
    return ExperienceVerification(candidate, True, "read_only_sql_complete", execution)


def memory_from_verified_experience(verification: ExperienceVerification, *, memory_id: str, created_at: str) -> MemoryRecord:
    if not verification.passed:
        raise ValueError(f"cannot write unverified experience: {verification.reason}")
    candidate = verification.candidate
    return MemoryRecord(
        memory_id=memory_id,
        content=candidate.to_memory_content(),
        source_task_id=str(candidate.source_question_id),
        created_at=created_at,
        applies_to_db_version=candidate.db_snapshot,
        depends_on_tables=list(candidate.referenced_tables),
        depends_on_columns=list(candidate.referenced_columns),
    )


def write_memory_after_task(
    *,
    store: MemoryStore,
    task: BirdTaskRecord,
    verification: ExperienceVerification,
    timestamp: str,
) -> MemoryRecord | None:
    if not verification.passed:
        return None
    memory = memory_from_verified_experience(
        verification,
        memory_id=f"bird_{task.agent_input.db_id}_{task.agent_input.question_id}_experience",
        created_at=timestamp,
    )
    store.add(memory, timestamp=timestamp, reason="verified generated SQL experience; future utility unknown")
    return memory


def assert_later_task_can_only_see_prior_memories(*, current_task: BirdTaskRecord, store: MemoryStore) -> None:
    for memory in store.all_records():
        if memory.source_task_id == str(current_task.agent_input.question_id):
            raise AssertionError("current task memory is visible before the task has completed")


def paired_runs_are_comparable(empty_run: SqlAgentRun, memory_run: SqlAgentRun) -> bool:
    return (
        empty_run.question_id == memory_run.question_id
        and empty_run.db_id == memory_run.db_id
        and empty_run.db_snapshot == memory_run.db_snapshot
        and empty_run.model_name == memory_run.model_name
        and empty_run.seed == memory_run.seed
    )


def evaluate_agent_run_against_gold(run: SqlAgentRun, gold_execution: SqlExecution) -> bool | None:
    if not run.execution.evaluable or not gold_execution.evaluable:
        return None
    return run.execution.rows == gold_execution.rows
