#!/usr/bin/env python3
"""Build an auditable optional-pose manifest for Phase 3 PVRIG candidates.

The manifest is intentionally pose-optional: every candidate receives at least
one explicit row even when no structure has been generated or supplied. This
keeps downstream geometry extraction auditable without docking or fabricating
pose-derived features.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CANDIDATES = ROOT / "experiments/phase2_5080_v1/predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv"
DEFAULT_CDR_MANIFEST = ROOT / "experiments/phase2_5080_v1/data_splits/vhh_cdr_type_masks_v2_3.csv"
DEFAULT_INDEX = ROOT / "model_data/index_v0_samples.csv"
DEFAULT_CANDIDATE_ANNOTATIONS = [
    ROOT / "model_data/mvp_candidates_v0.csv",
    ROOT / "reports/mvp_pvrig_top_candidates_v0.csv",
]
DEFAULT_OUTPUT = ROOT / "experiments/phase2_5080_v1/data_splits/p3_optional_pose_manifest_v1.csv"
DEFAULT_TARGET_BASELINE = "PVRIG_Q6DKI7_full_uniprot_target_domain_mapping_v1"
FIELDNAMES = [
    "candidate_id",
    "pose_id",
    "target_baseline",
    "candidate_csv_path",
    "candidate_source_row",
    "pose_path",
    "pose_relpath",
    "vhh_chain",
    "target_chain",
    "other_chains",
    "target_residue_numbering",
    "pose_source",
    "pose_status",
    "qc_status",
    "qc_notes",
    "calibration_role",
    "leakage_role",
    "leakage_label",
    "vhh_seq",
    "cdr3_seq",
    "cdr3_source",
    "candidate_payload_json",
]


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."}:
        return ""
    return text


def relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def stable_pose_id(candidate_id: str, target_baseline: str, pose_path: str, pose_source: str) -> str:
    key = "\t".join([candidate_id, target_baseline, pose_path or "NO_POSE", pose_source or "unspecified"])
    return "p3pose_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def candidate_id_aliases(candidate_id: str) -> list[str]:
    aliases = [candidate_id]
    parts = candidate_id.split("_")
    if len(parts) == 3 and parts[0] == "zym" and parts[2].isdigit():
        aliases.append(f"zympara_{parts[1]}_{int(parts[2]):06d}")
    return aliases


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_index_sequences(index_path: Path) -> dict[str, dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(index_path):
        sample_id = clean(row.get("sample_id"))
        if sample_id:
            by_id[sample_id] = row
    return by_id


def load_candidate_annotations(paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for path in paths:
        for row in read_csv_rows(path):
            candidate_id = clean(row.get("candidate_id"))
            if candidate_id and candidate_id not in by_id:
                by_id[candidate_id] = row
    return by_id


def load_cdr_by_sequence(cdr_path: Path) -> dict[str, dict[str, str]]:
    by_seq: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(cdr_path):
        seq = clean(row.get("vhh_seq"))
        if seq:
            by_seq[seq] = row
    return by_seq


def read_pose_index(path: Path | None, root: Path) -> dict[str, list[dict[str, str]]]:
    by_candidate: dict[str, list[dict[str, str]]] = {}
    if path is None or not path.exists():
        return by_candidate
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            candidate_id = clean(row.get("candidate_id"))
            if not candidate_id:
                continue
            pose_path = clean(row.get("pose_path"))
            if pose_path:
                p = Path(pose_path)
                if not p.is_absolute():
                    p = (path.parent / p).resolve()
                row["pose_path"] = str(p)
                row["pose_relpath"] = clean(row.get("pose_relpath")) or relpath(p, root)
            by_candidate.setdefault(candidate_id, []).append(row)
    return by_candidate


def discover_pose_files(pose_root: Path | None, root: Path) -> dict[str, list[dict[str, str]]]:
    by_candidate: dict[str, list[dict[str, str]]] = {}
    if pose_root is None or not pose_root.exists():
        return by_candidate
    for path in sorted(pose_root.rglob("*.pdb")):
        stem = path.stem
        # Conservative discovery: candidate id must be a prefix before optional separators.
        candidate_id = stem.split("__", 1)[0].split(".pose", 1)[0]
        if not candidate_id:
            continue
        by_candidate.setdefault(candidate_id, []).append(
            {
                "candidate_id": candidate_id,
                "pose_path": str(path.resolve()),
                "pose_relpath": relpath(path, root),
                "pose_source": "pose_root_scan",
                "pose_status": "pose_supplied",
                "qc_status": "unchecked",
                "qc_notes": "discovered_from_pose_root_no_generation_performed",
            }
        )
    return by_candidate


def resolve_candidate_sequence(
    candidate_id: str,
    candidate_row: dict[str, str],
    annotation_by_id: dict[str, dict[str, str]],
    index_by_id: dict[str, dict[str, str]],
    cdr_by_sequence: dict[str, dict[str, str]],
) -> tuple[str, str, str]:
    seq = clean(candidate_row.get("vhh_seq"))
    cdr3 = clean(candidate_row.get("cdr3_seq")) or clean(candidate_row.get("cdr3"))
    source = "candidate_csv"
    ann_row = annotation_by_id.get(candidate_id)
    if ann_row:
        seq = seq or clean(ann_row.get("vhh_seq"))
        cdr3 = cdr3 or clean(ann_row.get("cdr3_seq")) or clean(ann_row.get("cdr3"))
        source = "candidate_annotation_csv"
    for alias in candidate_id_aliases(candidate_id):
        idx_row = index_by_id.get(alias)
        if idx_row:
            seq = seq or clean(idx_row.get("vhh_seq")) or clean(idx_row.get("antibody_heavy_seq"))
            cdr3 = cdr3 or clean(idx_row.get("cdr3_seq")) or clean(idx_row.get("cdr3"))
            source = f"index:{alias}"
            break
    if seq and not cdr3:
        cdr_row = cdr_by_sequence.get(seq)
        if cdr_row:
            cdr3 = clean(cdr_row.get("cdr3_seq")) or clean(cdr_row.get("cdr3"))
            source = f"{source};cdr_manifest"
    return seq, cdr3, source if cdr3 else ""


def merge_pose_sources(*sources: dict[str, list[dict[str, str]]]) -> dict[str, list[dict[str, str]]]:
    merged: dict[str, list[dict[str, str]]] = {}
    for source in sources:
        for candidate_id, rows in source.items():
            merged.setdefault(candidate_id, []).extend(rows)
    return merged


def build_manifest(
    candidate_csv: Path,
    output: Path,
    pose_index_csv: Path | None = None,
    pose_root: Path | None = None,
    cdr_manifest: Path = DEFAULT_CDR_MANIFEST,
    index_csv: Path = DEFAULT_INDEX,
    candidate_annotation_csvs: Iterable[Path] = DEFAULT_CANDIDATE_ANNOTATIONS,
    target_baseline: str = DEFAULT_TARGET_BASELINE,
    default_vhh_chain: str = "A",
    default_target_chain: str = "T",
    calibration_role: str = "candidate_screening_optional_pose",
    missing_pose_status: str = "no_pose_supplied",
    root: Path = ROOT,
) -> dict[str, int]:
    candidates = read_csv_rows(candidate_csv)
    if not candidates:
        raise ValueError(f"No candidate rows found in {candidate_csv}")
    annotation_by_id = load_candidate_annotations(candidate_annotation_csvs)
    index_by_id = load_index_sequences(index_csv)
    cdr_by_sequence = load_cdr_by_sequence(cdr_manifest)
    poses_by_candidate = merge_pose_sources(read_pose_index(pose_index_csv, root), discover_pose_files(pose_root, root))

    rows: list[dict[str, str]] = []
    for source_row, candidate in enumerate(candidates):
        candidate_id = clean(candidate.get("candidate_id")) or f"candidate_row_{source_row:06d}"
        vhh_seq, cdr3_seq, cdr3_source = resolve_candidate_sequence(candidate_id, candidate, annotation_by_id, index_by_id, cdr_by_sequence)
        leakage_label = clean(candidate.get("leakage_label"))
        leakage_role = "candidate_no_known_positive_leakage" if leakage_label == "NO_KNOWN_POSITIVE_LEAKAGE" else (leakage_label or "not_labeled")
        pose_rows = poses_by_candidate.get(candidate_id) or [
            {
                "candidate_id": candidate_id,
                "pose_path": "",
                "pose_relpath": "",
                "pose_source": "none_supplied",
                "pose_status": missing_pose_status,
                "qc_status": "not_applicable_no_pose",
                "qc_notes": "explicit_optional_pose_placeholder_no_geometry_should_be_fabricated",
            }
        ]
        for pose in pose_rows:
            pose_path = clean(pose.get("pose_path"))
            pose_source = clean(pose.get("pose_source")) or clean(pose.get("source")) or "user_supplied_pose_index"
            row_target_baseline = clean(pose.get("target_baseline")) or target_baseline
            row = {
                "candidate_id": candidate_id,
                "pose_id": clean(pose.get("pose_id")) or stable_pose_id(candidate_id, row_target_baseline, pose_path, pose_source),
                "target_baseline": row_target_baseline,
                "candidate_csv_path": relpath(candidate_csv, root),
                "candidate_source_row": str(source_row),
                "pose_path": pose_path,
                "pose_relpath": clean(pose.get("pose_relpath")) or (relpath(Path(pose_path), root) if pose_path else ""),
                "vhh_chain": clean(pose.get("vhh_chain")) or clean(pose.get("antibody_chain")) or default_vhh_chain,
                "target_chain": clean(pose.get("target_chain")) or clean(pose.get("antigen_chain")) or default_target_chain,
                "other_chains": clean(pose.get("other_chains")),
                "target_residue_numbering": clean(pose.get("target_residue_numbering")) or "auto_full_or_model_uniprot_1based",
                "pose_source": pose_source,
                "pose_status": clean(pose.get("pose_status")) or ("pose_supplied" if pose_path else missing_pose_status),
                "qc_status": clean(pose.get("qc_status")) or "unchecked",
                "qc_notes": clean(pose.get("qc_notes")),
                "calibration_role": clean(pose.get("calibration_role")) or calibration_role,
                "leakage_role": clean(pose.get("leakage_role")) or leakage_role,
                "leakage_label": leakage_label,
                "vhh_seq": vhh_seq,
                "cdr3_seq": cdr3_seq,
                "cdr3_source": cdr3_source,
                "candidate_payload_json": json.dumps(candidate, sort_keys=True, ensure_ascii=True),
            }
            rows.append(row)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "candidates": len(candidates),
        "manifest_rows": len(rows),
        "pose_rows": sum(1 for row in rows if row["pose_path"]),
        "missing_pose_rows": sum(1 for row in rows if not row["pose_path"]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-csv", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pose-index-csv", type=Path)
    parser.add_argument("--pose-root", type=Path)
    parser.add_argument("--cdr-manifest", type=Path, default=DEFAULT_CDR_MANIFEST)
    parser.add_argument("--index-csv", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--candidate-annotation-csv", type=Path, action="append", default=None)
    parser.add_argument("--target-baseline", default=DEFAULT_TARGET_BASELINE)
    parser.add_argument("--default-vhh-chain", default="A")
    parser.add_argument("--default-target-chain", default="T")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_manifest(
        candidate_csv=args.candidate_csv,
        output=args.output,
        pose_index_csv=args.pose_index_csv,
        pose_root=args.pose_root,
        cdr_manifest=args.cdr_manifest,
        index_csv=args.index_csv,
        candidate_annotation_csvs=args.candidate_annotation_csv or DEFAULT_CANDIDATE_ANNOTATIONS,
        target_baseline=args.target_baseline,
        default_vhh_chain=args.default_vhh_chain,
        default_target_chain=args.default_target_chain,
    )
    print(json.dumps({"status": "PASS", "output": str(args.output), **summary}, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
