#!/usr/bin/env python3
"""Run the deterministic no-GPU toy experiment and print a compact log."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sql_memory_agent.driver import run_sequential_demo, summarize_run  # noqa: E402

def main() -> None:
    result = run_sequential_demo()
    print(json.dumps(summarize_run(result), indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
