#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_phase2_v2_4_manifests import (
    build_pose_proxy_summary,
    build_ranking_groups,
    build_validation_controls,
    sequence_hash,
    validate_control_isolation,
)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class BuildPhase2V24ManifestsTests(unittest.TestCase):
    def test_ranking_groups_keep_one_positive_and_typed_proxy_negatives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "triplets.csv"
            output = root / "groups.csv"
            write_csv(
                source,
                [
                    {
                        "ranking_group_id": "g1", "split": "train", "positive_pair_id": "p1",
                        "negative_pair_id": "n1", "negative_type": "N1_easy_cross_antigen",
                        "positive_vhh_seq": "AAAA", "positive_antigen_seq": "CCCC",
                        "negative_vhh_seq": "AAAA", "negative_antigen_seq": "DDDD",
                        "preference_label": 1, "label_source": "constructed_contrastive_preference",
                    },
                    {
                        "ranking_group_id": "g1", "split": "train", "positive_pair_id": "p1",
                        "negative_pair_id": "n2", "negative_type": "N3_framework_similar_hard_vhh",
                        "positive_vhh_seq": "AAAA", "positive_antigen_seq": "CCCC",
                        "negative_vhh_seq": "AAAT", "negative_antigen_seq": "CCCC",
                        "preference_label": 1, "label_source": "constructed_contrastive_preference",
                    },
                ],
            )

            summary = build_ranking_groups(source, output)
            groups = pd.read_csv(output)

            self.assertEqual(summary["ranking_groups"], 1)
            self.assertEqual(len(groups), 3)
            self.assertEqual((groups["candidate_role"] == "observed_cognate_positive").sum(), 1)
            negatives = groups[groups["candidate_role"] == "constructed_contrastive_candidate"]
            self.assertEqual(set(negatives["ordinary_bce_eligible"]), {"no"})
            self.assertEqual(set(negatives["proxy_label_policy"]), {"constructed_preference_not_verified_nonbinder"})
            self.assertGreater(
                float(negatives.loc[negatives["negative_type"].str.startswith("N3"), "ranking_weight"].iloc[0]),
                float(negatives.loc[negatives["negative_type"].str.startswith("N1"), "ranking_weight"].iloc[0]),
            )

    def test_controls_are_hash_keyed_and_never_ordinary_training_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            positive = root / "positive.csv"
            mutant = root / "mutant.csv"
            output = root / "controls.csv"
            write_csv(
                positive,
                [{
                    "calibration_id": "pos1", "molecule_name": "P1", "family": "F1",
                    "sequence": "ACDE", "label_role": "known_positive_pvrig_blocking_vhh",
                    "blocking_ic50_nm": 1.2, "kd_m": 1e-9, "pose_count": 10,
                }],
            )
            write_csv(
                mutant,
                [{
                    "control_id": "mut1", "base_molecule": "P1", "family": "F1",
                    "sequence": "ACDF", "label_role": "mutant_or_leakage_control_not_new_design",
                    "control_type": "mutant", "leakage_label": "NEAR_KNOWN_POSITIVE",
                    "consensus_rows": 10,
                }],
            )

            summary = build_validation_controls(positive, mutant, output)
            controls = pd.read_csv(output)

            self.assertEqual(summary["control_rows"], 2)
            self.assertEqual(set(controls["ordinary_train_allowed"]), {False})
            self.assertEqual(set(controls["ordinary_test_allowed"]), {False})
            self.assertEqual(set(controls["candidate_ranking_allowed"]), {False})
            self.assertEqual(controls.loc[controls["sample_id"] == "pos1", "sequence_sha256"].iloc[0], sequence_hash("ACDE"))

    def test_pose_proxy_summary_never_claims_experimental_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            positive = root / "positive_pose.csv"
            mutant = root / "mutant_pose.csv"
            output = root / "pose_summary.csv"
            write_csv(
                positive,
                [
                    {"calibration_name": "p1", "consensus_class": "CONSENSUS_BLOCKER_LIKE_A"},
                    {"calibration_name": "p1", "consensus_class": "BLOCKER_PLAUSIBLE_B"},
                ],
            )
            write_csv(
                mutant,
                [{"mutant_name": "m1", "consensus_class": "EVIDENCE_INFERENCE_ONLY_E"}],
            )

            summary = build_pose_proxy_summary(positive, mutant, output)
            poses = pd.read_csv(output)

            self.assertEqual(summary["source_pose_rows"], 3)
            self.assertEqual(set(poses["proxy_semantics"]), {"docking_proxy_not_experimental_label"})
            self.assertEqual(int(poses.loc[poses["sample_id"] == "p1", "consensus_blocker_like_a_count"].iloc[0]), 1)

    def test_control_hash_overlap_is_rejected(self) -> None:
        ranking = pd.DataFrame([{"vhh_seq": "ACDE", "candidate_role": "observed_cognate_positive"}])
        controls = pd.DataFrame([{"sequence_sha256": sequence_hash("ACDE")}])
        with self.assertRaises(ValueError):
            validate_control_isolation(ranking, controls)


if __name__ == "__main__":
    unittest.main()
