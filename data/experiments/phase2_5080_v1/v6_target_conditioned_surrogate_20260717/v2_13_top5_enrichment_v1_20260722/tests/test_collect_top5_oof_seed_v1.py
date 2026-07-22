from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PKG = Path(__file__).resolve().parents[1]
LOCAL_PREPARED = PKG.parent / "v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared"
REMOTE_PREPARED = Path("/data1/qlyu/projects/pvrig_v2_12_clean_attention_inner_oof_stack_v1_20260722/prepared")
PREPARED = LOCAL_PREPARED if LOCAL_PREPARED.is_dir() else REMOTE_PREPARED


def load_module():
    path = PKG / "src/collect_top5_oof_seed_v1.py"
    spec = importlib.util.spec_from_file_location("v213_top5_seed_collector_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


class PhaseBSeedCollectorTests(unittest.TestCase):
    def test_seed917_exact_five_fold_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contracts_dir, runs = root / "contracts", root / "runs"
            contracts_dir.mkdir(); runs.mkdir()
            with (PREPARED / "train9849_teacher.tsv").open(newline="", encoding="utf-8") as handle:
                teacher_rows = list(csv.DictReader(handle, delimiter="\t"))
            by_id = {row["candidate_id"]: row for row in teacher_rows}
            with (PREPARED / "candidate_fold_assignment.tsv").open(newline="", encoding="utf-8") as handle:
                assignments = list(csv.DictReader(handle, delimiter="\t"))
            for fold in range(5):
                split = contracts_dir / f"fold_{fold}_split.json"
                split.write_bytes((PREPARED / split.name).read_bytes())
                contract = json.loads((PREPARED / f"fold_{fold}_contract.json").read_text())
                contract["task"] = {"fold_id": fold, "seed": 917}
                contract["split_manifest"] = {"path": str(split), "sha256": sha(split)}
                contract["phase_b_provenance"] = {"selected_variant": "L3"}
                (contracts_dir / f"seed_917_fold_{fold}_contract.json").write_text(json.dumps(contract))
                prediction_rows = []
                for assigned in (row for row in assignments if int(row["fold_id"]) == fold):
                    source = by_id[assigned["candidate_id"]]
                    r8, r9 = float(source["R_8X6B"]), float(source["R_9E6Y"])
                    prediction_rows.append({
                        "candidate_id": assigned["candidate_id"], "sequence_sha256": assigned["sequence_sha256"],
                        "parent_framework_cluster": assigned["parent_framework_cluster"], "fold_id": fold,
                        "seed": 917, "variant": "L3", "target_R_8X6B": r8, "target_R_9E6Y": r9,
                        "target_R_dual_min": min(r8, r9), "prediction_R_8X6B": r8,
                        "prediction_R_9E6Y": r9, "prediction_R_dual_min": min(r8, r9),
                    })
                prediction_path = runs / f"fold_{fold}" / MOD.RUNNER.PREDICTION_NAME
                write_tsv(prediction_path, prediction_rows)
                result = {
                    "status": "PASS_V2_13_TOP5_CLEAN_ATTENTION_FOLD_TRAINING", "fold_id": fold,
                    "seed": 917, "variant": "L3", "open_development_access_count": 0,
                    "frozen_test_access_count": 0,
                    "outputs": {MOD.RUNNER.PREDICTION_NAME: sha(prediction_path)},
                }
                (prediction_path.parent / MOD.RUNNER.RESULT_NAME).write_text(json.dumps(result))
            output = root / "nested/aggregate"
            receipt = MOD.collect(
                PREPARED / "train9849_teacher.tsv", PREPARED / "candidate_fold_assignment.tsv",
                contracts_dir, runs, output, "L3", 917,
            )
            self.assertEqual(receipt["counts"]["seed"], 917)
            self.assertTrue((output / "TOP5_L3_SEED917_TRAIN9849_OOF_PREDICTIONS.tsv").is_file())


if __name__ == "__main__":
    unittest.main()
