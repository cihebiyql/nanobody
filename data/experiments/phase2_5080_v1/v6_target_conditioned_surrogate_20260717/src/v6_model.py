#!/usr/bin/env python3
"""Model and loss primitives for the V6 docking-geometry surrogate.

The model predicts computational docking geometry only.  It is deliberately a
structure-first residual architecture: a 126-feature M2-style branch predicts
the three continuous geometry targets, while residue-level PLM features can
only add a bounded residual.  This keeps a larger PLM from silently erasing the
strong structure baseline on a small supervised data set.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor, nn
from torch.nn import functional as F


TARGET_NAMES = ("R_8X6B", "R_9E6Y", "R_dual_min")
AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWYX"


class V6Error(RuntimeError):
    """Fail-closed V6 configuration or data error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise V6Error(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_parent_folds(groups: Sequence[str], fold_count: int, seed: int = 20260717) -> list[list[int]]:
    """Build deterministic, size-balanced folds without splitting a parent."""
    require(fold_count >= 2, "fold_count_must_be_at_least_two")
    require(len(groups) > 0, "empty_group_vector")
    by_group: dict[str, list[int]] = {}
    for index, group in enumerate(groups):
        require(bool(str(group)), f"empty_parent_group:{index}")
        by_group.setdefault(str(group), []).append(index)
    require(len(by_group) >= fold_count, "too_few_parent_groups")

    def group_key(item: tuple[str, list[int]]) -> tuple[int, str]:
        group, indices = item
        tie = hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()
        return (-len(indices), tie)

    bins: list[list[int]] = [[] for _ in range(fold_count)]
    loads = [0] * fold_count
    for _group, indices in sorted(by_group.items(), key=group_key):
        target = min(range(fold_count), key=lambda value: (loads[value], value))
        bins[target].extend(indices)
        loads[target] += len(indices)
    folds = [sorted(values) for values in bins]
    require(all(folds), "empty_parent_fold")
    require(sorted(index for fold in folds for index in fold) == list(range(len(groups))), "fold_row_closure_failed")
    for held in folds:
        held_set = set(held)
        inside = {str(groups[index]) for index in held}
        outside = {str(groups[index]) for index in range(len(groups)) if index not in held_set}
        require(not inside.intersection(outside), "parent_leakage_across_folds")
    return folds


class TinyResidueTokenizer:
    """Dependency-free tokenizer used only by synthetic tests/smoke runs."""

    pad_token_id = 0
    bos_token_id = 1
    eos_token_id = 2

    def __init__(self) -> None:
        self.vocabulary = {aa: index + 3 for index, aa in enumerate(AA_ALPHABET)}

    def __len__(self) -> int:
        return len(self.vocabulary) + 3

    def __call__(
        self,
        sequences: Sequence[str],
        *,
        padding: bool = True,
        return_tensors: str = "pt",
        return_special_tokens_mask: bool = True,
        truncation: bool = False,
        max_length: int | None = None,
    ) -> dict[str, Tensor]:
        require(return_tensors == "pt", "tiny_tokenizer_requires_pt")
        encoded: list[list[int]] = []
        for sequence in sequences:
            require(bool(sequence), "empty_sequence")
            values = [self.bos_token_id] + [self.vocabulary.get(aa, self.vocabulary["X"]) for aa in sequence] + [self.eos_token_id]
            if max_length is not None and len(values) > max_length:
                require(truncation, "sequence_exceeds_max_length")
                values = values[: max_length - 1] + [self.eos_token_id]
            encoded.append(values)
        width = max(map(len, encoded)) if padding else len(encoded[0])
        input_ids, attention, special = [], [], []
        for values in encoded:
            pads = width - len(values)
            input_ids.append(values + [self.pad_token_id] * pads)
            attention.append([1] * len(values) + [0] * pads)
            special.append([1] + [0] * (len(values) - 2) + [1] + [1] * pads)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
            "special_tokens_mask": torch.tensor(special, dtype=torch.long),
        }


