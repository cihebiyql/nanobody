#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name(
    "build_phase2_v4_d_cross_campaign_control_bridge.py"
)
SPEC = importlib.util.spec_from_file_location(
    "build_phase2_v4_d_cross_campaign_control_bridge", MODULE_PATH
)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def raw_result(
    job: dict[str, object], protocol_core: str, multiplier: float
) -> dict[str, object]:
    poses = []
    for index in range(4):
        scores = []
        for reference in MOD.CONFORMATIONS:
            scores.append(
                {
                    "reference_id": reference,
                    "hotspot_overlap": {
                        "full": {"count": 12.0 * multiplier},
                        "anchor": {"count": 6.0 * multiplier},
                        "holdout": {"count": 5.0 * multiplier},
                    },
                    "vhh_pvrl2_occlusion": {
                        "residue_pair_count": 300.0 * multiplier,
                        "by_vhh_region_pair_count": {"cdr3": 60.0 * multiplier},
                        "cdr3_fraction": 0.12 * multiplier,
                    },
                    "clashes_2p5a": {
                        "atom_pair_count": 8,
                        "residue_pair_count": 4,
                        "vhh_pvrig": {"residue_pair_count": 1},
                        "vhh_pvrl2": {"residue_pair_count": 3},
                    },
                    "overlay": {"t_ca_rmsd_a": 0.2},
                }
            )
        poses.append(
            {
                "pose": f"model_{index}.pdb",
                "haddock_io": {
                    "score": -100.0 + index,
                    "unw_energies.air": 1.0,
                },
                "scores": scores,
            }
        )
    return {
        "job_id": job["job_id"],
        "job_hash": job["job_hash"],
        "entity_type": "control",
        "entity_id": job["entity_id"],
        "dock_conformation": job["conformation"],
        "seed": int(job["seed"]),
        "state": "SUCCESS",
        "protocol_core_sha256": protocol_core,
        "selected_model_count": len(poses),
        "pose_scores": poses,
    }


