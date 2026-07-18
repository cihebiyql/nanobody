#!/usr/bin/env python3
"""Build the immutable V2.4 supervised-1507 development table."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence


NEW_FIELDS = [
    "docking_evidence_tier",
    "development_reliability_tier",
    "development_reliability_weight",
    "successful_seed_count_8X6B",
    "successful_seed_ids_8X6B",
    "successful_seed_count_9E6Y",
    "successful_seed_ids_9E6Y",
    "seed_dispersion_max",
    "ranking_release",
    "label_update_provenance",
]


class ContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise ContractError(f"missing TSV header: {path}")
        rows = list(reader)
        return list(reader.fieldnames), rows


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def verify_hashes(contract: Mapping[str, Any], paths: Mapping[str, Path]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for key, spec in contract["inputs"].items():
        path = paths[key]
        digest = sha256_file(path)
        observed[key] = digest
        require(digest == spec["sha256"], f"input hash mismatch for {key}: {digest}")
    return observed


def parse_seed_ids(value: str) -> list[int]:
    if not value:
        return []
    try:
        return [int(item) for item in value.split(",")]
    except ValueError as exc:
        raise ContractError(f"invalid seed id list: {value}") from exc


def exact_min(left: str, right: str) -> str:
    try:
        return str(min(Decimal(left), Decimal(right)))
    except InvalidOperation as exc:
        raise ContractError(f"invalid decimal receptor score: {left}, {right}") from exc


def _seed_text(values: Sequence[int]) -> str:
    return ",".join(str(value) for value in values)


def build_rows(
    contract: Mapping[str, Any],
    old_fields: list[str],
    old_rows: list[dict[str, str]],
    adaptive_rows: list[dict[str, str]],
    adaptive_receipt: Mapping[str, Any],
    adaptive_package_receipt: Mapping[str, Any],
    v4d_contract: Mapping[str, Any],
    v4d_audit: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, str]], dict[str, Any]]:
    expected = contract["expected"]
    labels = contract["source_labels"]
    mapping = contract["development_reliability"]["tier_mapping"]
    weights = contract["development_reliability"]["fixed_weights"]

    require(adaptive_receipt.get("status") == contract["inputs"]["adaptive_receipt"]["required_status"], "adaptive receipt status mismatch")
    require(adaptive_package_receipt.get("status") == contract["inputs"]["adaptive_package_receipt"]["required_status"], "adaptive package receipt status mismatch")
    require(v4d_audit.get("status") == contract["inputs"]["v4d_audit"]["required_status"], "V4-D audit status mismatch")
    require(v4d_audit["sealed_boundary"]["sealed_pose_files_opened"] == 0, "sealed V4-D pose access detected")
    require(v4d_audit["sealed_boundary"]["sealed_result_files_opened"] == 0, "sealed V4-D result access detected")

    require(len(old_rows) == expected["rows"], "old supervised row count mismatch")
    old_by_id = {row["candidate_id"]: row for row in old_rows}
    require(len(old_by_id) == len(old_rows), "duplicate candidate_id in old supervised table")
    old_v4d = {cid: row for cid, row in old_by_id.items() if row["teacher_source"] == labels["v4d_old"]}
    old_v4h = {cid: row for cid, row in old_by_id.items() if row["teacher_source"] == labels["v4h_old"]}
    require(len(old_v4d) == expected["teacher_source_counts"][labels["v4d_old"]], "V4-D count mismatch")
    require(len(old_v4h) == expected["teacher_source_counts"][labels["v4h_new"]], "V4-H count mismatch")
    require(len(old_v4d) + len(old_v4h) == len(old_rows), "unexpected teacher source in old table")

    adaptive_by_id: dict[str, dict[str, str]] = {}
    adaptive_tiers = Counter(row["docking_evidence_tier"] for row in adaptive_rows)
    require(dict(adaptive_tiers) == expected["v4h_adaptive_tier_counts"], f"adaptive tier counts mismatch: {dict(adaptive_tiers)}")
    for row in adaptive_rows:
        if row["docking_evidence_tier"] != "TECHNICAL_INCOMPLETE":
            require(row["candidate_id"] not in adaptive_by_id, "duplicate adaptive candidate_id")
            adaptive_by_id[row["candidate_id"]] = row
    require(set(adaptive_by_id) == set(old_v4h), "V4-H analyzable candidate closure mismatch")

    expected_seeds = list(expected["expected_seed_ids"])
    expected_seed_set = set(expected_seeds)
    partial = v4d_contract["expected_partial_candidate"]
    partial_id = partial["candidate_id"]
    require(partial_id in old_v4d, "V4-D partial candidate absent")
    require(v4d_audit["counts"]["teacher_candidates"] == len(old_v4d), "V4-D audit candidate count mismatch")

    output: list[dict[str, str]] = []
    for candidate_id in sorted(old_by_id):
        old = old_by_id[candidate_id]
        new = dict(old)
        new["schema_version"] = "pvrig_v6_training_table_v2_4"
        new["claim_boundary"] = contract["claim_boundary"]
        if candidate_id in old_v4d:
            new["docking_evidence_tier"] = "V4D_MULTI_SEED"
            tier = mapping["V4D_MULTI_SEED"]
            if candidate_id == partial_id:
                seeds8 = list(partial["observed_seeds_8x6b"])
                seeds9 = list(partial["observed_seeds_9e6y"])
            else:
                seeds8 = expected_seeds
                seeds9 = expected_seeds
            new["seed_dispersion_max"] = old["teacher_uncertainty"]
            new["ranking_release"] = "v4d_open_multi_seed_frozen_v1_1"
            new["label_update_provenance"] = "V4-D labels preserved byte-for-byte from materialized_v1_1"
        else:
            adaptive = adaptive_by_id[candidate_id]
            for key in ("sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"):
                require(old[key] == adaptive[key], f"V4-H metadata mismatch for {candidate_id}: {key}")
            evidence = adaptive["docking_evidence_tier"]
            require(evidence in mapping, f"unsupported V4-H evidence tier: {evidence}")
            seeds8 = parse_seed_ids(adaptive["successful_seed_ids_8X6B"])
            seeds9 = parse_seed_ids(adaptive["successful_seed_ids_9E6Y"])
            require(len(seeds8) == int(adaptive["successful_seed_count_8X6B"]), f"8X6B seed count mismatch: {candidate_id}")
            require(len(seeds9) == int(adaptive["successful_seed_count_9E6Y"]), f"9E6Y seed count mismatch: {candidate_id}")
            require(set(seeds8) <= expected_seed_set and set(seeds9) <= expected_seed_set, f"unexpected V4-H seed id: {candidate_id}")
            require(exact_min(adaptive["median_score_8X6B"], adaptive["median_score_9E6Y"]) == adaptive["R_dual_min"], f"adaptive exact-min mismatch: {candidate_id}")
            new["teacher_source"] = labels["v4h_new"]
            new["teacher_reliability"] = evidence
            new["R_8X6B"] = adaptive["median_score_8X6B"]
            new["R_9E6Y"] = adaptive["median_score_9E6Y"]
            new["R_dual_min"] = exact_min(new["R_8X6B"], new["R_9E6Y"])
            new["teacher_uncertainty"] = adaptive["seed_dispersion_max"]
            new["technical_reasons"] = adaptive["technical_reasons"]
            new["docking_evidence_tier"] = evidence
            new["seed_dispersion_max"] = adaptive["seed_dispersion_max"]
            new["ranking_release"] = adaptive["ranking_release"]
            new["label_update_provenance"] = "V4-H adaptive receptor medians with exact-min dual target"
            tier = mapping[evidence]

        require(seeds8 and seeds9, f"empty observed seed set: {candidate_id}")
        require(set(seeds8) <= expected_seed_set and set(seeds9) <= expected_seed_set, f"unexpected seed id: {candidate_id}")
        new["development_reliability_tier"] = tier
        new["development_reliability_weight"] = weights[tier]
        new["sample_weight"] = weights[tier]
        new["successful_seed_count_8X6B"] = str(len(seeds8))
        new["successful_seed_ids_8X6B"] = _seed_text(seeds8)
        new["successful_seed_count_9E6Y"] = str(len(seeds9))
        new["successful_seed_ids_9E6Y"] = _seed_text(seeds9)
        output.append(new)

    require(len(output) == expected["rows"], "new table row count mismatch")
    require(len({row["candidate_id"] for row in output}) == len(output), "new table candidate duplication")
    require(all(hashlib.sha256(row["sequence"].encode()).hexdigest() == row["sequence_sha256"] for row in output), "sequence hash mismatch")

    source_counts = Counter(row["teacher_source"] for row in output)
    require(dict(source_counts) == expected["teacher_source_counts"], f"new teacher source counts mismatch: {dict(source_counts)}")
    tier_counts = Counter(row["development_reliability_tier"] for row in output)
    require(dict(tier_counts) == expected["development_reliability_tier_counts"], f"development tier counts mismatch: {dict(tier_counts)}")
    parent_folds: dict[str, set[str]] = defaultdict(set)
    for row in output:
        parent_folds[row["parent_framework_cluster"]].add(row["outer_fold"])
    require(len(parent_folds) == expected["parent_cluster_count"], "parent cluster count mismatch")
    require(all(len(folds) == 1 for folds in parent_folds.values()), "parent split across outer folds")
    require(len({next(iter(folds)) for folds in parent_folds.values()}) == expected["outer_fold_count"], "outer fold count mismatch")
    require(len({row["parent_framework_cluster"] for row in output if row["teacher_source"] == labels["v4d_old"]}) == expected["v4d_parent_cluster_count"], "V4-D parent count mismatch")
    require(len({row["parent_framework_cluster"] for row in output if row["teacher_source"] == labels["v4h_new"]}) == expected["v4h_parent_cluster_count"], "V4-H parent count mismatch")

    # V4-D target and established reliability preservation is a byte-level contract.
    for candidate_id, old in old_v4d.items():
        new = next(row for row in output if row["candidate_id"] == candidate_id)
        for key in ("R_8X6B", "R_9E6Y", "R_dual_min", "teacher_uncertainty", "teacher_source", "teacher_reliability", "outer_fold"):
            require(new[key] == old[key], f"V4-D preserved field changed: {candidate_id} {key}")

    insert_at = old_fields.index("outer_fold")
    output_fields = old_fields[:insert_at] + NEW_FIELDS + old_fields[insert_at:]
    stats = {
        "row_count": len(output),
        "teacher_source_counts": dict(sorted(source_counts.items())),
        "development_reliability_tier_counts": dict(sorted(tier_counts.items())),
        "adaptive_docking_evidence_tier_counts": dict(sorted(adaptive_tiers.items())),
        "parent_cluster_count": len(parent_folds),
        "outer_fold_parent_counts": dict(sorted(Counter(next(iter(v)) for v in parent_folds.values()).items())),
        "v4d_partial_candidate": partial_id,
    }
    return output_fields, output, stats


def materialize(contract_path: Path, paths: Mapping[str, Path], output_dir: Path) -> dict[str, Any]:
    contract = load_json(contract_path)
    input_hashes = verify_hashes(contract, paths)
    old_hash_before = input_hashes["supervised_v1_1"]
    old_fields, old_rows = read_tsv(paths["supervised_v1_1"])
    _, adaptive_rows = read_tsv(paths["adaptive_ranking"])
    fields, rows, stats = build_rows(
        contract,
        old_fields,
        old_rows,
        adaptive_rows,
        load_json(paths["adaptive_receipt"]),
        load_json(paths["adaptive_package_receipt"]),
        load_json(paths["v4d_contract"]),
        load_json(paths["v4d_audit"]),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / "v6_supervised1507_v2_4.tsv"
    tmp_path = output_dir / ".v6_supervised1507_v2_4.tsv.tmp"
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, table_path)
    require(sha256_file(paths["supervised_v1_1"]) == old_hash_before, "old supervised table mutated")
    table_hash = sha256_file(table_path)
    receipt = {
        "schema_version": "pvrig_v6_supervised1507_v2_4_receipt_v1",
        "status": "PASS_V2_4_SUPERVISED1507_MATERIALIZED",
        "claim_boundary": contract["claim_boundary"],
        "contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        "builder": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
        "inputs": {key: {"path": str(paths[key]), "sha256": value} for key, value in sorted(input_hashes.items())},
        "output": {"path": str(table_path), "sha256": table_hash, "bytes": table_path.stat().st_size, **stats},
        "development_reliability": contract["development_reliability"],
        "label_policy": contract["label_policy"],
        "sealed_boundary": contract["sealed_boundary"],
        "old_supervised_table_unchanged": True,
    }
    receipt_path = output_dir / "v6_supervised1507_v2_4.receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums = [
        f"{table_hash}  {table_path.name}",
        f"{sha256_file(receipt_path)}  {receipt_path.name}",
    ]
    (output_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--supervised-v1-1", type=Path, required=True)
    parser.add_argument("--adaptive-ranking", type=Path, required=True)
    parser.add_argument("--adaptive-receipt", type=Path, required=True)
    parser.add_argument("--adaptive-package-receipt", type=Path, required=True)
    parser.add_argument("--v4d-contract", type=Path, required=True)
    parser.add_argument("--v4d-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = {
        "supervised_v1_1": args.supervised_v1_1,
        "adaptive_ranking": args.adaptive_ranking,
        "adaptive_receipt": args.adaptive_receipt,
        "adaptive_package_receipt": args.adaptive_package_receipt,
        "v4d_contract": args.v4d_contract,
        "v4d_audit": args.v4d_audit,
    }
    receipt = materialize(args.contract, paths, args.output_dir)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
