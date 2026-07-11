#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_phase2_v2_5_splits import (  # noqa: E402
    assign_connected_components,
    build_splits,
    canonicalize_registry,
    choose_splits,
    sequence_hash,
    sha256_text,
)
from evaluate_phase2_v2_5_readiness import (  # noqa: E402
    ALPHA_TWO_SIDED,
    MAX_CI_HALF_WIDTH,
    MDE_ABSOLUTE,
    MIN_POWER,
    build_audit,
    parse_args,
    target_readiness,
)
from phase2_v2_5_contracts import CANONICAL_FIELDS, SCHEMA_VERSION, validate_evidence_registry  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def indexed_sequence(index: int, prefix: str = "ACDEFGHIK") -> str:
    value = index
    suffix: list[str] = []
    for _ in range(4):
        suffix.append(AA_ALPHABET[value % len(AA_ALPHABET)])
        value //= len(AA_ALPHABET)
    return prefix + "".join(reversed(suffix))


def base_row(sample_id: str, seq: str, target: str, evidence: str = "E4", sealed: str | None = None) -> dict[str, object]:
    is_pvrig = "PVRIG" in target
    return {
        "sample_id": sample_id,
        "vhh_sequence": seq,
        "sequence_sha256": sequence_hash(seq),
        "target_id": target,
        "target_sequence_sha256": sha256_text(f"target:{target}"),
        "target_construct": f"{target}_construct",
        "target_family": target,
        "label_axis": "blocking" if is_pvrig else "binding",
        "evidence_level": evidence,
        "ground_truth_kind": "known_positive_calibration" if is_pvrig else "assay_backed_binding",
        "label_value": 1.0,
        "label_unit": "nM",
        "label_direction": "lower_is_better",
        "assay_type": "competition" if is_pvrig else "affinity",
        "assay_batch": f"batch_{sample_id}",
        "replicate_count": 2,
        "source_id": f"source_{sample_id}",
        "source_path_or_locator": f"fixture:{sample_id}",
        "allowed_use": "CALIBRATION_LEAKAGE_CONTROL_ONLY" if is_pvrig else "EXPERIMENTAL_RANKING_ONLY",
        "forbidden_use": "ORDINARY_TRAIN|TARGET_FORMAL" if is_pvrig else "BLOCKER_TRUTH|PVRIG_TARGET_FORMAL",
        "family_id": f"family_{sample_id}",
        "leakage_group_id": f"leak_{sample_id}",
        "split_group_id": "will_be_recomputed",
        "sealed_status": sealed or ("NOT_FORMAL" if is_pvrig else "OPEN_DEVELOPMENT"),
        "dataset_version": "fixture_v1",
        "mutation": "",
        "reference_sample_id": "",
        "pose_id": "",
        "pose_qc_status": "",
        "missing_reason": "not_applicable",
        "vhh_identity_cluster": f"vhh_cluster_{sample_id}",
        "cdr3_cluster": f"cdr3_cluster_{sample_id}",
        "pdb_id": "",
        "structure_group_id": "",
        "assay_batch_group_id": "",
        "source_group_id": "",
        "source_document_id": "",
        "patent_family_id": "",
        "base_mutant_group_id": "",
    }


def make_args(root: Path):
    exp = root / "experiments/phase2_5080_v1"
    return parse_args([
        "--train-manifest", str(exp / "train.csv"),
        "--dev-manifest", str(exp / "dev.csv"),
        "--formal-blinded", str(exp / "formal_blinded.csv"),
        "--split-audit", str(exp / "split_audit.json"),
        "--audit-out", str(exp / "readiness.json"),
        "--no-write",
    ])


