#!/usr/bin/env python3
"""Frozen embedding bank and neural heads for Phase 2 V3."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import torch
from torch import nn


@dataclass
class EmbeddingBank:
    index_by_sha256: dict[str, int]
    sequence_sha256: list[str]
    esm2: torch.Tensor
    vhhbert: torch.Tensor
    physchem: torch.Tensor
    config_sha256: str

    @property
    def esm2_dim(self) -> int:
        return int(self.esm2.shape[1])

    @property
    def vhhbert_dim(self) -> int:
        return int(self.vhhbert.shape[1])

    @property
    def physchem_dim(self) -> int:
        return int(self.physchem.shape[1])

    def to(self, device: torch.device) -> "EmbeddingBank":
        return EmbeddingBank(
            index_by_sha256=self.index_by_sha256,
            sequence_sha256=self.sequence_sha256,
            esm2=self.esm2.to(device=device, dtype=torch.float32),
            vhhbert=self.vhhbert.to(device=device, dtype=torch.float32),
            physchem=self.physchem.to(device=device, dtype=torch.float32),
            config_sha256=self.config_sha256,
        )


def load_embedding_bank(manifest_path: Path) -> EmbeddingBank:
    manifest = pd.read_csv(manifest_path)
    required = {
        "sequence_sha256",
        "shard_path",
        "shard_index",
        "esm2_dim",
        "vhhbert_dim",
        "physchem_dim",
        "config_sha256",
    }
    if required - set(manifest.columns) or manifest["sequence_sha256"].duplicated().any():
        raise ValueError("Malformed V3 embedding manifest")
    config_values = set(manifest["config_sha256"].astype(str))
    if len(config_values) != 1:
        raise ValueError("Embedding manifest mixes configuration hashes")
    sequences: list[str] = []
    esm_parts = []
    vhh_parts = []
    phys_parts = []
    seen_paths = []
    for path in manifest["shard_path"].astype(str):
        if not seen_paths or seen_paths[-1] != path:
            seen_paths.append(path)
    for raw_path in seen_paths:
        payload = torch.load(Path(raw_path), map_location="cpu", weights_only=False)
        shard_hashes = [str(value) for value in payload["sequence_sha256"]]
        sequences.extend(shard_hashes)
        esm_parts.append(payload["esm2"].cpu())
        vhh_parts.append(payload["vhhbert"].cpu())
        phys_parts.append(payload["physchem"].cpu())
    if sequences != manifest["sequence_sha256"].astype(str).tolist():
        raise ValueError("Embedding manifest row order does not match shard payloads")
    index_by_sha = {sha: index for index, sha in enumerate(sequences)}
    return EmbeddingBank(
        index_by_sha256=index_by_sha,
        sequence_sha256=sequences,
        esm2=torch.cat(esm_parts),
        vhhbert=torch.cat(vhh_parts),
        physchem=torch.cat(phys_parts),
        config_sha256=next(iter(config_values)),
    )


def frame_pair_indices(frame: pd.DataFrame, bank: EmbeddingBank) -> tuple[torch.Tensor, torch.Tensor]:
    vhh = frame["sequence_sha256"].astype(str).map(bank.index_by_sha256)
    target = frame["target_sequence_sha256"].astype(str).map(bank.index_by_sha256)
    if vhh.isna().any() or target.isna().any():
        missing_vhh = frame.loc[vhh.isna(), "sequence_sha256"].astype(str).head().tolist()
        missing_target = frame.loc[target.isna(), "target_sequence_sha256"].astype(str).head().tolist()
        raise ValueError(f"Embedding cache misses pair hashes: vhh={missing_vhh} target={missing_target}")
    return torch.tensor(vhh.astype(int).to_numpy()), torch.tensor(target.astype(int).to_numpy())


class BindingPriorModel(nn.Module):
    def __init__(
        self,
        variant: str,
        esm2_dim: int,
        vhhbert_dim: int,
        physchem_dim: int,
        latent_dim: int,
        hidden_dim: int,
        dropout: float,
    ):
        super().__init__()
        if variant not in {"vhh_only", "esm2_pair", "v3_full"}:
            raise ValueError(f"Unsupported V3 model variant: {variant}")
        self.variant = variant
        self.model_config = {
            "variant": variant,
            "esm2_dim": esm2_dim,
            "vhhbert_dim": vhhbert_dim,
            "physchem_dim": physchem_dim,
            "latent_dim": latent_dim,
            "hidden_dim": hidden_dim,
            "dropout": dropout,
        }
        if variant == "vhh_only":
            input_dim = vhhbert_dim + esm2_dim + physchem_dim
            self.vhh_head = nn.Sequential(
                nn.LayerNorm(input_dim),
                nn.Linear(input_dim, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.GELU(),
                nn.Linear(hidden_dim // 2, 1),
            )
            return

        vhh_input_dim = esm2_dim if variant == "esm2_pair" else vhhbert_dim + esm2_dim + physchem_dim
        self.vhh_projection = nn.Sequential(nn.LayerNorm(vhh_input_dim), nn.Linear(vhh_input_dim, latent_dim), nn.GELU())
        self.target_projection = nn.Sequential(nn.LayerNorm(esm2_dim), nn.Linear(esm2_dim, latent_dim), nn.GELU())
        interaction_dim = latent_dim * 4 + 1
        self.residual = nn.Sequential(
            nn.LayerNorm(interaction_dim),
            nn.Linear(interaction_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, latent_dim),
        )
        self.gate = nn.Sequential(nn.Linear(interaction_dim, latent_dim), nn.Sigmoid())
        self.output = nn.Sequential(
            nn.LayerNorm(latent_dim),
            nn.Linear(latent_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(self, bank: EmbeddingBank, vhh_index: torch.Tensor, target_index: torch.Tensor) -> torch.Tensor:
        esm_vhh = bank.esm2[vhh_index]
        if self.variant == "vhh_only":
            raw = torch.cat([bank.vhhbert[vhh_index], esm_vhh, bank.physchem[vhh_index]], dim=1)
            return self.vhh_head(raw).squeeze(-1)
        raw_vhh = esm_vhh if self.variant == "esm2_pair" else torch.cat(
            [bank.vhhbert[vhh_index], esm_vhh, bank.physchem[vhh_index]], dim=1
        )
        vhh = self.vhh_projection(raw_vhh)
        target = self.target_projection(bank.esm2[target_index])
        cosine = nn.functional.cosine_similarity(vhh, target).unsqueeze(1)
        interaction = torch.cat([vhh, target, vhh * target, torch.abs(vhh - target), cosine], dim=1)
        shared = 0.5 * (vhh + target) + self.gate(interaction) * self.residual(interaction)
        return self.output(shared).squeeze(-1)


def fixed_esm2_cosine(bank: EmbeddingBank, vhh_index: torch.Tensor, target_index: torch.Tensor) -> torch.Tensor:
    return nn.functional.cosine_similarity(bank.esm2[vhh_index], bank.esm2[target_index])


def within_target_pairwise_loss(
    logits: torch.Tensor,
    labels: torch.Tensor,
    target_codes: torch.Tensor,
    max_per_class: int = 64,
) -> torch.Tensor:
    losses = []
    for target in torch.unique(target_codes):
        mask = target_codes == target
        positives = logits[mask & (labels > 0.5)][:max_per_class]
        negatives = logits[mask & (labels < 0.5)][:max_per_class]
        if positives.numel() and negatives.numel():
            losses.append(nn.functional.softplus(-(positives[:, None] - negatives[None, :])).mean())
    return torch.stack(losses).mean() if losses else logits.sum() * 0.0


@torch.inference_mode()
def score_model(
    model: BindingPriorModel,
    bank: EmbeddingBank,
    vhh_index: torch.Tensor,
    target_index: torch.Tensor,
    batch_size: int,
    device: torch.device,
) -> torch.Tensor:
    model.eval()
    values = []
    for start in range(0, len(vhh_index), batch_size):
        vhh = vhh_index[start : start + batch_size].to(device)
        target = target_index[start : start + batch_size].to(device)
        values.append(torch.sigmoid(model(bank, vhh, target)).cpu())
    return torch.cat(values) if values else torch.empty(0)


def model_from_checkpoint(checkpoint: dict[str, Any], device: torch.device) -> BindingPriorModel:
    model = BindingPriorModel(**checkpoint["model_config"])
    model.load_state_dict(checkpoint["state_dict"])
    model.eval().to(device)
    return model
