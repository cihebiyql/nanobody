#!/usr/bin/env python3
"""Build the hash-bound V2.4 prefreeze manifest with calibration pending."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


BUNDLE = "/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v1_20260718"
RUNTIME = "/data1/qlyu/projects/pvrig_v6_residue_v2_4_four_lane_oof_v1_20260718"
V23_BUNDLE = "/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718"
HF_SNAPSHOT = "/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c"
ESM_SHA = "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"
EXPECTED_KEY_SHA256 = {
    "training_tsv": "47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1",
    "training_receipt": "b7e5f764a58d1d4d059c36ebbafc2851d93cce7539110b44b7fd7240e3344499",
    "trainer": "59245b7aa28c14e9134f15fa1c2f4717e3a3b3a7c3e044a4d7cda06afc1c685f",
    "trainer_test": "f28d93c3df30775c4d3d1ee120d0c5e7d39fb117d6eb01b58b342e5985873704",
    "calibration_runner": "b6ce135c7d89b97a407c923a42f13af8557ead679bdf3603981e5461544f08e5",
    "deployment_launcher": "29be5df27ae38787970b85a9150481442c9b13fa81db2e5da86b26bf0bd85935",
    "contact_formula": "7abe8e845b33ef7c77a61397a826fb3e6f94fb34122b7abbc2ddbd77c6db2ec7",
    "model": "d3295b4a8c8465a528f2e9a8b465e63177e465b2183999f6d972ffa4a3bde36d",
    "outer_split_source": "ce49916385ccb792b4b03dda72889ab8c72aaccd662ccfcdb1d30874bdd81e55",
    "outer_split_materialization_receipt": "5f412ab844420a18ff4d7b52d4a1631c98c2ee5f3dee4322df6c650eaa8e4c21",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_record(repo: Path, relative: str, node1_path: str) -> dict[str, Any]:
    path = (repo / relative).resolve()
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"source_missing_or_symlink:{path}")
    return {
        "source_path": str(path), "node1_path": node1_path,
        "sha256": sha(path), "size_bytes": path.stat().st_size,
        "validation_mode": "LOCAL_SOURCE_AND_NODE1",
    }


def run(repo: Path, output: Path) -> dict[str, Any]:
    p = "experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/v2_4_fs_stack_prototype_v1_20260718"
    r = "experiments/phase2_5080_v1"
    artifacts: dict[str, dict[str, Any]] = {}
    specs = {
        "training_tsv": (f"{p}/data_contract/materialized_v1/v6_supervised1507_v2_4.tsv", f"{BUNDLE}/inputs/v6_supervised1507_v2_4.tsv"),
        "training_receipt": (f"{p}/data_contract/materialized_v1/v6_supervised1507_v2_4.receipt.json", f"{BUNDLE}/inputs/v6_supervised1507_v2_4.receipt.json"),
        "trainer": (f"{p}/trainer/train_v2_4_base_split.py", f"{BUNDLE}/src/train_v2_4_base_split.py"),
        "trainer_test": (f"{p}/trainer/test_train_v2_4_base_split.py", f"{BUNDLE}/tests/test_train_v2_4_base_split.py"),
        "model": (f"{p}/model/residue_model_v2_4.py", f"{BUNDLE}/src/residue_model_v2_4.py"),
        "model_test": (f"{p}/model/test_residue_model_v2_4.py", f"{BUNDLE}/tests/test_residue_model_v2_4.py"),
        "calibration_runner": (f"{p}/deployment/run_open_only_prestep_calibration_v1.py", f"{BUNDLE}/src/run_open_only_prestep_calibration_v1.py"),
        "deployment_launcher": (f"{p}/deployment/node1_v2_4_outer_development_launcher_v1.py", f"{BUNDLE}/src/node1_v2_4_outer_development_launcher_v1.py"),
        "contact_formula": (f"{p}/contact_contract/contact_score_formula_v1.json", f"{BUNDLE}/inputs/contact_contract/contact_score_formula_v1.json"),
        "outer_split_source": (f"{p}/split_contract/prepared/whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4/outer_development_manifest.tsv", f"{BUNDLE}/inputs/splits/source_outer_development_manifest.tsv"),
        "outer_split_materialization_receipt": (f"{p}/deployment/prepared/outer_split_json_v1/receipt.json", f"{BUNDLE}/inputs/splits/receipt.json"),
        "dual_marginal_tsv_gz": (f"{r}/prepared/pvrig_v6_dual_residue_contact_targets_v2_20260718/v6_dual_source_residue_contact_targets_v2.tsv.gz", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/dual_marginal/v6_dual_source_residue_contact_targets_v2.tsv.gz"),
        "dual_marginal_receipt": (f"{r}/prepared/pvrig_v6_dual_residue_contact_targets_v2_20260718/RUN_RECEIPT.json", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/dual_marginal/RUN_RECEIPT.json"),
        "dual_pair_tsv_gz": (f"{r}/prepared/pvrig_v6_dual_pair_contact_targets_v2_20260718/v6_dual_source_pair_contact_targets_v2.tsv.gz", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/dual_pair/v6_dual_source_pair_contact_targets_v2.tsv.gz"),
        "dual_pair_receipt": (f"{r}/prepared/pvrig_v6_dual_pair_contact_targets_v2_20260718/RUN_RECEIPT.json", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/dual_pair/RUN_RECEIPT.json"),
        "vhh_graph_cache_npz": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/graph_cache_v2.npz", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/graph_cache_v2.npz"),
        "vhh_graph_manifest": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/graph_manifest_v2.tsv", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/graph_manifest_v2.tsv"),
        "vhh_graph_receipt": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/graph_cache_receipt_v2.json", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/graph_cache_receipt_v2.json"),
        "vhh_graph_closure": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/graph_input_closure_v2.tsv", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/graph_input_closure_v2.tsv"),
        "vhh_graph_materialization_receipt": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/materialization_receipt_v2.json", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/materialization_receipt_v2.json"),
        "base_target_pt": (f"{r}/prepared/pvrig_v6_residue_v2_fixed_target_graphs_v1_20260718/target_graphs_v2.pt", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt"),
        "base_target_receipt": (f"{r}/prepared/pvrig_v6_residue_v2_fixed_target_graphs_v1_20260718/target_graph_receipt_v2.json", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_receipt_v2.json"),
        "v23_trainer": (f"{r}/v6_target_conditioned_surrogate_20260717/residue_v2/src/train_nested_residue_surrogate_v2.py", f"{V23_BUNDLE}/residue_v2/src/train_nested_residue_surrogate_v2.py"),
        "v1_trainer": (f"{r}/v6_target_conditioned_surrogate_20260717/residue_v1/src/train_nested_residue_surrogate.py", f"{V23_BUNDLE}/residue_v1/src/train_nested_residue_surrogate.py"),
        "v1_5_trainer": (f"{r}/v6_target_conditioned_surrogate_20260717/residue_v1/src/train_nested_residue_surrogate_v1_5.py", f"{V23_BUNDLE}/residue_v1/src/train_nested_residue_surrogate_v1_5.py"),
        "v1_model": (f"{r}/v6_target_conditioned_surrogate_20260717/residue_v1/src/residue_model.py", f"{V23_BUNDLE}/residue_v1/src/residue_model.py"),
        # The local prepared directory uses the historical V2_3 filename, but
        # the immutable Node1 V2.3 deployment bundle published these exact
        # bytes as IMPLEMENTATION_FREEZE_V2.json.  Bind the real remote path;
        # the SHA remains the frozen e532... value.
        "v23_freeze": (f"{r}/prepared/pvrig_v6_residue_v2_3_numerical_soak_launcher_v1_20260718/IMPLEMENTATION_FREEZE_V2_3.json", f"{V23_BUNDLE}/residue_v2/IMPLEMENTATION_FREEZE_V2.json"),
    }
    for label, (source, node1) in specs.items():
        artifacts[label] = local_record(repo, source, node1)
    for fold in range(5):
        artifacts[f"outer_split_{fold}"] = local_record(
            repo, f"{p}/deployment/prepared/outer_split_json_v1/outer_fold_{fold}.json",
            f"{BUNDLE}/inputs/splits/outer_fold_{fold}.json",
        )
    for label, expected in EXPECTED_KEY_SHA256.items():
        observed = artifacts[label]["sha256"]
        if observed != expected:
            raise RuntimeError(f"key_artifact_sha256_mismatch:{label}:{observed}:{expected}")
    artifacts["esm2_650m_identity"] = {
        "node1_path": f"{HF_SNAPSHOT}/model.safetensors", "sha256": ESM_SHA,
        "size_bytes": 2609506392, "validation_mode": "INHERITED_NODE1_IMMUTABLE",
        "inherited_freeze_sha256": artifacts["v23_freeze"]["sha256"],
    }

    prefixes = [
        "ALL__", "CDR1_CDR2__", "CDR1_CDR3__", "CDR1_FRAMEWORK__", "CDR1__",
        "CDR2_CDR3__", "CDR2_FRAMEWORK__", "CDR2__", "CDR3_FRAMEWORK__", "CDR3__",
        "CDR_ALL__", "FRAMEWORK__",
    ]
    template = [
        "{python}", "{trainer}", "--lane", "{lane}", "--output-dir", "{output_dir}",
        "--split-manifest", "{split_manifest}", "--v2-3-bundle-root", V23_BUNDLE,
        "--training-tsv", "{training_tsv}", "--contact-tsv-gz", "{dual_marginal_tsv_gz}",
        "--graph-cache-dir", "{vhh_graph_dir}", "--target-graph-pt", "{base_target_pt}",
        "--pair-contact-tsv-gz", "{dual_pair_tsv_gz}", "--structure-dim", "126",
        "--contact-formula-json", "{contact_formula}",
        "--model-path", HF_SNAPSHOT, "--model-identity-file", "{esm2_650m_identity}",
        "--expected-model-sha256", ESM_SHA, "--learning-rate", "0.0001", "--weight-decay", "0.02",
        "--gradient-clip", "1.0", "--gradient-accumulation", "2", "--huber-delta", "0.03",
        "--receptor-weight", "1.0", "--dual-weight", "0.5", "--ridge-alpha", "10.0", "--seed", "43",
    ]
    for prefix in prefixes:
        template.extend(("--structure-prefix", prefix))
    payload = {
        "schema_version": "pvrig_v6_residue_v2_4_node1_deployment_manifest_v1",
        "status": "PREFREEZE_DRY_RUN_PENDING_CALIBRATION_DO_NOT_START",
        "production_authorized": False,
        "claim_boundary": "Open-only independent 8X6B/9E6Y computational Docking geometry surrogate; not binding, affinity, experimental blocking, Docking Gold, or submission evidence.",
        "bundle_root": BUNDLE, "runtime_root": RUNTIME,
        "python": "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python",
        "resources": {
            "lane_gpu_map": {"A_VHH_ONLY": 1, "B_TARGET_NO_CONTACT": 2, "C_SPLIT_MARGINAL": 4, "D_SPLIT_PAIR": 5},
            "cpu_threads_per_process": 8,
            "thread_environment": {"OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "8", "NUMEXPR_NUM_THREADS": "8", "TOKENIZERS_PARALLELISM": "false"},
        },
        "execution": {
            "phase_order": ["OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION", "IMPLEMENTATION_FREEZE", "TINY_SMOKE", "FOUR_LANE_OUTER_DEVELOPMENT"],
            "outer_folds": [0, 1, 2, 3, 4], "lanes_concurrent": 4,
            "folds_sequential_within_lane": True, "tiny_smoke_must_pass_all_lanes": True,
            "automatic_smoke_to_outer_transition": False,
        },
        "expected_training_counts": {
            "rows": 1507, "unique_candidates": 1507, "unique_parent_framework_clusters": 31,
            "teacher_sources": {"V4D_OPEN_MULTI_SEED": 226, "V4H_ADAPTIVE_SEED_RANKING": 1281},
            "reliability_tiers": {"A": 349, "B": 241, "C": 917},
        },
        "artifacts": artifacts,
        "trainer": {
            "artifact_label": "trainer", "argv_template": template,
            "tiny_smoke_extra_argv": ["--backbone-kind", "tiny", "--tiny-e2e", "--fixed-epochs", "1", "--graph-hidden-dim", "32", "--dropout", "0", "--batch-size", "4", "--device", "cpu", "--precision", "fp32"],
            "outer_development_extra_argv": None, "lane_outer_extra_argv": None,
            "required_result_file": "RESULT.json",
            "frozen_noncalibration_parameters": {"structure_dim": 126, "graph_hidden_dim": 128, "dropout": 0.25, "fixed_epochs": 8, "batch_size": 8, "learning_rate": 0.0001, "weight_decay": 0.02, "gradient_clip": 1.0, "gradient_accumulation": 2, "precision": "bf16", "huber_delta": 0.03, "receptor_weight": 1.0, "dual_weight": 0.5, "ridge_alpha": 10.0, "seed": 43},
        },
        "calibration_contract": {
            "binding_status": "PENDING_OPEN_ONLY_PRESTEP_CALIBRATION", "receipt_artifact_label": None,
            "calibration_runtime_root": "/data1/qlyu/projects/pvrig_v6_residue_v2_4_calibration_v1_20260718",
            "calibration_receipt_node1_path": f"{BUNDLE}/CALIBRATION_RECEIPT.json",
            "open_only": True, "optimizer_steps_before_observation": 0,
            "outer_metrics_access_count": 0, "prediction_metrics_access_count": 0,
            "fixed_grid": [0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01],
            "pair_to_marginal_ratio": 0.5, "target_gradient_fraction_band": [0.05, 0.2],
            "selection_rule": "per_lane_smallest_grid_value_in_target_band_before_optimizer_step",
            "frozen_lane_contact_weights": None,
            "attention_temperatures": {"8x6b": 1.0, "9e6y": 1.0},
        },
        "runtime_must_remain_absent_until_implementation_freeze": True,
        "pending": ["CALIBRATION_RECEIPT.json", "frozen_lane_contact_weights", "IMPLEMENTATION_FREEZE_V2_4.json"],
        "sealed_evaluation_access_count": 0, "prediction_metrics_access_count": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "PASS_PREFREEZE_MANIFEST_MATERIALIZED_CALIBRATION_PENDING", "output": str(output), "sha256": sha(output), "artifact_count": len(artifacts)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.repo_root, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
