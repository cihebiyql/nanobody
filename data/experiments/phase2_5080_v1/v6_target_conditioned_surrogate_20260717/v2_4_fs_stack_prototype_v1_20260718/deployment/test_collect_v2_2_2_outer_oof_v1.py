from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from . import collect_v2_2_2_outer_oof_v1 as mod


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact(path: Path) -> dict:
    return {"node1_path": str(path), "sha256": mod.sha256_file(path), "size_bytes": path.stat().st_size}


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.bundle = root / "bundle"
        self.runtime = root / "runtime"
        self.output = root / "post_outer"
        self.bundle.mkdir(); self.runtime.mkdir()
        self.manifest_path = self.bundle / "V2_4_NODE1_READY_MANIFEST_V2_2_2.json"
        self.freeze_path = self.bundle / "IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_2.json"
        self.training_path = self.bundle / "training.tsv"
        self.formula_path = self.bundle / "contact_formula.json"
        self.calibration_path = self.bundle / "CALIBRATION_RECEIPT.json"
        self.split_paths = [self.bundle / f"outer_fold_{fold}.json" for fold in mod.FOLDS]
        self.training = self._write_training()
        self.formula_path.write_text('{"formula":"fixed"}\n', encoding="utf-8")
        write_json(self.calibration_path, {"status": "PASS"})
        artifacts = {
            "training_tsv": artifact(self.training_path),
            "contact_formula": artifact(self.formula_path),
            "calibration_receipt": artifact(self.calibration_path),
        }
        parents = [f"P{index:02d}" for index in range(10)]
        for fold, path in enumerate(self.split_paths):
            score = parents[2 * fold:2 * fold + 2]
            train = [parent for parent in parents if parent not in score]
            split = {
                "schema_version": "pvrig_v2_4_open_base_split_manifest_v1",
                "outer_fold": fold,
                "split_id": f"outer_development_{fold}",
                "open_only": True,
                "fixed_epochs": 8,
                "train_parents": train,
                "score_parents": score,
                "train_parent_set_sha256": f"train_sha_{fold}",
                "score_parent_set_sha256": f"score_sha_{fold}",
                "training_tsv_sha256": mod.sha256_file(self.training_path),
                "source_outer_manifest_sha256": "f" * 64,
                "v4_f_test32_access_count": 0,
            }
            write_json(path, split)
            artifacts[f"outer_split_{fold}"] = artifact(path)
        self.manifest = {
            "schema_version": mod.MANIFEST_SCHEMA,
            "status": mod.READY_STATUS,
            "runtime_root": str(self.runtime),
            "claim_boundary": mod.CLAIM_BOUNDARY,
            "trainer_result_claim_boundary": mod.TRAINER_RESULT_CLAIM_BOUNDARY,
            "technical_supersession": {"bundle_revision": mod.BUNDLE_REVISION},
            "sealed_evaluation_access_count": 0,
            "prediction_metrics_access_count": 0,
            "expected_training_counts": {"rows": 10},
            "calibration_contract": {"frozen_lane_contact_weights": mod.EXPECTED_WEIGHTS},
            "artifacts": artifacts,
        }
        write_json(self.manifest_path, self.manifest)
        self.freeze = {
            "schema_version": mod.FREEZE_SCHEMA,
            "status": mod.FREEZE_STATUS,
            "manifest_sha256": mod.sha256_file(self.manifest_path),
            "formal_artifact_sha256": {key: value["sha256"] for key, value in artifacts.items()},
            "claim_boundary": mod.CLAIM_BOUNDARY,
            "trainer_result_claim_boundary": mod.TRAINER_RESULT_CLAIM_BOUNDARY,
            "bundle_revision": mod.BUNDLE_REVISION,
            "frozen_lane_contact_weights": mod.EXPECTED_WEIGHTS,
            "sealed_evaluation_access_count": 0,
            "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0,
        }
        write_json(self.freeze_path, self.freeze)
        status = self.runtime / "status"
        status.mkdir()
        self.smoke_path = status / "SMOKE_RECEIPT.json"
        write_json(self.smoke_path, {"status": "PASS_SMOKE"})
        self._write_all_results()
        self.outer_path = status / "OUTER_DEVELOPMENT_RECEIPT.json"
        self._write_outer_receipt()

    def _write_training(self):
        fields = ["candidate_id", "teacher_source", "parent_framework_cluster", "outer_fold", "R_8X6B", "R_9E6Y", "R_dual_min"]
        rows = []
        with self.training_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index in range(10):
                r8 = 0.20 + 0.02 * index
                r9 = 0.25 + 0.015 * index
                row = {
                    "candidate_id": f"C{index:02d}",
                    "teacher_source": "V4D_OPEN_MULTI_SEED" if index < 5 else "V4H_ADAPTIVE_SEED_RANKING",
                    "parent_framework_cluster": f"P{index:02d}",
                    "outer_fold": str(index // 2),
                    "R_8X6B": repr(r8), "R_9E6Y": repr(r9), "R_dual_min": repr(min(r8, r9)),
                }
                writer.writerow(row); rows.append(row)
        return {row["candidate_id"]: row for row in rows}

    def _prediction_rows(self, lane: str, fold: int):
        split = json.loads(self.split_paths[fold].read_text())
        candidates = [row for row in self.training.values() if row["parent_framework_cluster"] in set(split["score_parents"])]
        result = []
        lane_offset = 0.001 * mod.LANES.index(lane)
        for index, source in enumerate(candidates):
            truth8, truth9 = float(source["R_8X6B"]), float(source["R_9E6Y"])
            m28, m29 = truth8 + 0.01, truth9 - 0.005
            neural8, neural9 = truth8 + lane_offset + 0.002, truth9 + lane_offset - 0.001
            row = {
                "candidate_id": source["candidate_id"], "teacher_source": source["teacher_source"],
                "parent_framework_cluster": source["parent_framework_cluster"],
                "split_id": split["split_id"], "lane": lane,
                "truth_R8": source["R_8X6B"], "truth_R9": source["R_9E6Y"], "truth_Rdual": source["R_dual_min"],
                "M2_R8": repr(m28), "M2_R9": repr(m29), "M2_Rdual": repr(min(m28, m29)),
                "neural_R8": repr(neural8), "neural_R9": repr(neural9), "neural_Rdual": repr(min(neural8, neural9)),
                "contact_score_R8": repr(0.3 + index * 0.01), "contact_score_R9": repr(0.4 + index * 0.01),
                "contact_score_role": "diagnostic" if lane == "A_VHH_ONLY" else "stack_eligible",
                "contact_score_formula_sha256": "" if lane == "A_VHH_ONLY" else mod.sha256_file(self.formula_path),
                "base_training_parent_set_sha256": split["train_parent_set_sha256"],
                "base_training_parent_count": str(len(split["train_parents"])),
                "base_model_receipt_sha256": "PLACEHOLDER",
            }
            result.append(row)
        return result

    def _write_one_result(self, lane: str, fold: int) -> None:
        output = self.runtime / "outer_development" / lane / f"fold_{fold}"
        output.mkdir(parents=True, exist_ok=True)
        for name, content in (("m2_ridge.json", "{}\n"), ("neural_head.pt", "head\n"), ("contact_score_formula_v1.json", self.formula_path.read_text())):
            (output / name).write_text(content, encoding="utf-8")
        component = output / "component_receipts.json"
        write_json(component, {"lane": lane, "fold": fold})
        rows = self._prediction_rows(lane, fold)
        component_sha = mod.sha256_file(component)
        for row in rows:
            row["base_model_receipt_sha256"] = component_sha
        prediction = output / "base_score_predictions.tsv"
        with prediction.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=mod.PREDICTION_FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        split = json.loads(self.split_paths[fold].read_text())
        artifacts = {
            "predictions": {"path": prediction.name, "rows": len(rows), "sha256": mod.sha256_file(prediction)},
            "m2_ridge": {"path": "m2_ridge.json", "sha256": mod.sha256_file(output / "m2_ridge.json")},
            "neural_head": {"path": "neural_head.pt", "sha256": mod.sha256_file(output / "neural_head.pt")},
            "component_receipts": {"path": component.name, "sha256": component_sha},
            "contact_score_formula": {"path": "contact_score_formula_v1.json", "sha256": mod.sha256_file(output / "contact_score_formula_v1.json")},
        }
        result = {
            "schema_version": mod.RESULT_SCHEMA, "status": mod.RESULT_STATUS, "lane": lane,
            "split": split, "claim_boundary": mod.TRAINER_RESULT_CLAIM_BOUNDARY,
            "open_only": True, "v4_f_test32_access_count": 0,
            "loss_weights": {"receptor": 1.0, "dual": 0.5, **mod.EXPECTED_WEIGHTS[lane]},
            "source_parent_candidate_weighting": self._source_weight_audit(split),
            "artifacts": artifacts,
        }
        write_json(output / "RESULT.json", result)
        log = output.parent / f"fold_{fold}.trainer.log"
        log.write_text(f"{lane} {fold} complete\n", encoding="utf-8")

    def _source_weight_audit(self, split):
        train = set(split["train_parents"])
        sources = {}
        for source in sorted({row["teacher_source"] for row in self.training.values()}):
            selected = [row for row in self.training.values() if row["teacher_source"] == source and row["parent_framework_cluster"] in train]
            if selected:
                sources[source] = {
                    "parents": len({row["parent_framework_cluster"] for row in selected}),
                    "candidates": len(selected),
                    "mass": 0.5,
                }
        return {"contract": "0.5/source -> equal parent -> equal candidate", "sources": sources, "sum": 1.0}

    def _write_all_results(self) -> None:
        for lane in mod.LANES:
            for fold in mod.FOLDS:
                self._write_one_result(lane, fold)

    def _write_outer_receipt(self) -> None:
        outer = {}
        for lane in mod.LANES:
            outer[lane] = []
            for fold in mod.FOLDS:
                output = self.runtime / "outer_development" / lane / f"fold_{fold}"
                outer[lane].append({
                    "lane": lane, "outer_fold": fold, "physical_gpu": mod.LANES.index(lane),
                    "command_sha256": "a" * 64,
                    "result_sha256": mod.sha256_file(output / "RESULT.json"),
                    "log_sha256": mod.sha256_file(output.parent / f"fold_{fold}.trainer.log"),
                })
        payload = {
            "schema_version": mod.OUTER_SCHEMA, "status": mod.OUTER_STATUS,
            "manifest_sha256": mod.sha256_file(self.manifest_path),
            "implementation_freeze_sha256": mod.sha256_file(self.freeze_path),
            "formal_artifact_sha256": self.freeze["formal_artifact_sha256"],
            "smoke_receipt_sha256": mod.sha256_file(self.smoke_path),
            "calibration_receipt_sha256": self.manifest["artifacts"]["calibration_receipt"]["sha256"],
            "outer_development": outer,
            "claim_boundary": mod.CLAIM_BOUNDARY,
            "trainer_result_claim_boundary": mod.TRAINER_RESULT_CLAIM_BOUNDARY,
            "bundle_revision": mod.BUNDLE_REVISION,
            "sealed_evaluation_access_count": 0, "prediction_metrics_access_count": 0,
        }
        write_json(self.runtime / "status" / "OUTER_DEVELOPMENT_RECEIPT.json", payload)

    def refresh_fold(self, lane: str, fold: int) -> None:
        output = self.runtime / "outer_development" / lane / f"fold_{fold}"
        result_path = output / "RESULT.json"
        result = json.loads(result_path.read_text())
        prediction = output / result["artifacts"]["predictions"]["path"]
        result["artifacts"]["predictions"]["sha256"] = mod.sha256_file(prediction)
        write_json(result_path, result)
        outer_path = self.runtime / "status" / "OUTER_DEVELOPMENT_RECEIPT.json"
        outer = json.loads(outer_path.read_text())
        outer["outer_development"][lane][fold]["result_sha256"] = mod.sha256_file(result_path)
        write_json(outer_path, outer)


class CollectV222OuterOOFTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temporary.name).resolve())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def collect(self):
        f = self.fixture
        return mod.collect(manifest_path=f.manifest_path, freeze_path=f.freeze_path, runtime_root=f.runtime, output_root=f.output)

    def test_collects_all_lanes_and_stops_before_nested_stack(self) -> None:
        terminal = self.collect()
        self.assertEqual(terminal["result_count"], 20)
        self.assertFalse(terminal["strict_nested_stack_started"])
        self.assertFalse(terminal["automatic_strict_nested_stack_launch"])
        metrics = json.loads((self.fixture.output / "collection_v1" / "OOF_METRICS.json").read_text())
        self.assertEqual(set(metrics["lanes"]), set(mod.LANES))
        self.assertEqual(metrics["rows_per_lane"], 10)
        self.assertEqual(metrics["v4_f_test32_access_count"], 0)
        for lane in mod.LANES:
            self.assertTrue((self.fixture.output / "collection_v1" / "oof" / f"{lane}.outer_oof.tsv").is_file())

    def test_rejects_prediction_exact_min_tamper(self) -> None:
        f = self.fixture; lane, fold = "D_SPLIT_PAIR", 0
        prediction = f.runtime / "outer_development" / lane / f"fold_{fold}" / "base_score_predictions.tsv"
        with prediction.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t"); fields = reader.fieldnames; rows = list(reader)
        rows[0]["neural_Rdual"] = "0.999"
        with prediction.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
        f.refresh_fold(lane, fold)
        with self.assertRaisesRegex(mod.CollectionError, "prediction_exact_min"):
            self.collect()

    def test_rejects_parent_or_source_tamper(self) -> None:
        f = self.fixture; lane, fold = "C_SPLIT_MARGINAL", 1
        prediction = f.runtime / "outer_development" / lane / f"fold_{fold}" / "base_score_predictions.tsv"
        with prediction.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t"); fields = reader.fieldnames; rows = list(reader)
        rows[0]["teacher_source"] = "WRONG_SOURCE"
        with prediction.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
        f.refresh_fold(lane, fold)
        with self.assertRaisesRegex(mod.CollectionError, "prediction_source"):
            self.collect()

    def test_rejects_frozen_lane_weight_tamper(self) -> None:
        f = self.fixture; lane, fold = "C_SPLIT_MARGINAL", 0
        result_path = f.runtime / "outer_development" / lane / f"fold_{fold}" / "RESULT.json"
        result = json.loads(result_path.read_text()); result["loss_weights"]["marginal"] = 1.0; write_json(result_path, result)
        outer_path = f.runtime / "status" / "OUTER_DEVELOPMENT_RECEIPT.json"
        outer = json.loads(outer_path.read_text()); outer["outer_development"][lane][fold]["result_sha256"] = mod.sha256_file(result_path); write_json(outer_path, outer)
        with self.assertRaisesRegex(mod.CollectionError, "result_lane_weights"):
            self.collect()

    def test_rejects_source_weight_tamper(self) -> None:
        f = self.fixture; lane, fold = "B_TARGET_NO_CONTACT", 2
        result_path = f.runtime / "outer_development" / lane / f"fold_{fold}" / "RESULT.json"
        result = json.loads(result_path.read_text())
        result["source_parent_candidate_weighting"]["sources"]["V4D_OPEN_MULTI_SEED"]["mass"] = 0.6
        write_json(result_path, result)
        outer_path = f.runtime / "status" / "OUTER_DEVELOPMENT_RECEIPT.json"
        outer = json.loads(outer_path.read_text())
        outer["outer_development"][lane][fold]["result_sha256"] = mod.sha256_file(result_path)
        write_json(outer_path, outer)
        with self.assertRaisesRegex(mod.CollectionError, "source_weight_mass"):
            self.collect()

    def test_rejects_outer_claim_tamper(self) -> None:
        path = self.fixture.runtime / "status" / "OUTER_DEVELOPMENT_RECEIPT.json"
        payload = json.loads(path.read_text()); payload["claim_boundary"] = "tampered"; write_json(path, payload)
        with self.assertRaisesRegex(mod.CollectionError, "outer_claim_boundary"):
            self.collect()

    def test_watcher_times_out_without_receipt_and_never_launches_nested(self) -> None:
        f = self.fixture
        (f.runtime / "status" / "OUTER_DEVELOPMENT_RECEIPT.json").unlink()
        with self.assertRaisesRegex(mod.CollectionError, "watch_timeout"):
            mod.watch(
                manifest_path=f.manifest_path, freeze_path=f.freeze_path,
                runtime_root=f.runtime, output_root=f.output,
                poll_seconds=0.005, timeout_seconds=0.015,
            )
        status = json.loads((f.output / "WATCHER_STATUS.json").read_text())
        self.assertEqual(status["status"], "WAITING_OUTER_DEVELOPMENT_RECEIPT")
        self.assertFalse(status["automatic_strict_nested_stack_launch"])

    def test_existing_terminal_resume_is_hash_validated(self) -> None:
        f = self.fixture
        self.collect()
        metrics_path = f.output / "collection_v1" / "OOF_METRICS.json"
        metrics_path.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(mod.CollectionError, "existing_terminal_metrics_sha"):
            mod.watch(
                manifest_path=f.manifest_path, freeze_path=f.freeze_path,
                runtime_root=f.runtime, output_root=f.output,
                poll_seconds=0.01, timeout_seconds=0.01,
            )


if __name__ == "__main__":
    unittest.main()
