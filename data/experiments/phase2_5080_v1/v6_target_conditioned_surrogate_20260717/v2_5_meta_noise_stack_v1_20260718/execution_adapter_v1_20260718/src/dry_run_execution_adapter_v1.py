#!/usr/bin/env python3
"""Preauthorization dry-run of canonical hashes and inner C2 replay only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_SRC = HERE.parents[1] / "src"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BASE_SRC))

from evaluate_authorized_v2_5_strict_meta_v1 import recompute_inner_c2
from execution_common_v1 import (
    atomic_write_json,
    read_json,
    read_tsv,
    selected_c2_alpha_rows,
    sha256_file,
    unique_by,
    verify_named_hashes,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    contract_path = Path(args.contract).resolve()
    input_root = Path(args.input_root).resolve()
    output = Path(args.output_dir).resolve()
    contract = read_json(contract_path)
    hashes = verify_named_hashes(input_root, contract["canonical_inputs"])
    labels = unique_by(
        read_tsv(input_root / contract["canonical_inputs"]["labels"]["filename"]),
        "candidate_id", "label",
    )
    raw = unique_by(
        read_tsv(input_root / contract["canonical_inputs"]["coarse_pose_raw36"]["filename"]),
        "candidate_id", "raw36",
    )
    inner = read_tsv(input_root / contract["canonical_inputs"]["inner_manifest"]["filename"])
    frozen_alpha = selected_c2_alpha_rows(
        read_tsv(input_root / contract["canonical_inputs"]["existing_c2_alpha_selection"]["filename"])
    )
    predictions, audits = recompute_inner_c2(contract, labels, raw, inner, frozen_alpha)
    atomic_write_json(output / "PREAUTHORIZATION_DRY_RUN_RECEIPT.json", {
        "schema_version": "pvrig_v2_5_strict_meta_execution_adapter_dry_run_v1",
        "status": "PASS_PREAUTHORIZATION_BUILD_TEST_DRY_RUN",
        "contract_sha256": sha256_file(contract_path),
        "canonical_input_hashes": hashes,
        "candidate_count": len(labels),
        "inner_c2_candidate_count_by_outer_fold": {str(fold): len(rows) for fold, rows in predictions.items()},
        "selected_c2_alpha_by_outer_fold": {str(fold): value for fold, value in frozen_alpha.items()},
        "c2_replay_audits": audits,
        "D_lane_outer_evidence_opened": False,
        "performance_evaluation_performed": False,
        "formal_evaluator_launched": False,
        "execution_authorized": False,
        "v4_f_test32_access_count": 0,
        "claim_boundary": contract["claim_boundary"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
