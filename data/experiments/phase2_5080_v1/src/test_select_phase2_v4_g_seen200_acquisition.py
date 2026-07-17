#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("select_phase2_v4_g_seen200_acquisition.py")
SPEC = importlib.util.spec_from_file_location("select_phase2_v4_g_seen200_acquisition", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def aa_token(index: int, length: int) -> str:
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    value = index + 1
    output: list[str] = []
    for _ in range(length):
        output.append(alphabet[value % len(alphabet)])
        value = value // len(alphabet) + 1
    return "".join(output)


def write_table(path: Path, rows: list[dict[str, object]], delimiter: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=delimiter, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class Seen200SelectorTest(unittest.TestCase):
    def make_fixture(self, root: Path, *, branch: str = "PASS", reverse_scores: bool = False):
        source_parents = ["C0001", "C0002"]
        v4f_parent = "C0090"
        reserve_parents = ["C0098", "C0099"]
        pool: list[dict[str, str]] = []
        counter = 0
        for parent in [*source_parents, v4f_parent, *reserve_parents]:
            count = 17 if parent in source_parents else 1
            for replicate in range(count):
                cdr1 = aa_token(counter * 3, 7)
                cdr2 = aa_token(counter * 3 + 1, 7)
                cdr3 = aa_token(counter * 3 + 2, 11 + (replicate % 3))
                sequence = (
                    "QVQLVESGGGLVQPGGSLRLSCAAS"
                    + cdr1
                    + "WFRQAPGKEREFVA"
                    + cdr2
                    + "RFTISRDNAKNTVYLQMNSLKPEDTAVYYC"
                    + cdr3
                    + "WGQGTQVTVSS"
                )
                candidate_id = f"{parent}_candidate_{replicate:02d}"
                pool.append(
                    {
                        "candidate_id": candidate_id,
                        "vhh_sequence": sequence,
                        "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                        "parent_id": f"P_{parent}",
                        "parent_framework_cluster": parent,
                        "design_method": "synthetic",
                        "design_mode": "H3" if replicate % 2 else "H1H3",
                        "target_patch_id": ("A_CENTER", "B_LOWER", "C_CROSS")[replicate % 3],
                        "cdr1_after": cdr1,
                        "cdr2_after": cdr2,
                        "cdr3_after": cdr3,
                        "cdr3_length": str(len(cdr3)),
                        "fast_gate_tier": "FORMAL_ELIGIBLE",
                        "hard_fail": "False",
                    }
                )
                counter += 1
        pool_path = root / "pool.csv"
        write_table(pool_path, pool, ",")

        by_id = {row["candidate_id"]: row for row in pool}
        v4d: list[dict[str, str]] = []
        for parent in source_parents:
            source = by_id[f"{parent}_candidate_00"]
            v4d.append(
                {
                    "candidate_id": source["candidate_id"],
                    "sequence_sha256": source["sequence_sha256"],
                    "sequence": source["vhh_sequence"],
                    "parent_id": source["parent_id"],
                    "parent_framework_cluster": source["parent_framework_cluster"],
                    "original_formal_split": "train",
                    "model_split": "OPEN_TRAIN",
                    "design_method": source["design_method"],
                    "design_mode": source["design_mode"],
                    "target_patch_id": source["target_patch_id"],
                    "cdr1": source["cdr1_after"],
                    "cdr2": source["cdr2_after"],
                    "cdr3": source["cdr3_after"],
                    "cdr3_length": source["cdr3_length"],
                    "new_dual_docking_label_policy": "OPEN_AFTER_PRODUCTION_EVALUATOR_PASS",
                    "claim_boundary": "identity only",
                }
            )
        v4d_path = root / "v4d.tsv"
        write_table(v4d_path, v4d, "\t")

        v4f_source = by_id[f"{v4f_parent}_candidate_00"]
        v4f = [
            {
                "candidate_id": v4f_source["candidate_id"],
                "sequence_sha256": v4f_source["sequence_sha256"],
                "sequence": v4f_source["vhh_sequence"],
                "parent_id": v4f_source["parent_id"],
                "parent_framework_cluster": v4f_source["parent_framework_cluster"],
                "design_method": v4f_source["design_method"],
                "design_mode": v4f_source["design_mode"],
                "target_patch_id": v4f_source["target_patch_id"],
                "cdr1": v4f_source["cdr1_after"],
                "cdr2": v4f_source["cdr2_after"],
                "cdr3": v4f_source["cdr3_after"],
                "cdr3_length": v4f_source["cdr3_length"],
                "model_split": "PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT",
                "selection_stratum": f"{v4f_parent}|A_CENTER|H1H3",
                "full_qc_and_docking_policy": "identity only",
                "claim_boundary": "identity only",
            }
        ]
        v4f_path = root / "v4f.tsv"
        write_table(v4f_path, v4f, "\t")

        reserve = [
            {
                "parent_framework_cluster": parent,
                "parent_ids": f"P_{parent}",
                "selection_role": "UNTOUCHED_V4_G_RESERVE_PARENT",
                "parent_hash_rank": str(index + 1),
                "selection_hash": hashlib.sha256(parent.encode()).hexdigest(),
                "eligible_candidate_count": "1",
                "eligible_stratum_count": "1",
                "minimum_eligible_rows_per_stratum": "1",
                "untouched_policy": "identity only",
                "claim_boundary": "identity only",
            }
            for index, parent in enumerate(reserve_parents)
        ]
        reserve_path = root / "reserve.tsv"
        write_table(reserve_path, reserve, "\t")

        calibration_source = by_id["C0001_candidate_01"]
        calibration = [
            {
                "sequence_sha256": calibration_source["sequence_sha256"],
                "sequence": calibration_source["vhh_sequence"],
                "calibration_aliases": "CAL_001",
                "exclusion_role": "KNOWN_PVRIG_CALIBRATION_SEQUENCE_EXCLUDED_FROM_CANDIDATE_ACQUISITION",
                "claim_boundary": "identity-only exclusion",
            }
        ]
        calibration_path = root / "calibration.tsv"
        write_table(calibration_path, calibration, "\t")

        parent_prereg = {
            "status": "FROZEN_LABEL_FREE_BEFORE_V4D_OPEN_TEACHER_OR_V4F_DOCKING_LABELS",
            "future_seen200": {
                "source_parent_clusters": source_parents,
                "rows": 20,
                "rows_per_parent": 10,
                "model_open_gate_pass_quota_per_parent": {
                    "top": 4,
                    "uncertainty": 3,
                    "disagreement": 2,
                    "control": 1,
                },
                "model_open_gate_fail_quota_per_parent": {
                    "label_free_diverse_replacing_top": 4,
                    "uncertainty": 3,
                    "disagreement": 2,
                    "control": 1,
                },
            },
            "label_access": {
                "docking_label_files_opened": 0,
                "v4d_prospective_test_labels_opened": 0,
                "v4f_labels_opened": 0,
                "experimental_labels_opened": 0,
            },
        }
        prereg_path = root / "parent_prereg.json"
        write_json(prereg_path, parent_prereg)

        model_gate_pass = branch == "PASS"
        score_rows: list[dict[str, object]] = []
        no_score_ids = {row["candidate_id"] for row in [*v4d, *v4f]}
        no_score_parents = set(reserve_parents)
        for index, candidate in enumerate(pool):
            no_score = (
                candidate["candidate_id"] in no_score_ids
                or candidate["parent_framework_cluster"] in no_score_parents
            )
            prediction = 0.1 + index / 1000
            uncertainty = 0.2 + ((index * 7) % 17) / 100
            disagreement = 0.3 + ((index * 11) % 19) / 100
            route = (
                "MODEL_DEVELOPMENT_OR_CHALLENGE_EXCLUDED_NO_SCORE"
                if candidate["candidate_id"] in {row["candidate_id"] for row in v4d}
                else "PROSPECTIVE_V4_F_SEPARATE_FREEZER_NO_SCORE"
                if candidate["candidate_id"] in {row["candidate_id"] for row in v4f}
                else "UNTOUCHED_RESERVE_NO_SCORE"
                if candidate["parent_framework_cluster"] in no_score_parents
                else "EXPLOITATION"
                if model_gate_pass
                else "EXPLOITATION_BLOCKED_MODEL_GATE"
            )
            score_rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "sequence_sha256": candidate["sequence_sha256"],
                    "parent_framework_cluster": candidate["parent_framework_cluster"],
                    "design_method": candidate["design_method"],
                    "design_mode": candidate["design_mode"],
                    "target_patch_id": candidate["target_patch_id"],
                    "v4d_support_domain": "TRAIN_REFERENCE" if no_score else "IN_DOMAIN",
                    "v4d_support_domain_reason": "synthetic",
                    "scoring_governance": route if no_score else "DEPLOYMENT_SCORING_ALLOWED",
                    "model_scoring_permitted": str(not no_score),
                    "support_release_all_gates_passed": "True",
                    "model_open_gates_passed": str(model_gate_pass),
                    "deployment_route": route,
                    "exploitation_eligible": str(route == "EXPLOITATION"),
                    "portfolio_diversity_required": "False",
                    "base_model": "" if no_score else "base",
                    "base_prediction": "" if no_score else f"{prediction:.9f}",
                    "base_ensemble_uncertainty": "" if no_score else f"{uncertainty:.9f}",
                    "embedding_model": "" if no_score else "embedding",
                    "embedding_prediction": "" if no_score else f"{prediction + .01:.9f}",
                    "embedding_ensemble_uncertainty": "" if no_score else f"{uncertainty + .01:.9f}",
                    "contact_model": "" if no_score else "contact",
                    "contact_prediction": "" if no_score else f"{prediction - .01:.9f}",
                    "contact_ensemble_uncertainty": "" if no_score else f"{uncertainty - .01:.9f}",
                    "consensus_prediction": "" if no_score else f"{prediction:.9f}",
                    "ensemble_uncertainty": "" if no_score else f"{uncertainty:.9f}",
                    "model_disagreement": "" if no_score else f"{disagreement:.9f}",
                    "exploration_priority": "" if no_score else f"{uncertainty + disagreement:.9f}",
                    "exploitation_rank": "" if no_score or not model_gate_pass else str(index + 1),
                    "exploration_rank": "",
                    "claim_boundary": "prediction only",
                }
            )
        if reverse_scores:
            score_rows.reverse()
        scores_path = root / "candidate7087_deployment_scores.tsv"
        write_table(scores_path, score_rows, "\t")
        summary = {
            "schema_version": MOD.DEPLOYMENT_SCHEMA_VERSION,
            "status": (
                "PASS_DEPLOYMENT_SCORES_ROUTED"
                if model_gate_pass
                else "PASS_INFERENCE_ONLY_SCORES_EXPLOITATION_BLOCKED"
            ),
            "candidate_count": len(pool),
            "model_open_gates_all_passed": model_gate_pass,
            "support_release": {"all_gates_passed": True},
            "prospective_test_labels_read": False,
            "prospective_test_label_paths_accepted": 0,
            "v4f_labels_read": False,
            "experimental_labels_read": False,
        }
        summary_path = root / "candidate7087_deployment_summary.json"
        write_json(summary_path, summary)
        receipt = {
            "schema_version": MOD.DEPLOYMENT_SCHEMA_VERSION,
            "status": "PASS_DEPLOYMENT_SCORING_HASH_CLOSURE",
            "candidate_count": len(pool),
            "outputs": {
                str(scores_path.resolve()): MOD.sha256_file(scores_path),
                str(summary_path.resolve()): MOD.sha256_file(summary_path),
            },
            "prospective_test_labels_read": False,
            "prospective_test_label_paths_accepted": 0,
            "v4f_labels_read": False,
            "experimental_labels_read": False,
        }
        receipt_path = root / "candidate7087_deployment_receipt.json"
        write_json(receipt_path, receipt)

        freeze = {
            "schema_version": MOD.IMPLEMENTATION_FREEZE_VERSION,
            "status": "FROZEN_BEFORE_V4D_OPEN_MODEL_RESULTS_NO_SEEN200_SELECTION",
            "production_selection_executed": False,
            "label_access": {
                "v4d_open_model_results_opened": 0,
                "v4d_prospective_test_labels_opened": 0,
                "v4f_labels_opened": 0,
                "experimental_labels_opened": 0,
            },
            "artifacts": {
                "selector": {"path": str(MODULE_PATH.resolve()), "sha256": MOD.sha256_file(MODULE_PATH)},
                "tests": {"path": str(Path(__file__).resolve()), "sha256": MOD.sha256_file(Path(__file__))},
                "parent_preregistration": {"path": str(prereg_path.resolve()), "sha256": MOD.sha256_file(prereg_path)},
                "calibration_exclusions": {"path": str(calibration_path.resolve()), "sha256": MOD.sha256_file(calibration_path)},
            },
            "selection_policy": {
                "pass_quota_order": [list(value) for value in MOD.PASS_QUOTAS],
                "fail_quota_order": [list(value) for value in MOD.FAIL_QUOTAS],
            },
            "test_evidence": {"status": "PASS", "tests_run": 99},
        }
        freeze["freeze_payload_sha256"] = MOD.sha256_json(freeze)
        freeze_path = root / "freeze.json"
        write_json(freeze_path, freeze)
        paths = {
            "candidate_pool": pool_path,
            "deployment_scores": scores_path,
            "deployment_summary": summary_path,
            "deployment_receipt": receipt_path,
            "v4d_manifest": v4d_path,
            "v4f_manifest": v4f_path,
            "reserve2_manifest": reserve_path,
            "calibration_exclusions": calibration_path,
            "parent_preregistration": prereg_path,
            "implementation_freeze": freeze_path,
        }
        return {
            "paths": paths,
            "pool": pool,
            "v4d": v4d,
            "v4f": v4f,
            "reserve_parents": reserve_parents,
            "calibration": calibration,
            "source_parents": source_parents,
            "output": root / "out",
        }

    def run_fixture(self, fixture, *, verify_only: bool = False):
        return MOD.run(
            fixture["paths"],
            fixture["output"],
            verify_only=verify_only,
            enforce_production_locks=False,
            expected_pool_rows=len(fixture["pool"]),
            expected_v4d_rows=len(fixture["v4d"]),
            expected_v4f_rows=len(fixture["v4f"]),
            expected_source_parents=len(fixture["source_parents"]),
        )

    def read_manifest(self, fixture):
        with (fixture["output"] / MOD.OUTPUT_FILENAMES[0]).open() as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def test_pass_branch_exact_4_3_2_1_and_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory), branch="PASS")
            result = self.run_fixture(fixture)
            self.assertEqual(result["audit"]["model_open_gate_branch"], "PASS")
            rows = self.read_manifest(fixture)
            self.assertEqual(len(rows), 20)
            expected = dict(MOD.PASS_QUOTAS)
            for parent in fixture["source_parents"]:
                counts = Counter(row["selection_bucket"] for row in rows if row["parent_framework_cluster"] == parent)
                self.assertEqual(dict(counts), expected)
            forbidden_ids = {row["candidate_id"] for row in [*fixture["v4d"], *fixture["v4f"]]}
            forbidden_hashes = {row["sequence_sha256"] for row in fixture["calibration"]}
            self.assertFalse({row["candidate_id"] for row in rows} & forbidden_ids)
            self.assertFalse({row["sequence_sha256"] for row in rows} & forbidden_hashes)
            self.assertFalse({row["parent_framework_cluster"] for row in rows} & set(fixture["reserve_parents"]))

    def test_fail_branch_replaces_top_with_label_free_diversity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory), branch="FAIL")
            result = self.run_fixture(fixture)
            self.assertEqual(result["audit"]["model_open_gate_branch"], "FAIL")
            rows = self.read_manifest(fixture)
            for parent in fixture["source_parents"]:
                counts = Counter(row["selection_bucket"] for row in rows if row["parent_framework_cluster"] == parent)
                self.assertEqual(dict(counts), dict(MOD.FAIL_QUOTAS))
            self.assertNotIn("TOP_PREDICTION", {row["selection_bucket"] for row in rows})
            self.assertTrue(
                all(
                    row["selection_metric_name"].startswith("minimum_mean_normalized")
                    for row in rows
                    if row["selection_bucket"] == "LABEL_FREE_DIVERSITY_REPLACING_TOP"
                )
            )

    def test_selection_manifest_is_order_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = self.make_fixture(Path(first_dir), branch="PASS", reverse_scores=False)
            second = self.make_fixture(Path(second_dir), branch="PASS", reverse_scores=True)
            self.run_fixture(first)
            self.run_fixture(second)
            self.assertEqual(
                (first["output"] / MOD.OUTPUT_FILENAMES[0]).read_bytes(),
                (second["output"] / MOD.OUTPUT_FILENAMES[0]).read_bytes(),
            )

    def test_exact_replay_and_output_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory))
            self.run_fixture(fixture)
            replay = self.run_fixture(fixture, verify_only=True)
            self.assertEqual(replay["replay"]["status"], "PASS_EXACT_BYTE_REPLAY_AND_HASH_CLOSURE")
            manifest = fixture["output"] / MOD.OUTPUT_FILENAMES[0]
            manifest.write_text(manifest.read_text() + "tamper\n")
            with self.assertRaisesRegex(MOD.Seen200SelectionError, "published_output_replay_mismatch"):
                self.run_fixture(fixture, verify_only=True)

    def test_receipt_is_published_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory))
            destinations: list[str] = []
            original = os.replace

            def record_replace(source, destination):
                destinations.append(Path(destination).name)
                return original(source, destination)

            with mock.patch.object(MOD.os, "replace", side_effect=record_replace):
                self.run_fixture(fixture)
            self.assertEqual(destinations[-1], MOD.OUTPUT_FILENAMES[-1])

    def test_forbidden_label_column_and_label_access_flag_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory))
            score_path = fixture["paths"]["deployment_scores"]
            with score_path.open() as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            for row in rows:
                row["R_dual_min"] = "0.9"
            write_table(score_path, rows, "\t")
            receipt = json.loads(fixture["paths"]["deployment_receipt"].read_text())
            for path in list(receipt["outputs"]):
                if Path(path).name == score_path.name:
                    receipt["outputs"][path] = MOD.sha256_file(score_path)
            write_json(fixture["paths"]["deployment_receipt"], receipt)
            with self.assertRaisesRegex(MOD.Seen200SelectionError, "deployment_score_field_set_mismatch"):
                self.run_fixture(fixture)

        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory))
            summary = json.loads(fixture["paths"]["deployment_summary"].read_text())
            summary["prospective_test_labels_read"] = True
            write_json(fixture["paths"]["deployment_summary"], summary)
            receipt = json.loads(fixture["paths"]["deployment_receipt"].read_text())
            for path in list(receipt["outputs"]):
                if Path(path).name == fixture["paths"]["deployment_summary"].name:
                    receipt["outputs"][path] = MOD.sha256_file(fixture["paths"]["deployment_summary"])
            write_json(fixture["paths"]["deployment_receipt"], receipt)
            with self.assertRaisesRegex(MOD.Seen200SelectionError, "prospective_test_labels_read_not_false"):
                self.run_fixture(fixture)

    def test_parent_shortage_fails_closed_without_partial_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory))
            calibration_path = fixture["paths"]["calibration_exclusions"]
            parent_rows = [
                row
                for row in fixture["pool"]
                if row["parent_framework_cluster"] == fixture["source_parents"][0]
            ][1:9]
            exclusions = [
                {
                    "sequence_sha256": row["sequence_sha256"],
                    "sequence": row["vhh_sequence"],
                    "calibration_aliases": f"CAL_{index}",
                    "exclusion_role": "KNOWN_PVRIG_CALIBRATION_SEQUENCE_EXCLUDED_FROM_CANDIDATE_ACQUISITION",
                    "claim_boundary": "identity-only exclusion",
                }
                for index, row in enumerate(parent_rows)
            ]
            write_table(calibration_path, exclusions, "\t")
            freeze = json.loads(fixture["paths"]["implementation_freeze"].read_text())
            freeze["artifacts"]["calibration_exclusions"]["sha256"] = MOD.sha256_file(calibration_path)
            freeze.pop("freeze_payload_sha256", None)
            freeze["freeze_payload_sha256"] = MOD.sha256_json(freeze)
            write_json(fixture["paths"]["implementation_freeze"], freeze)
            with self.assertRaisesRegex(MOD.Seen200SelectionError, "insufficient_parent_candidates"):
                self.run_fixture(fixture)
            self.assertFalse(fixture["output"].exists())

    def test_input_receipt_and_implementation_freeze_tamper_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory))
            receipt = json.loads(fixture["paths"]["deployment_receipt"].read_text())
            key = next(path for path in receipt["outputs"] if Path(path).name.endswith("scores.tsv"))
            receipt["outputs"][key] = "0" * 64
            write_json(fixture["paths"]["deployment_receipt"], receipt)
            with self.assertRaisesRegex(MOD.Seen200SelectionError, "deployment_score_hash_mismatch"):
                self.run_fixture(fixture)

        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory))
            freeze = json.loads(fixture["paths"]["implementation_freeze"].read_text())
            freeze["artifacts"]["selector"]["sha256"] = "f" * 64
            freeze.pop("freeze_payload_sha256", None)
            freeze["freeze_payload_sha256"] = MOD.sha256_json(freeze)
            write_json(fixture["paths"]["implementation_freeze"], freeze)
            with self.assertRaisesRegex(MOD.Seen200SelectionError, "implementation_freeze_artifact_hash_mismatch"):
                self.run_fixture(fixture)

    def test_duplicate_pool_sequence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(Path(directory))
            pool_path = fixture["paths"]["candidate_pool"]
            with pool_path.open() as handle:
                rows = list(csv.DictReader(handle))
            rows[1]["vhh_sequence"] = rows[0]["vhh_sequence"]
            rows[1]["sequence_sha256"] = rows[0]["sequence_sha256"]
            write_table(pool_path, rows, ",")
            with self.assertRaisesRegex(MOD.Seen200SelectionError, "duplicate_candidate_sequence"):
                self.run_fixture(fixture)

    def test_real_static_identity_inputs_match_frozen_contract_without_scores(self) -> None:
        paths = {
            "candidate_pool": MOD.DEFAULT_POOL,
            "v4d_manifest": MOD.DEFAULT_V4D,
            "v4f_manifest": MOD.DEFAULT_V4F,
            "reserve2_manifest": MOD.DEFAULT_RESERVE,
            "calibration_exclusions": MOD.DEFAULT_CALIBRATION_EXCLUSIONS,
            "parent_preregistration": MOD.DEFAULT_PARENT_PREREGISTRATION,
        }
        for name, path in paths.items():
            self.assertTrue(path.is_file(), name)
            self.assertEqual(MOD.sha256_file(path), MOD.EXPECTED_PRODUCTION_HASHES[name])
        pool_snapshot = MOD.snapshot_file(paths["candidate_pool"])
        pool_raw, pool_fields = MOD.read_table(pool_snapshot, ",")
        pool = MOD.validate_pool(pool_raw, pool_fields, expected_rows=MOD.EXPECTED_POOL_ROWS)
        v4d_raw, v4d_fields = MOD.read_table(MOD.snapshot_file(paths["v4d_manifest"]), "\t")
        v4d = MOD.validate_identity_reference(
            v4d_raw,
            v4d_fields,
            label="v4d_manifest",
            expected_rows=MOD.EXPECTED_V4D_ROWS,
        )
        v4f_raw, v4f_fields = MOD.read_table(MOD.snapshot_file(paths["v4f_manifest"]), "\t")
        MOD.validate_identity_reference(
            v4f_raw,
            v4f_fields,
            label="v4f_manifest",
            expected_rows=MOD.EXPECTED_V4F_ROWS,
        )
        reserve_raw, reserve_fields = MOD.read_table(
            MOD.snapshot_file(paths["reserve2_manifest"]), "\t"
        )
        reserve = MOD.validate_reserve(reserve_raw, reserve_fields)
        exclusion_raw, exclusion_fields = MOD.read_table(
            MOD.snapshot_file(paths["calibration_exclusions"]), "\t"
        )
        exclusions = MOD.validate_calibration_exclusions(exclusion_raw, exclusion_fields)
        prereg = MOD.read_json(MOD.snapshot_file(paths["parent_preregistration"]))
        parents = MOD.validate_parent_preregistration(
            prereg, expected_source_parents=MOD.EXPECTED_SOURCE_PARENTS
        )
        self.assertEqual(
            {row["parent_framework_cluster"] for row in v4d if row["model_split"] == "OPEN_TRAIN"},
            set(parents),
        )
        forbidden_ids = {row["candidate_id"] for row in v4d}
        eligible_counts = Counter(
            row["parent_framework_cluster"]
            for row in pool
            if row["parent_framework_cluster"] in set(parents)
            and row["parent_framework_cluster"] not in reserve
            and row["candidate_id"] not in forbidden_ids
            and row["sequence_sha256"] not in exclusions
        )
        self.assertEqual(set(eligible_counts), set(parents))
        self.assertGreaterEqual(min(eligible_counts.values()), MOD.ROWS_PER_PARENT)


if __name__ == "__main__":
    unittest.main()