class TinyResidueBackbone(nn.Module):
    """Small differentiable residue encoder for CPU tests and GPU smoke."""

    def __init__(self, vocabulary_size: int, hidden_size: int = 32) -> None:
        super().__init__()
        self.hidden_size = int(hidden_size)
        self.embedding = nn.Embedding(vocabulary_size, hidden_size, padding_idx=0)
        self.encoder = nn.GRU(hidden_size, hidden_size // 2, batch_first=True, bidirectional=True)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        del attention_mask
        tokens, _state = self.encoder(self.embedding(input_ids))
        return tokens


class HuggingFaceResidueBackbone(nn.Module):
    """Offline local Hugging Face adapter for ESM2 and current ESMC releases."""

    def __init__(self, model: nn.Module) -> None:
        super().__init__()
        self.model = model
        config = model.config
        hidden = getattr(config, "hidden_size", None) or getattr(config, "d_model", None) or getattr(config, "embed_dim", None)
        require(hidden is not None, "hf_backbone_hidden_size_missing")
        self.hidden_size = int(hidden)

    @classmethod
    def from_local(
        cls,
        model_path: Path,
        *,
        gradient_checkpointing: bool = False,
        trust_remote_code: bool = False,
        lora: Mapping[str, Any] | None = None,
        load_dtype: str = "auto",
    ) -> tuple["HuggingFaceResidueBackbone", Any]:
        require(model_path.exists(), f"local_model_path_missing:{model_path}")
        try:
            from transformers import AutoModel, AutoModelForMaskedLM, AutoTokenizer
        except ImportError as error:
            raise V6Error("transformers_required_for_hf_backbone") from error

        common = {
            "local_files_only": True,
            "trust_remote_code": bool(trust_remote_code),
        }
        require(load_dtype in {"auto", "float32", "bfloat16"}, "invalid_hf_load_dtype")
        if load_dtype != "auto":
            common["torch_dtype"] = torch.float32 if load_dtype == "float32" else torch.bfloat16
        tokenizer = AutoTokenizer.from_pretrained(str(model_path), **common)
        first_error: Exception | None = None
        try:
            model = AutoModel.from_pretrained(str(model_path), **common)
        except Exception as error:  # ESMC releases may register only a masked-LM auto class.
            first_error = error
            try:
                model = AutoModelForMaskedLM.from_pretrained(str(model_path), **common)
            except Exception as second_error:
                raise V6Error(
                    "offline_hf_model_load_failed:"
                    f"auto_model={type(first_error).__name__}:{first_error};"
                    f"masked_lm={type(second_error).__name__}:{second_error}"
                ) from second_error

        if gradient_checkpointing:
            method = getattr(model, "gradient_checkpointing_enable", None)
            require(callable(method), "backbone_does_not_support_gradient_checkpointing")
            method()
            if hasattr(model.config, "use_cache"):
                model.config.use_cache = False

        if lora:
            try:
                from peft import LoraConfig, TaskType, get_peft_model
            except ImportError as error:
                raise V6Error("peft_required_when_lora_enabled") from error
            targets = list(lora.get("target_modules") or [])
            require(bool(targets), "lora_target_modules_required")
            config = LoraConfig(
                r=int(lora.get("r", 8)),
                lora_alpha=int(lora.get("alpha", 16)),
                lora_dropout=float(lora.get("dropout", 0.05)),
                bias="none",
                target_modules=targets,
                task_type=TaskType.FEATURE_EXTRACTION,
            )
            model = get_peft_model(model, config)
            if gradient_checkpointing:
                enable_inputs = getattr(model, "enable_input_require_grads", None)
                if callable(enable_inputs):
                    enable_inputs()
        return cls(model), tokenizer

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        output = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            output_hidden_states=True,
            return_dict=True,
        )
        tokens = getattr(output, "last_hidden_state", None)
        if tokens is None:
            hidden_states = getattr(output, "hidden_states", None)
            require(hidden_states is not None and len(hidden_states) > 0, "hf_backbone_did_not_return_residue_states")
            tokens = hidden_states[-1]
        require(tokens.ndim == 3, "hf_residue_state_shape_invalid")
        return tokens


@dataclass(frozen=True)
class V6ModelConfig:
    structure_dim: int = 126
    fusion_dim: int = 128
    dropout: float = 0.10
    residual_scale: float = 0.15
    uncertainty_head: bool = False
    contact_head: bool = False
    freeze_m2: bool = False


