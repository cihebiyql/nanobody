#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_phase2_v3_p2_v1_2_calibration.py")


def load_module():
    spec = importlib.util.spec_from_file_location("build_v1_2_calibration", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module()


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def pdb_line(
    record: str,
    serial: int,
    atom_name: str,
    resname: str,
    chain: str,
    residue: int,
    x: float,
    *,
    element: str = "C",
) -> str:
    return (
        f"{record:<6}{serial:5d} {atom_name:^4} {resname:>3} {chain}{residue:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00          {element:>2}  "
    )


class CalibrationBuilderFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.positive_workdir = root / "poses/positive_01"
        self.mutant_workdir = root / "poses/mutant_01"
        self.positive_manifest = root / "inputs/positives.csv"
        self.mutant_manifest = root / "inputs/mutants.csv"
        self.hotspots = root / "inputs/hotspots.csv"
        self.references = {
            "8x6b": root / "references/8X6B.pdb",
            "9e6y": root / "references/9E6Y.pdb",
        }
        self._write_inputs()

    def _write_models(self, workdir: Path, models: list[str]) -> None:
        for baseline in MOD.BASELINES:
            directory = workdir / f"haddock3/top_models_aligned_to_{baseline}"
            directory.mkdir(parents=True, exist_ok=True)
            for model in models:
                (directory / f"{model}_aligned_to_{baseline}.pdb").write_text(
                    f"REMARK {workdir.name} {model} {baseline}\nEND\n",
                    encoding="utf-8",
                )

    def _write_inputs(self) -> None:
        self._write_models(
            self.positive_workdir,
            ["cluster_2_model_1", "cluster_1_model_1"],
        )
        self._write_models(self.mutant_workdir, ["cluster_3_model_2"])
        write_csv(
            self.positive_manifest,
            [
                "recommended_order",
                "calibration_name",
                "family",
                "validation_role",
                "sequence_type",
                "workdir",
                "cdr1_range",
                "cdr2_range",
                "cdr3_range",
                "usage_boundary",
            ],
            [
                {
                    "recommended_order": "1",
                    "calibration_name": "positive_01",
                    "family": "P",
                    "validation_role": "positive_anchor",
                    "sequence_type": "original",
                    "workdir": str(self.positive_workdir),
                    "cdr1_range": "26-35",
                    "cdr2_range": "53-59",
                    "cdr3_range": "98-116",
                    "usage_boundary": "calibration_and_leakage_exclusion_only",
                }
            ],
        )
        write_csv(
            self.mutant_manifest,
            [
                "panel_order",
                "mutant_name",
                "family",
                "intended_role",
                "control_type",
                "workdir",
                "cdr1_range",
                "cdr2_range",
                "cdr3_range",
            ],
            [
                {
                    "panel_order": "1",
                    "mutant_name": "mutant_01",
                    "family": "P",
                    "intended_role": "computed perturbation control",
                    "control_type": "mutant",
                    "workdir": str(self.mutant_workdir),
                    "cdr1_range": "26-35",
                    "cdr2_range": "53-59",
                    "cdr3_range": "98-116",
                }
            ],
        )
        self.hotspots.parent.mkdir(parents=True, exist_ok=True)
        self.hotspots.write_text(
            "hotspot_id,pdb_8x6b_ref,pdb_9e6y_ref\nH1,B:1S,A:1S\n",
            encoding="utf-8",
        )
        for baseline, path in self.references.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"REMARK synthetic {baseline}\nEND\n", encoding="utf-8")

    def config(self, outdir: Path, contract=None):
        return MOD.BuildConfig(
            positive_manifest=self.positive_manifest,
            mutant_manifest=self.mutant_manifest,
            pose_scorer=self.root / "absent/pose_scorer.py",
            region_scorer=self.root / "absent/region_scorer.py",
            scoring_helper=self.root / "absent/helper.py",
            hotspots=self.hotspots,
            references=self.references,
            outdir=outdir,
            workspace_root=self.root,
            contract=contract
            or MOD.DatasetContract(
                positive_cases=1,
                mutant_cases=1,
                positive_poses_per_baseline=2,
                mutant_poses_per_baseline=1,
            ),
        )


