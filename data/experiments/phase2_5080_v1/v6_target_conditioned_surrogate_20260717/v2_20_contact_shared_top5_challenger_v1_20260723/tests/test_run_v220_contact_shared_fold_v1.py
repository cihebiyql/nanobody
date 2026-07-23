from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load(ROOT / "src" / "run_v220_contact_shared_fold_v1.py", "v220_fold_test")
paired = load(
    ROOT / "src" / "materialize_v220_paired_initial_state_v1.py",
    "v220_paired_test",
)
base = load(
    ROOT.parents[0]
    / "v2_13_top5_enrichment_v1_20260722"
    / "src"
    / "run_top5_clean_attention_fold_v1.py",
    "v213_base_test",
)
model_module = load(
    ROOT.parents[0]
    / "v2_5_ortho_contact_pose_stack_v1_20260718"
    / "model"
    / "residue_model_v2_5_ortho.py",
    "residue_model_v2_5_ortho",
)
trainer = load(
    ROOT.parents[0]
    / "v2_5_ortho_contact_pose_stack_v1_20260718"
    / "trainer"
    / "train_v2_5_ortho_heads.py",
    "v220_trainer_test",
)
BACKBONE_IDENTITY = hashlib.sha256(b"tiny_synthetic").hexdigest()


class GraphStoreStub:
    edge_feature_dim = 3

    def __init__(self, rows):
        self.rows = {row.candidate_id: row for row in rows}

    def graph(self, candidate_id):
        length = len(self.rows[candidate_id].sequence)
        source, target = [], []
        for index in range(length - 1):
            source.extend((index, index + 1))
            target.extend((index + 1, index))
        edges = len(source)
        return {
            "aa_index": np.arange(length, dtype=np.int64) % 20,
            "region_index": np.arange(length, dtype=np.int64) % 4,
            "confidence": np.full(length, 0.9, dtype=np.float32),
            "edge_index": np.asarray((source, target), dtype=np.int64),
            "edge_features": np.full((edges, 3), 0.2, dtype=np.float32),
        }


class TeacherStoreStub:
    def __init__(self, contact_ids, target_nodes):
        self.contact_ids = set(contact_ids)
        self.target_nodes = dict(target_nodes)
        self.augment_calls = []
        self._audit = {
            "status": "PASS_OUTER_FIT_ONLY_CONTACT_TEACHER_STORE",
            "score_parent_numeric_int_parse_count": 0,
            "score_parent_numeric_float_parse_count": 0,
            "counts": {"fit_teacher_candidates": len(self.contact_ids)},
        }

    @property
    def audit(self):
        return dict(self._audit)

    def augment_batch(self, batch, selected_rows, residue_mask):
        self.augment_calls.append([row.candidate_id for row in selected_rows])
        result = dict(batch)
        mask = residue_mask.bool()
        batch_size, width = mask.shape
        marginal_targets = torch.zeros((batch_size, width, 2), dtype=torch.float32)
        marginal_mask = torch.zeros_like(marginal_targets, dtype=torch.bool)
        marginal_uncertainty = torch.ones_like(marginal_targets)
        marginal_tier = torch.zeros(batch_size)
        pair_tier = torch.zeros(batch_size)
        for item, row in enumerate(selected_rows):
            if row.candidate_id not in self.contact_ids:
                continue
            positions = torch.nonzero(mask[item], as_tuple=False).flatten()
            marginal_mask[item, positions, :] = True
            marginal_targets[item, positions, :] = (
                torch.arange(len(positions)).float().remainder(2)[:, None]
            )
            marginal_tier[item] = 1.0
            pair_tier[item] = 1.0
        result.update(
            {
                "marginal_targets": marginal_targets,
                "marginal_mask": marginal_mask,
                "marginal_uncertainty": marginal_uncertainty,
                "marginal_tier_weights": marginal_tier,
                "pair_tier_weights": pair_tier,
            }
        )
        for receptor in ("8x6b", "9e6y"):
            nodes = self.target_nodes[receptor]
            target = torch.zeros((batch_size, width, nodes), dtype=torch.float32)
            pair_mask = torch.zeros_like(target, dtype=torch.bool)
            uncertainty = torch.ones_like(target)
            for item, row in enumerate(selected_rows):
                if row.candidate_id not in self.contact_ids:
                    continue
                positions = torch.nonzero(mask[item], as_tuple=False).flatten()
                pair_mask[item, positions, :] = True
                for offset, position in enumerate(positions):
                    target[item, position, offset % nodes] = 1.0
            result[f"pair_targets_{receptor}"] = target
            result[f"pair_mask_{receptor}"] = pair_mask
            result[f"pair_uncertainty_{receptor}"] = uncertainty
        return result


