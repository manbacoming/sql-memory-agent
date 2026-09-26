#!/usr/bin/env python3
"""Small BIRD dev integration check: load tasks and execute gold SQL read-only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sql_memory_agent.bird import load_bird_dev  # noqa: E402
from sql_memory_agent.bird_eval import execute_readonly_sql  # noqa: E402


def select_tasks(tasks, *, limit: int, one_per_db: bool):
    if not one_per_db:
        return tasks[:limit]
    selected = []
    seen = set()
    for task in tasks:
        db_id = task.agent_input.db_id
        if db_id in seen:
            continue
        seen.add(db_id)
        selected.append(task)
        if len(selected) >= limit:
            break
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev-root", default="/root/autodl-tmp/sql-memory-agent-data/bird/extracted/dev_20240627")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--one-per-db", action="store_true", help="check at most one task from each db_id")
    parser.add_argument("--timeout-ms", type=int, default=2000)
    parser.add_argument("--max-rows", type=int, default=1000)
    args = parser.parse_args()

    bundle = load_bird_dev(args.dev_root)
    tasks = select_tasks(bundle.tasks, limit=args.limit, one_per_db=args.one_per_db)
    results = []
    success = 0
    for task in tasks:
        execution = execute_readonly_sql(
            task.agent_input.sqlite_path,
            task.gold.gold_sql,
            timeout_ms=args.timeout_ms,
            max_rows=args.max_rows,
        )
        ok = execution.error is None
        if ok:
            success += 1
        results.append(
            {
                "question_id": task.agent_input.question_id,
                "db_id": task.agent_input.db_id,
                "sqlite_path": task.agent_input.sqlite_path,
                "success": ok,
                "error": execution.error,
                "row_count": None if execution.rows is None else len(execution.rows),
                "truncated": execution.truncated,
            }
        )
    summary = {
        "dev_root": bundle.root,
        "mode": "one_per_db" if args.one_per_db else "first_n",
        "checked": len(results),
        "success": success,
        "failed": len(results) - success,
        "results": results,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if success == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
