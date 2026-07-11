#!/usr/bin/env python3
"""Focused tests for the Phase 2 V2.5 P0 evidence registry."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_phase2_v2_5_evidence_registry import (  # noqa: E402
    build_evidence_registry,
    build_external_manifest,
    build_nanobind_affinity_rows,
    parse_args,
    run,
)
from phase2_v2_5_contracts import (  # noqa: E402
    CANONICAL_FIELDS,
    ContractError,
    PVRIG_TARGET_ID,
    compute_target_readiness,
    sequence_sha256,
    validate_evidence_registry,
    validate_external_manifest,
)


AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
FIXTURE_COMMIT = "a" * 40


def indexed_sequence(prefix: str, index: int, width: int = 4) -> str:
    chars: list[str] = []
    value = index
    for _ in range(width):
        chars.append(AMINO_ACIDS[value % len(AMINO_ACIDS)])
        value //= len(AMINO_ACIDS)
    return prefix + "".join(reversed(chars))


def write_nanobind_fixture(root: Path) -> None:
    checkout = root / "datasets/10_github_repos/NanoBind"
    affinity_dir = checkout / "data/affinity"
    git_ref = checkout / ".git/refs/heads"
    affinity_dir.mkdir(parents=True, exist_ok=True)
    git_ref.mkdir(parents=True, exist_ok=True)
    (checkout / ".git/HEAD").write_text("ref: refs/heads/master\n", encoding="ascii")
    (git_ref / "master").write_text(FIXTURE_COMMIT + "\n", encoding="ascii")

    rows: list[dict[str, object]] = []
    for index in range(181):
        rows.append(
            {
                "ID": f"fixture_{index:03d}",
                "nanobody_chain": "H",
                "seq_nanobody": indexed_sequence("QVQL", index),
                "antigen_chain": "A",
                "seq_antigen": indexed_sequence("MKT", index % 10),
                "affinity": float(index + 1) * 1e-9,
            }
        )
    for index in range(4):
        duplicate = dict(rows[index])
        duplicate["ID"] = f"fixture_duplicate_{index}"
        duplicate["affinity"] = float(rows[index]["affinity"]) * 3.0
        rows.append(duplicate)
    pd.DataFrame(rows).to_csv(affinity_dir / "all.csv", index=False)

    unrelated_copy = root / "code/downloaded_models/NanoBind"
    unrelated_copy.mkdir(parents=True)
    (unrelated_copy / "LICENSE").write_text("Unrelated copy only\n", encoding="ascii")


def write_fixture(root: Path) -> None:
    (root / "model_data").mkdir(parents=True)
    target = "ACDEFGHIKLMNPQRSTVWY"
    (root / "model_data/pvrig_target_ectodomain_proxy_v1.fasta").write_text(f">pvrig\n{target}\n", encoding="utf-8")
    split = root / "experiments/phase2_5080_v1/data_splits"
    prepared = root / "experiments/phase2_5080_v1/prepared"
    priors = root / "experiments/phase2_5080_v1/external_priors"
    for path in [split, prepared, priors]:
        path.mkdir(parents=True, exist_ok=True)
    write_nanobind_fixture(root)
    pd.DataFrame(
        [
            {
                "sample_id": "kp1",
                "molecule_name": "PVRIG-1",
                "sequence_sha256": "unused",
                "sequence": "QVQLVESGGG",
                "family": "1",
                "control_role": "known_positive_calibration",
                "label_hint": "known_positive_pvrig_blocking_vhh",
                "leakage_policy": "exact_known_positive_calibration_only",
                "assay_ic50_nm": 1.2,
                "kd_m": 2e-10,
                "reporter_ec50_nm": 0.04,
                "pose_count": 2,
                "ordinary_train_allowed": False,
                "ordinary_test_allowed": False,
                "candidate_ranking_allowed": False,
                "ground_truth_kind": "assay_backed_positive_calibration",
                "source_table": "fixture",
            },
            {
                "sample_id": "mut1",
                "molecule_name": "PVRIG-1-F99A",
                "sequence_sha256": "unused",
                "sequence": "QVQLVESGGA",
                "family": "1",
                "control_role": "mutant",
                "label_hint": "mutant_control",
                "leakage_policy": "near_known_positive",
                "assay_ic50_nm": "",
                "kd_m": "",
                "reporter_ec50_nm": "",
                "pose_count": 1,
                "ordinary_train_allowed": False,
                "ordinary_test_allowed": False,
                "candidate_ranking_allowed": False,
                "ground_truth_kind": "constructed_mutant_or_leakage_control",
                "source_table": "fixture",
            },
        ]
    ).to_csv(split / "pvrig_validation_controls_v2_4.csv", index=False)
    pd.DataFrame(
        [
            {
                "ranking_group_id": "g1",
                "split": "test",
                "positive_pair_id": "pos1",
                "candidate_pair_id": "n1",
                "candidate_role": "constructed_contrastive_candidate",
                "negative_type": "N1_easy_cross_antigen",
                "vhh_seq": "CARDRSTY",
                "antigen_seq": target,
                "preference_label": 0,
                "label_source": "constructed",
                "proxy_label_policy": "not_truth",
                "ranking_weight": 1.0,
                "ranking_margin": 1.0,
                "ordinary_bce_eligible": "no",
            }
        ]
    ).to_csv(split / "pair_ranking_groups_v2_4.csv", index=False)
    pd.DataFrame(
        [
            {
                "sample_id": "kp1",
                "source_lane": "known_positive_pose_calibration",
                "pose_rows": 2,
                "consensus_blocker_like_a_count": 0,
                "single_baseline_recheck_count": 1,
                "blocker_plausible_b_count": 1,
                "evidence_inference_only_e_count": 0,
                "other_class_count": 0,
                "any_blocker_like_a": False,
                "manual_review_required": True,
                "proxy_semantics": "docking_proxy_not_experimental_label",
            }
        ]
    ).to_csv(prepared / "pvrig_pose_proxy_summary_v2_4.csv", index=False)
    pd.DataFrame(
        [
            {
                "candidate_id": "cand1",
                "pose_id": "p1",
                "target_baseline": "PVRIG",
                "pose_path": "pose.pdb",
                "vhh_chain": "A",
                "target_chain": "B",
                "pose_status": "completed",
                "qc_status": "geometry_qc_pass",
                "geometry_status": "ok",
                "geometry_notes": "fixture",
                "heavy_atom_interface_contacts_le_4p5A": 3,
                "heavy_atom_clashes_lt_2p0A": 0,
                "minimum_heavy_atom_distance_A": 3.1,
                "vhh_interface_residues_json": "[]",
                "target_interface_residues_json": "[]",
                "target_interface_full_positions_json": "[]",
                "hotspot_contact_count": 1,
                "hotspot_weighted_contacts": 1,
                "hotspot_positions_json": "[]",
                "cdr3_seq": "CARGGYY",
                "cdr3_contacts": 1,
                "cdr3_interface_residues_json": "[]",
                "calibration_role": "candidate_screening_optional_pose",
                "leakage_role": "candidate_no_known_positive_leakage",
            }
        ]
    ).to_csv(prepared / "p3_pose_geometry_features_v1.csv", index=False)
    pd.DataFrame([{"candidate_id": "cand1", "status": "ok"}]).to_csv(priors / "selftest_nanobind_seq_one_candidate_v1.csv", index=False)
    contact_record = {
        "complex_id": "fixture_pdb|H|A",
        "pdb": "fixture_pdb",
        "structure_member": "fixture_pdb/model.cif",
        "split": "train",
        "vhh_chain": "H",
        "antigen_chain": "A",
        "vhh_seq": "QVQLCONTACT",
        "antigen_seq": target,
        "positive_pairs": [[1, 2], [3, 4]],
        "negative_pairs": [[0, 0]],
        "split_group_id": "connected_group_fixture",
        "vhh_cluster_id": "vhh_cluster_fixture",
        "cdr3_proxy_cluster_id": "cdr3_cluster_fixture",
        "antigen_cluster_id": "antigen_cluster_fixture",
    }
    contact_path = prepared / "structure_contact_maps_v3_clustered.jsonl"
    contact_path.write_text(
        json.dumps(contact_record) + "\n" + json.dumps(contact_record) + "\n",
        encoding="ascii",
    )


class Phase2V25EvidenceRegistryTests(unittest.TestCase):
    def test_build_registry_uses_canonical_schema_and_separates_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture(root)
            registry = build_evidence_registry(root)
            self.assertEqual(list(registry.columns), CANONICAL_FIELDS)
            self.assertEqual(validate_evidence_registry(registry).status, "PASS")
            self.assertEqual(set(registry["evidence_level"]), {"E0", "E1", "E2", "E3", "E4", "E5"})
            known = registry[registry["sample_id"] == "kp1"].iloc[0]
            self.assertEqual(known["allowed_use"], "CALIBRATION_LEAKAGE_CONTROL_ONLY")
            self.assertEqual(known["ordinary_train_allowed"], "false")
            contact = registry[registry["evidence_level"] == "E1"].iloc[0]
            self.assertEqual(contact["allowed_use"], "CONTACT_SITE_GUARDRAIL_ONLY")
            self.assertEqual(contact["ordinary_train_allowed"], "true")
            self.assertEqual(contact["candidate_ranking_allowed"], "false")
            self.assertIn("jsonl_lines=1,2", contact["source_path_or_locator"])
            constructed = registry[registry["evidence_level"] == "E2"].iloc[0]
            self.assertEqual(constructed["ordinary_bce_eligible"], "false")
            self.assertIn("not an experimental non-binder", constructed["notes"])
            pose = registry[registry["evidence_level"] == "E3"].iloc[0]
            self.assertEqual(pose["ground_truth_kind"], "pose_proxy")

    def test_schema_validator_hard_fails_aliases_and_proxy_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture(root)
            registry = build_evidence_registry(root)
            bad_alias = registry.copy()
            bad_alias["unit"] = bad_alias["label_unit"]
            with self.assertRaisesRegex(ContractError, "Non-canonical"):
                validate_evidence_registry(bad_alias)
            bad_proxy = registry.copy()
            idx = bad_proxy[bad_proxy["evidence_level"] == "E2"].index[0]
            bad_proxy.loc[idx, "ordinary_bce_eligible"] = "true"
            with self.assertRaisesRegex(ContractError, "E2 rows cannot be ordinary_bce_eligible"):
                validate_evidence_registry(bad_proxy)
            bad_known = registry.copy()
            idx = bad_known[bad_known["sample_id"] == "kp1"].index[0]
            bad_known.loc[idx, "ordinary_train_allowed"] = "true"
            with self.assertRaisesRegex(ContractError, "Known positive/control"):
                validate_evidence_registry(bad_known)

            bad_generic = registry.copy()
            idx = bad_generic[bad_generic["evidence_level"] == "E4"].index[0]
            bad_generic.loc[idx, "forbidden_use"] = "REDISTRIBUTION"
            with self.assertRaisesRegex(ContractError, "Generic E4"):
                validate_evidence_registry(bad_generic)

    def test_nanobind_affinity_aggregates_185_rows_to_181_generic_e4_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture(root)
            rows, details = build_nanobind_affinity_rows(root)
            registry = pd.DataFrame(rows)
            self.assertEqual(details["source_row_count"], 185)
            self.assertEqual(details["canonical_pair_count"], 181)
            self.assertEqual(details["duplicate_exact_pair_groups"], 4)
            self.assertEqual(details["duplicate_rows_merged"], 4)
            self.assertEqual(details["excluded_or_merged_count"], 4)
            self.assertEqual(len(registry), 181)
            first = registry.iloc[0]
            self.assertAlmostEqual(first["label_value"], 2e-9)
            self.assertEqual(first["label_unit"], "M")
            self.assertEqual(first["assay_type"], "Kd")
            self.assertEqual(first["allowed_use"], "EXPERIMENTAL_RANKING_ONLY")
            self.assertEqual(first["ordinary_train_allowed"], "true")
            self.assertEqual(first["ordinary_test_allowed"], "true")
            self.assertEqual(first["ordinary_bce_eligible"], "false")
            self.assertIn("BLOCKER_TRUTH", first["forbidden_use"])
            self.assertIn("replicate_count_not_reported", first["missing_reason"])
            self.assertIn("csv_lines=2,183", first["source_path_or_locator"])
            target_sequence = indexed_sequence("MKT", 0)
            self.assertEqual(first["target_id"], f"NANOBIND_TARGET_SHA256_{sequence_sha256(target_sequence)}")
            self.assertEqual(first["target_sequence_sha256"], sequence_sha256(target_sequence))

    def test_external_manifest_allows_nanobind_local_use_but_blocks_redistribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture(root)
            manifest = build_external_manifest(root)
            row = manifest.iloc[0]
            self.assertEqual(row["source_family"], "NanoBind")
            self.assertEqual(row["license_or_usage_status"], "REVIEWED_LOCAL_USE")
            self.assertEqual(row["redistribution_allowed"], "false")
            self.assertEqual(row["enters_training_or_evaluation"], "true")
            self.assertEqual(row["excluded_row_count"], "4")
            self.assertIn("REDISTRIBUTION", row["forbidden_use"])
            self.assertIn(FIXTURE_COMMIT, row["source_version"])
            self.assertIn("license_files_in_actual_checkout=none", row["notes"])
            validate_external_manifest(manifest)
            bad = manifest.copy()
            bad.loc[0, "redistribution_allowed"] = "true"
            with self.assertRaisesRegex(ContractError, "NanoBind"):
                validate_external_manifest(bad)
            unreviewed = manifest.copy()
            unreviewed.loc[0, "license_or_usage_status"] = "UNREVIEWED"
            with self.assertRaisesRegex(ContractError, "without allowed usage"):
                validate_external_manifest(unreviewed)

    def test_cli_dry_run_reports_data_not_ready_without_writing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_fixture(root)
            args = parse_args(["--root", str(root), "--dry-run"])
            summary = run(args)
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["data_readiness_status"], "DATA_NOT_READY")
            self.assertEqual(summary["target_readiness_target_id"], PVRIG_TARGET_ID)
            self.assertEqual(summary["generic_e4_binding_rows"], 181)
            self.assertEqual(summary["nanobind_affinity"]["source_row_count"], 185)
            self.assertEqual(summary["nanobind_affinity"]["canonical_pair_count"], 181)
            self.assertEqual(summary["contact_site_source"]["status"], "INCLUDED")
            self.assertEqual(summary["contact_site_source"]["included_complex_count"], 1)
            self.assertEqual(summary["contact_site_source"]["duplicate_source_rows_merged"], 1)
            self.assertEqual(summary["ordinary_negative_count"], 0)
            self.assertEqual(summary["constructed_proxy_rows"], 1)
            registry = build_evidence_registry(root)
            self.assertEqual(compute_target_readiness(registry), "DATA_NOT_READY")
            hypothetical = registry.copy()
            generic_e4 = hypothetical["evidence_level"].eq("E4")
            hypothetical.loc[generic_e4, "target_id"] = PVRIG_TARGET_ID
            self.assertEqual(compute_target_readiness(hypothetical), "TARGET_PILOT_READY")
            self.assertFalse((root / "experiments/phase2_5080_v1/data_splits/evidence_registry_v2_5.csv").exists())
            json.dumps(summary)


if __name__ == "__main__":
    unittest.main()
