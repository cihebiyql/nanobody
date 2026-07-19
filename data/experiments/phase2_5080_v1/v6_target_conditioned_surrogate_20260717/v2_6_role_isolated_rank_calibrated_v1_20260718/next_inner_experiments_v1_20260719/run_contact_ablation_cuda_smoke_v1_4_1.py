#!/usr/bin/env python3
"""Run one frozen open-inner one-epoch CUDA smoke for a V1.4 contact ablation."""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch


SCHEMA = "pvrig_v2_6_contact_ablation_cuda_smoke_job_v1_4_1"
CLAIM = (
    "Open-development inner-validation approximation of independent 8X6B/9E6Y "
    "computational Docking geometry only; not binding, affinity, experimental "
    "blocking, Docking Gold, sealed V4-F/test32 evidence, or submission truth."
)
INTEGRATION_FREEZE_SHA = "22f34aff3c5cd9b912f94e1266dffcb217c5767974160068365bea3889e0f4fc"
INTEGRATION_TRAINER_SHA = "a16bc446747edb95fdbc6d507c884a89810a97ec4f942dd895476c98a9f5f605"
V25_RUNNER_SHA = "f7c4e813f19d9034a945982d029118dc87cc6c420f1f8c8cf898bfec74065b7f"
V25_API_SHA = "af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0"
V25_MODEL_SHA = "26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521"
OPT_SHA = "2dadc945ec30eb802ca9f32fac84ce647783b9defc36db68f345fc00e972f363"
RANK_SHA = "b420766a7769a546418a68367b71742eb3ea7872dd2411a48609139a985ef2ec"
TRUST_SHA = "2acf16069e3609a8160d9193818fa707a5105405e28354956f3431634756959e"
SMOKE_SHA = "e6901c772411464d8b2fb906839dd07afcbfdfc39e1d8ec1d18b01e66b50ea21"

BASE_PACKAGE = Path("/data1/qlyu/projects/pvrig_v2_6_inner_only_pilot_resolved_v1_2_20260719")

V25_SRC = Path("/data1/qlyu/projects/pvrig_v2_5_ortho_heads_smoke_package_v1_2_20260718/src")
DATA = Path("/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718")
ADAPTER = Path("/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v2_2_2_20260718/src/train_v2_4_base_split.py")
V23 = Path("/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718")
TARGET = Path("/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt")
MODEL = Path("/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c")
MODEL_FILE = MODEL / "model.safetensors"
MODEL_SHA = "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def atomic_torch(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    torch.save(dict(payload), temporary)
    os.replace(temporary, path)


def modules(package_root: Path):
    dependencies = (
        (V25_SRC / "run_real1507_split_v1.py", V25_RUNNER_SHA),
        (V25_SRC / "train_v2_5_ortho_heads.py", V25_API_SHA),
        (V25_SRC / "residue_model_v2_5_ortho.py", V25_MODEL_SHA),
        (package_root / "integration_v1_4/IMPLEMENTATION_FREEZE_V1_4.json", INTEGRATION_FREEZE_SHA),
        (package_root / "integration_v1_4/real1507_role_isolated_trainer_v1_4.py", INTEGRATION_TRAINER_SHA),
        (BASE_PACKAGE / "vendor/optimizer/role_isolated_optimization_v1.py", OPT_SHA),
        (BASE_PACKAGE / "vendor/rank/rank_calibration_core_v1_1.py", RANK_SHA),
        (BASE_PACKAGE / "vendor/trust_anchors/TRUST_ANCHOR_SET_RECEIPT.json", TRUST_SHA),
        (BASE_PACKAGE / "smoke_evidence/SMOKE_RESULT_V1_3_1.json", SMOKE_SHA),
    )
    for path, expected in dependencies:
        require(path.is_file() and not path.is_symlink(), f"dependency_not_regular:{path}")
        require(sha(path) == expected, f"dependency_hash:{path}")
    sys.path[:0] = [
        str(V25_SRC),
        str(package_root / "integration_v1_4"),
        str(BASE_PACKAGE / "vendor/optimizer"),
        str(BASE_PACKAGE / "vendor/rank"),
    ]
    runner = importlib.import_module("run_real1507_split_v1")
    v25 = importlib.import_module("train_v2_5_ortho_heads")
    integ = importlib.import_module("real1507_role_isolated_trainer_v1_4")
    opt = importlib.import_module("role_isolated_optimization_v1")
    policy = integ.RankPolicyAdapter.load(BASE_PACKAGE / "vendor/rank/rank_calibration_core_v1_1.py", RANK_SHA)
    return runner, v25, integ, opt, policy


