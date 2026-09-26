"""BIRD dataset loading with explicit agent/evaluator separation."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class BirdLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class BirdAgentTaskInput:
    """Task fields visible to the SQL Agent. This object intentionally has no gold SQL."""

    question_id: int
    db_id: str
    question: str
    evidence: str
    difficulty: str | None
    sqlite_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BirdGoldRecord:
    """Evaluator-only gold fields. Never pass this object to the agent."""

    question_id: int
    db_id: str
    gold_sql: str


@dataclass(frozen=True)
class BirdTaskRecord:
    agent_input: BirdAgentTaskInput
    gold: BirdGoldRecord


@dataclass(frozen=True)
class BirdDevBundle:
    root: str
    tasks: list[BirdTaskRecord]

    def agent_inputs(self) -> list[BirdAgentTaskInput]:
        return [task.agent_input for task in self.tasks]


def default_bird_dev_root() -> Path:
    return Path("/root/autodl-tmp/sql-memory-agent-data/bird/extracted/dev_20240627")


def sqlite_path_for_db(dev_root: Path, db_id: str) -> Path:
    path = dev_root / "dev_databases" / db_id / f"{db_id}.sqlite"
    if not path.is_file():
        raise BirdLoadError(f"missing sqlite for db_id={db_id}: {path}")
    return path


def load_bird_dev(dev_root: str | Path | None = None, *, limit: int | None = None) -> BirdDevBundle:
    root = Path(dev_root) if dev_root is not None else default_bird_dev_root()
    dev_json = root / "dev.json"
    if not dev_json.is_file():
        raise BirdLoadError(f"missing dev.json: {dev_json}")
    records = json.loads(dev_json.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise BirdLoadError("dev.json must contain a list")
    tasks: list[BirdTaskRecord] = []
    for raw in records[:limit]:
        try:
            question_id = int(raw["question_id"])
            db_id = str(raw["db_id"])
            question = str(raw["question"])
            evidence = str(raw.get("evidence") or "")
            gold_sql = str(raw["SQL"])
            difficulty = raw.get("difficulty")
        except KeyError as exc:
            raise BirdLoadError(f"missing required field: {exc}") from exc
        sqlite_path = sqlite_path_for_db(root, db_id)
        agent = BirdAgentTaskInput(
            question_id=question_id,
            db_id=db_id,
            question=question,
            evidence=evidence,
            difficulty=str(difficulty) if difficulty is not None else None,
            sqlite_path=str(sqlite_path),
        )
        gold = BirdGoldRecord(question_id=question_id, db_id=db_id, gold_sql=gold_sql)
        tasks.append(BirdTaskRecord(agent_input=agent, gold=gold))
    return BirdDevBundle(root=str(root), tasks=tasks)


def sqlite_schema_summary(sqlite_path: str | Path, *, max_tables: int = 80) -> str:
    """Return a compact schema summary that is safe to show to an agent."""

    path = Path(sqlite_path)
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as con:
            table_rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchmany(max_tables)
            parts: list[str] = []
            for (table_name,) in table_rows:
                quoted = '"' + str(table_name).replace('"', '""') + '"'
                columns = [row[1] for row in con.execute(f"PRAGMA table_info({quoted})").fetchall()]
                parts.append(f"{table_name}({', '.join(columns)})")
            return "; ".join(parts)
    except sqlite3.Error as exc:
        raise BirdLoadError(f"could not read sqlite schema: {path}: {exc}") from exc
