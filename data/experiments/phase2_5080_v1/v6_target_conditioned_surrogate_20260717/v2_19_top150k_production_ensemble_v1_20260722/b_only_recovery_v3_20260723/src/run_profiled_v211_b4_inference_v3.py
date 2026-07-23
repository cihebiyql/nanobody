#!/usr/bin/env python3
"""Run the frozen V2.19 inference adapter with the exact V2.11 B4 profile.

This is intentionally narrower than adding the V2.11 schema to the generic
checkpoint allowlist.  The four checkpoint bytes, seeds, split, architecture,
state signature, and training RESULT provenance must all match the frozen
production profile before the generic adapter is allowed to deserialize the
heads for inference.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch


SCHEMA_VERSION = "pvrig_top150k_v211_b4_profile_validation_v3"
STATUS = "PASS_EXACT_V211_B4_CHECKPOINT_PROFILE"
CHECKPOINT_SCHEMA = "pvrig_v2_11_full10644_clean_attention_runner_v1"
LANE = "B_CLEAN_TARGET_ATTENTION"
SPLIT_ID = "v29_canonical_release_v1_joint_cdr3_D1"
BACKBONE_SHA256 = "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"
HEAD_CONFIG_SHA256 = "75ee344219fa5c2c96fcad45bef758e60e6d34efb1921436fcd0c9f18ce2af3e"
STATE_SIGNATURE_SHA256 = "421030fba897bf1b3229be39630a9e1f83f7a3f159536a4b47c4df96f7068f34"
EXPECTED_TENSOR_COUNT = 130
EXPECTED_PARAMETER_COUNT = 1_102_764
PROFILE_ID = "pvrig_v211_full10644_b4_exact_production_profile_v3"

EXPECTED_INPUT_BINDINGS = {
    "backbone_identity_file_sha256": BACKBONE_SHA256,
    "ortho_model_sha256": "26a193e7f854cdbce586c2fa89df947f0bd7218c3c675733c1724e7e7ee3c521",
    "ortho_trainer_sha256": "af93c39054a1a73568a68d498406fb3eddbffe1d688c93e16f59319148e285b0",
    "split_manifest_sha256": "9dc416dcf8694f321a5432ba8574f0229c03527af14926fcf2f43ee4211f07ed",
    "target_graph_pt_sha256": "59461f9d48e5995acd902ba8524caad5c779a3c8b54a5deee121f9c3be6adfbc",
    "target_graph_receipt_sha256": "b1823387b70375517b65848d873ff0e875396125ca5882ea384fabfcbd8880a9",
    "training_table_sha256": "46bc32276a574e21bb92d7e6672b18aa68323c778b4f65d2415a384144ab95c3",
}


class ProfileValidationError(RuntimeError):
    """Raised when any frozen B4 profile property drifts."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProfileValidationError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def state_signature(state: Mapping[str, Any]) -> tuple[str, int, int]:
    require(bool(state), "checkpoint_state_empty")
    entries: list[tuple[str, list[int], str]] = []
    parameters = 0
    for key, tensor in sorted(state.items()):
        require(isinstance(key, str) and isinstance(tensor, torch.Tensor), f"checkpoint_state_tensor_invalid:{key}")
        entries.append((key, list(tensor.shape), str(tensor.dtype)))
        parameters += tensor.numel()
    digest = hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode("utf-8")).hexdigest()
    return digest, len(entries), parameters


@dataclass(frozen=True)
class SeedProfile:
    seed: int
    checkpoint_sha256: str
    result_sha256: str


@dataclass(frozen=True)
class B4Profile:
    profile_id: str
    seeds: tuple[SeedProfile, ...]
    checkpoint_schema: str = CHECKPOINT_SCHEMA
    lane: str = LANE
    split_id: str = SPLIT_ID
    backbone_sha256: str = BACKBONE_SHA256
    head_config_sha256: str = HEAD_CONFIG_SHA256
    state_signature_sha256: str = STATE_SIGNATURE_SHA256
    tensor_count: int = EXPECTED_TENSOR_COUNT
    parameter_count: int = EXPECTED_PARAMETER_COUNT


