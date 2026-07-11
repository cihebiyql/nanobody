#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_phase2_v2_5_generic import (  # noqa: E402
    LABEL_COLUMNS,
    apply_authoritative_split_assignments,
    normalize_records,
    prepare,
)
from train_phase2_v2_5_generic import (  # noqa: E402
    BASELINE_ORDER,
    Config,
    exact_random_metrics,
    group_indices,
    load_formal_for_unseal,
    make_features,
    ordinal_pair_loss,
    pairwise_accuracy,
    read_formal_blinded,
    sequence_identity_nn,
    source_assay_prior,
    train,
)


class Args:
    pass


class Phase2V25GenericTests(unittest.TestCase):
    def write_nanobind(self, root: Path, rows: list[list[str]] | None = None) -> Path:
        path = root / "all.csv"
        if rows is None:
            rows = [
                ["pdbA", "H", "AAAA", "A", "TTTT", "1e-9"],
                ["pdbA_rep", "H", " a a a a ", "A", " t t t t ", "3e-9"],
                ["pdbB", "H", "AAAC", "A", "TTTT", "1e-8"],
                ["pdbC", "H", "CCCC", "A", "GGGG", "5e-9"],
                ["pdbD", "H", "CCCD", "A", "GGGG", "5e-8"],
                ["pdbE", "H", "EEEE", "A", "HHHH", "2e-9"],
                ["pdbF", "H", "EEEF", "A", "HHHH", "2e-8"],
            ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ID", "nanobody_chain", "seq_nanobody", "antigen_chain", "seq_antigen", "affinity"])
            writer.writerows(rows)
        return path

    def prepare_hash_fixture(self, root: Path) -> tuple[Path, dict]:
        args = Args()
        args.input_csv = self.write_nanobind(root)
        args.model_path = root / "fake_esm2"
        args.model_path.mkdir()
        (args.model_path / "config.json").write_text("{}", encoding="utf-8")
        args.output_dir = root / "prepared"
        args.dataset_version = "tiny_v1"
        args.split_seed = 7
        args.formal_fraction = 0.34
        args.dev_fraction = 0.33
        args.embedding_backend = "hash"
        args.device = "cpu"
        args.batch_size = 2
        args.max_residues = 32
        args.hash_dim = 8
        args.authoritative_split_mode = "internal"
        summary = prepare(args)
        return args.output_dir, summary.__dict__

    def test_authoritative_p1_assignments_override_internal_split_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = normalize_records(self.write_nanobind(root), "authoritative_v1", 7, 0.34, 0.33)
            by_key = {(row["sequence_sha256"], row["target_sequence_sha256"]): row for row in rows}
            components: dict[str, list[tuple[str, str]]] = {}
            for key, row in by_key.items():
                components.setdefault(str(row["split_group_id"]), []).append(key)
            component_keys = [sorted(values) for _, values in sorted(components.items())]
            split_keys = {"train": component_keys[0], "dev": component_keys[1], "formal": component_keys[2]}
            paths = {}
            for split, selected in split_keys.items():
                records = []
                for index, key in enumerate(selected):
                    row = by_key[key]
                    records.append({
                        "sample_id": f"p1_{split}_{index}",
                        "sequence_sha256": key[0],
                        "target_sequence_sha256": key[1],
                        "target_id": "NANOBIND_TARGET_SHA256_" + key[1],
                        "evidence_level": "E4",
                        "split_group_id": f"p1_component_{split}_{index}",
                    })
                path = root / f"{split}.csv"
                pd.DataFrame(records).to_csv(path, index=False)
                paths[split] = path
            provenance = apply_authoritative_split_assignments(rows, paths["train"], paths["dev"], paths["formal"])
            self.assertEqual(provenance["imported_e4_counts"], {"train": 2, "dev": 2, "formal": 2})
            self.assertEqual({split: sum(row["split"] == split for row in rows) for split in split_keys}, {"train": 2, "dev": 2, "formal": 2})
            self.assertEqual({row["sealed_status"] for row in rows if row["split"] == "formal"}, {"SEALED_LABELS"})

    def training_config(self, root: Path, output: Path, seeds: tuple[int, ...] = (43,)) -> Config:
        return Config(
            records_csv=str(output / "nanobind_affinity_train_dev_v2_5.csv"),
            embeddings_pt=str(output / "frozen_sequence_embeddings.pt"),
            formal_blinded_csv=str(output / "nanobind_affinity_formal_blinded_v2_5.csv"),
            out_dir=str(root / "runs"),
            seeds=seeds,
            epochs=2,
            hidden_dim=8,
            dropout=0.0,
            device="cpu",
            batch_groups=1,
        )

    def test_prepare_aggregates_duplicates_and_preserves_sealed_feature_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output, summary = self.prepare_hash_fixture(root)
            records = pd.read_csv(output / "nanobind_affinity_records_v2_5.csv")
            train_dev = pd.read_csv(output / "nanobind_affinity_train_dev_v2_5.csv")
            audit = json.loads((output / "nanobind_affinity_prepare_audit_v2_5.json").read_text(encoding="utf-8"))

            self.assertEqual(summary["input_rows"], 7)
            self.assertEqual(summary["total_records"], 6)
            self.assertEqual(summary["duplicate_group_count"], 1)
            duplicate = records.loc[records["source_record_count"] == 2].iloc[0]
            self.assertEqual(duplicate["source_record_ids"], "pdbA;pdbA_rep")
            self.assertEqual(audit["duplicate_audit"]["merged_excess_row_count"], 1)
            self.assertEqual(audit["duplicate_audit"]["policy"], "aggregate_exact_normalized_vhh_target_pair_with_median_kd")
            self.assertAlmostEqual(audit["duplicate_audit"]["duplicate_groups"][0]["median_affinity_kd_m"], 2e-9)
            if duplicate["split"] == "formal":
                labeled = pd.read_csv(output / "nanobind_affinity_formal_labels_sealed_v2_5.csv")
            else:
                labeled = train_dev
            canonical_label = labeled.loc[labeled["sample_id"] == duplicate["sample_id"], "affinity_kd_m"].iloc[0]
            self.assertAlmostEqual(float(canonical_label), 2e-9)

            self.assertEqual(set(records["allowed_use"]), {"EXPERIMENTAL_RANKING_ONLY"})
            self.assertTrue(records["replicate_count"].isna().all())
            self.assertTrue(records["missing_reason"].str.contains("HISTORICAL_REPLICATE_COUNT_NOT_REPORTED").all())
            self.assertEqual(records.groupby("split_group_id")["split"].nunique().max(), 1)
            self.assertEqual(records.groupby("ranking_group_id")["target_sequence_sha256"].nunique().max(), 1)

            blinded = pd.read_csv(output / "nanobind_affinity_formal_blinded_v2_5.csv")
            self.assertFalse(set(blinded.columns) & LABEL_COLUMNS)
            for column in (
                "vhh_sequence",
                "target_sequence",
                "vhh_sequence_length",
                "target_sequence_length",
                "sequence_sha256",
                "target_sequence_sha256",
                "ranking_group_id",
            ):
                self.assertIn(column, blinded.columns)
            self.assertEqual(set(blinded["sealed_status"]), {"SEALED_LABELS"})
            formal_public = records.loc[records["split"] == "formal"]
            self.assertTrue(formal_public["affinity_score"].isna().all())
            sealed = pd.read_csv(output / "nanobind_affinity_formal_labels_sealed_v2_5.csv")
            self.assertEqual(set(sealed["sealed_status"]), {"SEALED_LABELS"})
            self.assertIn("affinity_score", sealed.columns)

            embeddings = torch.load(output / "frozen_sequence_embeddings.pt", map_location="cpu", weights_only=False)
            self.assertEqual(summary["unique_sequences"], len(embeddings))
            self.assertTrue(all(tensor.numel() == 8 for tensor in embeddings.values()))

    def test_exact_vhh_target_components_do_not_replace_target_ranking_groups(self) -> None:
        rows = [
            ["a", "H", "AAAA", "A", "TTTT", "1e-9"],
            ["b", "H", "AAAA", "A", "GGGG", "2e-9"],
            ["c", "H", "CCCC", "A", "GGGG", "3e-9"],
            ["d", "H", "DDDD", "A", "HHHH", "4e-9"],
            ["e", "H", "DDDE", "A", "HHHH", "5e-9"],
            ["f", "H", "EEEE", "A", "IIII", "6e-9"],
            ["g", "H", "EEEF", "A", "IIII", "7e-9"],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = normalize_records(self.write_nanobind(root, rows), "component_v1", 3, 0.25, 0.25)
            linked = [row for row in normalized if row["vhh_sequence"] in {"AAAA", "CCCC"}]
            self.assertEqual(len({row["split_group_id"] for row in linked}), 1)
            self.assertEqual(len({row["split"] for row in linked}), 1)
            self.assertEqual(len({row["ranking_group_id"] for row in linked}), 2)
            linked_split = linked[0]["split"]
            groups = group_indices(normalized, linked_split, 1)
            linked_indices = {normalized.index(row) for row in linked}
            linked_group_sizes = sorted(len(set(group) & linked_indices) for group in groups if set(group) & linked_indices)
            self.assertEqual(linked_group_sizes, [1, 2])

    def test_prepare_rejects_bad_affinity_and_bad_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.csv"
            bad.write_text(
                "ID,nanobody_chain,seq_nanobody,antigen_chain,seq_antigen,affinity\n"
                "x,H,AA 11,A,TTTT,0\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                normalize_records(bad, "bad", 1, 0.0, 0.5)

    def test_ordinal_and_exact_random_metrics(self) -> None:
        scores_good = torch.tensor([3.0, 1.0, 2.0, 0.0])
        scores_bad = -scores_good
        labels = torch.tensor([9.0, 8.0, 7.0, 6.0])
        groups = [[0, 1], [2, 3]]
        self.assertLess(float(ordinal_pair_loss(scores_good, labels, groups)), float(ordinal_pair_loss(scores_bad, labels, groups)))
        rows = [{"affinity_score": str(value), "ranking_group_id": f"g{index // 2}"} for index, value in enumerate(labels.tolist())]
        self.assertEqual(pairwise_accuracy(rows, scores_good.tolist(), groups), 1.0)

        random_rows = [
            {"affinity_score": "3", "ranking_group_id": "g"},
            {"affinity_score": "2", "ranking_group_id": "g"},
            {"affinity_score": "1", "ranking_group_id": "g"},
        ]
        expected = exact_random_metrics(random_rows, [[0, 1, 2]])
        reversed_expected = exact_random_metrics(list(reversed(random_rows)), [[0, 1, 2]])
        self.assertEqual(expected["macro_group_pairwise_preference_accuracy"], 0.5)
        self.assertAlmostEqual(expected["group_mrr"], (1.0 + 0.5 + 1.0 / 3.0) / 3.0)
        self.assertAlmostEqual(expected["hit_at_1"], 1.0 / 3.0)
        self.assertAlmostEqual(expected["macro_group_ndcg_all"], reversed_expected["macro_group_ndcg_all"])

    def test_baselines_use_training_rows_only_and_source_prior_median(self) -> None:
        train_rows = [
            {"source_id": "s", "assay_type": "a", "affinity_score": "1", "vhh_sequence": "AAAA", "target_sequence": "TTTT"},
            {"source_id": "s", "assay_type": "a", "affinity_score": "100", "vhh_sequence": "CCCC", "target_sequence": "GGGG"},
            {"source_id": "s", "assay_type": "a", "affinity_score": "101", "vhh_sequence": "EEEE", "target_sequence": "HHHH"},
        ]
        eval_rows = [
            {"source_id": "s", "assay_type": "a", "affinity_score": "0", "vhh_sequence": "AAAT", "target_sequence": "TTTT"},
            {"source_id": "unknown", "assay_type": "x", "affinity_score": "0", "vhh_sequence": "CCCT", "target_sequence": "GGGG"},
        ]
        self.assertEqual(source_assay_prior(train_rows, eval_rows), [100.0, 100.0])
        self.assertEqual(sequence_identity_nn(train_rows, eval_rows), [1.0, 100.0])

    def test_training_smoke_cpu_does_not_read_formal_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output, _ = self.prepare_hash_fixture(root)
            labels = output / "nanobind_affinity_formal_labels_sealed_v2_5.csv"
            labels.rename(output / "labels_hidden.csv")
            summary = train(self.training_config(root, output))
            self.assertEqual(summary["formal_unseal_status"], "SEALED_LABELS_NOT_READ")
            seed_result = summary["seed_results"][0]
            self.assertEqual(seed_result["device"], "cpu")
            self.assertIsNone(seed_result["telemetry"]["cuda_device_name"])
            self.assertIsNone(seed_result["telemetry"]["cuda_peak_allocated_bytes"])
            self.assertGreater(seed_result["telemetry"]["elapsed_seconds"], 0.0)
            self.assertIn("macro_group_pairwise_preference_accuracy", seed_result["dev_metrics"]["shallow_head"])
            self.assertEqual(seed_result["dev_metrics"]["frozen_v2_4"]["status"], "INELIGIBLE_WITH_REASON")
            self.assertEqual(seed_result["dev_metrics"]["nanobind_external_prior"]["status"], "LEAKAGE_UNSAFE_DIAGNOSTIC")
            self.assertFalse(summary["preregistered_selection"]["formal_metrics_consulted"])

    def test_formal_evaluation_is_real_one_shot_and_never_selects_on_formal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output, _ = self.prepare_hash_fixture(root)
            training = train(self.training_config(root, output, seeds=(43, 53, 67)))
            run_dir = Path(training["run_dir"])
            selection_path = run_dir / "preregistered_selection.json"
            selection_before = selection_path.read_bytes()
            selected_before = training["preregistered_selection"]["selected_baseline"]

            labels = pd.read_csv(output / "nanobind_affinity_formal_labels_sealed_v2_5.csv")
            labels["affinity_score"] = list(reversed(labels["affinity_score"].tolist()))
            altered_labels = output / "formal_labels_altered_for_selection_guard.csv"
            labels.to_csv(altered_labels, index=False)
            evaluation_cfg = Config(
                formal_blinded_csv=str(output / "nanobind_affinity_formal_blinded_v2_5.csv"),
                formal_labels_csv=str(altered_labels),
                run_dir=str(run_dir),
                device="cpu",
                unseal_evaluate=True,
            )
            formal = train(evaluation_cfg)
            self.assertEqual(formal["formal_unseal_status"], "UNSEALED_EXPLICIT_ONE_SHOT_COMPLETE")
            self.assertEqual(formal["dev_selected_strongest_eligible_baseline"], selected_before)
            self.assertFalse(formal["formal_labels_used_for_checkpoint_or_method_selection"])
            self.assertEqual(selection_path.read_bytes(), selection_before)
            self.assertEqual(formal["seed_consistency"]["seed_count"], 3)
            self.assertEqual(set(formal["formal_inference_telemetry_by_seed"]), {"43", "53", "67"})

            for seed in (43, 53, 67):
                seed_dir = run_dir / "formal_evaluation" / f"seed_{seed}"
                predictions = pd.read_csv(seed_dir / "formal_predictions.csv")
                self.assertEqual(set(predictions["method"]), set(BASELINE_ORDER) | {"shallow_head"})
                metrics = json.loads((seed_dir / "formal_metrics.json").read_text(encoding="utf-8"))
                self.assertIn("paired_group_delta_vs_dev_selected_baseline", metrics)
                self.assertEqual(metrics["telemetry"]["actual_device"], "cpu")
                self.assertGreater(metrics["telemetry"]["elapsed_seconds"], 0.0)
                self.assertEqual(metrics["formal_metrics"]["frozen_v2_4"]["status"], "INELIGIBLE_WITH_REASON")
                self.assertEqual(metrics["formal_metrics"]["nanobind_external_prior"]["eligibility"], "INELIGIBLE")
                self.assertEqual(
                    metrics["formal_metrics"]["random_within_group"]["macro_group_pairwise_preference_accuracy"], 0.5
                )
            audit = json.loads((run_dir / "formal_unseal_audit.json").read_text(encoding="utf-8"))
            self.assertTrue(audit["inference_completed_before_labels_read"])
            self.assertTrue(audit["formal_features_unchanged_after_unseal"])
            self.assertFalse(audit["formal_labels_used_for_selection"])
            with self.assertRaises(RuntimeError):
                train(evaluation_cfg)

    def test_unseal_preserves_features_and_rejects_label_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output, _ = self.prepare_hash_fixture(root)
            blinded_path = output / "nanobind_affinity_formal_blinded_v2_5.csv"
            labels_path = output / "nanobind_affinity_formal_labels_sealed_v2_5.csv"
            blinded_rows = read_formal_blinded(blinded_path)
            merged_rows = load_formal_for_unseal(blinded_path, labels_path)
            embeddings = torch.load(output / "frozen_sequence_embeddings.pt", map_location="cpu", weights_only=False)
            self.assertTrue(torch.equal(make_features(blinded_rows, embeddings), make_features(merged_rows, embeddings)))

            bad_blinded = output / "bad_blinded.csv"
            pd.read_csv(blinded_path).assign(affinity_score=1.0).to_csv(bad_blinded, index=False)
            with self.assertRaises(ValueError):
                load_formal_for_unseal(bad_blinded, labels_path)

    def test_training_source_contains_no_sklearn_or_scipy(self) -> None:
        source = (Path(__file__).resolve().parent / "train_phase2_v2_5_generic.py").read_text(encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        self.assertEqual(len(digest), 64)
        self.assertNotIn("sklearn", source)
        self.assertNotIn("scipy", source)


if __name__ == "__main__":
    unittest.main()
