#!/usr/bin/env python3
"""Hash-gated watcher for the frozen strict terminal evaluator."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


EVALUATOR_ROOT = Path("/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_terminal_evaluator_v1_20260718")
PACKAGE_ROOT = Path("/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718")
RUNTIME_ROOT = Path("/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_2_1_20260718")
OUTPUT_ROOT = Path("/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_terminal_evaluation_v1_20260718")
PYTHON = Path("/data1/qlyu/software/envs/pvrig-v6-tc/bin/python")
EVALUATOR = EVALUATOR_ROOT / "evaluate_v2_2_2_strict_terminal_v1.py"
CONTRACT = EVALUATOR_ROOT / "STRICT_TERMINAL_EVALUATION_CONTRACT_V1.json"
FREEZE = EVALUATOR_ROOT / "STRICT_TERMINAL_EVALUATOR_IMPLEMENTATION_FREEZE_V1.json"
GRAPH = PACKAGE_ROOT / "plan" / "job_graph.json"
EXPECTED = {
    EVALUATOR: "a6c5e759d8999a76d56132b3c0131a3378651a223d437ab0289d6ab5a7a5f0eb",
    CONTRACT: "51895361a4bcf98ca4bf6020c9d922cc28d72822dff4826d9f477728784bafed",
    FREEZE: "c2c3d33efeb843e9914d2720d4c35b80760155d26b9d6a07ea2b113645a44128",
    GRAPH: "2dab5078ad81f3b3c02fc995ce0a7b556e638d905c20d73d5eeebe81b86a0f57",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    if OUTPUT_ROOT.exists():
        raise RuntimeError(f"output_root_preexists:{OUTPUT_ROOT}")
    for path, expected in EXPECTED.items():
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"hash_gate_failed:{path}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    atomic_json(OUTPUT_ROOT / "WATCHER_STATUS.json", {
        "status": "WAITING_STRICT_RUNTIME_TERMINAL",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "sealed_evaluation_access_count": 0,
    })
    terminal_path = RUNTIME_ROOT / "TERMINAL.json"
    while not terminal_path.is_file():
        time.sleep(30)
    upstream = json.loads(terminal_path.read_text(encoding="utf-8"))
    if upstream != {"returncode": 0, "status": "PASS"}:
        atomic_json(OUTPUT_ROOT / "WATCHER_TERMINAL.json", {
            "status": "FAIL_UPSTREAM_STRICT_RUNTIME",
            "upstream_terminal": upstream,
            "upstream_terminal_sha256": sha256(terminal_path),
            "sealed_evaluation_access_count": 0,
        })
        return 1
    result_dir = OUTPUT_ROOT / "result"
    command = [
        str(PYTHON), str(EVALUATOR),
        "--contract", str(CONTRACT),
        "--job-graph", str(GRAPH),
        "--runtime-root", str(RUNTIME_ROOT),
        "--output-dir", str(result_dir),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    (OUTPUT_ROOT / "EVALUATOR_STDOUT.log").write_text(completed.stdout, encoding="utf-8")
    (OUTPUT_ROOT / "EVALUATOR_STDERR.log").write_text(completed.stderr, encoding="utf-8")
    atomic_json(OUTPUT_ROOT / "WATCHER_TERMINAL.json", {
        "status": "PASS_STRICT_TERMINAL_EVALUATION_COMPLETE" if completed.returncode == 0 else "FAIL_STRICT_TERMINAL_EVALUATION",
        "returncode": completed.returncode,
        "upstream_terminal_sha256": sha256(terminal_path),
        "evaluator_sha256": EXPECTED[EVALUATOR],
        "contract_sha256": EXPECTED[CONTRACT],
        "freeze_sha256": EXPECTED[FREEZE],
        "job_graph_sha256": EXPECTED[GRAPH],
        "sealed_evaluation_access_count": 0,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
