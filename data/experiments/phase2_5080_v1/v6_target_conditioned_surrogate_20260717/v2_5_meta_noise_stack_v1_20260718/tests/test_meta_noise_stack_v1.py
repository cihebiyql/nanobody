#!/usr/bin/env python3

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dry_run_v1 import synthetic_rows
from meta_noise_stack_v1 import (
    GBDTConfig,
    MetaNoiseError,
    attach_existing_c2_outer_oof,
    base_arrays,
    crossfit_noise_for_outer_fold,
    exact_min,
    fit_convex_residual_stack,
    fit_noise_head,
    hierarchical_weights,
    predict_convex_residual_stack,
    predict_noise,
    read_tsv,
    run_outer_fold,
    run_strict_outer_crossfit,
    truth_array,
    validate_c2_outer_oof,
    validate_predictor_names,
    validate_whole_parent_split_contract,
)


def nested_fixture():
    labels = []
    outer = []
    inner = []
    for index in range(10):
        labels.append({
            "candidate_id": f"C{index}",
            "parent_framework_cluster": f"P{index}",
            "teacher_source": "S0" if index < 5 else "S1",
            "outer_fold": str(index % 5),
        })
    for outer_fold in range(5):
        train_parents = []
        for row in labels:
            role = "score" if int(row["outer_fold"]) == outer_fold else "train"
            outer.append({**row, "outer_fold": str(outer_fold), "candidate_role": role})
            if role == "train":
                train_parents.append(row["parent_framework_cluster"])
        assignment = {parent: i % 5 for i, parent in enumerate(sorted(train_parents))}
        for inner_fold in range(5):
            for row in labels:
                if row["parent_framework_cluster"] not in assignment:
                    continue
                role = "score" if assignment[row["parent_framework_cluster"]] == inner_fold else "train"
                inner.append({
                    **row,
                    "outer_fold": str(outer_fold),
                    "inner_fold": str(inner_fold),
                    "candidate_role": role,
                })
    return labels, outer, inner


