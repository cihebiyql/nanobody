#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_module:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECOVERY = load_module(
    "recover_phase2_v4_h_qc96_h2_h4_v1_2",
    HERE / "recover_phase2_v4_h_qc96_h2_h4_v1_2.py",
)
FROZEN = load_module(
    "run_phase2_v4_h_qc96_qc_node1_for_recovery_test",
    HERE / "run_phase2_v4_h_qc96_qc_node1.py",
)


PATCHES = ("A_CENTER", "B_LOWER", "C_CROSS")
MODES = ("H3", "H1H3")


def fixture_rows(per_stratum: int = 5):
    candidates = []
    full_by = {}
    for parent_rank in range(1, 6):
        parent = f"C{parent_rank:04d}"
        for patch in PATCHES:
            for mode in MODES:
                for member in range(per_stratum):
                    candidate_id = f"V4H__{parent}__{patch}__{mode}__{member:02d}"
                    sequence = f"QVQLV{parent_rank}{patch[0]}{mode}{member:02d}WGQ"
                    sequence_sha = hashlib.sha256(sequence.encode()).hexdigest()
                    row = {
                        "candidate_id": candidate_id,
                        "sequence_sha256": sequence_sha,
                        "sequence": sequence,
                        "parent_id": f"PARENT_{parent_rank}",
                        "parent_framework_cluster": parent,
                        "parent_queue_rank": str(parent_rank),
                        "target_patch_id": patch,
                        "design_mode": mode,
                        "cdr1_after": "GFTFS",
                        "cdr2_after": "ISGSG",
                        "cdr3_after": f"CAR{parent_rank}{member}YW",
                        "cdr3_length": "7",
                        "claim_boundary": "SOURCE_H1_DESIGN_CLAIM",
                        "raw_candidate_id": f"RAW_{candidate_id}",
                        "source_sequence_pdb_sha256": hashlib.sha256(candidate_id.encode()).hexdigest(),
                    }
                    candidates.append(row)
                    fail = parent_rank == 5 and patch == "A_CENTER" and mode == "H3" and member < 2
                    full_by[candidate_id] = {
                        "candidate_id": candidate_id,
                        "sequence": sequence,
                        "hard_fail": "true" if fail else "false",
                    }
    return candidates, full_by


def selected_context():
    candidates, full_by = fixture_rows()
    selected, capacity = RECOVERY.h4_select(candidates, full_by, RECOVERY.SELECTION_SEED)
    return {
        "source_fields": list(candidates[0]),
        "candidates": candidates,
        "full_by": full_by,
        "selected": selected,
        "capacity": capacity,
        "ready_parents": [
            row["parent_framework_cluster"]
            for row in capacity
            if row["capacity_state"] == "QC_CAPACITY_READY"
        ],
        "label_path_access": {
            "model_scores": 0,
            "docking_labels": 0,
            "experimental_labels": 0,
        },
    }


