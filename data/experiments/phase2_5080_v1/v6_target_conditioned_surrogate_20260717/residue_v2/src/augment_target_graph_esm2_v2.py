#!/usr/bin/env python3
"""Append frozen ESM2-650M residue embeddings to the fixed PVRIG graphs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pathlib
import shutil
import tempfile
from typing import Any, Callable, Mapping, Sequence

import torch
from torch import Tensor, nn


SCHEMA_VERSION = "pvrig_v6_target_graphs_esm2_650m_v2"
RECEPTORS = ("8x6b", "9e6y")
BASE_FEATURE_DIM = 30
ESM2_HIDDEN_DIM = 1280
OUTPUT_NAME = "target_graphs_esm2_650m_v2.pt"
RECEIPT_NAME = "target_graphs_esm2_650m_v2.receipt.json"
CURRENT_NAME = "CURRENT.json"
SHA256SUMS_NAME = "SHA256SUMS"
MODEL_IDENTITY_FILES = (
    "config.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt",
)
GRAPH_FIELDS = {"node_features", "edge_index", "edge_features", "interface_mask", "hotspot_mask"}


class TargetPLMError(RuntimeError):
    """Fail-closed target-PLM augmentation error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TargetPLMError(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: pathlib.Path) -> dict[str, dict[str, str]]:
    require(path.is_file() and not path.is_symlink(), "target_manifest_invalid")
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, "target_manifest_header_missing")
        required = {"receptor", "pdb_id", "pvrig_chain", "sequence", "sequence_sha256", "node_count"}
        require(required <= set(reader.fieldnames), f"target_manifest_fields_missing:{sorted(required - set(reader.fieldnames))}")
        rows = list(reader)
    require(len(rows) == len(RECEPTORS), "target_manifest_row_count_invalid")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        receptor = row["receptor"].lower()
        require(receptor in RECEPTORS and receptor not in result, f"target_manifest_receptor_invalid:{receptor}")
        sequence = row["sequence"].strip().upper()
        require(hashlib.sha256(sequence.encode("ascii")).hexdigest() == row["sequence_sha256"], f"target_sequence_hash_mismatch:{receptor}")
        require(int(row["node_count"]) == len(sequence), f"target_sequence_node_count_mismatch:{receptor}")
        result[receptor] = dict(row)
    require(set(result) == set(RECEPTORS), "target_manifest_receptor_closure")
    return result


def _contains_forbidden_source_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in {"teacher_source", "source_id", "campaign_id"}
            or _contains_forbidden_source_key(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_source_key(item) for item in value)
    return False


