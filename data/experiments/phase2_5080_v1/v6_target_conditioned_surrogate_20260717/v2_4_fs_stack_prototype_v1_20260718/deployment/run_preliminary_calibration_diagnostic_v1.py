#!/usr/bin/env python3
"""Run the non-promotable Stage1-contact calibration diagnostic plan.

This helper exists only to diagnose why the preregistered gradient grid had no
eligible point.  It does not create a calibration receipt or implementation
freeze and it never performs an optimizer step.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import subprocess
from typing import Any


EXPECTED_STATUS = "PRELIMINARY_STAGE1_CONTACT_DIAGNOSTIC_ONLY_NON_PROMOTABLE"
LANES = {"C_SPLIT_MARGINAL", "D_SPLIT_PAIR"}


def run(plan_path: pathlib.Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("status") != EXPECTED_STATUS or set(plan.get("commands", {})) != LANES:
        raise RuntimeError("diagnostic_plan_contract_invalid")
    if plan.get("optimizer_steps") != 0 or plan.get("outer_metrics_access_count") != 0:
        raise RuntimeError("diagnostic_plan_access_contract_invalid")
    root = pathlib.Path(plan["runtime_root"])
    if os.path.lexists(root):
        raise RuntimeError(f"diagnostic_runtime_exists:{root}")
    if not root.parent.is_dir() or root.parent.is_symlink():
        raise RuntimeError("diagnostic_runtime_parent_invalid")
    root.mkdir()

    def one(lane: str) -> dict[str, Any]:
        record = plan["commands"][lane]
        command = [str(value) for value in record["command"]]
        if "--calibration-only" not in command:
            raise RuntimeError(f"diagnostic_not_calibration_only:{lane}")
        environment = os.environ.copy()
        environment.update({
            "CUDA_VISIBLE_DEVICES": str(record["gpu"]),
            "OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8",
            "OPENBLAS_NUM_THREADS": "8", "NUMEXPR_NUM_THREADS": "8",
            "TOKENIZERS_PARALLELISM": "false",
        })
        log_path = root / f"{lane}.log"
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT,
                env=environment, check=False,
            )
        return {"lane": lane, "returncode": completed.returncode, "log": str(log_path)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = {lane: future.result() for lane, future in {
            lane: pool.submit(one, lane) for lane in sorted(LANES)
        }.items()}
    status = "PASS_PRELIMINARY_DIAGNOSTIC_EXECUTION" if all(
        item["returncode"] == 0 for item in results.values()
    ) else "FAIL_PRELIMINARY_DIAGNOSTIC_EXECUTION"
    receipt = {
        "schema_version": "pvrig_v2_4_preliminary_calibration_diagnostic_execution_v1",
        "status": status,
        "promotion_authorized": False,
        "implementation_freeze_authorized": False,
        "optimizer_steps": 0,
        "outer_metrics_access_count": 0,
        "v4_f_access_count": 0,
        "plan_path": str(plan_path),
        "lane_results": results,
        "claim_boundary": plan["claim_boundary"],
    }
    output = root / "DIAGNOSTIC_EXECUTION_RECEIPT.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if status.startswith("FAIL"):
        raise RuntimeError(status)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.plan), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
