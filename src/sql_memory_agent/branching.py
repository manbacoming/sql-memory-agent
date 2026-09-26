"""Semantic-branch memory selection used before a SQL solver is called once."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

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


CandidateMatchType = Literal["direct", "indirect", "exploration", "uncertain"]


@dataclass(frozen=True)
class CandidateSource:
    branch_id: str
    match_type: CandidateMatchType
    reason: str
    branch_requirement: str
    matched_content: list[str] = field(default_factory=list)
    matched_tables: list[str] = field(default_factory=list)
    matched_columns: list[str] = field(default_factory=list)
    dependency_chain: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryCandidate:
    memory_id: str
    sources: list[CandidateSource] = field(default_factory=list)

    def add_source(self, source: CandidateSource) -> None:
        key = (source.branch_id, source.match_type, tuple(source.dependency_chain))
        existing = {(item.branch_id, item.match_type, tuple(item.dependency_chain)) for item in self.sources}
        if key not in existing:
            self.sources.append(source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "sources": [source.to_dict() for source in self.sources],
        }


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
            dependencies=(
                (["metric_or_aggregation"] if any(b.branch_id == "metric_or_aggregation" for b in branches) else [])
                + (["refund_semantics"] if any(b.branch_id == "refund_semantics" for b in branches) else [])
            ),
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


def _memory_text(memory: MemoryRecord) -> str:
    return "\n".join([
        memory.content,
        " ".join(memory.depends_on_tables),
        " ".join(memory.depends_on_columns),
    ]).lower()


def _content_hits(text: str, terms: list[str]) -> list[str]:
    hits: list[str] = []
    for term in terms:
        normalized = term.lower().strip()
        if not normalized:
            continue
        if " " in normalized or "_" in normalized:
            present = normalized in text or normalized.replace(" ", "_") in text
        else:
            present = _token_present(text, normalized)
        if present and term not in hits:
            hits.append(term)
    return hits


def _direct_semantic_source(branch: SemanticBranch, memory: MemoryRecord) -> CandidateSource | None:
    memory_text = _memory_text(memory)
    branch_text = "\n".join([branch.branch_id, branch.requirement, *branch.source_evidence, *branch.query_terms]).lower()
    terms_by_branch = {
        "refund_semantics": ["refund", "refunds", "returned amount", "returned_amount", "deduct", "subtract", "net sales"],
        "metric_or_aggregation": ["average", "count", "sum", "total", "rate", "percent", "aggregation", "group by", "net sales"],
        "ranking_or_extreme": ["highest", "lowest", "top", "most", "least", "rank", "order by", "descending", "maximum", "minimum"],
        "requested_output": ["return", "select", "output", "list", "phone", "city", "api id", "name"],
        "filter_conditions": ["filter", "where", "condition", "threshold", "greater than", "less than", "not null", "county", "region"],
        "time_conditions": ["date", "year", "opened", "closed", "between", "after", "before"],
        "entity_linking": ["join", "foreign key", "link", "entity", "group by"],
    }
    semantic_terms = terms_by_branch.get(branch.branch_id, [])
    branch_hits = _content_hits(branch_text, semantic_terms)
    memory_hits = _content_hits(memory_text, semantic_terms)
    matched_terms = [term for term in semantic_terms if term in branch_hits and term in memory_hits]
    if branch.branch_id == "refund_semantics":
        core_refund_terms = {"refund", "refunds", "returned amount", "returned_amount", "deduct", "subtract"}
        if not (set(matched_terms) & core_refund_terms):
            return None
    if not matched_terms:
        return None
    matched_tables = sorted(set(branch.related_tables) & set(memory.depends_on_tables))
    matched_columns = sorted(set(branch.related_columns) & set(memory.depends_on_columns))
    return CandidateSource(
        branch_id=branch.branch_id,
        match_type="direct",
        reason=(
            f"Memory content contains semantic terms {', '.join(matched_terms)} that match "
            f"branch `{branch.branch_id}`; table/column overlap is only supporting evidence."
        ),
        branch_requirement=branch.requirement or branch.description,
        matched_content=matched_terms,
        matched_tables=matched_tables,
        matched_columns=matched_columns,
        evidence=branch.source_evidence,
    )


def _exploration_source(branch: SemanticBranch, memory: MemoryRecord) -> CandidateSource | None:
    matched_tables = sorted(set(branch.related_tables or branch.query_tables) & set(memory.depends_on_tables))
    matched_columns = sorted(set(branch.related_columns) & set(memory.depends_on_columns))
    if not matched_tables and not matched_columns and not branch.fallback:
        return None
    if branch.fallback:
        reason = f"Branch `{branch.branch_id}` is a fallback; compatible memory is kept only as an exploration candidate."
    else:
        reason = (
            f"Branch `{branch.branch_id}` shares tables/columns with this memory, but no direct semantic match was verified; "
            "kept as exploration rather than credited as solving the branch."
        )
    return CandidateSource(
        branch_id=branch.branch_id,
        match_type="exploration",
        reason=reason,
        branch_requirement=branch.requirement or branch.description,
        matched_tables=matched_tables,
        matched_columns=matched_columns,
        evidence=branch.source_evidence,
    )


def _indirect_source(branch: SemanticBranch, dependency: SemanticBranch, direct_source: CandidateSource) -> CandidateSource:
    return CandidateSource(
        branch_id=branch.branch_id,
        match_type="indirect",
        reason=(
            f"Branch `{branch.branch_id}` depends on `{dependency.branch_id}`; the memory directly matches "
            f"that upstream branch, not the current branch itself."
        ),
        branch_requirement=branch.requirement or branch.description,
        matched_content=list(direct_source.matched_content),
        matched_tables=list(direct_source.matched_tables),
        matched_columns=list(direct_source.matched_columns),
        dependency_chain=[dependency.branch_id, branch.branch_id],
        evidence=list(branch.source_evidence),
    )


def select_memories_for_task(
    *,
    context: AgentVisibleTaskContext,
    store: MemoryStore,
    policy: MemorySelectionPolicy | None = None,
) -> MemorySelectionResult:
    """Run one pre-solver memory selection pass with auditable branch-level evidence."""

    policy = policy or MemorySelectionPolicy()
    branches = generate_semantic_branches(
        question=context.question,
        schema_text=context.schema_text,
        evidence=context.evidence,
    )
    branch_by_id = {branch.branch_id: branch for branch in branches}
    memories = store.retrieve(db_version_id=context.db_version_id, query_tables=None)
    candidates_by_id: dict[str, MemoryCandidate] = {}
    selected_by_id: dict[str, MemoryRecord] = {}
    direct_sources: dict[tuple[str, str], CandidateSource] = {}

    def add_source(memory: MemoryRecord, source: CandidateSource) -> None:
        candidate = candidates_by_id.setdefault(memory.memory_id, MemoryCandidate(memory.memory_id))
        candidate.add_source(source)
        if memory.memory_id not in selected_by_id and len(selected_by_id) < policy.max_candidates:
            selected_by_id[memory.memory_id] = memory

    for branch in branches:
        for memory in memories:
            source = _direct_semantic_source(branch, memory)
            if source is None:
                continue
            direct_sources[(memory.memory_id, branch.branch_id)] = source
            add_source(memory, source)

    for branch in branches:
        for dependency_id in branch.dependencies:
            dependency = branch_by_id.get(dependency_id)
            if dependency is None:
                continue
            for memory in memories:
                direct_source = direct_sources.get((memory.memory_id, dependency_id))
                if direct_source is not None:
                    add_source(memory, _indirect_source(branch, dependency, direct_source))

    for branch in branches:
        for memory in memories:
            if (memory.memory_id, branch.branch_id) in direct_sources:
                continue
            existing = candidates_by_id.get(memory.memory_id)
            if existing is not None and any(source.branch_id == branch.branch_id for source in existing.sources):
                continue
            source = _exploration_source(branch, memory)
            if source is not None:
                add_source(memory, source)

    return MemorySelectionResult(
        task_context=context,
        branches=branches,
        candidates=list(candidates_by_id.values()),
        selected_memories=list(selected_by_id.values()),
        policy=policy,
    )