def load_base_graphs(
    base_target_pt: pathlib.Path,
    target_manifest: pathlib.Path,
    base_receipt_path: pathlib.Path,
) -> tuple[dict[str, dict[str, Tensor]], dict[str, dict[str, str]], dict[str, Any]]:
    require(base_target_pt.is_file() and not base_target_pt.is_symlink(), "base_target_pt_invalid")
    require(base_receipt_path.is_file() and not base_receipt_path.is_symlink(), "base_target_receipt_invalid")
    receipt = json.loads(base_receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED", "base_target_receipt_status_invalid")
    require(receipt.get("node_feature_dim") == BASE_FEATURE_DIM, "base_target_feature_dim_invalid")
    require(receipt.get("outputs", {}).get(base_target_pt.name) == sha256_file(base_target_pt), "base_target_pt_hash_mismatch")
    manifest = _read_manifest(target_manifest)
    require(receipt.get("outputs", {}).get(target_manifest.name) == sha256_file(target_manifest), "base_target_manifest_hash_mismatch")
    payload = torch.load(base_target_pt, map_location="cpu", weights_only=True)
    if isinstance(payload, Mapping) and "target_graphs" in payload:
        payload = payload["target_graphs"]
    require(isinstance(payload, Mapping) and set(payload) == set(RECEPTORS), "base_target_receptor_closure")
    require(not _contains_forbidden_source_key(payload), "base_target_contains_source_feature")
    graphs: dict[str, dict[str, Tensor]] = {}
    for receptor in RECEPTORS:
        graph = payload[receptor]
        require(isinstance(graph, Mapping) and set(graph) == GRAPH_FIELDS, f"base_target_graph_fields:{receptor}")
        tensors = {name: graph[name].detach().cpu() for name in GRAPH_FIELDS}
        require(all(isinstance(value, Tensor) for value in tensors.values()), f"base_target_non_tensor:{receptor}")
        node_count = int(manifest[receptor]["node_count"])
        require(tensors["node_features"].shape == (node_count, BASE_FEATURE_DIM), f"base_target_node_shape:{receptor}")
        require(tensors["interface_mask"].shape == tensors["hotspot_mask"].shape == (node_count,), f"base_target_mask_shape:{receptor}")
        require(receipt["targets"][receptor]["sequence_sha256"] == manifest[receptor]["sequence_sha256"], f"base_target_receipt_sequence:{receptor}")
        require(receipt["targets"][receptor]["nodes"] == node_count, f"base_target_receipt_nodes:{receptor}")
        graphs[receptor] = tensors
    return graphs, manifest, receipt


def _tokenized(tokenizer: Any, text: str) -> Mapping[str, Any]:
    value = tokenizer(
        text,
        add_special_tokens=True,
        return_attention_mask=True,
        return_tensors="pt",
    )
    require(isinstance(value, Mapping) and "input_ids" in value, "tokenizer_output_invalid")
    return value


def exact_tokenize_sequence(tokenizer: Any, sequence: str) -> tuple[Tensor, Tensor, Tensor, str]:
    """Require one non-special token per observed residue and exact AA IDs."""

    sequence = sequence.strip().upper()
    require(sequence, "target_sequence_empty")
    attempts = (("raw", sequence), ("space_separated", " ".join(sequence)))
    accepted: list[tuple[Tensor, Tensor, Tensor, str]] = []
    residue_token_ids: dict[str, int] = {}
    for aa in sorted(set(sequence)):
        encoded = tokenizer(aa, add_special_tokens=False, return_attention_mask=False)
        ids = encoded["input_ids"] if isinstance(encoded, Mapping) else None
        if isinstance(ids, Tensor):
            ids = ids.flatten().tolist()
        require(isinstance(ids, Sequence) and len(ids) == 1, f"single_residue_tokenization_invalid:{aa}")
        residue_token_ids[aa] = int(ids[0])
    for mode, text in attempts:
        batch = _tokenized(tokenizer, text)
        input_ids = batch["input_ids"]
        attention_mask = batch.get("attention_mask", torch.ones_like(input_ids))
        if input_ids.ndim != 2 or input_ids.shape[0] != 1 or attention_mask.shape != input_ids.shape:
            continue
        ids = input_ids[0].tolist()
        if hasattr(tokenizer, "get_special_tokens_mask"):
            special = tokenizer.get_special_tokens_mask(ids, already_has_special_tokens=True)
        else:
            all_special_ids = getattr(tokenizer, "all_special_ids", None)
            require(all_special_ids is not None, "tokenizer_special_mask_unavailable")
            special_set = {int(value) for value in all_special_ids}
            special = [int(value in special_set) for value in ids]
        if len(special) != len(ids):
            continue
        positions = [
            index for index, (is_special, attended) in enumerate(zip(special, attention_mask[0].tolist()))
            if not is_special and attended
        ]
        if len(positions) != len(sequence):
            continue
        observed = [int(input_ids[0, position]) for position in positions]
        expected = [residue_token_ids[aa] for aa in sequence]
        if observed != expected:
            continue
        accepted.append((input_ids.long(), attention_mask.long(), torch.tensor(positions, dtype=torch.long), mode))
    require(accepted, "token_residue_alignment_failed")
    # Both forms may be accepted by an ESM tokenizer; they must produce exactly
    # the same token IDs and residue positions rather than silently diverging.
    reference = accepted[0]
    require(
        all(torch.equal(value[0], reference[0]) and torch.equal(value[2], reference[2]) for value in accepted),
        "tokenization_modes_disagree",
    )
    return reference


def backbone_hidden_states(model: nn.Module, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
    output = model(input_ids=input_ids, attention_mask=attention_mask)
    if isinstance(output, Mapping):
        states = output.get("last_hidden_state")
    else:
        states = getattr(output, "last_hidden_state", None)
    require(isinstance(states, Tensor), "backbone_missing_last_hidden_state")
    require(states.shape[:2] == input_ids.shape, "backbone_hidden_state_shape_invalid")
    return states


def embed_observed_sequence(
    tokenizer: Any,
    model: nn.Module,
    sequence: str,
    *,
    device: torch.device,
    expected_hidden_dim: int,
    inference_dtype: torch.dtype,
) -> tuple[Tensor, str]:
    input_ids, attention_mask, positions, tokenization_mode = exact_tokenize_sequence(tokenizer, sequence)
    input_ids = input_ids.to(device)
    attention_mask = attention_mask.to(device)
    positions = positions.to(device)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    autocast_enabled = inference_dtype == torch.bfloat16
    with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=inference_dtype, enabled=autocast_enabled):
        states = backbone_hidden_states(model, input_ids, attention_mask)
        residue_states = states[0].index_select(0, positions)
    require(residue_states.shape == (len(sequence), expected_hidden_dim), "plm_residue_embedding_shape_invalid")
    require(bool(torch.all(torch.isfinite(residue_states))), "plm_residue_embedding_nonfinite")
    return residue_states.detach().to(device="cpu", dtype=torch.float32).contiguous(), tokenization_mode


def augment_graphs(
    base_graphs: Mapping[str, Mapping[str, Tensor]],
    manifest: Mapping[str, Mapping[str, str]],
    tokenizer: Any,
    model: nn.Module,
    *,
    device: torch.device,
    expected_hidden_dim: int = ESM2_HIDDEN_DIM,
    inference_dtype: torch.dtype = torch.bfloat16,
) -> tuple[dict[str, dict[str, Tensor]], dict[str, dict[str, Any]]]:
    require(set(base_graphs) == set(manifest) == set(RECEPTORS), "augmentation_receptor_closure")
    augmented: dict[str, dict[str, Tensor]] = {}
    audit: dict[str, dict[str, Any]] = {}
    for receptor in RECEPTORS:
        sequence = manifest[receptor]["sequence"]
        embeddings, tokenization_mode = embed_observed_sequence(
            tokenizer, model, sequence, device=device,
            expected_hidden_dim=expected_hidden_dim, inference_dtype=inference_dtype,
        )
        base = base_graphs[receptor]
        require(base["node_features"].shape == (len(sequence), BASE_FEATURE_DIM), f"base_features_before_concat:{receptor}")
        graph = {
            "node_features": torch.cat((base["node_features"].float(), embeddings), dim=1).contiguous(),
            "edge_index": base["edge_index"].clone(),
            "edge_features": base["edge_features"].clone(),
            "interface_mask": base["interface_mask"].clone(),
            "hotspot_mask": base["hotspot_mask"].clone(),
        }
        require(graph["node_features"].shape == (len(sequence), BASE_FEATURE_DIM + expected_hidden_dim), f"augmented_feature_shape:{receptor}")
        augmented[receptor] = graph
        audit[receptor] = {
            "sequence_sha256": manifest[receptor]["sequence_sha256"],
            "nodes": len(sequence),
            "tokenization_mode": tokenization_mode,
            "embedding_dim": expected_hidden_dim,
            "embedding_dtype_stored": "float32",
            "embedding_sha256": hashlib.sha256(embeddings.numpy().tobytes(order="C")).hexdigest(),
        }
    require(not _contains_forbidden_source_key(augmented), "augmented_target_contains_source_feature")
    return augmented, audit


def load_frozen_esm2(
    model_path: pathlib.Path,
    model_identity_file: pathlib.Path,
    *,
    device: torch.device,
    expected_hidden_dim: int = ESM2_HIDDEN_DIM,
) -> tuple[Any, nn.Module, dict[str, Any]]:
    require(model_path.is_dir() and not model_path.is_symlink(), "local_model_directory_required")
    resolved_model = model_path.resolve(strict=True)
    resolved_identity = model_identity_file.resolve(strict=True)
    require(resolved_identity.is_file() and resolved_identity.is_relative_to(resolved_model), "model_identity_outside_snapshot")
    require(device.type == "cuda", "production_esm2_requires_cuda")
    require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), "cuda_bf16_required")
    # Enforce offline mode before importing or calling Transformers.
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    try:
        from transformers import AutoModel, AutoTokenizer
    except ImportError as error:
        raise TargetPLMError("transformers_required") from error
    tokenizer = AutoTokenizer.from_pretrained(
        str(resolved_model), local_files_only=True, trust_remote_code=False,
    )
    model = AutoModel.from_pretrained(
        str(resolved_model), local_files_only=True, trust_remote_code=False,
        torch_dtype=torch.bfloat16,
    ).to(device)
    hidden = getattr(model.config, "hidden_size", None) or getattr(model.config, "d_model", None)
    require(hidden == expected_hidden_dim, f"esm2_hidden_dim_mismatch:{hidden}")
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    snapshot_files = {}
    for filename in MODEL_IDENTITY_FILES:
        path = resolved_model / filename
        if path.is_file():
            snapshot_files[filename] = sha256_file(path)
    identity = {
        "snapshot_path": str(resolved_model),
        "model_identity_path": str(resolved_identity),
        "model_identity_sha256": sha256_file(resolved_identity),
        "snapshot_metadata_hashes": snapshot_files,
        "hidden_dim": hidden,
        "torch_dtype_loaded": "bfloat16",
        "local_files_only": True,
        "trust_remote_code": False,
        "network_disabled": True,
    }
    return tokenizer, model, identity