class V6MultitaskModel(nn.Module):
    """Residue/structure fusion with an explicit M2 residual skip."""

    def __init__(self, backbone: nn.Module, backbone_hidden_size: int, config: V6ModelConfig) -> None:
        super().__init__()
        require(config.structure_dim > 0 and config.fusion_dim > 0, "invalid_model_dimensions")
        require(config.residual_scale > 0, "residual_scale_must_be_positive")
        self.backbone = backbone
        self.config = config
        self.sequence_projection = nn.Sequential(
            nn.LayerNorm(backbone_hidden_size),
            nn.Linear(backbone_hidden_size, config.fusion_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
        )
        self.structure_encoder = nn.Sequential(
            nn.LayerNorm(config.structure_dim),
            nn.Linear(config.structure_dim, config.fusion_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
        )
        self.m2_head = nn.Linear(config.structure_dim, len(TARGET_NAMES))
        self.residual_head = nn.Sequential(
            nn.Linear(config.fusion_dim * 3, config.fusion_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.fusion_dim, len(TARGET_NAMES)),
        )
        self.uncertainty_head = nn.Linear(config.fusion_dim * 3, len(TARGET_NAMES)) if config.uncertainty_head else None
        self.contact_head = nn.Linear(backbone_hidden_size, 1) if config.contact_head else None
        if config.freeze_m2:
            for parameter in self.m2_head.parameters():
                parameter.requires_grad_(False)

    def load_m2_state(self, state: Mapping[str, Tensor], *, freeze: bool = True) -> None:
        self.m2_head.load_state_dict(dict(state), strict=True)
        if freeze:
            for parameter in self.m2_head.parameters():
                parameter.requires_grad_(False)

    def forward(
        self,
        *,
        input_ids: Tensor,
        attention_mask: Tensor,
        residue_mask: Tensor,
        structure_features: Tensor,
    ) -> dict[str, Tensor]:
        require(structure_features.ndim == 2 and structure_features.shape[1] == self.config.structure_dim, "structure_shape_invalid")
        token_states = self.backbone(input_ids, attention_mask)
        require(token_states.shape[:2] == input_ids.shape, "backbone_token_shape_mismatch")
        mask = residue_mask.to(dtype=token_states.dtype).unsqueeze(-1)
        denominator = mask.sum(dim=1).clamp_min(1.0)
        pooled = (token_states * mask).sum(dim=1) / denominator
        sequence = self.sequence_projection(pooled)
        structure = self.structure_encoder(structure_features)
        fusion = torch.cat((sequence, structure, sequence * structure), dim=-1)
        m2 = self.m2_head(structure_features)
        residual = self.config.residual_scale * torch.tanh(self.residual_head(fusion))
        prediction = m2 + residual
        result = {
            "prediction": prediction,
            "m2_prediction": m2,
            "residual": residual,
        }
        if self.uncertainty_head is not None:
            result["log_variance"] = self.uncertainty_head(fusion).clamp(-8.0, 4.0)
        if self.contact_head is not None:
            result["contact_logits"] = self.contact_head(token_states).squeeze(-1)
        return result


@dataclass(frozen=True)
class V6LossConfig:
    dual_weight: float = 1.0
    receptor_weight: float = 0.35
    contact_weight: float = 0.0
    ranking_weight: float = 0.0
    uncertainty_weight: float = 0.0
    residual_weight: float = 0.10
    huber_delta: float = 0.03
    ranking_margin: float = 0.005
    ranking_temperature: float = 0.02


def _weighted_mean(values: Tensor, weights: Tensor) -> Tensor:
    require(values.ndim == 1 and weights.shape == values.shape, "weighted_mean_shape_invalid")
    return (values * weights).sum() / weights.sum().clamp_min(torch.finfo(values.dtype).eps)


def within_parent_ranking_loss(
    prediction: Tensor,
    target: Tensor,
    parent_ids: Sequence[str],
    sample_weight: Tensor,
    *,
    minimum_delta: float,
    temperature: float,
) -> Tensor:
    require(prediction.ndim == target.ndim == sample_weight.ndim == 1, "ranking_vector_shape_invalid")
    require(len(prediction) == len(parent_ids), "ranking_parent_count_mismatch")
    losses: list[Tensor] = []
    weights: list[Tensor] = []
    for left in range(len(prediction)):
        for right in range(left + 1, len(prediction)):
            if str(parent_ids[left]) != str(parent_ids[right]):
                continue
            delta = target[left] - target[right]
            if float(torch.abs(delta).detach().cpu()) < minimum_delta:
                continue
            sign = torch.sign(delta)
            scaled = sign * (prediction[left] - prediction[right]) / temperature
            losses.append(F.softplus(-scaled))
            weights.append(torch.sqrt(sample_weight[left] * sample_weight[right]))
    if not losses:
        return prediction.sum() * 0.0
    return _weighted_mean(torch.stack(losses), torch.stack(weights))


def compute_multitask_loss(
    output: Mapping[str, Tensor],
    targets: Tensor,
    sample_weight: Tensor,
    parent_ids: Sequence[str],
    config: V6LossConfig,
    *,
    contact_targets: Tensor | None = None,
    contact_mask: Tensor | None = None,
) -> tuple[Tensor, dict[str, Tensor]]:
    prediction = output["prediction"]
    require(prediction.shape == targets.shape and prediction.shape[1] == len(TARGET_NAMES), "target_prediction_shape_mismatch")
    require(sample_weight.ndim == 1 and len(sample_weight) == len(targets), "sample_weight_shape_invalid")
    require(bool(torch.all(sample_weight > 0)), "sample_weights_must_be_positive")
    huber = F.huber_loss(prediction, targets, reduction="none", delta=config.huber_delta)
    r8 = _weighted_mean(huber[:, 0], sample_weight)
    r9 = _weighted_mean(huber[:, 1], sample_weight)
    dual = _weighted_mean(huber[:, 2], sample_weight)
    receptor = 0.5 * (r8 + r9)
    residual = output["residual"].square().mean(dim=1)
    residual_penalty = _weighted_mean(residual, sample_weight)
    total = config.dual_weight * dual + config.receptor_weight * receptor + config.residual_weight * residual_penalty
    parts: dict[str, Tensor] = {
        "dual_huber": dual,
        "receptor_huber": receptor,
        "residual_penalty": residual_penalty,
    }

    if config.uncertainty_weight > 0:
        require("log_variance" in output, "uncertainty_loss_requested_without_head")
        log_variance = output["log_variance"]
        nll = 0.5 * (torch.exp(-log_variance) * (prediction - targets).square() + log_variance)
        uncertainty = _weighted_mean(nll.mean(dim=1), sample_weight)
        total = total + config.uncertainty_weight * uncertainty
        parts["uncertainty_nll"] = uncertainty

    if config.contact_weight > 0:
        require("contact_logits" in output, "contact_loss_requested_without_head")
        require(contact_targets is not None and contact_mask is not None, "contact_targets_required")
        require(contact_targets.shape == contact_mask.shape == output["contact_logits"].shape, "contact_shape_mismatch")
        valid = contact_mask.to(dtype=prediction.dtype)
        per_token = F.binary_cross_entropy_with_logits(output["contact_logits"], contact_targets, reduction="none")
        counts = valid.sum(dim=1)
        available = counts > 0
        if bool(torch.any(available)):
            per_candidate = (per_token * valid).sum(dim=1) / counts.clamp_min(1.0)
            contact = _weighted_mean(per_candidate[available], sample_weight[available])
        else:
            contact = prediction.sum() * 0.0
        total = total + config.contact_weight * contact
        parts["contact_bce"] = contact

    if config.ranking_weight > 0:
        ranking = within_parent_ranking_loss(
            prediction[:, 2],
            targets[:, 2],
            parent_ids,
            sample_weight,
            minimum_delta=config.ranking_margin,
            temperature=config.ranking_temperature,
        )
        total = total + config.ranking_weight * ranking
        parts["ranking"] = ranking

    parts["total"] = total
    return total, parts


def model_contract(model: V6MultitaskModel, loss: V6LossConfig) -> dict[str, Any]:
    return {
        "model": asdict(model.config),
        "loss": asdict(loss),
        "targets": list(TARGET_NAMES),
        "claim_boundary": (
            "Sequence/monomer-structure approximation of independent dual-receptor "
            "computational docking geometry; not binding probability, affinity, "
            "experimental competition, blocking, or Docking Gold."
        ),
    }