class ProjectionTests(unittest.TestCase):
    def test_core_manifest_schema_is_exact_frozen_22_columns(self):
        self.assertEqual(len(RECOVERY.CORE_MANIFEST_FIELDS), 22)
        self.assertEqual(RECOVERY.CORE_MANIFEST_FIELDS, [
            "candidate_id", "sequence_sha256", "sequence", "parent_id",
            "parent_framework_cluster", "parent_queue_rank", "target_patch_id",
            "design_mode", "cdr1_after", "cdr2_after", "cdr3_after", "cdr3_length",
            "h4_selection_hash", "h4_selection_rank_in_stratum", "selection_stratum",
            "model_split", "tnp_supervision_state", "tnp_score", "tnp_red_flag",
            "tnp_yellow_flag", "full_qc_and_docking_policy", "claim_boundary",
        ])

    def test_actual_h1_header_is_exact_and_has_only_claim_boundary_collision(self):
        self.assertEqual(len(RECOVERY.EXPECTED_H1_SOURCE_FIELDS), 33)
        self.assertIn("claim_boundary", RECOVERY.EXPECTED_H1_SOURCE_FIELDS)
        self.assertNotIn("model_split", RECOVERY.EXPECTED_H1_SOURCE_FIELDS)
        self.assertNotIn("h4_selection_hash", RECOVERY.EXPECTED_H1_SOURCE_FIELDS)
        RECOVERY.validate_h1_source_header(RECOVERY.EXPECTED_H1_SOURCE_FIELDS)
        with self.assertRaisesRegex(RuntimeError, "h1_source_header_mismatch"):
            RECOVERY.validate_h1_source_header(
                [*RECOVERY.EXPECTED_H1_SOURCE_FIELDS, "model_split"]
            )

    def test_projection_drops_extra_provenance_and_requires_every_core_key(self):
        row = {field: field for field in RECOVERY.CORE_MANIFEST_FIELDS}
        row["extra_provenance"] = "kept_only_in_sidecar"
        projected = RECOVERY.project_rows([row], RECOVERY.CORE_MANIFEST_FIELDS)
        self.assertEqual(list(projected[0]), RECOVERY.CORE_MANIFEST_FIELDS)
        self.assertNotIn("extra_provenance", projected[0])
        del row["candidate_id"]
        with self.assertRaisesRegex(RuntimeError, "projection_missing_fields:0:candidate_id"):
            RECOVERY.project_rows([row], RECOVERY.CORE_MANIFEST_FIELDS)

    def test_tnp_na_semantics_are_fail_closed(self):
        context = selected_context()
        rows = RECOVERY.project_rows(context["selected"], RECOVERY.CORE_MANIFEST_FIELDS)
        RECOVERY.validate_manifest_semantics(rows)
        cases = [
            ("tnp_supervision_state", "VALID_TNP", "manifest_tnp_state_changed"),
            ("tnp_score", "0.5", "manifest_tnp_na_not_empty"),
            ("tnp_red_flag", "NA", "manifest_tnp_na_not_empty"),
            ("candidate_id", "", "manifest_required_value_empty"),
        ]
        for field, value, error in cases:
            mutated = [dict(row) for row in rows]
            mutated[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, error):
                RECOVERY.validate_manifest_semantics(mutated)

    def test_atomic_tsv_exact_header_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.tsv"
            RECOVERY.atomic_tsv(path, [{"a": "1", "b": "2"}], ["a", "b"])
            with path.open(newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                self.assertEqual(reader.fieldnames, ["a", "b"])
                self.assertEqual(list(reader), [{"a": "1", "b": "2"}])
            with self.assertRaisesRegex(RuntimeError, "refuse_overwrite"):
                RECOVERY.atomic_tsv(path, [{"a": "3", "b": "4"}], ["a", "b"])


class FrozenSelectionParityTests(unittest.TestCase):

    def test_real1440_end_to_end_run_replay_binds_current_runner(self):
        path = (
            HERE.parent / "audits" /
            "phase2_v4_h_qc96_h2_h4_recovery_v1_2_real1440_full_run_replay.json"
        )
        evidence = json.loads(path.read_text())
        self.assertEqual(
            evidence["status"], "PASS_REAL1440_V1_2_END_TO_END_RUN_PUBLICATION_REPLAY"
        )
        self.assertEqual(
            evidence["v1_2_recovery_script_sha256"],
            hashlib.sha256((HERE / "recover_phase2_v4_h_qc96_h2_h4_v1_2.py").read_bytes()).hexdigest(),
        )
        self.assertEqual(evidence["selected_rows"], 96)
        self.assertEqual(
            evidence["selected_ids_ordered_sha256"],
            "91e86a1ab0aba2dc37dfd2e3b4f30479fa4653690f9b005dd28c94a79f9aadf4",
        )
        self.assertEqual(len(evidence["five_required_outputs"]), 5)
        self.assertTrue(evidence["formal_manifest"]["header_exact_core22"])
        self.assertEqual(evidence["formal_manifest"]["header_columns"], 22)
        self.assertEqual(evidence["formal_manifest"]["claim_boundary_value"], RECOVERY.CLAIM)
        self.assertTrue(
            evidence["source_provenance_sidecar"]["header_exact_original_h1"]
        )
        self.assertTrue(
            evidence["source_provenance_sidecar"]["all_33_fields_exact_replay"]
        )
        self.assertFalse(
            evidence["source_provenance_sidecar"]["selection_metadata_added"]
        )
        self.assertEqual(evidence["source_provenance_sidecar"]["header_columns"], 33)
        self.assertEqual(
            evidence["source_provenance_sidecar"]["source_claim_boundary_value"],
            "PVRIG-hotspot-conditioned RFantibody sequences; sequence/developability "
            "design evidence only, not Docking geometry, binding, affinity, competition, "
            "experimental blocking, or Docking Gold.",
        )

    def test_selection_seed_matches_actual_frozen_source_config(self):
        self.assertEqual(
            RECOVERY.SELECTION_SEED,
            "phase2_v4_h_h4_fullqc_hash_selection_v1_20260717",
        )

    def test_recovery_selection_exactly_matches_frozen_h4(self):
        candidates, full_by = fixture_rows()
        actual, actual_capacity = RECOVERY.h4_select(candidates, full_by, RECOVERY.SELECTION_SEED)
        expected, expected_capacity = FROZEN.h4_select(
            candidates, full_by, seed=RECOVERY.SELECTION_SEED
        )
        self.assertEqual(actual, expected)
        self.assertEqual(actual_capacity, expected_capacity)
        self.assertEqual(len(actual), 96)
        self.assertEqual(
            Counter(row["parent_framework_cluster"] for row in actual),
            Counter({f"C{rank:04d}": 24 for rank in range(1, 5)}),
        )
        self.assertEqual(
            Counter(Counter(row["selection_stratum"] for row in actual).values()),
            Counter({4: 24}),
        )
        self.assertEqual(actual_capacity[-1]["capacity_state"], "INSUFFICIENT_QC_CAPACITY")

    def test_invalid_hard_fail_does_not_silently_become_failure(self):
        with self.assertRaisesRegex(RuntimeError, "invalid_hard_fail"):
            RECOVERY.hard_pass({"candidate_id": "x", "hard_fail": "NA"})


class RecoveryPublicationTests(unittest.TestCase):
    def test_run_keeps_formal_schema_exact_and_provenance_in_sidecar(self):
        context = selected_context()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            recovery_root = Path(tmp) / "recovery"
            source.mkdir()
            runtime = RECOVERY.Recovery(source, recovery_root, enforce_canonical=False)
            with mock.patch.object(runtime, "validate", return_value=context):
                result = runtime.run()
            self.assertEqual(result["status"], "PASS_V4_H_QC96_FROZEN_AFTER_LABEL_FREE_FULL_QC")
            self.assertEqual(
                result["recovery_status"], "PASS_V4_H_QC96_H4_MANIFEST_RECOVERY_VALIDATED"
            )
            formal_fields, formal_rows = RECOVERY.read_tsv(recovery_root / "qc96_manifest_v1.tsv")
            side_fields, side_rows = RECOVERY.read_tsv(
                recovery_root / "qc96_selected_source_provenance_v1.tsv"
            )
            self.assertEqual(formal_fields, RECOVERY.CORE_MANIFEST_FIELDS)
            self.assertEqual(len(formal_rows), 96)
            self.assertNotIn("raw_candidate_id", formal_fields)
            self.assertEqual(side_fields, context["source_fields"])
            self.assertIn("raw_candidate_id", side_fields)
            self.assertIn("source_sequence_pdb_sha256", side_fields)
            self.assertNotIn("h4_selection_hash", side_fields)
            self.assertNotIn("model_split", side_fields)
            self.assertEqual(len(side_rows), 96)
            RECOVERY.validate_manifest_semantics(formal_rows)
            source_by = {row["candidate_id"]: row for row in context["candidates"]}
            formal_by = {row["candidate_id"]: row for row in formal_rows}
            for row in side_rows:
                original = source_by[row["candidate_id"]]
                self.assertEqual(row, {field: original[field] for field in context["source_fields"]})
                self.assertEqual(row["claim_boundary"], "SOURCE_H1_DESIGN_CLAIM")
                self.assertEqual(formal_by[row["candidate_id"]]["claim_boundary"], RECOVERY.CLAIM)
            audit = json.loads((recovery_root / "qc96_audit_v1.json").read_text())
            self.assertFalse(audit["formal_manifest_schema_expanded"])
            self.assertEqual(audit["manifest_fields"], RECOVERY.CORE_MANIFEST_FIELDS)
            self.assertTrue(audit["provenance_sidecar_exact_original_source_schema"])
            self.assertFalse(audit["provenance_sidecar_selection_metadata_added"])

    def test_nonempty_recovery_root_is_refused_before_publication(self):
        context = selected_context()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            recovery_root = Path(tmp) / "recovery"
            source.mkdir()
            recovery_root.mkdir()
            (recovery_root / "foreign").write_text("x")
            runtime = RECOVERY.Recovery(source, recovery_root, enforce_canonical=False)
            with mock.patch.object(runtime, "validate", return_value=context):
                with self.assertRaisesRegex(RuntimeError, "recovery_root_not_empty"):
                    runtime.run()


class PreflightFailClosedTests(unittest.TestCase):
    def recovery(self, tmp: str):
        source = Path(tmp) / "source"
        target = Path(tmp) / "target"
        source.mkdir()
        return RECOVERY.Recovery(source, target, enforce_canonical=False), source

    def test_source_recovery_overlap_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "same"
            root.mkdir()
            runtime = RECOVERY.Recovery(root, root, enforce_canonical=False)
            with self.assertRaisesRegex(RuntimeError, "source_recovery_path_overlap"):
                runtime.validate()

    def test_source_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, _ = self.recovery(tmp)
            with mock.patch.object(RECOVERY, "SOURCE_HASHES", {"missing": "0" * 64}), \
                 mock.patch.object(RECOVERY, "MARKER_BINDINGS", {}), \
                 mock.patch.object(RECOVERY, "SOURCE_H4_ABSENT", ()):
                with self.assertRaisesRegex(RuntimeError, "source_hash_mismatch:missing"):
                    runtime.validate()

    def test_marker_set_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, _ = self.recovery(tmp)
            with mock.patch.object(RECOVERY, "SOURCE_HASHES", {}), \
                 mock.patch.object(RECOVERY, "MARKER_BINDINGS", {"fast": (1, "bad")}), \
                 mock.patch.object(RECOVERY, "SOURCE_H4_ABSENT", ()):
                with self.assertRaisesRegex(RuntimeError, "fast_marker_set_mismatch"):
                    runtime.validate()

    def test_unexpected_old_failure_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, source = self.recovery(tmp)
            (source / "status").mkdir()
            (source / "status/qc.failed.json").write_text(json.dumps({"status": "WRONG", "error": "wrong"}))
            with mock.patch.object(RECOVERY, "SOURCE_HASHES", {}), \
                 mock.patch.object(RECOVERY, "MARKER_BINDINGS", {}), \
                 mock.patch.object(RECOVERY, "SOURCE_H4_ABSENT", ()):
                with self.assertRaisesRegex(RuntimeError, "unexpected_old_failure"):
                    runtime.validate()

    def test_source_h4_output_existing_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, source = self.recovery(tmp)
            (source / "unexpected_h4.tsv").write_text("x")
            with mock.patch.object(RECOVERY, "SOURCE_HASHES", {}), \
                 mock.patch.object(RECOVERY, "MARKER_BINDINGS", {}), \
                 mock.patch.object(RECOVERY, "SOURCE_H4_ABSENT", ("unexpected_h4.tsv",)):
                with self.assertRaisesRegex(RuntimeError, "source_h4_outputs_no_longer_absent"):
                    runtime.validate()

    def test_bound_source_paths_exclude_model_docking_and_label_artifacts(self):
        forbidden = ("/model", "/docking", "/label", "experimental")
        for rel in RECOVERY.SOURCE_HASHES:
            with self.subTest(rel=rel):
                self.assertFalse(any(token in f"/{rel.lower()}" for token in forbidden))


if __name__ == "__main__":
    unittest.main(verbosity=2)
