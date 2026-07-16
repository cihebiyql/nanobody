#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_pvrig_geometry_shortlist.py")
SPEC = importlib.util.spec_from_file_location("pvrig_geometry_shortlist", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def row(candidate_id: str, **overrides: str) -> dict[str, str]:
    result = {
        "candidate_id": candidate_id, "sequence": "QVQLV" + candidate_id[-3:],
        "source_cohort": "FULLQC290_PRIMARY", "model_split": "OPEN_TRAIN",
        "geometry_status": "OPEN_USABLE", "r_dual_min": "0.50", "r_dual_gap": "0.10",
        "geometry_uncertainty": "0.10", "successful_seeds_8x6b": "3",
        "successful_seeds_9e6y": "3", "parent_id": "parent_" + candidate_id[-2:],
        "target_patch_id": "A_CENTER", "design_mode": "H3", "cdr3_cluster": "cluster_" + candidate_id,
        "full_qc_status": "COMPLETE_HARD_PASS_ABNATIV_COMPLETE", "official_validator_pass": "true",
        "leakage_status": "NO_KNOWN_POSITIVE_LEAKAGE", "developability_score": "0.80",
        "abnativ_vhh_score": "0.80", "max_positive_cdr_identity": "0.20",
        "generic_binding_prior": "0.50", "generic_prior_uncertainty": "0.10",
    }
    result.update(overrides)
    return result


def write_master(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class GeometryShortlistTests(unittest.TestCase):
    def test_equal_metric_values_receive_equal_midrank_percentiles(self) -> None:
        rows = [
            {"candidate_id": "A", "metric": "1"},
            {"candidate_id": "B", "metric": "1"},
            {"candidate_id": "C", "metric": "3"},
        ]
        scores = MOD.percentiles(rows, "metric")
        self.assertEqual(scores["A"], scores["B"])
        self.assertEqual(scores["A"], 0.25)
        self.assertEqual(scores["C"], 1.0)

    def test_sealed_and_dual128_are_excluded(self) -> None:
        rows = [row("open"), row("sealed", model_split="SEALED_TEST"), row("dual", source_cohort="DUAL128_SECONDARY")]
        eligible, exclusions = MOD.eligible_rows(rows, 3)
        self.assertEqual([candidate["candidate_id"] for candidate in eligible], ["open"])
        self.assertEqual(exclusions["SEALED_OR_TEST_SPLIT"], 1)
        self.assertEqual(exclusions["NON_FULLQC290"], 1)

    def test_r_dual_min_is_primary_over_generic_prior(self) -> None:
        rows = [
            row("geometry_high", r_dual_min="0.95", generic_binding_prior="0.01"),
            row("prior_high", r_dual_min="0.10", generic_binding_prior="0.99"),
        ]
        MOD.add_scores(rows, 3)
        ranked = sorted(rows, key=lambda item: -float(item["geometry_rank_score"]))
        self.assertEqual(ranked[0]["candidate_id"], "geometry_high")
        self.assertEqual(ranked[0]["generic_prior_role"], "WEAK_PRIOR_WEIGHT_0.02")

    def test_tnp_and_igfold_annotations_do_not_change_ranking(self) -> None:
        rows = [
            row("geometry_high", r_dual_min="0.95", tnp_status="NOT_RUN", igfold_status="NOT_RUN"),
            row("geometry_low", r_dual_min="0.10", tnp_status="RISK_FLAGS", igfold_status="FAIL"),
        ]
        MOD.add_scores(rows, 3)
        ranked = sorted(rows, key=lambda item: -float(item["geometry_rank_score"]))
        self.assertEqual(ranked[0]["candidate_id"], "geometry_high")
        self.assertIn("not eligibility gates", ranked[0]["deepqc_policy"])

    def test_diversity_caps_are_enforced(self) -> None:
        rows = []
        for index in range(8):
            rows.append(row(
                f"candidate_{index:02d}", parent_id="same_parent" if index < 4 else f"parent_{index}",
                target_patch_id="A_CENTER" if index < 3 else "B_LOWER",
                design_mode="H3", cdr3_cluster="same_cluster" if index < 3 else f"cluster_{index}",
                geometry_rank_score=f"{10 - index}.0",
            ))
        selected = MOD.select_diverse(rows, 5, parent_cap=3, parent_patch_mode_cap=2, cdr3_cluster_cap=2)
        self.assertLessEqual(sum(item["parent_id"] == "same_parent" for item in selected), 3)
        self.assertLessEqual(sum(item["cdr3_cluster"] == "same_cluster" for item in selected), 2)

    def test_missing_geometry_fails_closed(self) -> None:
        rows = [row("missing", r_dual_min="")]
        with self.assertRaisesRegex(ValueError, "missing r_dual_min"):
            MOD.eligible_rows(rows, 3)

    def test_cli_outputs_pose_manifest_with_two_conformations(self) -> None:
        rows = [row(f"candidate_{index:03d}", parent_id=f"parent_{index}") for index in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master = root / "master.tsv"
            output = root / "out"
            write_master(master, rows)
            audit = MOD.run(MOD.parse_args([
                "--master", str(master), "--outdir", str(output), "--expected-open-count", "0",
                "--expected-sealed-count", "0",
                "--shortlist-size", "5", "--pose-review-size", "2",
            ]))
            self.assertEqual(audit["pose_review_manifest_rows"], 4)
            with (output / "top20_pose_review_manifest.tsv").open() as handle:
                manifest = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual({item["conformation"] for item in manifest}, {"8X6B", "9E6Y"})
            self.assertTrue(all(item["job_or_pose_bundle_status"] == "PENDING_SYNC" for item in manifest))


if __name__ == "__main__":
    unittest.main()