def context_args(output: Path, variant: str, device: str) -> argparse.Namespace:
    split = "outer_0_inner_0"
    return argparse.Namespace(
        lane_variant=variant,
        output_dir=output,
        v2_4_adapter_path=ADAPTER,
        expected_v2_4_adapter_sha256="59245b7aa28c14e9134f15fa1c2f4717e3a3b3a7c3e044a4d7cda06afc1c685f",
        v2_3_bundle_root=V23,
        training_tsv=DATA / f"inputs/split_training/{split}.tsv",
        contact_tsv_gz=DATA / f"inputs/split_contacts/{split}.marginal.tsv.gz",
        pair_contact_tsv_gz=DATA / f"inputs/split_contacts/{split}.pair.tsv.gz",
        graph_cache_dir=DATA / f"inputs/split_graphs/{split}",
        target_graph_pt=TARGET,
        contact_formula_json=DATA / "inputs/contact_score_formula_v1.json",
        split_manifest=DATA / f"plan/trainer_splits/{split}.json",
        model_path=MODEL,
        model_identity_file=MODEL_FILE,
        expected_model_sha256=MODEL_SHA,
        device=device,
        expected_rows=1269,
        expected_parents=28,
        expected_train_rows=1085,
        expected_score_rows=184,
    )


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def write_predictions(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    require(len(records) == 184, "prediction_row_count")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--integration-lane", required=True)
    parser.add_argument("--seed", type=int, choices=(43, 97, 193), required=True)
    parser.add_argument("--lambda-rank", type=float, choices=(0.0,), required=True)
    parser.add_argument("--physical-gpu", type=int, choices=(5, 6), required=True)
    parser.add_argument("--device", choices=("cuda:0", "cuda:1", "cuda:2", "cuda:3"), required=True)
    args = parser.parse_args()

    require(not args.output_dir.exists(), "output_dir_exists")
    require(os.environ.get("CUDA_VISIBLE_DEVICES") == "1,4,5,6", "cuda_visible_devices")
    require(os.environ.get("CUBLAS_WORKSPACE_CONFIG") == ":4096:8", "cublas_workspace")
    logical = {1: 0, 4: 1, 5: 2, 6: 3}[args.physical_gpu]
    require(args.device == f"cuda:{logical}", "physical_logical_mapping")
    torch.cuda.set_device(logical)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), "cuda_bf16_unavailable")

    runner, v25, integ, opt, policy = modules(args.package_root)
    allowed = {
        "F0_MARGINAL_ONLY_NO_RANK": (integ.LANE_F, 0.0, "E_DECOUPLED_CONTACT_SHARED", 1.0, 0.0),
        "F0_PAIR_ONLY_NO_RANK": (integ.LANE_F, 0.0, "E_DECOUPLED_CONTACT_SHARED", 0.0, 0.5),
    }
    require(args.variant in allowed, "variant")
    lane, rank_lambda, source_variant, marginal_weight, pair_weight = allowed[args.variant]
    require(args.integration_lane == lane and args.lambda_rank == rank_lambda, "lane_rank_contract")

    set_seed(args.seed)
    context = runner.load_real_context(context_args(args.output_dir, source_variant, args.device))
    context.batches.seed = args.seed
    scalar_loss = v25.OrthoLossConfig(receptor_weight=1.0, dual_weight=0.5, marginal_weight=0.0, pair_weight=0.0)
    contact_loss = v25.OrthoLossConfig(receptor_weight=1.0, dual_weight=0.5, marginal_weight=marginal_weight, pair_weight=pair_weight)
    role_config = opt.RoleOptimizerConfig(
        learning_rate=1e-4,
        contact_learning_rate=1e-4,
        weight_decay=0.02,
        clip_shared=1.0,
        clip_scalar=1.0,
        clip_contact=1.0,
        kappa=0.25,
        lambda_contact_shared=1.0,
    )
    config = integ.V26TrainerConfig(
        integration_lane=lane,
        fixed_epochs=1,
        gradient_accumulation=2,
        lambda_rank=rank_lambda,
        precision="bf16",
        base_seed=args.seed,
        outer_fold=0,
        inner_fold=0,
        expected_main_batches_per_epoch=math.ceil(len(context.train_indices) / context.batches.batch_size),
        rank_trust_anchor_set_receipt_path=str(BASE_PACKAGE / "vendor/trust_anchors/TRUST_ANCHOR_SET_RECEIPT.json"),
        rank_trust_anchor_dir=str(BASE_PACKAGE / "vendor/trust_anchors"),
        physical_gpu_index=args.physical_gpu,
        logical_cuda_index=logical,
    )
    receipt = integ.train_v25_real1507_context_nonlaunching(
        context=context,
        v25_api=v25,
        optimizer_api=opt,
        rank_policy=policy,
        delta_noise_binding_path=BASE_PACKAGE / "vendor/V2_6_DELTA_NOISE_BINDING.json",
        scalar_loss_config=scalar_loss,
        contact_loss_config=contact_loss,
        role_optimizer_config=role_config,
        config=config,
        device_name=args.device,
    )
    expected_steps = math.ceil(math.ceil(1085 / 8) / 2)
    require(receipt["optimizer_steps"] == expected_steps, "optimizer_step_count")
    require(len(receipt["gradient_step_diagnostics"]) == expected_steps, "step_evidence_count")
    require(receipt["exact_min_probe_error"] == 0.0, "exact_min_probe")
    require(all(receipt.get(field) == 0 for field in ("score_truth_rows_accessed", "outer_metrics_access_count", "v4_f_test32_access_count")), "receipt_firewall")

    records = runner._score_without_metrics(context, device_name=args.device)
    args.output_dir.mkdir(parents=True)
    prediction_path = args.output_dir / "score_predictions_no_metrics.tsv"
    write_predictions(prediction_path, records)
    exact_min_violations = sum(
        abs(float(row["neural_Rdual"]) - min(float(row["neural_R8"]), float(row["neural_R9"]))) > 1e-7
        for row in records
    )
    require(exact_min_violations == 0, "prediction_exact_min")

    checkpoint_path = args.output_dir / "neural_head.pt"
    head_state = {name: parameter.detach().cpu().clone() for name, parameter in context.model.named_parameters() if parameter.requires_grad}
    require(head_state and all(name.startswith("head.") for name in head_state), "checkpoint_not_head_only")
    atomic_torch(checkpoint_path, {"schema_version": SCHEMA + "_checkpoint", "job_id": args.job_id, "head_state": head_state, "claim_boundary": CLAIM})

    training_path = args.output_dir / "TRAINING_RECEIPT.json"
    atomic_json(training_path, receipt)
    step_path = args.output_dir / "STEP_EVIDENCE.jsonl"
    with step_path.open("w") as handle:
        for event in receipt["gradient_step_diagnostics"]:
            payload = dict(event)
            payload["finite_state"] = True
            payload["outer_test_truth_access_count"] = 0
            payload["outer_metrics_access_count"] = 0
            payload["v4_f_test32_access_count"] = 0
            handle.write(json.dumps(payload, sort_keys=True, allow_nan=False) + "\n")

    artifacts = {
        "training_receipt": {"path": training_path.name, "sha256": sha(training_path)},
        "step_evidence": {"path": step_path.name, "sha256": sha(step_path), "rows": expected_steps},
        "checkpoint": {"path": checkpoint_path.name, "sha256": sha(checkpoint_path)},
        "predictions": {"path": prediction_path.name, "sha256": sha(prediction_path), "rows": len(records)},
    }
    result = {
        "schema_version": SCHEMA,
        "status": "PASS_OPEN_INNER_CONTACT_ABLATION_CUDA_SMOKE",
        "claim_boundary": CLAIM,
        "job_id": args.job_id,
        "variant": args.variant,
        "integration_lane": args.integration_lane,
        "seed": args.seed,
        "rank_lambda": args.lambda_rank,
        "contact_ablation": {"marginal_weight": marginal_weight, "pair_weight": pair_weight},
        "outer_fold": 0,
        "inner_fold": 0,
        "fixed_epochs": 1,
        "optimizer_steps": expected_steps,
        "precision": "bf16",
        "physical_gpu": args.physical_gpu,
        "logical_device": args.device,
        "integration_freeze_sha256": INTEGRATION_FREEZE_SHA,
        "integration_trainer_sha256": INTEGRATION_TRAINER_SHA,
        "cuda_smoke_result_sha256": SMOKE_SHA,
        "execution_wrapper_launched": True,
        "execution_host": "node1",
        "trainer_receipt_remote_training_launched_semantics": (
            "False denotes the nonlaunching integration API contract; this outer SHA-bound "
            "wrapper performed the actual Node1 execution."
        ),
        "exact_min_violation_count": 0,
        "artifacts": artifacts,
        "outer_test_truth_access_count": 0,
        "outer_metrics_access_count": 0,
        "v4_f_test32_access_count": 0,
    }
    atomic_json(args.output_dir / "RESULT.json", result)
    del context
    gc.collect()
    torch.cuda.empty_cache()
    print(json.dumps({"status": result["status"], "job_id": args.job_id, "optimizer_steps": expected_steps}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
