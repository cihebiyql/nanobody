import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "evaluate_v2_10_open_development.py"
SPEC = importlib.util.spec_from_file_location("development_eval", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def parent_hash(values):
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode()).hexdigest()


class EvaluationTests(unittest.TestCase):
    def test_prediction_model_order_matches_real_stage0_header(self):
        expected = (
            "RIDGE_ESM2_650M",
            "RIDGE_ESM2_3B",
            "RIDGE_ESM2_650M_3B",
            "ELASTICNET_ESM2_650M_PCA",
        )
        header = ["candidate_id"]
        for model in expected:
            header.extend([f"{model}__R8", f"{model}__R9", f"{model}__Rdual_exact_min"])
        self.assertEqual(module.prediction_model_names(header), expected)

    def fixture(self, root: Path):
        teacher = root / "teacher.tsv"
        fields = [
            "candidate_id", "sequence_sha256", "parent_framework_cluster",
            "R_8X6B", "R_9E6Y", "R_dual_min", "sample_weight",
            "teacher_reliability",
        ]
        rows = []
        for index, (parent, r8, r9) in enumerate([
            ("T1", .2, .3), ("T2", .3, .4),
            ("D1", .4, .5), ("D1", .5, .6),
            ("D2", .6, .7), ("D2", .7, .8),
        ]):
            candidate = f"c{index}"
            rows.append({
                "candidate_id": candidate,
                "sequence_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                "parent_framework_cluster": parent,
                "R_8X6B": str(r8), "R_9E6Y": str(r9),
                "R_dual_min": str(min(r8, r9)), "sample_weight": "1",
                "teacher_reliability": "OPEN_WEAK_LABEL",
            })
        with teacher.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        digest = module.sha256_file(teacher)
        split = root / "split.json"
        split.write_text(json.dumps({
            "schema_version": module.SPLIT_SCHEMA,
            "data_version": "D1", "open_only": True,
            "frozen_test_access_count": 0, "sealed_truth_access_count": 0,
            "training_tsv_sha256": digest,
            "expected_train_rows": 2, "expected_score_rows": 4,
            "expected_total_rows": 6,
            "train_parents": ["T1", "T2"], "score_parents": ["D1", "D2"],
            "frozen_test_parents": ["F1"],
            "train_parent_set_sha256": parent_hash(["T1", "T2"]),
            "score_parent_set_sha256": parent_hash(["D1", "D2"]),
            "frozen_test_parent_set_sha256": parent_hash(["F1"]),
        }))
        run = root / "run"
        seed_dir = run / "seed_43"
        seed_dir.mkdir(parents=True)
        prediction = seed_dir / "OPEN_SCORE_PREDICTIONS.tsv"
        prediction_fields = [
            "candidate_id", "parent_framework_cluster", "truth_R8", "truth_R9",
            "truth_Rdual_exact_min", "M1__R8", "M1__R9", "M1__Rdual_exact_min",
            "M2__R8", "M2__R9", "M2__Rdual_exact_min",
        ]
        with prediction.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=prediction_fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for row in rows[2:]:
                r8, r9 = float(row["R_8X6B"]), float(row["R_9E6Y"])
                writer.writerow({
                    "candidate_id": row["candidate_id"],
                    "parent_framework_cluster": row["parent_framework_cluster"],
                    "truth_R8": r8, "truth_R9": r9,
                    "truth_Rdual_exact_min": min(r8, r9),
                    "M1__R8": r8, "M1__R9": r9, "M1__Rdual_exact_min": min(r8, r9),
                    "M2__R8": 1-r8, "M2__R9": 1-r9, "M2__Rdual_exact_min": min(1-r8, 1-r9),
                })
        result = {
            "status": "PASS_OPEN_SEQUENCE_STAGE0_COMPLETE",
            "seed": 43,
            "data_version": "D1",
            "train_rows": 2,
            "score_rows": 4,
            "model_names": ["M1", "M2"],
            "input_access": {"frozen_test": 0, "sealed_truth": 0},
            "inputs": {
                "training_tsv_sha256": digest,
                "split_manifest_sha256": module.sha256_file(split),
            },
        }
        (seed_dir / "RESULT.json").write_text(json.dumps(result))
        self.refresh_seed_hashes(seed_dir)
        preflight = {
            "status": "PASS_PREFLIGHT", "data_version": "D1",
            "seeds": [43], "train_rows": 2, "score_rows": 4, "total_rows": 6,
            "frozen_test_access_count": 0, "sealed_truth_access_count": 0,
            "teacher_frozen_parent_overlap_count": 0,
            "training_tsv_sha256": digest,
            "split_manifest_sha256": module.sha256_file(split),
            "model_names": ["M1", "M2"],
        }
        summary = {
            "status": "PASS_MULTISEED_COMPLETE", "data_version": "D1",
            "seeds": [43], "train_rows": 2, "score_rows": 4,
            "model_names": ["M1", "M2"],
        }
        (run / "PREFLIGHT.json").write_text(json.dumps(preflight))
        (run / "MULTISEED_SUMMARY.json").write_text(json.dumps(summary))
        self.refresh_root_hashes(run)
        return teacher, digest, split, prediction

    def refresh_seed_hashes(self, seed_dir: Path):
        names = ["OPEN_SCORE_PREDICTIONS.tsv", "RESULT.json"]
        (seed_dir / "SHA256SUMS").write_text("".join(
            f"{module.sha256_file(seed_dir/name)}  {name}\n" for name in names
        ))

    def refresh_root_hashes(self, run: Path):
        names = ["MULTISEED_SUMMARY.json", "PREFLIGHT.json"]
        (run / "SHA256SUMS").write_text("".join(
            f"{module.sha256_file(run/name)}  {name}\n" for name in names
        ))

    def evaluate(self, root: Path):
        teacher, digest, split, prediction = self.fixture(root)
        return module.evaluate(
            teacher, digest, split, [(43, prediction)],
            module.ExpectedCounts(train=2, development=4, total=6),
            expected_seeds=(43,),
        )

    def test_valid_metrics_and_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(Path(tmp))
        self.assertEqual(result["status"], "PASS_V2_10_OPEN_DEVELOPMENT_EVALUATION")
        self.assertEqual(result["development_selected_model"], "M1")
        value = result["seed_mean_R8_R9_then_exact_min_metrics"]["M1"]
        self.assertAlmostEqual(value["primary_summary"]["recall_true_top20_at_budget20"], 1.0)
        self.assertAlmostEqual(value["Rdual_exact_min"]["spearman"], 1.0)

    def test_prediction_candidate_outside_development_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teacher, digest, split, prediction = self.fixture(root)
            text = prediction.read_text().replace("c2\tD1", "c0\tT1", 1)
            prediction.write_text(text)
            self.refresh_seed_hashes(prediction.parent)
            with self.assertRaisesRegex(module.EvaluationError, "outside_development"):
                module.evaluate(teacher, digest, split, [(43, prediction)], module.ExpectedCounts(2, 4, 6), expected_seeds=(43,))

    def test_prediction_exact_min_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teacher, digest, split, prediction = self.fixture(root)
            lines = prediction.read_text().splitlines()
            fields = lines[0].split("\t")
            values = lines[1].split("\t")
            values[fields.index("M1__Rdual_exact_min")] = "0.999"
            lines[1] = "\t".join(values)
            prediction.write_text("\n".join(lines) + "\n")
            self.refresh_seed_hashes(prediction.parent)
            with self.assertRaisesRegex(module.EvaluationError, "prediction_exact_min"):
                module.evaluate(teacher, digest, split, [(43, prediction)], module.ExpectedCounts(2, 4, 6), expected_seeds=(43,))

    def test_prediction_development_closure_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teacher, digest, split, prediction = self.fixture(root)
            lines = prediction.read_text().splitlines()
            prediction.write_text("\n".join(lines[:-1]) + "\n")
            self.refresh_seed_hashes(prediction.parent)
            with self.assertRaisesRegex(module.EvaluationError, "development_closure"):
                module.evaluate(teacher, digest, split, [(43, prediction)], module.ExpectedCounts(2, 4, 6), expected_seeds=(43,))

    def test_seed_hash_closure_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teacher, digest, split, prediction = self.fixture(root)
            prediction.write_text(prediction.read_text() + "\n")
            with self.assertRaisesRegex(module.EvaluationError, "hashed_file_mismatch"):
                module.evaluate(teacher, digest, split, [(43, prediction)], module.ExpectedCounts(2, 4, 6), expected_seeds=(43,))

    def test_seed_contract_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            teacher, digest, split, prediction = self.fixture(root)
            with self.assertRaisesRegex(module.EvaluationError, "seed_contract"):
                module.evaluate(teacher, digest, split, [(43, prediction)], module.ExpectedCounts(2, 4, 6), expected_seeds=(43, 97))

    def test_forbidden_path_fails(self):
        with tempfile.TemporaryDirectory(prefix="sealed_truth_") as tmp:
            with self.assertRaisesRegex(module.EvaluationError, "forbidden"):
                module.reject_forbidden_path(Path(tmp) / "x.tsv", "fixture")

    def test_atomic_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.evaluate(root)
            output = root / "output"
            module.write_outputs(output, result)
            self.assertTrue((output / "DEVELOPMENT_METRICS.json").is_file())
            self.assertTrue((output / "MODEL_SELECTION.tsv").is_file())
            self.assertTrue((output / "SHA256SUMS").is_file())


if __name__ == "__main__":
    unittest.main()
