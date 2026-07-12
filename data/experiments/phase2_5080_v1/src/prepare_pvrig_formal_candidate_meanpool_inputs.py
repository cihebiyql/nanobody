#!/usr/bin/env python3
"""Build the frozen mean-pooled embedding manifest for formal PVRIG designs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))
from phase2_v3_contracts import sha256_file, sha256_text  # noqa: E402

DEFAULT_INPUT = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/fast_gate/fast_gate_all_v1.csv"
DEFAULT_TARGET = DATA_ROOT / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_OUTPUT = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs/sequence_manifest_v3.csv"
ELIGIBLE_TIERS = {"FORMAL_ELIGIBLE", "RESERVE_REVIEW"}
CLAIM_BOUNDARY = "model_input_preparation_not_binding_docking_or_blocking_truth"


def read_fasta(path: Path) -> str:
    return "".join(
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(">")
    )


def prepare(input_path: Path, target_path: Path, output_path: Path) -> dict[str, Any]:
    frame = pd.read_csv(input_path)
    required = {"candidate_id", "vhh_sequence", "sequence_sha256", "fast_gate_tier"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Fast-gate input is missing {sorted(missing)}")
    frame = frame[frame["fast_gate_tier"].astype(str).isin(ELIGIBLE_TIERS)].copy()
    if frame.empty:
        raise ValueError("No formal-eligible or reserve candidates for model input preparation")
    if frame["sequence_sha256"].duplicated().any():
        raise ValueError("Candidate model input must be exact-sequence deduplicated")
    observed = frame["vhh_sequence"].astype(str).map(sha256_text)
    if not observed.equals(frame["sequence_sha256"].astype(str)):
        raise ValueError("Candidate sequence hashes differ from vhh_sequence")
    rows = [
        {
            "sequence_sha256": row.sequence_sha256,
            "sequence": row.vhh_sequence,
            "sequence_length": len(str(row.vhh_sequence)),
            "roles": "vhh",
        }
        for row in frame[["sequence_sha256", "vhh_sequence"]].itertuples(index=False)
    ]
    target = read_fasta(target_path)
    if not target:
        raise ValueError("PVRIG target FASTA is empty")
    target_hash = sha256_text(target)
    rows.append(
        {
            "sequence_sha256": target_hash,
            "sequence": target,
            "sequence_length": len(target),
            "roles": "antigen",
        }
    )
    output = pd.DataFrame(rows).sort_values("sequence_sha256").reset_index(drop=True)
    if output["sequence_sha256"].duplicated().any():
        raise ValueError("Candidate and target sequence hashes unexpectedly collide")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)
    audit = {
        "status": "PASS_PVRIG_FORMAL_MEANPOOL_INPUTS_READY",
        "schema_version": "pvrig_formal_candidate_meanpool_inputs_v1",
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "target_fasta": str(target_path),
        "target_fasta_sha256": sha256_file(target_path),
        "target_sequence_sha256": target_hash,
        "candidate_count": len(frame),
        "sequence_count": len(output),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    output_path.with_name("sequence_manifest_audit_v1.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--target-fasta", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    print(json.dumps(prepare(args.input, args.target_fasta, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
