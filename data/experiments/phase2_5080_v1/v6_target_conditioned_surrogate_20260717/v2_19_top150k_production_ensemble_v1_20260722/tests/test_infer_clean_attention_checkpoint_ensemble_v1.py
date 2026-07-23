from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/infer_clean_attention_checkpoint_ensemble_v1.py"
V6_ROOT = ROOT.parent
BASE_SOURCE = V6_ROOT / "v2_12_clean_attention_inner_oof_stack_v1_20260722/src/run_clean_attention_inner_oof_fold_v1.py"
BASE_TEST_SOURCE = V6_ROOT / "v2_12_clean_attention_inner_oof_stack_v1_20260722/tests/test_run_clean_attention_inner_oof_fold_v1.py"


def import_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


MOD = import_module("v219_production_clean_attention_ensemble", SOURCE)
BASE = import_module("v219_clean_attention_training_base", BASE_SOURCE)
FIXTURE_MODULE = import_module("v219_clean_attention_training_fixture", BASE_TEST_SOURCE)


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProductionFixture:
    def __init__(self, root: Path):
        self.root = root
        self.training_fixture = FIXTURE_MODULE.Fixture(root / "training_fixture")
        self.training_fixture.root.mkdir(exist_ok=True)

    @classmethod
    def create(cls, root: Path) -> "ProductionFixture":
        # The inherited fixture expects its root to exist before construction.
        (root / "training_fixture").mkdir(parents=True)
        self = object.__new__(cls)
        self.root = root
        self.training_fixture = FIXTURE_MODULE.Fixture(root / "training_fixture")
        self.checkpoint1 = self.training_fixture.output / BASE.CHECKPOINT_NAME
        BASE.train(self.training_fixture.args())
        payload = torch.load(self.checkpoint1, map_location="cpu", weights_only=True)
        payload["seed"] = 917
        payload["split_id"] = "tiny_D1_second_head"
        state = dict(payload["head_state_dict"])
        bias_key = "scalar_head.4.bias"
        assert bias_key in state
        state[bias_key] = state[bias_key].clone() + torch.tensor([0.04, -0.03])
        payload["head_state_dict"] = state
        self.checkpoint2 = root / "second_head.pt"
        torch.save(payload, self.checkpoint2)
        self.manifest = root / "compact.tsv"
        compact = [{field: row[field] for field in MOD.COMPACT_FIELDS} for row in self.training_fixture.rows]
        write_tsv(self.manifest, list(MOD.COMPACT_FIELDS), compact)
        self.output = root / "production_output"
        return self

    def args(self) -> argparse.Namespace:
        return argparse.Namespace(
            manifest=self.manifest,
            expected_rows=8,
            graph_cache_dir=self.training_fixture.graph_cache,
            reference_contract=self.training_fixture.contract,
            base_module=BASE_SOURCE,
            checkpoint=[self.checkpoint1, self.checkpoint2],
            output_dir=self.output,
            device="cpu",
            batch_size=3,
            precision="fp32",
            uncertainty_penalty=1.0,
            backbone_kind="tiny",
            backbone_dtype="fp32",
            model_path=None,
            model_identity_file=None,
            expected_model_sha256=None,
            tiny_hidden_size=16,
            tiny_e2e=True,
        )


class CleanAttentionProductionInferenceTests(unittest.TestCase):
    def test_multicheckpoint_inference_reuses_backbone_and_has_exact_min(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductionFixture.create(Path(temporary))
            receipt = MOD.infer(fixture.args())
            self.assertEqual(receipt["status"], MOD.STATUS)
            self.assertEqual(receipt["counts"]["rows"], 8)
            self.assertEqual(receipt["counts"]["checkpoints"], 2)
            self.assertEqual(receipt["inference"]["backbone_forward_batches"], 3)
            self.assertEqual(receipt["inference"]["head_forward_batches"], 6)
            self.assertTrue(receipt["inference"]["shared_backbone_once_per_batch"])
            self.assertLessEqual(receipt["inference"]["exact_min_max_abs_error"], 1e-7)
            self.assertEqual(receipt["input_firewall"]["truth_fields_read"], 0)
            self.assertEqual(receipt["input_firewall"]["docking_pose_files_opened"], 0)

            output = fixture.output / MOD.OUTPUT_NAME
            with output.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                fields = list(reader.fieldnames or ())
                rows = list(reader)
            self.assertEqual(len(rows), 8)
            self.assertFalse(any("target_" in field or "truth" in field for field in fields))
            self.assertEqual(sorted(int(row["ensemble_conservative_rank"]) for row in rows), list(range(1, 9)))
            for row in rows:
                for prefix in ("checkpoint_000", "checkpoint_001"):
                    self.assertAlmostEqual(
                        float(row[f"{prefix}_R_dual_min"]),
                        min(float(row[f"{prefix}_R_8X6B"]), float(row[f"{prefix}_R_9E6Y"])),
                        places=8,
                    )
                self.assertEqual(row["ensemble_checkpoint_count"], "2")
                self.assertEqual(row["claim_boundary"], MOD.CLAIM_BOUNDARY)
            self.assertTrue((fixture.output / MOD.RECEIPT_NAME).is_file())
            self.assertTrue((fixture.output / MOD.SHA256_NAME).is_file())
            sums = (fixture.output / MOD.SHA256_NAME).read_text(encoding="utf-8")
            self.assertIn(sha256(output), sums)

    def test_truth_column_in_compact_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductionFixture.create(Path(temporary))
            rows = []
            for source in fixture.training_fixture.rows:
                row = {field: source[field] for field in MOD.COMPACT_FIELDS}
                row["R_dual_min"] = source["R_dual_min"]
                rows.append(row)
            write_tsv(fixture.manifest, list(MOD.COMPACT_FIELDS) + ["R_dual_min"], rows)
            with self.assertRaisesRegex(MOD.ProductionInferenceError, "compact_manifest_fields_exact_required"):
                MOD.infer(fixture.args())

    def test_checkpoint_backbone_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductionFixture.create(Path(temporary))
            payload = torch.load(fixture.checkpoint2, map_location="cpu", weights_only=True)
            payload["backbone_identity_sha256"] = "not_the_tiny_backbone"
            torch.save(payload, fixture.checkpoint2)
            with self.assertRaisesRegex(MOD.ProductionInferenceError, "tiny_checkpoint_identity_invalid"):
                MOD.infer(fixture.args())

    def test_graph_candidate_exact_closure_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductionFixture.create(Path(temporary))
            fixture.expected_rows = 7
            with fixture.manifest.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))[:7]
            write_tsv(fixture.manifest, list(MOD.COMPACT_FIELDS), rows)
            args = fixture.args()
            args.expected_rows = 7
            with self.assertRaisesRegex(Exception, "graph_candidate_exact_closure"):
                MOD.infer(args)

    def test_existing_output_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ProductionFixture.create(Path(temporary))
            fixture.output.mkdir()
            with self.assertRaisesRegex(MOD.ProductionInferenceError, "output_dir_exists"):
                MOD.infer(fixture.args())


if __name__ == "__main__":
    unittest.main()
