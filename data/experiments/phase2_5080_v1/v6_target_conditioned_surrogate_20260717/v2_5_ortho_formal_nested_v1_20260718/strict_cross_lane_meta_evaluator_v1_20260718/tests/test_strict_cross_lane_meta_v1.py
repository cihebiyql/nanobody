import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


evaluator = load("strict_cross_lane_meta", ROOT / "src" / "evaluate_strict_cross_lane_meta_v1.py")
watcher = load("strict_cross_lane_watcher", ROOT / "src" / "watch_terminal_then_evaluate_v1.py")


class EvaluatorTests(unittest.TestCase):
    def test_contract_hash_and_roles(self):
        contract = evaluator.validate_contract(ROOT.parent / "evaluation_contract_v1_20260718" / "CROSS_LANE_NESTED_META_EVALUATION_CONTRACT_V1.json")
        self.assertEqual(contract["lane_roles"]["formal_primary_base_lane"], evaluator.PRIMARY_LANE)

    def test_robust_contact_is_train_only_and_clipped(self):
        train = np.asarray([[0.0, 10.0], [1.0, 11.0], [2.0, 12.0], [100.0, 13.0]])
        center, scale = evaluator.robust_contact_fit(train)
        transformed = evaluator.robust_contact_transform(np.asarray([[1000.0, -1000.0]]), center, scale)
        self.assertTrue(np.all(np.abs(transformed) <= 5.0))
        self.assertTrue(np.all(scale >= 1e-6))

    def test_meta_recovers_nonnegative_signal_and_exact_m2_fallback_exists(self):
        rng = np.random.default_rng(1)
        n = 80
        m2 = rng.normal(0.55, 0.03, (n, 2))
        neural = m2 + rng.normal(0, 0.02, (n, 2))
        c2 = m2 + rng.normal(0, 0.02, (n, 2))
        contact = rng.normal(0, 1, (n, 2))
        truth = m2 + 0.25 * (neural - m2) + 0.15 * (c2 - m2) + 0.01 * contact
        fit = evaluator.fit_meta(truth, m2, c2, neural, contact, np.ones(n) / n)
        self.assertGreaterEqual(fit.w_E, 0)
        self.assertGreaterEqual(fit.w_C2, 0)
        self.assertGreaterEqual(fit.beta_C, 0)
        self.assertLessEqual(fit.w_E + fit.w_C2, 1 + 1e-10)
        fallback = evaluator.MetaFit(0, 0, 0, "EXACT_M2", 0, 0)
        np.testing.assert_allclose(evaluator.meta_predict(fallback, m2, c2, neural, contact), m2)

    def test_negative_contact_cannot_receive_negative_beta(self):
        rng = np.random.default_rng(2)
        n = 50
        m2 = rng.normal(0.5, 0.02, (n, 2))
        contact = rng.normal(0, 1, (n, 2))
        truth = m2 - 0.1 * contact
        fit = evaluator.fit_meta(truth, m2, m2, m2, contact, np.ones(n) / n)
        self.assertEqual(fit.beta_C, 0.0)

    def _write_job(self, root: Path, *, contact=True, bad_hash=False):
        rows = [{"candidate_id": "c1", "neural_R8": "0.5", "neural_R9": "0.6", "neural_Rdual": "0.5", "contact_score_R8": "0.2" if contact else "", "contact_score_R9": "0.3" if contact else ""}]
        p = root / "score_predictions_no_metrics.tsv"
        with p.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
            writer.writeheader(); writer.writerows(rows)
        digest = evaluator.sha256(p)
        result = {"status": "PASS_FORMAL_INNER_TRAINING", "phase": "inner", "outer_fold": 0, "inner_fold": 0, "formal_hparam_id": "H0", "formal_seed": 43, "lane": {"variant": evaluator.PRIMARY_LANE}, "prediction_metrics_access_count": 0, "v4_f_test32_access_count": 0, "artifacts": {"predictions_no_metrics": {"path": p.name, "sha256": "0" * 64 if bad_hash else digest}}}
        (root / "RESULT.json").write_text(json.dumps(result))

    def test_raw_job_hash_and_contact_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._write_job(root)
            rows = evaluator.validate_raw_job(root, phase="inner", outer_fold=0, inner_fold=0, hparam_id="H0", seed=43, expected_ids={"c1"}, require_contact=True)
            self.assertEqual(set(rows), {"c1"})

    def test_raw_job_hash_tamper_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._write_job(root, bad_hash=True)
            with self.assertRaisesRegex(evaluator.EvaluationError, "job_prediction_hash"):
                evaluator.validate_raw_job(root, phase="inner", outer_fold=0, inner_fold=0, hparam_id="H0", seed=43, expected_ids={"c1"}, require_contact=True)

    def test_missing_contact_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._write_job(root, contact=False)
            with self.assertRaisesRegex(evaluator.EvaluationError, "missing_contact"):
                evaluator.validate_raw_job(root, phase="inner", outer_fold=0, inner_fold=0, hparam_id="H0", seed=43, expected_ids={"c1"}, require_contact=True)

    def test_promotion_requires_source_mae(self):
        contract = json.loads((ROOT.parent / "evaluation_contract_v1_20260718" / "CROSS_LANE_NESTED_META_EVALUATION_CONTRACT_V1.json").read_text())
        rows = []
        for parent in range(31):
            source = "V4D_OPEN_MULTI_SEED" if parent < 15 else "V4H_ADAPTIVE_SEED_RANKING"
            for i in range(3):
                truth = 0.4 + parent * 0.005 + i * 0.001
                rows.append({"candidate_id": f"c{parent}_{i}", "parent_framework_cluster": f"p{parent}", "teacher_source": source, "truth_R8": truth, "truth_R9": truth + .02, "truth_Rdual": truth, "pred_R8": truth, "pred_R9": truth + .02, "pred_Rdual": truth})
        baseline = [dict(row, pred_R8=row["truth_R8"] + .01, pred_R9=row["truth_R9"] + .01, pred_Rdual=row["truth_Rdual"] + .01) for row in rows]
        decision = evaluator.promotion_decision(contract, rows, baseline)
        self.assertIn("each_source_Rdual_mae", decision["checks"])
        self.assertIn("parent_bootstrap", decision["checks"])


