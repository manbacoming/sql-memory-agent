#!/usr/bin/env python3
"""Check whether the staged resources can run a tiny real BIRD train chain.

This script is intentionally read-only: it does not download data, load a model,
or start GPU inference. It reports blocking missing resources instead of falling
back to toy or BIRD dev results.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sql_memory_agent.bird import BirdLoadError, default_bird_train_root, load_bird_train, same_db_task_flow  # noqa: E402

TRAIN_URL = "https://bird-bench.oss-cn-beijing.aliyuncs.com/train.zip"
DATA_ROOT = Path("/root/autodl-tmp/sql-memory-agent-data")
MODEL_ROOT = Path("/root/autodl-tmp/sql-memory-agent-models")


def _disk(path: Path) -> dict[str, int]:
    usage = shutil.disk_usage(path)
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def _nvidia_smi_status() -> dict[str, str | bool]:
    path = shutil.which("nvidia-smi") or "/usr/bin/nvidia-smi"
    p = Path(path)
    if not p.exists():
        return {"available": False, "reason": "nvidia-smi_not_found"}
    if not os.access(p, os.X_OK):
        return {"available": False, "reason": "nvidia-smi_not_executable", "path": str(p)}
    try:
        out = subprocess.run([str(p), "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"], check=False, text=True, capture_output=True, timeout=10)
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"available": False, "reason": repr(exc), "path": str(p)}
    return {"available": out.returncode == 0, "reason": out.stderr.strip(), "path": str(p), "stdout": out.stdout.strip()}


def _model_files() -> list[str]:
    if not MODEL_ROOT.exists():
        return []
    patterns = ["*.safetensors", "pytorch_model*.bin", "config.json", "tokenizer.json"]
    files: list[str] = []
    for pattern in patterns:
        files.extend(str(path) for path in MODEL_ROOT.rglob(pattern))
    return sorted(files)[:20]


def main() -> int:
    report: dict[str, object] = {
        "train_url": TRAIN_URL,
        "data_root": str(DATA_ROOT),
        "model_root": str(MODEL_ROOT),
        "disk_autodl_tmp": _disk(Path("/root/autodl-tmp")),
        "nvidia_smi": _nvidia_smi_status(),
        "model_files_sample": _model_files(),
        "blocked_reasons": [],
    }
    train_zip = DATA_ROOT / "bird" / "raw" / "train.zip"
    train_root = default_bird_train_root()
    report["train_zip_exists"] = train_zip.is_file()
    report["train_zip_size"] = train_zip.stat().st_size if train_zip.is_file() else 0
    report["train_root"] = str(train_root)
    report["train_root_exists"] = train_root.is_dir()
    if not train_zip.is_file() and not train_root.is_dir():
        report["blocked_reasons"].append("BIRD train zip/databases are not staged")
    if not _model_files():
        report["blocked_reasons"].append("No local SQL Agent model files staged under /root/autodl-tmp/sql-memory-agent-models")
    if not report["nvidia_smi"].get("available"):
        report["blocked_reasons"].append("GPU state cannot be verified with nvidia-smi")

    try:
        bundle = load_bird_train(train_root, limit=200, require_sqlite=True)
        flow = same_db_task_flow(bundle.tasks, min_tasks=2)
        report["train_tasks_loaded"] = len(bundle.tasks)
        report["same_db_flow_length"] = len(flow)
        report["same_db_flow_db_id"] = flow[0].agent_input.db_id if flow else None
    except BirdLoadError as exc:
        report["train_tasks_loaded"] = 0
        report["same_db_flow_length"] = 0
        report["blocked_reasons"].append(str(exc))

    report["ready_for_real_chain"] = not report["blocked_reasons"]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