class BridgeFixture:
    def __init__(self, root: Path, controls: int = 2) -> None:
        self.root = root
        self.left_root = root / "left"
        self.right_root = root / "right"
        self.out_dir = root / "out"
        self.control_ids = [f"CTRL_{index:03d}" for index in range(controls)]
        self.left_core = "a" * 64
        self.right_core = "b" * 64
        self.left_rows = self._make_campaign(
            self.left_root, "left", self.left_core, multiplier=1.0
        )
        self.right_rows = self._make_campaign(
            self.right_root, "right", self.right_core, multiplier=1.005
        )

    def _make_campaign(
        self, campaign_root: Path, label: str, core: str, multiplier: float
    ) -> list[dict[str, object]]:
        write_json(
            campaign_root / MOD.PROTOCOL_CORE_LOCK_RELATIVE_PATH,
            {"protocol_core_sha256": core},
        )
        protocol = {
            "schema_version": 1,
            "status": "fixture",
            "protocol_id": label,
            "docking": {
                "engine": "HADDOCK3",
                "validated_engine_version": "fixture",
                "sampling": 40,
                "npart": 2,
                "randremoval": True,
                "module_seed_fields": ["rigidbody.iniseed", "flexref.iniseed"],
                "rigidbody_tolerance": 5,
                "flexref_tolerance": 10,
                "seeds": list(MOD.SEEDS),
                "seletop_select": 10,
                "seletopclusts_top_models": 4,
            },
            "scoring": {
                "atom_records": "standard_amino_acid_ATOM_only",
                "clash_cutoff_a": 2.5,
                "pvrig_vhh_contact_cutoff_a": 4.5,
                "pvrl2_occlusion_cutoff_a": 4.5,
            },
            "interface": {"air_anchor_count": 12, "holdout_count": 11},
            "references": {
                "receptor_chain": "T",
                "ligand_chain": "L",
                "numbering": "fixture",
                "conformations": {
                    "8x6b": {"receptor_number_offset": 38},
                    "9e6y": {"receptor_number_offset": 40},
                },
            },
        }
        write_json(campaign_root / MOD.PROTOCOL_SPEC_RELATIVE_PATH, protocol)
        control_manifest_rows = [
            {"entity_id": entity_id, "sequence_sha256": sha256_text(f"sequence:{entity_id}")}
            for entity_id in self.control_ids
        ]
        write_tsv(
            campaign_root / MOD.CONTROL_MANIFEST_RELATIVE_PATH,
            control_manifest_rows,
        )
        score_pose = campaign_root / MOD.SCORE_POSE_RELATIVE_PATH
        score_pose.parent.mkdir(parents=True, exist_ok=True)
        score_pose.write_text("# identical frozen score fixture\n", encoding="utf-8")
        for conformation in MOD.CONFORMATIONS:
            receptor = (
                campaign_root
                / "inputs/normalized"
                / f"{conformation}_pvrig_receptor.pdb"
            )
            receptor.parent.mkdir(parents=True, exist_ok=True)
            receptor.write_text(
                f"ATOM      1  CA  ALA T   1      {1 if conformation == '8x6b' else 2}.000   0.000   0.000\n",
                encoding="utf-8",
            )
        rows: list[dict[str, object]] = []
        candidate_job_id = f"{label}_CANDIDATE_DO_NOT_OPEN"
        rows.append(
            {
                "job_id": candidate_job_id,
                "job_hash": sha256_text(candidate_job_id),
                "entity_type": "candidate",
                "entity_id": "CANDIDATE_DO_NOT_OPEN",
                "conformation": "8x6b",
                "seed": 917,
                "sequence_sha256": "f" * 64,
                "cdr1_range": "1-2",
                "cdr2_range": "3-4",
                "cdr3_range": "5-6",
                "cdr_residues": "1,2,3,4,5,6",
                "receptor_pdb": "inputs/normalized/8x6b_pvrig_receptor.pdb",
                "receptor_chain": "T",
                "control_class": "",
                "expected_behavior": "",
                "ligand_chain": "L",
                "vhh_chain": "A",
                "numbering": "fixture",
                "protocol_core_sha256": core,
            }
        )
        candidate_result = (
            campaign_root
            / MOD.RESULTS_RELATIVE_PATH
            / candidate_job_id
            / "job_result.json"
        )
        candidate_result.parent.mkdir(parents=True, exist_ok=True)
        candidate_result.write_text("not JSON and must never be opened", encoding="utf-8")
        for entity_index, entity_id in enumerate(self.control_ids):
            sequence_sha256 = sha256_text(f"sequence:{entity_id}")
            for conformation_index, conformation in enumerate(MOD.CONFORMATIONS):
                for seed_index, seed in enumerate(MOD.SEEDS):
                    job_id = f"{label}_{entity_id}_{conformation}_{seed}"
                    job: dict[str, object] = {
                        "job_id": job_id,
                        "job_hash": sha256_text(job_id),
                        "entity_type": "control",
                        "entity_id": entity_id,
                        "conformation": conformation,
                        "seed": seed,
                        "sequence_sha256": sequence_sha256,
                        "cdr1_range": "26-33",
                        "cdr2_range": "51-58",
                        "cdr3_range": "97-113",
                        "cdr_residues": "26,27,51,52,97,98",
                        "receptor_pdb": f"inputs/normalized/{conformation}_pvrig_receptor.pdb",
                        "receptor_chain": "T",
                        "control_class": "positive_control",
                        "expected_behavior": "BLOCKER_SUPPORT",
                        "ligand_chain": "L",
                        "vhh_chain": "A",
                        "numbering": "fixture",
                        "protocol_core_sha256": core,
                    }
                    rows.append(job)
                    result = (
                        campaign_root
                        / MOD.RESULTS_RELATIVE_PATH
                        / job_id
                        / "job_result.json"
                    )
                    job_multiplier = multiplier * (
                        0.7
                        + entity_index * 0.01
                        + conformation_index * 0.003
                        + seed_index * 0.001
                    )
                    write_json(result, raw_result(job, core, job_multiplier))
        write_tsv(campaign_root / MOD.MANIFEST_RELATIVE_PATH, rows)
        return rows

    @property
    def expected_jobs(self) -> int:
        return len(self.control_ids) * len(MOD.CONFORMATIONS) * len(MOD.SEEDS)

    def build(self) -> dict[str, object]:
        return MOD.build_bridge(
            self.left_root,
            self.right_root,
            self.out_dir,
            left_label="left",
            right_label="right",
            expected_control_count=len(self.control_ids),
            expected_job_count=self.expected_jobs,
            test_only=True,
            bootstrap_replicates=50,
        )

    def verify(self) -> dict[str, object]:
        return MOD.verify_receipt(
            self.out_dir / MOD.OUTPUT_FILENAMES[-1],
            self.left_root,
            self.right_root,
            left_label="left",
            right_label="right",
            expected_control_count=len(self.control_ids),
            expected_job_count=self.expected_jobs,
            test_only=True,
        )


