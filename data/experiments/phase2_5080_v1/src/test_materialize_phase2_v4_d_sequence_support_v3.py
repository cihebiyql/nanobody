#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import numpy as np


MODULE_PATH = Path(__file__).with_name(
    "materialize_phase2_v4_d_sequence_support_v3.py"
)
SPEC = importlib.util.spec_from_file_location(
    "materialize_phase2_v4_d_sequence_support_v3", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def unit(values: tuple[float, ...]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    return array / np.linalg.norm(array)


def record(
    candidate_id: str,
    parent: str,
    *,
    full: tuple[float, ...] = (1.0, 0.0),
    cdr_embedding: tuple[float, ...] = (1.0, 0.0),
    cdrs: tuple[str, str, str] = ("ACDE", "FGHI", "KLMN"),
    contact: tuple[float, ...] = (0.0, 0.0),
    sequence: str | None = None,
    digest: str | None = None,
) -> MODULE.MaterializedRecord:
    sequence = sequence or ("QQ" + cdrs[0] + "RR" + cdrs[1] + "SS" + cdrs[2] + "TT")
    return MODULE.MaterializedRecord(
        candidate_id=candidate_id,
        sequence_sha256=digest or MODULE.sha256_bytes(sequence.encode("ascii")),
        declared_parent=parent,
        sequence=sequence,
        full_esm=unit(full),
        cdr_esm=unit(cdr_embedding),
        cdr1=cdrs[0],
        cdr2=cdrs[1],
        cdr3=cdrs[2],
        contact=np.asarray(contact, dtype=np.float32),
    )


def tiny_lock() -> dict:
    return {
        "claim_boundary": "label-free support only",
        "calibration": {
            "threshold_quantile": 0.95,
            "nested_validation": {
                "folds": 5,
                "seed": 20260716,
                "minimum_parent_rows": 6,
                "policy": "within-parent deterministic candidate hash fold",
            },
        },
        "hard_gates": {
            "cdr_composition_shuffle": {"in_domain_fraction_maximum": 0.05},
            "cross_parent_cdr_graft": {"in_domain_fraction_maximum": 0.10},
            "channel_splice": {"in_domain_fraction_maximum": 0.05},
            "unseen_parent_chimera": {"near_domain_fraction_maximum": 0.10},
        },
        "decision_policy": {
            "pass": "PASS_LABEL_FREE_SUPPORT",
            "fail": "FAIL_RESEARCH_ONLY",
        },
        "publication_contract": {
            "required_outputs": [
                "candidate7087_sequence_support_v3.csv",
                "candidate7087_sequence_support_v3.audit.json",
                "candidate7087_sequence_support_v3.receipt.json",
            ]
        },
    }


class SupportV3ProductionMaterializerTests(unittest.TestCase):
    def test_embedding_summary_uses_full_and_each_cdr_mean_std_then_l2(self) -> None:
        embedding = np.asarray(
            [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]],
            dtype=np.float32,
        )
        full, cdr = MODULE.summarize_embedding_array(embedding, [1, 1, 2, 3])
        self.assertEqual(full.shape, (4,))
        self.assertEqual(cdr.shape, (12,))
        self.assertAlmostEqual(float(np.linalg.norm(full)), 1.0, places=6)
        self.assertAlmostEqual(float(np.linalg.norm(cdr)), 1.0, places=6)
        raw_full = np.concatenate((embedding.mean(0), embedding.std(0, ddof=0)))
        np.testing.assert_allclose(full, raw_full / np.linalg.norm(raw_full), rtol=1e-6)
        raw_cdr = np.concatenate(
            (
                embedding[:2].mean(0),
                embedding[:2].std(0, ddof=0),
                embedding[2:3].mean(0),
                embedding[2:3].std(0, ddof=0),
                embedding[3:4].mean(0),
                embedding[3:4].std(0, ddof=0),
            )
        )
        np.testing.assert_allclose(cdr, raw_cdr / np.linalg.norm(raw_cdr), rtol=1e-6)

    def test_robust_scaler_is_fit_only_on_declared_open_train_ids(self) -> None:
        values = {
            "T1": [0.0, 10.0],
            "T2": [1.0, 11.0],
            "T3": [2.0, 12.0],
            "T4": [3.0, 13.0],
            "SEALED": [10000.0, -10000.0],
        }
        scaled, audit = MODULE.robust_scale(values, ["T1", "T2", "T3", "T4"])
        self.assertEqual(audit["fit_row_count"], 4)
        self.assertEqual(audit["median"], [1.5, 11.5])
        self.assertGreater(float(scaled["SEALED"][0]), 1000.0)
        with self.assertRaises(MODULE.MaterializationError):
            MODULE.robust_scale({"A": [1.0], "B": [1.0]}, ["A", "B"])

    def test_equal_parent_mass_weighted_linear_quantile(self) -> None:
        balanced = MODULE.weighted_linear_quantile([0.0, 0.0, 10.0, 10.0], ["A", "A", "B", "B"], 0.5)
        duplicated_a = MODULE.weighted_linear_quantile(
            [0.0] * 20 + [10.0, 10.0], ["A"] * 20 + ["B", "B"], 0.5
        )
        self.assertAlmostEqual(balanced, 5.0)
        self.assertAlmostEqual(duplicated_a, 5.0)

    def test_same_neighbor_rule_rejects_cross_reference_channel_borrowing(self) -> None:
        a = record("A", "P", full=(1, 0, 0), cdr_embedding=(0, 1, 0), contact=(3, 3))
        b = record(
            "B", "P", full=(0, 1, 0), cdr_embedding=(1, 0, 0),
            cdrs=("NPQR", "STVW", "YACD"), contact=(2, 2),
        )
        c = record(
            "C", "P", full=(0, 0, 1), cdr_embedding=(0, 0, 1),
            cdrs=("CEGH", "IKLM", "NPQS"), contact=(0, 0),
        )
        mosaic = record(
            "M", "P", full=(1, 0, 0), cdr_embedding=(1, 0, 0),
            cdrs=("NPQR", "STVW", "YACD"), contact=(0, 0), digest="f" * 64,
        )
        thresholds = {channel: 1e-8 for channel in MODULE.CORE.REQUIRED_CHANNELS}
        result = MODULE.classify_record(mosaic, [a, b, c], thresholds, thresholds)
        self.assertEqual(result.label, "OUT_OF_DOMAIN")
        legitimate = record(
            "LEGIT", "P", full=(1, 0, 0), cdr_embedding=(0, 1, 0),
            contact=(3, 3), digest="e" * 64,
        )
        result = MODULE.classify_record(legitimate, [a, b, c], thresholds, thresholds)
        self.assertEqual(result.label, "IN_DOMAIN")
        self.assertEqual(result.neighbor_id, "A")

    def test_null_generation_is_deterministic_unique_and_semantically_exact(self) -> None:
        refs = []
        spans = {}
        parent_cdrs = {
            "P1": ("ACDE", "FGHI", "KLMN"),
            "P2": ("NPQR", "STVW", "YACD"),
            "P3": ("EFGH", "IKLM", "NPQS"),
        }
        for parent, cdrs in parent_cdrs.items():
            for index in range(3):
                suffix = "ACDEFGHIKLMNPQRSTVWY"[index]
                framework_prefix = {"P1": "QQ", "P2": "VV", "P3": "WW"}[parent]
                sequence = framework_prefix + cdrs[0] + "RR" + cdrs[1] + "SS" + cdrs[2] + "TT" + suffix
                row = record(f"{parent}_{index}", parent, cdrs=cdrs, sequence=sequence)
                refs.append(row)
                spans[row.sequence_sha256] = {
                    "cdr1": (2, 6), "cdr2": (8, 12), "cdr3": (14, 18)
                }
        first = MODULE.generate_null_sequences(refs, spans, replicates_each=3, seed=11)
        second = MODULE.generate_null_sequences(refs, spans, replicates_each=3, seed=11)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 9)
        self.assertEqual(len({row.sequence_sha256 for row in first}), 9)
        by_id = {row.candidate_id: row for row in refs}
        for row in first:
            if row.kind == "cdr_composition_shuffle":
                source = by_id[row.source_ids[0]]
                for name in ("cdr1", "cdr2", "cdr3"):
                    self.assertEqual(Counter(getattr(row, name)), Counter(getattr(source, name)))
                self.assertEqual(row.declared_parent, source.declared_parent)
            else:
                donor = by_id[row.source_ids[1]]
                self.assertEqual((row.cdr1, row.cdr2, row.cdr3), (donor.cdr1, donor.cdr2, donor.cdr3))
                self.assertNotEqual(row.source_parents[0], row.source_parents[1])
                if row.kind == "unseen_parent_chimera":
                    self.assertTrue(row.declared_parent.startswith("UNSEEN_CHIMERA_"))

    def test_null_cache_wrong_panel_hash_and_partial_cache_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache = root / "cache"
            cache.mkdir()
            receipt = root / "receipt.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schema_version": "phase2_v4_d_sequence_support_v3_null_esm2_cache_receipt_v2",
                        "status": "PASS_COMPLETE_LABEL_FREE_CACHE_CLOSURE",
                        "null_panel_sha256": "wrong",
                        "artifacts": {},
                    }
                )
            )
            with self.assertRaisesRegex(MODULE.MaterializationError, "panel_hash_mismatch"):
                MODULE.validate_null_cache_state(cache, receipt, "expected")
            receipt.write_text(
                json.dumps(
                    {
                        "schema_version": "phase2_v4_d_sequence_support_v3_null_esm2_cache_receipt_v2",
                        "status": "PASS_COMPLETE_LABEL_FREE_CACHE_CLOSURE",
                        "null_panel_sha256": "expected",
                    }
                )
            )
            with self.assertRaisesRegex(MODULE.MaterializationError, "binding_set_incomplete"):
                MODULE.validate_null_cache_state(cache, receipt, "expected")
            receipt.unlink()
            (cache / "partial.pt").write_bytes(b"partial")
            with self.assertRaisesRegex(MODULE.MaterializationError, "partial_null_cache"):
                MODULE.validate_null_cache_state(cache, receipt, "expected")

    def test_label_like_runtime_path_and_null_columns_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(MODULE.MaterializationError, "label_like_runtime_path"):
                MODULE.require_ext4_runtime(root / "docking_results")
            adapter = root / "adapter.csv"
            with adapter.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["candidate_id", "geometry_tier"])
                writer.writeheader()
                writer.writerow({"candidate_id": "X", "geometry_tier": "G1"})
            with self.assertRaisesRegex(MODULE.MaterializationError, "label_like_columns"):
                MODULE.validate_null_adapter_boundary(adapter, 1)

    def test_sentinel_only_log_cannot_authorize_v2_freeze(self) -> None:
        with self.assertRaisesRegex(MODULE.MaterializationError, "command_record"):
            MODULE.validate_frozen_test_log(
                MODULE.TEST_PASS_SENTINEL + "\n",
                expected_command=MODULE._frozen_test_command(),
                expected_count=MODULE.EXPECTED_FROZEN_TEST_COUNT,
            )

    def test_contact_reload_enforces_exact_candidate_sequence_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "contact.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["candidate_id", "sequence_sha256", "feature_seed_mean"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "candidate_id": "C1",
                        "sequence_sha256": "wrong",
                        "feature_seed_mean": "0.5",
                    }
                )
            with self.assertRaisesRegex(MODULE.MaterializationError, "sequence_identity"):
                MODULE._load_contact_values(path, ["feature"], {"C1": "expected"})

    def test_exact_output_verifier_rejects_directories_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a").write_text("a")
            (root / "b").write_text("b")
            (root / "c").mkdir()
            with self.assertRaisesRegex(MODULE.MaterializationError, "nonregular"):
                MODULE.verify_exact_regular_file_set(root, {"a", "b", "c"})

    def test_snapshot_detects_input_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input.dat"
            path.write_bytes(b"frozen")
            record_snapshot = MODULE.snapshot_file(path)
            MODULE.verify_snapshot(record_snapshot, "input")
            path.write_bytes(b"mutated")
            with self.assertRaises(MODULE.MaterializationError):
                MODULE.verify_snapshot(record_snapshot, "input")

    def test_publication_has_exact_output_set_and_receipt_is_written_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            publish = root / "publish"
            freeze = root / "freeze.json"
            freeze.write_text("{}\n")
            events = []
            original = MODULE.atomic_write_json

            def recording_write(path, payload):
                events.append(Path(path).name)
                return original(path, payload)

            with mock.patch.object(MODULE, "atomic_write_json", side_effect=recording_write):
                MODULE.publish_passed_outputs(
                    publish_dir=publish,
                    table_rows=[{"candidate_id": "X", "support_domain": "OUT_OF_DOMAIN"}],
                    audit={"status": "PASS_LABEL_FREE_SUPPORT"},
                    freeze_path=freeze,
                    lock=tiny_lock(),
                )
            self.assertEqual(events[-1], "candidate7087_sequence_support_v3.receipt.json")
            self.assertEqual(
                {path.name for path in publish.iterdir()},
                set(tiny_lock()["publication_contract"]["required_outputs"]),
            )
            receipt = json.loads(
                (publish / "candidate7087_sequence_support_v3.receipt.json").read_text()
            )
            MODULE.verify_snapshot(receipt["support_table"], "published_table")
            MODULE.verify_snapshot(receipt["audit"], "published_audit")
            with self.assertRaisesRegex(MODULE.MaterializationError, "not_empty"):
                MODULE.publish_passed_outputs(
                    publish_dir=publish,
                    table_rows=[{"candidate_id": "Y"}],
                    audit={},
                    freeze_path=freeze,
                    lock=tiny_lock(),
                )

    def test_channel_splice_uses_three_distinct_parent_sources_and_fixed_count(self) -> None:
        refs = []
        for parent_index in range(4):
            parent = f"P{parent_index}"
            for row_index in range(2):
                refs.append(
                    record(
                        f"{parent}_{row_index}", parent,
                        full=(1.0, float(parent_index + 1), 0.1),
                        cdr_embedding=(0.1, 1.0, float(parent_index + 1)),
                        contact=(float(parent_index), float(row_index)),
                    )
                )
        splices = MODULE.generate_channel_splices(refs, count=25, seed=17)
        self.assertEqual(len(splices), 25)
        by_id = {row.candidate_id: row for row in refs}
        for query, source_ids in splices:
            self.assertEqual(len(set(source_ids)), 3)
            self.assertEqual(len({by_id[source].declared_parent for source in source_ids}), 3)
            self.assertEqual(query.declared_parent, by_id[source_ids[0]].declared_parent)
            np.testing.assert_array_equal(query.full_esm, by_id[source_ids[0]].full_esm)
            np.testing.assert_array_equal(query.cdr_esm, by_id[source_ids[1]].cdr_esm)
            np.testing.assert_array_equal(query.contact, by_id[source_ids[2]].contact)

    def test_nested_validation_uses_hash_folds_and_never_validates_against_itself(self) -> None:
        refs = []
        for parent_index in range(3):
            parent = f"P{parent_index}"
            for index in range(12):
                refs.append(
                    record(
                        f"{parent}_{index:02d}", parent,
                        digest=f"{parent_index + 1:x}{index:02x}".ljust(64, "0"),
                    )
                )
        first = MODULE.nested_validation(refs, tiny_lock())
        second = MODULE.nested_validation(refs, tiny_lock())
        self.assertEqual(first, second)
        self.assertEqual(first["row_count"], len(refs))
        self.assertEqual(set(first["parent_fractions"]), {"P0", "P1", "P2"})
        self.assertTrue(all(value == 1.0 for value in first["parent_fractions"].values()))


if __name__ == "__main__":
    unittest.main()
