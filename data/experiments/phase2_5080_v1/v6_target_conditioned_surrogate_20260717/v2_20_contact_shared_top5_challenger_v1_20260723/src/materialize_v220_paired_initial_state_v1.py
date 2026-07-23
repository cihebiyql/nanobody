#!/usr/bin/env python3
"""Materialize byte-identical V2.20 lane-E *head* states for paired folds.

This module deliberately stops before optimizer construction or training.  A
single seed-43 head checkpoint is serialized once and copied byte-for-byte to
each outer fold.  The frozen ESM2 backbone is never serialized into this
checkpoint.  Its externally verified artifact identity and its in-memory
canonical state hash are bound separately, so head-only storage cannot silently
pair with a different backbone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import struct
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import torch
from torch import nn


SCHEMA_VERSION = "pvrig.v220.paired_initial_head_state.v2"
LANE_E = "E_DECOUPLED_CONTACT"
CONTACT_ENCODER_GRADIENT = "shared"
INITIALIZATION_SEED = 43
DEFAULT_FOLDS = tuple(range(5))
REQUIRED_ROLES = ("shared_encoder", "attention_scalar", "contact")
STATE_MAGIC = b"PVRIG_V220_PAIRED_HEAD_STATE_V2\n"
HEAD_PREFIX = "head."
SHARED_PREFIXES = (
    "head.aa_embedding",
    "head.region_embedding",
    "head.vhh_graph_encoder",
    "head.target_graph_encoder",
    "head.conformer_embedding",
    "head.shared_encoder",
)
SCALAR_PREFIXES = (
    "head.attention_interaction",
    "head.condition_fusion",
    "head.scalar_head",
    "head.attention_scalar",
)
CONTACT_PREFIXES = (
    "head.contact_interaction",
    "head.contact_calibration",
    "head.contact",
)


class PairedInitialStateError(RuntimeError):
    """Raised when the frozen paired-initialization contract is violated."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PairedInitialStateError(message)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tensor_bytes(tensor: torch.Tensor) -> bytes:
    cpu = tensor.detach().cpu().contiguous()
    if cpu.numel() == 0:
        return b""
    return cpu.view(torch.uint8).numpy().tobytes(order="C")


def tensor_record(name: str, tensor: torch.Tensor) -> dict[str, Any]:
    _require(torch.is_tensor(tensor), f"state entry is not a tensor: {name}")
    return {
        "name": name,
        "dtype": str(tensor.dtype),
        "shape": list(tensor.shape),
        "tensor_sha256": _sha256_bytes(_tensor_bytes(tensor)),
    }


def canonical_state_sha256(
    state: Mapping[str, torch.Tensor], names: Sequence[str] | None = None
) -> str:
    selected = sorted(state) if names is None else sorted(names)
    _require(len(selected) == len(set(selected)), "duplicate state names")
    missing = [name for name in selected if name not in state]
    _require(not missing, f"missing state entries: {missing}")
    records = [tensor_record(name, state[name]) for name in selected]
    return _sha256_bytes(_canonical_json_bytes(records))


def parameter_order_sha256(model: nn.Module) -> str:
    records = [
        {
            "name": name,
            "dtype": str(parameter.dtype),
            "shape": list(parameter.shape),
            "requires_grad": bool(parameter.requires_grad),
        }
        for name, parameter in model.named_parameters()
        if name.startswith(HEAD_PREFIX)
    ]
    return _sha256_bytes(_canonical_json_bytes(records))


def _head_state(model: nn.Module) -> dict[str, torch.Tensor]:
    state = {
        name: tensor
        for name, tensor in model.state_dict().items()
        if name.startswith(HEAD_PREFIX)
    }
    _require(state, "model head state is empty")
    expected = {f"{HEAD_PREFIX}{name}" for name in model.head.state_dict()}
    _require(set(state) == expected, "model head state key closure failed")
    return state


def _validate_sha256(value: str, label: str) -> str:
    _require(isinstance(value, str), f"{label} must be a string")
    normalized = value.lower()
    _require(
        len(normalized) == 64
        and all(character in "0123456789abcdef" for character in normalized),
        f"{label} must be a lowercase-compatible SHA256",
    )
    return normalized


