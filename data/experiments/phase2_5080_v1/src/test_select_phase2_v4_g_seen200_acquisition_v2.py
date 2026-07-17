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


MODULE_PATH = Path(__file__).with_name("select_phase2_v4_g_seen200_acquisition_v2.py")
SPEC = importlib.util.spec_from_file_location("select_phase2_v4_g_seen200_acquisition_v2", MODULE_PATH)
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


class Seen200SelectorV2Test(unittest.TestCase):
    def make_fixture(
        self,
        root: Path,
        *,
        branch: str = "PASS",
        reverse_scores: bool = False,
        source_parents: list[str] | None = None,
        census_hard_fail_replicates: set[int] | None = None,
    ):
        source_parents = source_parents or ["C0001", "C0002"]
        census_hard_fail_replicates = census_hard_fail_replicates or set()
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

        calibration_source = by_id[f"{source_parents[0]}_candidate_01"]
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
                "rows": len(source_parents) * 10,
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

        selector_v2_prereg = {
            "schema_version": "phase2_v4_g_seen200_selector_v2_preregistration_v1",
            "status": "FROZEN_V2_SUPERSEDING_V1_PREPRODUCTION_BLOCKERS_NO_SELECTION",
            "production_selection_executed": False,
            "production_outputs_created": 0,
            "label_access": {
                "v4d_open_model_results_opened": 0,
                "v4d_prospective_test_labels_opened": 0,
                "v4f_labels_opened": 0,
                "docking_labels_opened": 0,
                "experimental_labels_opened": 0,
            },
            "frozen_selection_intent": {
                "source_parent_clusters": source_parents,
                "rows_per_parent": 10,
                "rows_total": len(source_parents) * 10,
            },
        }
        selector_v2_prereg["preregistration_payload_sha256"] = MOD.sha256_json(
            selector_v2_prereg
        )
        selector_v2_prereg_path = root / "selector_v2_preregistration.json"
        write_json(selector_v2_prereg_path, selector_v2_prereg)

        census_rows: list[dict[str, str]] = []
        hard_fail_count = 0
        for candidate in pool:
            replicate = int(candidate["candidate_id"].rsplit("_", 1)[1])
            is_hard_fail = (
                candidate["parent_framework_cluster"] in set(source_parents)
                and replicate in census_hard_fail_replicates
            )
            hard_fail_count += int(is_hard_fail)
            census_rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "sequence_sha256": candidate["sequence_sha256"],
                    "parent_framework_cluster": candidate["parent_framework_cluster"],
                    "fast_hard_fail": str(is_hard_fail),
                    "reason_summary": "synthetic_hard_fail" if is_hard_fail else "developability_warn",
                    "official_validator_failed_reason": "",
                    "census_role": "GLOBAL_POOL_OTHER",
                }
            )
        census_path = root / "candidate7087_node1_fastqc_census_v1.tsv"
        write_table(census_path, census_rows, "\t")
        census_audit = {
            "schema_version": MOD.CENSUS_AUDIT_SCHEMA_VERSION,
            "status": "PASS_7087_FAST_QC_CENSUS_AUDIT",
            "candidate_count": len(pool),
            "fast_hard_pass_count": len(pool) - hard_fail_count,
            "fast_hard_fail_count": hard_fail_count,
            "parent_count": len({row["parent_framework_cluster"] for row in pool}),
            "preregistration_sha256": "a" * 64,
            "runtime_manifest_sha256": "b" * 64,
            "label_path_access": {
                "docking": 0,
                "experimental": 0,
                "model_score": 0,
                "v4_d_geometry": 0,
                "v4_f_labels": 0,
            },
            "outputs": {
                census_path.name: MOD.sha256_file(census_path),
            },
        }
        census_audit_path = root / "candidate7087_node1_fastqc_census_v1.audit.json"
        write_json(census_audit_path, census_audit)
        census_receipt = {
            "schema_version": MOD.CENSUS_RECEIPT_SCHEMA_VERSION,
            "status": "PASS_7087_FAST_QC_CENSUS_READY_FOR_SUPPORT_V4_A_PLANNING",
            "candidate_count": len(pool),
            "fast_hard_pass_count": len(pool) - hard_fail_count,
            "fast_hard_fail_count": hard_fail_count,
            "parent_count": len({row["parent_framework_cluster"] for row in pool}),
            "preregistration_sha256": "a" * 64,
            "runtime_manifest_sha256": "b" * 64,
            "receipt_publication_order": "LAST_AFTER_ALL_CLOSURE_GATES",
            "label_path_access": dict(census_audit["label_path_access"]),
            "output_sha256": {
                census_path.name: MOD.sha256_file(census_path),
                census_audit_path.name: MOD.sha256_file(census_audit_path),
            },
        }
        census_receipt_path = root / "candidate7087_node1_fastqc_census_v1.receipt.json"
        write_json(census_receipt_path, census_receipt)
        census_verification = {
            "schema_version": MOD.CENSUS_VERIFICATION_SCHEMA_VERSION,
            "status": "PASS_INDEPENDENT_LARGE_SCALE_FAST_CENSUS_VERIFICATION",
            "candidate_table_sha256": MOD.sha256_file(census_path),
            "receipt_sha256": MOD.sha256_file(census_receipt_path),
            "checks": {
                "candidate_rows": True,
                "candidate_bijection": True,
                "receipt_output_hashes": True,
            },
            "results": {
                "fast_hard_pass": len(pool) - hard_fail_count,
                "fast_hard_fail": hard_fail_count,
            },
        }
        census_verification_path = root / "INDEPENDENT_VERIFICATION.json"
        write_json(census_verification_path, census_verification)

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
            "v4f_label_paths_accepted": 0,
            "experimental_labels_read": False,
            "experimental_label_paths_accepted": 0,
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
            "v4f_label_paths_accepted": 0,
            "experimental_labels_read": False,
            "experimental_label_paths_accepted": 0,
        }
        receipt_path = root / "candidate7087_deployment_receipt.json"
        write_json(receipt_path, receipt)

        freeze = {
            "schema_version": MOD.IMPLEMENTATION_FREEZE_VERSION,
            "status": "FROZEN_V2_BEFORE_V4D_OPEN_MODEL_RESULTS_NO_SEEN200_SELECTION",
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
                "selector_v2_preregistration": {"path": str(selector_v2_prereg_path.resolve()), "sha256": MOD.sha256_file(selector_v2_prereg_path)},
                "calibration_exclusions": {"path": str(calibration_path.resolve()), "sha256": MOD.sha256_file(calibration_path)},
                "node1_fastqc_census": {"path": str(census_path.resolve()), "sha256": MOD.sha256_file(census_path)},
                "node1_fastqc_census_receipt": {"path": str(census_receipt_path.resolve()), "sha256": MOD.sha256_file(census_receipt_path)},
                "node1_fastqc_census_audit": {"path": str(census_audit_path.resolve()), "sha256": MOD.sha256_file(census_audit_path)},
                "node1_fastqc_census_independent_verification": {"path": str(census_verification_path.resolve()), "sha256": MOD.sha256_file(census_verification_path)},
            },
            "selection_policy": {
                "pass_quota_order": [list(value) for value in MOD.PASS_QUOTAS],
                "fail_quota_order": [list(value) for value in MOD.FAIL_QUOTAS],
                "control_pre_reservation": "reserve_before_all_model_ranked_and_diversity_buckets",
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
            "selector_v2_preregistration": selector_v2_prereg_path,
            "node1_fastqc_census": census_path,
            "node1_fastqc_census_receipt": census_receipt_path,
            "node1_fastqc_census_audit": census_audit_path,
            "node1_fastqc_census_independent_verification": census_verification_path,
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
            "census_hard_fail_ids": {
                row["candidate_id"] for row in census_rows if row["fast_hard_fail"] == "True"
            },
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

    def refresh_deployment_receipt(self, fixture) -> None:
        receipt_path = fixture["paths"]["deployment_receipt"]
        receipt = json.loads(receipt_path.read_text())
        for key, path_name in (
            ("deployment_scores", "deployment_scores"),
            ("deployment_summary", "deployment_summary"),
        ):
            path = fixture["paths"][path_name]
            bound = next(name for name in receipt["outputs"] if Path(name).name == path.name)
            receipt["outputs"][bound] = MOD.sha256_file(path)
        write_json(receipt_path, receipt)

    def refresh_freeze_artifact(self, fixture, artifact_name: str, path_name: str) -> None:
        freeze_path = fixture["paths"]["implementation_freeze"]
        freeze = json.loads(freeze_path.read_text())
        freeze["artifacts"][artifact_name]["sha256"] = MOD.sha256_file(
            fixture["paths"][path_name]
        )
        freeze.pop("freeze_payload_sha256", None)
        freeze["freeze_payload_sha256"] = MOD.sha256_json(freeze)
        write_json(freeze_path, freeze)

    def make_hard_fails_score_dominant(self, fixture) -> None:
        score_path = fixture["paths"]["deployment_scores"]
        with score_path.open() as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        for row in rows:
            if row["candidate_id"] in fixture["census_hard_fail_ids"]:
                for field in (
                    "base_prediction",
                    "embedding_prediction",
                    "contact_prediction",
                    "consensus_prediction",
                    "base_ensemble_uncertainty",
                    "embedding_ensemble_uncertainty",
                    "contact_ensemble_uncertainty",
                    "ensemble_uncertainty",
                    "model_disagreement",
                    "exploration_priority",
                ):
                    if row[field]:
                        row[field] = "999.000000000"
        write_table(score_path, rows, "\t")
        self.refresh_deployment_receipt(fixture)

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

    def test_census_hard_fail_is_rejected_before_ranking_for_four_known_parents(self) -> None:
        source_parents = ["C0139", "C0500", "C0509", "C0533"]
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(
                Path(directory),
                source_parents=source_parents,
                census_hard_fail_replicates={15, 16},
            )
            self.make_hard_fails_score_dominant(fixture)
            self.run_fixture(fixture)
            rows = self.read_manifest(fixture)
            selected = {row["candidate_id"] for row in rows}
            self.assertFalse(selected & fixture["census_hard_fail_ids"])
            replay = self.run_fixture(fixture, verify_only=True)
            self.assertEqual(
                replay["audit"]["checks"]["node1_fastqc_hard_fail_overlap"], 0
            )

    def test_census_hard_fail_is_excluded_before_nonfinite_model_values_are_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.make_fixture(
                Path(directory), census_hard_fail_replicates={16}
            )
            score_path = fixture["paths"]["deployment_scores"]
            with score_path.open() as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            for row in rows:
                if row["candidate_id"] in fixture["census_hard_fail_ids"]:
                    row["consensus_prediction"] = "NaN"
                    row["ensemble_uncertainty"] = "NaN"
                    row["model_disagreement"] = "NaN"
            write_table(score_path, rows, "\t")
            self.refresh_deployment_receipt(fixture)
            self.run_fixture(fixture)
            selected = {row["candidate_id"] for row in self.read_manifest(fixture)}
            self.assertFalse(selected & fixture["census_hard_fail_ids"])

    def test_hash_control_is_prereserved_and_invariant_to_all_model_score_perturbation(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = self.make_fixture(Path(first_dir), branch="PASS")
            second = self.make_fixture(Path(second_dir), branch="PASS")
            score_path = second["paths"]["deployment_scores"]
            with score_path.open() as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            for index, row in enumerate(rows):
                if not row["model_scoring_permitted"].lower() == "true":
                    continue
                values = {
                    "base_prediction": 1000 - index,
                    "embedding_prediction": index % 7,
                    "contact_prediction": (index * 13) % 19,
                    "consensus_prediction": 1000 - index,
                    "base_ensemble_uncertainty": (index * 17) % 23,
                    "embedding_ensemble_uncertainty": (index * 19) % 29,
                    "contact_ensemble_uncertainty": (index * 23) % 31,
                    "ensemble_uncertainty": (index * 29) % 37,
                    "model_disagreement": (index * 31) % 41,
                    "exploration_priority": (index * 37) % 43,
                }
                for field, value in values.items():
                    row[field] = f"{float(value):.9f}"
            write_table(score_path, rows, "\t")
            self.refresh_deployment_receipt(second)
            self.run_fixture(first)
            self.run_fixture(second)
            first_rows = self.read_manifest(first)
            second_rows = self.read_manifest(second)
            controls = lambda rows: {
                (row["parent_framework_cluster"], row["candidate_id"])
                for row in rows
                if row["selection_bucket"] == "LABEL_FREE_HASH_CONTROL"
            }
            self.assertEqual(controls(first_rows), controls(second_rows))
            first_ranked = {
                row["candidate_id"]
                for row in first_rows
                if row["selection_bucket"] != "LABEL_FREE_HASH_CONTROL"
            }
            second_ranked = {
                row["candidate_id"]
                for row in second_rows
                if row["selection_bucket"] != "LABEL_FREE_HASH_CONTROL"
            }
            self.assertNotEqual(first_ranked, second_ranked)

    def test_census_tsv_receipt_audit_and_independent_verification_tamper_fail_closed(self) -> None:
        cases = (
            ("node1_fastqc_census", "node1_fastqc_census", "census"),
            ("node1_fastqc_census_receipt", "node1_fastqc_census_receipt", "receipt"),
            ("node1_fastqc_census_audit", "node1_fastqc_census_audit", "audit"),
            (
                "node1_fastqc_census_independent_verification",
                "node1_fastqc_census_independent_verification",
                "verification",
            ),
        )
        for path_name, artifact_name, label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = self.make_fixture(Path(directory))
                path = fixture["paths"][path_name]
                if label == "verification":
                    payload = json.loads(path.read_text())
                    payload["status"] = "TAMPERED"
                    write_json(path, payload)
                else:
                    path.write_bytes(path.read_bytes() + b"\n")
                self.refresh_freeze_artifact(fixture, artifact_name, path_name)
                with self.assertRaises(MOD.Seen200SelectionError):
                    self.run_fixture(fixture)
                self.assertFalse(fixture["output"].exists())

    def test_experimental_labels_read_must_be_explicit_false_in_summary_and_receipt(self) -> None:
        for path_name in ("deployment_summary", "deployment_receipt"):
            with self.subTest(path_name=path_name), tempfile.TemporaryDirectory() as directory:
                fixture = self.make_fixture(Path(directory))
                path = fixture["paths"][path_name]
                payload = json.loads(path.read_text())
                payload.pop("experimental_labels_read")
                write_json(path, payload)
                if path_name == "deployment_summary":
                    self.refresh_deployment_receipt(fixture)
                with self.assertRaisesRegex(
                    MOD.Seen200SelectionError, "experimental_labels_read_not_false"
                ):
                    self.run_fixture(fixture)
                self.assertFalse(fixture["output"].exists())

    def test_all_sealed_label_path_acceptance_counts_must_be_explicit_zero(self) -> None:
        accepted_fields = (
            "prospective_test_label_paths_accepted",
            "v4f_label_paths_accepted",
            "experimental_label_paths_accepted",
        )
        for path_name in ("deployment_summary", "deployment_receipt"):
            for field in accepted_fields:
                for mutation in ("missing", "nonzero"):
                    with (
                        self.subTest(path_name=path_name, field=field, mutation=mutation),
                        tempfile.TemporaryDirectory() as directory,
                    ):
                        fixture = self.make_fixture(Path(directory))
                        path = fixture["paths"][path_name]
                        payload = json.loads(path.read_text())
                        if mutation == "missing":
                            payload.pop(field)
                        else:
                            payload[field] = 1
                        write_json(path, payload)
                        if path_name == "deployment_summary":
                            self.refresh_deployment_receipt(fixture)
                        with self.assertRaisesRegex(
                            MOD.Seen200SelectionError, f"{field}_not_explicit_zero"
                        ):
                            self.run_fixture(fixture)
                        self.assertFalse(fixture["output"].exists())

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
            "selector_v2_preregistration": MOD.DEFAULT_SELECTOR_V2_PREREGISTRATION,
            "node1_fastqc_census": MOD.DEFAULT_CENSUS,
            "node1_fastqc_census_receipt": MOD.DEFAULT_CENSUS_RECEIPT,
            "node1_fastqc_census_audit": MOD.DEFAULT_CENSUS_AUDIT,
            "node1_fastqc_census_independent_verification": MOD.DEFAULT_CENSUS_INDEPENDENT_VERIFICATION,
        }
        for name, path in paths.items():
            self.assertTrue(path.is_file(), name)
            self.assertEqual(MOD.sha256_file(path), MOD.EXPECTED_PRODUCTION_HASHES[name])
        pool_snapshot = MOD.snapshot_file(paths["candidate_pool"])
        pool_raw, pool_fields = MOD.read_table(pool_snapshot, ",")
        pool = MOD.validate_pool(pool_raw, pool_fields, expected_rows=MOD.EXPECTED_POOL_ROWS)
        census = MOD.validate_node1_fastqc_census(
            MOD.snapshot_file(paths["node1_fastqc_census"]),
            MOD.snapshot_file(paths["node1_fastqc_census_receipt"]),
            MOD.snapshot_file(paths["node1_fastqc_census_audit"]),
            MOD.snapshot_file(paths["node1_fastqc_census_independent_verification"]),
            expected_rows=MOD.EXPECTED_POOL_ROWS,
        )
        self.assertEqual(set(census), {row["candidate_id"] for row in pool})
        self.assertEqual(sum(row["fast_hard_fail"] for row in census.values()), 2509)
        known_hard_fails = {
            "C0139": "RFV1__PLDNANO_VHH_00197__A_CENTER__H3__B00__M01",
            "C0500": "RFV1__PLDNANO_VHH_00871__A_CENTER__H3__B00__M00",
            "C0509": "RFV1__PLDNANO_VHH_00882__A_CENTER__H3__B00__M00",
            "C0533": "RFV1__PLDNANO_VHH_00921__A_CENTER__H3__B00__M00",
        }
        for parent, candidate_id in known_hard_fails.items():
            self.assertTrue(census[candidate_id]["fast_hard_fail"], parent)
            self.assertEqual(census[candidate_id]["parent_framework_cluster"], parent)
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
        MOD.validate_selector_v2_preregistration(
            MOD.read_json(MOD.snapshot_file(paths["selector_v2_preregistration"])), parents
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
            and not census[row["candidate_id"]]["fast_hard_fail"]
        )
        self.assertEqual(set(eligible_counts), set(parents))
        self.assertGreaterEqual(min(eligible_counts.values()), MOD.ROWS_PER_PARENT)


if __name__ == "__main__":
    unittest.main()
