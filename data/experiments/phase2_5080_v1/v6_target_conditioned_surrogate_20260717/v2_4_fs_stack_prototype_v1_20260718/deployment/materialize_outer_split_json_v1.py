#!/usr/bin/env python3
"""Convert canonical parent-balanced outer TSV into five trainer JSON manifests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMA = "pvrig_v2_4_open_base_split_manifest_v1"


class SplitMaterializationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SplitMaterializationError(message)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parent_sha(parents: set[str]) -> str:
    return hashlib.sha256("".join(f"{parent}\n" for parent in sorted(parents)).encode()).hexdigest()


def run(input_tsv: Path, training_tsv: Path, output_dir: Path, fixed_epochs: int) -> dict[str, Any]:
    require(not output_dir.exists() or not any(output_dir.iterdir()), "nonempty_output_dir")
    require(fixed_epochs > 0, "fixed_epochs")
    with training_tsv.open(newline="", encoding="utf-8") as handle:
        training = list(csv.DictReader(handle, delimiter="\t"))
    candidate_parent = {row["candidate_id"]: row["parent_framework_cluster"] for row in training}
    require(len(candidate_parent) == len(training) == 1507, "training_candidate_closure")
    with input_tsv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    by_fold: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_fold[int(row["outer_fold"])].append(row)
    require(set(by_fold) == set(range(5)), "outer_fold_closure")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for fold in range(5):
        fold_rows = by_fold[fold]
        require(len(fold_rows) == 1507, f"fold_candidate_count:{fold}")
        require({row["candidate_id"] for row in fold_rows} == set(candidate_parent), f"fold_candidate_closure:{fold}")
        require(all(candidate_parent[row["candidate_id"]] == row["parent_framework_cluster"] for row in fold_rows), f"fold_parent_identity:{fold}")
        train_parents = {row["parent_framework_cluster"] for row in fold_rows if row["candidate_role"] == "train"}
        score_parents = {row["parent_framework_cluster"] for row in fold_rows if row["candidate_role"] == "score"}
        require(train_parents and score_parents and train_parents.isdisjoint(score_parents), f"parent_isolation:{fold}")
        require(train_parents | score_parents == set(candidate_parent.values()), f"parent_closure:{fold}")
        train_digest, score_digest = parent_sha(train_parents), parent_sha(score_parents)
        require({row["train_parent_set_sha256"] for row in fold_rows} == {train_digest}, f"train_parent_sha:{fold}")
        require({row["score_parent_set_sha256"] for row in fold_rows} == {score_digest}, f"score_parent_sha:{fold}")
        payload = {
            "schema_version": SCHEMA,
            "split_id": f"outer_development_{fold}",
            "outer_fold": fold,
            "train_parents": sorted(train_parents),
            "score_parents": sorted(score_parents),
            "fixed_epochs": fixed_epochs,
            "open_only": True,
            "v4_f_test32_access_count": 0,
            "train_parent_set_sha256": train_digest,
            "score_parent_set_sha256": score_digest,
            "source_outer_manifest_sha256": sha256_file(input_tsv),
            "training_tsv_sha256": sha256_file(training_tsv),
        }
        path = output_dir / f"outer_fold_{fold}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outputs[str(fold)] = {"path": str(path), "sha256": sha256_file(path), "train_parents": len(train_parents), "score_parents": len(score_parents)}
    receipt = {
        "schema_version": "pvrig_v2_4_outer_split_json_materialization_receipt_v1",
        "status": "PASS_FIVE_PARENT_ISOLATED_OUTER_SPLIT_JSON_MANIFESTS",
        "input_outer_manifest": {"path": str(input_tsv), "sha256": sha256_file(input_tsv), "rows": len(rows)},
        "training_tsv": {"path": str(training_tsv), "sha256": sha256_file(training_tsv), "rows": len(training)},
        "fixed_epochs": fixed_epochs,
        "outputs": outputs,
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
    }
    receipt_path = output_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-tsv", type=Path, required=True)
    parser.add_argument("--training-tsv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixed-epochs", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run(args.input_tsv, args.training_tsv, args.output_dir, args.fixed_epochs), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