PRODUCTION_PROFILE = B4Profile(
    profile_id=PROFILE_ID,
    seeds=(
        SeedProfile(43, "0a09ca095cda3eb0ba75582f9a0dcbfa2fd2e3007fe6733020b7a79b897c7723", "b5ffcfb10cf5e8bd578bc8db8cd975d09bf617c2dc96dba120fdc69461c79d20"),
        SeedProfile(917, "642984c4b2e07016fd1698b43fbb8851ce6f77fc6fd279e7eab9c9142746e9ca", "a798823bf23f59a1513e6c0ff8b114559846b3c8ee3785a4d5dea75f4a3863ee"),
        SeedProfile(1931, "0e8ab9b9b0d6ce07bd2fa12ed3118577c883a491e9b275ea672c2050bac311a5", "0b6455224f80dc802576fa0bbb5ca050d4bf4fa16e727b92795df75152f7539f"),
        SeedProfile(3253, "6a5ccdb459d0aa7d3126122ebfb2919228a0c1c529382fb1db4d40ab179e662f", "56f72a20f9cef1844c280a87ba4db59679a71e374268b520514787e197f817d2"),
    ),
)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_module(name: str, path: Path) -> Any:
    require(path.is_file() and not path.is_symlink(), f"base_inference_module_invalid:{path}")
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None, "base_inference_module_spec_invalid")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def _load_json(path: Path) -> Mapping[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"result_receipt_invalid:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, Mapping), f"result_receipt_not_object:{path}")
    return payload


def validate_exact_profile(
    checkpoint_paths: Sequence[Path],
    result_paths: Sequence[Path],
    profile: B4Profile = PRODUCTION_PROFILE,
) -> dict[str, Any]:
    expected_seeds = tuple(item.seed for item in profile.seeds)
    require(tuple(sorted(expected_seeds)) == expected_seeds, "profile_seed_order_invalid")
    require(len(checkpoint_paths) == len(result_paths) == len(profile.seeds) == 4, "b4_exact_four_required")
    require(len(set(checkpoint_paths)) == 4 and len(set(result_paths)) == 4, "b4_path_duplicate")
    validated: list[dict[str, Any]] = []
    seen_payload_seeds: set[int] = set()

    for checkpoint_path, result_path, expected in zip(checkpoint_paths, result_paths, profile.seeds):
        checkpoint_sha = sha256_file(checkpoint_path)
        result_sha = sha256_file(result_path)
        require(checkpoint_sha == expected.checkpoint_sha256, f"checkpoint_sha256_mismatch:seed{expected.seed}")
        require(result_sha == expected.result_sha256, f"result_sha256_mismatch:seed{expected.seed}")

        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        require(isinstance(checkpoint, Mapping), f"checkpoint_payload_invalid:seed{expected.seed}")
        require(checkpoint.get("schema_version") == profile.checkpoint_schema, f"checkpoint_schema_invalid:seed{expected.seed}")
        require(checkpoint.get("lane") == profile.lane, f"checkpoint_lane_invalid:seed{expected.seed}")
        require(checkpoint.get("backbone_identity_sha256") == profile.backbone_sha256, f"checkpoint_backbone_invalid:seed{expected.seed}")
        require(int(checkpoint.get("seed", -1)) == expected.seed, f"checkpoint_seed_invalid:seed{expected.seed}")
        require(str(checkpoint.get("split_id", "")) == profile.split_id, f"checkpoint_split_invalid:seed{expected.seed}")
        require(str(checkpoint.get("variant", "BASE")) == "BASE", f"checkpoint_variant_invalid:seed{expected.seed}")
        config = checkpoint.get("head_config")
        state = checkpoint.get("head_state_dict")
        require(isinstance(config, Mapping), f"checkpoint_config_invalid:seed{expected.seed}")
        require(isinstance(state, Mapping), f"checkpoint_state_invalid:seed{expected.seed}")
        require(canonical_sha256(dict(config)) == profile.head_config_sha256, f"checkpoint_config_sha256_mismatch:seed{expected.seed}")
        require(config.get("enable_contact_evidence") is False, f"checkpoint_contact_enabled:seed{expected.seed}")
        signature, tensors, parameters = state_signature(state)
        require(signature == profile.state_signature_sha256, f"checkpoint_state_signature_mismatch:seed{expected.seed}")
        require(tensors == profile.tensor_count, f"checkpoint_tensor_count_mismatch:seed{expected.seed}")
        require(parameters == profile.parameter_count, f"checkpoint_parameter_count_mismatch:seed{expected.seed}")

        result = _load_json(result_path)
        require(result.get("schema_version") == profile.checkpoint_schema, f"result_schema_invalid:seed{expected.seed}")
        require(result.get("status") == "PASS_FULL10644_CLEAN_ATTENTION_FIXED_EPOCH_TRAINING", f"result_status_invalid:seed{expected.seed}")
        require(result.get("lane") == profile.lane, f"result_lane_invalid:seed{expected.seed}")
        require(int(result.get("seed", -1)) == expected.seed, f"result_seed_invalid:seed{expected.seed}")
        require(result.get("backbone_identity_sha256") == profile.backbone_sha256, f"result_backbone_invalid:seed{expected.seed}")
        require(result.get("split", {}).get("split_id") == profile.split_id, f"result_split_invalid:seed{expected.seed}")
        require(result.get("frozen_test_access_count") == 0, f"result_frozen_test_access:seed{expected.seed}")
        require(result.get("exact_min_inference") is True, f"result_exact_min_invalid:seed{expected.seed}")
        require(result.get("outputs", {}).get("clean_attention_head_final.pt") == checkpoint_sha, f"result_checkpoint_hash_invalid:seed{expected.seed}")
        bindings = result.get("input_bindings")
        require(isinstance(bindings, Mapping), f"result_input_bindings_invalid:seed{expected.seed}")
        for key, value in EXPECTED_INPUT_BINDINGS.items():
            require(bindings.get(key) == value, f"result_input_binding_invalid:seed{expected.seed}:{key}")
        firewall = result.get("neural_input_firewall", {})
        for key in ("m2_input_count", "c2_input_count", "contact_input_count", "candidate_docking_pose_input_count", "candidate_id_input_count", "parent_id_input_count"):
            require(firewall.get(key) == 0, f"result_firewall_invalid:seed{expected.seed}:{key}")
        contact_role = result.get("training", {}).get("optimizer_parameter_roles", {}).get("contact", {})
        require(contact_role.get("parameter_values") == 0, f"result_contact_optimizer_values:seed{expected.seed}")
        seen_payload_seeds.add(expected.seed)
        validated.append({
            "seed": expected.seed,
            "checkpoint": {"path": str(checkpoint_path), "sha256": checkpoint_sha},
            "result": {"path": str(result_path), "sha256": result_sha},
            "schema_version": profile.checkpoint_schema,
            "split_id": profile.split_id,
            "variant": "BASE",
            "head_config_sha256": profile.head_config_sha256,
            "state_signature_sha256": profile.state_signature_sha256,
            "tensor_count": tensors,
            "parameter_count": parameters,
        })
    require(seen_payload_seeds == set(expected_seeds), "b4_seed_set_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "profile_id": profile.profile_id,
        "checkpoint_schema": profile.checkpoint_schema,
        "lane": profile.lane,
        "split_id": profile.split_id,
        "backbone_identity_sha256": profile.backbone_sha256,
        "head_config_sha256": profile.head_config_sha256,
        "state_signature_sha256": profile.state_signature_sha256,
        "checkpoints": validated,
        "truth_access": {"teacher_labels_opened": 0, "candidate_docking_pose_files_opened": 0, "frozen_test_access_count": 0},
    }


def infer_profiled(
    base_module: Any,
    base_args: argparse.Namespace,
    result_paths: Sequence[Path],
    profile_receipt: Path,
    profile: B4Profile = PRODUCTION_PROFILE,
) -> Mapping[str, Any]:
    require(not profile_receipt.exists(), "profile_receipt_exists")
    validation = validate_exact_profile(base_args.checkpoint, result_paths, profile)
    _atomic_json(profile_receipt, validation)
    accepted = set(base_module.ACCEPTED_CHECKPOINT_SCHEMAS)
    require(profile.checkpoint_schema not in accepted, "base_module_already_accepts_v211_schema")
    base_module.ACCEPTED_CHECKPOINT_SCHEMAS.add(profile.checkpoint_schema)
    try:
        result = base_module.infer(base_args)
    finally:
        base_module.ACCEPTED_CHECKPOINT_SCHEMAS.clear()
        base_module.ACCEPTED_CHECKPOINT_SCHEMAS.update(accepted)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    wrapper = argparse.ArgumentParser(add_help=False)
    wrapper.add_argument("--base-inference-module", type=Path, required=True)
    wrapper.add_argument("--result-receipt", type=Path, action="append", required=True)
    wrapper.add_argument("--profile-receipt", type=Path, required=True)
    wrapper_args, remaining = wrapper.parse_known_args(argv)
    base = _load_module("pvrig_v219_clean_attention_inference_for_v3", wrapper_args.base_inference_module)
    base_args = base.parser().parse_args(remaining)
    base.validate_args(base_args)
    result = infer_profiled(base, base_args, wrapper_args.result_receipt, wrapper_args.profile_receipt)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
