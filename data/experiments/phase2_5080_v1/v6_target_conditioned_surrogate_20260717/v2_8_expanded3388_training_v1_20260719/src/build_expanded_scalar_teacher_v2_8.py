#!/usr/bin/env python3
"""Build the versioned 3,388-row scalar docking-geometry teacher.

The builder is deliberately scalar-only.  It does not pretend that the new V4-I
rows already have local 126-D monomer features or residue-contact supervision.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


SCALAR_FIELDS = [
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_framework_cluster",
    "target_patch_id",
    "design_mode",
    "cdr1",
    "cdr2",
    "cdr3",
    "source_campaign",
    "source_lane",
    "teacher_source",
    "teacher_reliability",
    "sample_weight",
    "docking_evidence_tier",
    "development_reliability_tier",
    "development_reliability_weight",
    "successful_seed_count_8X6B",
    "successful_seed_ids_8X6B",
    "successful_seed_count_9E6Y",
    "successful_seed_ids_9E6Y",
    "paired_successful_seed_count",
    "seed_dispersion_max",
    "uncertainty_observed",
    "ranking_release",
    "label_update_provenance",
    "outer_fold",
    "R_8X6B",
    "R_9E6Y",
    "R_dual_min",
    "teacher_uncertainty",
    "technical_reasons",
    "structure_feature_state",
    "contact_teacher_state",
    "stage2_repeat_selected",
    "claim_boundary",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def read_tsv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError(f"missing_header:{path}")
        return list(reader), list(reader.fieldnames)


def write_tsv(path: Path, rows: Iterable[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def require_unique(rows: list[dict[str, str]], field: str, name: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row.get(field, "")
        if not key:
            raise ValueError(f"blank_{field}:{name}")
        if key in out:
            raise ValueError(f"duplicate_{field}:{name}:{key}")
        out[key] = row
    return out


def as_float(value: str, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_float:{label}:{value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"nonfinite_float:{label}:{value!r}")
    return result


def check_exact_min(row: dict[str, str], r8_key: str, r9_key: str, dual_key: str, name: str) -> None:
    r8 = as_float(row[r8_key], f"{name}:{r8_key}")
    r9 = as_float(row[r9_key], f"{name}:{r9_key}")
    dual = as_float(row[dual_key], f"{name}:{dual_key}")
    if abs(dual - min(r8, r9)) > 1e-8:
        raise ValueError(f"exact_min_violation:{name}:{r8}:{r9}:{dual}")


def quantiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}

    def pick(q: float) -> float:
        return ordered[int(q * (len(ordered) - 1))]

    return {
        "min": ordered[0],
        "q10": pick(0.10),
        "q25": pick(0.25),
        "median": pick(0.50),
        "q75": pick(0.75),
        "q90": pick(0.90),
        "max": ordered[-1],
    }


def reliability_fields(tier: str, contract: dict) -> tuple[str, str]:
    policy = contract["reliability_policy"].get(tier)
    if policy is None:
        raise ValueError(f"unknown_reliability_tier:{tier}")
    return str(policy["tier"]), str(policy["base_weight"])


def paired_seed_count(row: dict[str, str]) -> int:
    seeds8 = {item for item in row["successful_seed_ids_8X6B"].split(",") if item}
    seeds9 = {item for item in row["successful_seed_ids_9E6Y"].split(",") if item}
    return len(seeds8 & seeds9)


def validate_contract_hashes(contract: dict, paths: dict[str, Path]) -> dict[str, str]:
    actual = {name: sha256_file(path) for name, path in paths.items()}
    for name, expected in contract["input_sha256"].items():
        if actual.get(name) != expected:
            raise ValueError(f"input_sha256_mismatch:{name}:{actual.get(name)}:{expected}")
    return actual


def build(args: argparse.Namespace) -> dict:
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    input_paths = {
        "old_supervised1507": args.old_teacher,
        "v4i_candidates": args.v4i_candidates,
        "v4i_stage1_ranking": args.v4i_stage1,
        "v4i_stage2_ranking": args.v4i_stage2,
        "protocol_compatibility_audit": args.protocol_compatibility,
    }
    input_hashes = validate_contract_hashes(contract, input_paths)
    protocol_compatibility = json.loads(args.protocol_compatibility.read_text(encoding="utf-8"))
    if protocol_compatibility.get("status") != "PASS_SCORING_AND_DOCKING_SEMANTICS_COMPATIBLE_PANEL_SIZE_ONLY_DIFFERENCES":
        raise ValueError("protocol_compatibility_status_not_pass")
    if protocol_compatibility.get("normalized_protocol_semantics_equal") is not True:
        raise ValueError("normalized_protocol_semantics_not_equal")
    if protocol_compatibility.get("candidate_level_aggregation", {}).get("compatible_scale") is not True:
        raise ValueError("candidate_level_scalar_scale_not_compatible")

    old_rows, _ = read_tsv(args.old_teacher)
    candidate_rows, _ = read_tsv(args.v4i_candidates)
    stage1_rows, _ = read_tsv(args.v4i_stage1)
    stage2_rows, _ = read_tsv(args.v4i_stage2)
    expected = contract["expected_counts"]
    observed_input_counts = {
        "old_teacher_rows": len(old_rows),
        "v4i_candidate_rows": len(candidate_rows),
        "v4i_stage1_rows": len(stage1_rows),
        "v4i_stage2_rows": len(stage2_rows),
    }
    for key, value in observed_input_counts.items():
        if value != expected[key]:
            raise ValueError(f"count_mismatch:{key}:{value}:{expected[key]}")

    old_by_id = require_unique(old_rows, "candidate_id", "old_teacher")
    candidates_by_id = require_unique(candidate_rows, "candidate_id", "v4i_candidates")
    stage1_by_id = require_unique(stage1_rows, "candidate_id", "v4i_stage1")
    stage2_by_id = require_unique(stage2_rows, "candidate_id", "v4i_stage2")

    if set(candidates_by_id) != set(stage1_by_id):
        raise ValueError("candidate_stage1_id_set_mismatch")
    if not set(stage2_by_id).issubset(stage1_by_id):
        raise ValueError("stage2_not_subset_of_stage1")
    if set(old_by_id) & set(stage1_by_id):
        raise ValueError("candidate_id_overlap_old_v4i")

    old_seq_hashes: set[str] = set()
    parent_folds: dict[str, set[str]] = defaultdict(set)
    expanded_rows: list[dict[str, str]] = []
    for row in old_rows:
        if sequence_sha256(row["sequence"]) != row["sequence_sha256"]:
            raise ValueError(f"old_sequence_sha_mismatch:{row['candidate_id']}")
        if row["sequence_sha256"] in old_seq_hashes:
            raise ValueError(f"old_sequence_sha_duplicate:{row['sequence_sha256']}")
        old_seq_hashes.add(row["sequence_sha256"])
        check_exact_min(row, "R_8X6B", "R_9E6Y", "R_dual_min", f"old:{row['candidate_id']}")
        parent_folds[row["parent_framework_cluster"]].add(row["outer_fold"])
        source_campaign = "V4D" if row["teacher_source"] == "V4D_OPEN_MULTI_SEED" else "V4H"
        expanded_rows.append(
            {
                **{field: row.get(field, "") for field in SCALAR_FIELDS},
                "schema_version": "pvrig_v6_scalar_teacher_v2_8",
                "source_campaign": source_campaign,
                "source_lane": "LEGACY_CANONICAL_1507",
                "paired_successful_seed_count": str(paired_seed_count(row)),
                "uncertainty_observed": "1" if int(row["successful_seed_count_8X6B"]) > 1 and int(row["successful_seed_count_9E6Y"]) > 1 else "0",
                "structure_feature_state": "LOCAL_126D_AVAILABLE",
                "contact_teacher_state": "LOCAL_CONTACT_TEACHER_AVAILABLE",
                "stage2_repeat_selected": "0",
            }
        )
    bad_parent_folds = {parent: folds for parent, folds in parent_folds.items() if len(folds) != 1}
    if bad_parent_folds:
        raise ValueError(f"old_parent_cross_fold_leakage:{bad_parent_folds}")
    fold_by_parent = {parent: next(iter(folds)) for parent, folds in parent_folds.items()}

    technical_rows: list[dict[str, str]] = []
    v4i_rows: list[dict[str, str]] = []
    new_seq_hashes: set[str] = set()
    for candidate_id, stage1 in stage1_by_id.items():
        candidate = candidates_by_id[candidate_id]
        if candidate["sequence_sha256"] != stage1["sequence_sha256"]:
            raise ValueError(f"candidate_stage1_sha_mismatch:{candidate_id}")
        if sequence_sha256(candidate["sequence"]) != candidate["sequence_sha256"]:
            raise ValueError(f"v4i_sequence_sha_mismatch:{candidate_id}")
        if candidate["sequence_sha256"] in new_seq_hashes:
            raise ValueError(f"v4i_sequence_sha_duplicate:{candidate['sequence_sha256']}")
        new_seq_hashes.add(candidate["sequence_sha256"])
        if candidate["sequence_sha256"] in old_seq_hashes:
            raise ValueError(f"sequence_sha_overlap_old_v4i:{candidate['sequence_sha256']}")
        if candidate["parent_framework_cluster"] not in fold_by_parent:
            raise ValueError(f"unmapped_parent_fold:{candidate_id}:{candidate['parent_framework_cluster']}")

        if not stage1["R_dual_min"]:
            technical_rows.append({**candidate, **{f"stage1__{k}": v for k, v in stage1.items()}})
            continue

        selected = candidate_id in stage2_by_id
        label = stage2_by_id[candidate_id] if selected else stage1
        r8_key = "median_score_8X6B"
        r9_key = "median_score_9E6Y"
        check_exact_min(label, r8_key, r9_key, "R_dual_min", f"v4i:{candidate_id}")
        reliability = label["docking_evidence_tier"]
        dev_tier, base_weight = reliability_fields(reliability, contract)
        observed_uncertainty = int(label["successful_seed_count_8X6B"]) > 1 and int(label["successful_seed_count_9E6Y"]) > 1
        teacher_source = "V4I_STAGE2_COMBINED_REPEAT" if selected else "V4I_STAGE1_SEED917"
        provenance = (
            "stage2_seed917_1931_selected500_ranking.tsv"
            if selected
            else "stage1_seed917_ranking.tsv"
        )
        out = {
            "schema_version": "pvrig_v6_scalar_teacher_v2_8",
            "candidate_id": candidate_id,
            "sequence_sha256": candidate["sequence_sha256"],
            "sequence": candidate["sequence"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "target_patch_id": candidate["target_patch_id"],
            "design_mode": candidate["design_mode"],
            "cdr1": candidate["cdr1_after"],
            "cdr2": candidate["cdr2_after"],
            "cdr3": candidate["cdr3_after"],
            "source_campaign": "V4I",
            "source_lane": candidate["source_lane"],
            "teacher_source": teacher_source,
            "teacher_reliability": reliability,
            "sample_weight": base_weight,
            "docking_evidence_tier": reliability,
            "development_reliability_tier": dev_tier,
            "development_reliability_weight": base_weight,
            "successful_seed_count_8X6B": label["successful_seed_count_8X6B"],
            "successful_seed_ids_8X6B": label["successful_seed_ids_8X6B"],
            "successful_seed_count_9E6Y": label["successful_seed_count_9E6Y"],
            "successful_seed_ids_9E6Y": label["successful_seed_ids_9E6Y"],
            "paired_successful_seed_count": str(paired_seed_count(label)),
            "seed_dispersion_max": label["seed_dispersion_max"],
            "uncertainty_observed": "1" if observed_uncertainty else "0",
            "ranking_release": label["ranking_release"],
            "label_update_provenance": provenance,
            "outer_fold": fold_by_parent[candidate["parent_framework_cluster"]],
            "R_8X6B": label[r8_key],
            "R_9E6Y": label[r9_key],
            "R_dual_min": label["R_dual_min"],
            "teacher_uncertainty": label["seed_dispersion_max"],
            "technical_reasons": label["technical_reasons"],
            "structure_feature_state": "REMOTE_MONOMER_AVAILABLE_FEATURES_NOT_MATERIALIZED",
            "contact_teacher_state": "CONTACT_TEACHER_NOT_EXTRACTED",
            "stage2_repeat_selected": "1" if selected else "0",
            "claim_boundary": contract["claim_boundary"],
        }
        v4i_rows.append(out)
        expanded_rows.append(out)

    if len(v4i_rows) != expected["v4i_scalar_valid_rows"]:
        raise ValueError(f"count_mismatch:v4i_scalar_valid_rows:{len(v4i_rows)}:{expected['v4i_scalar_valid_rows']}")
    if len(technical_rows) != expected["v4i_technical_incomplete_rows"]:
        raise ValueError(f"count_mismatch:v4i_technical_incomplete_rows:{len(technical_rows)}:{expected['v4i_technical_incomplete_rows']}")
    if len(expanded_rows) != expected["expanded_scalar_rows"]:
        raise ValueError(f"count_mismatch:expanded_scalar_rows:{len(expanded_rows)}:{expected['expanded_scalar_rows']}")

    all_ids = [row["candidate_id"] for row in expanded_rows]
    all_hashes = [row["sequence_sha256"] for row in expanded_rows]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("expanded_candidate_id_duplicate")
    if len(set(all_hashes)) != expected["expanded_unique_sequence_sha256"]:
        raise ValueError("expanded_sequence_sha_count_mismatch")
    if len({row["parent_framework_cluster"] for row in expanded_rows}) != expected["expanded_parent_clusters"]:
        raise ValueError("expanded_parent_count_mismatch")

    multi_seed = sum(row["teacher_reliability"] in {"MULTI_SEED", "DUAL_2_SEED", "DUAL_3_SEED"} for row in expanded_rows)
    single_seed = sum(row["teacher_reliability"] == "DUAL_1_SEED" for row in expanded_rows)
    if multi_seed != expected["expanded_multi_seed_rows"] or single_seed != expected["expanded_single_seed_rows"]:
        raise ValueError(f"expanded_seed_tier_count_mismatch:{multi_seed}:{single_seed}")

    expanded_rows.sort(key=lambda row: (row["source_campaign"], row["candidate_id"]))
    v4i_rows.sort(key=lambda row: row["candidate_id"])
    technical_rows.sort(key=lambda row: row["candidate_id"])
    stage2_ablation_rows = [
        row
        for row in expanded_rows
        if row["source_campaign"] != "V4I" or row["stage2_repeat_selected"] == "1"
    ]
    if len(stage2_ablation_rows) != expected["stage2_ablation_scalar_rows"]:
        raise ValueError(
            f"count_mismatch:stage2_ablation_scalar_rows:{len(stage2_ablation_rows)}:{expected['stage2_ablation_scalar_rows']}"
        )
    write_tsv(args.output_dir / "v4i_scalar_teacher1881_v2_8.tsv", v4i_rows, SCALAR_FIELDS)
    write_tsv(args.output_dir / "v6_scalar_teacher2007_stage2_ablation_v2_8.tsv", stage2_ablation_rows, SCALAR_FIELDS)
    write_tsv(args.output_dir / "v6_scalar_teacher3388_v2_8.tsv", expanded_rows, SCALAR_FIELDS)
    technical_fields = list(candidate_rows[0].keys()) + [f"stage1__{key}" for key in stage1_rows[0].keys()]
    write_tsv(args.output_dir / "v4i_technical_incomplete81_v2_8.tsv", technical_rows, technical_fields)

    outputs = {
        name: sha256_file(args.output_dir / name)
        for name in [
            "v4i_scalar_teacher1881_v2_8.tsv",
            "v6_scalar_teacher2007_stage2_ablation_v2_8.tsv",
            "v6_scalar_teacher3388_v2_8.tsv",
            "v4i_technical_incomplete81_v2_8.tsv",
        ]
    }
    receipt = {
        "schema_version": "pvrig_v2_8_expanded3388_materialization_receipt_v1",
        "status": "PASS",
        "claim_boundary": contract["claim_boundary"],
        "input_sha256": input_hashes,
        "output_sha256": outputs,
        "counts": {
            **observed_input_counts,
            "v4i_scalar_valid_rows": len(v4i_rows),
            "v4i_technical_incomplete_rows": len(technical_rows),
            "stage2_ablation_scalar_rows": len(stage2_ablation_rows),
            "expanded_scalar_rows": len(expanded_rows),
            "expanded_unique_sequence_sha256": len(set(all_hashes)),
            "expanded_parent_clusters": len({row["parent_framework_cluster"] for row in expanded_rows}),
            "expanded_multi_seed_rows": multi_seed,
            "expanded_single_seed_rows": single_seed,
            "receptor_specific_scalar_targets": len(expanded_rows) * 2,
        },
        "distributions": {
            "source_campaign": dict(sorted(Counter(row["source_campaign"] for row in expanded_rows).items())),
            "teacher_reliability": dict(sorted(Counter(row["teacher_reliability"] for row in expanded_rows).items())),
            "outer_fold": dict(sorted(Counter(row["outer_fold"] for row in expanded_rows).items())),
            "target_patch_id": dict(sorted(Counter(row["target_patch_id"] for row in expanded_rows).items())),
            "design_mode": dict(sorted(Counter(row["design_mode"] for row in expanded_rows).items())),
            "v4i_source_lane": dict(sorted(Counter(row["source_lane"] for row in v4i_rows).items())),
        },
        "R_dual_min_quantiles": {
            "old1507": quantiles([float(row["R_dual_min"]) for row in expanded_rows if row["source_campaign"] != "V4I"]),
            "v4i1881": quantiles([float(row["R_dual_min"]) for row in v4i_rows]),
            "expanded3388": quantiles([float(row["R_dual_min"]) for row in expanded_rows]),
        },
        "invariants": {
            "R_dual_exact_min": True,
            "cross_source_sequence_overlap": 0,
            "v4i_stage2_is_candidate_level_overlay_not_independent_rows": True,
            "technical_incomplete_imputed": False,
            "whole_parent_fold_binding_preserved": True,
            "new_v4i_parent_clusters": 0,
            "v4i_contact_teacher_available": False,
            "v4h_v4i_protocol_semantics_compatible": True,
            "protocol_core_hashes_equal": False,
        },
        "protocol_compatibility": {
            "status": protocol_compatibility["status"],
            "normalized_protocol_semantics_sha256": protocol_compatibility["normalized_protocol_semantics_sha256"],
            "audit_sha256": input_hashes["protocol_compatibility_audit"],
        },
    }
    receipt_path = args.output_dir / "MATERIALIZATION_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sha_lines = [f"{sha256_file(args.output_dir / name)}  {name}" for name in sorted(outputs)]
    sha_lines.append(f"{sha256_file(receipt_path)}  MATERIALIZATION_RECEIPT.json")
    (args.output_dir / "SHA256SUMS").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    here = Path(__file__).resolve().parents[1]
    surrogate_root = here.parent
    parser.add_argument("--contract", type=Path, default=here / "DATA_CONTRACT.json")
    parser.add_argument(
        "--old-teacher",
        type=Path,
        default=surrogate_root / "v2_4_fs_stack_prototype_v1_20260718/data_contract/materialized_v1/v6_supervised1507_v2_4.tsv",
    )
    phase2_root = here.parents[1]
    prepared = phase2_root / "prepared" / "pvrig_v4_i_round2_terminal_v1_20260719"
    parser.add_argument("--v4i-candidates", type=Path, default=prepared / "candidates.tsv")
    parser.add_argument("--v4i-stage1", type=Path, default=prepared / "stage1_seed917_ranking.tsv")
    parser.add_argument("--v4i-stage2", type=Path, default=prepared / "stage2_seed917_1931_selected500_ranking.tsv")
    parser.add_argument(
        "--protocol-compatibility",
        type=Path,
        default=surrogate_root
        / "v2_8_v4i_open3388_multicampaign_v1_20260719"
        / "PROTOCOL_SEMANTIC_COMPATIBILITY_AUDIT.json",
    )
    parser.add_argument("--output-dir", type=Path, default=here / "prepared")
    return parser.parse_args(argv)


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result, indent=2, sort_keys=True))
