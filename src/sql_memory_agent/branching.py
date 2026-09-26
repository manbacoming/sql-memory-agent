"""Semantic-branch memory selection used before a SQL solver is called once."""
from __future__ import annotations

import re
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
    name: str = ""
    requirement: str = ""
    source_evidence: list[str] = field(default_factory=list)
    related_tables: list[str] = field(default_factory=list)
    related_columns: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["name"]:
            data["name"] = self.branch_id
        if not data["requirement"]:
            data["requirement"] = self.description
        if not data["related_tables"]:
            data["related_tables"] = list(self.query_tables)
        return data


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


def _schema_tables(schema_text: str) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for part in schema_text.split("; "):
        if "(" not in part or not part.endswith(")"):
            continue
        table, columns = part.split("(", 1)
        name = table.strip()
        if not name:
            continue
        column_text = columns[:-1]
        parsed_columns = [col.strip().strip('`"') for col in column_text.split(",") if col.strip()]
        tables[name] = parsed_columns
    if tables:
        return tables

    # Toy schemas are sometimes short prose such as
    # "orders/stores/cities plus refunds.refund_amount". Treat this as a
    # conservative schema hint, not as a complete database catalog.
    common_words = {"plus", "with", "and", "schema", "update", "uses", "net", "sales", "subtract", "approved"}
    for table, column in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)", schema_text):
        tables.setdefault(table, [])
        if column not in tables[table]:
            tables[table].append(column)
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", schema_text):
        lowered = token.lower()
        if lowered in common_words or len(token) <= 2:
            continue
        if lowered.endswith("s") or "_" in lowered:
            tables.setdefault(token, [])
    return tables


_GENERIC_SCHEMA_WORDS = {
    "id", "type", "date", "status", "amount", "name", "number", "code", "state", "city", "county", "school",
    "account", "order", "value", "year", "month", "day", "time", "rate", "total", "average",
}


def _token_present(text: str, token: str) -> bool:
    escaped = re.escape(token.lower())
    return re.search(rf"(?<![a-z0-9_]){escaped}s?(?![a-z0-9_])", text.lower()) is not None


def _matching_schema_items(text: str, schema_text: str) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    tables = _schema_tables(schema_text)
    matched_tables: set[str] = set()
    matched_columns: set[str] = set()
    for table, columns in tables.items():
        table_low = table.lower()
        if _token_present(lowered, table_low):
            matched_tables.add(table)
        for column in columns:
            col_low = column.lower()
            normalized = col_low.replace("_", " ")
            quoted = f"`{col_low}`"
            if col_low in _GENERIC_SCHEMA_WORDS and quoted not in lowered:
                continue
            normalized_match = normalized != col_low and normalized in lowered
            if quoted in lowered or _token_present(lowered, col_low) or normalized_match:
                matched_columns.add(f"{table}.{column}")
                matched_tables.add(table)
    return sorted(matched_tables), sorted(matched_columns)

