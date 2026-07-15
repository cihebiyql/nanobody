#!/usr/bin/env python3
"""Freeze the prospective parent-cluster split for the Full-QC 290 panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "phase2_v4_d_fullqc290_split_v1"
FROZEN_AT = "2026-07-15T18:35:10+08:00"
SOURCE_SHA256 = "316a1732f2f123faf12f5a6eb0e4444fe1ce0cb5e34cf3b4f40641867acb5895"
DUAL128_SOURCE_SHA256 = "5e536f7178cb214102aef684c65fc97b4996d3b83de5b6f506ad2f9bf8e66c78"
EXPECTED_ROWS = 290
EXPECTED_SPLIT_COUNTS = {
    "OPEN_TRAIN": 226,
    "OPEN_DEVELOPMENT": 32,
    "PROSPECTIVE_COMPUTATIONAL_TEST": 32,
}
SPLIT_MAP = {
    "train": "OPEN_TRAIN",
    "dev": "OPEN_DEVELOPMENT",
    "test": "PROSPECTIVE_COMPUTATIONAL_TEST",
}
EXPECTED_PARENT_CLUSTER_COUNTS = {
    "OPEN_TRAIN": 20,
    "OPEN_DEVELOPMENT": 3,
    "PROSPECTIVE_COMPUTATIONAL_TEST": 3,
}
EXPECTED_DEVELOPMENT_CLUSTERS = {"C0210", "C0354", "C0448"}
EXPECTED_TEST_CLUSTERS = {"C0299", "C0311", "C0474"}

REQUIRED_FIELDS = {
    "candidate_id",
    "vhh_sequence",
    "sequence_sha256",
    "parent_id",
    "parent_framework_cluster",
    "formal_split",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1_after",
    "cdr2_after",
    "cdr3_after",
    "cdr3_length",
    "full_qc_hard_fail",
}

OUTPUT_FIELDS = [
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_id",
    "parent_framework_cluster",
    "original_formal_split",
    "model_split",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1",
    "cdr2",
    "cdr3",
    "cdr3_length",
    "new_dual_docking_label_policy",
    "claim_boundary",
]

CLAIM_BOUNDARY = (
    "Prospectively split fixed-PVRIG sequence-to-independent-dual-docking panel; "
    "computational geometry only, not binding, affinity, competition, Docking Gold, "
    "or experimental blocking truth."
)


class SplitFreezeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_csv(path: Path) -> list[dict[str, str]]:
    if sha256_file(path) != SOURCE_SHA256:
        raise SplitFreezeError("source_sha256_mismatch")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_FIELDS - fields)
        if missing:
            raise SplitFreezeError(f"source_missing_required_fields:{','.join(missing)}")
        rows = list(reader)
    if len(rows) != EXPECTED_ROWS:
        raise SplitFreezeError(f"expected_{EXPECTED_ROWS}_rows_got_{len(rows)}")
    return rows


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def freeze_rows(source_rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for source in source_rows:
        candidate_id = source["candidate_id"].strip()
        sequence = source["vhh_sequence"].strip().upper()
        expected_sha = hashlib.sha256(sequence.encode("utf-8")).hexdigest()
        if not candidate_id or expected_sha != source["sequence_sha256"]:
            raise SplitFreezeError(f"blank_id_or_sequence_hash_mismatch:{candidate_id}")
        if truthy(source["full_qc_hard_fail"]):
            raise SplitFreezeError(f"full_qc_hard_fail_in_panel:{candidate_id}")
        original_split = source["formal_split"].strip()
        if original_split not in SPLIT_MAP:
            raise SplitFreezeError(f"invalid_original_split:{candidate_id}:{original_split}")
        model_split = SPLIT_MAP[original_split]
        output.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": source["sequence_sha256"],
                "sequence": sequence,
                "parent_id": source["parent_id"],
                "parent_framework_cluster": source["parent_framework_cluster"],
                "original_formal_split": original_split,
                "model_split": model_split,
                "design_method": source["design_method"],
                "design_mode": source["design_mode"],
                "target_patch_id": source["target_patch_id"],
                "cdr1": source["cdr1_after"],
                "cdr2": source["cdr2_after"],
                "cdr3": source["cdr3_after"],
                "cdr3_length": source["cdr3_length"],
                "new_dual_docking_label_policy": (
                    "SEALED_UNTIL_ONE_SHOT_COMPUTATIONAL_EVALUATION"
                    if model_split == "PROSPECTIVE_COMPUTATIONAL_TEST"
                    else "OPEN_AFTER_PRODUCTION_EVALUATOR_PASS"
                ),
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    output.sort(key=lambda row: row["candidate_id"])
    validate_rows(output)
    return output


def distribution(rows: Iterable[dict[str, str]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(row[field] for row in rows).items()))


def validate_rows(rows: list[dict[str, str]]) -> None:
    if len({row["candidate_id"] for row in rows}) != EXPECTED_ROWS:
        raise SplitFreezeError("blank_or_duplicate_candidate_id")
    if len({row["sequence_sha256"] for row in rows}) != EXPECTED_ROWS:
        raise SplitFreezeError("blank_or_duplicate_sequence_sha256")
    if distribution(rows, "model_split") != EXPECTED_SPLIT_COUNTS:
        raise SplitFreezeError("split_count_mismatch")

    clusters_by_split = {
        split: {
            row["parent_framework_cluster"]
            for row in rows
            if row["model_split"] == split
        }
        for split in EXPECTED_SPLIT_COUNTS
    }
    for split, expected_count in EXPECTED_PARENT_CLUSTER_COUNTS.items():
        if len(clusters_by_split[split]) != expected_count:
            raise SplitFreezeError(f"parent_cluster_count_mismatch:{split}")
    split_names = list(clusters_by_split)
    for index, left in enumerate(split_names):
        for right in split_names[index + 1 :]:
            if clusters_by_split[left] & clusters_by_split[right]:
                raise SplitFreezeError(f"parent_cluster_overlap:{left}:{right}")
    if clusters_by_split["OPEN_DEVELOPMENT"] != EXPECTED_DEVELOPMENT_CLUSTERS:
        raise SplitFreezeError("development_parent_cluster_set_mismatch")
    if clusters_by_split["PROSPECTIVE_COMPUTATIONAL_TEST"] != EXPECTED_TEST_CLUSTERS:
        raise SplitFreezeError("test_parent_cluster_set_mismatch")


def load_dual128_hashes(path: Path) -> tuple[set[str], set[str]]:
    if sha256_file(path) != DUAL128_SOURCE_SHA256:
        raise SplitFreezeError("dual128_source_sha256_mismatch")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return (
        {row["candidate_id"] for row in rows},
        {row["sequence_sha256"] for row in rows},
    )


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def build_audit(
    source_path: Path,
    dual128_path: Path,
    manifest_path: Path,
    rows: list[dict[str, str]],
) -> dict[str, object]:
    dual_ids, dual_hashes = load_dual128_hashes(dual128_path)
    candidate_ids = {row["candidate_id"] for row in rows}
    sequence_hashes = {row["sequence_sha256"] for row in rows}
    cluster_counts = {
        split: len(
            {
                row["parent_framework_cluster"]
                for row in rows
                if row["model_split"] == split
            }
        )
        for split in EXPECTED_SPLIT_COUNTS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_PROSPECTIVE_COMPUTATIONAL_SPLIT",
        "frozen_at": FROZEN_AT,
        "source": {
            "path": str(source_path),
            "sha256": sha256_file(source_path),
            "candidate_count": len(rows),
            "selection_basis": "Full-QC hard-pass with complete AbNatiV before independent dual docking",
        },
        "split": {
            "counts": distribution(rows, "model_split"),
            "group_unit": "parent_framework_cluster",
            "parent_cluster_counts": cluster_counts,
            "development_parent_clusters": sorted(EXPECTED_DEVELOPMENT_CLUSTERS),
            "test_parent_clusters": sorted(EXPECTED_TEST_CLUSTERS),
            "source_assignment": "preexisting Teacher500 formal_split copied without dual-docking labels",
        },
        "integrity_gates": {
            "source_sha256_matches": True,
            "candidate_count_is_290": len(rows) == EXPECTED_ROWS,
            "candidate_ids_unique": len(candidate_ids) == EXPECTED_ROWS,
            "sequences_unique": len(sequence_hashes) == EXPECTED_ROWS,
            "parent_cluster_overlap_across_split": 0,
            "dual128_candidate_id_overlap": len(candidate_ids & dual_ids),
            "dual128_sequence_overlap": len(sequence_hashes & dual_hashes),
            "new_independent_dual_docking_result_fields_used": False,
        },
        "manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=(
            root
            / "runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/"
            "teacher500_full_qc_complete290_lineage.csv"
        ),
    )
    parser.add_argument(
        "--dual128-source",
        type=Path,
        default=root / "data_splits/pvrig_v4_c/dual128_candidates_source.tsv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "data_splits/pvrig_v4_d",
    )
    args = parser.parse_args(argv)

    source_path = args.input.resolve()
    dual128_path = args.dual128_source.resolve()
    output_dir = args.output_dir.resolve()
    manifest_path = output_dir / "fullqc290_split_manifest.tsv"
    audit_path = output_dir / "fullqc290_split_audit.json"
    rows = freeze_rows(load_csv(source_path))
    write_tsv(manifest_path, rows)
    write_json(
        audit_path,
        build_audit(source_path, dual128_path, manifest_path, rows),
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "manifest": str(manifest_path),
                "audit": str(audit_path),
                "split_counts": distribution(rows, "model_split"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
