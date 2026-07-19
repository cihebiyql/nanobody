#!/usr/bin/env python3
from __future__ import annotations

import dataclasses
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rank_calibration_core_v1", ROOT / "rank_calibration_core_v1.py")
assert spec and spec.loader
core = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = core
spec.loader.exec_module(core)

V6_ROOT = ROOT.parent.parent
BINDING = V6_ROOT / "v2_6_noise_tolerance_binding_v1_20260718" / "V2_6_DELTA_NOISE_BINDING.json"


def labels(parent_count: int = 10, siblings: int = 4):
    output = []
    for parent_index in range(parent_count):
        for sibling_index in range(siblings):
            value = 0.20 + 0.05 * sibling_index + 0.001 * parent_index
            output.append(
                core.CandidateLabel(
                    candidate_id=f"P{parent_index:02d}_C{sibling_index:02d}",
                    parent_cluster_id=f"P{parent_index:02d}",
                    true_r8=value + 0.02,
                    true_r9=value,
                )
            )
    return output


def calibration_rows(count: int = 80, outer_fold: int = 2):
    output = []
    for index in range(count):
        x8 = 0.10 + 0.006 * index
        x9 = 0.14 + 0.005 * index
        output.append(
            core.CalibrationRow(
                candidate_id=f"C{index:03d}",
                parent_cluster_id=f"P{index % 10:02d}",
                outer_fold=outer_fold,
                fit_role=core.CALIBRATION_FIT_ROLE,
                predicted_r8=x8,
                predicted_r9=x9,
                true_r8=1.18 * x8 + 0.025,
                true_r9=0.82 * x9 - 0.018,
            )
        )
    return output


class BindingAndDualTests(unittest.TestCase):
    def test_authoritative_delta_noise_binding(self):
        receipt = core.verify_frozen_delta_noise_binding(BINDING)
        self.assertEqual(receipt["binding_sha256"], core.FROZEN_BINDING_SHA256)
        self.assertEqual(receipt["frozen_12_decimal_delta_noise"], 0.019614956149)
        self.assertEqual(receipt["v4_f_or_test32_results_accessed"], 0)

    def test_mutated_binding_is_rejected(self):
        payload = json.loads(BINDING.read_text())
        payload["delta_noise"] = 0.02
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binding.json"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(core.RankCalibrationError, "sha256_mismatch"):
                core.verify_frozen_delta_noise_binding(path)

    def test_softmin_fp32_equality_gradient_and_exact_min(self):
        values = torch.tensor([0.2, 0.7], dtype=torch.bfloat16, requires_grad=True)
        smooth = core.normalized_softmin(values, values)
        self.assertEqual(smooth.dtype, torch.float32)
        self.assertTrue(torch.allclose(smooth, values.float(), atol=1e-6))
        smooth.sum().backward()
        self.assertTrue(torch.all(torch.isfinite(values.grad)))
        receptor = torch.tensor([[0.55, 0.57], [0.42, 0.31]])
        self.assertTrue(torch.equal(core.exact_min_dual(receptor), torch.tensor([0.55, 0.31])))

    def test_softmin_extreme_bf16_is_finite(self):
        left = torch.tensor([-1000.0, 1000.0], dtype=torch.bfloat16)
        right = torch.tensor([1000.0, -1000.0], dtype=torch.bfloat16)
        self.assertTrue(torch.all(torch.isfinite(core.normalized_softmin(left, right))))


class ParentPairEpochCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding = core.verify_frozen_delta_noise_binding(BINDING)

    def build(self, **kwargs):
        selected_labels = kwargs.pop("labels", labels())
        outer_fold = kwargs.get("outer_fold", 1)
        inner_fold = kwargs.get("inner_fold", 3)
        defaults = dict(
            labels=selected_labels,
            base_seed=1931,
            outer_fold=outer_fold,
            inner_fold=inner_fold,
            epoch=4,
            scalar_optimizer_steps=7,
            binding_receipt=self.binding,
            expected_training_split_sha256=core.compute_training_split_sha256(
                selected_labels, outer_fold, inner_fold
            ),
            expected_label_sha256=core.compute_label_sha256(selected_labels),
        )
        defaults.update(kwargs)
        return core.build_parent_pair_epoch_cache(**defaults)

    def test_exact_eight_per_step_parent_round_robin_and_determinism(self):
        first = self.build()
        second = self.build()
        self.assertEqual(first.cache_content_sha256, second.cache_content_sha256)
        self.assertEqual(len(first.records), 56)
        for step in range(7):
            batch = first.step_pairs(step)
            self.assertEqual(len(batch), 8)
            self.assertEqual(len({record.parent_cluster_id for record in batch}), 8)
        counts = dict(first.emitted_pairs_per_parent).values()
        self.assertLessEqual(max(counts) - min(counts), 1)
        self.assertLessEqual(len(core.deduplicated_pair_endpoints(first.step_pairs(0))), 16)

    def test_seed_and_label_mutations_change_hash(self):
        original = self.build()
        different_seed = self.build(base_seed=1932)
        self.assertNotEqual(original.cache_content_sha256, different_seed.cache_content_sha256)
        mutated = labels()
        mutated[0] = dataclasses.replace(mutated[0], true_r9=mutated[0].true_r9 + 0.02)
        different_label = self.build(labels=mutated)
        self.assertNotEqual(original.label_sha256, different_label.label_sha256)
        self.assertNotEqual(original.cache_content_sha256, different_label.cache_content_sha256)
        with self.assertRaisesRegex(core.RankCalibrationError, "label_sha256_mismatch"):
            self.build(labels=mutated, expected_label_sha256=original.label_sha256)

    def test_split_firewall_rejects_nontrain_and_forbidden(self):
        leaked = labels()
        leaked[0] = dataclasses.replace(leaked[0], split_role="OUTER_TEST")
        with self.assertRaisesRegex(core.RankCalibrationError, "nontrain_candidate"):
            self.build(labels=leaked)
        with self.assertRaisesRegex(core.RankCalibrationError, "forbidden_candidate"):
            self.build(forbidden_candidate_ids={labels()[0].candidate_id})

    def test_unverified_binding_and_too_few_eligible_parents_fail_closed(self):
        bad_receipt = dict(self.binding)
        bad_receipt["binding_sha256"] = "0" * 64
        with self.assertRaisesRegex(core.RankCalibrationError, "unverified_delta_noise"):
            self.build(binding_receipt=bad_receipt)
        with self.assertRaisesRegex(core.RankCalibrationError, "below_8"):
            self.build(labels=labels(parent_count=7))

    def test_below_noise_pairs_are_discarded_and_cache_tamper_detected(self):
        data = labels()
        # Add an adjacent sibling below the noise margin to every parent.
        for parent_index in range(10):
            data.append(
                core.CandidateLabel(
                    candidate_id=f"P{parent_index:02d}_NEAR",
                    parent_cluster_id=f"P{parent_index:02d}",
                    true_r8=0.221,
                    true_r9=0.201,
                )
            )
        cache = self.build(labels=data)
        self.assertGreater(cache.noise_margin_discard_count, 0)
        tampered_record = dataclasses.replace(cache.records[0], pair_weight=cache.records[0].pair_weight + 0.1)
        tampered = dataclasses.replace(cache, records=(tampered_record,) + cache.records[1:])
        with self.assertRaises(core.RankCalibrationError):
            tampered.verify()

    def test_persisted_cache_has_audit_and_zero_sealed_access(self):
        cache = self.build()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CACHE.json"
            cache.write_json(path)
            payload = json.loads(path.read_text())
            replay = core.load_parent_pair_epoch_cache(
                path,
                expected_training_split_sha256=cache.training_split_sha256,
                expected_label_sha256=cache.label_sha256,
            )
            self.assertEqual(replay.cache_content_sha256, cache.cache_content_sha256)
            payload["records"][0]["pair_weight"] += 0.01
            path.write_text(json.dumps(payload))
            with self.assertRaises(core.RankCalibrationError):
                core.load_parent_pair_epoch_cache(
                    path,
                    expected_training_split_sha256=cache.training_split_sha256,
                    expected_label_sha256=cache.label_sha256,
                )
        self.assertEqual(payload["cache_content_sha256"], cache.cache_content_sha256)
        self.assertEqual(payload["v4_f_or_test32_results_accessed"], 0)
        self.assertEqual(payload["delta_noise"], core.FROZEN_DELTA_NOISE)


class PairLogitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        receipt = core.verify_frozen_delta_noise_binding(BINDING)
        cls.cache = core.build_parent_pair_epoch_cache(
            labels(), base_seed=43, outer_fold=0, inner_fold=0, epoch=0,
            scalar_optimizer_steps=1, binding_receipt=receipt,
            expected_training_split_sha256=core.compute_training_split_sha256(labels(), 0, 0),
            expected_label_sha256=core.compute_label_sha256(labels()),
        )

    def predictions(self, correct: bool):
        rows = labels()
        values = torch.tensor(
            [[row.true_dual, row.true_dual] if correct else [-row.true_dual, -row.true_dual] for row in rows],
            requires_grad=True,
        )
        batch = core.build_softmin_dual_prediction_batch([row.candidate_id for row in rows], values)
        return batch, values

    def test_correct_order_has_lower_loss_and_gradient(self):
        records = self.cache.step_pairs(0)
        correct, correct_receptors = self.predictions(True)
        reversed_predictions, _ = self.predictions(False)
        correct_loss = core.noise_aware_pairlogit(correct, records)
        reversed_loss = core.noise_aware_pairlogit(reversed_predictions, records)
        self.assertEqual(correct_loss.dtype, torch.float32)
        self.assertLess(float(correct_loss.detach()), float(reversed_loss.detach()))
        correct_loss.backward()
        self.assertIsNotNone(correct_receptors.grad)
        self.assertTrue(torch.all(torch.isfinite(correct_receptors.grad)))

    def test_missing_endpoint_and_short_batch_fail_closed(self):
        records = self.cache.step_pairs(0)
        predictions, _ = self.predictions(True)
        missing_id = records[0].left_candidate_id
        keep = [index for index, candidate_id in enumerate(predictions.candidate_ids) if candidate_id != missing_id]
        predictions = core.SoftminDualPredictionBatch(
            candidate_ids=tuple(predictions.candidate_ids[index] for index in keep),
            values=predictions.values[keep],
            tau=core.SOFTMIN_TAU,
        )
        with self.assertRaisesRegex(core.RankCalibrationError, "prediction_missing"):
            core.noise_aware_pairlogit(predictions, records)
        with self.assertRaisesRegex(core.RankCalibrationError, "not_exactly_eight"):
            core.noise_aware_pairlogit(self.predictions(True)[0], records[:7])
        with self.assertRaisesRegex(core.RankCalibrationError, "typed_softmin"):
            core.noise_aware_pairlogit({}, records)


