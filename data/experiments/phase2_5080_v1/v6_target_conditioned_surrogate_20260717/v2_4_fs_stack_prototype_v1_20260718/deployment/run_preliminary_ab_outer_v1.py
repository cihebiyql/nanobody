#!/usr/bin/env python3
"""Run the preliminary open-development A/B outer-fold baselines on Node1."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import subprocess
from typing import Any


STATUS = "PRELIMINARY_AB_OPEN_DEVELOPMENT_NOT_FULL_STACK_NOT_PROMOTABLE"
LANE_GPU = {"A_VHH_ONLY": 1, "B_TARGET_NO_CONTACT": 2}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(plan_path: pathlib.Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("status") != STATUS or plan.get("promotion_authorized") is not False:
        raise RuntimeError("preliminary_ab_plan_status_invalid")
    if plan.get("contact_supervision_used") is not False or plan.get("v4_f_access_count") != 0:
        raise RuntimeError("preliminary_ab_plan_evidence_boundary_invalid")
    if set(plan.get("lanes", {})) != set(LANE_GPU):
        raise RuntimeError("preliminary_ab_lane_closure_invalid")
    root = pathlib.Path(plan["runtime_root"])
    if os.path.lexists(root):
        raise RuntimeError(f"preliminary_ab_runtime_exists:{root}")
    if not root.parent.is_dir() or root.parent.is_symlink():
        raise RuntimeError("preliminary_ab_runtime_parent_invalid")
    root.mkdir()

    def one_lane(lane: str) -> list[dict[str, Any]]:
        record = plan["lanes"][lane]
        if int(record["gpu"]) != LANE_GPU[lane]:
            raise RuntimeError(f"preliminary_ab_gpu_invalid:{lane}")
        folds = record.get("folds")
        if [item.get("fold") for item in folds] != list(range(5)):
            raise RuntimeError(f"preliminary_ab_fold_closure:{lane}")
        results = []
        for item in folds:
            fold = int(item["fold"])
            command = [str(value) for value in item["command"]]
            if "--calibration-only" in command or "--tiny-e2e" in command:
                raise RuntimeError(f"preliminary_ab_forbidden_mode:{lane}:{fold}")
            if command.count("--marginal-weight") != 1 or command.count("--pair-weight") != 1:
                raise RuntimeError(f"preliminary_ab_contact_weight_flags:{lane}:{fold}")
            if command[command.index("--marginal-weight") + 1] != "0" or command[command.index("--pair-weight") + 1] != "0":
                raise RuntimeError(f"preliminary_ab_contact_weight_nonzero:{lane}:{fold}")
            output = pathlib.Path(command[command.index("--output-dir") + 1])
            if output != root / lane / f"fold_{fold}" or os.path.lexists(output):
                raise RuntimeError(f"preliminary_ab_output_contract:{lane}:{fold}")
            output.parent.mkdir(parents=True, exist_ok=True)
            environment = os.environ.copy()
            environment.update({
                "CUDA_VISIBLE_DEVICES": str(LANE_GPU[lane]),
                "OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8",
                "OPENBLAS_NUM_THREADS": "8", "NUMEXPR_NUM_THREADS": "8",
                "TOKENIZERS_PARALLELISM": "false",
            })
            log_path = output.parent / f"fold_{fold}.trainer.log"
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    command, stdout=log, stderr=subprocess.STDOUT,
                    env=environment, check=False,
                )
            if completed.returncode != 0:
                raise RuntimeError(f"preliminary_ab_trainer_failed:{lane}:{fold}:{completed.returncode}")
            result_path = output / "RESULT.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            observed_fold = (result.get("split") or {}).get("outer_fold", result.get("outer_fold"))
            if not str(result.get("status", "")).startswith("PASS") or result.get("lane") != lane or int(observed_fold) != fold:
                raise RuntimeError(f"preliminary_ab_result_identity:{lane}:{fold}")
            results.append({
                "fold": fold,
                "command_sha256": hashlib.sha256("\0".join(command).encode()).hexdigest(),
                "result_path": str(result_path), "result_sha256": sha256(result_path),
                "log_path": str(log_path), "log_sha256": sha256(log_path),
            })
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {lane: pool.submit(one_lane, lane) for lane in sorted(LANE_GPU)}
        lane_results = {lane: future.result() for lane, future in futures.items()}
    receipt = {
        "schema_version": "pvrig_v2_4_preliminary_ab_outer_execution_receipt_v1",
        "status": "PASS_PRELIMINARY_AB_OPEN_DEVELOPMENT_BASE_LANES",
        "plan_sha256": sha256(plan_path),
        "promotion_authorized": False,
        "full_stack_complete": False,
        "contact_supervision_used": False,
        "v4_f_access_count": 0,
        "lane_results": lane_results,
        "claim_boundary": plan["claim_boundary"],
    }
    output = root / "PRELIMINARY_AB_EXECUTION_RECEIPT.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.plan), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
