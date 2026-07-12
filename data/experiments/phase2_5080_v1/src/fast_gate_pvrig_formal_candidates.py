#!/usr/bin/env python3
"""Apply cheap sequence, CDR novelty, and liability gates before model scoring."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
WORKSPACE_ROOT = EXP_DIR.parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from build_cdr_masks_v2_3 import heuristic_result  # noqa: E402

DEFAULT_INPUT = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/rfantibody_candidates_exact_dedup_v1.csv"
DEFAULT_POSITIVES = WORKSPACE_ROOT / "docking/calibration/patent_success_validation"
DEFAULT_OUTPUT = EXP_DIR / "prepared/pvrig_teacher_formal_v1_candidates/fast_gate"
STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
HYDROPHOBIC = set("AVILMFWY")
CLAIM_BOUNDARY = "cheap_sequence_gate_not_binding_docking_developability_or_blocking_truth"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aligned_identity(left: str, right: str) -> float:
    """Return global-alignment matches divided by the longer CDR length."""
    left, right = left.upper(), right.upper()
    if not left or not right:
        return 0.0
    previous = [0] * (len(right) + 1)
    for aa in left:
        current = [0]
        for index, bb in enumerate(right, start=1):
            current.append(max(previous[index], current[index - 1], previous[index - 1] + int(aa == bb)))
        previous = current
    return 100.0 * previous[-1] / max(len(left), len(right))


def load_positive_cdrs(root: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(root.glob("case*/inputs/*.fasta")):
        sequence = "".join(
            line.strip().upper()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith(">")
        )
        result = heuristic_result(sequence, "known_positive_calibration")
        if result.status == "unresolved":
            raise ValueError(f"Could not extract positive CDRs from {path}: {result.fallback_reason}")
        rows.append(
            {
                "positive_id": path.parent.parent.name,
                "sequence": sequence,
                "cdr1": result.cdrs["cdr1"],
                "cdr2": result.cdrs["cdr2"],
                "cdr3": result.cdrs["cdr3"],
            }
        )
    if not rows:
        raise FileNotFoundError(f"No positive calibration FASTAs under {root}")
    return rows


def glyco_motifs(sequence: str) -> list[str]:
    return [match.group(0) for match in re.finditer(r"N[^P][ST]", sequence)]


def longest_run(sequence: str, alphabet: set[str]) -> int:
    best = current = 0
    for residue in sequence:
        current = current + 1 if residue in alphabet else 0
        best = max(best, current)
    return best


def max_homopolymer(sequence: str) -> int:
    return max((len(match.group(0)) for match in re.finditer(r"(.)\1*", sequence)), default=0)


def gate_row(row: pd.Series, positives: Sequence[dict[str, str]]) -> dict[str, Any]:
    sequence = str(row["vhh_sequence"]).upper()
    cdrs = {name: str(row[f"{name}_after"]).upper() for name in ("cdr1", "cdr2", "cdr3")}
    hard_failures = []
    review_flags = []
    if not sequence or set(sequence) - STANDARD_AA:
        hard_failures.append("nonstandard_or_empty_sequence")
    if not 95 <= len(sequence) <= 160:
        hard_failures.append("sequence_length_outside_95_160")
    if any(not value for value in cdrs.values()):
        hard_failures.append("missing_cdr")
    if sequence.count("C") < 2:
        hard_failures.append("missing_conserved_cysteines")
    if any(glyco_motifs(value) for value in cdrs.values()):
        hard_failures.append("cdr_n_linked_glyco_motif")
    if any(max_homopolymer(value) >= 5 for value in cdrs.values()):
        hard_failures.append("cdr_homopolymer_ge_5")
    if any(longest_run(value, HYDROPHOBIC) >= 4 for value in cdrs.values()):
        review_flags.append("cdr_hydrophobic_run_ge_4")
    if any(max(Counter(value).values(), default=0) / max(len(value), 1) >= 0.45 for value in cdrs.values()):
        review_flags.append("cdr_low_complexity_residue_fraction_ge_0_45")

    best_identity = -1.0
    best_positive = ""
    best_cdr = ""
    for positive in positives:
        for cdr_name, cdr in cdrs.items():
            identity = aligned_identity(cdr, positive[cdr_name])
            if identity > best_identity:
                best_identity = identity
                best_positive = positive["positive_id"]
                best_cdr = cdr_name
    exact_positive = next((item["positive_id"] for item in positives if sequence == item["sequence"]), "")
    if exact_positive:
        hard_failures.append("exact_known_positive_sequence")
    if best_identity >= 80.0:
        hard_failures.append("max_positive_cdr_identity_ge_80")
    elif best_identity >= 75.0:
        review_flags.append("max_positive_cdr_identity_75_to_80")
    tier = "FORMAL_ELIGIBLE" if not hard_failures and best_identity < 75.0 else "RESERVE_REVIEW"
    if hard_failures:
        tier = "HARD_FAIL"
    return {
        **row.to_dict(),
        "fast_gate_tier": tier,
        "hard_fail": bool(hard_failures),
        "hard_failure_reasons": ";".join(sorted(set(hard_failures))),
        "review_flags": ";".join(sorted(set(review_flags))),
        "max_positive_cdr_identity": round(best_identity, 3),
        "max_identity_positive_id": best_positive,
        "max_identity_cdr": best_cdr,
        "exact_positive_id": exact_positive,
        "cdr_glyco_motif_count": sum(len(glyco_motifs(value)) for value in cdrs.values()),
        "max_cdr_hydrophobic_run": max(longest_run(value, HYDROPHOBIC) for value in cdrs.values()),
        "max_cdr_homopolymer": max(max_homopolymer(value) for value in cdrs.values()),
        "fast_gate_claim_boundary": CLAIM_BOUNDARY,
    }


def run(input_path: Path, positive_root: Path, output_dir: Path) -> dict[str, Any]:
    frame = pd.read_csv(input_path)
    required = {"candidate_id", "vhh_sequence", "sequence_sha256", "cdr1_after", "cdr2_after", "cdr3_after"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Candidate input is missing {sorted(missing)}")
    if frame["sequence_sha256"].duplicated().any():
        raise ValueError("Fast gate requires exact-deduplicated candidates")
    positives = load_positive_cdrs(positive_root)
    output = pd.DataFrame([gate_row(row, positives) for _, row in frame.iterrows()])
    output = output.sort_values(["hard_fail", "fast_gate_tier", "candidate_id"]).reset_index(drop=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_path = output_dir / "fast_gate_all_v1.csv"
    pass_path = output_dir / "fast_gate_formal_eligible_v1.csv"
    reserve_path = output_dir / "fast_gate_reserve_review_v1.csv"
    fail_path = output_dir / "fast_gate_hard_fail_v1.csv"
    output.to_csv(all_path, index=False)
    output[output["fast_gate_tier"] == "FORMAL_ELIGIBLE"].to_csv(pass_path, index=False)
    output[output["fast_gate_tier"] == "RESERVE_REVIEW"].to_csv(reserve_path, index=False)
    output[output["fast_gate_tier"] == "HARD_FAIL"].to_csv(fail_path, index=False)
    tier_counts = dict(Counter(output["fast_gate_tier"].astype(str)))
    audit: dict[str, Any] = {
        "status": "PASS_FAST_GATE_COMPLETED",
        "schema_version": "pvrig_formal_candidate_fast_gate_audit_v1",
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "input_unique_candidates": len(frame),
        "positive_calibration_count": len(positives),
        "tier_counts": tier_counts,
        "hard_failure_counts": dict(
            Counter(
                reason
                for value in output["hard_failure_reasons"].astype(str)
                for reason in value.split(";")
                if reason
            )
        ),
        "review_flag_counts": dict(
            Counter(
                reason
                for value in output["review_flags"].astype(str)
                for reason in value.split(";")
                if reason
            )
        ),
        "output_paths": {"all": str(all_path), "formal_eligible": str(pass_path), "reserve": str(reserve_path), "hard_fail": str(fail_path)},
        "output_sha256": {"all": sha256_file(all_path), "formal_eligible": sha256_file(pass_path), "reserve": sha256_file(reserve_path), "hard_fail": sha256_file(fail_path)},
        "next_gate": "official validator and ANARCI/IMGT on Node1, then generic model/QC stratified teacher sampling",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (output_dir / "fast_gate_audit_v1.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--positive-root", type=Path, default=DEFAULT_POSITIVES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.input, args.positive_root, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