class MetaNoiseStackTests(unittest.TestCase):
    def test_exact_min_is_derived(self):
        values = np.asarray([[0.2, 0.4], [0.7, 0.1]])
        np.testing.assert_array_equal(exact_min(values), [0.2, 0.1])

    def test_identifier_predictors_are_forbidden(self):
        validate_predictor_names(["M2_R8", "contact_entropy"])
        for forbidden in ("candidate_id", "parent_id", "campaign_id", "outer_fold", "seed_id"):
            with self.assertRaises(MetaNoiseError):
                validate_predictor_names(["M2_R8", forbidden])

    def test_convex_stack_constraints_and_prediction(self):
        rng = np.random.default_rng(3)
        m2 = rng.normal(0.5, 0.03, (80, 2))
        branches = {
            "neural": m2 + rng.normal(0, 0.02, (80, 2)),
            "contact": m2 + rng.normal(0, 0.02, (80, 2)),
            "c2": m2 + rng.normal(0, 0.02, (80, 2)),
        }
        truth = m2 + 0.2 * (branches["neural"] - m2) + 0.3 * (branches["contact"] - m2)
        model = fit_convex_residual_stack(truth, m2, branches, np.ones(80), l2_toward_m2=1e-8)
        self.assertTrue(np.all(model.weights() >= 0))
        self.assertLessEqual(float(model.weights().sum()), 1.0 + 1e-10)
        prediction = predict_convex_residual_stack(model, m2, branches)
        self.assertEqual(prediction.shape, (80, 2))
        self.assertGreater(model.neural_weight, 0.05)
        self.assertGreater(model.contact_weight, 0.05)

    def test_noise_head_ignores_tier_c_truth_not_zero_imputation(self):
        inner, _ = synthetic_rows()
        weights = hierarchical_weights(inner)
        first = fit_noise_head(inner, weights)
        changed = copy.deepcopy(inner)
        for row in changed:
            if row["development_reliability_tier"] == "C":
                row["seed_dispersion_max"] = 9999.0
        second = fit_noise_head(changed, weights)
        np.testing.assert_allclose(first.coefficient, second.coefficient, atol=0, rtol=0)
        self.assertEqual(first.intercept_log_variance, second.intercept_log_variance)
        variance, reliability = predict_noise(first, changed)
        self.assertTrue(np.isfinite(variance).all())
        self.assertTrue(np.all((reliability >= 0.25) & (reliability <= 4.0)))

    def test_noise_reliability_is_parent_cross_fitted(self):
        inner, outer = synthetic_rows()
        inner_rel, outer_rel, audit = crossfit_noise_for_outer_fold(inner, outer)
        self.assertEqual(inner_rel.shape, (len(inner),))
        self.assertEqual(outer_rel.shape, (len(outer),))
        self.assertFalse(audit["tier_C_used_as_variance_truth"])
        self.assertTrue(all(item["fit_score_parent_overlap"] == 0 for item in audit["fold_audits"]))

    def test_same_row_or_parent_leakage_fails_closed(self):
        inner, outer = synthetic_rows()
        duplicate = copy.deepcopy(outer)
        duplicate[0]["candidate_id"] = inner[0]["candidate_id"]
        with self.assertRaises(MetaNoiseError):
            crossfit_noise_for_outer_fold(inner, duplicate)
        duplicate = copy.deepcopy(outer)
        duplicate[0]["parent_framework_cluster"] = inner[0]["parent_framework_cluster"]
        with self.assertRaises(MetaNoiseError):
            crossfit_noise_for_outer_fold(inner, duplicate)

    def test_outer_truth_is_never_used_for_fit_or_prediction(self):
        inner, outer = synthetic_rows()
        first = run_outer_fold(inner, outer, include_gbdt=True)
        poisoned = copy.deepcopy(outer)
        for index, row in enumerate(poisoned):
            row["truth_R8"] = 1e9 + index
            row["truth_R9"] = -1e9 - index
        second = run_outer_fold(inner, poisoned, include_gbdt=True)
        for field in (
            "primary_prediction_two", "reliability_prediction_two", "gbdt_prediction_two",
            "outer_predicted_reliability",
        ):
            np.testing.assert_allclose(first[field], second[field], atol=0, rtol=0)
        self.assertFalse(first["outer_truth_accessed_for_fit"])

    def test_all_model_duals_are_exact_min(self):
        inner, outer = synthetic_rows()
        result = run_outer_fold(inner, outer, include_gbdt=True)
        for prefix in ("primary", "reliability", "gbdt"):
            two = result[f"{prefix}_prediction_two"]
            np.testing.assert_array_equal(result[f"{prefix}_prediction_dual"], np.minimum(two[:, 0], two[:, 1]))

    def test_gbdt_is_fixed_challenger_only(self):
        config = GBDTConfig()
        self.assertEqual(config.role, "CHALLENGER_ONLY_NOT_PRIMARY")
        self.assertLessEqual(config.max_depth, 3)
        self.assertGreaterEqual(config.min_samples_leaf, 32)

    def test_c2_outer_fold_closure(self):
        labels = {
            f"C{index}": {
                "outer_fold": str(index % 5),
                "parent_framework_cluster": f"P{index}",
                "teacher_source": "S0" if index < 5 else "S1",
            }
            for index in range(10)
        }
        rows = []
        for candidate, label in labels.items():
            p8, p9 = 0.5, 0.49
            rows.append({
                "model_id": "C2_INNER_SELECTED_PCA8_RIDGE",
                "candidate_id": candidate,
                "outer_fold": label["outer_fold"],
                "parent_framework_cluster": label["parent_framework_cluster"],
                "teacher_source": label["teacher_source"],
                "selected_c2_alpha": 10.0 + int(label["outer_fold"]),
                "pred_R8": p8,
                "pred_R9": p9,
                "pred_Rdual": min(p8, p9),
            })
        audit = validate_c2_outer_oof(rows, labels)
        self.assertEqual(audit["candidate_count"], 10)
        self.assertTrue(audit["candidate_scored_exactly_once"])
        broken = copy.deepcopy(rows)
        broken[0]["outer_fold"] = "4"
        with self.assertRaises(MetaNoiseError):
            validate_c2_outer_oof(broken, labels)

        outer_base = [{
            "candidate_id": candidate,
            "outer_fold": label["outer_fold"],
            "parent_framework_cluster": label["parent_framework_cluster"],
            "teacher_source": label["teacher_source"],
        } for candidate, label in labels.items()]
        joined = attach_existing_c2_outer_oof(outer_base, rows, labels)
        self.assertEqual(len(joined), len(labels))
        self.assertTrue(all("c2_R8" in row and "c2_R9" in row for row in joined))

    def test_five_fold_strict_crossfit_api_closes(self):
        all_inner = []
        all_outer = []
        for fold in range(5):
            inner, outer = synthetic_rows()
            for row in inner:
                row["candidate_id"] = f"F{fold}_{row['candidate_id']}"
                row["parent_framework_cluster"] = f"F{fold}_{row['parent_framework_cluster']}"
                row["outer_fold"] = fold
            for row in outer:
                row["candidate_id"] = f"F{fold}_{row['candidate_id']}"
                row["parent_framework_cluster"] = f"F{fold}_{row['parent_framework_cluster']}"
                row["outer_fold"] = fold
            all_inner.extend(inner)
            all_outer.extend(outer)
        result = run_strict_outer_crossfit(all_inner, all_outer, include_gbdt=False)
        self.assertEqual(result["outer_folds"], 5)
        self.assertEqual(result["candidate_count"], len(all_outer))
        self.assertFalse(result["same_row_stacking"])
        self.assertFalse(result["outer_truth_accessed_for_fit"])
        self.assertEqual(len({row["candidate_id"] for row in result["predictions"]}), len(all_outer))

    def test_whole_parent_nested_split_contract(self):
        labels, outer, inner = nested_fixture()
        audit = validate_whole_parent_split_contract(labels, outer, inner)
        self.assertTrue(audit["each_candidate_outer_score_once"])
        self.assertTrue(audit["each_outer_train_candidate_inner_score_once"])
        broken = copy.deepcopy(inner)
        broken[0]["candidate_role"] = "score" if broken[0]["candidate_role"] == "train" else "train"
        with self.assertRaises(MetaNoiseError):
            validate_whole_parent_split_contract(labels, outer, broken)

    def test_v4f_path_is_rejected_before_open(self):
        with self.assertRaises(MetaNoiseError):
            read_tsv(Path("/tmp/V4-F/test32.tsv"))


if __name__ == "__main__":
    unittest.main()
