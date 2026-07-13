#!/usr/bin/env python3
"""Aggregate formal Teacher500 pose, geometry, and contact-frequency labels."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import build_pvrig_teacher_v1 as base  # noqa: E402

DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"
DEFAULT_WORK_ROOT = EXP_DIR / "runs/pvrig_teacher_formal_v1/teacher500_postprocessed"
DEFAULT_PREPARED = EXP_DIR / "prepared/pvrig_teacher_formal_v1"
DEFAULT_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_teacher_manifest_v1.csv"
DEFAULT_AUDIT_JSON = EXP_DIR / "audits/pvrig_formal_teacher500_audit.json"
DEFAULT_AUDIT_MD = EXP_DIR / "audits/PVRIG_FORMAL_TEACHER500_AUDIT.md"
EXPECTED_CANDIDATES = 500
SCHEMA_VERSION = "pvrig_formal_teacher500_geometry_v1"
CLAIM_BOUNDARY = "prospective_docking_geometry_surrogate_not_binding_or_experimental_blocking_truth"
DATASET_ROLE = "prospective_multparent_pvrig_docking_teacher"
LEAKAGE_STATUS = "PROSPECTIVE_GENERATED_NOT_KNOWN_POSITIVE_OR_DERIVATIVE"

METADATA_FIELDS = [
    "selection_rank",
    "teacher_selection_layer",
    "layer_rank",
    "parent_id",
    "parent_framework_cluster",
    "formal_split",
    "target_patch_id",
    "hotspots_uniprot",
    "design_mode",
    "design_method",
    "designed_regions",
    "backbone_index",
    "mpnn_index",
    "cdr1_before",
    "cdr2_before",
    "cdr3_before",
    "cdr1_after",
    "cdr2_after",
    "cdr3_after",
    "fast_gate_tier",
    "generic_binding_prior",
    "model_uncertainty",
    "model_disagreement",
    "cheap_qc_score",
]
POSE_FIELDS = base.POSE_FIELDS + METADATA_FIELDS
CANDIDATE_FIELDS = base.CANDIDATE_FIELDS + METADATA_FIELDS


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    return base.sha256_file(path)


def metadata(row: dict[str, str]) -> dict[str, str]:
    return {field: row.get(field, "") for field in METADATA_FIELDS}


def make_case(row: dict[str, str], work_root: Path) -> base.Case:
    candidate_id = row["candidate_id"]
    workdir = work_root / candidate_id
    consensus = workdir / "reports" / f"{candidate_id}_8x6b_9e6y_consensus.csv"
    if not consensus.exists():
        raise FileNotFoundError(consensus)
    return base.Case(
        candidate_id=candidate_id,
        candidate_name=candidate_id,
        family=f"RFantibody_{row['target_patch_id']}_{row['design_mode']}",
        sequence=row["vhh_sequence"],
        calibration_role=DATASET_ROLE,
        workdir=workdir,
        consensus_csv=consensus,
    )


def update_common(record: dict[str, object], row: dict[str, str]) -> dict[str, object]:
    record.update(metadata(row))
    record["schema_version"] = SCHEMA_VERSION
    record["claim_boundary"] = CLAIM_BOUNDARY
    return record


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")


def teacher_manifest_row(row: dict[str, str], case: base.Case) -> dict[str, str]:
    return {
        **row,
        "schema_version": SCHEMA_VERSION,
        "teacher_dataset_role": DATASET_ROLE,
        "calibration_only": "false",
        "submission_eligible": "false_teacher_data_only_pending_separate_full_qc",
        "leakage_status": LEAKAGE_STATUS,
        "workdir": str(case.workdir),
        "consensus_csv": str(case.consensus_csv),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def known_positive_sequences(positive_root: Path) -> dict[str, str]:
    sequences: dict[str, str] = {}
    for row in base.read_csv(positive_root / "batch_manifest.csv"):
        candidate_id = base.clean(row["calibration_name"])
        fasta = base.find_one(positive_root / candidate_id / "inputs", "*.fasta")
        sequences[candidate_id] = base.read_single_fasta(fasta)
    return sequences


def write_report(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# PVRIG Formal Teacher500 Audit",
        "",
        f"- Status: `{audit['status']}`",
        f"- Candidates: `{audit['candidate_count']}/{EXPECTED_CANDIDATES}`",
        f"- Pose rows: `{audit['pose_count']}`",
        f"- Complete candidate summaries: `{audit['complete_candidate_count']}/{EXPECTED_CANDIDATES}`",
        f"- Parent framework clusters: `{audit['parent_framework_cluster_count']}`",
        f"- Exact known-positive overlap: `{audit['exact_known_positive_sequence_overlap_count']}`",
        f"- Claim boundary: `{CLAIM_BOUNDARY}`",
        "",
        "## Interpretation",
        "",
        "- These labels are computational geometry/contact-frequency surrogates, not binding or functional blocking truth.",
        "- 9E6Y is a second reference-interface rescoring of 8X6B-generated poses, not an independent second docking run.",
        "- Parent-cluster train/dev/test assignments are inherited from Parent40 and must not be randomized by candidate row.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    selection = read_csv(args.selection)
    if len(selection) != EXPECTED_CANDIDATES or len({row["candidate_id"] for row in selection}) != EXPECTED_CANDIDATES:
        raise ValueError(f"Selection must contain {EXPECTED_CANDIDATES} unique candidates")
    pose_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    contact_rows: list[dict[str, object]] = []
    manifest_rows: list[dict[str, str]] = []
    for row in sorted(selection, key=lambda value: int(value["selection_rank"])):
        case = make_case(row, args.work_root)
        case_poses, contacts = base.build_case_pose_rows(case, args.top_k, not args.skip_contacts)
        for pose in case_poses:
            update_common(pose, row)
        contact = base.contact_frequency_record(case, case_poses, contacts)
        contact["sequence"] = row["vhh_sequence"]
        contact["sequence_sha256"] = row["sequence_sha256"]
        update_common(contact, row)
        summary = base.candidate_summary(case, case_poses, contact, args.min_supporting_clusters)
        update_common(summary, row)
        summary.update(
            {
                "calibration_only": "false",
                "submission_eligible": "false_teacher_data_only_pending_separate_full_qc",
                "provisional_rule_status": "PROVISIONAL_DOCKING_TEACHER_LABEL_NOT_EXPERIMENTAL_TRUTH",
            }
        )
        pose_rows.extend(case_poses)
        contact_rows.append(contact)
        candidate_rows.append(summary)
        manifest_rows.append(teacher_manifest_row(row, case))

    args.prepared_out.mkdir(parents=True, exist_ok=True)
    candidate_path = args.prepared_out / "candidate_summary.csv"
    pose_path = args.prepared_out / "pose_summary.csv"
    contact_path = args.prepared_out / "pose_contact_frequency.jsonl"
    config_path = args.prepared_out / "teacher_config.json"
    base.write_csv(candidate_path, candidate_rows, CANDIDATE_FIELDS)
    base.write_csv(pose_path, pose_rows, POSE_FIELDS)
    write_jsonl(contact_path, contact_rows)
    base.write_csv(args.manifest_out, manifest_rows, list(manifest_rows[0]))
    config = {
        "schema_version": SCHEMA_VERSION,
        "top_k": args.top_k,
        "pose_generation_receptor": "8X6B",
        "independent_9e6y_docking": False,
        "min_supporting_clusters_for_provisional_stable_tier": args.min_supporting_clusters,
        "consensus_relevance": base.CONSENSUS_RELEVANCE,
        "relevance_weights": base.RELEVANCE_WEIGHTS,
        "parent_split_policy": "frozen_parent_framework_cluster_28_train_6_dev_6_test",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    selection_ids = {row["candidate_id"] for row in selection}
    id_sets = {
        "selection": selection_ids,
        "candidate_summary": {base.clean(row["candidate_id"]) for row in candidate_rows},
        "pose_summary": {base.clean(row["candidate_id"]) for row in pose_rows},
        "contact_frequency": {base.clean(row["candidate_id"]) for row in contact_rows},
        "teacher_manifest": {row["candidate_id"] for row in manifest_rows},
    }
    id_consistent = all(values == selection_ids for values in id_sets.values())
    positives = known_positive_sequences(args.positive_root)
    positive_sequences = set(positives.values())
    exact_overlaps = sorted(row["candidate_id"] for row in selection if row["vhh_sequence"] in positive_sequences)
    pose_counts = Counter(int(row["pose_count"]) for row in candidate_rows)
    audit: dict[str, Any] = {
        "status": "PASS_FORMAL_TEACHER500_READY",
        "schema_version": SCHEMA_VERSION,
        "candidate_count": len(candidate_rows),
        "pose_count": len(pose_rows),
        "candidate_pose_count_distribution": dict(sorted(pose_counts.items())),
        "pose_consensus_class_counts": dict(sorted(Counter(base.clean(row["consensus_class"]) for row in pose_rows).items())),
        "contact_pose_success_count": sum(base.clean(row["contact_extraction_status"]) == "ok" for row in pose_rows),
        "contact_pose_failure_count": sum(base.clean(row["contact_extraction_status"]) != "ok" for row in pose_rows),
        "complete_candidate_count": sum(base.clean(row["teacher_completeness"]) == "COMPLETE" for row in candidate_rows),
        "parent_framework_cluster_count": len({row["parent_framework_cluster"] for row in selection}),
        "formal_split_counts": dict(sorted(Counter(row["formal_split"] for row in selection).items())),
        "target_patch_counts": dict(sorted(Counter(row["target_patch_id"] for row in selection).items())),
        "selection_layer_counts": dict(sorted(Counter(row["teacher_selection_layer"] for row in selection).items())),
        "candidate_id_set_consistency": id_consistent,
        "candidate_id_counts": {name: len(values) for name, values in id_sets.items()},
        "unique_candidate_sequence_count": len({row["vhh_sequence"] for row in selection}),
        "exact_known_positive_sequence_overlap_count": len(exact_overlaps),
        "exact_known_positive_sequence_overlaps": exact_overlaps,
        "output_sha256": {
            str(candidate_path): sha256_file(candidate_path),
            str(pose_path): sha256_file(pose_path),
            str(contact_path): sha256_file(contact_path),
            str(config_path): sha256_file(config_path),
            str(args.manifest_out): sha256_file(args.manifest_out),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if len(candidate_rows) != EXPECTED_CANDIDATES or any(count < args.min_poses or count > args.top_k for count in pose_counts):
        audit["status"] = "FAIL_UNEXPECTED_TEACHER_COUNTS"
    elif audit["complete_candidate_count"] != EXPECTED_CANDIDATES:
        audit["status"] = "FAIL_INCOMPLETE_CANDIDATE_SUMMARIES"
    elif not args.skip_contacts and audit["contact_pose_failure_count"]:
        audit["status"] = "FAIL_CONTACT_EXTRACTION_INCOMPLETE"
    elif not id_consistent:
        audit["status"] = "FAIL_CANDIDATE_ID_SET_MISMATCH"
    elif exact_overlaps:
        audit["status"] = "FAIL_EXACT_KNOWN_POSITIVE_SEQUENCE_LEAKAGE"
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(args.audit_md, audit)
    if audit["status"] != "PASS_FORMAL_TEACHER500_READY":
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--positive-root", type=Path, default=base.DEFAULT_POSITIVE_ROOT)
    parser.add_argument("--prepared-out", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT_JSON)
    parser.add_argument("--audit-md", type=Path, default=DEFAULT_AUDIT_MD)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--min-poses", type=int, default=4)
    parser.add_argument("--min-supporting-clusters", type=int, default=2)
    parser.add_argument("--skip-contacts", action="store_true")
    args = parser.parse_args(argv)
    if args.top_k <= 0 or args.min_poses <= 0 or args.min_poses > args.top_k or args.min_supporting_clusters <= 0:
        parser.error("Require 0 < --min-poses <= --top-k and positive --min-supporting-clusters")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    print(json.dumps(run(parse_args(argv)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
