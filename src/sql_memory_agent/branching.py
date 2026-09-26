"""Semantic-branch memory selection used before a SQL solver is called once."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .memory import MemoryStore
from .models import MemoryRecord


@dataclass(frozen=True)
class AgentVisibleTaskContext:
    """Only fields that may be shown to retrieval and the SQL Agent."""

    task_id: str
    db_version_id: str
    question: str
    schema_text: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticBranch:
    branch_id: str
    description: str
    query_terms: list[str]
    query_tables: list[str]
    fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryCandidate:
    memory_id: str
    branch_id: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemorySelectionPolicy:
    """Fixed testing policy; this is not a trained memory policy."""

    max_candidates: int = 20
    exploration_probability: float = 0.0
    policy_name: str = "fixed-branch-deduplicate"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemorySelectionResult:
    task_context: AgentVisibleTaskContext
    branches: list[SemanticBranch]
    candidates: list[MemoryCandidate]
    selected_memories: list[MemoryRecord]
    policy: MemorySelectionPolicy = field(default_factory=MemorySelectionPolicy)

    @property
    def selected_memory_ids(self) -> list[str]:
        return [memory.memory_id for memory in self.selected_memories]

    def to_log_payload(self) -> dict[str, Any]:
        return {
            "task_context": self.task_context.to_dict(),
            "branches": [branch.to_dict() for branch in self.branches],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_memory_ids": self.selected_memory_ids,
            "policy": self.policy.to_dict(),
            "solver_memory_selection_count": 1,
        }


def _contains_any(text: str, needles: set[str]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def generate_semantic_branches(*, question: str, schema_text: str, evidence: str = "") -> list[SemanticBranch]:
    """Build checkable semantic retrieval branches from agent-visible text only.

    The splitter is deliberately conservative. When the text does not expose a
    reliable semantic structure, it returns one fallback branch covering the full
    question instead of pretending a precise decomposition is known.
    """

    public_text = "\n".join(part for part in [question, schema_text, evidence] if part)
    lowered = public_text.lower()
    has_sales = _contains_any(lowered, {"sale", "sales", "order", "orders", "amount"})
    has_city = _contains_any(lowered, {"city", "cities"})
    has_refund = _contains_any(lowered, {"refund", "refunds", "returned", "return"})
    has_refund_schema = _contains_any(lowered, {"refunds", "refund_events", "refund_amount", "returned_amount"})
    has_orders_schema = _contains_any(lowered, {"orders", "order_amount"})

    branches: list[SemanticBranch] = []
    if has_refund and has_refund_schema:
        refund_tables = [name for name in ["refunds", "refund_events", "orders"] if name in lowered]
        branches.append(
            SemanticBranch(
                branch_id="refund_semantics",
                description="Determine how refund or returned amount fields affect net sales",
                query_terms=["refund", "returned amount", "net sales"],
                query_tables=refund_tables or ["refunds", "refund_events"],
            )
        )
    if has_sales and has_city and has_orders_schema:
        tables = [name for name in ["orders", "stores", "cities"] if name in lowered]
        branches.append(
            SemanticBranch(
                branch_id="city_sales_aggregation",
                description="Aggregate order amounts by city and compare sales",
                query_terms=["city", "sales", "orders"],
                query_tables=tables or ["orders", "stores", "cities"],
            )
        )

    if not branches:
        return [
            SemanticBranch(
                branch_id="full_question_fallback",
                description="Fallback to the full question because semantic decomposition is not reliable",
                query_terms=[question],
                query_tables=[],
                fallback=True,
            )
        ]
    return branches


def _candidate_reason(branch: SemanticBranch, memory: MemoryRecord) -> str:
    tables = sorted(set(branch.query_tables) & set(memory.depends_on_tables))
    if tables:
        return f"Branch `{branch.branch_id}` needs tables {', '.join(tables)}; this memory depends on those tables."
    return f"Branch `{branch.branch_id}` is the full-question fallback; this memory is compatible with the current database version."


def select_memories_for_task(
    *,
    context: AgentVisibleTaskContext,
    store: MemoryStore,
    policy: MemorySelectionPolicy | None = None,
) -> MemorySelectionResult:
    """Run one pre-solver memory selection pass with branch-level retrieval."""

    policy = policy or MemorySelectionPolicy()
    branches = generate_semantic_branches(
        question=context.question,
        schema_text=context.schema_text,
        evidence=context.evidence,
    )
    candidates: list[MemoryCandidate] = []
    selected_by_id: dict[str, MemoryRecord] = {}

    for branch in branches:
        query_tables = set(branch.query_tables) if branch.query_tables else None
        for memory in store.retrieve(db_version_id=context.db_version_id, query_tables=query_tables):
            candidates.append(MemoryCandidate(memory.memory_id, branch.branch_id, _candidate_reason(branch, memory)))
            if memory.memory_id not in selected_by_id and len(selected_by_id) < policy.max_candidates:
                selected_by_id[memory.memory_id] = memory

    return MemorySelectionResult(
        task_context=context,
        branches=branches,
        candidates=candidates,
        selected_memories=list(selected_by_id.values()),
        policy=policy,
    )
