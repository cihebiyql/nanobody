#!/usr/bin/env python3
"""Prepare the train9849-only teacher, five whole-parent folds, and frozen contracts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from sklearn.model_selection import GroupKFold


SCHEMA = "pvrig_v2_12_clean_attention_inner_oof_prepare_v1"
CONTRACT_SCHEMA = "pvrig_v2_12_clean_attention_inner_oof_fold_contract_v1"
LANE = "B_CLEAN_TARGET_ATTENTION"
SEED = 43


class PrepareError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PrepareError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_set_hash(values: Iterable[str]) -> str:
    return hashlib.sha256("".join(f"{value}\n" for value in sorted(set(values))).encode()).hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"tsv_invalid:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = list(reader.fieldnames or ()), [dict(row) for row in reader]
    require(fields and rows, f"tsv_empty:{path}")
    return fields, rows


def write_tsv(path: Path, fields: Sequence[str], rows: Sequence[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare(
    source_table: Path,
    source_split: Path,
    output_dir: Path,
    runtime_root: Path,
) -> dict:
    require(not output_dir.exists(), f"output_exists:{output_dir}")
    source_payload = json.loads(source_split.read_text(encoding="utf-8"))
    require(source_payload.get("expected_train_rows") == 9849, "source_train_count_contract")
    require(source_payload.get("expected_score_rows") == 795, "source_score_count_contract")
    fields, all_rows = read_tsv(source_table)
    require(len(all_rows) == 10644, "source_total_rows")
    train_parents = set(source_payload["train_parents"])
    open_development_parents = set(source_payload["score_parents"])
    frozen_test_parents = set(source_payload["frozen_test_parents"])
    require(train_parents.isdisjoint(open_development_parents | frozen_test_parents), "source_parent_overlap")
    rows = [row for row in all_rows if row["parent_framework_cluster"] in train_parents]
    require(len(rows) == 9849, f"train9849_count:{len(rows)}")
    require("cdr3" in fields, "cdr3_field_missing")
    require({row["parent_framework_cluster"] for row in rows} == train_parents, "train_parent_closure")
    require(not any(row["parent_framework_cluster"] in open_development_parents for row in rows), "open_development_row_present")

    output_dir.mkdir(parents=True)
    table_path = output_dir / "train9849_teacher.tsv"
    write_tsv(table_path, fields, rows)
    table_sha = sha256_file(table_path)
    groups = np.asarray([row["parent_framework_cluster"] for row in rows])
    indices = np.arange(len(rows))
    splitter = GroupKFold(n_splits=5)
    folds = []
    seen_score_parents: set[str] = set()
    seen_score_candidates: set[str] = set()
    parent_fold_rows: list[dict[str, str]] = []
    candidate_fold_rows: list[dict[str, str]] = []

    for fold_id, (fit, score) in enumerate(splitter.split(indices, groups=groups)):
        fit_parents = sorted(set(groups[fit]))
        score_parents = sorted(set(groups[score]))
        require(set(fit_parents).isdisjoint(score_parents), f"fold_parent_overlap:{fold_id}")
        require(not (set(score_parents) & seen_score_parents), f"fold_score_parent_repeat:{fold_id}")
        score_candidates = {rows[index]["candidate_id"] for index in score}
        fit_cdr3 = {rows[index]["cdr3"].strip().upper() for index in fit}
        score_cdr3 = {rows[index]["cdr3"].strip().upper() for index in score}
        shared_exact_cdr3 = fit_cdr3 & score_cdr3
        score_rows_with_shared_exact_cdr3 = sum(
            rows[index]["cdr3"].strip().upper() in shared_exact_cdr3 for index in score
        )
        require(not (score_candidates & seen_score_candidates), f"fold_score_candidate_repeat:{fold_id}")
        seen_score_parents.update(score_parents)
        seen_score_candidates.update(score_candidates)
        parent_fold_rows.extend({"parent_framework_cluster": parent, "fold_id": str(fold_id)} for parent in score_parents)
        candidate_fold_rows.extend({
            "candidate_id": rows[index]["candidate_id"],
            "sequence_sha256": rows[index]["sequence_sha256"],
            "parent_framework_cluster": rows[index]["parent_framework_cluster"],
            "fold_id": str(fold_id),
        } for index in score)
        split_payload = {
            "schema_version": "pvrig_v2_12_inner_whole_parent_fold_v1",
            "split_id": f"canonical_train9849_groupkfold5_fold{fold_id}",
            "fold_id": fold_id,
            "train_parents": fit_parents,
            "score_parents": score_parents,
            "frozen_test_parents": sorted(frozen_test_parents | open_development_parents),
            "train_parent_set_sha256": stable_set_hash(fit_parents),
            "score_parent_set_sha256": stable_set_hash(score_parents),
            "excluded_open_development_parent_set_sha256": stable_set_hash(open_development_parents),
            "train_rows": int(len(fit)),
            "score_rows": int(len(score)),
            "open_development_access_count": 0,
            "frozen_test_access_count": 0,
            "generalization_boundary": "WHOLE_PARENT_OOF_ONLY_NOT_CDR3_OR_SEQUENCE_FAMILY_OOD",
            "cross_fold_exact_cdr3_audit": {
                "shared_exact_cdr3_count": len(shared_exact_cdr3),
                "score_rows_with_shared_exact_cdr3": int(score_rows_with_shared_exact_cdr3),
            },
        }
        split_path = output_dir / f"fold_{fold_id}_split.json"
        split_path.write_text(json.dumps(split_payload, indent=2, sort_keys=True) + "\n")
        contract = {
            "schema_version": CONTRACT_SCHEMA,
            "status": "FROZEN_INNER_OOF_PRE_LAUNCH",
            "lane": LANE,
            "contact_supervision_enabled": False,
            "task": {"fold_id": fold_id, "seed": SEED},
            "expected_counts": {"total": 9849, "train": int(len(fit)), "score": int(len(score))},
            "training_table": {"path": str(runtime_root / "prepared/train9849_teacher.tsv"), "sha256": table_sha},
            "split_manifest": {"path": str(runtime_root / f"prepared/fold_{fold_id}_split.json"), "sha256": sha256_file(split_path)},
            "fixed_hyperparameters": {
                "epochs": 8, "batch_size": 8, "gradient_accumulation": 4, "precision": "bf16",
                "learning_rate": 0.0001, "weight_decay": 0.02, "graph_hidden_dim": 128,
                "dropout": 0.25, "receptor_weight": 1.0, "dual_weight": 0.5,
                "huber_beta": 0.03, "softmin_tau": 0.02,
            },
            "fixed_target_graph": {
                "receipt": {
                    "path": "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_receipt_v2.json",
                    "sha256": "b1823387b70375517b65848d873ff0e875396125ca5882ea384fabfcbd8880a9",
                },
                "torch_artifact": {
                    "path": "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt",
                    "sha256": "59461f9d48e5995acd902ba8524caad5c779a3c8b54a5deee121f9c3be6adfbc",
                },
            },
            "ortho_model": {
                "path": "/data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/model/residue_model_v2_5_ortho.py",
                "sha256": "26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521",
            },
            "ortho_trainer": {
                "path": "/data1/qlyu/projects/pvrig_v2_5_ortho_formal_nested_package_v1_3_20260718/node1_bundle/trainer/train_v2_5_ortho_heads.py",
                "sha256": "af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0",
            },
            "neural_input_allowlist": [
                "input_ids", "attention_mask", "residue_mask", "vhh_aa_index", "vhh_region_index",
                "vhh_confidence", "vhh_edge_index", "vhh_edge_features", "target_graphs",
            ],
            "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
            "generalization_boundary": "WHOLE_PARENT_OOF_ONLY_NOT_CDR3_OR_SEQUENCE_FAMILY_OOD",
        }
        contract_path = output_dir / f"fold_{fold_id}_contract.json"
        contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
        folds.append({
            "fold_id": fold_id,
            "train_rows": int(len(fit)), "score_rows": int(len(score)),
            "train_parents": len(fit_parents), "score_parents": len(score_parents),
            "split_sha256": sha256_file(split_path), "contract_sha256": sha256_file(contract_path),
            "shared_exact_cdr3_count": len(shared_exact_cdr3),
            "score_rows_with_shared_exact_cdr3": int(score_rows_with_shared_exact_cdr3),
        })

    require(seen_score_parents == train_parents, "five_fold_parent_exact_closure")
    require(len(seen_score_candidates) == 9849, "five_fold_candidate_exact_closure")
    parent_fold_path = output_dir / "parent_fold_assignment.tsv"
    candidate_fold_path = output_dir / "candidate_fold_assignment.tsv"
    write_tsv(parent_fold_path, ("parent_framework_cluster", "fold_id"), sorted(parent_fold_rows, key=lambda row: row["parent_framework_cluster"]))
    write_tsv(candidate_fold_path, ("candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id"), candidate_fold_rows)
    manifest = {
        "schema_version": SCHEMA,
        "status": "PASS_TRAIN9849_FIVE_FOLD_INNER_OOF_PREPARED",
        "source": {
            "canonical_table_sha256": sha256_file(source_table),
            "canonical_split_sha256": sha256_file(source_split),
        },
        "outputs": {
            "train9849_teacher.tsv": table_sha,
            "parent_fold_assignment.tsv": sha256_file(parent_fold_path),
            "candidate_fold_assignment.tsv": sha256_file(candidate_fold_path),
        },
        "counts": {"rows": 9849, "parents": 54, "folds": 5, "open_development_rows": 0, "frozen_test_rows": 0},
        "generalization_boundary": "WHOLE_PARENT_OOF_ONLY_NOT_CDR3_OR_SEQUENCE_FAMILY_OOD",
        "folds": folds,
    }
    manifest_path = output_dir / "OOF_PREPARE_RECEIPT.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-table", type=Path, required=True)
    parser.add_argument("--source-split", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = prepare(args.source_table, args.source_split, args.output_dir, args.runtime_root)
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