class CrossCampaignControlBridgeTests(unittest.TestCase):
    def test_frozen_preregistration_and_fail_decision_are_enforced(self) -> None:
        snapshot, preregistration = MOD.load_preregistration(production=True)
        self.assertEqual(snapshot.sha256, MOD.EXPECTED_PREREGISTRATION_SHA256)
        freeze = MOD.load_implementation_freeze(
            snapshot, preregistration, production=True
        )
        self.assertEqual(
            freeze.payload["preregistration_sha256"], snapshot.sha256
        )
        self.assertIn(freeze.manifest.sha256, freeze.sha256_record.payload.decode())
        rows = []
        for entity_index in range(MOD.EXPECTED_CONTROL_COUNT):
            for conformation_index, conformation in enumerate(MOD.CONFORMATIONS):
                for seed_index, seed in enumerate(MOD.SEEDS):
                    left = 0.1 + entity_index / 100.0 + conformation_index / 1000.0 + seed_index / 10000.0
                    rows.append(
                        {
                            "entity_id": f"CTRL_{entity_index:03d}",
                            "conformation": conformation,
                            "seed": seed,
                            "left_job_utility": left,
                            "right_job_utility": 1.0 - left,
                        }
                    )
        metrics, gates, decision = MOD.evaluate_bridge_metrics(
            rows, preregistration, bootstrap_replicates=100
        )
        self.assertEqual(
            set(metrics["report_only"]),
            {
                "overall_pearson",
                "rmse",
                "linear_regression_right_on_left",
                "bland_altman_right_minus_left",
            },
        )
        self.assertTrue(any(payload["status"] == "FAIL" for payload in gates.values()))
        self.assertEqual(decision, "FAIL_NO_LEGACY128_TRAINING_MERGE")

    def test_builder_imports_and_help_runs_without_site_packages_or_numpy(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import numpy", source)
        completed = subprocess.run(
            [sys.executable, "-S", str(MODULE_PATH), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("verify-receipt", completed.stdout)

    def test_full_synthetic_47_by_282_exact_count_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BridgeFixture(Path(directory), controls=MOD.EXPECTED_CONTROL_COUNT)
            result = MOD.build_bridge(
                fixture.left_root,
                fixture.right_root,
                fixture.out_dir,
                left_label="left",
                right_label="right",
                expected_control_count=MOD.EXPECTED_CONTROL_COUNT,
                expected_job_count=MOD.EXPECTED_JOB_COUNT,
                test_only=True,
                bootstrap_replicates=100,
            )
            self.assertEqual(result["job_row_count"], MOD.EXPECTED_JOB_COUNT)
            self.assertEqual(result["control_row_count"], MOD.EXPECTED_CONTROL_COUNT)
            receipt = json.loads(
                (fixture.out_dir / MOD.OUTPUT_FILENAMES[-1]).read_text()
            )
            self.assertEqual(receipt["execution_mode"], "test_fixture")
            self.assertEqual(receipt["candidate_result_paths_opened"], 0)
            self.assertEqual(
                result["decision"],
                "PASS_SHARED_CONTINUOUS_SCALE_FOR_FUTURE_AUXILIARY_ABLATION_ONLY",
            )

    def test_builds_control_only_bridge_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BridgeFixture(Path(directory))
            published: list[str] = []
            real_replace = MOD.os.replace

            def record_replace(source: object, destination: object) -> None:
                destination_path = Path(destination)
                if destination_path.parent == fixture.out_dir:
                    published.append(destination_path.name)
                real_replace(source, destination)

            with mock.patch.object(MOD.os, "replace", side_effect=record_replace):
                result = fixture.build()
            self.assertEqual(
                result["status"],
                "PASS_V4_D_CROSS_CAMPAIGN_CONTROL_BRIDGE_RECEIPT_VERIFIED",
            )
            self.assertEqual(published, list(MOD.OUTPUT_FILENAMES))
            job_rows, _ = MOD.read_output_tsv(fixture.out_dir / MOD.OUTPUT_FILENAMES[0])
            aggregate_rows, _ = MOD.read_output_tsv(
                fixture.out_dir / MOD.OUTPUT_FILENAMES[1]
            )
            self.assertEqual(len(job_rows), fixture.expected_jobs)
            self.assertEqual(len(aggregate_rows), len(fixture.control_ids))
            self.assertTrue(all(float(row["delta_job_utility"]) > 0 for row in job_rows))
            audit = json.loads((fixture.out_dir / MOD.OUTPUT_FILENAMES[2]).read_text())
            self.assertEqual(audit["candidate_result_paths_opened"], 0)
            self.assertEqual(
                audit["campaigns"]["left"][
                    "candidate_manifest_rows_excluded_before_result_paths"
                ],
                1,
            )
            receipt_path = fixture.out_dir / MOD.OUTPUT_FILENAMES[-1]
            receipt = json.loads(receipt_path.read_text())
            self.assertFalse(
                any("CANDIDATE_DO_NOT_OPEN" in path for path in receipt["input_hashes"])
            )
            first_hash = MOD.snapshot_file(receipt_path, "receipt").sha256
            self.assertEqual(fixture.build()["status"], result["status"])
            self.assertEqual(MOD.snapshot_file(receipt_path, "receipt").sha256, first_hash)

    def test_rejects_cross_campaign_sequence_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BridgeFixture(Path(directory))
            control = next(row for row in fixture.right_rows if row["entity_type"] == "control")
            control["sequence_sha256"] = "0" * 64
            write_tsv(fixture.right_root / MOD.MANIFEST_RELATIVE_PATH, fixture.right_rows)
            with self.assertRaisesRegex(MOD.BridgeError, "cross_campaign_identity_mismatch"):
                fixture.build()

    def test_rejects_cdr_receptor_and_seed_mismatch(self) -> None:
        for mismatch in ("cdr", "receptor", "seed"):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as directory:
                fixture = BridgeFixture(Path(directory))
                control = next(
                    row for row in fixture.right_rows if row["entity_type"] == "control"
                )
                if mismatch == "cdr":
                    control["cdr3_range"] = "98-114"
                    write_tsv(
                        fixture.right_root / MOD.MANIFEST_RELATIVE_PATH,
                        fixture.right_rows,
                    )
                    expected = "cross_campaign_identity_mismatch"
                elif mismatch == "receptor":
                    receptor = (
                        fixture.right_root
                        / "inputs/normalized"
                        / f"{control['conformation']}_pvrig_receptor.pdb"
                    )
                    receptor.write_text(
                        "ATOM      1  CA  GLY T   1       9.000   9.000   9.000\n",
                        encoding="utf-8",
                    )
                    expected = "cross_campaign_receptor_mismatch"
                else:
                    control["seed"] = 999
                    write_tsv(
                        fixture.right_root / MOD.MANIFEST_RELATIVE_PATH,
                        fixture.right_rows,
                    )
                    expected = "unexpected_seed"
                with self.assertRaisesRegex(MOD.BridgeError, expected):
                    fixture.build()

    def test_rejects_result_protocol_core_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BridgeFixture(Path(directory))
            control = next(row for row in fixture.right_rows if row["entity_type"] == "control")
            path = (
                fixture.right_root
                / MOD.RESULTS_RELATIVE_PATH
                / str(control["job_id"])
                / "job_result.json"
            )
            payload = json.loads(path.read_text())
            payload["protocol_core_sha256"] = "c" * 64
            write_json(path, payload)
            with self.assertRaisesRegex(MOD.BridgeError, "protocol_core_sha256"):
                fixture.build()

    def test_rejects_control_result_symlink_before_target_is_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BridgeFixture(Path(directory))
            control = next(row for row in fixture.right_rows if row["entity_type"] == "control")
            control_result = (
                fixture.right_root
                / MOD.RESULTS_RELATIVE_PATH
                / str(control["job_id"])
                / "job_result.json"
            )
            candidate = next(
                row for row in fixture.right_rows if row["entity_type"] == "candidate"
            )
            candidate_result = (
                fixture.right_root
                / MOD.RESULTS_RELATIVE_PATH
                / str(candidate["job_id"])
                / "job_result.json"
            )
            control_result.unlink()
            os.symlink(candidate_result, control_result)
            with self.assertRaisesRegex(
                MOD.BridgeError, "not_regular_file_or_symlink_forbidden"
            ):
                fixture.build()

    def test_rejects_tampered_implementation_freeze_binding(self) -> None:
        snapshot, preregistration = MOD.load_preregistration(production=True)
        payload = json.loads(MOD.DEFAULT_IMPLEMENTATION_FREEZE.read_text())
        payload["bindings"]["builder"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            freeze_path = Path(directory) / MOD.DEFAULT_IMPLEMENTATION_FREEZE.name
            record_path = freeze_path.with_suffix(".sha256")
            write_json(freeze_path, payload)
            freeze_hash = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
            record_path.write_text(
                f"{freeze_hash}  {freeze_path.name}\n", encoding="ascii"
            )
            with self.assertRaisesRegex(
                MOD.BridgeError, "implementation_freeze_binding_hash_mismatch:builder"
            ):
                MOD.load_implementation_freeze(
                    snapshot,
                    preregistration,
                    production=False,
                    freeze_path=freeze_path,
                    sha256_record_path=record_path,
                )

    def test_production_mode_rejects_small_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BridgeFixture(Path(directory))
            with self.assertRaisesRegex(MOD.BridgeError, "production_control_count"):
                MOD.build_bridge(
                    fixture.left_root,
                    fixture.right_root,
                    fixture.out_dir,
                    expected_control_count=len(fixture.control_ids),
                    expected_job_count=fixture.expected_jobs,
                    test_only=False,
                )

    def test_tampered_output_fails_receipt_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = BridgeFixture(Path(directory))
            fixture.build()
            path = fixture.out_dir / MOD.OUTPUT_FILENAMES[0]
            path.write_text(path.read_text() + "\n", encoding="utf-8")
            with self.assertRaisesRegex(MOD.BridgeError, "receipt_output_hash_invalid"):
                fixture.verify()

    def test_exact_output_set_rejects_extra_and_symlinked_outputs(self) -> None:
        for attack in ("extra", "symlink"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as directory:
                fixture = BridgeFixture(Path(directory))
                fixture.build()
                if attack == "extra":
                    (fixture.out_dir / "unexpected.txt").write_text("extra\n")
                    expected = "unexpected_output_files"
                else:
                    audit = fixture.out_dir / MOD.OUTPUT_FILENAMES[2]
                    copy = fixture.root / "audit-copy.json"
                    copy.write_bytes(audit.read_bytes())
                    audit.unlink()
                    os.symlink(copy, audit)
                    expected = "output_not_regular_or_symlink_forbidden"
                with self.assertRaisesRegex(MOD.BridgeError, expected):
                    fixture.verify()

    def test_final_snapshot_recheck_detects_input_output_set_and_receipt_toctou(self) -> None:
        for attack in ("input", "output", "output_set", "receipt"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as directory:
                fixture = BridgeFixture(Path(directory))
                fixture.build()
                if attack == "input":
                    control = next(
                        row
                        for row in fixture.right_rows
                        if row["entity_type"] == "control"
                    )
                    target = (
                        fixture.right_root
                        / MOD.RESULTS_RELATIVE_PATH
                        / str(control["job_id"])
                        / "job_result.json"
                    )
                elif attack == "output":
                    target = fixture.out_dir / MOD.OUTPUT_FILENAMES[0]
                elif attack == "receipt":
                    target = fixture.out_dir / MOD.OUTPUT_FILENAMES[-1]
                else:
                    target = fixture.out_dir / "late-extra.txt"
                real_evaluate = MOD.evaluate_bridge_metrics

                def mutate_after_replay(*args: object, **kwargs: object):
                    result = real_evaluate(*args, **kwargs)
                    if attack == "output_set":
                        target.write_text("late extra\n", encoding="utf-8")
                    else:
                        target.write_bytes(target.read_bytes() + b"\n")
                    return result

                expected = {
                    "input": "snapshot_changed_since_capture",
                    "output": "snapshot_changed_since_capture",
                    "output_set": "unexpected_output_files",
                    "receipt": "receipt_changed_during_verification",
                }[attack]
                with mock.patch.object(
                    MOD,
                    "evaluate_bridge_metrics",
                    side_effect=mutate_after_replay,
                ), self.assertRaisesRegex(MOD.BridgeError, expected):
                    fixture.verify()


if __name__ == "__main__":
    unittest.main()