class FoldLocalCalibrationTests(unittest.TestCase):
    def test_positive_affine_fit_improves_both_receptors_and_exact_min(self):
        model = core.fit_fold_local_positive_affine(calibration_rows(), outer_fold=2)
        self.assertEqual(model.r8.status, "FITTED_POSITIVE_AFFINE")
        self.assertEqual(model.r9.status, "FITTED_POSITIVE_AFFINE")
        self.assertLess(model.r8.raw_huber_fitted, model.r8.raw_huber_identity)
        self.assertLess(model.r9.raw_huber_fitted, model.r9.raw_huber_identity)
        predictions = torch.tensor([[0.2, 0.4], [0.7, 0.3]], dtype=torch.bfloat16)
        output = model.apply(predictions)
        self.assertEqual(output["calibrated_receptor_predictions"].dtype, torch.float32)
        self.assertTrue(
            torch.equal(output["exact_min_dual"], output["calibrated_receptor_predictions"].min(1).values)
        )

    def test_identity_fallback_for_insufficient_support(self):
        model = core.fit_fold_local_positive_affine(
            calibration_rows(count=8), outer_fold=2, minimum_rows=16, minimum_parents=4
        )
        self.assertEqual(model.r8.status, "IDENTITY_FALLBACK")
        self.assertEqual(model.r8.fallback_reason, "INSUFFICIENT_ROWS")
        self.assertEqual((model.r8.slope, model.r8.intercept), (1.0, 0.0))

    def test_outer_test_role_and_forbidden_candidate_are_rejected(self):
        rows = calibration_rows()
        rows[0] = dataclasses.replace(rows[0], fit_role="OUTER_TEST")
        with self.assertRaisesRegex(core.RankCalibrationError, "fit_role_invalid"):
            core.fit_fold_local_positive_affine(rows, outer_fold=2)
        with self.assertRaisesRegex(core.RankCalibrationError, "outer_test_candidate"):
            core.fit_fold_local_positive_affine(
                calibration_rows(), outer_fold=2, forbidden_candidate_ids={"C000"}
            )

    def test_wrong_fold_duplicate_nonfinite_and_parameter_mutation_rejected(self):
        rows = calibration_rows()
        rows[0] = dataclasses.replace(rows[0], outer_fold=3)
        with self.assertRaisesRegex(core.RankCalibrationError, "outer_fold_mismatch"):
            core.fit_fold_local_positive_affine(rows, outer_fold=2)
        duplicated = calibration_rows() + [calibration_rows()[0]]
        with self.assertRaisesRegex(core.RankCalibrationError, "duplicate_calibration"):
            core.fit_fold_local_positive_affine(duplicated, outer_fold=2)
        nonfinite = calibration_rows()
        nonfinite[0] = dataclasses.replace(nonfinite[0], true_r8=float("nan"))
        with self.assertRaisesRegex(core.RankCalibrationError, "nonfinite"):
            core.fit_fold_local_positive_affine(nonfinite, outer_fold=2)
        model = core.fit_fold_local_positive_affine(calibration_rows(), outer_fold=2)
        broken = dataclasses.replace(model, r8=dataclasses.replace(model.r8, slope=1.7))
        with self.assertRaisesRegex(core.RankCalibrationError, "slope_bounds"):
            broken.validate()

    def test_fit_hash_changes_on_label_mutation_and_payload_sealed(self):
        original = core.fit_fold_local_positive_affine(calibration_rows(), outer_fold=2)
        changed_rows = calibration_rows()
        changed_rows[0] = dataclasses.replace(changed_rows[0], true_r8=changed_rows[0].true_r8 + 0.001)
        changed = core.fit_fold_local_positive_affine(changed_rows, outer_fold=2)
        self.assertNotEqual(original.fit_data_sha256, changed.fit_data_sha256)
        payload = original.to_payload()
        self.assertEqual(payload["v4_f_or_test32_results_accessed"], 0)
        self.assertEqual(payload["derived_inference_target"], "exact_min(calibrated_R8,calibrated_R9)")


class ContractTests(unittest.TestCase):
    def test_contract_declares_no_independent_dual_or_outer_fit(self):
        contract = core.implementation_contract()
        self.assertFalse(contract["dual"]["independent_Rdual_output_allowed"])
        self.assertTrue(contract["forbidden"]["outer_test_fit_or_recalibration"])
        self.assertTrue(contract["forbidden"]["exact_min_in_rank_loss"])
        self.assertEqual(contract["v4_f_or_test32_results_accessed"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
