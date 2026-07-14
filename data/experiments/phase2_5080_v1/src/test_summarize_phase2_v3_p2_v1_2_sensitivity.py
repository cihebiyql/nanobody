#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("summarize_phase2_v3_p2_v1_2_sensitivity.py")


def load_module():
    spec = importlib.util.spec_from_file_location("summarize_v1_2_sensitivity", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module()


def write_csv(path: Path, rows: list[dict[str, str]], fields=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(fields or rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class SyntheticFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.metrics = root / "inputs/metrics.csv"
        self.rescore_audit = root / "inputs/rescore_audit.json"
        self.positive_manifest = root / "inputs/positive_manifest.csv"
        self.mutant_manifest = root / "inputs/mutant_manifest.csv"
        self.old_rules = root / "tools/rules.json"
        self.old_classifier = root / "tools/classifier.py"
        self.positive_workdir = root / "legacy/positive_01"
        self.mutant_workdir = root / "legacy/mutant_01"
        self._write_tools()
        self._write_manifests()
        self._write_legacy()
        self._write_metrics()
        self.refresh_audit()

    def _write_tools(self) -> None:
        self.old_rules.parent.mkdir(parents=True, exist_ok=True)
        self.old_rules.write_text('{"threshold": 10}\n', encoding="utf-8")
        self.old_classifier.write_text(
            """import json
def load_rules(path):
    return json.loads(path.read_text())
def classify(row, rules, format_context, source_files):
    total = float(row['total_vhh_pvrl2_residue_pair_occlusion'])
    return {'blocker_class': 'BLOCKER_LIKE_A' if total >= rules['threshold'] else 'EVIDENCE_INFERENCE_ONLY_E'}
""",
            encoding="utf-8",
        )

    def _write_manifests(self) -> None:
        write_csv(
            self.positive_manifest,
            [
                {
                    "recommended_order": "1",
                    "calibration_name": "positive_01",
                    "family": "F1",
                    "sequence_type": "original",
                    "workdir": str(self.positive_workdir),
                }
            ],
        )
        write_csv(
            self.mutant_manifest,
            [
                {
                    "panel_order": "1",
                    "mutant_name": "mutant_01",
                    "family": "F1",
                    "mutation_class": "single_conservative_cdr3",
                    "control_type": "mutant",
                    "workdir": str(self.mutant_workdir),
                }
            ],
        )

    @staticmethod
    def old_row(model: str, baseline: str) -> dict[str, str]:
        return {
            "model": model,
            "baseline": baseline,
            "hotspot_overlap_count": "14",
            "total_vhh_pvrl2_atom_occlusion": "100",
            "total_vhh_pvrl2_residue_pair_occlusion": "20",
            "cdr3_atom_occlusion": "40",
            "cdr3_atom_occlusion_fraction": "0.4",
            "cdr3_residue_pair_occlusion": "8",
            "cdr3_residue_pair_occlusion_fraction": "0.4",
            "framework_residue_pair_occlusion": "12",
        }

    def _write_legacy(self) -> None:
        for sample_id, workdir in (
            ("positive_01", self.positive_workdir),
            ("mutant_01", self.mutant_workdir),
        ):
            for baseline in MOD.BASELINES:
                reports = workdir / "reports"
                write_csv(
                    reports / f"{baseline}_baseline/cdr3_occlusion_summary_{baseline}.csv",
                    [self.old_row("cluster_1_model_1", baseline)],
                )
                write_csv(
                    reports / f"{sample_id}_{baseline}_blocker_classification.csv",
                    [
                        {
                            "model": "cluster_1_model_1",
                            "blocker_class": "BLOCKER_LIKE_A",
                        }
                    ],
                )

    def inventory(self, baseline: str) -> dict:
        excluded = 1 if baseline == "8x6b" else 2
        return {
            "chain": "A" if baseline == "8x6b" else "D",
            "parsed_atom_and_hetatm_count": 10 + excluded,
            "protein_atom_heavy_atom_count": 10,
            "protein_atom_residue_count": 2,
            "selected_protein_heavy_atom_count": 10,
            "selected_protein_residue_count": 2,
            "excluded_hetatm_heavy_atom_count": excluded,
            "excluded_hetatm_residue_count": excluded,
            "excluded_hoh_heavy_atom_count": 1,
            "excluded_hoh_residue_count": 1,
            "excluded_edo_heavy_atom_count": excluded - 1,
            "excluded_edo_residue_count": excluded - 1,
            "excluded_other_hetatm_heavy_atom_count": 0,
            "excluded_other_hetatm_residue_count": 0,
            "excluded_hydrogen_or_deuterium_count": 0,
            "atom_altloc_heavy_atom_count": 0,
            "atom_altloc_labels": [],
            "selection_rule": "protein ATOM heavy atoms only; all HETATM excluded",
        }

    def _write_metrics(self) -> None:
        positive_rows = read_csv(self.positive_manifest)
        mutant_rows = read_csv(self.mutant_manifest)
        source_info = {
            "positive_01": {
                "source_dataset": "known_positive_calibration",
                "source_order": "1",
                "family": "F1",
                "manifest": self.positive_manifest,
                "manifest_row": positive_rows[0],
                "new_total": 15,
            },
            "mutant_01": {
                "source_dataset": "mutant_or_reference_control",
                "source_order": "1",
                "family": "F1",
                "manifest": self.mutant_manifest,
                "manifest_row": mutant_rows[0],
                "new_total": 5,
            },
        }
        rows = []
        for sample_id, info in source_info.items():
            for baseline in MOD.BASELINES:
                inventory = self.inventory(baseline)
                total = info["new_total"]
                row = {
                    "source_dataset": info["source_dataset"],
                    "source_order": info["source_order"],
                    "sample_id": sample_id,
                    "family": info["family"],
                    "model": "cluster_1_model_1",
                    "baseline": baseline,
                    "formal_eligible": "false",
                    "threshold_freeze_eligible": "false",
                    "source_pose_sha256": "a" * 64,
                    "source_manifest_sha256": MOD.sha256_file(info["manifest"]),
                    "source_manifest_row_sha256": MOD.sha256_json(info["manifest_row"]),
                    "hotspot_overlap_count": "14",
                    "total_occluding_atom_contact_count": str(total * 5),
                    "total_occluding_residue_pair_count": str(total),
                    "cdr3_occluding_atom_contact_count": "30" if total >= 10 else "10",
                    "cdr3_occlusion_fraction_of_total": "0.4",
                    "cdr3_occluding_residue_pair_count": "6" if total >= 10 else "2",
                    "cdr3_occluding_residue_pair_fraction_of_total": "0.4",
                    "framework_occluding_residue_pair_count": str(total - (6 if total >= 10 else 2)),
                    "reference_pvrl2_record_inventory_json": MOD.canonical_json(inventory),
                    "reference_pvrl2_record_inventory_sha256": MOD.sha256_json(inventory),
                }
                row["metrics_row_sha256"] = MOD.row_hash(row, "metrics_row_sha256")
                rows.append(row)
        write_csv(self.metrics, rows)

    def refresh_metrics_row_hashes(self) -> None:
        rows = read_csv(self.metrics)
        for row in rows:
            row["metrics_row_sha256"] = MOD.row_hash(row, "metrics_row_sha256")
        write_csv(self.metrics, rows)

    def refresh_audit(self) -> None:
        metrics_hash = MOD.sha256_file(self.metrics)
        payload = {
            "status": "PASS_V1_2_DEVELOPMENT_SENSITIVITY_RESCORE_BUILT",
            "formal_eligible": False,
            "threshold_freeze_eligible": False,
            "output_sha256": {"continuous_metrics": metrics_hash},
            "observed_inventory": {"total_rows": len(read_csv(self.metrics))},
        }
        self.rescore_audit.parent.mkdir(parents=True, exist_ok=True)
        self.rescore_audit.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def config(self, output_name: str = "out"):
        out = self.root / output_name
        return MOD.SummaryConfig(
            metrics=self.metrics,
            rescore_audit=self.rescore_audit,
            positive_manifest=self.positive_manifest,
            mutant_manifest=self.mutant_manifest,
            old_rules=self.old_rules,
            old_classifier=self.old_classifier,
            delta_csv=out / "delta.csv",
            audit_json=out / "audit.json",
            report_md=out / "report.md",
            expected_metrics_sha256=MOD.sha256_file(self.metrics),
            expected_rescore_audit_sha256=MOD.sha256_file(self.rescore_audit),
            expected_old_rules_sha256=MOD.sha256_file(self.old_rules),
            expected_old_classifier_sha256=MOD.sha256_file(self.old_classifier),
            expected_rows=4,
            expected_samples=2,
            workspace_root=self.root,
        )


class V12SensitivitySummaryTests(unittest.TestCase):
    def test_outputs_are_deterministic_and_keep_diagnostic_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SyntheticFixture(Path(tmp))
            first = fixture.config("first")
            second = fixture.config("second")
            audit_first = MOD.run_summary(first)
            audit_second = MOD.run_summary(second)
            self.assertEqual(first.delta_csv.read_bytes(), second.delta_csv.read_bytes())
            self.assertEqual(first.report_md.read_bytes(), second.report_md.read_bytes())
            self.assertEqual(first.audit_json.read_bytes(), second.audit_json.read_bytes())
            self.assertEqual(audit_first["output_sha256"], audit_second["output_sha256"])
            self.assertEqual(audit_first["row_closure"]["delta_rows"], 4)
            self.assertEqual(audit_first["old_rule_replay"]["mismatches"], 0)
            self.assertFalse(audit_first["threshold_freeze_eligible"])
            self.assertFalse(audit_first["v1_2_labels_emitted"])
            rows = read_csv(first.delta_csv)
            self.assertEqual(sum(row["old_rule_class_changed"] == "true" for row in rows), 2)
            self.assertTrue(all(row["diagnostic_only"] == "true" for row in rows))
            for row in rows:
                self.assertEqual(
                    row["delta_row_sha256"], MOD.row_hash(row, "delta_row_sha256")
                )

    def test_duplicate_and_unmatched_rows_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SyntheticFixture(Path(tmp))
            rows = read_csv(fixture.metrics)
            rows[-1] = dict(rows[0])
            write_csv(fixture.metrics, rows)
            fixture.refresh_audit()
            with self.assertRaisesRegex(MOD.ClosureError, "Duplicate key"):
                MOD.run_summary(fixture.config())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = SyntheticFixture(Path(tmp))
            path = (
                fixture.positive_workdir
                / "reports/8x6b_baseline/cdr3_occlusion_summary_8x6b.csv"
            )
            row = read_csv(path)[0]
            row["model"] = "cluster_9_model_9"
            write_csv(path, [row])
            with self.assertRaisesRegex(MOD.ClosureError, "model mismatch"):
                MOD.run_summary(fixture.config())

    def test_nonfinite_metric_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SyntheticFixture(Path(tmp))
            rows = read_csv(fixture.metrics)
            rows[0]["total_occluding_residue_pair_count"] = "nan"
            write_csv(fixture.metrics, rows)
            fixture.refresh_metrics_row_hashes()
            fixture.refresh_audit()
            with self.assertRaisesRegex(MOD.ClosureError, "Non-finite numeric"):
                MOD.run_summary(fixture.config())

    def test_expected_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SyntheticFixture(Path(tmp))
            config = fixture.config()
            bad = MOD.SummaryConfig(
                **{
                    **config.__dict__,
                    "expected_metrics_sha256": "0" * 64,
                }
            )
            with self.assertRaisesRegex(MOD.ClosureError, "SHA256 mismatch"):
                MOD.run_summary(bad)


if __name__ == "__main__":
    unittest.main()
