#!/usr/bin/env python3
"""Build a resumable frozen VHHBERT/ESM2 embedding cache for V3."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd
import torch

from phase2_v3_contracts import physicochemical_features, sha256_file, sha256_text, write_csv_atomic, write_json_atomic

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_PREPARED = EXP_DIR / "prepared" / "phase2_v3_binding"
DEFAULT_SEQUENCE_MANIFEST = DEFAULT_PREPARED / "sequence_manifest_v3.csv"
DEFAULT_OUTPUT = DEFAULT_PREPARED / "embeddings"
DEFAULT_VHHBERT = DATA_ROOT / "datasets" / "25_vhh_models" / "VHHBERT"
DEFAULT_ESM2 = DATA_ROOT / "datasets" / "10_github_repos" / "NanoBind" / "models" / "esm2_t6_8M_UR50D"
DEFAULT_VHHBERT_STATE = DEFAULT_PREPARED / "vhhbert_roberta_encoder.pt"


@dataclass(frozen=True)
class EmbeddingConfig:
    backend: str
    vhhbert_model_path: str
    esm2_model_path: str
    vhhbert_model_sha256: str
    esm2_model_sha256: str
    vhhbert_dim: int
    esm2_dim: int
    physchem_dim: int
    max_esm_residues: int
    chunk_overlap: int
    pooling: str = "residue_mean_excluding_special_tokens"


def hash_model_directory(path: Path) -> str:
    files = [item for item in sorted(path.iterdir()) if item.is_file() and item.name != "tf_model.h5"]
    payload = [(item.name, sha256_file(item)) for item in files]
    return sha256_text(json.dumps(payload, separators=(",", ":")))


def chunk_sequence(sequence: str, max_residues: int, overlap: int = 0) -> list[str]:
    if max_residues <= 0 or overlap < 0 or overlap >= max_residues:
        raise ValueError("Invalid chunking configuration")
    if len(sequence) <= max_residues:
        return [sequence]
    stride = max_residues - overlap
    return [sequence[start : start + max_residues] for start in range(0, len(sequence), stride)]


def deterministic_hash_embedding(sequence: str, dim: int, salt: str) -> torch.Tensor:
    raw = bytearray()
    counter = 0
    while len(raw) < dim:
        raw.extend(hashlib.sha256(f"{salt}|{counter}|{sequence}".encode("utf-8")).digest())
        counter += 1
    values = torch.tensor(list(raw[:dim]), dtype=torch.float32)
    return (values - 127.5) / 127.5


def _discover_safetensors(package_dir: Path) -> Callable[[str, str], dict[str, torch.Tensor]]:
    try:
        from safetensors.torch import load_file

        return load_file
    except ImportError:
        if package_dir.is_dir():
            sys.path.insert(0, str(package_dir))
            from safetensors.torch import load_file

            return load_file
        raise RuntimeError(
            "VHHBERT conversion requires an existing safetensors package. "
            "Pass --safetensors-package-dir; no dependency is installed automatically."
        )


def ensure_vhhbert_state(model_path: Path, output_path: Path, package_dir: Path) -> dict[str, Any]:
    source_path = model_path / "model.safetensors"
    source_sha = sha256_file(source_path)
    if output_path.is_file():
        payload = torch.load(output_path, map_location="cpu", weights_only=False)
        if payload.get("source_sha256") != source_sha:
            raise ValueError("Existing converted VHHBERT state does not match source safetensors hash")
        return payload
    load_file = _discover_safetensors(package_dir)
    source_state = load_file(str(source_path), device="cpu")
    encoder_state = {
        key.removeprefix("roberta."): value
        for key, value in source_state.items()
        if key.startswith("roberta.")
    }
    if not encoder_state:
        raise ValueError("VHHBERT safetensors file contains no roberta encoder weights")
    payload = {
        "schema_version": "phase2_v3_vhhbert_encoder_state_v1",
        "source_path": str(source_path),
        "source_sha256": source_sha,
        "state_dict": encoder_state,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=output_path.parent, delete=False) as tmp:
        torch.save(payload, tmp.name)
        tmp_path = Path(tmp.name)
    tmp_path.replace(output_path)
    return payload


def mean_pool(last_hidden: torch.Tensor, attention_mask: torch.Tensor, special_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.bool() & ~special_mask.bool()
    weights = mask.unsqueeze(-1).to(last_hidden.dtype)
    return (last_hidden * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1.0)


def load_real_models(args: argparse.Namespace) -> tuple[Any, Any, Any, Any, EmbeddingConfig]:
    from transformers import AutoModel, AutoTokenizer, BertTokenizer, RobertaConfig, RobertaModel

    device = torch.device(args.device)
    state_payload = ensure_vhhbert_state(args.vhhbert_model_path, args.vhhbert_state_path, args.safetensors_package_dir)
    config = RobertaConfig.from_pretrained(args.vhhbert_model_path, local_files_only=True)
    vhhbert = RobertaModel(config, add_pooling_layer=False)
    missing, unexpected = vhhbert.load_state_dict(state_payload["state_dict"], strict=False)
    missing = [key for key in missing if key != "embeddings.position_ids"]
    if missing or unexpected:
        raise ValueError(f"Converted VHHBERT state mismatch: missing={missing[:5]} unexpected={unexpected[:5]}")
    vhh_tokenizer = BertTokenizer.from_pretrained(args.vhhbert_model_path, local_files_only=True)
    esm_tokenizer = AutoTokenizer.from_pretrained(args.esm2_model_path, local_files_only=True)
    esm2 = AutoModel.from_pretrained(args.esm2_model_path, local_files_only=True, add_pooling_layer=False)
    vhhbert.eval().to(device)
    esm2.eval().to(device)
    cfg = EmbeddingConfig(
        backend="real",
        vhhbert_model_path=str(args.vhhbert_model_path),
        esm2_model_path=str(args.esm2_model_path),
        vhhbert_model_sha256=hash_model_directory(args.vhhbert_model_path),
        esm2_model_sha256=hash_model_directory(args.esm2_model_path),
        vhhbert_dim=int(config.hidden_size),
        esm2_dim=int(esm2.config.hidden_size),
        physchem_dim=len(physicochemical_features("QVQL" + "A" * 96)),
        max_esm_residues=args.max_esm_residues,
        chunk_overlap=args.chunk_overlap,
    )
    return vhh_tokenizer, vhhbert, esm_tokenizer, esm2, cfg


@torch.inference_mode()
def embed_vhhbert(
    sequences: Sequence[str], tokenizer: Any, model: Any, device: torch.device, batch_size: int
) -> torch.Tensor:
    output = []
    for start in range(0, len(sequences), batch_size):
        spaced = [" ".join(sequence) for sequence in sequences[start : start + batch_size]]
        encoded = tokenizer(
            spaced,
            padding=True,
            truncation=True,
            max_length=182,
            return_tensors="pt",
            return_special_tokens_mask=True,
        )
        special = encoded.pop("special_tokens_mask")
        encoded = {key: value.to(device) for key, value in encoded.items()}
        pooled = mean_pool(model(**encoded).last_hidden_state, encoded["attention_mask"], special.to(device))
        output.append(pooled.cpu())
    return torch.cat(output) if output else torch.empty((0, int(model.config.hidden_size)))


@torch.inference_mode()
def embed_esm2(
    sequences: Sequence[str],
    tokenizer: Any,
    model: Any,
    device: torch.device,
    batch_size: int,
    max_residues: int,
    overlap: int,
) -> torch.Tensor:
    chunks: list[str] = []
    owners: list[int] = []
    weights: list[int] = []
    for owner, sequence in enumerate(sequences):
        for chunk in chunk_sequence(sequence, max_residues, overlap):
            chunks.append(chunk)
            owners.append(owner)
            weights.append(len(chunk))
    sums = torch.zeros((len(sequences), int(model.config.hidden_size)), dtype=torch.float32)
    totals = torch.zeros(len(sequences), dtype=torch.float32)
    for positions in length_aware_batches([len(chunk) for chunk in chunks], batch_size):
        batch = [chunks[position] for position in positions]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=max_residues + 2,
            return_tensors="pt",
            return_special_tokens_mask=True,
        )
        special = encoded.pop("special_tokens_mask")
        encoded = {key: value.to(device) for key, value in encoded.items()}
        pooled = mean_pool(model(**encoded).last_hidden_state, encoded["attention_mask"], special.to(device)).cpu()
        for offset, vector in enumerate(pooled):
            position = positions[offset]
            owner = owners[position]
            weight = float(weights[position])
            sums[owner] += vector * weight
            totals[owner] += weight
    return sums / totals.unsqueeze(1).clamp_min(1.0)


def length_aware_batches(lengths: Sequence[int], short_batch_size: int) -> list[list[int]]:
    """Avoid quadratic-attention OOM when rare long antigens share a shard with VHHs."""
    buckets = [
        ([index for index, length in enumerate(lengths) if length <= 256], short_batch_size),
        ([index for index, length in enumerate(lengths) if 256 < length <= 512], min(short_batch_size, 32)),
        ([index for index, length in enumerate(lengths) if length > 512], min(short_batch_size, 2)),
    ]
    output = []
    for positions, cap in buckets:
        output.extend(positions[start : start + max(cap, 1)] for start in range(0, len(positions), max(cap, 1)))
    return output


def shard_config_sha(config: EmbeddingConfig, hashes: Sequence[str]) -> str:
    payload = {"config": asdict(config), "sequence_sha256": list(hashes)}
    return sha256_text(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def validate_existing_shard(path: Path, expected_sha: str, expected_hashes: Sequence[str]) -> dict[str, Any]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("config_sha256") != expected_sha or payload.get("sequence_sha256") != list(expected_hashes):
        raise ValueError(f"Existing embedding shard does not match frozen config/input: {path}")
    count = len(expected_hashes)
    for key in ("esm2", "vhhbert", "physchem", "vhhbert_available"):
        if key not in payload or int(payload[key].shape[0]) != count:
            raise ValueError(f"Malformed existing embedding shard {path}: {key}")
    return payload


def build_hash_shard(rows: list[dict[str, Any]], config: EmbeddingConfig) -> dict[str, torch.Tensor]:
    esm2 = torch.stack([deterministic_hash_embedding(row["sequence"], config.esm2_dim, "esm2") for row in rows])
    vhhbert = torch.stack(
        [
            deterministic_hash_embedding(row["sequence"], config.vhhbert_dim, "vhhbert")
            if "vhh" in row["roles"].split(";")
            else torch.zeros(config.vhhbert_dim)
            for row in rows
        ]
    )
    physchem = torch.tensor(
        [physicochemical_features(row["sequence"]) if "vhh" in row["roles"].split(";") else [0.0] * config.physchem_dim for row in rows],
        dtype=torch.float32,
    )
    available = torch.tensor(["vhh" in row["roles"].split(";") for row in rows], dtype=torch.bool)
    return {"esm2": esm2, "vhhbert": vhhbert, "physchem": physchem, "vhhbert_available": available}


def prepare_embeddings(args: argparse.Namespace) -> dict[str, Any]:
    frame = pd.read_csv(args.sequence_manifest)
    required = {"sequence_sha256", "sequence", "sequence_length", "roles"}
    if required - set(frame.columns):
        raise ValueError(f"Sequence manifest missing {sorted(required - set(frame.columns))}")
    if frame["sequence_sha256"].duplicated().any():
        raise ValueError("Sequence manifest contains duplicate hashes")
    rows = frame.sort_values("sequence_sha256").to_dict("records")
    if args.backend == "real":
        vhh_tokenizer, vhhbert, esm_tokenizer, esm2_model, config = load_real_models(args)
    else:
        vhh_tokenizer = vhhbert = esm_tokenizer = esm2_model = None
        config = EmbeddingConfig(
            backend="hash",
            vhhbert_model_path="hash",
            esm2_model_path="hash",
            vhhbert_model_sha256="hash",
            esm2_model_sha256="hash",
            vhhbert_dim=args.hash_vhhbert_dim,
            esm2_dim=args.hash_esm2_dim,
            physchem_dim=len(physicochemical_features("QVQL" + "A" * 96)),
            max_esm_residues=args.max_esm_residues,
            chunk_overlap=args.chunk_overlap,
        )
    config_sha = sha256_text(json.dumps(asdict(config), separators=(",", ":"), sort_keys=True))
    output_dir = args.output_dir
    shard_dir = output_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    reused = 0
    created = 0
    device = torch.device(args.device)
    for shard_index, start in enumerate(range(0, len(rows), args.shard_size)):
        batch_rows = rows[start : start + args.shard_size]
        hashes = [str(row["sequence_sha256"]) for row in batch_rows]
        expected_sha = shard_config_sha(config, hashes)
        shard_path = shard_dir / f"shard_{shard_index:05d}.pt"
        if shard_path.is_file():
            payload = validate_existing_shard(shard_path, expected_sha, hashes)
            reused += 1
        else:
            if args.backend == "hash":
                tensors = build_hash_shard(batch_rows, config)
            else:
                sequences = [str(row["sequence"]) for row in batch_rows]
                esm_tensor = embed_esm2(
                    sequences,
                    esm_tokenizer,
                    esm2_model,
                    device,
                    args.esm_batch_size,
                    args.max_esm_residues,
                    args.chunk_overlap,
                )
                vhh_indices = [index for index, row in enumerate(batch_rows) if "vhh" in str(row["roles"]).split(";")]
                vhh_tensor = torch.zeros((len(batch_rows), config.vhhbert_dim), dtype=torch.float32)
                if vhh_indices:
                    values = embed_vhhbert(
                        [sequences[index] for index in vhh_indices],
                        vhh_tokenizer,
                        vhhbert,
                        device,
                        args.vhhbert_batch_size,
                    )
                    vhh_tensor[vhh_indices] = values
                vhh_index_set = set(vhh_indices)
                physchem = torch.tensor(
                    [
                        physicochemical_features(row["sequence"])
                        if index in vhh_index_set
                        else [0.0] * config.physchem_dim
                        for index, row in enumerate(batch_rows)
                    ],
                    dtype=torch.float32,
                )
                tensors = {
                    "esm2": esm_tensor,
                    "vhhbert": vhh_tensor,
                    "physchem": physchem,
                    "vhhbert_available": torch.tensor([index in vhh_index_set for index in range(len(batch_rows))]),
                }
            payload = {
                "schema_version": "phase2_v3_embedding_shard_v1",
                "config_sha256": expected_sha,
                "sequence_sha256": hashes,
                **{key: value.half() if value.dtype == torch.float32 and key != "physchem" else value for key, value in tensors.items()},
            }
            with tempfile.NamedTemporaryFile("wb", dir=shard_dir, delete=False) as tmp:
                torch.save(payload, tmp.name)
                tmp_path = Path(tmp.name)
            tmp_path.replace(shard_path)
            created += 1
        for offset, row in enumerate(batch_rows):
            manifest_rows.append(
                {
                    "sequence_sha256": row["sequence_sha256"],
                    "sequence_length": row["sequence_length"],
                    "roles": row["roles"],
                    "shard_path": str(shard_path),
                    "shard_index": offset,
                    "esm2_dim": config.esm2_dim,
                    "vhhbert_dim": config.vhhbert_dim,
                    "physchem_dim": config.physchem_dim,
                    "config_sha256": config_sha,
                }
            )
    manifest_path = output_dir / "embedding_manifest_v3.csv"
    write_csv_atomic(manifest_path, manifest_rows, list(manifest_rows[0]))
    summary = {
        "schema_version": "phase2_v3_embedding_summary_v1",
        "sequence_manifest": str(args.sequence_manifest),
        "sequence_manifest_sha256": sha256_file(args.sequence_manifest),
        "embedding_manifest": str(manifest_path),
        "embedding_manifest_sha256": sha256_file(manifest_path),
        "config": asdict(config),
        "config_sha256": config_sha,
        "sequence_count": len(rows),
        "vhh_sequence_count": sum("vhh" in str(row["roles"]).split(";") for row in rows),
        "antigen_sequence_count": sum("antigen" in str(row["roles"]).split(";") for row in rows),
        "shard_count": (len(rows) + args.shard_size - 1) // args.shard_size,
        "created_shards": created,
        "reused_shards": reused,
        "device": str(device),
        "cuda_device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
    }
    write_json_atomic(output_dir / "embedding_summary_v3.json", summary)
    print(json.dumps({"sequence_count": len(rows), "created_shards": created, "reused_shards": reused}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence-manifest", type=Path, default=DEFAULT_SEQUENCE_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--backend", choices=("real", "hash"), default="real")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--vhhbert-model-path", type=Path, default=DEFAULT_VHHBERT)
    parser.add_argument("--esm2-model-path", type=Path, default=DEFAULT_ESM2)
    parser.add_argument("--vhhbert-state-path", type=Path, default=DEFAULT_VHHBERT_STATE)
    parser.add_argument("--safetensors-package-dir", type=Path, default=Path("/tmp/pvrig_v3_safetensors"))
    parser.add_argument("--vhhbert-batch-size", type=int, default=128)
    parser.add_argument("--esm-batch-size", type=int, default=256)
    parser.add_argument("--shard-size", type=int, default=1024)
    parser.add_argument("--max-esm-residues", type=int, default=1000)
    parser.add_argument("--chunk-overlap", type=int, default=0)
    parser.add_argument("--hash-vhhbert-dim", type=int, default=16)
    parser.add_argument("--hash-esm2-dim", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    prepare_embeddings(parse_args())


if __name__ == "__main__":
    main()