def target_graph(nodes: int):
    source, target = [], []
    for index in range(nodes - 1):
        source.extend((index, index + 1))
        target.extend((index + 1, index))
    return {
        "node_features": torch.randn(nodes, 4),
        "edge_index": torch.tensor((source, target), dtype=torch.long),
        "edge_features": torch.full((len(source), 3), 0.1),
        "interface_mask": torch.ones(nodes, dtype=torch.bool),
        "hotspot_mask": torch.arange(nodes).remainder(2).bool(),
    }


def make_rows():
    rows = []
    parents = ["FIT_A"] * 8 + ["FIT_B"] * 8 + ["SCORE_A"] * 2 + ["SCORE_B"] * 2
    for index, parent in enumerate(parents):
        sequence = "ACDE" if index % 2 == 0 else "FGHI"
        digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        r8 = 0.15 + index * 0.01
        r9 = 0.18 + (index % 7) * 0.012
        rows.append(
            base.CandidateRow(
                f"C{index:03d}", digest, sequence, parent, 1.0, (r8, r9)
            )
        )
    return rows


def build_model():
    base.seed_everything(43)
    backbone = base.TinyBackbone(8)
    for parameter in backbone.parameters():
        parameter.requires_grad_(False)
    config = model_module.ResidueV25OrthoConfig.for_lane(
        runner.LANE,
        backbone_hidden_size=8,
        target_node_dim=4,
        edge_feature_dim=3,
        graph_hidden_dim=8,
        dropout=0.0,
        enable_contact_evidence=True,
        contact_encoder_gradient="shared",
    )
    return trainer.build_model(runner.LANE, backbone, config)


class CaptureCalibrator:
    def __init__(self):
        self.calls = []

    def __call__(
        self, model, adapter, batches, target_graphs, device, precision, grid
    ):
        eligible = [item["batch_id"] for item in batches if item["contact_eligible"]]
        self.calls.append(eligible[:8])
        return {
            "status": "PASS_CONTACT_WEIGHT_CALIBRATED_NO_OPTIMIZER",
            "selected_contact_weight": 0.000625,
            "selected_batch_ids": eligible[:8],
            "lambda_grid": list(grid),
            "optimizer_created": False,
            "optimizer_steps": 0,
            "training_started": False,
        }