class Phase2V25SplitReadinessTests(unittest.TestCase):
    def build_fixture(
        self,
        root: Path,
        rows: list[dict[str, object]],
        *,
        dev_fraction: float = 0.25,
        formal_fraction: float = 0.25,
    ) -> dict[str, object]:
        exp = root / "experiments/phase2_5080_v1"
        registry = exp / "registry.csv"
        write_csv(registry, rows)
        return build_splits(
            registry,
            exp / "train.csv",
            exp / "dev.csv",
            exp / "formal_blinded.csv",
            exp / "formal_labels.csv",
            exp / "split_audit.json",
            dev_fraction=dev_fraction,
            formal_fraction=formal_fraction,
            seed=123,
        )

    def test_connected_components_keep_linked_rows_in_one_split_and_zero_split_group_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [base_row(f"g{i}", indexed_sequence(i, "ACDEFGHIK"), f"GENERIC_{i}") for i in range(6)]
            rows[0]["source_id"] = "shared_patent"
            rows[1]["source_id"] = "shared_patent"
            rows[1]["patent_family_id"] = "shared_patent"
            rows[0]["patent_family_id"] = "shared_patent"
            rows.extend(base_row(f"p{i}", indexed_sequence(i, "LMNPQRSTV"), "PVRIG") for i in range(4))

            audit = self.build_fixture(root, rows)
            exp = root / "experiments/phase2_5080_v1"
            split_frame = pd.concat([pd.read_csv(exp / "train.csv"), pd.read_csv(exp / "dev.csv"), pd.read_csv(exp / "formal_blinded.csv")], ignore_index=True, sort=False)
            linked_splits = set(split_frame.loc[split_frame["sample_id"].isin(["g0", "g1"]), "split"])

            self.assertEqual(len(linked_splits), 1)
            self.assertNotIn("source_id", audit["leakage_overlap_audit"])
            self.assertEqual(audit["leakage_overlap_audit"]["split_group_id"]["train_vs_dev"], 0)
            self.assertEqual(audit["leakage_overlap_audit"]["split_group_id"]["train_vs_formal"], 0)

    def test_dataset_constants_do_not_collapse_components_but_explicit_relations_do(self) -> None:
        rows = [base_row(f"row_{i}", indexed_sequence(i, "ACDEFGHIK"), f"TARGET_{i}") for i in range(13)]
        for row in rows[:8]:
            row["source_id"] = "NanoBind_affinity_all"
            row["assay_batch"] = "nanobind_affinity_all_csv"

        rows[2]["vhh_sequence"] = rows[0]["vhh_sequence"]
        rows[2]["sequence_sha256"] = rows[0]["sequence_sha256"]
        rows[3]["target_sequence_sha256"] = rows[1]["target_sequence_sha256"]
        rows[3]["target_family"] = rows[1]["target_family"]
        rows[3]["target_construct"] = rows[1]["target_construct"]
        rows[5].update({
            "label_axis": "mutation_effect",
            "ground_truth_kind": "real_assay_mutation_effect",
            "mutation": "A1V",
            "reference_sample_id": "row_4",
        })
        rows[6]["base_mutant_group_id"] = "explicit_mutant_family"
        rows[7]["base_mutant_group_id"] = "explicit_mutant_family"
        rows[8].update({"source_id": "study", "assay_batch": "batch_one"})
        rows[9].update({"source_id": "study", "assay_batch": "batch_one"})
        rows[10].update({"source_id": "study", "assay_batch": "batch_two"})
        rows[11]["source_group_id"] = "explicit_source_group"
        rows[12]["source_group_id"] = "explicit_source_group"

        frame = assign_connected_components(canonicalize_registry(pd.DataFrame(rows)))
        groups = frame.set_index("sample_id")["split_group_id"].to_dict()

        self.assertNotEqual(groups["row_0"], groups["row_1"])
        self.assertEqual(groups["row_0"], groups["row_2"])
        self.assertEqual(groups["row_1"], groups["row_3"])
        self.assertEqual(groups["row_4"], groups["row_5"])
        self.assertEqual(groups["row_6"], groups["row_7"])
        self.assertEqual(groups["row_8"], groups["row_9"])
        self.assertNotEqual(groups["row_8"], groups["row_10"])
        self.assertEqual(groups["row_11"], groups["row_12"])

    def test_generic_e4_open_development_integration_has_train_dev_and_blinded_formal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows: list[dict[str, object]] = []
            for target_index in range(6):
                for candidate_index in range(2):
                    index = target_index * 2 + candidate_index
                    row = base_row(
                        f"generic_{index}",
                        indexed_sequence(index, "LMNPQRSTV"),
                        f"GENERIC_TARGET_{target_index}",
                    )
                    row.update({
                        "source_id": "NanoBind_affinity_all",
                        "assay_batch": "nanobind_affinity_all_csv",
                        "sealed_status": "OPEN_DEVELOPMENT",
                        "allowed_use": "EXPERIMENTAL_RANKING_ONLY",
                    })
                    rows.append(row)

            p0_frame = pd.DataFrame(rows)
            p0_frame["schema_version"] = SCHEMA_VERSION
            p0_frame["ordinary_train_allowed"] = "true"
            p0_frame["ordinary_test_allowed"] = "true"
            p0_frame["candidate_ranking_allowed"] = "true"
            p0_frame["ordinary_bce_eligible"] = "false"
            p0_frame["lane"] = "generic_real_assay_ranking"
            p0_frame["notes"] = "integration fixture"
            self.assertEqual(validate_evidence_registry(p0_frame[CANONICAL_FIELDS]).status, "PASS")

            audit = self.build_fixture(root, rows)
            exp = root / "experiments/phase2_5080_v1"
            train = pd.read_csv(exp / "train.csv")
            dev = pd.read_csv(exp / "dev.csv")
            blinded = pd.read_csv(exp / "formal_blinded.csv")
            labels = pd.read_csv(exp / "formal_labels.csv")

            self.assertGreater(len(train), 0)
            self.assertGreater(len(dev), 0)
            self.assertGreater(len(blinded), 0)
            self.assertEqual(set(blinded["sample_id"]), set(labels["sample_id"]))
            self.assertFalse(set(["label_value", "label_unit", "label_direction"]) & set(blinded.columns))
            self.assertTrue({"label_value", "label_unit", "label_direction"} <= set(labels.columns))
            group_sets = [set(frame["split_group_id"]) for frame in [train, dev, blinded]]
            self.assertTrue(group_sets[0].isdisjoint(group_sets[1]))
            self.assertTrue(group_sets[0].isdisjoint(group_sets[2]))
            self.assertTrue(group_sets[1].isdisjoint(group_sets[2]))
            self.assertNotIn("source_id", audit["leakage_overlap_audit"])
            for pairs in audit["leakage_overlap_audit"].values():
                self.assertTrue(all(count == 0 for count in pairs.values()))

    def test_lane_local_generic_quotas_ignore_many_non_assay_rows_and_filter_sealed_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows: list[dict[str, object]] = []
            for index in range(994):
                row = base_row(
                    f"aux_{index}",
                    indexed_sequence(index, "QRSTVWYAC"),
                    f"AUX_TARGET_{index}",
                    evidence="E1",
                    sealed="NOT_FORMAL",
                )
                row.update({
                    "label_axis": "contact",
                    "ground_truth_kind": "structure_contact_metadata",
                    "label_value": "",
                    "label_unit": "",
                    "label_direction": "",
                    "assay_type": "",
                    "assay_batch": "",
                    "replicate_count": "",
                    "allowed_use": "CONTACT_SITE_GUARDRAIL_ONLY",
                    "forbidden_use": "AFFINITY_PRIMARY|FORMAL_LABEL",
                    "missing_reason": "no_affinity_label_for_contact_metadata",
                })
                rows.append(row)

            for target_index in range(6):
                target_id = f"GENERIC_STRESS_TARGET_{target_index}"
                for candidate_index in range(2):
                    index = target_index * 2 + candidate_index
                    row = base_row(
                        f"stress_e4_{index}",
                        indexed_sequence(index, "LMNPQRSTV"),
                        target_id,
                    )
                    row.update({
                        "source_id": "NanoBind_affinity_all",
                        "assay_batch": "nanobind_affinity_all_csv",
                        "sealed_status": "OPEN_DEVELOPMENT",
                        "allowed_use": "EXPERIMENTAL_RANKING_ONLY",
                    })
                    rows.append(row)
                metadata = base_row(
                    f"linked_metadata_{target_index}",
                    indexed_sequence(target_index, "FGHIKLMNP"),
                    target_id,
                    evidence="E1",
                    sealed="NOT_FORMAL",
                )
                metadata.update({
                    "label_axis": "contact",
                    "ground_truth_kind": "component_metadata",
                    "label_value": "",
                    "label_unit": "",
                    "label_direction": "",
                    "assay_type": "",
                    "assay_batch": "",
                    "replicate_count": "",
                    "allowed_use": "CONTACT_SITE_GUARDRAIL_ONLY",
                    "forbidden_use": "AFFINITY_PRIMARY|FORMAL_LABEL",
                    "missing_reason": "component_metadata_has_no_affinity_label",
                })
                rows.append(metadata)

            audit = self.build_fixture(root, rows)
            exp = root / "experiments/phase2_5080_v1"
            train = pd.read_csv(exp / "train.csv")
            dev = pd.read_csv(exp / "dev.csv")
            blinded = pd.read_csv(exp / "formal_blinded.csv")
            labels = pd.read_csv(exp / "formal_labels.csv")

            e4_counts = {
                "train": int(train["evidence_level"].eq("E4").sum()),
                "dev": int(dev["evidence_level"].eq("E4").sum()),
                "formal": int(blinded["evidence_level"].eq("E4").sum()),
            }
            self.assertEqual(e4_counts["train"], 6)
            self.assertEqual(e4_counts["dev"] + e4_counts["formal"], 6)
            self.assertGreater(e4_counts["dev"], 0)
            self.assertGreater(e4_counts["formal"], 0)
            self.assertLessEqual(max(e4_counts["dev"], e4_counts["formal"]), 4)
            self.assertEqual(sum(e4_counts.values()), 12)
            self.assertTrue(blinded["evidence_level"].eq("E1").any())
            self.assertTrue(labels["evidence_level"].isin(["E4", "E5", "E6"]).all())
            self.assertFalse(labels[["label_value", "label_unit", "label_direction"]].isna().any().any())
            self.assertFalse(labels[["label_value", "label_unit", "label_direction"]].astype(str).apply(lambda column: column.str.strip().eq("")).any().any())
            self.assertEqual(set(labels["sample_id"]), set(blinded.loc[blinded["evidence_level"].eq("E4"), "sample_id"]))
            self.assertLess(audit["row_counts"]["formal_labels_sealed"], audit["row_counts"]["formal_blinded"])

    def test_component_weighted_mixed_metadata_keeps_train_largest_and_holdouts_near_twenty_percent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows: list[dict[str, object]] = []
            component_weights = [36, 6, 5, 4, 3, 2, 2, 1, 1]
            sequence_index = 0
            for component_index, weight in enumerate(component_weights):
                target_id = f"REALISTIC_TARGET_{component_index}"
                for candidate_index in range(weight):
                    row = base_row(
                        f"real_e4_{component_index}_{candidate_index}",
                        indexed_sequence(sequence_index, "ACDEFGHIK"),
                        target_id,
                    )
                    sequence_index += 1
                    row.update({
                        "source_id": "NanoBind_affinity_all",
                        "assay_batch": "nanobind_affinity_all_csv",
                        "allowed_use": "EXPERIMENTAL_RANKING_ONLY",
                        "sealed_status": "OPEN_DEVELOPMENT",
                    })
                    rows.append(row)
                for evidence_level in ["E1", "E2"]:
                    metadata = base_row(
                        f"real_{evidence_level.lower()}_{component_index}",
                        indexed_sequence(sequence_index, "LMNPQRSTV"),
                        target_id,
                        evidence=evidence_level,
                        sealed="NOT_FORMAL",
                    )
                    sequence_index += 1
                    metadata.update({
                        "label_axis": "contact" if evidence_level == "E1" else "proxy",
                        "ground_truth_kind": "structure_contact_metadata" if evidence_level == "E1" else "constructed_proxy",
                        "label_value": "",
                        "label_unit": "",
                        "label_direction": "",
                        "assay_type": "",
                        "assay_batch": "",
                        "replicate_count": "",
                        "allowed_use": "CONTACT_SITE_GUARDRAIL_ONLY" if evidence_level == "E1" else "PROXY_STRESS_ONLY",
                        "forbidden_use": "AFFINITY_PRIMARY|FORMAL_LABEL",
                        "missing_reason": "component_metadata_has_no_affinity_label",
                    })
                    rows.append(metadata)

            audit = self.build_fixture(root, rows, dev_fraction=0.20, formal_fraction=0.20)
            exp = root / "experiments/phase2_5080_v1"
            train = pd.read_csv(exp / "train.csv")
            dev = pd.read_csv(exp / "dev.csv")
            blinded = pd.read_csv(exp / "formal_blinded.csv")
            labels = pd.read_csv(exp / "formal_labels.csv")
            e4_counts = {
                "train": int(train["evidence_level"].eq("E4").sum()),
                "dev": int(dev["evidence_level"].eq("E4").sum()),
                "formal": int(blinded["evidence_level"].eq("E4").sum()),
            }

            self.assertEqual(e4_counts, {"train": 36, "dev": 12, "formal": 12})
            self.assertGreater(e4_counts["train"], e4_counts["dev"])
            self.assertGreater(e4_counts["train"], e4_counts["formal"])
            self.assertAlmostEqual(e4_counts["dev"] / 60.0, 0.20)
            self.assertAlmostEqual(e4_counts["formal"] / 60.0, 0.20)
            for frame in [train, dev, blinded]:
                self.assertGreater(frame.loc[frame["evidence_level"].eq("E4"), "split_group_id"].nunique(), 0)
            self.assertTrue(blinded["evidence_level"].isin(["E1", "E2"]).any())
            self.assertEqual(len(labels), e4_counts["formal"])
            self.assertTrue(labels["evidence_level"].eq("E4").all())
            for pairs in audit["leakage_overlap_audit"].values():
                self.assertTrue(all(count == 0 for count in pairs.values()))

    def test_generic_formal_quota_hard_fails_before_exhausting_train_or_dev_groups(self) -> None:
        rows = [base_row(f"quota_{i}", indexed_sequence(i, "ACDEFGHIK"), f"QUOTA_TARGET_{i}") for i in range(3)]
        frame = assign_connected_components(canonicalize_registry(pd.DataFrame(rows)))

        with self.assertRaisesRegex(ValueError, "exhaust generic train or dev"):
            choose_splits(frame, dev_fraction=0.25, formal_fraction=0.90, seed=123)

    def test_pvrig_formal_requires_e6_and_explicit_sealed_status(self) -> None:
        rows = [
            base_row("pvrig_e4_sealed", indexed_sequence(0, "PVRIGACDE"), "PVRIG_E4", evidence="E4", sealed="SEALED_LABELS"),
            base_row("pvrig_e6_open", indexed_sequence(1, "PVRIGACDE"), "PVRIG_E6_OPEN", evidence="E6", sealed="OPEN_DEVELOPMENT"),
            base_row("pvrig_e6_sealed", indexed_sequence(2, "PVRIGACDE"), "PVRIG_E6_SEALED", evidence="E6", sealed="SEALED_LABELS"),
        ]
        for row in rows:
            row["allowed_use"] = "EXPERIMENTAL_RANKING_ONLY"
            row["forbidden_use"] = "ORDINARY_TRAIN|DEVELOPMENT_LABEL_ACCESS"
            row["ground_truth_kind"] = "prospective_blinded_assay"
        frame = assign_connected_components(canonicalize_registry(pd.DataFrame(rows)))
        splits = choose_splits(frame, dev_fraction=0.2, formal_fraction=0.5, seed=123)
        by_id = dict(zip(frame["sample_id"], splits))

        self.assertNotEqual(by_id["pvrig_e4_sealed"], "formal")
        self.assertNotEqual(by_id["pvrig_e6_open"], "formal")
        self.assertEqual(by_id["pvrig_e6_sealed"], "formal")

    def test_split_builder_hard_fails_nonzero_supported_key_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [base_row(f"forced_{i}", indexed_sequence(i, "QRSTVWYAC"), f"FORCED_TARGET_{i}") for i in range(4)]
            rows[1]["vhh_sequence"] = rows[0]["vhh_sequence"]
            rows[1]["sequence_sha256"] = rows[0]["sequence_sha256"]

            def forced_row_split(frame: pd.DataFrame, **_: object) -> pd.Series:
                return pd.Series(["train", "dev", "train", "dev"], index=frame.index)

            with patch("build_phase2_v2_5_splits.choose_splits", side_effect=forced_row_split):
                with self.assertRaisesRegex(ValueError, "Nonzero split leakage overlap"):
                    self.build_fixture(root, rows)
            self.assertFalse((root / "experiments/phase2_5080_v1/train.csv").exists())

    def test_generic_formal_is_blinded_and_sealed_labels_are_separate_from_pvrig_target_formal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [base_row(f"p{i}", indexed_sequence(i, "PVRIGLMNP"), "PVRIG") for i in range(11)]
            rows.extend(base_row(f"generic_formal_{i}", indexed_sequence(i, "ACDEFGHIK"), f"GENERIC_{i}") for i in range(4))
            generic_dev = [base_row(f"generic_dev_{i}", indexed_sequence(i, "LMNPQRSTV"), f"GENERIC_DEV_{i}") for i in range(4)]
            for row in generic_dev:
                row["allowed_use"] = "CONTACT_SITE_GUARDRAIL_ONLY"
            rows.extend(generic_dev)

            audit = self.build_fixture(root, rows)
            exp = root / "experiments/phase2_5080_v1"
            blinded = pd.read_csv(exp / "formal_blinded.csv")
            labels = pd.read_csv(exp / "formal_labels.csv")

            self.assertEqual(audit["formal_scope"], "GENERIC_FORMAL_ONLY")
            self.assertGreater(len(blinded), 0)
            self.assertFalse(any(column in blinded.columns for column in ["label_value", "label_unit", "label_direction"]))
            self.assertTrue({"label_value", "label_unit", "label_direction"} <= set(labels.columns))
            self.assertFalse(blinded["target_id"].astype(str).str.contains("PVRIG").any())
            self.assertEqual(audit["row_counts"]["formal_blinded"], audit["row_counts"]["formal_labels_sealed"])
            self.assertRegex(audit["output_sha256"]["formal_labels_sealed"], r"^[0-9a-f]{64}$")

    def test_current_pvrig_like_data_returns_data_not_ready_and_never_schedules_target_training(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [base_row(f"p{i}", indexed_sequence(i, "PVRIGACDE"), "PVRIG") for i in range(11)]
            for i in range(29):
                row = base_row(f"mut{i}", indexed_sequence(i, "LMNPQRSTV"), "PVRIG")
                row.update({
                    "label_axis": "mutation_effect",
                    "evidence_level": "E0",
                    "ground_truth_kind": "mutation_control_without_measured_effect",
                    "label_value": "",
                    "label_unit": "",
                    "label_direction": "",
                    "assay_type": "",
                    "assay_batch": "",
                    "allowed_use": "leakage_control_only",
                    "forbidden_use": "ordinary_train,target_training,target_formal",
                    "missing_reason": "no_measured_delta_kd_delta_ic50_or_functional_loss_label",
                })
                rows.append(row)
            self.build_fixture(root, rows)

            result = build_audit(make_args(root))

            self.assertEqual(result["data_readiness"]["status"], "DATA_NOT_READY")
            self.assertEqual(result["formal_decision"]["status"], "DATA_NOT_READY_FOR_TARGET_MODEL")
            self.assertFalse(result["data_readiness"]["target_training_scheduled"])
            self.assertEqual(result["data_readiness"]["verified_binary_negative"], 0)
            self.assertEqual(result["data_readiness"]["assay_backed_rank_groups"], 0)
            self.assertEqual(result["data_readiness"]["target_development_model_eligible_rows"], 0)
            self.assertEqual(result["data_readiness"]["target_development_non_model_eligible_rows"], result["data_readiness"]["target_development_assay_backed_rows"])
            self.assertGreater(result["data_readiness"]["target_development_control_only_rows"], 0)
            self.assertEqual(result["calibration"]["status"], "NOT_APPLICABLE")

    def test_nonranking_rows_cannot_pad_twenty_row_target_pilot_gate(self) -> None:
        eligible = []
        for index in range(5):
            row = base_row(f"eligible_{index}", indexed_sequence(index, "PVRIGACDE"), "PVRIG", evidence="E5")
            row.update({
                "allowed_use": "EXPERIMENTAL_RANKING_ONLY",
                "ground_truth_kind": "verified_nonbinder" if index == 0 else "blocker_positive",
                "family_id": f"eligible_family_{index}",
                "assay_batch": f"eligible_batch_{index}",
                "source_id": f"eligible_source_{index}",
                "split_group_id": f"eligible_group_{index}",
            })
            eligible.append(row)
        nonranking = []
        for index in range(15):
            row = base_row(f"guardrail_{index}", indexed_sequence(index, "LMNPQRSTV"), "PVRIG", evidence="E5")
            row["allowed_use"] = "CONTACT_SITE_GUARDRAIL_ONLY"
            nonranking.append(row)
        result = target_readiness(pd.DataFrame(eligible + nonranking), pd.DataFrame(), pd.DataFrame())
        self.assertEqual(result["status"], "DATA_NOT_READY")
        self.assertEqual(result["target_development_model_eligible_rows"], 5)
        self.assertEqual(result["target_development_non_model_eligible_rows"], 15)
        self.assertFalse(result["target_training_scheduled"])

    def test_formal_power_contract_uses_registered_constants_without_reading_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [base_row(f"p{i}", indexed_sequence(i, "PVRIGACDE"), "PVRIG") for i in range(5)]
            rows.extend(base_row(f"generic_formal_{i}", indexed_sequence(i, "ACDEFGHIK"), f"GENERIC_{i}") for i in range(6))
            self.build_fixture(root, rows)

            result = build_audit(make_args(root))
            power = result["data_readiness"]["power_simulation"]

            self.assertEqual(power["mde_absolute"], MDE_ABSOLUTE)
            self.assertEqual(power["alpha_two_sided"], ALPHA_TWO_SIDED)
            self.assertEqual(power["minimum_power"], MIN_POWER)
            self.assertEqual(power["maximum_ci_half_width"], MAX_CI_HALF_WIDTH)
            self.assertFalse(power["formal_labels_read"])

    def test_blinded_formal_manifest_with_label_columns_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [base_row(f"generic_formal_{i}", indexed_sequence(i, "ACDEFGHIK"), f"GENERIC_{i}") for i in range(4)]
            self.build_fixture(root, rows)
            exp = root / "experiments/phase2_5080_v1"
            blinded = pd.read_csv(exp / "formal_blinded.csv")
            blinded["label_value"] = [1.0] * len(blinded)
            blinded.to_csv(exp / "formal_blinded.csv", index=False)

            result = build_audit(make_args(root))

            self.assertEqual(result["status"], "INVALID_RUN")
            self.assertIn("label_value", result["formal_seal"]["formal_blinded_label_columns_exposed"])


if __name__ == "__main__":
    unittest.main()
