#!/usr/bin/env python3
"""Aggregate the prospective 96-candidate PVRIG docking-teacher pilot."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import build_pvrig_teacher_v1 as base

EXP_DIR = SCRIPT_DIR.parent
DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_pilot96/pvrig_teacher_pilot96_manifest.tsv"
DEFAULT_WORK_ROOT = EXP_DIR / "runs/pvrig_teacher_v1_20260712/pilot96_postprocessed"
DEFAULT_PREPARED = EXP_DIR / "prepared/pvrig_teacher_pilot96"
DEFAULT_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_pilot96/pvrig_teacher_pilot96_teacher_manifest.tsv"
DEFAULT_AUDIT_JSON = EXP_DIR / "audits/pvrig_teacher_pilot96_audit.json"
DEFAULT_AUDIT_MD = EXP_DIR / "audits/PVRIG_TEACHER_PILOT96_AUDIT.md"

SCHEMA_VERSION = "pvrig_teacher_pilot96_geometry_v1"
CLAIM_BOUNDARY = "prospective_docking_geometry_surrogate_not_binding_or_blocker_proof"
CALIBRATION_ROLE = "prospective_generated_docking_teacher_pilot"
LEAKAGE_STATUS = "PROSPECTIVE_GENERATED_NOT_KNOWN_POSITIVE_OR_DERIVATIVE"

METADATA_FIELDS = [
    "selection_rank",
    "source_candidate_id",
    "hotspot_set",
    "hotspots_uniprot",
    "framework_id",
    "parent_framework_cluster",
    "backbone_index",
    "mpnn_index",
    "rfd_mindist",
    "rfd_hotspot_distance_bin",
    "fast_score",
    "fast_rank",
    "fast_recommendation",
    "selection_stratum",
    "teacher_split",
    "formal_model_eligible",
]
POSE_FIELDS = base.POSE_FIELDS + METADATA_FIELDS
CANDIDATE_FIELDS = base.CANDIDATE_FIELDS + METADATA_FIELDS


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metadata(row: dict[str, str]) -> dict[str, str]:
    return {field: row.get(field, "") for field in METADATA_FIELDS}


def known_positive_sequences(positive_root: Path) -> dict[str, str]:
    sequences: dict[str, str] = {}
    for row in base.read_csv(positive_root / "batch_manifest.csv"):
        candidate_id = base.clean(row["calibration_name"])
        fasta = base.find_one(positive_root / candidate_id / "inputs", "*.fasta")
        sequences[candidate_id] = base.read_single_fasta(fasta)
    return sequences


def make_case(row: dict[str, str], work_root: Path) -> base.Case:
    candidate_id = row["candidate_id"]
    workdir = work_root / candidate_id
    consensus = workdir / "reports" / f"{candidate_id}_8x6b_9e6y_consensus.csv"
    if not consensus.exists():
        raise FileNotFoundError(consensus)
    return base.Case(
        candidate_id=candidate_id,
        candidate_name=candidate_id,
        family=f"RFantibody_patch_{row['hotspot_set']}",
        sequence=row["sequence"],
        calibration_role=CALIBRATION_ROLE,
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


def write_tsv(path: Path, rows: Sequence[dict[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def teacher_manifest_row(row: dict[str, str], case: base.Case) -> dict[str, str]:
    result = dict(row)
    result.update(
        {
            "schema_version": SCHEMA_VERSION,
            "selection_claim_boundary": row.get("claim_boundary", ""),
            "teacher_dataset_role": CALIBRATION_ROLE,
            "calibration_only": "false",
            "submission_eligible": "false_pending_full_qc_single_framework_pilot",
            "leakage_status": LEAKAGE_STATUS,
            "workdir": str(case.workdir),
            "consensus_csv": str(case.consensus_csv),
            "claim_boundary": CLAIM_BOUNDARY,
        }
    )
    return result


def write_audit_markdown(path: Path, audit: dict[str, object]) -> None:
    lines = [
        "# PVRIG Teacher Pilot96 Audit",
        "",
        f"- Status: `{audit['status']}`",
        f"- Candidates: `{audit['candidate_count']}/96`.",
        f"- Pose rows: `{audit['pose_count']}` (maximum `{audit['maximum_pose_count']}`).",
        f"- Contact extraction: `{audit['contact_pose_success_count']}/{audit['pose_count']}`.",
        f"- Complete candidate summaries: `{audit['complete_candidate_count']}/96`.",
        f"- Candidate ID set consistency: `{audit['candidate_id_set_consistency']}`.",
        f"- Exact known-positive sequence overlap: `{audit['exact_known_positive_sequence_overlap_count']}`.",
        f"- Parent framework clusters: `{audit['parent_framework_cluster_count']}`.",
        f"- Claim boundary: `{CLAIM_BOUNDARY}`.",
        "",
        "## Interpretation",
        "",
        "- This is a prospective docking-teacher pilot, not a known-positive calibration replay.",
        "- All candidates share one parent framework, so the set can validate data flow and model plumbing only.",
        "- It cannot support a formal unseen-parent V3-P claim or prove binding/blocking activity.",
        "- 9E6Y is a rescoring baseline for the same 8X6B-generated poses, not an independent docking run.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, object]:
    selection = read_tsv(args.selection)
    if len(selection) != 96 or len({row["candidate_id"] for row in selection}) != 96:
        raise ValueError("The selection manifest must contain 96 unique candidates")

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
        update_common(contact, row)
        summary = base.candidate_summary(case, case_poses, contact, args.min_supporting_clusters)
        update_common(summary, row)
        summary.update(
            {
                "calibration_only": "false",
                "submission_eligible": "false_pending_full_qc_single_framework_pilot",
                "provisional_rule_status": "PROVISIONAL_SINGLE_FRAMEWORK_PILOT_NOT_FROZEN_TRAINING_LABEL",
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
    manifest_fields = list(manifest_rows[0])
    write_tsv(args.manifest_out, manifest_rows, manifest_fields)

    config = {
        "schema_version": SCHEMA_VERSION,
        "top_k": args.top_k,
        "pose_generation_receptor": "8X6B",
        "independent_9e6y_docking": False,
        "min_supporting_clusters_for_provisional_stable_tier": args.min_supporting_clusters,
        "consensus_relevance": base.CONSENSUS_RELEVANCE,
        "relevance_weights": base.RELEVANCE_WEIGHTS,
        "single_framework_pilot": True,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    maximum_pose_count = len(selection) * args.top_k
    minimum_pose_count = len(selection) * args.min_poses
    pose_count_distribution = Counter(int(row["pose_count"]) for row in candidate_rows)
    pose_classes = Counter(base.clean(row["consensus_class"]) for row in pose_rows)
    parent_clusters = {row["parent_framework_cluster"] for row in selection}
    selection_ids = {row["candidate_id"] for row in selection}
    candidate_ids = {base.clean(row["candidate_id"]) for row in candidate_rows}
    pose_ids = {base.clean(row["candidate_id"]) for row in pose_rows}
    contact_ids = {base.clean(row["candidate_id"]) for row in contact_rows}
    manifest_ids = {row["candidate_id"] for row in manifest_rows}
    id_sets = {
        "selection": selection_ids,
        "candidate_summary": candidate_ids,
        "pose_summary": pose_ids,
        "contact_frequency": contact_ids,
        "teacher_manifest": manifest_ids,
    }
    id_set_consistency = all(values == selection_ids for values in id_sets.values())
    positives = known_positive_sequences(args.positive_root)
    positive_sequence_to_ids: dict[str, list[str]] = {}
    for positive_id, sequence in positives.items():
        positive_sequence_to_ids.setdefault(sequence, []).append(positive_id)
    exact_positive_overlaps = {
        row["candidate_id"]: sorted(positive_sequence_to_ids[row["sequence"]])
        for row in selection
        if row["sequence"] in positive_sequence_to_ids
    }
    audit: dict[str, object] = {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
        "candidate_count": len(candidate_rows),
        "pose_count": len(pose_rows),
        "maximum_pose_count": maximum_pose_count,
        "minimum_required_pose_count": minimum_pose_count,
        "candidate_pose_count_distribution": dict(sorted(pose_count_distribution.items())),
        "pose_consensus_class_counts": dict(sorted(pose_classes.items())),
        "contact_pose_success_count": sum(base.clean(row["contact_extraction_status"]) == "ok" for row in pose_rows),
        "contact_pose_failure_count": sum(base.clean(row["contact_extraction_status"]) != "ok" for row in pose_rows),
        "complete_candidate_count": sum(base.clean(row["teacher_completeness"]) == "COMPLETE" for row in candidate_rows),
        "parent_framework_cluster_count": len(parent_clusters),
        "parent_framework_clusters": sorted(parent_clusters),
        "hotspot_counts": dict(sorted(Counter(row["hotspot_set"] for row in selection).items())),
        "formal_model_eligible_counts": dict(sorted(Counter(row["formal_model_eligible"] for row in selection).items())),
        "candidate_id_counts": {name: len(values) for name, values in id_sets.items()},
        "candidate_id_set_consistency": id_set_consistency,
        "unique_candidate_sequence_count": len({row["sequence"] for row in selection}),
        "known_positive_sequence_count": len(positives),
        "known_positive_unique_sequence_count": len(set(positives.values())),
        "exact_known_positive_sequence_overlap_count": len(exact_positive_overlaps),
        "exact_known_positive_sequence_overlaps": exact_positive_overlaps,
        "leakage_check_status": (
            "PASS_NO_EXACT_KNOWN_POSITIVE_SEQUENCE_OVERLAP"
            if not exact_positive_overlaps
            else "FAIL_EXACT_KNOWN_POSITIVE_SEQUENCE_OVERLAP"
        ),
        "input_sha256": {
            str(args.selection): sha256_file(args.selection),
            str(args.positive_root / "batch_manifest.csv"): sha256_file(args.positive_root / "batch_manifest.csv"),
        },
        "output_sha256": {
            str(candidate_path): sha256_file(candidate_path),
            str(pose_path): sha256_file(pose_path),
            str(contact_path): sha256_file(contact_path),
            str(config_path): sha256_file(config_path),
            str(args.manifest_out): sha256_file(args.manifest_out),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if len(candidate_rows) != 96 or any(count < args.min_poses or count > args.top_k for count in pose_count_distribution):
        audit["status"] = "FAIL_UNEXPECTED_PILOT_COUNTS"
    if sum(base.clean(row["teacher_completeness"]) == "COMPLETE" for row in candidate_rows) != 96:
        audit["status"] = "FAIL_INCOMPLETE_CANDIDATE_SUMMARIES"
    if not args.skip_contacts and audit["contact_pose_failure_count"]:
        audit["status"] = "FAIL_CONTACT_EXTRACTION_INCOMPLETE"
    if not id_set_consistency:
        audit["status"] = "FAIL_CANDIDATE_ID_SET_MISMATCH"
    if exact_positive_overlaps:
        audit["status"] = "FAIL_EXACT_KNOWN_POSITIVE_SEQUENCE_LEAKAGE"

    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_audit_markdown(args.audit_md, audit)
    if audit["status"] != "PASS":
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


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
