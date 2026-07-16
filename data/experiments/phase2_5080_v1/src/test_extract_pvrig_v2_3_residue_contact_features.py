#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "extract_pvrig_v2_3_residue_contact_features.py"
SPEC = importlib.util.spec_from_file_location("extract_pvrig_v2_3_residue_contact_features", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)

from train_phase2_v2_3 import Config, CrossContactNetV23, seq_hash  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class LabelFreeResidueFeatureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = "ACDEFGHIK"
        self.sequences = ("LMNPQRSTV", "WYACDEFGHI")
        self.candidates = self.root / "candidates.csv"
        rows = []
        for index, sequence in enumerate(self.sequences, start=1):
            cdr1, cdr2, cdr3 = sequence[1:3], sequence[4:6], sequence[7:9]
            rows.append(
                {
                    "candidate_id": f"candidate-{index}",
                    "sequence_sha256": seq_hash(sequence),
                    "vhh_seq": sequence,
                    "cdr1": cdr1,
                    "cdr2": cdr2,
                    "cdr3": cdr3,
                    "cdr1_span_0based": "1-3",
                    "cdr2_span_0based": "4-6",
                    "cdr3_span_0based": "7-9",
                    "parent_framework_cluster": f"C{index:04d}",
                    "design_method": "synthetic",
                    "design_mode": "H3",
                    "target_patch_id": "A_CENTER",
                }
            )
        write_csv(self.candidates, rows)
        self.target_fasta = self.root / "target.fasta"
        self.target_fasta.write_text(f">target\n{self.target}\n", encoding="utf-8")
        self.hotspots = self.root / "hotspots.tsv"
        write_csv(
            self.root / "hotspots.csv",
            [
                {
                    "hotspot_id": "h1", "hotspot_class": "core_hotspot",
                    "priority_weight": "1.0", "uniprot_position": "40", "uniprot_aa": "C",
                },
                {
                    "hotspot_id": "h2", "hotspot_class": "secondary_hotspot",
                    "priority_weight": "0.7", "uniprot_position": "43", "uniprot_aa": "F",
                },
            ],
        )
        # Exercise the production TSV contract rather than relying on the suffix fallback.
        csv_rows, fields = MOD.read_csv(self.root / "hotspots.csv")
        with self.hotspots.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            writer.writerows(csv_rows)
        self.masks = self.root / "masks.csv"
        mask_rows = []
        for sequence in self.sequences:
            values = [0, 1, 1, 0, 2, 2, 0, 3, 3] + ([0] if len(sequence) == 10 else [])
            mask_rows.append(
                {
                    "sequence_hash": seq_hash(sequence),
                    "vhh_seq": sequence,
                    "vhh_len": len(sequence),
                    "cdr_mask_json": json.dumps(values),
                    "spans_json": json.dumps({"cdr1": [1, 3], "cdr2": [4, 6], "cdr3": [7, 9]}),
                    "cdr1_seq": sequence[1:3],
                    "cdr2_seq": sequence[4:6],
                    "cdr3_seq": sequence[7:9],
                    "status": "exact_annotation",
                }
            )
        write_csv(self.masks, mask_rows)
        self.cache_dir = self.root / "cache"
        self.cache_dir.mkdir()
        cfg = self.config(seed=1)
        shard = {}
        cache_rows = []
        for index, sequence in enumerate((*self.sequences, self.target), start=1):
            digest = seq_hash(sequence)
            shard[digest] = torch.full((len(sequence), cfg.esm_dim), index / 10.0, dtype=torch.float16)
            cache_rows.append(
                {
                    "sequence_sha256": digest,
                    "sequence_length": len(sequence),
                    "cached_length": len(sequence),
                    "truncation_policy": "none",
                    "chain_type": "antigen" if sequence == self.target else "vhh",
                    "shard_path": "shard_00000.pt",
                    "shard_key": digest,
                }
            )
        torch.save(shard, self.cache_dir / "shard_00000.pt")
        self.cache_manifest = self.cache_dir / "manifest.csv"
        write_csv(self.cache_manifest, cache_rows)
        torch.manual_seed(17)
        model = CrossContactNetV23(cfg)
        state = model.state_dict()
        self.checkpoints = []
        for seed in (1, 2, 3):
            checkpoint = self.root / f"seed{seed}.pt"
            seed_cfg = self.config(seed=seed)
            seed_state = {name: tensor.clone() for name, tensor in state.items()}
            seed_state["para.bias"] += seed * 0.1
            seed_state["epi.bias"] += seed * 0.05
            seed_state["contact_bias_v.bias"] += seed * 0.08
            seed_state["pair.5.bias"] += seed * 0.12
            torch.save(
                {"model": seed_state, "cfg": asdict(seed_cfg), "epoch": seed, "best_score": 1.0 + seed / 10},
                checkpoint,
            )
            self.checkpoints.append(checkpoint)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def config(seed: int) -> Config:
        return Config(
            seed=seed,
            d_model=16,
            esm_dim=8,
            contact_dim=8,
            layers=1,
            cross_layers=1,
            heads=2,
            dropout=0.0,
            max_vhh_len=16,
            max_antigen_len=16,
        )

    def common(self) -> dict[str, object]:
        return {
            "candidates_path": self.candidates,
            "cache_manifest_path": self.cache_manifest,
            "mask_path": self.masks,
            "target_path": self.target_fasta,
            "hotspot_path": self.hotspots,
            "checkpoint_paths": self.checkpoints,
            "expected_count": 2,
            "expected_seeds": {1, 2, 3},
            "target_uniprot_start": 39,
            "expected_hotspots": 2,
            "test_only_allow_unfrozen_input_hashes": True,
        }

    def test_preflight_and_three_seed_extraction_are_label_free_and_hash_closed(self) -> None:
        preflight, candidates = MOD.preflight(**self.common())
        self.assertEqual(preflight["status"], "READY")
        self.assertEqual(preflight["cache_coverage_count"], 3)
        self.assertEqual(preflight["cdr_mask_coverage_count"], 2)
        self.assertEqual(len(candidates), 2)

        output = self.root / "features.csv"
        audit = self.root / "features.audit.json"
        report = MOD.run_extraction(
            **self.common(),
            output_path=output,
            audit_path=audit,
            batch_size=2,
            device_name="cpu",
            use_amp=False,
            superseded_output_paths=(),
        )
        frame = pd.read_csv(output)
        persisted = json.loads(audit.read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["candidate_id"].tolist(), ["candidate-1", "candidate-2"])
        self.assertEqual(set(frame["cdr_mask_status"]), {"exact_annotation"})
        self.assertIn("contact_hotspot_weighted_mean_seed_mean", frame.columns)
        self.assertIn("contact_hotspot_weighted_mean_seed_std", frame.columns)
        self.assertIn("seed1_paratope_cdr3_mean", frame.columns)
        self.assertTrue((frame["contact_hotspot_weighted_mean_seed_std"] > 0.0).all())
        seed_columns = [f"seed{seed}_contact_hotspot_weighted_mean" for seed in (1, 2, 3)]
        expected_mean = frame[seed_columns].mean(axis=1)
        expected_std = frame[seed_columns].std(axis=1, ddof=0)
        self.assertTrue(np.allclose(frame["contact_hotspot_weighted_mean_seed_mean"], expected_mean))
        self.assertTrue(np.allclose(frame["contact_hotspot_weighted_mean_seed_std"], expected_std))
        self.assertEqual(persisted["input_hashes"]["cache_manifest"], MOD.sha256_file(self.cache_manifest))
        self.assertEqual(persisted["input_hashes"]["cdr_masks"], MOD.sha256_file(self.masks))
        self.assertEqual(persisted["output_sha256"], MOD.sha256_file(output))
        self.assertEqual(persisted["label_free_contract"]["docking_label_inputs_read"], 0)
        self.assertEqual(persisted["label_free_contract"]["v4d_raw_results_read"], 0)
        self.assertTrue(persisted["release_closure_sha256"])
        self.assertEqual(
            persisted["feature_policy"]["default_trainer_must_exclude"],
            list(MOD.DIAGNOSTIC_ONLY_FEATURES),
        )
        receipt = output.with_suffix(".receipt.json")
        verified = MOD.verify_release_receipt(receipt)
        self.assertEqual(verified["status"], "PASS")
        output.write_text(output.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(MOD.FeatureExtractionError, "output hash"):
            MOD.verify_release_receipt(receipt)

    def test_preflight_reports_missing_cache_coverage_without_inference(self) -> None:
        rows, _fields = MOD.read_csv(self.cache_manifest)
        write_csv(self.cache_manifest, rows[:-1])

        report, _candidates = MOD.preflight(**self.common())

        self.assertEqual(report["status"], "BLOCKED_INPUT_COVERAGE")
        self.assertEqual(report["blockers"]["missing_cache_sequences"], 1)

    def test_candidate_docking_or_teacher_columns_fail_closed(self) -> None:
        rows, _fields = MOD.read_csv(self.candidates)
        for row in rows:
            row["R_dual_min"] = "0.9"
        write_csv(self.candidates, rows)

        with self.assertRaisesRegex(MOD.FeatureExtractionError, "adapter schema mismatch"):
            MOD.preflight(**self.common())

    def test_swapped_mask_sequences_and_cache_shard_keys_are_blocked(self) -> None:
        mask_rows, _fields = MOD.read_csv(self.masks)
        mask_rows[0]["sequence_hash"], mask_rows[1]["sequence_hash"] = (
            mask_rows[1]["sequence_hash"],
            mask_rows[0]["sequence_hash"],
        )
        write_csv(self.masks, mask_rows)
        report, _candidates = MOD.preflight(**self.common())
        self.assertEqual(report["status"], "BLOCKED_INPUT_COVERAGE")
        self.assertEqual(report["blockers"]["invalid_or_nonexact_cdr_masks"], 2)

        # Restore masks, then prove that a manifest key alias cannot silently load another tensor.
        self.setUp_masks_only()
        cache_rows, _fields = MOD.read_csv(self.cache_manifest)
        cache_rows[0]["shard_key"] = cache_rows[1]["sequence_sha256"]
        write_csv(self.cache_manifest, cache_rows)
        report, _candidates = MOD.preflight(**self.common())
        self.assertEqual(report["blockers"]["invalid_cache_identity"], 1)

    def setUp_masks_only(self) -> None:
        mask_rows = []
        for sequence in self.sequences:
            values = [0, 1, 1, 0, 2, 2, 0, 3, 3] + ([0] if len(sequence) == 10 else [])
            mask_rows.append(
                {
                    "sequence_hash": seq_hash(sequence),
                    "vhh_seq": sequence,
                    "vhh_len": len(sequence),
                    "cdr_mask_json": json.dumps(values),
                    "spans_json": json.dumps({"cdr1": [1, 3], "cdr2": [4, 6], "cdr3": [7, 9]}),
                    "cdr1_seq": sequence[1:3],
                    "cdr2_seq": sequence[4:6],
                    "cdr3_seq": sequence[7:9],
                    "status": "exact_annotation",
                }
            )
        write_csv(self.masks, mask_rows)

    def test_hotspot_mapping_accepts_first_and_last_target_residue_and_rejects_outside(self) -> None:
        boundary = self.root / "boundary.tsv"
        rows = [
            {
                "hotspot_id": "first", "hotspot_class": "core_hotspot", "priority_weight": "1",
                "uniprot_position": "39", "uniprot_aa": self.target[0],
            },
            {
                "hotspot_id": "last", "hotspot_class": "core_hotspot", "priority_weight": "1",
                "uniprot_position": str(39 + len(self.target) - 1), "uniprot_aa": self.target[-1],
            },
        ]
        with boundary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        weights, selected = MOD.load_hotspot_weights(boundary, self.target, 39, 2)
        self.assertEqual([row["target_index_0based"] for row in selected], [0, len(self.target) - 1])
        self.assertEqual(float(weights[0]), 1.0)
        self.assertEqual(float(weights[-1]), 1.0)
        rows[-1]["uniprot_position"] = str(39 + len(self.target))
        with boundary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaisesRegex(MOD.FeatureExtractionError, "outside target"):
            MOD.load_hotspot_weights(boundary, self.target, 39, 2)

    def test_residue_feature_formula_golden_and_length_confounded_policy(self) -> None:
        features = MOD.residue_features(
            0.0,
            np.asarray([0.2, 0.8]),
            np.asarray([0.1, 0.5, 0.9]),
            np.asarray([[0.2, 0.1, 0.8], [0.4, 0.3, 0.6]]),
            np.asarray([1, 3]),
            np.asarray([1.0, 0.0, 0.5]),
        )
        self.assertAlmostEqual(features["pair_ranking_sigmoid_weak"], 0.5)
        self.assertAlmostEqual(features["contact_hotspot_weighted_mean"], 1.3 / 3.0)
        self.assertAlmostEqual(features["contact_noninterface_mean"], 0.2)
        self.assertAlmostEqual(features["contact_interface_specificity"], 1.3 / 3.0 - 0.2)
        self.assertAlmostEqual(features["contact_cdr3_hotspot_weighted_mean"], 0.7 / 1.5)
        self.assertAlmostEqual(
            features["contact_cdr3_hotspot_mass_length_confounded_diagnostic"], 0.7
        )
        self.assertAlmostEqual(features["contact_hotspot_fraction"], 2.0 / 2.4)
        self.assertAlmostEqual(features["epitope_hotspot_weighted_mean"], 0.55 / 1.5)
        self.assertAlmostEqual(features["epitope_interface_specificity"], 0.55 / 1.5 - 0.5)
        self.assertTrue(set(MOD.DIAGNOSTIC_ONLY_FEATURES).isdisjoint(MOD.STABLE_FEATURE_NAMES))

    def test_superseded_output_is_quarantined_but_current_schema_is_never_overwritten(self) -> None:
        output = self.root / "release.csv"
        write_csv(
            output,
            [{"schema_version": MOD.SUPERSEDED_SCHEMA_VERSIONS[0], "candidate_id": "old"}],
        )
        audit = self.root / "release.audit.json"
        audit.write_text("{}\n", encoding="utf-8")
        receipt = MOD.quarantine_superseded_release((output, audit), output)
        self.assertEqual(receipt["status"], "QUARANTINED_SUPERSEDED_RELEASE")
        self.assertFalse(output.exists())
        self.assertEqual(len(receipt["moved"]), 2)
        write_csv(output, [{"schema_version": MOD.SCHEMA_VERSION, "candidate_id": "current"}])
        with self.assertRaisesRegex(MOD.FeatureExtractionError, "non-superseded"):
            MOD.quarantine_superseded_release((output,), output)

    def test_prepare_adapter_derives_exact_masks_from_frozen_one_based_spans(self) -> None:
        source = self.root / "fast_gate.csv"
        sequence = "ACDEFGHIKLMN"
        write_csv(
            source,
            [
                {
                    "candidate_id": "adapter-1",
                    "vhh_sequence": sequence,
                    "sequence_sha256": seq_hash(sequence),
                    "sequence_length": len(sequence),
                    "cdr1_after": "CD", "cdr1_start_1based": 2, "cdr1_end_1based": 3,
                    "cdr2_after": "FG", "cdr2_start_1based": 5, "cdr2_end_1based": 6,
                    "cdr3_after": "IKL", "cdr3_start_1based": 8, "cdr3_end_1based": 10,
                    "parent_framework_cluster": "C0001",
                    "design_method": "synthetic", "design_mode": "H3", "target_patch_id": "A_CENTER",
                }
            ],
        )
        adapter = self.root / "adapter.csv"
        masks = self.root / "adapter_masks.csv"
        receipt = self.root / "adapter.audit.json"

        audit = MOD.prepare_label_free_inputs(source, adapter, masks, receipt, expected_count=1)
        adapted, _ = MOD.read_csv(adapter)
        mask_rows, _ = MOD.read_csv(masks)
        values = json.loads(mask_rows[0]["cdr_mask_json"])

        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(adapted[0]["vhh_seq"], sequence)
        self.assertEqual(adapted[0]["cdr3_span_0based"], "7-10")
        self.assertEqual(values[1:3], [1, 1])
        self.assertEqual(values[4:6], [2, 2])
        self.assertEqual(values[7:10], [3, 3, 3])
        self.assertEqual(mask_rows[0]["status"], "exact_annotation")


if __name__ == "__main__":
    unittest.main()
