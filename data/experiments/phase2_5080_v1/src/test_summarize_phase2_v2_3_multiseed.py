#!/usr/bin/env python3
"""Unit tests for Phase 2 V2.3 multi-seed summarization."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from summarize_phase2_v2_3_multiseed import (  # noqa: E402
    NOT_APPLICABLE,
    PAIR_PROXY_BOUNDARY,
    build_summary,
    parse_args,
    write_candidate_csv,
    write_json,
    write_markdown,
)


class SummarizePhase2V23MultiseedTests(unittest.TestCase):
    def write_run(self, root: Path, seed: int, contact_auprc: float = 0.7, proxy_auroc: float = 0.55, sizes: dict[str, int] | None = None) -> Path:
        run = root / f"phase2_v2_3_20260710_seed{seed}"
        run.mkdir()
        (run / "config_resolved.json").write_text(json.dumps({"seed": seed, "schema_version": "v2_3_strict"}), encoding="utf-8")
        metrics = {
            "schema_version": "v2_3_strict",
            "run_id": run.name,
            "dataset_sizes": sizes
            or {
                "contact_train": 10,
                "contact_val": 3,
                "contact_test": 4,
                "site_train": 8,
                "site_val": 2,
                "site_test": 3,
                "pair_train": 9,
                "pair_val": 2,
                "pair_test": 3,
                "rank_train": 7,
                "rank_val": 2,
                "rank_test": 3,
            },
            "contact_test": {"contact_auprc": contact_auprc, "contact_auroc": 0.8, "unrelated": 999},
            "site_test": {"paratope_auprc": 0.6, "epitope_auprc": 0.5},
            "ranking_test": {"ranking_mrr": 0.4 + seed / 1000, "ranking_hit_at_1": 0.25},
            "pair_test": {
                "pair_contrastive_proxy_auroc": proxy_auroc,
                "pair_contrastive_proxy_auprc": 0.44,
                "pair_auroc": 0.99,
                "pair_metric_boundary": "constructed rows are not verified non-binders",
            },
        }
        (run / "test_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        return run

    def write_candidates(self, root: Path, seed: int, rows: list[dict[str, object]]) -> Path:
        path = root / f"candidates_seed{seed}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def test_multiseed_metrics_candidates_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run1 = self.write_run(root, 43, contact_auprc=0.7, proxy_auroc=0.5)
            run2 = self.write_run(root, 47, contact_auprc=0.9, proxy_auroc=0.7)
            cand1 = self.write_candidates(
                root,
                43,
                [
                    {"candidate_id": "A", "rank": 1, "phase2_v2_3_pair_ranking_logit": 2.0, "phase2_v2_3_combined_ranking_ai_prior": 0.9},
                    {"candidate_id": "B", "rank": 2, "phase2_v2_3_pair_ranking_logit": 1.0, "phase2_v2_3_combined_ranking_ai_prior": 0.4},
                ],
            )
            cand2 = self.write_candidates(
                root,
                47,
                [
                    {"candidate_id": "A", "rank": 2, "phase2_v2_3_pair_ranking_logit": 1.5, "phase2_v2_3_combined_ranking_ai_prior": 0.7},
                    {"candidate_id": "B", "rank": 1, "phase2_v2_3_pair_ranking_logit": 1.8, "phase2_v2_3_combined_ranking_ai_prior": 0.8},
                ],
            )
            out_json = root / "summary.json"
            out_md = root / "summary.md"
            out_csv = root / "candidates.csv"
            args = parse_args(
                [
                    str(run1),
                    str(run2 / "test_metrics.json"),
                    "--candidate-csv",
                    f"43={cand1}",
                    "--candidate-csv",
                    f"47={cand2}",
                    "--output-json",
                    str(out_json),
                    "--output-md",
                    str(out_md),
                    "--output-candidates-csv",
                    str(out_csv),
                ]
            )
            summary = build_summary(args)
            write_json(summary, out_json)
            write_markdown(summary, out_md)
            write_candidate_csv(summary, out_csv)

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["seeds"], ["43", "47"])
            self.assertAlmostEqual(summary["metrics"]["contact_auprc"]["mean"], 0.8)
            self.assertAlmostEqual(summary["metrics"]["pair_contrastive_proxy_auroc"]["mean"], 0.6)
            self.assertNotIn("pair_auroc", summary["metrics"])
            self.assertEqual(summary["pair_proxy_boundary"], PAIR_PROXY_BOUNDARY)
            self.assertEqual(summary["candidate_summary"][0]["consensus_rank"], 1)
            self.assertEqual(summary["candidate_summary"][0]["rank_median"], 1.5)
            self.assertTrue(out_json.exists())
            self.assertIn("pair_contrastive_proxy", out_md.read_text(encoding="utf-8"))
            self.assertIn("consensus_rank", out_csv.read_text(encoding="utf-8"))

    def test_dataset_size_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run1 = self.write_run(root, 43)
            run2 = self.write_run(root, 47, sizes={"contact_train": 999, "contact_val": 3, "contact_test": 4})
            args = parse_args([str(run1), str(run2), "--output-json", str(root / "s.json"), "--output-md", str(root / "s.md"), "--output-candidates-csv", str(root / "c.csv")])
            with self.assertRaisesRegex(ValueError, "Dataset size mismatch"):
                build_summary(args)

    def test_pair_proxy_boundary_excludes_legacy_pair_auroc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run = self.write_run(root, 43)
            args = parse_args([str(run), "--output-json", str(root / "s.json"), "--output-md", str(root / "s.md"), "--output-candidates-csv", str(root / "c.csv")])
            summary = build_summary(args)
            self.assertIn("pair_contrastive_proxy_auroc", summary["metrics"])
            self.assertNotIn("pair_auroc", summary["metrics"])
            self.assertNotIn("binding_auroc", json.dumps(summary).lower())
            self.assertIn("not binding AUROC", summary["pair_proxy_boundary"])

    def test_calibration_na_without_verified_binary_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run = self.write_run(root, 43)
            constructed = root / "constructed.csv"
            pd.DataFrame(
                [
                    {"candidate_id": "A", "constructed_contrastive_target": 1, "predicted_probability": 0.8, "label_source": "constructed_contrastive"},
                    {"candidate_id": "B", "constructed_contrastive_target": 0, "predicted_probability": 0.2, "label_source": "constructed_contrastive"},
                ]
            ).to_csv(constructed, index=False)
            args = parse_args(
                [
                    str(run),
                    "--calibration-csv",
                    str(constructed),
                    "--output-json",
                    str(root / "s.json"),
                    "--output-md",
                    str(root / "s.md"),
                    "--output-candidates-csv",
                    str(root / "c.csv"),
                ]
            )
            summary = build_summary(args)
            self.assertEqual(summary["calibration"]["status"], NOT_APPLICABLE)
            self.assertIn("verified binary labels", summary["calibration"]["reason"])
            self.assertIn("constructed contrasts", summary["calibration"]["reason"])


if __name__ == "__main__":
    unittest.main()
