#!/usr/bin/env python3
"""Select the frozen 64-candidate V3-P2 dual-docking protocol pilot."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]

DEFAULT_CALIBRATION_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_v1_manifest.csv"
DEFAULT_CALIBRATION_SUMMARY = EXP_DIR / "prepared/pvrig_teacher_v1/candidate_summary.csv"
DEFAULT_TEACHER500_MANIFEST = (
    EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"
)
DEFAULT_TEACHER500_SUMMARY = EXP_DIR / "prepared/pvrig_teacher_formal_v1/candidate_summary.csv"
DEFAULT_OUTPUT = EXP_DIR / "data_splits/pvrig_v3_p2/dual_docking_pilot64_manifest.csv"
DEFAULT_FASTA = EXP_DIR / "data_splits/pvrig_v3_p2/dual_docking_pilot64.fasta"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p2_dual_docking_pilot_selection_audit.json"

SCHEMA_VERSION = "phase2_v3_p2_dual_docking_pilot64_v1"
CLAIM_BOUNDARY = (
    "dual-conformer docking protocol calibration; computational docking gold, "
    "not experimental binding or blocking truth"
)
TIER_ORDER = {"G5": 0, "G4": 1, "G3": 2, "G2": 3, "G1": 4}
CONTROL_QUOTAS = {"20": 6, "30": 5, "38": 4, "39": 6}
TEACHER_TIER_QUOTAS = {"G1": 8, "G2": 8, "G3": 8, "G5": 8}
REPLICATE_TEACHER_QUOTAS = {"G1": 2, "G2": 2, "G3": 2, "G5": 1}

FIELDS = [
    "schema_version",
    "pilot_rank",
    "pilot_id",
    "source_cohort",
    "source_candidate_id",
    "sequence",
    "sequence_sha256",
    "family",
    "parent_framework_cluster",
    "source_formal_split",
    "target_patch_id",
    "design_mode",
    "existing_docking_quality",
    "existing_stable_tier",
    "existing_teacher_relevance_mean",
    "selection_stratum",
    "replicate_seed_required",
    "required_docking_protocol",
    "calibration_only",
    "submission_eligible",
    "claim_boundary",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: str) -> str:
    return hashlib.sha256(f"pvrig-v3-p2-pilot-v1\t{value}".encode()).hexdigest()


def join_one_to_one(
    left: Sequence[dict[str, str]], right: Sequence[dict[str, str]], key: str = "candidate_id"
) -> list[dict[str, str]]:
    right_by_key = {row[key]: row for row in right}
    if len(right_by_key) != len(right):
        raise ValueError(f"Duplicate {key} in right table")
    output: list[dict[str, str]] = []
    for row in left:
        if row[key] not in right_by_key:
            raise ValueError(f"Missing {key}={row[key]} in right table")
        merged = dict(row)
        for field, value in right_by_key[row[key]].items():
            if field not in merged:
                merged[field] = value
        output.append(merged)
    return output


def select_calibration(
    manifest: Sequence[dict[str, str]], summary: Sequence[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows = join_one_to_one(manifest, summary)
    positives = sorted(
        (row for row in rows if row["calibration_role"] == "known_positive_calibration_only"),
        key=lambda row: (row["family"], stable_hash(row["candidate_id"])),
    )
    if len(positives) != 11 or {row["family"] for row in positives} != {"20", "30", "38", "39", "151"}:
        raise ValueError("Expected 11 known positives spanning five frozen families")
    positive_hashes = {row["sequence_sha256"] for row in positives}
    controls: list[dict[str, str]] = []
    for family, quota in CONTROL_QUOTAS.items():
        available = [
            row
            for row in rows
            if row["family"] == family
            and row["calibration_role"] == "known_positive_derived_mutant_calibration_only"
            and row["sequence_sha256"] not in positive_hashes
        ]
        available.sort(
            key=lambda row: (
                TIER_ORDER[row["provisional_stable_geometry_tier"]],
                stable_hash(row["candidate_id"]),
            )
        )
        if len(available) < quota:
            raise ValueError(f"Insufficient non-exact controls for family {family}: {len(available)} < {quota}")
        controls.extend(available[:quota])
    if len(controls) != 21 or len({row["sequence_sha256"] for row in positives + controls}) != 32:
        raise ValueError("Calibration pilot selection must contain 32 unique sequences")
    return positives, controls


def select_teacher500(
    manifest: Sequence[dict[str, str]], summary: Sequence[dict[str, str]]
) -> list[dict[str, str]]:
    rows = join_one_to_one(manifest, summary)
    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    used_parents: set[str] = set()
    patch_counts: Counter[str] = Counter()
    mode_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()

    for tier in ("G1", "G5", "G3", "G2"):
        for _ in range(TEACHER_TIER_QUOTAS[tier]):
            available = [
                row
                for row in rows
                if row["candidate_id"] not in selected_ids
                and row["provisional_stable_geometry_tier"] == tier
            ]
            if not available:
                raise ValueError(f"Insufficient Teacher500 candidates for tier {tier}")
            chosen = min(
                available,
                key=lambda row: (
                    row["parent_framework_cluster"] in used_parents,
                    patch_counts[row["target_patch_id"]],
                    mode_counts[row["design_mode"]],
                    split_counts[row["formal_split"]],
                    stable_hash(row["candidate_id"]),
                ),
            )
            selected.append(chosen)
            selected_ids.add(chosen["candidate_id"])
            used_parents.add(chosen["parent_framework_cluster"])
            patch_counts[chosen["target_patch_id"]] += 1
            mode_counts[chosen["design_mode"]] += 1
            split_counts[chosen["formal_split"]] += 1

    if len(selected) != 32 or len(used_parents) != 32:
        raise ValueError("Teacher500 pilot block must contain 32 candidates from 32 parents")
    if max(patch_counts.values()) - min(patch_counts.values()) > 1 or set(mode_counts.values()) != {16}:
        raise ValueError(f"Teacher500 pilot is not patch/mode balanced: patch={patch_counts} mode={mode_counts}")
    return selected


def replicate_ids(
    positives: Sequence[dict[str, str]],
    controls: Sequence[dict[str, str]],
    teacher: Sequence[dict[str, str]],
) -> set[str]:
    output: set[str] = set()
    for family in ("20", "30", "38", "39", "151"):
        output.add(min((row for row in positives if row["family"] == family), key=lambda row: stable_hash(row["candidate_id"]))["candidate_id"])
    for family in ("20", "30", "38", "39"):
        output.add(
            min(
                (row for row in controls if row["family"] == family),
                key=lambda row: (TIER_ORDER[row["provisional_stable_geometry_tier"]], stable_hash(row["candidate_id"])),
            )["candidate_id"]
        )
    for tier, quota in REPLICATE_TEACHER_QUOTAS.items():
        matches = sorted(
            (row for row in teacher if row["provisional_stable_geometry_tier"] == tier),
            key=lambda row: stable_hash(row["candidate_id"]),
        )
        output.update(row["candidate_id"] for row in matches[:quota])
    if len(output) != 16:
        raise ValueError(f"Expected 16 replicate candidates, found {len(output)}")
    return output


def format_row(
    row: dict[str, str], cohort: str, rank: int, replicate: bool
) -> dict[str, object]:
    calibration = cohort != "teacher500_stratified"
    return {
        "schema_version": SCHEMA_VERSION,
        "pilot_rank": rank,
        "pilot_id": f"P2PILOT_{rank:03d}",
        "source_cohort": cohort,
        "source_candidate_id": row["candidate_id"],
        "sequence": row["sequence"] if calibration else row["vhh_sequence"],
        "sequence_sha256": row["sequence_sha256"],
        "family": row.get("family", ""),
        "parent_framework_cluster": row.get("parent_framework_cluster", ""),
        "source_formal_split": row.get("formal_split", row.get("split", "calibration_only")),
        "target_patch_id": row.get("target_patch_id", ""),
        "design_mode": row.get("design_mode", ""),
        "existing_docking_quality": "CALIBRATION_REPLAY" if calibration else "DG_B",
        "existing_stable_tier": row["provisional_stable_geometry_tier"],
        "existing_teacher_relevance_mean": row["teacher_relevance_mean"],
        "selection_stratum": (
            f"positive_family_{row['family']}"
            if cohort == "known_positive"
            else f"matched_control_family_{row['family']}"
            if cohort == "matched_control"
            else f"teacher500_{row['provisional_stable_geometry_tier']}"
        ),
        "replicate_seed_required": str(replicate).lower(),
        "required_docking_protocol": "DG_A_INDEPENDENT_8X6B_AND_9E6Y",
        "calibration_only": str(calibration).lower(),
        "submission_eligible": str(not calibration).lower(),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_fasta(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        f">{row['pilot_id']} source={row['source_candidate_id']} cohort={row['source_cohort']} replicate={row['replicate_seed_required']}\n{row['sequence']}\n"
        for row in rows
    )
    path.write_text(text, encoding="ascii")


def build(args: argparse.Namespace) -> dict[str, object]:
    calibration_manifest = Path(args.calibration_manifest)
    calibration_summary = Path(args.calibration_summary)
    teacher_manifest = Path(args.teacher500_manifest)
    teacher_summary = Path(args.teacher500_summary)
    output = Path(args.output)
    fasta = Path(args.fasta)
    audit_path = Path(args.audit)

    positives, controls = select_calibration(read_csv(calibration_manifest), read_csv(calibration_summary))
    teacher = select_teacher500(read_csv(teacher_manifest), read_csv(teacher_summary))
    replicate = replicate_ids(positives, controls, teacher)
    source_rows = [
        *(('known_positive', row) for row in positives),
        *(('matched_control', row) for row in controls),
        *(('teacher500_stratified', row) for row in teacher),
    ]
    rows = [format_row(row, cohort, index, row["candidate_id"] in replicate) for index, (cohort, row) in enumerate(source_rows, 1)]
    if len(rows) != 64 or len({row["sequence_sha256"] for row in rows}) != 64:
        raise ValueError("Pilot must contain 64 unique candidate sequences")
    write_csv(output, rows)
    write_fasta(fasta, rows)

    teacher_rows = [row for row in rows if row["source_cohort"] == "teacher500_stratified"]
    audit: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_P2_DUAL_DOCKING_PILOT64_SELECTED",
        "candidate_count": len(rows),
        "unique_sequence_count": len({row["sequence_sha256"] for row in rows}),
        "cohort_counts": dict(Counter(str(row["source_cohort"]) for row in rows)),
        "positive_family_counts": dict(Counter(str(row["family"]) for row in rows if row["source_cohort"] == "known_positive")),
        "control_family_counts": dict(Counter(str(row["family"]) for row in rows if row["source_cohort"] == "matched_control")),
        "teacher_stable_tier_counts": dict(Counter(str(row["existing_stable_tier"]) for row in teacher_rows)),
        "teacher_parent_count": len({row["parent_framework_cluster"] for row in teacher_rows}),
        "teacher_patch_counts": dict(Counter(str(row["target_patch_id"]) for row in teacher_rows)),
        "teacher_mode_counts": dict(Counter(str(row["design_mode"]) for row in teacher_rows)),
        "replicate_seed_candidate_count": sum(row["replicate_seed_required"] == "true" for row in rows),
        "required_docking_protocol": "DG_A_INDEPENDENT_8X6B_AND_9E6Y",
        "input_sha256": {
            "calibration_manifest": sha256_file(calibration_manifest),
            "calibration_summary": sha256_file(calibration_summary),
            "teacher500_manifest": sha256_file(teacher_manifest),
            "teacher500_summary": sha256_file(teacher_summary),
        },
        "output_paths": {"manifest": str(output.resolve()), "fasta": str(fasta.resolve())},
        "output_sha256": {"manifest": sha256_file(output), "fasta": sha256_file(fasta)},
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-manifest", default=str(DEFAULT_CALIBRATION_MANIFEST))
    parser.add_argument("--calibration-summary", default=str(DEFAULT_CALIBRATION_SUMMARY))
    parser.add_argument("--teacher500-manifest", default=str(DEFAULT_TEACHER500_MANIFEST))
    parser.add_argument("--teacher500-summary", default=str(DEFAULT_TEACHER500_SUMMARY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--fasta", default=str(DEFAULT_FASTA))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    audit = build(parse_args(argv))
    print(json.dumps(audit, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