class V220FoldRunnerTests(unittest.TestCase):
    def make_inputs(self, rows, split, targets, teacher_store):
        return runner.FoldInputs(
            base=base,
            trainer=trainer,
            model=build_model(),
            tokenizer=base.TinyTokenizer(),
            rows=rows,
            split=split,
            graph_store=GraphStoreStub(rows),
            target_graphs=targets,
            teacher_store=teacher_store,
            model_identity=BACKBONE_IDENTITY,
        )

    def test_tiny_paired_c0_c1_end_to_end(self) -> None:
        rows = make_rows()
        split = base.Split(
            tuple(range(16)),
            tuple(range(16, 20)),
            ("FIT_A", "FIT_B"),
            ("SCORE_A", "SCORE_B"),
            "tiny_fold_0",
        )
        targets = {"8x6b": target_graph(5), "9e6y": target_graph(5)}
        teacher_store = TeacherStoreStub(
            [row.candidate_id for row in rows[:16]], {"8x6b": 5, "9e6y": 5}
        )
        calibrator = CaptureCalibrator()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = root / "initial.pt"
            initial_receipt = paired.save_paired_initial_state(
                initial,
                build_model(),
                0,
                43,
                backbone_identity_sha256=BACKBONE_IDENTITY,
            )
            initial_receipt_path = Path(f"{initial}.receipt.json")
            results = {}
            for arm in ("C0", "C1"):
                inputs = self.make_inputs(rows, split, targets, teacher_store)
                config = runner.FoldConfig(
                    arm=arm,
                    fold_id=0,
                    output_dir=root / arm,
                    initial_state_path=initial,
                    initial_state_receipt_path=initial_receipt_path,
                    expected_initial_state_sha256=initial_receipt[
                        "serialized_checkpoint_sha256"
                    ],
                    expected_initial_state_receipt_sha256=paired.file_sha256(
                        initial_receipt_path
                    ),
                    device="cpu",
                    seed=43,
                    epochs=1,
                    batch_size=2,
                    eval_batch_size=2,
                    gradient_accumulation=2,
                    precision="fp32",
                    learning_rate=1e-3,
                    weight_decay=0.0,
                    gradient_clip=1.0,
                    tiny_e2e=True,
                )
                results[arm] = runner.run_fold_core(
                    config,
                    inputs,
                    paired_module=paired,
                    calibrator=calibrator,
                )

            c0, c1 = results["C0"], results["C1"]
            self.assertEqual(
                c0["pairing"]["initial_state_hashes"],
                c1["pairing"]["initial_state_hashes"],
            )
            self.assertEqual(
                c0["pairing"]["serialized_initial_state_scope"], "model.head"
            )
            self.assertEqual(
                c0["pairing"]["backbone_binding"],
                c1["pairing"]["backbone_binding"],
            )
            self.assertFalse(
                c0["pairing"]["backbone_binding"]["serialized_in_checkpoint"]
            )
            self.assertEqual(
                c0["pairing"]["optimizer_group_sha256"],
                c1["pairing"]["optimizer_group_sha256"],
            )
            self.assertEqual(
                c0["pairing"]["epoch_batch_order_sha256"],
                c1["pairing"]["epoch_batch_order_sha256"],
            )
            self.assertEqual(c0["contact_weights"]["applied_marginal_weight"], 0.0)
            self.assertEqual(c0["contact_weights"]["applied_pair_weight"], 0.0)
            self.assertEqual(
                c1["contact_weights"]["applied_marginal_weight"], 0.000625
            )
            self.assertEqual(
                c1["contact_weights"]["applied_pair_weight"], 0.0003125
            )
            self.assertEqual(calibrator.calls[0], calibrator.calls[1])
            self.assertEqual(len(calibrator.calls[0]), 8)
            self.assertTrue(c0["exact_min_inference"] and c1["exact_min_inference"])
            self.assertEqual(
                c1["teacher_store_audit"]["score_parent_numeric_float_parse_count"],
                0,
            )
            for arm in ("C0", "C1"):
                output = root / arm
                for name in (
                    runner.PREDICTION_NAME,
                    runner.CHECKPOINT_NAME,
                    runner.HISTORY_NAME,
                    runner.RESULT_NAME,
                    runner.CALIBRATION_NAME,
                ):
                    self.assertTrue((output / name).is_file())
                with (output / runner.PREDICTION_NAME).open() as handle:
                    records = list(csv.DictReader(handle, delimiter="\t"))
                self.assertEqual(len(records), 4)
                authoritative = {row.candidate_id: row.targets for row in rows}
                for record in records:
                    expected_truth = authoritative[record["candidate_id"]]
                    self.assertEqual(
                        record["target_R_8X6B"], f"{expected_truth[0]:.12g}"
                    )
                    self.assertEqual(
                        record["target_R_9E6Y"], f"{expected_truth[1]:.12g}"
                    )
                    self.assertEqual(
                        record["target_R_dual_min"], f"{min(expected_truth):.12g}"
                    )
                    exact = min(
                        float(record["prediction_R_8X6B"]),
                        float(record["prediction_R_9E6Y"]),
                    )
                    self.assertAlmostEqual(
                        exact, float(record["prediction_R_dual_min"]), places=7
                    )

    def test_production_hyperparameters_fail_closed(self) -> None:
        config = runner.FoldConfig(
            arm="C1",
            fold_id=0,
            output_dir=Path("unused"),
            initial_state_path=Path("unused"),
            initial_state_receipt_path=Path("unused.receipt.json"),
            expected_initial_state_sha256="0" * 64,
            expected_initial_state_receipt_sha256="1" * 64,
            epochs=7,
        )
        with self.assertRaises(runner.V220FoldError):
            config.validate()
        for kwargs in ({"graph_hidden_dim": 64}, {"dropout": 0.2}):
            with self.subTest(**kwargs):
                drifted = runner.FoldConfig(
                    arm="C1",
                    fold_id=0,
                    output_dir=Path("unused"),
                    initial_state_path=Path("unused"),
                    initial_state_receipt_path=Path("unused.receipt"),
                    expected_initial_state_sha256="a" * 64,
                    expected_initial_state_receipt_sha256="b" * 64,
                    **kwargs,
                )
                with self.assertRaises(runner.V220FoldError):
                    drifted.validate()

    def test_teacher_audit_rejects_outer_score_numeric_access(self) -> None:
        store = TeacherStoreStub([], {"8x6b": 5, "9e6y": 5})
        store._audit["score_parent_numeric_float_parse_count"] = 1
        with self.assertRaises(runner.V220FoldError):
            runner._teacher_audit(store)

    def test_batch_order_hash_is_deterministic_and_seed_sensitive(self) -> None:
        rows = make_rows()
        collator = lambda indices: {"indices": torch.tensor(indices)}
        first = runner._batch_order(base, tuple(range(16)), collator, 2, 43)
        repeat = runner._batch_order(base, tuple(range(16)), collator, 2, 43)
        changed = runner._batch_order(base, tuple(range(16)), collator, 2, 44)
        self.assertEqual(
            runner.batch_order_sha256(rows, first),
            runner.batch_order_sha256(rows, repeat),
        )
        self.assertNotEqual(
            runner.batch_order_sha256(rows, first),
            runner.batch_order_sha256(rows, changed),
        )


if __name__ == "__main__":
    unittest.main()
