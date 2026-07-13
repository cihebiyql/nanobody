#!/usr/bin/env python3
"""Seal parent-cluster-safe Teacher500 inputs for formal V3-P training."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_CANDIDATES = EXP_DIR / "prepared/pvrig_teacher_formal_v1/candidate_summary.csv"
DEFAULT_CONTACTS = EXP_DIR / "prepared/pvrig_teacher_formal_v1/pose_contact_frequency.jsonl"
DEFAULT_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_teacher_manifest_v1.csv"
DEFAULT_TEACHER_AUDIT = EXP_DIR / "audits/pvrig_formal_teacher500_audit.json"
DEFAULT_OUTPUT = EXP_DIR / "prepared/phase2_v3_p1_formal"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p1_formal_data_audit.json"
SCHEMA_VERSION = "phase2_v3_p1_formal_data_v1"
CLAIM_BOUNDARY = "docking_geometry_surrogate_not_binding_or_experimental_blocking_truth"

KEY_FIELDS = ["candidate_id", "sequence_sha256", "parent_framework_cluster"]
LABEL_FIELDS = [
    "pose_count",
    "valid_baseline_pair_count",
    "topk_aa_fraction",
    "topk_single_a_fraction",
    "topk_plausible_b_fraction",
    "topk_c_fraction",
    "topk_e_fraction",
    "topk_a_or_b_fraction",
    "blocker_supporting_cluster_count",
    "aa_supporting_cluster_count",
    "pose_cluster_count",
    "pose_cluster_entropy",
    "median_hotspot_overlap_8x6b",
    "median_hotspot_overlap_9e6y",
    "median_total_occlusion_8x6b",
    "median_total_occlusion_9e6y",
    "median_cdr3_occlusion_8x6b",
    "median_cdr3_occlusion_9e6y",
    "median_cdr3_fraction_8x6b",
    "median_cdr3_fraction_9e6y",
    "teacher_relevance_mean",
    "teacher_relevance_median",
    "teacher_relevance_max",
    "best_pose_vs_median_gap",
    "best_evidence_tier",
    "provisional_stable_geometry_tier",
    "valid_contact_pose_count",
    "failed_contact_pose_count",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("utf-8")).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    atomic_text(path, "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))


def index_unique(rows: Sequence[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id or candidate_id in indexed:
            raise ValueError(f"{label} has missing or duplicate candidate_id: {candidate_id!r}")
        indexed[candidate_id] = dict(row)
    return indexed


def split_overlap(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    clusters = {
        split: {str(row["parent_framework_cluster"]) for row in rows if row["formal_split"] == split}
        for split in ("train", "dev", "test")
    }
    return {
        "train_dev": len(clusters["train"] & clusters["dev"]),
        "train_test": len(clusters["train"] & clusters["test"]),
        "dev_test": len(clusters["dev"] & clusters["test"]),
    }


def numeric_stats(rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> dict[str, dict[str, float]]:
    stats: dict[str, dict[str, float]] = {}
    for field in fields:
        values: list[float] = []
        for row in rows:
            try:
                values.append(float(row[field]))
            except (KeyError, TypeError, ValueError):
                continue
        if values:
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            stats[field] = {"mean": mean, "std": variance**0.5, "minimum": min(values), "maximum": max(values)}
    return stats


def prepare(
    candidates_path: Path,
    contacts_path: Path,
    manifest_path: Path,
    output_dir: Path,
    audit_path: Path,
    upstream_audit_path: Path,
    expected_candidates: int = 500,
    expected_splits: dict[str, int] | None = None,
) -> dict[str, Any]:
    upstream = json.loads(upstream_audit_path.read_text(encoding="utf-8"))
    if upstream.get("status") != "PASS_FORMAL_TEACHER500_READY":
        raise ValueError(f"Formal Teacher500 upstream audit is not PASS: {upstream.get('status')}")
    upstream_hashes = upstream.get("output_sha256")
    if not isinstance(upstream_hashes, dict):
        raise ValueError("Formal Teacher500 upstream audit lacks output_sha256")
    for path in (candidates_path, contacts_path, manifest_path):
        resolved = path.resolve()
        matches = [value for key, value in upstream_hashes.items() if Path(key).resolve() == resolved]
        if len(matches) != 1 or matches[0] != sha256_file(path):
            raise ValueError(f"Formal Teacher500 upstream hash mismatch for {path}")
    candidates = index_unique(read_csv(candidates_path), "candidate_summary")
    contacts = index_unique(read_jsonl(contacts_path), "contact_frequency")
    manifest = index_unique(read_csv(manifest_path), "teacher_manifest")
    id_sets = [set(candidates), set(contacts), set(manifest)]
    if any(values != id_sets[0] for values in id_sets[1:]) or len(candidates) != expected_candidates:
        raise ValueError(
            f"Teacher ID closure failed: candidates={len(candidates)} contacts={len(contacts)} "
            f"manifest={len(manifest)} expected={expected_candidates}"
        )

    merged: list[dict[str, Any]] = []
    enriched_contacts: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates):
        candidate = candidates[candidate_id]
        meta = manifest[candidate_id]
        sequence = str(candidate.get("sequence") or meta.get("vhh_sequence") or "").strip()
        sequence_sha = str(candidate.get("sequence_sha256") or meta.get("sequence_sha256") or "").strip()
        if not sequence or sequence_hash(sequence) != sequence_sha:
            raise ValueError(f"Sequence hash mismatch for {candidate_id}")
        contact_sequence = str(contacts[candidate_id].get("sequence", "")).strip()
        contact_sha = str(contacts[candidate_id].get("sequence_sha256", "")).strip()
        if contact_sequence != sequence or contact_sha != sequence_sha or sequence_hash(contact_sequence) != contact_sha:
            raise ValueError(f"Contact sequence/hash mismatch for {candidate_id}")
        for candidate_field, manifest_field, label in (
            ("sequence_sha256", "sequence_sha256", "Sequence hash"),
            ("formal_split", "formal_split", "Split"),
            ("parent_framework_cluster", "parent_framework_cluster", "Parent-cluster"),
        ):
            candidate_value = str(candidate.get(candidate_field, "")).strip()
            manifest_value = str(meta.get(manifest_field, "")).strip()
            if candidate_value and manifest_value and candidate_value != manifest_value:
                raise ValueError(f"{label} mismatch for {candidate_id}: {candidate_value!r} != {manifest_value!r}")
        split = str(candidate.get("formal_split") or meta.get("formal_split") or "").strip()
        cluster = str(candidate.get("parent_framework_cluster") or meta.get("parent_framework_cluster") or "").strip()
        if split not in {"train", "dev", "test"} or not cluster:
            raise ValueError(f"Invalid split/cluster for {candidate_id}: {split!r}/{cluster!r}")
        for field in LABEL_FIELDS:
            if field not in candidate or str(candidate[field]).strip() == "":
                raise ValueError(f"Missing formal label {field} for {candidate_id}")
        if str(candidate.get("teacher_completeness", "")).strip() != "COMPLETE":
            raise ValueError(f"Incomplete teacher summary for {candidate_id}")
        if int(float(candidate["failed_contact_pose_count"])) != 0:
            raise ValueError(f"Teacher contact extraction failure for {candidate_id}")
        if int(float(candidate["valid_baseline_pair_count"])) != int(float(candidate["pose_count"])):
            raise ValueError(f"Incomplete dual-baseline poses for {candidate_id}")
        if int(float(candidate["valid_contact_pose_count"])) != int(float(candidate["pose_count"])):
            raise ValueError(f"Incomplete contact poses for {candidate_id}")
        row = {**meta, **candidate, "sequence": sequence, "sequence_sha256": sequence_sha, "formal_split": split,
               "parent_framework_cluster": cluster, "geometry_tier_index": str(5 - int(str(candidate["provisional_stable_geometry_tier"])[1:])),
               "claim_boundary": CLAIM_BOUNDARY}
        merged.append(row)
        enriched_contacts.append({**contacts[candidate_id], **{field: row[field] for field in KEY_FIELDS}, "formal_split": split,
                                  "sealed_status": "SEALED_FORMAL_TEST_LABEL" if split == "test" else "OPEN_DEVELOPMENT_LABEL"})

    counts = Counter(str(row["formal_split"]) for row in merged)
    expected_splits = expected_splits or {"train": 350, "dev": 75, "test": 75}
    if dict(counts) != expected_splits:
        raise ValueError(f"Unexpected split counts: {dict(counts)} != {expected_splits}")
    overlap = split_overlap(merged)
    if any(overlap.values()):
        raise ValueError(f"Parent-cluster leakage across splits: {overlap}")

    train_dev = [row for row in merged if row["formal_split"] in {"train", "dev"}]
    formal = [row for row in merged if row["formal_split"] == "test"]
    label_fields = [*KEY_FIELDS, "formal_split", "geometry_tier_index", *LABEL_FIELDS, "claim_boundary", "sealed_status"]
    sealed_labels = [{**row, "sealed_status": "SEALED_FORMAL_TEST_LABEL"} for row in formal]
    blinded_fields = [field for field in merged[0] if field not in set(LABEL_FIELDS) | {"geometry_tier_index"}]
    blinded = [{field: row.get(field, "") for field in blinded_fields} for row in formal]
    if any(field in blinded_fields for field in LABEL_FIELDS + ["geometry_tier_index"]):
        raise AssertionError("Blinded formal manifest contains label columns")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "train_dev": output_dir / "pvrig_teacher_train_dev_v1.csv",
        "formal_blinded": output_dir / "pvrig_teacher_formal_blinded_v1.csv",
        "formal_labels_sealed": output_dir / "pvrig_teacher_formal_labels_sealed_v1.csv",
        "contact_train_dev": output_dir / "pvrig_contact_train_dev_v1.jsonl",
        "contact_formal_labels_sealed": output_dir / "pvrig_contact_formal_labels_sealed_v1.jsonl",
        "train_normalization": output_dir / "train_only_normalization_v1.json",
    }
    train_dev_fields = list(merged[0])
    if "geometry_tier_index" not in train_dev_fields:
        train_dev_fields.append("geometry_tier_index")
    write_csv(outputs["train_dev"], train_dev, train_dev_fields)
    write_csv(outputs["formal_blinded"], blinded, blinded_fields)
    write_csv(outputs["formal_labels_sealed"], sealed_labels, label_fields)
    write_jsonl(outputs["contact_train_dev"], (row for row in enriched_contacts if row["formal_split"] in {"train", "dev"}))
    write_jsonl(outputs["contact_formal_labels_sealed"], (row for row in enriched_contacts if row["formal_split"] == "test"))
    normalization = {
        "schema_version": SCHEMA_VERSION,
        "fit_split": "train_only",
        "row_count": counts["train"],
        "numeric_label_stats": numeric_stats([row for row in merged if row["formal_split"] == "train"], LABEL_FIELDS),
    }
    atomic_text(outputs["train_normalization"], json.dumps(normalization, indent=2, sort_keys=True) + "\n")

    audit: dict[str, Any] = {
        "status": "PASS_PHASE2_V3_P1_FORMAL_DATA_SEALED",
        "schema_version": SCHEMA_VERSION,
        "row_counts": dict(sorted(counts.items())),
        "unique_parent_clusters": len({row["parent_framework_cluster"] for row in merged}),
        "parent_cluster_cross_split_overlap": overlap,
        "candidate_id_closure": True,
        "sequence_hash_closure": True,
        "formal_blinded_label_columns": [],
        "input_sha256": {str(path): sha256_file(path) for path in (candidates_path, contacts_path, manifest_path)},
        "upstream_teacher_audit": str(upstream_audit_path),
        "upstream_teacher_audit_sha256": sha256_file(upstream_audit_path),
        "output_paths": {name: str(path) for name, path in outputs.items()},
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit["output_sha256"] = {name: sha256_file(path) for name, path in outputs.items()}
    atomic_text(audit_path, json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--contacts", type=Path, default=DEFAULT_CONTACTS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--upstream-teacher-audit", type=Path, default=DEFAULT_TEACHER_AUDIT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--expected-candidates", type=int, default=500)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    print(json.dumps(prepare(args.candidates, args.contacts, args.manifest, args.output_dir, args.audit,
                             args.upstream_teacher_audit,
                             args.expected_candidates), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
