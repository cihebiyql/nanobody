#!/usr/bin/env python3
"""Independently validate the completed RFantibody V2 delivery artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_counts(root: Path, stage: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in (root / "docking/state" / stage).glob("*.json"):
        try:
            counts[str(read_json(path).get("status", "unknown"))] += 1
        except (OSError, json.JSONDecodeError):
            counts["unreadable"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.run_root.resolve()
    output = args.output or root / "reports/independent_final_validation.json"

    candidates = read_tsv(root / "data/candidates.tsv")
    sequence_qc = read_tsv(root / "data/sequence_qc.tsv")
    rf2 = read_tsv(root / "data/rf2_metrics.tsv")
    monomer = read_tsv(root / "data/monomer_qc.tsv")
    docking = read_tsv(root / "data/docking_runs.tsv")
    baseline = read_tsv(root / "data/docking_pose_baseline_metrics.tsv")
    consensus = read_tsv(root / "data/docking_pose_consensus.tsv")
    summary = read_tsv(root / "data/training_dataset/candidate_summary.tsv")
    normalized_candidates = read_tsv(root / "data/training_dataset/candidates.tsv")
    manifest = read_json(root / "data/training_dataset/dataset_manifest.json")
    final_audit = read_json(root / "reports/final_audit.json")

    candidate_ids = [row["candidate_id"] for row in candidates]
    sequences = [row["sequence"] for row in candidates]
    recomputed_sequence_hashes = [hashlib.sha256(sequence.encode()).hexdigest() for sequence in sequences]
    rf2_pairs = [(row["candidate_id"], row["seed"]) for row in rf2]
    rf2_by_seed = Counter(row["seed"] for row in rf2)
    nbb2_states = state_counts(root, "nbb2")
    haddock_states = state_counts(root, "haddock")
    postprocess_states = state_counts(root, "postprocess")

    selected_counts: dict[str, int] = {}
    for candidate_id in candidate_ids:
        selected = (
            root
            / "docking/haddock"
            / candidate_id
            / f"run_{candidate_id}_pvrig_8x6b_full_interface"
            / "6_seletopclusts"
        )
        selected_counts[candidate_id] = len(list(selected.glob("cluster_*_model_*.pdb"))) + len(
            list(selected.glob("cluster_*_model_*.pdb.gz"))
        )

    manifest_outputs = manifest["output_files"]
    output_hashes_match = True
    output_rows_match = True
    for item in manifest_outputs.values():
        path = Path(str(item["path"]))
        output_hashes_match &= path.is_file() and sha256(path) == item["sha256"]
        output_rows_match &= path.is_file() and len(read_tsv(path)) == item["rows"]

    summary_by_id = {row["candidate_id"]: row for row in summary}
    normalized_by_id = {row["candidate_id"]: row for row in normalized_candidates}
    token_splits: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for candidate_id, candidate in normalized_by_id.items():
        split = summary_by_id[candidate_id]["split"]
        for key in ("backbone_group_id", "arm_id", "sequence_group_id"):
            token_splits[(key, candidate[key])].add(split)
    split_violations = {
        f"{key}:{value}": sorted(splits)
        for (key, value), splits in token_splits.items()
        if len(splits) > 1
    }

    rescue_reports = [read_json(path) for path in sorted((root / "docking/reports").glob("*_haddock_rescue.json"))]
    checks = {
        "candidate_rows_1024": len(candidates) == 1024,
        "candidate_ids_unique_1024": len(set(candidate_ids)) == 1024,
        "candidate_sequences_unique_1024": len(set(sequences)) == 1024,
        "candidate_sequence_hashes_valid": recomputed_sequence_hashes == [row["sequence_sha256"] for row in candidates],
        "sequence_qc_1024_no_hard_fail": len(sequence_qc) == 1024
        and all(row["hard_fail"].strip().lower() in {"false", "0"} for row in sequence_qc),
        "rf2_3072_unique_candidate_seed_pairs": len(rf2) == 3072 and len(set(rf2_pairs)) == 3072,
        "rf2_each_seed_1024": rf2_by_seed == Counter({"42": 1024, "43": 1024, "44": 1024}),
        "rf2_not_used_as_negative_labels": all(row["rf2_failure_label_policy"] == "qc_status_only" for row in rf2),
        "nbb2_states_all_success": nbb2_states == Counter({"success": 1024}),
        "monomer_table_all_success": len(monomer) == 1024 and all(row["nbb2_status"] == "success" for row in monomer),
        "haddock_states_all_success": haddock_states == Counter({"success": 1024}),
        "all_candidates_have_selected_models": len(selected_counts) == 1024 and min(selected_counts.values()) >= 1,
        "docking_table_all_completed": len(docking) == 1024 and all(row["docking_status"] == "completed" for row in docking),
        "dual_reference_rows_complete": len(baseline) == 8192
        and len(consensus) == 4096
        and len({row["candidate_id"] for row in baseline}) == 1024
        and len({row["candidate_id"] for row in consensus}) == 1024,
        "postprocess_states_all_success": postprocess_states == Counter({"success": 1024}),
        "training_manifest_final_1024": manifest["mode"] == "final"
        and manifest["candidate_count"] == 1024
        and manifest["completed_docking_candidates"] == 1024,
        "training_output_hashes_match": output_hashes_match,
        "training_output_rows_match": output_rows_match,
        "training_axes_remain_separate": len(summary) == 1024
        and all(row["binder_axis_status"] == "deferred" and row["binder_label"] == "unknown" for row in summary)
        and all(row["docking_status"] == "completed" for row in summary),
        "split_has_no_hard_key_leakage": not split_violations
        and manifest["split_audit"]["leakage_violation_count"] == 0,
        "two_way_split_is_explicit": manifest["split_counts"] == {"train": 522, "validation": 502}
        and manifest["split_audit"]["test_split_available"] is False,
        "known_positive_reference_is_present": manifest["source_files"]["known_positives"]["exists"] is True,
        "all_rescue_reports_successful": len(rescue_reports) == 3
        and all(report.get("result") == "success" for report in rescue_reports),
        "final_audit_passes": final_audit["status"] == "PASS"
        and all(bool(value) for value in final_audit["checks"].values()),
        "scientific_boundary_is_explicit": "not experimental binding, Kd, or blockade proof"
        in str(final_audit["scientific_boundary"]),
    }
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "counts": {
            "candidates": len(candidates),
            "rf2_rows": len(rf2),
            "nbb2_success": nbb2_states["success"],
            "haddock_success": haddock_states["success"],
            "postprocess_success": postprocess_states["success"],
            "baseline_rows": len(baseline),
            "consensus_rows": len(consensus),
            "training_pose_rows": manifest_outputs["docking_pose_features.tsv"]["rows"],
            "rescue_reports": len(rescue_reports),
        },
        "split_counts": manifest["split_counts"],
        "split_audit": manifest["split_audit"],
        "split_violations": split_violations,
        "selected_model_count_range": [min(selected_counts.values()), max(selected_counts.values())],
        "scientific_boundary": final_audit["scientific_boundary"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