def backbone_binding(
    model: nn.Module, backbone_identity_sha256: str
) -> dict[str, Any]:
    """Bind, but never serialize, the frozen backbone used with the head.

    ``backbone_identity_sha256`` is the already verified model-artifact digest
    returned by the frozen V2.13 backbone loader.  The canonical in-memory state
    digest provides an independent runtime check that C0/C1 loaded the same
    tensors, while the lightweight parameter contract makes architecture drift
    explicit.
    """

    identity = _validate_sha256(
        backbone_identity_sha256, "backbone_identity_sha256"
    )
    backbone = getattr(model, "backbone", None)
    _require(isinstance(backbone, nn.Module), "model must expose model.backbone")
    parameters = list(backbone.named_parameters())
    _require(parameters, "model backbone parameters are empty")
    _require(
        all(not parameter.requires_grad for _, parameter in parameters),
        "paired-state backbone must be fully frozen",
    )
    state = backbone.state_dict()
    _require(state, "model backbone state is empty")
    contract = [
        {
            "name": name,
            "dtype": str(tensor.dtype),
            "shape": list(tensor.shape),
        }
        for name, tensor in sorted(state.items())
    ]
    return {
        "artifact_identity_sha256": identity,
        "runtime_state_sha256": canonical_state_sha256(state),
        "state_contract_sha256": _sha256_bytes(_canonical_json_bytes(contract)),
        "module_type": f"{type(backbone).__module__}.{type(backbone).__qualname__}",
        "parameter_tensors": len(parameters),
        "state_tensors": len(state),
        "all_parameters_frozen": True,
        "serialized_in_checkpoint": False,
    }


def seed_everything(seed: int = INITIALIZATION_SEED) -> None:
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def validate_lane_e_shared(
    model: nn.Module,
    *,
    lane: str = LANE_E,
    contact_encoder_gradient: str = CONTACT_ENCODER_GRADIENT,
) -> None:
    _require(lane == LANE_E, f"only {LANE_E} is allowed, got {lane}")
    _require(
        contact_encoder_gradient == CONTACT_ENCODER_GRADIENT,
        "V2.20 requires shared contact gradients",
    )
    head = getattr(model, "head", None)
    _require(head is not None, "model must expose model.head")
    config = getattr(head, "config", None)
    if config is not None and hasattr(config, "enable_contact_evidence"):
        _require(bool(config.enable_contact_evidence), "contact evidence is disabled")
    if config is not None and hasattr(config, "contact_encoder_gradient"):
        _require(
            config.contact_encoder_gradient == CONTACT_ENCODER_GRADIENT,
            "model config is not shared-contact lane-E",
        )
    backbone = getattr(model, "backbone", None)
    _require(isinstance(backbone, nn.Module), "model must expose model.backbone")
    _require(
        all(not parameter.requires_grad for parameter in backbone.parameters()),
        "paired-state backbone must be fully frozen",
    )


def validate_parameter_roles(
    model: nn.Module,
    role_parameters: Mapping[str, Sequence[tuple[str, nn.Parameter]]],
) -> dict[str, list[str]]:
    _require(
        set(role_parameters) == set(REQUIRED_ROLES),
        f"roles must be exactly {REQUIRED_ROLES}",
    )
    trainable = {
        name: parameter
        for name, parameter in model.named_parameters()
        if parameter.requires_grad
    }
    assigned: dict[str, str] = {}
    normalized: dict[str, list[str]] = {}
    for role in REQUIRED_ROLES:
        entries = list(role_parameters[role])
        _require(entries, f"empty parameter role: {role}")
        normalized[role] = []
        for name, parameter in entries:
            _require(name in trainable, f"unknown/non-trainable parameter {name}")
            _require(
                trainable[name] is parameter,
                f"parameter object does not match model.named_parameters: {name}",
            )
            _require(name not in assigned, f"parameter assigned twice: {name}")
            assigned[name] = role
            normalized[role].append(name)
    missing = sorted(set(trainable) - set(assigned))
    extra = sorted(set(assigned) - set(trainable))
    _require(not missing, f"unassigned trainable parameters: {missing}")
    _require(not extra, f"extraneous assigned parameters: {extra}")
    return normalized


