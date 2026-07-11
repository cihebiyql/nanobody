#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_phase2_v2_4_final import build_audit, file_sha256, parse_args, sequence_hash  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ValidatePhase2V24FinalTests(unittest.TestCase):
    def make_args(self, root: Path, extra: list[str] | None = None):
        exp = root / "experiments/phase2_5080_v1"
        argv = [
            "--exp-dir", str(exp),
            "--manifest-audit", str(exp / "audits/phase2_v2_4_manifest_build_v1.json"),
            "--ranking-csv", str(exp / "data_splits/pair_ranking_groups_v2_4.csv"),
            "--controls-csv", str(exp / "data_splits/pvrig_validation_controls_v2_4.csv"),
            "--pose-summary-csv", str(exp / "prepared/pvrig_pose_proxy_summary_v2_4.csv"),
            "--aggregate-json", str(exp / "reports/phase2_v2_4_multiseed_summary_v1.json"),
            "--preregistration-json", str(exp / "audits/phase2_v2_4_preregistration_v1.json"),
            "--pose-identity-json", str(exp / "audits/phase2_v2_4_candidate_pose_identity_qc_v1.json"),
            "--fusion-json", str(exp / "audits/phase2_v2_4_fusion_provenance_v1.json"),
            "--canonical-checkpoint", str(exp / "checkpoints/phase2_v2_4_best_checkpoint.pt"),
            "--portable-checkpoint-audit", str(exp / "audits/phase2_v2_4_portable_checkpoints_v1.json"),
            "--portable-inference-equivalence", str(exp / "audits/phase2_v2_4_portable_inference_equivalence_v1.json"),
            "--json-out", str(exp / "audits/out.json"),
            "--markdown-out", str(exp / "audits/out.md"),
            "--no-write",
        ]
        if extra:
            argv.extend(extra)
        return parse_args(argv)

    def write_fixture(self, root: Path, overlap: bool = False, bad_boundary: bool = False) -> None:
        exp = root / "experiments/phase2_5080_v1"
        ranking_rows = [
            {
                "ranking_group_id": "g1", "split": "train", "positive_pair_id": "p1", "candidate_pair_id": "p1",
                "candidate_role": "observed_cognate_positive", "negative_type": "positive_anchor", "vhh_seq": "AAAA",
                "antigen_seq": "CCCC", "preference_label": 1, "label_source": "cognate_structure_pair",
                "proxy_label_policy": "observed_cognate_positive_rank_anchor", "ranking_weight": 1.0,
                "ranking_margin": 0.0, "ordinary_bce_eligible": "yes",
            },
            {
                "ranking_group_id": "g1", "split": "train", "positive_pair_id": "p1", "candidate_pair_id": "n1",
                "candidate_role": "constructed_contrastive_candidate", "negative_type": "N1_easy_cross_antigen", "vhh_seq": "AAAT",
                "antigen_seq": "DDDD", "preference_label": 0, "label_source": "constructed_contrastive_preference",
                "proxy_label_policy": "constructed_preference_not_verified_nonbinder", "ranking_weight": 0.5,
                "ranking_margin": 0.15, "ordinary_bce_eligible": "no",
            },
        ]
        write_csv(exp / "data_splits/pair_ranking_groups_v2_4.csv", ranking_rows)
        control_rows = []
        for index in range(47):
            seq = "AAAA" if overlap and index == 0 else f"CCCC{index}"
            control_rows.append({
                "sample_id": f"ctrl{index}", "molecule_name": f"C{index}", "sequence_sha256": sequence_hash(seq),
                "sequence": seq, "family": "PVRIG", "control_role": "known_positive_calibration" if index < 11 else "mutant",
                "label_hint": "calibration", "leakage_policy": "exact_known_positive_calibration_only",
                "assay_ic50_nm": "", "kd_m": "", "reporter_ec50_nm": "", "pose_count": 1,
                "ordinary_train_allowed": False, "ordinary_test_allowed": False, "candidate_ranking_allowed": False,
                "ground_truth_kind": "assay_backed_positive_calibration", "source_table": "fixture",
            })
        write_csv(exp / "data_splits/pvrig_validation_controls_v2_4.csv", control_rows)
        write_csv(exp / "prepared/pvrig_pose_proxy_summary_v2_4.csv", [
            {
                "sample_id": row["sample_id"], "source_lane": "known_positive_pose_calibration", "pose_rows": 1,
                "consensus_blocker_like_a_count": 0, "single_baseline_recheck_count": 0,
                "blocker_plausible_b_count": 0, "evidence_inference_only_e_count": 1,
                "other_class_count": 0, "any_blocker_like_a": False, "manual_review_required": True,
                "proxy_semantics": "docking_proxy_not_experimental_label",
            }
            for row in control_rows
        ])
        write_json(exp / "audits/phase2_v2_4_manifest_build_v1.json", {
            "status": "PASS",
            "boundaries": {"constructed_negatives": "ranking proxies, not verified non-binders", "pose_labels": "docking proxies, not experimental labels"},
        })
        write_json(exp / "audits/phase2_v2_4_preregistration_v1.json", {"status": "LOCKED", "test_metrics_used_for_selection": False})
        write_json(exp / "audits/phase2_v2_4_candidate_pose_identity_qc_v1.json", {"status": "PASS", "exact_identity": True})
        write_json(exp / "audits/phase2_v2_4_fusion_provenance_v1.json", {"status": "PASS", "provenance": {"ai": "proxy"}, "boundary": "proxy only"})
        write_json(exp / "reports/phase2_v2_4_multiseed_summary_v1.json", {
            "status": "PASS", "seeds": ["43", "53", "67"], "n_runs": 3,
            "calibration": {"status": "NOT_APPLICABLE", "reason": "no verified binary labels"},
            "boundary": "proxy rankings only" if not bad_boundary else "validated blocker biological validation",
        })
        canonical_written = False
        for seed in (43, 53, 67):
            run = exp / "runs" / f"phase2_v2_4_fixture_seed{seed}"
            run.mkdir(parents=True, exist_ok=True)
            checkpoint_bytes = f"checkpoint-{seed}".encode("ascii")
            (run / "best_checkpoint.pt").write_bytes(checkpoint_bytes)
            (exp / "checkpoints").mkdir(parents=True, exist_ok=True)
            (exp / f"checkpoints/phase2_v2_4_strict_seed{seed}_best_checkpoint.pt").write_bytes(checkpoint_bytes)
            if seed == 67 and not canonical_written:
                (exp / "checkpoints/phase2_v2_4_best_checkpoint.pt").write_bytes(checkpoint_bytes)
                canonical_written = True
            write_json(run / "config_resolved.json", {"seed": seed})
            metrics = {
                "dataset_sizes": {"rank_train": 1, "rank_val": 1, "rank_test": 1},
                "label_boundary": "constructed ranking candidates are proxy contrasts, not verified non-binders; not a classifier",
                "contact_test": {"contact_auprc": 0.7},
                "ranking_test": {"ranking_mrr": 0.4, "ranking_metric_boundary": "proxy, not classifier"},
                "calibration": {"status": "NOT_APPLICABLE", "reason": "no verified positive-and-negative probability labels"},
            }
            write_json(run / "test_metrics.json", metrics)
            write_json(run / "run_summary.json", {
                "history": [{"epoch": 1, "val_contact_auprc": 0.6}],
                "test_metrics": metrics,
                "env": {"run_id": run.name, "best_epoch": 1, "device": "cuda", "gpu_name": "NVIDIA GeForce RTX 5080"},
                "warmstart": {"status": "loaded", "source": f"phase2_v2_3_strict_seed{seed}_best_checkpoint.pt", "loaded_keys": 99},
                "strict_inputs": {},
            })
            write_json(run / "metrics_history.json", [{"epoch": 1, "val_contact_auprc": 0.6}])
            write_json(exp / f"audits/{run.name}_gpu_telemetry_summary.json", {
                "train_exit_code": 0,
                "samples": 20,
                "gpu_names": ["NVIDIA GeForce RTX 5080"],
                "max_utilization_gpu_pct": 60.0,
                "max_memory_used_mib": 6000.0,
            })
        portable_rows = []
        for seed in (43, 53, 67):
            source = exp / f"runs/phase2_v2_4_fixture_seed{seed}/best_checkpoint.pt"
            portable = exp / f"checkpoints/phase2_v2_4_strict_seed{seed}_best_checkpoint.pt"
            portable_rows.append({
                "seed": seed,
                "source_sha256": file_sha256(source),
                "portable_sha256": file_sha256(portable),
                "model_state_roundtrip_equal": True,
            })
        write_json(exp / "audits/phase2_v2_4_portable_checkpoints_v1.json", {
            "status": "PASS",
            "checkpoints": portable_rows,
            "canonical_matches_selected_portable_sha256": True,
        })
        write_json(exp / "audits/phase2_v2_4_portable_inference_equivalence_v1.json", {
            "status": "PASS",
            "seeds": [43, 53, 67],
            "all_three_seeds_full50_exact": True,
            "candidate_ids_equal": True,
            "candidate_identity_hashes_equal": True,
            "max_abs_differences": {"ranking_logit": 0.0},
        })

    def test_passes_when_all_required_v24_artifacts_are_proxy_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root)
            result = build_audit(self.make_args(root))
            self.assertEqual(result["status"], "PASS_WITH_PAIR_RANKING_LIMITATION")
            self.assertEqual(result["failed_checks"], [])

    def test_fails_when_pvrig_control_hash_overlaps_ranking_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, overlap=True)
            result = build_audit(self.make_args(root))
            self.assertIn("pvrig_controls_have_zero_exact_hash_overlap_with_ranking", result["failed_checks"])

    def test_fails_when_required_seed_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root)
            missing = root / "experiments/phase2_5080_v1/runs/phase2_v2_4_fixture_seed53/test_metrics.json"
            missing.unlink()
            result = build_audit(self.make_args(root))
            self.assertIn("exact_seed_set_43_53_67_present", result["failed_checks"])

    def test_warns_not_fails_when_optional_fusion_artifact_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root)
            (root / "experiments/phase2_5080_v1/audits/phase2_v2_4_fusion_provenance_v1.json").unlink()
            result = build_audit(self.make_args(root))
            self.assertNotEqual(result["status"], "FAIL")
            self.assertIn("fusion_provenance_is_explicit_and_proxy_bounded", result["warnings"])

    def test_fails_when_aggregate_claims_biological_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_fixture(root, bad_boundary=True)
            result = build_audit(self.make_args(root))
            self.assertIn("aggregate_boundary_does_not_claim_biological_validation", result["failed_checks"])


if __name__ == "__main__":
    unittest.main()
