#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_phase2_v3_p2_v1_3_dual47_completion15_package.py")
SPEC = importlib.util.spec_from_file_location("build_phase2_v3_p2_v1_3_dual47_completion15_package", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class BuildV13Dual47Completion15PackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.package = cls.root / "package"
        cls.audit = MOD.build_package(outdir=cls.package)
        cls.cases = read_csv(cls.package / "manifests/case_manifest.csv")
        cls.runs = read_csv(cls.package / "manifests/run_manifest.csv")
        cls.reuse = read_csv(cls.package / "manifests/exact_reuse_manifest.csv")
        cls.new = read_csv(cls.package / "manifests/new_run_manifest.csv")
        cls.monomers = read_csv(cls.package / "manifests/new_monomer_manifest.csv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_real_fixture_cardinality_anchor_and_release_boundary(self) -> None:
        self.assertEqual(self.audit["status"], "PASS_V1_3_DUAL47_COMPLETION15_PACKAGE_READY")
        self.assertEqual((len(self.cases), len(self.runs), len(self.reuse), len(self.new)), (47, 94, 64, 30))
        self.assertEqual(len(self.monomers), 15)
        self.assertEqual(Counter(row["execution_mode"] for row in self.runs), Counter({
            "REUSE_OLD_PILOT64_MAIN": 64, "NEW_DUAL_DOCKING_COMPLETION": 30,
        }))
        self.assertEqual(Counter(row["receptor_id"] for row in self.runs), Counter({"8X6B": 47, "9E6Y": 47}))
        self.assertEqual(Counter(row["anchor_class"] for row in self.cases), Counter({
            "core_direct_blocker": 5, "same_family_support": 6, "control": 36,
        }))
        self.assertEqual(self.audit["anchor_composition"]["new_family_count"], 0)
        self.assertFalse(self.audit["anchor_composition"]["new_family_claimed"])
        for key in ("formal_eligible", "training_label_release_eligible", "docking_gold_release_eligible", "p2_training_ready"):
            self.assertFalse(self.audit[key])
        self.assertFalse(self.audit["remote_jobs_launched"])
        self.assertFalse(self.audit["scoring_or_calibration_performed"])

    def test_candidate_provenance_and_row_hashes_are_closed(self) -> None:
        for row in self.cases:
            self.assertTrue(row["family"])
            self.assertTrue(row["calibration_role"])
            self.assertEqual(len(row["sequence_sha256"]), 64)
            self.assertEqual(len(row["teacher_manifest_row_sha256"]), 64)
            self.assertEqual(MOD.row_sha256(row, "case_manifest_row_sha256"), row["case_manifest_row_sha256"])
        for row in self.runs:
            for field in ("family", "calibration_role", "sequence_sha256", "teacher_manifest_row_sha256"):
                self.assertTrue(row[field])
            self.assertEqual(MOD.row_sha256(row, "run_manifest_row_sha256"), row["run_manifest_row_sha256"])
        for row in self.reuse:
            self.assertEqual(MOD.row_sha256(row, "reuse_manifest_row_sha256"), row["reuse_manifest_row_sha256"])

    def test_exact_reuse_binds_old_package_runs_controller_and_emref(self) -> None:
        binding = self.audit["old_reuse_binding"]
        self.assertEqual(binding["protocol_id"], "DG_A_PILOT64_V1_1")
        self.assertEqual(binding["remote_root"], "/data/qlyu/projects/pvrig_v3_p2_dual_docking_pilot64_v2_20260714")
        self.assertEqual(binding["package_audit_sha256"], MOD.sha256_file(MOD.DEFAULT_OLD_PACKAGE / "package_audit.json"))
        self.assertEqual(binding["run_manifest_sha256"], MOD.sha256_file(MOD.DEFAULT_OLD_PACKAGE / "manifests/run_manifest.csv"))
        self.assertEqual(binding["controller_sha256"], MOD.sha256_file(MOD.DEFAULT_OLD_PACKAGE / "scripts/run_dual_docking_pilot64.py"))
        self.assertEqual(len({(row["case_id"], row["receptor_id"]) for row in self.reuse}), 64)
        for row in self.reuse:
            self.assertEqual(row["source_protocol_id"], "DG_A_PILOT64_V1_1")
            self.assertEqual(row["v1_3_emref_gate_status"], "PASS_4_EMREF_TOP8_READY")
            self.assertEqual(row["source_final_stage_ignored"], "true")
            self.assertEqual(row["exact_reuse_hash_closed"], "true")
            self.assertGreaterEqual(int(row["source_emref_output_count"]), 8)
            counts = json.loads(row["source_stage_output_counts_json"])
            self.assertTrue(MOD.stage_counts_pass(counts))
            self.assertEqual(MOD.sha256_file(MOD.WORKSPACE_ROOT / row["source_completion_relpath"]), row["source_completion_sha256"])
            self.assertEqual(MOD.sha256_file(MOD.WORKSPACE_ROOT / row["source_emref_io_relpath"]), row["source_emref_io_sha256"])

    def test_new_configs_stop_at_emref_and_use_frozen_protocol(self) -> None:
        self.assertEqual(len({row["case_id"] for row in self.new}), 15)
        for row in self.new:
            config = (self.package / row["config_relpath"]).read_text(encoding="utf-8")
            sections = [line for line in config.splitlines() if line.startswith("[")]
            self.assertEqual(sections, ["[topoaa]", "[rigidbody]", "[seletop]", "[flexref]", "[emref]"])
            self.assertIn("ncores = 4", config)
            self.assertIn("sampling = 40", config)
            self.assertIn("tolerance = 5", config)
            self.assertIn("select = 10", config)
            self.assertNotIn("[clustfcc]", config)
            self.assertNotIn("[seletopclusts]", config)
            expected_seed = "917" if row["receptor_id"] == "8X6B" else "20917"
            self.assertEqual(row["rigidbody_iniseed"], expected_seed)
            for path_field, hash_field in (("config_relpath", "config_sha256"),
                ("monomer_relpath", "monomer_sha256"), ("receptor_relpath", "receptor_sha256"),
                ("restraint_relpath", "restraint_sha256"), ("hotspot_relpath", "hotspot_sha256")):
                self.assertEqual(MOD.sha256_file(self.package / row[path_field]), row[hash_field])
        for receptor in ("8x6b", "9e6y"):
            values = (self.package / f"hotspots/hotspot_residues_{receptor}.txt").read_text().split()
            self.assertEqual(len(values), 23)

    def test_controller_case_filter_and_no_final_stage_gate(self) -> None:
        controller = self.package / "scripts/run_v1_3_completion15.py"
        case_id = self.new[0]["case_id"]
        completed = subprocess.run([sys.executable, str(controller), "--root", str(self.package),
            "--list-only", "--case-id", case_id], check=True, capture_output=True, text=True)
        listed = json.loads(completed.stdout)
        self.assertEqual(len(listed), 2)
        self.assertEqual({row["receptor_id"] for row in listed}, {"8X6B", "9E6Y"})
        reused_case = next(row["case_id"] for row in self.cases if row["execution_mode"] == "REUSE_OLD_PILOT64_MAIN")
        refused = subprocess.run([sys.executable, str(controller), "--root", str(self.package),
            "--list-only", "--case-id", reused_case], check=False, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        spec = importlib.util.spec_from_file_location("generated_v13_controller", controller)
        assert spec and spec.loader
        generated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generated)
        self.assertEqual(set(generated.STAGE_IO_RELPATHS), {"topoaa", "rigidbody", "seletop", "flexref", "emref"})
        counts = {"topoaa": 2, "rigidbody": 38, "seletop": 10, "flexref": 8, "emref": 8}
        self.assertTrue(generated.stage_counts_pass(counts))
        for stage in counts:
            failed = dict(counts)
            failed[stage] -= 1
            self.assertFalse(generated.stage_counts_pass(failed), stage)
        source = controller.read_text(encoding="utf-8")
        self.assertIn("archive_partial", source)
        self.assertIn("atomic_json", source)
        self.assertIn("wait_for_load", source)
        self.assertIn("PASS_4_EMREF_TOP8_READY", source)
        self.assertNotIn("6_seletopclusts", source)

    def test_content_manifest_is_sha256sum_compatible(self) -> None:
        completed = subprocess.run(
            "tail -n +2 manifests/package_content_sha256.tsv | sha256sum -c -",
            cwd=self.package, shell=True, check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("FAILED", completed.stdout + completed.stderr)

    def test_package_is_deterministic(self) -> None:
        second = self.root / "package_second"
        second_audit = MOD.build_package(outdir=second)
        first_files = {path.relative_to(self.package).as_posix(): MOD.sha256_file(path)
                       for path in self.package.rglob("*")
                       if path.is_file() and "__pycache__" not in path.parts}
        second_files = {path.relative_to(second).as_posix(): MOD.sha256_file(path)
                        for path in second.rglob("*")
                        if path.is_file() and "__pycache__" not in path.parts}
        self.assertEqual(first_files, second_files)
        self.assertEqual(self.audit, second_audit)


if __name__ == "__main__":
    unittest.main()
