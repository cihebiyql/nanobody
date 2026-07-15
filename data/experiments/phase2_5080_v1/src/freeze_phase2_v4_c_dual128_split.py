#!/usr/bin/env python3
"""Freeze a label-blind split for the independent dual-conformation panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "phase2_v4_c_dual128_split_v1"
FROZEN_AT = "2026-07-15T17:25:37+08:00"
SOURCE_SHA256 = "5e536f7178cb214102aef684c65fc97b4996d3b83de5b6f506ad2f9bf8e66c78"
EXPECTED_CANDIDATES = 128
EXPECTED_SPLIT_COUNTS = {"OPEN_DEVELOPMENT": 96, "RETROSPECTIVE_GROUPED_CHALLENGE": 32}

# Selected before reading any result-level labels from the new 1050-job campaign.
FROZEN_HOLDOUT_FAMILIES = {
    "cdr3fam_1123a5138b7256ef",
    "cdr3fam_2352b3129f9fcd51",
    "cdr3fam_2448fd763ef46a7a",
    "cdr3fam_34167aa664ca4668",
    "cdr3fam_4014404289c4a5bb",
    "cdr3fam_50c2e1562afdc685",
    "cdr3fam_5a8a2dcdbefa3711",
    "cdr3fam_5bf78d2d6f74ea86",
    "cdr3fam_6fbf6dd84aa9a641",
    "cdr3fam_70cf0d845194cd11",
    "cdr3fam_7613b1d45053a428",
    "cdr3fam_85883584551877a4",
    "cdr3fam_b3bcf70d86ca348c",
    "cdr3fam_c494700d5c100c30",
    "cdr3fam_d58db9e2493ba0c2",
    "cdr3fam_d618a0ac25c434b6",
    "cdr3fam_e8a153d548d1244c",
    "cdr3fam_fd1391935e1127d1",
}

REQUIRED_FIELDS = {
    "candidate_id",
    "source_run_id",
    "sequence_sha256",
    "sequence",
    "arm_id",
    "scaffold_id",
    "h3_regime",
    "backbone_group_id",
    "near_cdr3_family_id",
    "selection_bucket",
    "cdr1",
    "cdr2",
    "cdr3",
}

OUTPUT_FIELDS = [
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "phase",
    "arm_id",
    "scaffold_id",
    "h3_regime",
    "backbone_group_id",
    "near_cdr3_family_id",
    "selection_bucket",
    "source_run_id",
    "cdr1",
    "cdr2",
    "cdr3",
    "model_split",
    "new_docking_label_policy",
    "claim_boundary",
]

EXPECTED_HOLDOUT_DISTRIBUTIONS = {
    "phase": {"P1": 6, "P2": 4, "P3": 7, "P4": 6, "P5": 5, "P6": 4},
    "scaffold_id": {"ekg": 13, "qkg": 8, "qrg": 11},
    "selection_bucket": {
        "DIVERSE_PLAUSIBLE": 7,
        "LOCKED_DUAL_REFERENCE_A": 12,
        "RF2_FORMAL_PASS": 1,
        "RF2_NEAR_PASS": 6,
        "SINGLE_BASELINE_RECHECK": 6,
    },
    "h3_regime": {"L": 24, "S": 8},
}

CLAIM_BOUNDARY = (
    "Fixed-PVRIG sequence-to-computational-dual-docking surrogate split only; "
    "not binding, affinity, competition, or experimental blocking truth."
)


class SplitFreezeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_source(path: Path) -> list[dict[str, str]]:
    actual_sha256 = sha256_file(path)
    if actual_sha256 != SOURCE_SHA256:
        raise SplitFreezeError(
            f"source_sha256_mismatch: expected={SOURCE_SHA256} actual={actual_sha256}"
        )
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_FIELDS - fields)
        if missing:
            raise SplitFreezeError(f"source_missing_required_fields:{','.join(missing)}")
        rows = list(reader)
    if len(rows) != EXPECTED_CANDIDATES:
        raise SplitFreezeError(f"expected_{EXPECTED_CANDIDATES}_rows_got_{len(rows)}")
    for field in ("candidate_id", "sequence_sha256"):
        values = [row[field] for row in rows]
        if any(not value for value in values) or len(set(values)) != len(values):
            raise SplitFreezeError(f"blank_or_duplicate:{field}")
    return rows


def phase_from_arm(arm_id: str) -> str:
    phase = arm_id.split("_", 1)[0]
    if phase not in {"P1", "P2", "P3", "P4", "P5", "P6"}:
        raise SplitFreezeError(f"invalid_phase_from_arm:{arm_id}")
    return phase


def freeze_rows(source_rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for source in source_rows:
        family = source["near_cdr3_family_id"]
        model_split = (
            "RETROSPECTIVE_GROUPED_CHALLENGE"
            if family in FROZEN_HOLDOUT_FAMILIES
            else "OPEN_DEVELOPMENT"
        )
        output.append(
            {
                "candidate_id": source["candidate_id"],
                "sequence_sha256": source["sequence_sha256"],
                "sequence": source["sequence"],
                "phase": phase_from_arm(source["arm_id"]),
                "arm_id": source["arm_id"],
                "scaffold_id": source["scaffold_id"],
                "h3_regime": source["h3_regime"],
                "backbone_group_id": source["backbone_group_id"],
                "near_cdr3_family_id": family,
                "selection_bucket": source["selection_bucket"],
                "source_run_id": source["source_run_id"],
                "cdr1": source["cdr1"],
                "cdr2": source["cdr2"],
                "cdr3": source["cdr3"],
                "model_split": model_split,
                "new_docking_label_policy": (
                    "DESCRIPTIVE_CHALLENGE_NOT_FORMAL"
                    if model_split == "RETROSPECTIVE_GROUPED_CHALLENGE"
                    else "OPEN_AFTER_EVALUATOR_STABLE_PASS"
                ),
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    output.sort(key=lambda row: row["candidate_id"])
    validate_frozen_rows(output)
    return output


def distribution(rows: Iterable[dict[str, str]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(row[field] for row in rows).items()))


def validate_frozen_rows(rows: list[dict[str, str]]) -> None:
    split_counts = Counter(row["model_split"] for row in rows)
    if dict(split_counts) != EXPECTED_SPLIT_COUNTS:
        raise SplitFreezeError(
            f"split_count_mismatch: expected={EXPECTED_SPLIT_COUNTS} actual={dict(split_counts)}"
        )
    by_split = {
        split: [row for row in rows if row["model_split"] == split]
        for split in EXPECTED_SPLIT_COUNTS
    }
    open_families = {row["near_cdr3_family_id"] for row in by_split["OPEN_DEVELOPMENT"]}
    test_families = {
        row["near_cdr3_family_id"]
        for row in by_split["RETROSPECTIVE_GROUPED_CHALLENGE"]
    }
    if open_families & test_families:
        raise SplitFreezeError("near_cdr3_family_overlap_across_split")
    if test_families != FROZEN_HOLDOUT_FAMILIES:
        raise SplitFreezeError("frozen_holdout_family_set_mismatch")
    holdout = by_split["RETROSPECTIVE_GROUPED_CHALLENGE"]
    for field, expected in EXPECTED_HOLDOUT_DISTRIBUTIONS.items():
        actual = distribution(holdout, field)
        if actual != expected:
            raise SplitFreezeError(
                f"holdout_distribution_mismatch:{field}:expected={expected}:actual={actual}"
            )


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def build_audit(source_path: Path, manifest_path: Path, rows: list[dict[str, str]]) -> dict[str, object]:
    split_counts = distribution(rows, "model_split")
    split_distributions = {
        split: {
            field: distribution(
                (row for row in rows if row["model_split"] == split), field
            )
            for field in ("phase", "scaffold_id", "selection_bucket", "h3_regime")
        }
        for split in EXPECTED_SPLIT_COUNTS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_RETROSPECTIVE_GROUPED_CHALLENGE_SPLIT",
        "frozen_at": FROZEN_AT,
        "source": {
            "path": str(source_path),
            "sha256": sha256_file(source_path),
            "candidate_count": len(rows),
            "remote_origin": (
                "/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714/"
                "inputs/candidates_128.tsv"
            ),
        },
        "selection": {
            "new_docking_result_fields_used": [],
            "label_blind_strata": [
                "phase_from_arm_id",
                "scaffold_id",
                "selection_bucket_preexisting_v2_metadata",
                "h3_regime",
            ],
            "group_unit": "near_cdr3_family_id",
            "deterministic_search_seed": 20260715,
            "deterministic_search_attempts": 500000,
            "frozen_holdout_family_count": len(FROZEN_HOLDOUT_FAMILIES),
            "frozen_holdout_families": sorted(FROZEN_HOLDOUT_FAMILIES),
            "limitation": (
                "The split code did not read result-level labels, but the remote campaign already had "
                "partial results before this artifact was timestamped. This is a retrospective grouped "
                "challenge, not a provably untouched formal test. All 128 candidates also come from one "
                "source run and three scaffold IDs."
            ),
        },
        "split_counts": split_counts,
        "split_distributions": split_distributions,
        "integrity_gates": {
            "source_sha256_matches": sha256_file(source_path) == SOURCE_SHA256,
            "candidate_count_is_128": len(rows) == EXPECTED_CANDIDATES,
            "exact_sequence_overlap_across_split": 0,
            "near_cdr3_family_overlap_across_split": 0,
            "holdout_distribution_matches_frozen_spec": True,
            "new_docking_labels_read_by_split_code": False,
            "strict_prospective_time_order_proven": False,
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
        default=root / "data_splits/pvrig_v4_c/dual128_candidates_source.tsv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "data_splits/pvrig_v4_c",
    )
    args = parser.parse_args(argv)

    source_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    manifest_path = output_dir / "dual128_split_manifest.tsv"
    audit_path = output_dir / "dual128_split_audit.json"
    rows = freeze_rows(load_source(source_path))
    write_tsv(manifest_path, rows)
    write_json(audit_path, build_audit(source_path, manifest_path, rows))
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