class WatcherTests(unittest.TestCase):
    def test_terminal_ready_waits_without_final(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "TERMINAL.json").write_text(json.dumps({"status": "PASS"}))
            self.assertFalse(watcher.terminal_ready(root))

    def test_terminal_ready_checks_graph_and_sealed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "final").mkdir()
            (root / "TERMINAL.json").write_text(json.dumps({"status": "PASS", "returncode": 0, "completed": 301, "job_graph_sha256": watcher.EXPECTED_GRAPH_SHA, "v4_f_test32_access_count": 0}))
            (root / "final" / "RESULT.json").write_text(json.dumps({"status": "PASS_FORMAL_OPEN_OUTER_EVALUATION_COLLECTED", "v4_f_test32_access_count": 0}))
            self.assertTrue(watcher.terminal_ready(root))

    def test_terminal_sealed_access_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "final").mkdir()
            (root / "TERMINAL.json").write_text(json.dumps({"status": "PASS", "returncode": 0, "completed": 301, "job_graph_sha256": watcher.EXPECTED_GRAPH_SHA, "v4_f_test32_access_count": 1}))
            (root / "final" / "RESULT.json").write_text(json.dumps({"status": "PASS_FORMAL_OPEN_OUTER_EVALUATION_COLLECTED", "v4_f_test32_access_count": 0}))
            with self.assertRaisesRegex(watcher.WatcherError, "terminal_sealed_access"):
                watcher.terminal_ready(root)


if __name__ == "__main__":
    unittest.main()