def _phrase_matches(text: str, patterns: list[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            phrase = match.group(0).strip()
            if phrase and phrase not in matches:
                matches.append(phrase)
    return matches


def _branch(
    *,
    branch_id: str,
    name: str,
    requirement: str,
    source_evidence: list[str],
    schema_text: str,
    public_text: str,
    query_terms: list[str],
    fallback: bool = False,
    dependencies: list[str] | None = None,
    uncertainty: list[str] | None = None,
) -> SemanticBranch:
    matched_tables, matched_columns = _matching_schema_items("\n".join(source_evidence + query_terms), schema_text)
    if not matched_tables:
        text_tables, text_columns = _matching_schema_items(public_text, schema_text)
        matched_tables = text_tables
        matched_columns = text_columns
    notes = list(uncertainty or [])
    if not matched_tables:
        notes.append("?????? schema ??????????")
    return SemanticBranch(
        branch_id=branch_id,
        name=name,
        description=requirement,
        requirement=requirement,
        source_evidence=source_evidence,
        query_terms=query_terms,
        query_tables=matched_tables,
        related_tables=matched_tables,
        related_columns=matched_columns,
        dependencies=list(dependencies or []),
        uncertainty=notes,
        fallback=fallback,
    )


def generate_semantic_branches(*, question: str, schema_text: str, evidence: str = "") -> list[SemanticBranch]:
    """Build checkable semantic retrieval branches from agent-visible text only.

    The splitter is deliberately conservative. It records uncertainty instead of
    pretending table/column links are known. When no specific semantic demand can
    be detected, it returns one fallback branch covering the full question.
    """

    natural_text = "\n".join(part for part in [question, evidence] if part)
    public_text = natural_text
    lowered = "\n".join(part for part in [question, evidence, schema_text] if part).lower()
    branches: list[SemanticBranch] = []

    refund_phrases = _phrase_matches(
        natural_text,
        [r"refund[^?.;]*", r"returned amount[^?.;]*", r"returned amounts[^?.;]*", r"return amount[^?.;]*"],
    )
    if refund_phrases:
        branches.append(_branch(
            branch_id="refund_semantics",
            name="Refund semantics",
            requirement="????????????????????",
            source_evidence=refund_phrases[:4],
            schema_text=schema_text,
            public_text=public_text,
            query_terms=["refund", "returned amount", "net sales"],
            uncertainty=[] if any(term in lowered for term in ["refund", "returned"]) else ["????????????"],
        ))

    output_phrases = _phrase_matches(
        question,
        [r"what (?:is|are)[^?.]*", r"which [^?.]*", r"please list[^?.]*", r"list [^?.]*", r"give [^?.]*", r"name [^?.]*", r"rank [^?.]*"],
    )
    generic_outputs = {"what is unusual here", "what are unusual here", "what is unusual"}
    output_phrases = [phrase for phrase in output_phrases if phrase.lower().strip() not in generic_outputs]
    if output_phrases:
        branches.append(_branch(
            branch_id="requested_output",
            name="Requested output",
            requirement="???????????????????",
            source_evidence=output_phrases[:3],
            schema_text=schema_text,
            public_text=public_text,
            query_terms=["requested output", "select target"],
        ))

    metric_phrases = _phrase_matches(
        natural_text,
        [r"eligible free rate[^.;?]*", r"excellence rate[^.;?]*", r"percent[^.;?]*", r"average[^.;?]*", r"total[^.;?]*", r"sum[^.;?]*", r"difference[^.;?]*", r"how many", r"number of", r"count\([^)]*\)"],
    )
    if metric_phrases:
        branches.append(_branch(
            branch_id="metric_or_aggregation",
            name="Metric or aggregation",
            requirement="???????????????????",
            source_evidence=metric_phrases[:5],
            schema_text=schema_text,
            public_text=public_text,
            query_terms=["metric", "aggregation", "count", "average", "rate", "total"],
            dependencies=["filter_conditions"],
        ))

    filter_phrases = _phrase_matches(
        natural_text,
        [r"with [^?.;]*", r"where [^?.;]*", r"in [A-Z][A-Za-z ]+", r"from [A-Z][A-Za-z ]+ schools", r"whose [^?.;]*", r"that (?:are|is|has|have|were|was)[^?.;]*", r"direct [^?.;]*", r"charter[- ][^?.;]*", r"[^?.;]*funded schools", r"exclusively virtual", r"greater than [^?.;]*", r"less than [^?.;]*", r"more than [^?.;]*", r"not more than [^?.;]*", r"over [0-9.]+", r"under [^?.;]*"],
    )
    if filter_phrases:
        branches.append(_branch(
            branch_id="filter_conditions",
            name="Filter conditions",
            requirement="??????????????????????????",
            source_evidence=filter_phrases[:6],
            schema_text=schema_text,
            public_text=public_text,
            query_terms=["filter", "condition", "threshold"],
        ))

    time_phrases = _phrase_matches(
        natural_text,
        [r"after [0-9][^?.;]*", r"before [0-9][^?.;]*", r"between [0-9][^?.;]*", r"in [12][0-9]{3}s?", r"opened [^?.;]*", r"closed [^?.;]*", r"year ?= ?[12][0-9]{3}"],
    )
    if time_phrases:
        branches.append(_branch(
            branch_id="time_conditions",
            name="Time conditions",
            requirement="??????????????",
            source_evidence=time_phrases[:5],
            schema_text=schema_text,
            public_text=public_text,
            query_terms=["date", "year", "opened", "closed", "time range"],
            dependencies=["filter_conditions"] if any(b.branch_id == "filter_conditions" for b in branches) else [],
        ))

    order_phrases = _phrase_matches(
        natural_text,
        [r"highest [^?.;]*", r"lowest [^?.;]*", r"top [0-9]+[^?.;]*", r"most [^?.;]*", r"least [^?.;]*", r"descending order", r"rank [^?.;]*", r"[0-9]+(?:st|nd|rd|th) highest[^?.;]*"],
    )
    if order_phrases:
        branches.append(_branch(
            branch_id="ranking_or_extreme",
            name="Ranking or extreme selection",
            requirement="????????/???Top-K ???????",
            source_evidence=order_phrases[:5],
            schema_text=schema_text,
            public_text=public_text,
            query_terms=["rank", "top", "highest", "lowest", "order"],
            dependencies=["metric_or_aggregation"] if any(b.branch_id == "metric_or_aggregation" for b in branches) else [],
        ))

    if _contains_any(lowered, {"join", "each", "respective", "per ", " by ", "among"}) and len(_schema_tables(schema_text)) > 1:
        branches.append(_branch(
            branch_id="entity_linking",
            name="Entity linking",
            requirement="????????????????",
            source_evidence=_phrase_matches(natural_text, [r"among [^?.;]*", r"each [^?.;]*", r"respective [^?.;]*", r"by [^?.;]*"])[:4],
            schema_text=schema_text,
            public_text=public_text,
            query_terms=["join", "entity", "group by"],
            uncertainty=["??? schema ???????????????"],
        ))

    if not branches:
        return [
            SemanticBranch(
                branch_id="full_question_fallback",
                name="Full question fallback",
                description="Fallback to the full question because semantic decomposition is not reliable",
                requirement="?????????????????????????",
                source_evidence=[question],
                query_terms=[question],
                query_tables=[],
                related_tables=[],
                related_columns=[],
                uncertainty=["??????????????????????????"],
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
        if not query_tables and not branch.fallback:
            continue
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