class V12CalibrationBuilderTests(unittest.TestCase):
    def test_manifest_only_is_byte_deterministic_and_naturally_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CalibrationBuilderFixture(Path(tmp))
            first = fixture.config(fixture.root / "out_first")
            second = fixture.config(fixture.root / "out_second")
            audit_first = MOD.build_package(first, manifest_only=True)
            audit_second = MOD.build_package(second, manifest_only=True)

            first_manifest = first.outdir / MOD.POSE_MANIFEST_NAME
            second_manifest = second.outdir / MOD.POSE_MANIFEST_NAME
            self.assertEqual(first_manifest.read_bytes(), second_manifest.read_bytes())
            self.assertEqual(
                (first.outdir / MOD.AUDIT_NAME).read_bytes(),
                (second.outdir / MOD.AUDIT_NAME).read_bytes(),
            )
            self.assertEqual(audit_first["output_sha256"], audit_second["output_sha256"])

            rows = read_csv(first_manifest)
            observed_order = [
                (row["sample_id"], row["model"], row["baseline"]) for row in rows
            ]
            self.assertEqual(
                observed_order,
                [
                    ("positive_01", "cluster_1_model_1", "8x6b"),
                    ("positive_01", "cluster_1_model_1", "9e6y"),
                    ("positive_01", "cluster_2_model_1", "8x6b"),
                    ("positive_01", "cluster_2_model_1", "9e6y"),
                    ("mutant_01", "cluster_3_model_2", "8x6b"),
                    ("mutant_01", "cluster_3_model_2", "9e6y"),
                ],
            )
            for row in rows:
                self.assertEqual(
                    row["manifest_row_sha256"],
                    MOD.row_hash(row, "manifest_row_sha256"),
                )
                self.assertEqual(row["formal_eligible"], "false")
                self.assertEqual(row["threshold_freeze_eligible"], "false")
            self.assertFalse(audit_first["toolchain_complete"])

    def test_expected_dataset_contract_is_enforced(self) -> None:
        self.assertEqual(MOD.DEFAULT_CONTRACT.positive_cases, 11)
        self.assertEqual(MOD.DEFAULT_CONTRACT.mutant_cases, 36)
        self.assertEqual(MOD.DEFAULT_CONTRACT.positive_poses_per_baseline, 109)
        self.assertEqual(MOD.DEFAULT_CONTRACT.mutant_poses_per_baseline, 357)
        self.assertEqual(MOD.DEFAULT_CONTRACT.total_rows, 932)
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CalibrationBuilderFixture(Path(tmp))
            wrong = MOD.DatasetContract(
                positive_cases=1,
                mutant_cases=1,
                positive_poses_per_baseline=3,
                mutant_poses_per_baseline=1,
            )
            with self.assertRaisesRegex(MOD.ContractError, "Pose-count contract mismatch"):
                MOD.build_package(
                    fixture.config(fixture.root / "out", wrong), manifest_only=True
                )

    def test_missing_or_mismatched_baseline_pose_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CalibrationBuilderFixture(Path(tmp))
            missing = (
                fixture.positive_workdir
                / "haddock3/top_models_aligned_to_9e6y"
                / "cluster_2_model_1_aligned_to_9e6y.pdb"
            )
            missing.unlink()
            with self.assertRaisesRegex(MOD.ContractError, "Mismatched aligned models"):
                MOD.build_package(
                    fixture.config(fixture.root / "out"), manifest_only=True
                )

    def test_outputs_have_no_geometry_classification_or_threshold_labels(self) -> None:
        forbidden_suffixes = ("_classification", "_class", "_tier", "_label")
        for field in MOD.METRICS_FIELDS:
            lowered = field.lower()
            self.assertNotIn(lowered, MOD.FORBIDDEN_RAW_KEYS)
            self.assertFalse(lowered.endswith(forbidden_suffixes), field)
        with tempfile.TemporaryDirectory() as tmp:
            fixture = CalibrationBuilderFixture(Path(tmp))
            config = fixture.config(fixture.root / "out")
            audit = MOD.build_package(config, manifest_only=True)
            fields = read_csv(config.outdir / MOD.POSE_MANIFEST_NAME)[0].keys()
            self.assertNotIn("geometry_tier", fields)
            self.assertNotIn("blocker_class", fields)
            self.assertFalse(audit["thresholds_or_classes_applied"])
            self.assertFalse(audit["threshold_freeze_eligible"])
            self.assertFalse(audit["formal_eligible"])
            self.assertEqual(audit["protocol_id"], "DG_A_PVRIG_V1_2_DEV")
            serialized = json.dumps(audit, sort_keys=True)
            self.assertNotIn("BLOCKER_LIKE_A", serialized)

    @unittest.skipUnless(
        MOD.DEFAULT_POSE_SCORER.is_file() and MOD.DEFAULT_REGION_SCORER.is_file(),
        "V1.2 scorer integration requires both scorer files",
    )
    def test_real_v1_2_scorer_payload_shapes_integrate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pose = root / "pose.pdb"
            reference = root / "reference.pdb"
            hotspots = root / "hotspots.csv"
            pose.write_text(
                "\n".join(
                    [
                        pdb_line("ATOM", 1, "CA", "SER", "B", 10, 0.0),
                        pdb_line("ATOM", 2, "CA", "TYR", "A", 100, 4.5),
                        "END",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            reference.write_text(
                "\n".join(
                    [
                        pdb_line("ATOM", 1, "CA", "ALA", "D", 1, 9.0),
                        pdb_line("HETATM", 2, "O", "HOH", "D", 201, 4.5, element="O"),
                        pdb_line("HETATM", 3, "C1", "EDO", "D", 202, 5.0),
                        "END",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            hotspots.write_text(
                "hotspot_id,pdb_test_ref,priority_weight\nH1,C:10S,1\n",
                encoding="utf-8",
            )
            pose_json = root / "pose_score.json"
            region_json = root / "region_score.json"
            pose_report = MOD.run_scorer(
                [
                    sys.executable,
                    str(MOD.DEFAULT_POSE_SCORER),
                    "--pose-pdb",
                    str(pose),
                    "--reference-pdb",
                    str(reference),
                    "--pvrig-chain",
                    "B",
                    "--vhh-chain",
                    "A",
                    "--ref-pvrig-chain",
                    "C",
                    "--ref-pvrl2-chain",
                    "D",
                    "--hotspots-csv",
                    str(hotspots),
                    "--hotspot-ref-column",
                    "pdb_test_ref",
                    "--cdr-ranges",
                    "CDR3:100-100",
                    "--assume-aligned",
                    "--out-json",
                    str(pose_json),
                ],
                pose_json,
                "real pose scorer integration fixture",
            )
            region_report = MOD.run_scorer(
                [
                    sys.executable,
                    str(MOD.DEFAULT_REGION_SCORER),
                    "--pose-pdb",
                    str(pose),
                    "--reference-pdb",
                    str(reference),
                    "--vhh-chain",
                    "A",
                    "--ref-pvrl2-chain",
                    "D",
                    "--cdr1",
                    "26-35",
                    "--cdr2",
                    "53-59",
                    "--cdr3",
                    "100-100",
                    "--out-json",
                    str(region_json),
                ],
                region_json,
                "real region scorer integration fixture",
            )
            manifest_row = {field: "" for field in MOD.MANIFEST_FIELDS}
            metric_row = MOD.flatten_metric_row(
                manifest_row, pose_report, region_report
            )
            pose_ref = json.loads(metric_row["reference_pvrl2_record_inventory_json"])
            region_ref = json.loads(
                metric_row["region_reference_pvrl2_record_inventory_json"]
            )
            self.assertEqual(pose_ref["excluded_hetatm_heavy_atom_count"], 2)
            self.assertEqual(region_ref["excluded_hetatm_heavy_atom_count"], 2)
            self.assertIn("excluded_hydrogen_or_deuterium_count", pose_ref)
            self.assertIn("excluded_hydrogen_count", region_ref)
            self.assertNotEqual(
                metric_row["reference_pvrl2_record_inventory_sha256"],
                metric_row["region_reference_pvrl2_record_inventory_sha256"],
            )
            self.assertEqual(
                metric_row["scoring_semantics_version"],
                MOD.SCORING_SEMANTICS_VERSION,
            )


if __name__ == "__main__":
    unittest.main()