def write_content_addressed_delivery(
    *,
    augmented_graphs: Mapping[str, Mapping[str, Tensor]],
    audit: Mapping[str, Mapping[str, Any]],
    output_dir: pathlib.Path,
    input_hashes: Mapping[str, str],
    model_identity: Mapping[str, Any],
    implementation_path: pathlib.Path,
) -> dict[str, Any]:
    require(not output_dir.exists(), f"output_dir_already_exists:{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        artifact_temp = staging / OUTPUT_NAME
        torch.save({"target_graphs": dict(augmented_graphs)}, artifact_temp)
        artifact_sha = sha256_file(artifact_temp)
        artifact_dir = staging / "by_sha256" / artifact_sha
        artifact_dir.mkdir(parents=True)
        artifact_path = artifact_dir / OUTPUT_NAME
        os.replace(artifact_temp, artifact_path)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_TARGET_GRAPHS_ESM2_650M_AUGMENTED",
            "claim_boundary": "Frozen label-free PVRIG target representation augmentation only; no candidate Docking pose, teacher source, binding, affinity, or experimental blocking truth.",
            "input_hashes": dict(input_hashes),
            "implementation_sha256": sha256_file(implementation_path),
            "model_identity": dict(model_identity),
            "inference": {
                "dtype": "bfloat16",
                "stored_dtype": "float32",
                "base_feature_dim": BASE_FEATURE_DIM,
                "plm_feature_dim": next(iter(audit.values()))["embedding_dim"],
                "augmented_feature_dim": next(iter(augmented_graphs.values()))["node_features"].shape[1],
                "network_access": "disabled",
            },
            "targets": dict(audit),
            "output": {
                "relative_path": str(artifact_path.relative_to(staging)),
                "sha256": artifact_sha,
                "bytes": artifact_path.stat().st_size,
            },
            "sealed_boundary": {
                "teacher_source_is_model_feature": False,
                "candidate_docking_pose_files_opened": 0,
                "base_target_cache_mutated": False,
            },
        }
        receipt_path = artifact_dir / RECEIPT_NAME
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (artifact_dir / SHA256SUMS_NAME).write_text(
            f"{artifact_sha}  {OUTPUT_NAME}\n{sha256_file(receipt_path)}  {RECEIPT_NAME}\n",
            encoding="utf-8",
        )
        current = {
            "schema_version": SCHEMA_VERSION,
            "artifact_sha256": artifact_sha,
            "artifact_relative_path": str(artifact_path.relative_to(staging)),
            "receipt_relative_path": str(receipt_path.relative_to(staging)),
            "receipt_sha256": sha256_file(receipt_path),
        }
        (staging / CURRENT_NAME).write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(staging, output_dir)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def augment_target_delivery(
    *,
    base_target_pt: pathlib.Path,
    target_manifest: pathlib.Path,
    base_target_receipt: pathlib.Path,
    model_path: pathlib.Path,
    model_identity_file: pathlib.Path,
    output_dir: pathlib.Path,
    device: torch.device,
) -> dict[str, Any]:
    graphs, manifest, _ = load_base_graphs(base_target_pt, target_manifest, base_target_receipt)
    tokenizer, model, model_identity = load_frozen_esm2(
        model_path, model_identity_file, device=device,
    )
    augmented, audit = augment_graphs(
        graphs, manifest, tokenizer, model, device=device,
        expected_hidden_dim=ESM2_HIDDEN_DIM, inference_dtype=torch.bfloat16,
    )
    return write_content_addressed_delivery(
        augmented_graphs=augmented,
        audit=audit,
        output_dir=output_dir,
        input_hashes={
            "base_target_pt": sha256_file(base_target_pt),
            "target_manifest": sha256_file(target_manifest),
            "base_target_receipt": sha256_file(base_target_receipt),
            "model_identity_file": sha256_file(model_identity_file),
        },
        model_identity=model_identity,
        implementation_path=pathlib.Path(__file__),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-target-pt", required=True, type=pathlib.Path)
    parser.add_argument("--target-manifest", required=True, type=pathlib.Path)
    parser.add_argument("--base-target-receipt", required=True, type=pathlib.Path)
    parser.add_argument("--model-path", required=True, type=pathlib.Path)
    parser.add_argument("--model-identity-file", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    receipt = augment_target_delivery(
        base_target_pt=args.base_target_pt,
        target_manifest=args.target_manifest,
        base_target_receipt=args.base_target_receipt,
        model_path=args.model_path,
        model_identity_file=args.model_identity_file,
        output_dir=args.output_dir,
        device=torch.device(args.device),
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
