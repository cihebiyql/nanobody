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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


COLLECTOR = load_module("v214_listwise_collector_test", PKG / "src/collect_v214_listwise_oof_v1.py")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class Top5CollectorTests(unittest.TestCase):
    def test_collects_exact_variant_five_fold_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contracts, runs = root / "contracts", root / "runs"
            contracts.mkdir(); runs.mkdir()
            with (PREPARED / "train9849_teacher.tsv").open(newline="", encoding="utf-8") as handle:
                teacher = list(csv.DictReader(handle, delimiter="\t"))
            by_id = {row["candidate_id"]: row for row in teacher}
            with (PREPARED / "candidate_fold_assignment.tsv").open(newline="", encoding="utf-8") as handle:
                assignments = list(csv.DictReader(handle, delimiter="\t"))
            for fold in range(5):
                split = contracts / f"fold_{fold}_split.json"
                split.write_bytes((PREPARED / split.name).read_bytes())
                contract = json.loads((PREPARED / f"fold_{fold}_contract.json").read_text())
                contract["split_manifest"] = {"path": str(split), "sha256": sha256_file(split)}
                (contracts / f"fold_{fold}_contract.json").write_text(json.dumps(contract))
                prediction_rows = []
                for assigned in (row for row in assignments if int(row["fold_id"]) == fold):
                    source = by_id[assigned["candidate_id"]]
                    r8, r9 = float(source["R_8X6B"]), float(source["R_9E6Y"])
                    prediction_rows.append({
                        "candidate_id": assigned["candidate_id"],
                        "sequence_sha256": assigned["sequence_sha256"],
                        "parent_framework_cluster": assigned["parent_framework_cluster"],
                        "fold_id": str(fold), "seed": "43", "variant": "N2",
                        "target_R_8X6B": repr(r8), "target_R_9E6Y": repr(r9),
                        "target_R_dual_min": repr(min(r8, r9)),
                        "prediction_R_8X6B": repr(r8), "prediction_R_9E6Y": repr(r9),
                        "prediction_R_dual_min": repr(min(r8, r9)),
                    })
                fold_dir = runs / f"fold_{fold}"
                prediction_path = fold_dir / COLLECTOR.RUNNER.PREDICTION_NAME
                write_tsv(prediction_path, prediction_rows)
                result = {
                    "status": "PASS_V2_14_LISTWISE_TOP5_FOLD",
                    "fold_id": fold, "seed": 43, "variant": "N2",
                    "open_development_access_count": 0, "frozen_test_access_count": 0,
                    "outputs": {COLLECTOR.RUNNER.PREDICTION_NAME: sha256_file(prediction_path)},
                }
                (fold_dir / COLLECTOR.RUNNER.RESULT_NAME).write_text(json.dumps(result))
            output = root / "aggregate"
            receipt = COLLECTOR.collect(
                PREPARED / "train9849_teacher.tsv",
                PREPARED / "candidate_fold_assignment.tsv",
                contracts, runs, output, "N2",
            )
            self.assertEqual(receipt["status"], "PASS_V2_14_LISTWISE_TRAIN9849_WHOLE_PARENT_OOF")
            self.assertEqual(receipt["variant"], "N2")
            output_path = output / "V214_N2_TRAIN9849_OOF_PREDICTIONS.tsv"
            with output_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 9849)
            self.assertEqual({row["variant"] for row in rows}, {"N2"})


if __name__ == "__main__":
    unittest.main()