def infer_parameter_roles(model: nn.Module) -> dict[str, list[tuple[str, nn.Parameter]]]:
    """Infer the frozen lane-E role partition from audited parameter prefixes."""

    roles: dict[str, list[tuple[str, nn.Parameter]]] = {
        role: [] for role in REQUIRED_ROLES
    }
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        matches = []
        if name.startswith(SHARED_PREFIXES):
            matches.append("shared_encoder")
        if name.startswith(SCALAR_PREFIXES):
            matches.append("attention_scalar")
        if name.startswith(CONTACT_PREFIXES):
            matches.append("contact")
        _require(len(matches) == 1, f"cannot uniquely classify trainable parameter: {name}")
        roles[matches[0]].append((name, parameter))
    validate_parameter_roles(model, roles)
    return roles


def initialization_hashes(
    model: nn.Module,
    role_names: Mapping[str, Sequence[str]],
    backbone_identity_sha256: str,
    *,
    precomputed_backbone_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = _head_state(model)
    shared_names = list(role_names["shared_encoder"])
    scalar_names = shared_names + list(role_names["attention_scalar"])
    contact_names = list(role_names["contact"])
    role_order_hashes = {
        role: _sha256_bytes(_canonical_json_bytes(list(role_names[role])))
        for role in REQUIRED_ROLES
    }
    head_sha256 = canonical_state_sha256(state)
    binding = (
        dict(precomputed_backbone_binding)
        if precomputed_backbone_binding is not None
        else backbone_binding(model, backbone_identity_sha256)
    )
    _require(
        binding.get("artifact_identity_sha256")
        == _validate_sha256(
            backbone_identity_sha256, "backbone_identity_sha256"
        ),
        "precomputed backbone identity mismatch",
    )
    return {
        # Legacy key retained for runner/receipt compatibility.  From schema v2
        # onward its explicit scope is model.head, not the frozen backbone.
        "full_state_sha256": head_sha256,
        "head_state_sha256": head_sha256,
        "scalar_state_sha256": canonical_state_sha256(state, scalar_names),
        "shared_state_sha256": canonical_state_sha256(state, shared_names),
        "contact_state_sha256": canonical_state_sha256(state, contact_names),
        "parameter_order_sha256": parameter_order_sha256(model),
        "head_parameter_order_sha256": parameter_order_sha256(model),
        "role_parameter_order_sha256": role_order_hashes,
        "backbone_identity_sha256": binding["artifact_identity_sha256"],
        "backbone_runtime_state_sha256": binding["runtime_state_sha256"],
        "backbone_state_contract_sha256": binding["state_contract_sha256"],
    }


def state_hashes(
    model: nn.Module,
    backbone_identity_sha256: str,
    *,
    precomputed_backbone_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Runner-facing state hash API using the frozen lane-E role prefixes."""

    validate_lane_e_shared(model)
    role_entries = infer_parameter_roles(model)
    role_names = {
        role: [name for name, _ in role_entries[role]] for role in REQUIRED_ROLES
    }
    return initialization_hashes(
        model,
        role_names,
        backbone_identity_sha256,
        precomputed_backbone_binding=precomputed_backbone_binding,
    )


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _encode_checkpoint(payload: Mapping[str, Any]) -> bytes:
    state = payload.get("head_state_dict")
    _require(isinstance(state, Mapping), "checkpoint head_state_dict is missing")
    binary = bytearray()
    entries = []
    for name in sorted(state):
        tensor = state[name]
        raw = _tensor_bytes(tensor)
        entries.append(
            {
                "name": name,
                "dtype": str(tensor.dtype),
                "shape": list(tensor.shape),
                "offset": len(binary),
                "nbytes": len(raw),
            }
        )
        binary.extend(raw)
    header = {
        key: value for key, value in payload.items() if key != "head_state_dict"
    }
    header["head_state_entries"] = entries
    header_bytes = _canonical_json_bytes(header)
    return STATE_MAGIC + struct.pack("<Q", len(header_bytes)) + header_bytes + bytes(binary)


def _decode_checkpoint(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    _require(payload.startswith(STATE_MAGIC), "invalid paired-state magic")
    cursor = len(STATE_MAGIC)
    _require(len(payload) >= cursor + 8, "truncated paired-state header")
    header_size = struct.unpack("<Q", payload[cursor : cursor + 8])[0]
    cursor += 8
    _require(len(payload) >= cursor + header_size, "truncated paired-state metadata")
    header = json.loads(payload[cursor : cursor + header_size])
    binary = payload[cursor + header_size :]
    entries = header.pop("head_state_entries", None)
    _require(isinstance(entries, list), "missing paired-state tensor index")
    state: dict[str, torch.Tensor] = {}
    for entry in entries:
        name = entry["name"]
        dtype_name = entry["dtype"]
        _require(dtype_name.startswith("torch."), f"invalid dtype: {dtype_name}")
        dtype = getattr(torch, dtype_name.split(".", 1)[1], None)
        _require(isinstance(dtype, torch.dtype), f"unsupported dtype: {dtype_name}")
        offset = int(entry["offset"])
        nbytes = int(entry["nbytes"])
        _require(0 <= offset <= len(binary), f"invalid tensor offset: {name}")
        _require(offset + nbytes <= len(binary), f"truncated tensor bytes: {name}")
        shape = tuple(int(value) for value in entry["shape"])
        if nbytes == 0:
            tensor = torch.empty(shape, dtype=dtype)
        else:
            buffer = bytearray(binary[offset : offset + nbytes])
            tensor = torch.frombuffer(buffer, dtype=torch.uint8).clone().view(dtype)
            tensor = tensor.reshape(shape)
        state[name] = tensor
    header["head_state_dict"] = state
    return header


def _atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        # A small canonical container avoids path names, pickle storage IDs,
        # ZIP timestamps, and other non-tensor serialization nondeterminism.
        temporary.write_bytes(_encode_checkpoint(payload))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def verify_external_checkpoint_binding(
    path: Path,
    receipt_path: Path,
    *,
    expected_checkpoint_sha256: str,
    expected_receipt_sha256: str,
) -> dict[str, Any]:
    """Verify externally frozen bytes before trusting checkpoint metadata.

    The expected digests must come from the implementation freeze/launcher,
    never from the checkpoint or its sidecar.  The sidecar is then checked for
    semantic closure with those externally supplied bytes.
    """

    path = Path(path)
    receipt_path = Path(receipt_path)
    expected_checkpoint = _validate_sha256(
        expected_checkpoint_sha256, "expected_checkpoint_sha256"
    )
    expected_receipt = _validate_sha256(
        expected_receipt_sha256, "expected_receipt_sha256"
    )
    _require(path.is_file() and not path.is_symlink(), f"invalid initial state: {path}")
    _require(
        receipt_path.is_file() and not receipt_path.is_symlink(),
        f"invalid initial state receipt: {receipt_path}",
    )
    actual_checkpoint = file_sha256(path)
    _require(
        actual_checkpoint == expected_checkpoint,
        "externally frozen checkpoint SHA256 mismatch",
    )
    actual_receipt = file_sha256(receipt_path)
    _require(
        actual_receipt == expected_receipt,
        "externally frozen receipt SHA256 mismatch",
    )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PairedInitialStateError("invalid external initial state receipt") from error
    _require(isinstance(receipt, dict), "external initial state receipt must be an object")
    _require(receipt.get("schema_version") == SCHEMA_VERSION, "receipt schema mismatch")
    _require(
        receipt.get("status")
        in {
            "PAIRED_INITIAL_STATE_SAVED_NO_TRAINING",
            "PAIRED_INITIAL_STATE_READY_NO_TRAINING",
        },
        "receipt status mismatch",
    )
    _require(
        receipt.get("serialized_state_scope") == "model.head",
        "receipt serialized state scope mismatch",
    )
    _require(
        receipt.get("serialized_checkpoint_sha256") == actual_checkpoint,
        "receipt/checkpoint SHA256 mismatch",
    )
    receipt_checkpoint = receipt.get("checkpoint")
    _require(isinstance(receipt_checkpoint, str), "receipt checkpoint path missing")
    _require(
        Path(receipt_checkpoint).resolve() == path.resolve(),
        "receipt checkpoint path mismatch",
    )
    return receipt


def save_paired_initial_state(
    path: Path,
    model: nn.Module,
    fold_id: int,
    seed: int,
    *,
    backbone_identity_sha256: str,
) -> dict[str, Any]:
    """Save a fold initial state and a fold-specific sidecar receipt.

    ``fold_id`` is intentionally kept out of the tensor checkpoint payload, so
    models with identical state produce the same serialized-state contract.
    Fold provenance is written to ``<path>.receipt.json``.
    """

    path = Path(path)
    _require(seed == INITIALIZATION_SEED, "V2.20 initialization seed must be 43")
    _require(isinstance(fold_id, int) and fold_id >= 0, "invalid fold_id")
    _require(not path.exists(), f"refusing to overwrite {path}")
    receipt_path = Path(f"{path}.receipt.json")
    _require(not receipt_path.exists(), f"refusing to overwrite {receipt_path}")
    validate_lane_e_shared(model)
    binding = backbone_binding(model, backbone_identity_sha256)
    hashes = state_hashes(
        model,
        backbone_identity_sha256,
        precomputed_backbone_binding=binding,
    )
    checkpoint = {
        "schema_version": SCHEMA_VERSION,
        "lane": LANE_E,
        "contact_encoder_gradient": CONTACT_ENCODER_GRADIENT,
        "initialization_seed": seed,
        "serialized_state_scope": "model.head",
        "backbone_binding": binding,
        "head_state_dict": {
            name: tensor.detach().cpu().clone()
            for name, tensor in _head_state(model).items()
        },
        "hashes": hashes,
    }
    _atomic_torch_save(path, checkpoint)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "PAIRED_INITIAL_STATE_SAVED_NO_TRAINING",
        "fold_id": fold_id,
        "initialization_seed": seed,
        "checkpoint": str(path),
        "serialized_checkpoint_sha256": file_sha256(path),
        "serialized_state_scope": "model.head",
        "backbone_binding": binding,
        "hashes": hashes,
    }
    _atomic_json(receipt_path, receipt)
    return receipt


def load_and_verify_initial_state(
    path: Path,
    model: nn.Module,
    *,
    backbone_identity_sha256: str,
    receipt_path: Path,
    expected_checkpoint_sha256: str,
    expected_receipt_sha256: str,
) -> dict[str, Any]:
    """Strictly load a saved initial head state after external hash closure."""

    path = Path(path)
    external_receipt = verify_external_checkpoint_binding(
        path,
        receipt_path,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_receipt_sha256=expected_receipt_sha256,
    )
    checkpoint = _decode_checkpoint(path)
    _require(isinstance(checkpoint, dict), "invalid checkpoint payload")
    _require(checkpoint.get("schema_version") == SCHEMA_VERSION, "schema mismatch")
    _require(checkpoint.get("lane") == LANE_E, "lane mismatch")
    _require(
        checkpoint.get("contact_encoder_gradient") == CONTACT_ENCODER_GRADIENT,
        "contact gradient mode mismatch",
    )
    _require(
        checkpoint.get("initialization_seed") == INITIALIZATION_SEED,
        "initialization seed mismatch",
    )
    _require(
        checkpoint.get("serialized_state_scope") == "model.head",
        "serialized state scope mismatch",
    )
    current_backbone = backbone_binding(model, backbone_identity_sha256)
    _require(
        checkpoint.get("backbone_binding") == current_backbone,
        "backbone binding mismatch",
    )
    _require(
        external_receipt.get("backbone_binding") == current_backbone,
        "receipt backbone binding mismatch",
    )
    expected_hashes = checkpoint.get("hashes")
    _require(isinstance(expected_hashes, dict), "missing checkpoint hashes")
    _require(
        external_receipt.get("hashes") == expected_hashes,
        "receipt/checkpoint hashes mismatch",
    )
    state = checkpoint.get("head_state_dict")
    _require(isinstance(state, dict), "missing checkpoint head_state_dict")
    _require(set(state) == set(_head_state(model)), "head state key mismatch")
    _require(
        canonical_state_sha256(state) == expected_hashes.get("head_state_sha256"),
        "checkpoint head tensor hash mismatch before load",
    )
    _require(
        expected_hashes.get("full_state_sha256")
        == expected_hashes.get("head_state_sha256"),
        "legacy full/head state hash alias mismatch",
    )
    relative_state = {
        name[len(HEAD_PREFIX) :]: tensor for name, tensor in state.items()
    }
    model.head.load_state_dict(relative_state, strict=True)
    actual_hashes = state_hashes(
        model,
        backbone_identity_sha256,
        precomputed_backbone_binding=current_backbone,
    )
    _require(actual_hashes == expected_hashes, "model hashes mismatch after load")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_INITIAL_STATE_LOADED_AND_VERIFIED",
        "checkpoint": str(path),
        "receipt": str(receipt_path),
        "serialized_checkpoint_sha256": file_sha256(path),
        "receipt_sha256": file_sha256(receipt_path),
        "external_hash_binding_verified": True,
        "serialized_state_scope": "model.head",
        "backbone_binding": current_backbone,
        "hashes": actual_hashes,
        "training_started": False,
    }


def materialize_paired_initial_states(
    *,
    model_factory: Callable[[], nn.Module],
    role_resolver: Callable[
        [nn.Module], Mapping[str, Sequence[tuple[str, nn.Parameter]]]
    ],
    output_dir: Path,
    folds: Sequence[int] = DEFAULT_FOLDS,
    seed: int = INITIALIZATION_SEED,
    lane: str = LANE_E,
    contact_encoder_gradient: str = CONTACT_ENCODER_GRADIENT,
    backbone_identity_sha256: str,
) -> dict[str, Any]:
    """Create a single serialized seed state and byte-identical fold copies."""

    output_dir = Path(output_dir)
    fold_ids = list(folds)
    _require(fold_ids, "at least one fold is required")
    _require(len(fold_ids) == len(set(fold_ids)), "duplicate fold identifiers")
    _require(seed == INITIALIZATION_SEED, "V2.20 initialization seed must be 43")
    _require(not output_dir.exists(), f"refusing to overwrite {output_dir}")
    output_dir.mkdir(parents=True)

    try:
        seed_everything(seed)
        model = model_factory()
        validate_lane_e_shared(
            model, lane=lane, contact_encoder_gradient=contact_encoder_gradient
        )
        role_names = validate_parameter_roles(model, role_resolver(model))
        binding = backbone_binding(model, backbone_identity_sha256)
        hashes = initialization_hashes(
            model,
            role_names,
            backbone_identity_sha256,
            precomputed_backbone_binding=binding,
        )
        cpu_head_state = {
            name: tensor.detach().cpu().clone()
            for name, tensor in _head_state(model).items()
        }
        checkpoint = {
            "schema_version": SCHEMA_VERSION,
            "lane": lane,
            "contact_encoder_gradient": contact_encoder_gradient,
            "initialization_seed": seed,
            "serialized_state_scope": "model.head",
            "backbone_binding": binding,
            "head_state_dict": cpu_head_state,
            "role_parameter_names": role_names,
            "hashes": hashes,
        }
        master = output_dir / "paired_initial_state_seed43.pt"
        _atomic_torch_save(master, checkpoint)
        serialized_sha256 = file_sha256(master)

        fold_records = []
        for fold in fold_ids:
            fold_dir = output_dir / f"fold_{fold}"
            checkpoint_path = fold_dir / "initial_state_seed43.pt"
            _atomic_copy(master, checkpoint_path)
            copied_sha256 = file_sha256(checkpoint_path)
            _require(
                copied_sha256 == serialized_sha256,
                f"serialized state mismatch for fold {fold}",
            )
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "status": "PAIRED_INITIAL_STATE_READY_NO_TRAINING",
                "fold": fold,
                "lane": lane,
                "contact_encoder_gradient": contact_encoder_gradient,
                "initialization_seed": seed,
                "checkpoint": str(checkpoint_path),
                "serialized_checkpoint_sha256": copied_sha256,
                "serialized_state_scope": "model.head",
                "backbone_binding": binding,
                "hashes": hashes,
            }
            _atomic_json(fold_dir / "INITIAL_STATE_RECEIPT.json", receipt)
            fold_records.append(receipt)

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_PAIRED_INITIAL_STATE_MATERIALIZED_NO_TRAINING",
            "lane": lane,
            "contact_encoder_gradient": contact_encoder_gradient,
            "initialization_seed": seed,
            "folds": fold_ids,
            "master_checkpoint": str(master),
            "serialized_checkpoint_sha256": serialized_sha256,
            "serialized_state_scope": "model.head",
            "backbone_binding": binding,
            "all_fold_serializations_identical": True,
            "hashes": hashes,
            "fold_records": fold_records,
        }
        _atomic_json(output_dir / "PAIRED_INITIAL_STATE_MANIFEST.json", manifest)
        return manifest
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-contract", action="store_true")
    args = parser.parse_args()
    if not args.print_contract:
        parser.error(
            "This reusable module requires a repository model_factory; "
            "import materialize_paired_initial_states instead."
        )
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "lane": LANE_E,
                "contact_encoder_gradient": CONTACT_ENCODER_GRADIENT,
                "initialization_seed": INITIALIZATION_SEED,
                "folds": DEFAULT_FOLDS,
                "serialized_state_scope": "model.head",
                "backbone_serialized": False,
                "backbone_identity_sha256_required": True,
                "training_started": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
