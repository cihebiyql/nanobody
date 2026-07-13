#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_phase2_v3_p2_dual_docking_pilot_package.py")
SPEC = importlib.util.spec_from_file_location("build_phase2_v3_p2_dual_docking_pilot_package", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def section(config: str, name: str) -> str:
    return config.split(f"[{name}]", 1)[1].split("\n[", 1)[0]


class BuildPhase2V3P2DualDockingPilotPackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.package = cls.root / "package"
        cls.audit = MOD.build_package(outdir=cls.package)
        cls.run_rows = read_csv(cls.package / "manifests/run_manifest.csv")
        cls.monomer_rows = read_csv(cls.package / "manifests/monomer_manifest.csv")
        cls.protocol_rows = read_csv(cls.package / "manifests/protocol_manifest.csv")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_real_asset_closure_and_cardinality(self) -> None:
        self.assertEqual(self.audit["status"], "PASS_PILOT64_DUAL_DOCKING_PACKAGE_READY")
        self.assertEqual(self.audit["candidate_count"], 64)
        self.assertEqual(self.audit["monomer_count"], 64)
        self.assertEqual(self.audit["monomer_sequence_validation_count"], 64)
        self.assertEqual(self.audit["run_count"], 160)
        self.assertEqual(self.audit["main_run_count"], 128)
        self.assertEqual(self.audit["replicate_run_count"], 32)
        self.assertEqual(self.audit["hotspot_counts"], {"8X6B": 23, "9E6Y": 23})
        self.assertEqual(len(self.run_rows), 160)
        self.assertEqual(len(self.monomer_rows), 64)
        self.assertEqual(len(self.protocol_rows), 4)
        self.assertEqual(
            Counter((row["receptor_id"], row["seed_role"]) for row in self.run_rows),
            Counter({("8X6B", "main"): 64, ("8X6B", "replicate"): 16,
                     ("9E6Y", "main"): 64, ("9E6Y", "replicate"): 16}),
        )

    def test_run_manifest_schema_paths_and_hash_closure(self) -> None:
        self.assertEqual(list(self.run_rows[0]), MOD.RUN_FIELDS)
        by_pilot: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.run_rows:
            by_pilot[row["pilot_id"]].append(row)
            for path_key, hash_key in (
                ("config_relpath", "config_sha256"),
                ("monomer_relpath", "monomer_sha256"),
                ("receptor_relpath", "receptor_sha256"),
                ("restraint_relpath", "restraint_sha256"),
                ("hotspot_relpath", "hotspot_sha256"),
            ):
                self.assertEqual(MOD.sha256_file(self.package / row[path_key]), row[hash_key])
            self.assertEqual(row["run_workspace_relpath"], f"runs/{row['run_id']}")
            self.assertEqual(row["run_dir_relpath"], f"runs/{row['run_id']}/run_{row['run_id']}")
            self.assertEqual(row["completion_relpath"], f"runs/{row['run_id']}/{row['run_id']}.complete.json")
            self.assertEqual(row["log_relpath"], f"runs/{row['run_id']}/{row['run_id']}.log")
            self.assertEqual(row["tolerance_relaxed"], "false")
        for rows in by_pilot.values():
            self.assertEqual(len({row["monomer_relpath"] for row in rows}), 1)
            self.assertEqual(len({row["monomer_sha256"] for row in rows}), 1)
        self.assertEqual(len({row["monomer_relpath"] for row in self.run_rows}), 64)

    def test_haddock_protocol_and_disjoint_actual_seed_ranges(self) -> None:
        expected = {
            ("8X6B", "main"): (917, 918, 957),
            ("8X6B", "replicate"): (10917, 10918, 10957),
            ("9E6Y", "main"): (20917, 20918, 20957),
            ("9E6Y", "replicate"): (30917, 30918, 30957),
        }
        ranges: list[set[int]] = []
        for row in self.protocol_rows:
            key = (row["receptor_id"], row["seed_role"])
            iniseed, seed_start, seed_end = expected[key]
            self.assertEqual(int(row["topoaa_iniseed"]), 917)
            self.assertEqual(int(row["rigidbody_iniseed"]), iniseed)
            self.assertEqual(int(row["rigidbody_seed_start"]), seed_start)
            self.assertEqual(int(row["rigidbody_seed_end"]), seed_end)
            self.assertEqual(seed_end - seed_start + 1, 40)
            self.assertEqual(row["flexref_iniseed"], "INHERIT_RIGIDBODY_POSE_SEEDS")
            self.assertEqual(row["emref_iniseed"], "INHERIT_RIGIDBODY_POSE_SEEDS")
            self.assertEqual(row["haddock3_version_contract"], "2025.11.0")
            ranges.append(set(range(seed_start, seed_end + 1)))
        for index, left in enumerate(ranges):
            for right in ranges[index + 1:]:
                self.assertFalse(left & right)

        for row in self.run_rows:
            config = (self.package / row["config_relpath"]).read_text(encoding="utf-8")
            self.assertIn("ncores = 4", config)
            self.assertIn("iniseed = 917", section(config, "topoaa"))
            self.assertIn(f"iniseed = {row['rigidbody_iniseed']}", section(config, "rigidbody"))
            self.assertIn("sampling = 40", section(config, "rigidbody"))
            self.assertIn("tolerance = 5", section(config, "rigidbody"))
            self.assertIn("select = 10", section(config, "seletop"))
            self.assertIn("tolerance = 10", section(config, "flexref"))
            self.assertNotIn("iniseed", section(config, "flexref"))
            self.assertNotIn("iniseed", section(config, "emref"))
            self.assertIn("min_population = 1", section(config, "clustfcc"))
            self.assertIn("top_models = 4", section(config, "seletopclusts"))

    def test_receptor_chain_extraction_relabeling_and_hotspots(self) -> None:
        packaged_8x6b = self.package / "receptors/pvrig_8x6b_chainB.pdb"
        self.assertEqual(packaged_8x6b.read_bytes(), MOD.DEFAULT_8X6B_RECEPTOR.read_bytes())

        source_atoms = [
            line[:21] + "B" + line[22:]
            for line in MOD.DEFAULT_9E6Y_STRUCTURE.read_text(encoding="ascii").splitlines()
            if line.startswith("ATOM  ") and line[21] == "A"
        ]
        packaged_atoms = [
            line for line in (self.package / "receptors/pvrig_9e6y_chainB.pdb").read_text(encoding="ascii").splitlines()
            if line.startswith("ATOM  ")
        ]
        self.assertEqual(packaged_atoms, source_atoms)
        self.assertTrue(all(line[21] == "B" for line in packaged_atoms))
        self.assertEqual(len(MOD.pdb_residues(self.package / "receptors/pvrig_8x6b_chainB.pdb", "B")), 103)
        self.assertEqual(len(MOD.pdb_residues(self.package / "receptors/pvrig_9e6y_chainB.pdb", "B")), 108)
        hotspot_8x6b = [int(value) for value in (self.package / "hotspots/hotspot_residues_8x6b.txt").read_text().split()]
        hotspot_9e6y = [int(value) for value in (self.package / "hotspots/hotspot_residues_9e6y.txt").read_text().split()]
        self.assertEqual(hotspot_8x6b, [33, 34, 36, 43, 44, 45, 49, 52, 54, 57, 58, 59, 60, 62, 97, 99, 100, 101, 102, 103, 104, 105, 106])
        self.assertEqual(hotspot_9e6y, [31, 32, 34, 41, 42, 43, 47, 50, 52, 55, 56, 57, 58, 60, 95, 97, 98, 99, 100, 101, 102, 103, 104])

    def test_cdr_ranges_use_required_frozen_sources(self) -> None:
        self.assertEqual(
            Counter(row["cdr_source_type"] for row in self.monomer_rows),
            Counter({"existing_three_consecutive_cdr_residue_groups": 32,
                     "frozen_teacher500_manifest_coordinates": 32}),
        )
        for row in self.monomer_rows:
            ranges = []
            for name in ("cdr1", "cdr2", "cdr3"):
                start, end = map(int, row[f"{name}_range"].split("-"))
                self.assertLessEqual(start, end)
                ranges.append((start, end))
            self.assertLess(ranges[0][1], ranges[1][0])
            self.assertLess(ranges[1][1], ranges[2][0])
            self.assertEqual(row["source_monomer_sha256"], row["monomer_sha256"])
            self.assertEqual(row["pdb_sequence_validated"], "true")

    def test_controller_filters_load_gate_completion_and_partial_archive_contract(self) -> None:
        controller = self.package / "scripts/run_dual_docking_pilot64.py"
        source = controller.read_text(encoding="utf-8")
        self.assertIn('MAX_CONCURRENT_JOBS = 5', source)
        self.assertIn('PVRIG_DOCKING_MAX_LOAD1", "55"', source)
        self.assertIn("wait_for_load(max_load1, load_poll_seconds)", source)
        self.assertIn('"PASS_DOCKING_OUTPUT_COMPLETE"', source)
        self.assertIn('"PENDING_GEOMETRY_AND_CONTACT_POSTPROCESS"', source)
        self.assertIn("shutil.move", source)
        self.assertIn('root / "partial_runs"', source)
        completed = subprocess.run(
            [sys.executable, str(controller), "--root", str(self.package), "--list-only",
             "--pilot-id", "P2PILOT_001", "--receptor", "9E6Y", "--seed-role", "replicate"],
            check=True, capture_output=True, text=True,
        )
        rows = json.loads(completed.stdout)
        self.assertEqual(rows, [{
            "run_id": "P2PILOT_001__9E6Y__replicate", "pilot_id": "P2PILOT_001",
            "receptor_id": "9E6Y", "seed_role": "replicate", "iniseed": "30917",
        }])
        refused = subprocess.run(
            [sys.executable, str(controller), "--root", str(self.package), "--list-only", "--max-workers", "6"],
            check=False, capture_output=True, text=True,
        )
        self.assertNotEqual(refused.returncode, 0)

    def test_manifests_and_package_are_deterministic(self) -> None:
        second = self.root / "package_second"
        second_audit = MOD.build_package(outdir=second)
        for relpath in (
            "manifests/run_manifest.csv", "manifests/monomer_manifest.csv",
            "manifests/protocol_manifest.csv", "manifests/package_content_sha256.tsv",
            "scripts/run_dual_docking_pilot64.py", "package_audit.json",
        ):
            self.assertEqual((self.package / relpath).read_bytes(), (second / relpath).read_bytes())
        self.assertEqual(self.audit, second_audit)


if __name__ == "__main__":
    unittest.main()
