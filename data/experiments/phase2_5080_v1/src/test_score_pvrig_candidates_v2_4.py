#!/usr/bin/env python3
"""Focused tests for V2.4 PVRIG scoring and three-seed summaries."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_pvrig_candidates_v2_4 import (  # noqa: E402
    BOUNDARY_NOTE,
    CHECKPOINT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    load_model_from_checkpoint,
    parse_args as parse_score_args,
    run_scoring,
    split_exclusions,
    validate_candidate_identity,
)
from summarize_phase2_v2_4_multiseed import (  # noqa: E402
    NOT_APPLICABLE,
    build_summary,
    parse_args as parse_summary_args,
    write_candidate_csv,
    write_json,
    write_markdown,
)
from train_phase2_v2_3 import CDRMaskStore, ESM2Cache, seq_hash  # noqa: E402
from train_phase2_v2_4 import Config, CrossContactNetV24  # noqa: E402


class ScorePvrigCandidatesV24Tests(unittest.TestCase):
    def tiny_config(self) -> Config:
        return Config(
            root=".",
            out_root="experiments/phase2_5080_v1",
            esm2_cache_manifest="cache/manifest.csv",
            cdr_mask_csv="cdr_masks.csv",
            d_model=16,
            esm_dim=8,
            contact_dim=8,
            layers=1,
            cross_layers=1,
            heads=2,
            dropout=0.0,
            max_vhh_len=12,
            max_antigen_len=14,
            ranking_groups_csv="groups.csv",
            pvrig_controls_csv="controls.csv",
        )

    def write_cache(self, root: Path, seqs: list[str], cfg: Config) -> Path:
        cache_dir = root / "cache"
        cache_dir.mkdir()
        shard = {}
        rows = []
        for idx, seq in enumerate(seqs):
            digest = seq_hash(seq)
            shard[digest] = torch.full((len(seq), cfg.esm_dim), float(idx + 1), dtype=torch.float32)
            rows.append({"sequence_sha256": digest, "sequence_length": len(seq), "cached_length": len(seq), "truncation_policy": "none", "shard_path": "shard_00000.pt", "shard_key": digest})
        torch.save(shard, cache_dir / "shard_00000.pt")
        manifest = cache_dir / "manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return manifest

    def write_masks(self, root: Path, seqs: list[str]) -> Path:
        path = root / "cdr_masks.csv"
        rows = []
        for seq in seqs:
            mask = [0] * len(seq)
            if len(mask) >= 2:
                mask[-2:] = [3, 3]
            rows.append({"sequence_hash": seq_hash(seq), "vhh_seq": seq, "vhh_len": len(seq), "cdr_mask_json": json.dumps(mask), "status": "ok"})
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def write_checkpoint(self, root: Path, cfg: Config, schema: str = CHECKPOINT_SCHEMA_VERSION) -> Path:
        torch.manual_seed(11)
        model = CrossContactNetV24(cfg)
        path = root / "checkpoint.pt"
        torch.save({"model": model.state_dict(), "cfg": asdict(cfg), "epoch": 3, "best_score": 1.5, "schema_version": schema}, path)
        return path

    def test_checkpoint_schema_is_strict(self) -> None:
        cfg = self.tiny_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = self.write_checkpoint(Path(tmpdir), cfg, schema="phase2_v2_3_checkpoint")
            with self.assertRaisesRegex(ValueError, "Incompatible V2.4 checkpoint schema"):
                load_model_from_checkpoint(bad, None, torch.device("cpu"))

    def test_candidate_identity_hash_mismatch_is_rejected(self) -> None:
        df = pd.DataFrame([{"candidate_id": "cand", "vhh_seq": "ACDE", "vhh_sequence_sha256": "not-the-hash"}])
        with self.assertRaisesRegex(ValueError, "Candidate identity mismatch"):
            validate_candidate_identity(df)

    def test_controls_and_constructed_rows_are_excluded_before_ranking(self) -> None:
        control_seq = "ACDEFGHIK"
        df = pd.DataFrame(
            [
                {"candidate_id": "keep", "vhh_seq": "LMNPQRST", "candidate_role": "new_candidate", "negative_type": ""},
                {"candidate_id": "known", "vhh_seq": control_seq, "candidate_role": "new_candidate", "negative_type": ""},
                {"candidate_id": "n1", "vhh_seq": "QRSTVWYA", "candidate_role": "constructed_contrastive_candidate", "negative_type": "N1_easy_cross_antigen"},
            ]
        )
        kept, excluded = split_exclusions(df, {seq_hash(control_seq)})
        self.assertEqual(kept["candidate_id"].tolist(), ["keep"])
        self.assertEqual(set(excluded["candidate_id"]), {"known", "n1"})
        self.assertIn("excluded_constructed_n1_n2_n3_proxy_contrast", set(excluded["exclusion_reason"]))

    def test_run_scoring_writes_exact_provenance_boundary_and_na_calibration(self) -> None:
        cfg = self.tiny_config()
        keep_seq = "ACDEFGHIK"
        control_seq = "LMNPQRST"
        target_seq = "QRSTVWYA"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manifest = self.write_cache(root, [keep_seq, target_seq], cfg)
            masks = self.write_masks(root, [keep_seq])
            checkpoint = self.write_checkpoint(root, cfg)
            candidate_table = root / "mvp_candidates.csv"
            pd.DataFrame(
                [
                    {"candidate_id": "cand_keep", "vhh_seq": keep_seq, "candidate_role": "new_candidate", "vhh_sequence_sha256": seq_hash(keep_seq)},
                    {"candidate_id": "control", "vhh_seq": control_seq, "candidate_role": "new_candidate", "vhh_sequence_sha256": seq_hash(control_seq)},
                ]
            ).to_csv(candidate_table, index=False)
            top = root / "top50.csv"
            pd.DataFrame([{"candidate_id": "cand_keep"}, {"candidate_id": "control"}]).to_csv(top, index=False)
            controls = root / "controls.csv"
            pd.DataFrame([{"sample_id": "ctrl", "sequence": control_seq, "sequence_sha256": seq_hash(control_seq)}]).to_csv(controls, index=False)
            fasta = root / "target.fasta"
            fasta.write_text(f">pvrig_proxy\n{target_seq}\n", encoding="utf-8")
            output = root / "scores.csv"
            args = parse_score_args([
                "--root", str(root), "--checkpoint", str(checkpoint), "--config", "", "--v2-2-top50", str(top),
                "--candidate-table", str(candidate_table), "--target-fasta", str(fasta), "--esm2-cache-manifest", str(manifest),
                "--cdr-mask-csv", str(masks), "--pvrig-controls-csv", str(controls), "--output", str(output), "--device", "cpu",
            ])
            result = run_scoring(args)
            scored = pd.read_csv(output)
            metadata = json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
            excluded = pd.read_csv(output.with_suffix(".excluded.csv"))

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(len(scored), 1)
            self.assertEqual(scored.loc[0, "schema_version"], SCHEMA_VERSION)
            self.assertEqual(scored.loc[0, "vhh_sequence"], keep_seq)
            self.assertEqual(scored.loc[0, "vhh_sequence_sha256"], seq_hash(keep_seq))
            self.assertEqual(scored.loc[0, "target_sequence_sha256"], seq_hash(target_seq))
            self.assertEqual(scored.loc[0, "phase2_v2_4_boundary_note"], BOUNDARY_NOTE)
            self.assertEqual(scored.loc[0, "phase2_v2_4_calibration_status"], NOT_APPLICABLE)
            self.assertIn("not verified non-binders", scored.loc[0, "phase2_v2_4_boundary_note"])
            self.assertEqual(metadata["calibration"]["status"], NOT_APPLICABLE)
            self.assertEqual(metadata["ranked_candidates"], 1)
            self.assertEqual(metadata["excluded_candidates"], 1)
            self.assertEqual(excluded.loc[0, "candidate_id"], "control")

    def write_run(self, root: Path, seed: int, ranking_mrr: float = 0.4, sizes: dict[str, int] | None = None, checkpoint_schema: str = CHECKPOINT_SCHEMA_VERSION) -> Path:
        run = root / f"phase2_v2_4_seed{seed}"
        run.mkdir()
        (run / "config_resolved.json").write_text(json.dumps({"seed": seed, "schema_version": checkpoint_schema}), encoding="utf-8")
        metrics = {
            "run_id": run.name,
            "schema_version": checkpoint_schema,
            "dataset_sizes": sizes or {"contact_test": 4, "site_test": 3, "pair_test": 3, "rank_test": 3},
            "contact_test": {"contact_auprc": 0.7 + seed / 1000},
            "site_test": {"paratope_auprc": 0.6, "epitope_auprc": 0.5},
            "ranking_test": {"ranking_mrr": ranking_mrr, "ranking_hit_at_1": 0.25, "ranking_hard_negative_win_rate": 0.75},
            "pair_test": {"pair_metric_boundary": "constructed rows are not verified non-binders"},
        }
        (run / "test_metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        return run

    def write_candidates(self, root: Path, seed: int, rows: list[dict[str, object]]) -> Path:
        path = root / f"candidates_seed{seed}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def test_three_seed_summary_reports_stability_and_per_seed_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [self.write_run(root, seed, ranking_mrr=0.4 + idx / 10) for idx, seed in enumerate((41, 43, 47))]
            identity = hashlib.sha256(b"A\x1fACDE\x1fTARGET").hexdigest()
            base = {"schema_version": SCHEMA_VERSION, "phase2_v2_4_boundary_note": BOUNDARY_NOTE, "candidate_identity_sha256": identity, "vhh_sequence_sha256": seq_hash("ACDE"), "target_sequence_sha256": seq_hash("TARGET")}
            cand_args = []
            for seed, ranks in zip((41, 43, 47), ((1, 2), (2, 1), (1, 2))):
                path = self.write_candidates(root, seed, [
                    {**base, "candidate_id": "A", "rank": ranks[0], "phase2_v2_4_pair_ranking_logit": 2.0, "phase2_v2_4_combined_ranking_ai_prior": 0.9},
                    {**base, "candidate_id": "B", "rank": ranks[1], "phase2_v2_4_pair_ranking_logit": 1.0, "phase2_v2_4_combined_ranking_ai_prior": 0.4},
                ])
                cand_args.extend(["--candidate-csv", f"{seed}={path}"])
            out_json = root / "summary.json"
            out_md = root / "summary.md"
            out_csv = root / "candidates.csv"
            args = parse_summary_args([*(str(run) for run in runs), *cand_args, "--output-json", str(out_json), "--output-md", str(out_md), "--output-candidates-csv", str(out_csv)])
            summary = build_summary(args)
            write_json(summary, out_json)
            write_markdown(summary, out_md)
            write_candidate_csv(summary, out_csv)

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["n_runs"], 3)
            self.assertEqual(summary["calibration"]["status"], NOT_APPLICABLE)
            self.assertIn("ranking_mrr", summary["metrics"])
            self.assertIn("rank_stability", summary["candidate_summary"][0])
            self.assertEqual(summary["candidate_summary"][0]["phase2_v2_4_sequence_ensemble_score"], 1.0)
            self.assertGreater(summary["candidate_summary"][0]["phase2_v2_4_sequence_ensemble_score"], summary["candidate_summary"][1]["phase2_v2_4_sequence_ensemble_score"])
            self.assertIn("41", json.loads(summary["candidate_summary"][0]["per_seed_scores_json"]))
            self.assertIn("per_seed_scores_json", out_csv.read_text(encoding="utf-8"))
            self.assertIn("not verified non-binders", out_md.read_text(encoding="utf-8"))

    def test_summary_rejects_candidate_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runs = [self.write_run(root, seed) for seed in (41, 43, 47)]
            cand_args = []
            for seed, digest in zip((41, 43, 47), (seq_hash("A"), seq_hash("A"), seq_hash("DIFFERENT"))):
                path = self.write_candidates(root, seed, [{"schema_version": SCHEMA_VERSION, "phase2_v2_4_boundary_note": BOUNDARY_NOTE, "candidate_id": "A", "candidate_identity_sha256": "id", "vhh_sequence_sha256": digest, "target_sequence_sha256": seq_hash("TARGET"), "rank": 1, "phase2_v2_4_pair_ranking_logit": 1.0, "phase2_v2_4_combined_ranking_ai_prior": 0.5}])
                cand_args.extend(["--candidate-csv", f"{seed}={path}"])
            args = parse_summary_args([*(str(run) for run in runs), *cand_args, "--output-json", str(root / "s.json"), "--output-md", str(root / "s.md"), "--output-candidates-csv", str(root / "c.csv")])
            with self.assertRaisesRegex(ValueError, "Candidate identity mismatch"):
                build_summary(args)


if __name__ == "__main__":
    unittest.main()
