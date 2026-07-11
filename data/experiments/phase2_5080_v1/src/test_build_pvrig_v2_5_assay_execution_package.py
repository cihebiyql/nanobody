from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_pvrig_v2_5_assay_execution_package import (
    DEFAULT_PANEL,
    DEFAULT_TARGET_FASTA,
    build_package,
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PvrigV25AssayExecutionPackageTests(unittest.TestCase):
    def test_real_panel_builds_blinded_three_run_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / "package"
            manifest = build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, outdir)

            self.assertEqual(manifest["status"], "READY_FOR_LAB_PREREGISTRATION")
            self.assertEqual(manifest["measurement_status"], "NO_EXPERIMENTAL_RESULTS_RECORDED")
            self.assertEqual(manifest["counts"]["panel_candidates"], 24)
            self.assertEqual(manifest["counts"]["prospective_groups"], 8)
            self.assertEqual(manifest["counts"]["scheduled_runs"], 3)
            self.assertEqual(manifest["counts"]["scheduled_day_blocks"], 3)
            self.assertEqual(manifest["counts"]["scheduled_sample_runs"], 72)

            key = pd.read_csv(outdir / "blinding_key.csv")
            schedule = pd.read_csv(outdir / "assay_run_schedule_blinded.csv")
            self.assertEqual(len(key), 24)
            self.assertEqual(key["assay_sample_id"].nunique(), 24)
            self.assertEqual(len(schedule), 72)
            self.assertNotIn("candidate_id", schedule.columns)
            self.assertNotIn("candidate_role", schedule.columns)
            self.assertNotIn("sequence_sha256", schedule.columns)
            self.assertTrue(schedule.groupby("run_id")["assay_sample_id"].nunique().eq(24).all())

            for filename, call_column in [
                ("expression_qc_results.csv", "scientist_qc_call"),
                ("binding_results.csv", "scientist_binding_call"),
                ("competition_results.csv", "scientist_blocking_call"),
                ("functional_results.csv", "scientist_functional_call"),
            ]:
                frame = pd.read_csv(outdir / filename)
                self.assertEqual(set(frame[call_column]), {"PENDING"})

            prereg = json.loads((outdir / "assay_preregistration.json").read_text())
            self.assertEqual(
                prereg["frozen_inputs"]["target_sequence_sha256"],
                "b3d2735abe671004474d0196f9d010bbdf22ea2cec9ccb6d71b28f9bdb328075",
            )
            self.assertTrue(prereg["hard_truth_gates"]["expression_failure_is_not_nonbinding"])
            self.assertTrue(prereg["hard_truth_gates"]["binding_is_not_blocking"])

            persisted = json.loads((outdir / "package_manifest.json").read_text())
            for filename, expected in persisted["artifacts"].items():
                self.assertEqual(file_sha256(outdir / filename), expected)

    def test_build_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, first)
            build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, second)
            first_files = sorted(path.name for path in first.iterdir())
            second_files = sorted(path.name for path in second.iterdir())
            self.assertEqual(first_files, second_files)
            for filename in first_files:
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes(), filename)

    def test_tampered_sequence_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel = pd.read_csv(DEFAULT_PANEL)
            panel.loc[0, "sequence_sha256"] = "0" * 64
            bad_panel = root / "bad_panel.csv"
            panel.to_csv(bad_panel, index=False)
            with self.assertRaisesRegex(ValueError, "Sequence hash mismatch"):
                build_package(bad_panel, DEFAULT_TARGET_FASTA, root / "package")

    def test_rebuild_refuses_nonpending_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / "package"
            build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, outdir)
            results = pd.read_csv(outdir / "expression_qc_results.csv", keep_default_na=False)
            results.loc[0, "scientist_qc_call"] = "FAIL"
            results.to_csv(outdir / "expression_qc_results.csv", index=False)
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite non-pending"):
                build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, outdir)

    def test_tampered_group_roles_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            panel = pd.read_csv(DEFAULT_PANEL)
            group_id = panel.loc[0, "prospective_group_id"]
            panel.loc[panel["prospective_group_id"] == group_id, "candidate_role"] = "known_positive_reference"
            bad_panel = root / "bad_roles.csv"
            panel.to_csv(bad_panel, index=False)
            with self.assertRaisesRegex(ValueError, "role composition changed"):
                build_package(bad_panel, DEFAULT_TARGET_FASTA, root / "package")

    def test_rebuild_does_not_absorb_analysis_or_raw_files_into_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / "package"
            build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, outdir)
            (outdir / "assay_analysis_summary.json").write_text("{}\n")
            (outdir / "raw_instrument_export.bin").write_bytes(b"raw")
            manifest = build_package(DEFAULT_PANEL, DEFAULT_TARGET_FASTA, outdir)
            self.assertEqual(manifest["artifact_count"], 10)
            self.assertNotIn("assay_analysis_summary.json", manifest["artifacts"])
            self.assertNotIn("raw_instrument_export.bin", manifest["artifacts"])


if __name__ == "__main__":
    unittest.main()
