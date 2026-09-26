#!/usr/bin/env python3
"""Review semantic branch generation on toy and BIRD dev samples."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sql_memory_agent.bird import default_bird_dev_root, load_bird_dev, sqlite_schema_summary  # noqa: E402
from sql_memory_agent.branching import AgentVisibleTaskContext, SemanticBranch, generate_semantic_branches  # noqa: E402
from sql_memory_agent.example_data import ensure_toy_databases, toy_tasks  # noqa: E402


BIRD_SAMPLE_IDS = [0, 4, 5, 13, 39, 62, 66, 89, 340, 531, 717, 1020]


@dataclass(frozen=True)
class AuditSample:
    sample_id: str
    source: str
    question_id: str
    db_id: str
    question: str
    evidence: str
    schema_text: str
    schema_source: str
    gold_sql: str | None
    coverage_tags: list[str]


@dataclass(frozen=True)
class AuditFinding:
    severity: str
    question_id: str
    db_id: str
    question: str
    branch_summary: str
    problem: str
    recommendation: str


def _legacy_branches(question: str, schema_text: str, evidence: str) -> list[str]:
    public = "\n".join(part for part in [question, schema_text, evidence] if part).lower()
    branches: list[str] = []
    if any(token in public for token in ["refund", "refunds", "returned", "return"]):
        if any(token in public for token in ["refunds", "refund_events", "refund_amount", "returned_amount"]):
            branches.append("refund_semantics")
    if any(token in public for token in ["sale", "sales", "order", "orders", "amount"]):
        if "city" in public or "cities" in public:
            if "orders" in public or "order_amount" in public:
                branches.append("city_sales_aggregation")
    return branches or ["full_question_fallback"]


def _coverage_tags(question: str, evidence: str) -> list[str]:
    text = f"{question}\n{evidence}".lower()
    tags: list[str] = []
    if re.search(r"how many|number of|count|average|rate|percent|total|sum|difference", text):
        tags.append("aggregation_or_metric")
    if re.search(r"highest|lowest|top \d+|most |least |rank|\d+(st|nd|rd|th) highest", text):
        tags.append("ranking_or_extreme")
    if re.search(r"after \d|before \d|between \d|in [12]\d{3}s?|opened|closed|year ?=", text):
        tags.append("time_condition")
    if re.search(r"with |where |whose |that |greater than|less than|more than|not more than|over \d|under |county|directly funded|charter|virtual", text):
        tags.append("filter_condition")
    if re.search(r"list |what |which |give |name |phone|address|number", text):
        tags.append("requested_output")
    return tags or ["unclear_or_simple_lookup"]


def _toy_samples() -> list[AuditSample]:
    dbs = ensure_toy_databases(Path("/root/autodl-tmp/sql-memory-agent-data/toy"))
    samples: list[AuditSample] = []
    for task in toy_tasks():
        db = dbs[task.db_version_id]
        samples.append(AuditSample(
            sample_id=f"toy:{task.task_id}",
            source="toy",
            question_id=task.task_id,
            db_id=task.db_version_id,
            question=task.question,
            evidence="",
            schema_text=db.description,
            schema_source="DatabaseVersion.description",
            gold_sql=task.gold_sql,
            coverage_tags=_coverage_tags(task.question, ""),
        ))
    return samples


def _bird_samples() -> tuple[list[AuditSample], list[int]]:
    root = default_bird_dev_root()
    if not (root / "dev.json").is_file():
        return [], BIRD_SAMPLE_IDS
    bundle = load_bird_dev(root)
    by_id = {task.agent_input.question_id: task for task in bundle.tasks}
    samples: list[AuditSample] = []
    missing: list[int] = []
    for question_id in BIRD_SAMPLE_IDS:
        task = by_id.get(question_id)
        if task is None:
            missing.append(question_id)
            continue
        schema_text = sqlite_schema_summary(task.agent_input.sqlite_path)
        samples.append(AuditSample(
            sample_id=f"bird:{question_id}",
            source="bird_dev",
            question_id=str(question_id),
            db_id=task.agent_input.db_id,
            question=task.agent_input.question,
            evidence=task.agent_input.evidence,
            schema_text=schema_text,
            schema_source=f"sqlite_schema_summary({task.agent_input.db_id})",
            gold_sql=task.gold.gold_sql,
            coverage_tags=_coverage_tags(task.agent_input.question, task.agent_input.evidence),
        ))
    return samples, missing


def load_samples() -> tuple[list[AuditSample], list[str]]:
    samples = _toy_samples()
    bird, missing_ids = _bird_samples()
    samples.extend(bird)
    notes = []
    if missing_ids:
        notes.append(f"BIRD dev ?????? question_id?{missing_ids}")
    covered = {tag for sample in samples for tag in sample.coverage_tags}
    for required in ["aggregation_or_metric", "ranking_or_extreme", "time_condition", "filter_condition", "requested_output"]:
        if required not in covered:
            notes.append(f"??????????{required}")
    return samples, notes


def _branch_ids(branches: Iterable[SemanticBranch]) -> set[str]:
    return {branch.branch_id for branch in branches}


def _branch_summary(branches: list[SemanticBranch]) -> str:
    return "; ".join(f"{branch.branch_id}: {branch.requirement or branch.description}" for branch in branches)


def _expected_branch_ids(sample: AuditSample) -> set[str]:
    expected: set[str] = set()
    if "requested_output" in sample.coverage_tags:
        expected.add("requested_output")
    if "aggregation_or_metric" in sample.coverage_tags:
        expected.add("metric_or_aggregation")
    if "ranking_or_extreme" in sample.coverage_tags:
        expected.add("ranking_or_extreme")
    if "time_condition" in sample.coverage_tags:
        expected.add("time_conditions")
    if "filter_condition" in sample.coverage_tags:
        expected.add("filter_conditions")
    return expected


def _gold_identifiers(gold_sql: str | None) -> set[str]:
    if not gold_sql:
        return set()
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", gold_sql))
    return {token.lower() for token in tokens if token.upper() not in {"SELECT", "FROM", "WHERE", "JOIN", "LEFT", "ON", "GROUP", "BY", "ORDER", "LIMIT", "AND", "OR", "AS", "DESC", "ASC", "COUNT", "SUM", "AVG", "MAX", "MIN"}}


def audit_sample(sample: AuditSample) -> tuple[list[SemanticBranch], list[str], list[AuditFinding]]:
    branches = generate_semantic_branches(question=sample.question, schema_text=sample.schema_text, evidence=sample.evidence)
    ids = _branch_ids(branches)
    legacy = _legacy_branches(sample.question, sample.schema_text, sample.evidence)
    expected = _expected_branch_ids(sample)
    findings: list[AuditFinding] = []

    legacy_missing = expected - set(legacy)
    if legacy_missing:
        findings.append(AuditFinding(
            severity="old_fixed",
            question_id=sample.question_id,
            db_id=sample.db_id,
            question=sample.question,
            branch_summary=", ".join(legacy),
            problem=f"??????????????{sorted(legacy_missing)}?",
            recommendation="?????????????????????????????",
        ))

    current_missing = expected - ids
    if current_missing:
        findings.append(AuditFinding(
            severity="needs_review",
            question_id=sample.question_id,
            db_id=sample.db_id,
            question=sample.question,
            branch_summary=_branch_summary(branches),
            problem=f"??????????????{sorted(current_missing)}?",
            recommendation="??????????????????????????",
        ))

    for branch in branches:
        if branch.uncertainty:
            findings.append(AuditFinding(
                severity="manual_check",
                question_id=sample.question_id,
                db_id=sample.db_id,
                question=sample.question,
                branch_summary=f"{branch.branch_id}: {branch.requirement or branch.description}",
                problem="?????????" + "?".join(branch.uncertainty),
                recommendation="?????? schema ?????????????",
            ))

    if sample.gold_sql:
        gold_tokens = _gold_identifiers(sample.gold_sql)
        related = {item.split(".")[-1].lower() for branch in branches for item in branch.related_columns}
        if gold_tokens and related and not (gold_tokens & related):
            findings.append(AuditFinding(
                severity="gold_reference_only",
                question_id=sample.question_id,
                db_id=sample.db_id,
                question=sample.question,
                branch_summary=_branch_summary(branches),
                problem="??????? gold SQL ????????????????? gold SQL ??????????????????????????",
                recommendation="??????????gold SQL ??????????? Agent ???",
            ))
    return branches, legacy, findings


def render_report(samples: list[AuditSample], notes: list[str]) -> str:
    all_findings: list[AuditFinding] = []
    lines: list[str] = [
        "# ??????????",
        "",
        "???? `scripts/audit_branching.py` ???BIRD dev ???????????????????????????????????",
        "???????? question?Agent ?? schema ????? evidence?gold SQL ???????????????????????????????? SQL Agent ???",
        "",
        "## ????",
        "",
        f"????????{len(samples)}?toy {sum(s.source == 'toy' for s in samples)}?BIRD dev {sum(s.source == 'bird_dev' for s in samples)}??",
    ]
    if notes:
        lines.extend(["", "?????????"])
        lines.extend(f"- {note}" for note in notes)
    lines.extend(["", "| source | question_id | db_id | ???? | schema ?? | ??? |", "|---|---:|---|---|---|---|"])
    for sample in samples:
        lines.append(f"| {sample.source} | {sample.question_id} | `{sample.db_id}` | {', '.join(sample.coverage_tags)} | `{sample.schema_source}` | {sample.question.replace('|', '/')} |")

    lines.extend(["", "## ??????", ""])
    for sample in samples:
        branches, legacy, findings = audit_sample(sample)
        all_findings.extend(findings)
        lines.extend([
            f"### {sample.source} / {sample.question_id} / `{sample.db_id}`",
            "",
            f"????{sample.question}",
            f"?????{sample.evidence or '???'}",
            f"schema ???`{sample.schema_source}`",
            f"???????`{', '.join(legacy)}`",
            "",
            "?????",
        ])
        for branch in branches:
            data = branch.to_dict()
            lines.extend([
                f"- `{branch.branch_id}` / {data['name']}",
                f"  - ?????{data['requirement']}",
                f"  - ?????{'; '.join(data['source_evidence']) if data['source_evidence'] else '???????'}",
                f"  - ????{', '.join(data['related_tables']) if data['related_tables'] else '???'}",
                f"  - ?????{', '.join(data['related_columns']) if data['related_columns'] else '???'}",
                f"  - ?????{', '.join(data['dependencies']) if data['dependencies'] else '?'}",
                f"  - ?????{'; '.join(data['uncertainty']) if data['uncertainty'] else '?'}",
            ])
        lines.append("")

    lines.extend(["", "## ??????????", ""])
    if not all_findings:
        lines.append("??????????????????????????????????????????????????")
    else:
        lines.append("| severity | question_id | db_id | ??/??? | ???? | ???? |")
        lines.append("|---|---:|---|---|---|---|")
        for finding in all_findings:
            lines.append(
                f"| {finding.severity} | {finding.question_id} | `{finding.db_id}` | {finding.branch_summary.replace('|', '/')} | {finding.problem.replace('|', '/')} | {finding.recommendation.replace('|', '/')} |"
            )

    fixed = sum(1 for finding in all_findings if finding.severity == "old_fixed")
    needs = sum(1 for finding in all_findings if finding.severity != "old_fixed")
    lines.extend([
        "",
        "## ??",
        "",
        f"- ??????????????????????????{fixed}?",
        f"- ???????????/????????{needs}?",
        "- ?????? SQL Agent ?????????????????",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true", help="write docs/BRANCHING_AUDIT.md")
    args = parser.parse_args()
    samples, notes = load_samples()
    report = render_report(samples, notes)
    if args.write_report:
        path = ROOT / "docs" / "BRANCHING_AUDIT.md"
        path.write_text(report, encoding="utf-8")
        print(path)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
