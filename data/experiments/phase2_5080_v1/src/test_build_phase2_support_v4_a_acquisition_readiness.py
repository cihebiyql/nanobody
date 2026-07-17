#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


MODULE_PATH = Path(__file__).with_name(
    "build_phase2_support_v4_a_acquisition_readiness.py"
)
SPEC = importlib.util.spec_from_file_location("support_v4_a_readiness", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def aa_token(index: int, length: int = 11) -> str:
    value = index + 1
    output: list[str] = []
    for _ in range(length):
        output.append(ALPHABET[value % len(ALPHABET)])
        value = value // len(ALPHABET) + 1
    return "".join(output)


def candidate_row(
    parent: str,
    patch: str,
    mode: str,
    index: int,
    *,
    identity: float = 42.0,
    cdr3: str | None = None,
) -> dict[str, str]:
    cdr3 = cdr3 or aa_token(index)
    sequence = "QVQLVESGGGLVQPGGSLRLSCAAS" + cdr3 + "WGQGTQVTVSS"
    return {
        "candidate_id": f"{parent}__{patch}__{mode}__{index:04d}",
        "vhh_sequence": sequence,
        "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
        "parent_id": f"P_{parent}",
        "parent_framework_cluster": parent,
        "target_patch_id": patch,
        "design_mode": mode,
        "cdr3_after": cdr3,
        "cdr3_length": str(len(cdr3)),
        "max_positive_cdr_identity": str(identity),
        # These forbidden columns deliberately exist in the source fixture.  The
        # implementation must neither read nor use them.
        "generic_binding_prior": str(index / 1000),
        "R_dual_min": str(1.0 - index / 1000),
        "experimental_blocking": "SEALED",
    }


def one_parent_fixture(
    *, single_mode: bool = False
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    counter = 0
    modes = ("H1H3",) if single_mode else MOD.MODES
    per_mode = 14 if not single_mode else 28
    for patch in MOD.PATCHES:
        for mode in modes:
            for _ in range(per_mode):
                rows.append(candidate_row("C0001", patch, mode, counter))
                counter += 1
    census = [
        {
            "candidate_id": row["candidate_id"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "fast_hard_fail": "False",
        }
        for row in rows
    ]
    return rows, census


class SupportV4AReadinessTests(unittest.TestCase):
    def eligible_one_parent(
        self, *, single_mode: bool = False
    ) -> tuple[list[dict[str, str]], dict[str, str]]:
        rows, census = one_parent_fixture(single_mode=single_mode)
        roles = {"C0001": MOD.ROLE_OPEN_TRAIN}
        eligible, exclusions = MOD.collect_eligible_candidates(
            rows,
            census,
            roles,
            calibration_sequence_sha256=set(),
            prior_panel_candidate_ids=set(),
            prior_panel_sequence_sha256=set(),
        )
        self.assertFalse(exclusions)
        return eligible, roles

    def test_balanced_selection_has_exact_parent_patch_mode_and_role_quotas(self) -> None:
        eligible, roles = self.eligible_one_parent()
        selected, parent_audit = MOD.select_readiness_pool(eligible, roles)

        self.assertEqual(len(selected), 36)
        self.assertEqual(Counter(row["parent_framework_cluster"] for row in selected), {"C0001": 36})
        self.assertEqual(Counter(row["target_patch_id"] for row in selected), {patch: 12 for patch in MOD.PATCHES})
        self.assertEqual(Counter(row["design_mode"] for row in selected), {mode: 18 for mode in MOD.MODES})
        self.assertEqual(Counter(row["acquisition_role"] for row in selected), {MOD.ROLE_ACQUISITION: 24, MOD.ROLE_AUDIT: 12})
        self.assertEqual(len({row["cdr3"] for row in selected}), 36)
        self.assertEqual(parent_audit[0]["mode_coverage_state"], "BALANCED_BOTH_MODES")

    def test_single_mode_fallback_is_explicit_and_preserves_patch_and_role_quotas(self) -> None:
        eligible, roles = self.eligible_one_parent(single_mode=True)
        selected, parent_audit = MOD.select_readiness_pool(eligible, roles)

        self.assertEqual(len(selected), 36)
        self.assertEqual(Counter(row["target_patch_id"] for row in selected), {patch: 12 for patch in MOD.PATCHES})
        self.assertEqual(Counter(row["design_mode"] for row in selected), {"H1H3": 36})
        self.assertEqual(Counter(row["acquisition_role"] for row in selected), {MOD.ROLE_ACQUISITION: 24, MOD.ROLE_AUDIT: 12})
        self.assertEqual(parent_audit[0]["mode_coverage_state"], "FORCED_SINGLE_MODE_BY_FAST_QC")

    def test_selection_is_replay_deterministic_and_forbidden_scores_are_inert(self) -> None:
        rows, census = one_parent_fixture()
        roles = {"C0001": MOD.ROLE_OPEN_TRAIN}
        first_eligible, _ = MOD.collect_eligible_candidates(
            rows,
            census,
            roles,
            calibration_sequence_sha256=set(),
            prior_panel_candidate_ids=set(),
            prior_panel_sequence_sha256=set(),
        )
        first, _ = MOD.select_readiness_pool(first_eligible, roles)

        mutated = list(reversed([dict(row) for row in rows]))
        for index, row in enumerate(mutated):
            row["generic_binding_prior"] = str(9999 - index)
            row["R_dual_min"] = str(index * 1000)
            row["experimental_blocking"] = "MUTATED_SEALED_VALUE"
        second_eligible, _ = MOD.collect_eligible_candidates(
            mutated,
            list(reversed(census)),
            roles,
            calibration_sequence_sha256=set(),
            prior_panel_candidate_ids=set(),
            prior_panel_sequence_sha256=set(),
        )
        second, _ = MOD.select_readiness_pool(second_eligible, roles)
        self.assertEqual(first, second)

    def test_fast_qc_identity_calibration_prior_panel_and_role_exclusions(self) -> None:
        rows, census = one_parent_fixture()
        roles = {"C0001": MOD.ROLE_OPEN_TRAIN, "C9000": MOD.ROLE_V4_F}
        bad_fast = rows[0]
        bad_identity = rows[1]
        calibration = rows[2]
        prior_id = rows[3]
        prior_sha = rows[4]
        rows.append(candidate_row("C9000", "A_CENTER", "H3", 9999))
        census.append(
            {
                "candidate_id": rows[-1]["candidate_id"],
                "sequence_sha256": rows[-1]["sequence_sha256"],
                "parent_framework_cluster": "C9000",
                "fast_hard_fail": "False",
            }
        )
        next(item for item in census if item["candidate_id"] == bad_fast["candidate_id"])["fast_hard_fail"] = "True"
        bad_identity["max_positive_cdr_identity"] = "75.0"

        eligible, exclusions = MOD.collect_eligible_candidates(
            rows,
            census,
            roles,
            calibration_sequence_sha256={calibration["sequence_sha256"]},
            prior_panel_candidate_ids={prior_id["candidate_id"]},
            prior_panel_sequence_sha256={prior_sha["sequence_sha256"]},
        )
        eligible_ids = {row["candidate_id"] for row in eligible}
        for row in [bad_fast, bad_identity, calibration, prior_id, prior_sha, rows[-1]]:
            self.assertNotIn(row["candidate_id"], eligible_ids)
        self.assertEqual(
            exclusions,
            Counter(
                {
                    "FAST_QC_HARD_FAIL": 1,
                    "POSITIVE_CDR_IDENTITY_GE_75": 1,
                    "KNOWN_CALIBRATION_EXACT_SEQUENCE": 1,
                    "PRIOR_PANEL_CANDIDATE_IDENTITY": 1,
                    "PRIOR_PANEL_SEQUENCE_IDENTITY": 1,
                    "FORBIDDEN_PARENT_ROLE_V4_F": 1,
                }
            ),
        )

    def test_capacity_audit_requires_36_fast_pass_and_12_per_patch_after_exclusions(self) -> None:
        eligible, roles = self.eligible_one_parent()
        parent_summary = [
            {
                "parent_framework_cluster": "C0001",
                "fast_hard_pass_count": "84",
                "support_v4_capacity_state": "READY_FOR_24_TEACHER_PLUS_12_AUDIT_ACQUISITION",
            }
        ]
        audit = MOD.build_capacity_audit(eligible, parent_summary, roles)
        self.assertEqual(audit[0]["readiness_state"], "READY_FOR_FUTURE_24_PLUS_12_ACQUISITION")
        self.assertEqual(audit[0]["global_unique_cdr3_quota_feasible"], "True")

        short_cross = [
            row for row in eligible if row["target_patch_id"] == "C_CROSS"
        ][:11]
        short = [
            row for row in eligible if row["target_patch_id"] != "C_CROSS"
        ] + short_cross
        with self.assertRaisesRegex(RuntimeError, "patch capacity"):
            MOD.build_capacity_audit(short, parent_summary, roles)

        parent_summary[0]["fast_hard_pass_count"] = "35"
        with self.assertRaisesRegex(RuntimeError, ">= 36"):
            MOD.build_capacity_audit(eligible, parent_summary, roles)

    def test_parent_role_partition_rejects_overlap_or_missing_roles(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            MOD.validate_parent_role_partition(
                {
                    MOD.ROLE_OPEN_TRAIN: {"C0001"},
                    MOD.ROLE_OPEN_DEVELOPMENT: {"C0001"},
                    MOD.ROLE_FORMAL_TEST: set(),
                    MOD.ROLE_V4_F: set(),
                    MOD.ROLE_V4_G: set(),
                    MOD.ROLE_RESERVE2: set(),
                },
                expected_parent_count=1,
                expected_open_train_count=1,
            )
        with self.assertRaisesRegex(RuntimeError, "parent count"):
            MOD.validate_parent_role_partition(
                {
                    MOD.ROLE_OPEN_TRAIN: {"C0001"},
                    MOD.ROLE_OPEN_DEVELOPMENT: set(),
                    MOD.ROLE_FORMAL_TEST: set(),
                    MOD.ROLE_V4_F: set(),
                    MOD.ROLE_V4_G: set(),
                    MOD.ROLE_RESERVE2: set(),
                },
                expected_parent_count=2,
                expected_open_train_count=1,
            )

    def test_infeasible_unique_cdr3_contract_fails_closed(self) -> None:
        eligible, roles = self.eligible_one_parent()
        for index, row in enumerate(eligible):
            if row["target_patch_id"] == "A_CENTER":
                row["cdr3"] = "AAAAAAAAAAA" if index % 2 else "CCCCCCCCCCC"
        with self.assertRaisesRegex(RuntimeError, "mode capacity|unique CDR3"):
            MOD.select_readiness_pool(eligible, roles)

    def test_cli_never_materializes_without_explicit_authorization(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--materialize-production-selection", completed.stderr)

    def test_audit_claim_boundary_is_capacity_not_domain_pass(self) -> None:
        self.assertEqual(MOD.SUPPORT_V3_FROZEN_STATUS, "FAIL_RESEARCH_RANKING_AND_DIRECT_DOCKING_ROUTING_ONLY")
        self.assertNotIn("DOMAIN_PASS", MOD.READINESS_STATUS)
        self.assertIn("future", MOD.CLAIM_BOUNDARY.lower())
        self.assertIn("not support-domain pass", MOD.CLAIM_BOUNDARY.lower())
        self.assertIn("binding probability", MOD.CLAIM_BOUNDARY.lower())

    def test_frozen_prereg_and_capacity_audit_are_label_free_and_not_materialized(self) -> None:
        prereg = json.loads(MOD.DEFAULT_PREREGISTRATION.read_text(encoding="utf-8"))
        capacity_path = MOD.DATA_ROOT / prereg["observed_label_free_capacity"]["capacity_audit_path"]
        capacity = json.loads(capacity_path.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(capacity_path.read_bytes()).hexdigest(),
            prereg["observed_label_free_capacity"]["capacity_audit_sha256"],
        )
        self.assertEqual(
            prereg["version_boundary"]["support_v3_status_must_remain"],
            MOD.SUPPORT_V3_FROZEN_STATUS,
        )
        self.assertEqual(
            len(prereg["frozen_parent_roles"][MOD.ROLE_OPEN_TRAIN]), 20
        )
        self.assertTrue(
            prereg["observed_label_free_capacity"][
                "all_open_train_parents_fast_hard_pass_ge_36"
            ]
        )
        self.assertFalse(capacity["production_selection_materialized"])
        self.assertFalse(prereg["decision_policy"]["production_domain_pass_allowed"])
        self.assertEqual(set(prereg["label_access_gate"].values()), {0})
        self.assertNotIn(
            "generic_binding_prior",
            prereg["allowed_information_contract"]["candidate_source_fields"],
        )


if __name__ == "__main__":
    unittest.main()
