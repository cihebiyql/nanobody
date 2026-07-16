#!/usr/bin/env python3
"""Freeze an untouched parent-cluster holdout for the next docking-surrogate round."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "phase2_v4_f_prospective_holdout_v1"
EXPECTED_POOL_SHA256 = "a92da7c939bf008ffaf7f3a305871477f74466d64f3489e9941c34a61a620e07"
EXPECTED_V4D_SPLIT_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_POOL_ROWS = 7087
HOLDOUT_CLUSTER_COUNT = 4
ROWS_PER_STRATUM = 4
SELECTION_SEED = "phase2_v4_f_prospective_holdout_20260716"
MODEL_SPLIT = "PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT"
PATCHES = ("A_CENTER", "B_LOWER", "C_CROSS")
MODES = ("H3", "H1H3")
OUTPUT_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "sequence",
    "parent_id",
    "parent_framework_cluster",
    "design_method",
    "design_mode",
    "target_patch_id",
    "cdr1",
    "cdr2",
    "cdr3",
    "cdr3_length",
    "model_split",
    "selection_stratum",
    "full_qc_and_docking_policy",
    "claim_boundary",
)
CLAIM_BOUNDARY = (
    "Prospectively frozen sequence panel for a future fixed-PVRIG computational "
    "docking-surrogate evaluation; not binding, affinity, competition, Docking Gold, "
    "or experimental blocking truth."
)


class HoldoutFreezeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def read_table(path: Path, delimiter: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def require_fields(rows: Iterable[dict[str, str]], fields: set[str], label: str) -> None:
    rows = list(rows)
    if not rows:
        raise HoldoutFreezeError(f"empty_{label}")
    missing = fields - set(rows[0])
    if missing:
        raise HoldoutFreezeError(f"{label}_missing_fields:{','.join(sorted(missing))}")


def validate_pool(rows: list[dict[str, str]], expected_rows: int = EXPECTED_POOL_ROWS) -> None:
    required = {
        "candidate_id",
        "vhh_sequence",
        "sequence_sha256",
        "parent_id",
        "parent_framework_cluster",
        "design_method",
        "design_mode",
        "target_patch_id",
        "cdr1_after",
        "cdr2_after",
        "cdr3_after",
        "cdr3_length",
    }
    require_fields(rows, required, "candidate_pool")
    if len(rows) != expected_rows:
        raise HoldoutFreezeError(f"candidate_pool_row_count:{len(rows)}")
    ids = [row["candidate_id"] for row in rows]
    hashes = [row["sequence_sha256"] for row in rows]
    if len(set(ids)) != len(ids) or len(set(hashes)) != len(hashes):
        raise HoldoutFreezeError("candidate_pool_duplicate_id_or_sequence")
    for row in rows:
        blank = sorted(field for field in required if not str(row.get(field, "")).strip())
        if blank:
            raise HoldoutFreezeError(
                f"candidate_pool_blank_fields:{row.get('candidate_id','MISSING')}:{','.join(blank)}"
            )
        sequence = row["vhh_sequence"].strip().upper()
        if hashlib.sha256(sequence.encode("utf-8")).hexdigest() != row["sequence_sha256"]:
            raise HoldoutFreezeError(f"sequence_hash_mismatch:{row['candidate_id']}")
        if row["design_mode"] not in MODES or row["target_patch_id"] not in PATCHES:
            raise HoldoutFreezeError(f"unexpected_design_stratum:{row['candidate_id']}")


def select_clusters(pool_rows: list[dict[str, str]], v4d_rows: list[dict[str, str]]) -> list[str]:
    pool_clusters = {row["parent_framework_cluster"] for row in pool_rows}
    v4d_clusters = {row["parent_framework_cluster"] for row in v4d_rows}
    eligible = sorted(pool_clusters - v4d_clusters)
    if len(eligible) < HOLDOUT_CLUSTER_COUNT:
        raise HoldoutFreezeError("insufficient_untouched_parent_clusters")
    return sorted(
        eligible,
        key=lambda cluster: stable_hash(SELECTION_SEED, "cluster", cluster),
    )[:HOLDOUT_CLUSTER_COUNT]


def select_rows(
    pool_rows: list[dict[str, str]], selected_clusters: Iterable[str]
) -> list[dict[str, str]]:
    by_stratum: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    selected_cluster_set = set(selected_clusters)
    for row in pool_rows:
        cluster = row["parent_framework_cluster"]
        if cluster in selected_cluster_set:
            by_stratum[(cluster, row["target_patch_id"], row["design_mode"])].append(row)

    output: list[dict[str, str]] = []
    for cluster in sorted(selected_cluster_set):
        for patch in PATCHES:
            for mode in MODES:
                key = (cluster, patch, mode)
                choices = sorted(
                    by_stratum.get(key, []),
                    key=lambda row: stable_hash(
                        SELECTION_SEED,
                        "candidate",
                        cluster,
                        patch,
                        mode,
                        row["candidate_id"],
                        row["sequence_sha256"],
                    ),
                )
                if len(choices) < ROWS_PER_STRATUM:
                    raise HoldoutFreezeError(
                        f"insufficient_stratum_rows:{cluster}:{patch}:{mode}:{len(choices)}"
                    )
                for source in choices[:ROWS_PER_STRATUM]:
                    output.append(
                        {
                            "candidate_id": source["candidate_id"],
                            "sequence_sha256": source["sequence_sha256"],
                            "sequence": source["vhh_sequence"],
                            "parent_id": source["parent_id"],
                            "parent_framework_cluster": cluster,
                            "design_method": source["design_method"],
                            "design_mode": mode,
                            "target_patch_id": patch,
                            "cdr1": source["cdr1_after"],
                            "cdr2": source["cdr2_after"],
                            "cdr3": source["cdr3_after"],
                            "cdr3_length": source["cdr3_length"],
                            "model_split": MODEL_SPLIT,
                            "selection_stratum": f"{cluster}|{patch}|{mode}",
                            "full_qc_and_docking_policy": (
                                "run_full_qc_on_all_96_then_dock_every_full_qc_hard_pass;"
                                "no_model_score_reselection"
                            ),
                            "claim_boundary": CLAIM_BOUNDARY,
                        }
                    )
    output.sort(key=lambda row: row["candidate_id"])
    return output


def validate_output(
    rows: list[dict[str, str]], selected_clusters: list[str], v4d_rows: list[dict[str, str]]
) -> dict[str, Any]:
    expected = HOLDOUT_CLUSTER_COUNT * len(PATCHES) * len(MODES) * ROWS_PER_STRATUM
    if len(rows) != expected:
        raise HoldoutFreezeError(f"holdout_row_count:{len(rows)}")
    if len({row["candidate_id"] for row in rows}) != expected:
        raise HoldoutFreezeError("holdout_candidate_ids_not_unique")
    if len({row["sequence_sha256"] for row in rows}) != expected:
        raise HoldoutFreezeError("holdout_sequences_not_unique")
    v4d_ids = {row["candidate_id"] for row in v4d_rows}
    v4d_hashes = {row["sequence_sha256"] for row in v4d_rows}
    v4d_clusters = {row["parent_framework_cluster"] for row in v4d_rows}
    v4d_parents = {row.get("parent_id", "") for row in v4d_rows if row.get("parent_id")}
    if v4d_ids & {row["candidate_id"] for row in rows}:
        raise HoldoutFreezeError("holdout_candidate_overlap_with_v4d")
    if v4d_hashes & {row["sequence_sha256"] for row in rows}:
        raise HoldoutFreezeError("holdout_sequence_overlap_with_v4d")
    if v4d_clusters & {row["parent_framework_cluster"] for row in rows}:
        raise HoldoutFreezeError("holdout_parent_cluster_overlap_with_v4d")
    if v4d_parents & {row["parent_id"] for row in rows}:
        raise HoldoutFreezeError("holdout_parent_id_overlap_with_v4d")
    cdr_overlap = {
        field: len(
            {row[field] for row in rows}
            & {source.get(field, "") for source in v4d_rows if source.get(field)}
        )
        for field in ("cdr1", "cdr2", "cdr3")
    }
    if any(cdr_overlap.values()):
        raise HoldoutFreezeError(f"holdout_exact_cdr_overlap_with_v4d:{cdr_overlap}")
    cluster_counts = Counter(row["parent_framework_cluster"] for row in rows)
    stratum_counts = Counter(row["selection_stratum"] for row in rows)
    if set(cluster_counts) != set(selected_clusters) or set(cluster_counts.values()) != {24}:
        raise HoldoutFreezeError("holdout_cluster_balance_failed")
    if set(stratum_counts.values()) != {ROWS_PER_STRATUM} or len(stratum_counts) != 24:
        raise HoldoutFreezeError("holdout_stratum_balance_failed")
    return {
        "row_count": len(rows),
        "cluster_counts": dict(sorted(cluster_counts.items())),
        "patch_counts": dict(sorted(Counter(row["target_patch_id"] for row in rows).items())),
        "mode_counts": dict(sorted(Counter(row["design_mode"] for row in rows).items())),
        "stratum_count": len(stratum_counts),
        "candidate_overlap_with_v4d": 0,
        "sequence_overlap_with_v4d": 0,
        "parent_cluster_overlap_with_v4d": 0,
        "parent_id_overlap_with_v4d": 0,
        "exact_cdr_overlap_with_v4d": cdr_overlap,
        "cdr3_length_counts": dict(
            sorted(Counter(int(row["cdr3_length"]) for row in rows).items())
        ),
    }


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run(
    pool_path: Path,
    v4d_split_path: Path,
    output_dir: Path,
    *,
    enforce_production_hashes: bool = True,
    expected_pool_rows: int = EXPECTED_POOL_ROWS,
) -> dict[str, Any]:
    if enforce_production_hashes:
        if sha256_file(pool_path) != EXPECTED_POOL_SHA256:
            raise HoldoutFreezeError("candidate_pool_sha256_mismatch")
        if sha256_file(v4d_split_path) != EXPECTED_V4D_SPLIT_SHA256:
            raise HoldoutFreezeError("v4d_split_sha256_mismatch")
    pool_rows = read_table(pool_path, ",")
    v4d_rows = read_table(v4d_split_path, "\t")
    validate_pool(pool_rows, expected_pool_rows)
    require_fields(
        v4d_rows,
        {"candidate_id", "sequence_sha256", "parent_framework_cluster"},
        "v4d_split",
    )
    selected_clusters = select_clusters(pool_rows, v4d_rows)
    selected_rows = select_rows(pool_rows, selected_clusters)
    checks = validate_output(selected_rows, selected_clusters, v4d_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "prospective_holdout96_manifest.tsv"
    audit_path = output_dir / "prospective_holdout96_audit.json"
    receipt_path = output_dir / "prospective_holdout96_receipt.json"
    write_tsv(manifest_path, selected_rows)
    configuration = {
        "schema_version": SCHEMA_VERSION,
        "selection_seed": SELECTION_SEED,
        "holdout_cluster_count": HOLDOUT_CLUSTER_COUNT,
        "rows_per_stratum": ROWS_PER_STRATUM,
        "patches": list(PATCHES),
        "design_modes": list(MODES),
        "model_split": MODEL_SPLIT,
        "expected_pool_rows": expected_pool_rows,
        "production_hash_enforcement": enforce_production_hashes,
    }
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN"
            if enforce_production_hashes
            else "TEST_ONLY_PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN"
        ),
        "execution_mode": "production" if enforce_production_hashes else "test_only",
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__)),
        },
        "configuration": configuration,
        "configuration_sha256": sha256_json(configuration),
        "selection_seed": SELECTION_SEED,
        "selection_policy": (
            "hash-rank four parent clusters absent from V4-D, then hash-rank four "
            "candidates per parent-cluster x target-patch x design-mode stratum"
        ),
        "selected_parent_clusters": selected_clusters,
        "inputs": {
            "candidate_pool": {
                "path": str(pool_path.resolve()),
                "sha256": sha256_file(pool_path),
                "row_count": len(pool_rows),
            },
            "v4d_split": {
                "path": str(v4d_split_path.resolve()),
                "sha256": sha256_file(v4d_split_path),
                "row_count": len(v4d_rows),
            },
        },
        "checks": checks,
        "output": {
            "path": str(manifest_path.resolve()),
            "sha256": sha256_file(manifest_path),
            "row_count": len(selected_rows),
        },
        "future_release_policy": {
            "full_qc": "run on all 96 without model-score selection",
            "docking": "dock every Full-QC hard-pass candidate",
            "labels": "do not compute or open before model/config/test predictions are frozen",
            "failed_full_qc": "report attrition; never replace from outside this frozen panel",
        },
        "evaluation_note": (
            "The panel is balanced by parent, patch, and design mode but not by CDR3 length; "
            "report metrics per parent and CDR3-length stratum."
        ),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit["audit_payload_sha256"] = sha256_json(audit)
    write_json(audit_path, audit)
    receipt = {
        "schema_version": "phase2_v4_f_prospective_holdout_receipt_v1",
        "status": "PASS_COMPLETE_HASH_CLOSURE" if enforce_production_hashes else "TEST_ONLY_PASS_HASH_CLOSURE",
        "execution_mode": audit["execution_mode"],
        "implementation_sha256": audit["implementation"]["sha256"],
        "configuration_sha256": audit["configuration_sha256"],
        "candidate_pool_sha256": audit["inputs"]["candidate_pool"]["sha256"],
        "v4d_split_sha256": audit["inputs"]["v4d_split"]["sha256"],
        "manifest_sha256": sha256_file(manifest_path),
        "audit_file_sha256": sha256_file(audit_path),
        "audit_payload_sha256": audit["audit_payload_sha256"],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(receipt_path, receipt)
    return audit


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=(
            root
            / "prepared/pvrig_teacher_formal_v1_candidates/fast_gate/"
            "fast_gate_formal_eligible_v1.csv"
        ),
    )
    parser.add_argument(
        "--v4d-split",
        type=Path,
        default=root / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=root / "data_splits/pvrig_v4_f"
    )
    args = parser.parse_args(argv)
    result = run(args.candidate_pool, args.v4d_split, args.output_dir)
    print(
        json.dumps(
            {
                "status": result["status"],
                "clusters": result["selected_parent_clusters"],
                "rows": result["output"]["row_count"],
                "manifest": result["output"]["path"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
