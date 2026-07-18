#!/usr/bin/env python3
"""Nested whole-parent trainer for the frozen Residue V2 ablation matrix.

Each invocation owns exactly one outer fold.  Five independent invocations
produce the five prediction files consumed by ``collect_residue_oof_v2.py``.
The PLM is always frozen and checkpoints contain only ``head.*`` tensors.
``teacher_source`` is retained solely for the deterministic 2:6 sampler,
source-balanced losses, metrics, and audit output.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor, nn
from torch.nn import functional as F
from torch.optim import AdamW
from torch.utils.data import DataLoader


HERE = Path(__file__).resolve()
V1_SRC = HERE.parents[2] / "residue_v1" / "src"
if str(V1_SRC) not in sys.path:
    sys.path.insert(0, str(V1_SRC))

import train_nested_residue_surrogate as v1  # noqa: E402
import train_nested_residue_surrogate_v1_5 as v15  # noqa: E402
from residue_model import DualContactResidualHead, ResidueHeadConfig, ResidueSurrogate  # noqa: E402

from build_residue_graph_cache_v2 import load_graph_cache  # noqa: E402
from domain_balance_v2 import (  # noqa: E402
    SOURCES,
    V4D,
    V4H,
    DeterministicDomainBatchSampler,
    assert_teacher_source_not_model_feature,
    source_balanced_component,
)
from residue_model_v2 import (  # noqa: E402
    CLAIM_BOUNDARY,
    RECEPTOR_NAMES,
    InvariantGraphEncoder,
    ResidueV2Config,
    ResidueV2Surrogate,
    TargetConditionedResidueV2Head,
    backbone_states,
    model_contract,
    trainable_checkpoint_state,
)


SCHEMA_VERSION = "pvrig_v6_nested_residue_surrogate_v2"
PREREGISTRATION_SCHEMA = "pvrig_v6_residue_v2_preregistration"
PREREGISTRATION_STATUS = "FROZEN_DESIGN_BEFORE_RESIDUE_V2_OOF_RESULTS"
LANES = ("A_DOMAIN", "B_VHH3D", "C_PATCH", "D_FULL_PAIR")
GRAPH_LANES = frozenset(("B_VHH3D", "C_PATCH", "D_FULL_PAIR"))
TARGET_LANES = frozenset(("C_PATCH", "D_FULL_PAIR"))
PAIR_LANES = frozenset(("D_FULL_PAIR",))
TRAIN_REQUIRED = {
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "outer_fold", "teacher_source",
}
PAIR_REQUIRED = {
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "receptor",
    "vhh_sequence_index", "contact_target", "contact_uncertainty_weight", "target_mask",
    "pair_table_semantics",
}
CONTACT_LOSS_AMENDMENT_SCHEMA = "pvrig_v6_residue_v2_contact_loss_amendment_v1"
CONTACT_LOSS_AMENDMENT_SCHEMA_V2_2 = "pvrig_v6_residue_v2_contact_loss_amendment_v2_2"
CONTACT_LOSS_AMENDMENT_STATUS = "FROZEN_BEFORE_ANY_FORMAL_RESIDUE_V2_TRAINING"
CONTACT_LOSS_NORMALIZATION = (
    "per_candidate_per_receptor_soft_positive_negative_balanced_then_equal_source"
)
LOSS_COMPONENT_ORDER = ("dual", "receptor", "marginal", "ranking", "residual", "pair")
CONTACT_GRADIENT_GRID = (
    (0.0025, 0.00125),
    (0.005, 0.0025),
    (0.01, 0.005),
    (0.02, 0.01),
)
CONTACT_GRADIENT_TARGET_MIN = 0.05
CONTACT_GRADIENT_TARGET_MAX = 0.20
CONTACT_GRADIENT_HARD_MAX = 0.30
CONTACT_GRADIENT_GRID_V2_2 = (
    0.0003125,
    0.000625,
    0.00125,
    0.0025,
    0.005,
    0.01,
    0.02,
)


class TrainerV2Error(RuntimeError):
    """Fail-closed V2 trainer input or protocol error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TrainerV2Error(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    torch.save(dict(payload), temporary)
    os.replace(temporary, path)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"input_missing_or_symlink:{path}")
    opener: Any = gzip.open if path.suffix == ".gz" else Path.open
    if path.suffix == ".gz":
        handle = opener(path, "rt", encoding="utf-8-sig", newline="")
    else:
        handle = opener(path, "r", encoding="utf-8-sig", newline="")
    with handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def load_preregistration(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "preregistration_missing_or_symlink")
    payload = json.loads(path.read_text())
    require(payload.get("schema_version") == PREREGISTRATION_SCHEMA, "preregistration_schema_invalid")
    require(payload.get("status") == PREREGISTRATION_STATUS, "preregistration_status_invalid")
    require(set(payload.get("lanes") or {}) == set(LANES), "preregistration_lane_closure")
    require(payload.get("training", {}).get("teacher_source_is_model_feature") is False, "teacher_source_feature_contract")
    require(payload.get("sealed_and_excluded", {}).get("teacher_source_as_model_feature") is True, "teacher_source_seal_contract")
    return payload


def validate_contact_receipt(path: Path, contact_tsv_gz: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "contact_receipt_missing_or_symlink")
    payload = json.loads(path.read_text())
    require(payload.get("schema_version") == "pvrig_v6_residue_dual_source_contact_targets_v2_receipt", "contact_receipt_schema")
    require(payload.get("status") == "PASS_DUAL_SOURCE_CONTACT_TARGETS_V2", "contact_receipt_status")
    require(payload.get("teacher_source_is_model_feature") is False, "contact_receipt_source_feature_contract")
    output = payload.get("output") or {}
    require(output.get("path") == contact_tsv_gz.name, "contact_receipt_output_name")
    require(output.get("sha256") == sha256_file(contact_tsv_gz), "contact_receipt_output_hash")
    return payload


def validate_target_graph_receipt(path: Path, target_graph_pt: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "target_graph_receipt_missing_or_symlink")
    payload = json.loads(path.read_text())
    schema = payload.get("schema_version")
    require(schema in {
        "pvrig_v6_residue_v2_fixed_target_graphs",
        "pvrig_v6_target_graphs_esm2_650m_v2",
    }, "target_graph_receipt_schema")
    sealed = payload.get("sealed_boundary") or {}
    require(sealed.get("teacher_source_is_model_feature") is False, "target_graph_receipt_source_contract")
    require(sealed.get("candidate_docking_pose_files_opened") == 0, "target_graph_receipt_candidate_pose_contract")
    if schema == "pvrig_v6_residue_v2_fixed_target_graphs":
        require(payload.get("status") == "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED", "target_graph_receipt_status")
        observed_sha = (payload.get("outputs") or {}).get(target_graph_pt.name)
    else:
        require(payload.get("status") == "PASS_TARGET_GRAPHS_ESM2_650M_AUGMENTED", "target_graph_receipt_status")
        require(sealed.get("base_target_cache_mutated") is False, "target_graph_receipt_base_mutation_contract")
        inference = payload.get("inference") or {}
        require(
            inference.get("network_access") == "disabled"
            and int(inference.get("base_feature_dim", -1)) == 30
            and int(inference.get("plm_feature_dim", -1)) == 1280
            and int(inference.get("augmented_feature_dim", -1)) == 1310,
            "target_graph_receipt_augmentation_contract",
        )
        require(bool((payload.get("model_identity") or {}).get("model_identity_sha256")), "target_graph_receipt_model_identity")
        output = payload.get("output") or {}
        require(Path(str(output.get("relative_path", ""))).name == target_graph_pt.name, "target_graph_receipt_output_name")
        observed_sha = output.get("sha256")
    require(observed_sha == sha256_file(target_graph_pt), "target_graph_receipt_output_hash")
    return payload


def load_teacher_metadata(
    training_tsv: Path,
    rows: Sequence[v1.TrainingRow],
    preregistration: Mapping[str, Any],
    *,
    smoke_mode: bool,
) -> tuple[list[str], dict[str, Any]]:
    fields, raw = read_tsv(training_tsv)
    require(TRAIN_REQUIRED <= set(fields), f"training_audit_fields_missing:{sorted(TRAIN_REQUIRED-set(fields))}")
    by_id = {row["candidate_id"]: row for row in raw}
    require(len(by_id) == len(raw) == len(rows), "training_audit_candidate_count_or_duplicate")
    sources: list[str] = []
    parent_source: dict[str, str] = {}
    for row in rows:
        source = by_id[row.candidate_id]["teacher_source"]
        require(source in SOURCES, f"teacher_source_invalid:{row.candidate_id}:{source}")
        require(by_id[row.candidate_id]["sequence_sha256"] == row.sequence_sha256, f"audit_sequence_hash:{row.candidate_id}")
        require(by_id[row.candidate_id]["parent_framework_cluster"] == row.parent, f"audit_parent:{row.candidate_id}")
        require(int(by_id[row.candidate_id]["outer_fold"]) == row.outer_fold, f"audit_outer_fold:{row.candidate_id}")
        require(row.parent not in parent_source or parent_source[row.parent] == source, f"parent_cross_source:{row.parent}")
        parent_source[row.parent] = source
        sources.append(source)
    counts = Counter(sources)
    parent_counts = Counter(parent_source.values())
    require(set(counts) == set(SOURCES), "teacher_source_closure")
    if not smoke_mode:
        for source in SOURCES:
            expected = preregistration["sources"][source]
            require(counts[source] == int(expected["candidates"]), f"teacher_source_candidate_count:{source}")
            require(parent_counts[source] == int(expected["parent_clusters"]), f"teacher_source_parent_count:{source}")
        require(len(rows) == int(preregistration["training"]["candidate_count"]), "training_candidate_count")
        require(len(parent_source) == int(preregistration["training"]["parent_cluster_count"]), "training_parent_count")
    return sources, {
        "candidate_counts": dict(counts),
        "parent_counts": dict(parent_counts),
        "teacher_source_usage": "sampler, source-normalized loss, metrics, and audit only",
    }


def validate_outer_fold_closure(rows: Sequence[v1.TrainingRow]) -> None:
    require({row.outer_fold for row in rows} == set(range(5)), "outer_fold_closure")
    parent_folds: dict[str, set[int]] = {}
    for row in rows:
        parent_folds.setdefault(row.parent, set()).add(row.outer_fold)
    require(all(len(folds) == 1 for folds in parent_folds.values()), "outer_parent_leakage")


def load_contact_uncertainty(
    contact_tsv_gz: Path,
    rows: Sequence[v1.TrainingRow],
) -> dict[int, np.ndarray]:
    fields, raw = read_tsv(contact_tsv_gz)
    required = {
        "candidate_id", "vhh_sequence_index",
        "contact_uncertainty_weight_8x6b", "contact_uncertainty_weight_9e6y",
    }
    require(required <= set(fields), f"contact_uncertainty_fields_missing:{sorted(required-set(fields))}")
    row_by_id = {row.candidate_id: (index, row) for index, row in enumerate(rows)}
    values: dict[int, np.ndarray] = {
        index: np.full((len(row.sequence), 2), np.nan, dtype=np.float32)
        for index, row in enumerate(rows)
    }
    for source in raw:
        candidate = source["candidate_id"]
        require(candidate in row_by_id, f"uncertainty_candidate_not_training:{candidate}")
        row_index, row = row_by_id[candidate]
        residue = int(source["vhh_sequence_index"]) - 1
        require(0 <= residue < len(row.sequence), f"uncertainty_residue_index:{candidate}:{residue+1}")
        weights = np.asarray([
            float(source["contact_uncertainty_weight_8x6b"]),
            float(source["contact_uncertainty_weight_9e6y"]),
        ], dtype=np.float32)
        require(bool(np.all(np.isfinite(weights))) and bool(np.all((weights >= 0.5) & (weights <= 1.0))), f"uncertainty_weight_invalid:{candidate}:{residue+1}")
        require(bool(np.all(np.isnan(values[row_index][residue]))), f"uncertainty_duplicate_residue:{candidate}:{residue+1}")
        values[row_index][residue] = weights
    require(all(bool(np.all(np.isfinite(value))) for value in values.values()), "uncertainty_residue_closure")
    return values


class GraphCacheStore:
    """Validated random access over the ragged label-free monomer cache."""

    def __init__(self, directory: Path, rows: Sequence[v1.TrainingRow]) -> None:
        arrays, manifest, receipt = load_graph_cache(directory)
        self.arrays = arrays
        self.receipt = receipt
        self.manifest = {row["entity_id"]: row for row in manifest}
        require(len(self.manifest) == len(manifest), "graph_manifest_duplicate_entity")
        require(set(self.manifest) == {row.candidate_id for row in rows}, "graph_candidate_exact_closure")
        for row in rows:
            require(self.manifest[row.candidate_id]["sequence_sha256"] == row.sequence_sha256, f"graph_sequence_hash:{row.candidate_id}")
        self.edge_feature_dim = int(receipt["counts"]["edge_feature_dim"])

    def graph(self, candidate_id: str) -> dict[str, np.ndarray]:
        source = self.manifest[candidate_id]
        node_start, node_end = int(source["node_start"]), int(source["node_end"])
        edge_start, edge_end = int(source["edge_start"]), int(source["edge_end"])
        edge_index = self.arrays["edge_index"][:, edge_start:edge_end] - node_start
        require(bool(np.all((edge_index >= 0) & (edge_index < node_end - node_start))), f"graph_edge_bounds:{candidate_id}")
        return {
            "aa_index": self.arrays["aa_index"][node_start:node_end],
            "region_index": self.arrays["region_index"][node_start:node_end],
            "confidence": self.arrays["confidence"][node_start:node_end],
            "edge_index": edge_index,
            "edge_features": self.arrays["edge_features"][edge_start:edge_end],
        }


def _contains_forbidden_source_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower() in {"teacher_source", "source_id", "campaign_id"} or _contains_forbidden_source_key(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_source_key(item) for item in value)
    return False


def load_target_graphs(path: Path, expected_edge_dim: int) -> dict[str, dict[str, Tensor]]:
    require(path.is_file() and not path.is_symlink(), "target_graph_missing_or_symlink")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if isinstance(payload, Mapping) and "target_graphs" in payload:
        payload = payload["target_graphs"]
    require(isinstance(payload, Mapping) and set(payload) == set(RECEPTOR_NAMES), "target_graph_receptor_closure")
    require(not _contains_forbidden_source_key(payload), "teacher_source_target_feature_forbidden")
    output: dict[str, dict[str, Tensor]] = {}
    node_dim: int | None = None
    for receptor in RECEPTOR_NAMES:
        graph = payload[receptor]
        required = {"node_features", "edge_index", "edge_features", "interface_mask", "hotspot_mask"}
        require(isinstance(graph, Mapping) and required <= set(graph), f"target_graph_fields:{receptor}")
        tensors = {name: graph[name].detach().cpu() for name in required}
        require(all(isinstance(value, Tensor) for value in tensors.values()), f"target_graph_tensor:{receptor}")
        require(tensors["node_features"].ndim == 2, f"target_node_shape:{receptor}")
        node_dim = tensors["node_features"].shape[1] if node_dim is None else node_dim
        require(tensors["node_features"].shape[1] == node_dim, "target_node_dim_mismatch")
        require(tensors["edge_features"].shape[1] == expected_edge_dim, f"target_edge_dim:{receptor}")
        require(tensors["interface_mask"].shape == tensors["hotspot_mask"].shape == (len(tensors["node_features"]),), f"target_mask_shape:{receptor}")
        output[receptor] = tensors
    return output


class PairTargetStore:
    """Canonical sparse pair targets with explicitly contracted exact-zero absence."""

    def __init__(self, path: Path, rows: Sequence[v1.TrainingRow], target_nodes: Mapping[str, int]) -> None:
        fields, raw = read_tsv(path)
        target_index_field = "pvrig_node_index" if "pvrig_node_index" in fields else "pvrig_sequence_index"
        require(PAIR_REQUIRED <= set(fields) and target_index_field in fields, f"pair_fields_missing:{sorted(PAIR_REQUIRED-set(fields))}")
        by_id = {row.candidate_id: (index, row) for index, row in enumerate(rows)}
        self.values: dict[tuple[int, str, int, int], tuple[float, float, bool]] = {}
        sparse_by_group: defaultdict[tuple[int, str], list[tuple[int, int, float, float, bool]]] = defaultdict(list)
        observed_candidate_receptors: set[tuple[int, str]] = set()
        for source in raw:
            candidate = source["candidate_id"]
            require(candidate in by_id, f"pair_candidate_not_training:{candidate}")
            row_index, row = by_id[candidate]
            require(source["sequence_sha256"] == row.sequence_sha256, f"pair_sequence_hash:{candidate}")
            require(source["parent_framework_cluster"] == row.parent, f"pair_parent:{candidate}")
            receptor = source["receptor"].lower()
            require(receptor in RECEPTOR_NAMES, f"pair_receptor:{candidate}:{receptor}")
            require(source["pair_table_semantics"] == "SPARSE_ABSENCE_IS_EXACT_ZERO", f"pair_sparse_semantics:{candidate}")
            vhh_index = int(source["vhh_sequence_index"]) - 1
            target_index = int(source[target_index_field]) - 1
            require(0 <= vhh_index < len(row.sequence), f"pair_vhh_index:{candidate}")
            require(0 <= target_index < target_nodes[receptor], f"pair_target_index:{candidate}")
            value = float(source["contact_target"])
            weight = float(source["contact_uncertainty_weight"])
            mask = bool(int(source["target_mask"]))
            require(math.isfinite(value) and 0.0 <= value <= 1.0, f"pair_target_invalid:{candidate}")
            require(math.isfinite(weight) and 0.5 <= weight <= 1.0, f"pair_weight_invalid:{candidate}")
            key = (row_index, receptor, vhh_index, target_index)
            require(key not in self.values, f"pair_duplicate:{key}")
            self.values[key] = (value, weight, mask)
            sparse_by_group[(row_index, receptor)].append((vhh_index, target_index, value, weight, mask))
            observed_candidate_receptors.add((row_index, receptor))
        require(self.values, "pair_targets_empty")
        require(
            observed_candidate_receptors == {(index, receptor) for index in range(len(rows)) for receptor in RECEPTOR_NAMES},
            "pair_candidate_receptor_closure",
        )
        self.sparse_by_group: dict[tuple[int, str], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
        for group, entries in sparse_by_group.items():
            ordered = sorted(entries, key=lambda item: (item[0], item[1]))
            self.sparse_by_group[group] = (
                np.asarray([item[0] for item in ordered], dtype=np.int64),
                np.asarray([item[1] for item in ordered], dtype=np.int64),
                np.asarray([item[2] for item in ordered], dtype=np.float32),
                np.asarray([item[3] for item in ordered], dtype=np.float32),
                np.asarray([item[4] for item in ordered], dtype=np.bool_),
            )


class V2Collator:
    def __init__(
        self,
        rows: Sequence[v1.TrainingRow],
        tokenizer: Any,
        bases: Mapping[int, np.ndarray],
        teacher_sources: Sequence[str],
        contact_uncertainty: Mapping[int, np.ndarray],
        *,
        graph_store: GraphCacheStore | None,
        pair_store: PairTargetStore | None,
        target_nodes: Mapping[str, int],
    ) -> None:
        require(len(rows) == len(teacher_sources), "collator_source_length")
        self.rows = rows
        self.base = v1.Collator(rows, tokenizer, bases)
        self.teacher_sources = list(teacher_sources)
        self.contact_uncertainty = contact_uncertainty
        self.graph_store = graph_store
        self.pair_store = pair_store
        self.target_nodes = dict(target_nodes)

    def __call__(self, indices: Sequence[int]) -> dict[str, Any]:
        batch = self.base(indices)
        batch["teacher_sources"] = [self.teacher_sources[index] for index in indices]
        # Preserve the original double-precision TSV values for the collector's
        # exact truth closure; model tensors remain float32/bfloat16.
        batch["target_exact"] = [self.rows[index].targets[2] for index in indices]
        contact_uncertainty = torch.ones_like(batch["contact_targets"])
        positions_by_item: list[Tensor] = []
        for item, index in enumerate(indices):
            positions = batch["residue_mask"][item].nonzero(as_tuple=False).flatten()
            positions_by_item.append(positions)
            contact_uncertainty[item, positions] = torch.tensor(self.contact_uncertainty[index])
        batch["contact_uncertainty"] = contact_uncertainty
        if self.graph_store is not None:
            batch_size, token_width = batch["input_ids"].shape
            aa = torch.zeros((batch_size, token_width), dtype=torch.long)
            region = torch.zeros((batch_size, token_width), dtype=torch.long)
            confidence = torch.zeros((batch_size, token_width), dtype=torch.float32)
            edge_indices: list[Tensor] = []
            edge_features: list[Tensor] = []
            for item, (index, positions) in enumerate(zip(indices, positions_by_item)):
                graph = self.graph_store.graph(self.rows[index].candidate_id)
                require(len(positions) == len(graph["aa_index"]), f"graph_token_alignment:{self.rows[index].candidate_id}")
                aa[item, positions] = torch.tensor(graph["aa_index"], dtype=torch.long)
                region[item, positions] = torch.tensor(graph["region_index"], dtype=torch.long)
                confidence[item, positions] = torch.tensor(graph["confidence"], dtype=torch.float32)
                local_edges = torch.tensor(graph["edge_index"], dtype=torch.long)
                translated = torch.stack((positions[local_edges[0]], positions[local_edges[1]])) + item * token_width
                edge_indices.append(translated)
                edge_features.append(torch.tensor(graph["edge_features"], dtype=torch.float32))
            batch.update({
                "vhh_aa_index": aa,
                "vhh_region_index": region,
                "vhh_confidence": confidence,
                "vhh_edge_index": torch.cat(edge_indices, dim=1),
                "vhh_edge_features": torch.cat(edge_features, dim=0),
            })
        if self.pair_store is not None:
            for receptor in RECEPTOR_NAMES:
                nodes = self.target_nodes[receptor]
                target = torch.zeros((*batch["input_ids"].shape, nodes), dtype=torch.float32)
                weight = torch.ones_like(target)
                mask = torch.zeros_like(target, dtype=torch.bool)
                for item, (index, positions) in enumerate(zip(indices, positions_by_item)):
                    # The canonical sparse table explicitly contracts every
                    # omitted residue pair as an observed exact zero. Padding
                    # remains unavailable.
                    mask[item, positions, :] = True
                    residue_index, target_index, sparse_target, sparse_weight, sparse_mask = self.pair_store.sparse_by_group[(index, receptor)]
                    if len(residue_index):
                        token_index = positions[torch.from_numpy(residue_index)]
                        target_node_index = torch.from_numpy(target_index)
                        target[item, token_index, target_node_index] = torch.from_numpy(sparse_target)
                        weight[item, token_index, target_node_index] = torch.from_numpy(sparse_weight)
                        mask[item, token_index, target_node_index] = torch.from_numpy(sparse_mask)
                batch[f"pair_targets_{receptor}"] = target
                batch[f"pair_uncertainty_{receptor}"] = weight
                batch[f"pair_mask_{receptor}"] = mask
        return batch


class VHHGraphOnlyHead(nn.Module):
    """Lane B: add the label-free VHH graph without target conditioning."""

    def __init__(self, config: ResidueV2Config) -> None:
        super().__init__()
        config.validate()
        self.config = config
        hidden = config.graph_hidden_dim
        self.aa_embedding = nn.Embedding(config.aa_vocab_size, config.aa_embedding_dim)
        self.region_embedding = nn.Embedding(config.region_vocab_size, config.region_embedding_dim)
        input_dim = config.backbone_hidden_size + config.aa_embedding_dim + config.region_embedding_dim + 1
        self.vhh_graph_encoder = InvariantGraphEncoder(
            input_dim, hidden, config.edge_feature_dim, config.vhh_graph_layers, config.dropout,
        )
        self.marginal_head = nn.Linear(hidden, 2)
        self.structure_projection = nn.Sequential(nn.LayerNorm(config.structure_dim), nn.Linear(config.structure_dim, hidden), nn.GELU())
        self.residual_head = nn.Sequential(
            nn.LayerNorm(hidden * 4 + 3), nn.Linear(hidden * 4 + 3, hidden), nn.GELU(),
            nn.Dropout(config.dropout), nn.Linear(hidden, 3),
        )

    def forward(
        self,
        token_states: Tensor,
        residue_mask: Tensor,
        vhh_aa_index: Tensor,
        vhh_region_index: Tensor,
        vhh_confidence: Tensor,
        vhh_edge_index: Tensor,
        vhh_edge_features: Tensor,
        structure_features: Tensor,
        m2_base: Tensor,
    ) -> dict[str, Tensor]:
        batch, length, _ = token_states.shape
        if vhh_confidence.ndim == 2:
            vhh_confidence = vhh_confidence.unsqueeze(-1)
        features = torch.cat((
            token_states,
            self.aa_embedding(vhh_aa_index),
            self.region_embedding(vhh_region_index),
            vhh_confidence.to(token_states.dtype),
        ), dim=-1)
        states = self.vhh_graph_encoder(features.reshape(batch * length, -1), vhh_edge_index, vhh_edge_features).reshape(batch, length, -1)
        logits = self.marginal_head(states)
        mask = residue_mask.to(states.dtype).unsqueeze(-1)
        global_pool = (states * mask).sum(1) / mask.sum(1).clamp_min(1.0)
        probabilities = torch.sigmoid(logits) * residue_mask.unsqueeze(-1).to(states.dtype)
        pools = []
        for channel in range(2):
            weights = probabilities[:, :, channel]
            pools.append((states * weights.unsqueeze(-1)).sum(1) / weights.sum(1, keepdim=True).clamp_min(1e-6))
        structure = self.structure_projection(structure_features)
        raw = self.residual_head(torch.cat((global_pool, pools[0], pools[1], structure, m2_base), dim=-1))
        residual = self.config.residual_scale * torch.tanh(raw)
        return {
            "prediction": m2_base + residual,
            "m2_base": m2_base,
            "residual": residual,
            "marginal_contact_logits": logits,
            "marginal_contact_probabilities": probabilities,
        }


class VHHGraphOnlySurrogate(nn.Module):
    def __init__(self, backbone: nn.Module, head: VHHGraphOnlyHead) -> None:
        super().__init__()
        self.backbone = backbone
        self.head = head
        for parameter in self.backbone.parameters():
            parameter.requires_grad_(False)

    def forward(self, batch: Mapping[str, Any]) -> dict[str, Tensor]:
        self.backbone.eval()
        with torch.no_grad():
            states = backbone_states(self.backbone, batch["input_ids"], batch["attention_mask"])
        return self.head(
            states, batch["residue_mask"], batch["vhh_aa_index"], batch["vhh_region_index"],
            batch["vhh_confidence"], batch["vhh_edge_index"], batch["vhh_edge_features"],
            batch["structure"], batch["m2_base"],
        )


def load_frozen_backbone(args: argparse.Namespace) -> tuple[nn.Module, Any, int, str]:
    if args.backbone_kind == "tiny":
        tokenizer = v1.TinyTokenizer()
        backbone = v1.TinyBackbone(len(tokenizer), args.tiny_hidden_size)
        identity = "tiny_synthetic"
        hidden = args.tiny_hidden_size
    else:
        require(args.model_path is not None and args.model_path.is_dir() and not args.model_path.is_symlink(), "local_model_directory_required")
        require(args.model_identity_file is not None and args.model_identity_file.is_file() and not args.model_identity_file.is_symlink(), "model_identity_file_required")
        identity = sha256_file(args.model_identity_file)
        require(args.expected_model_sha256 and identity == args.expected_model_sha256, "model_identity_sha256_mismatch")
        try:
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:
            raise TrainerV2Error("transformers_required") from error
        tokenizer = AutoTokenizer.from_pretrained(str(args.model_path), local_files_only=True, trust_remote_code=args.trust_remote_code)
        backbone = AutoModel.from_pretrained(str(args.model_path), local_files_only=True, trust_remote_code=args.trust_remote_code)
        hidden = getattr(backbone.config, "hidden_size", None) or getattr(backbone.config, "d_model", None)
        require(hidden is not None, "backbone_hidden_size_missing")
    for parameter in backbone.parameters():
        parameter.requires_grad_(False)
    return backbone, tokenizer, int(hidden), identity


def build_model(
    args: argparse.Namespace,
    *,
    edge_feature_dim: int,
    target_node_dim: int,
    device: torch.device,
) -> tuple[nn.Module, Any, dict[str, Any]]:
    assert_teacher_source_not_model_feature([
        "sequence", "frozen_plm_residue_state", "aa_index", "region_index", "confidence",
        "invariant_edge_features", "structure_features", "m2_base", "fixed_target_graphs",
    ])
    backbone, tokenizer, hidden, identity = load_frozen_backbone(args)
    if args.lane == "A_DOMAIN":
        config = ResidueHeadConfig(
            backbone_hidden_size=hidden,
            structure_dim=args.structure_dim,
            fusion_dim=args.graph_hidden_dim,
            dropout=args.dropout,
            residual_scale=args.residual_scale,
            detach_contact_pooling=False,
        )
        model: nn.Module = ResidueSurrogate(backbone, DualContactResidualHead(config), backbone_mode="frozen")
        contract = {"lane": args.lane, "head": asdict(config), "architecture": "frozen_v1_5_sequence_head"}
    else:
        config_v2 = ResidueV2Config(
            backbone_hidden_size=hidden,
            target_node_dim=target_node_dim,
            structure_dim=args.structure_dim,
            edge_feature_dim=edge_feature_dim,
            graph_hidden_dim=args.graph_hidden_dim,
            dropout=args.dropout,
            residual_scale=args.residual_scale,
        )
        if args.lane == "B_VHH3D":
            model = VHHGraphOnlySurrogate(backbone, VHHGraphOnlyHead(config_v2))
            contract = {"lane": args.lane, "model": asdict(config_v2), "architecture": "vhh_graph_without_target_conditioning"}
        else:
            model = ResidueV2Surrogate(backbone, TargetConditionedResidueV2Head(config_v2))
            contract = {"lane": args.lane, **model_contract(config_v2)}
    model.to(device)
    require(not any(parameter.requires_grad for parameter in model.backbone.parameters()), "backbone_not_frozen")  # type: ignore[attr-defined]
    contract["backbone_identity"] = identity
    contract["checkpoint_policy"] = "head_only_no_backbone_no_optimizer"
    return model, tokenizer, contract


def head_checkpoint_state(model: nn.Module) -> dict[str, Tensor]:
    if isinstance(model, ResidueV2Surrogate):
        state = trainable_checkpoint_state(model)
    else:
        state = {
            name: parameter.detach().cpu().clone()
            for name, parameter in model.named_parameters()
            if parameter.requires_grad
        }
    require(state and all(name.startswith("head.") for name in state), "checkpoint_not_head_only")
    return state


def load_head_checkpoint_state(model: nn.Module, state: Mapping[str, Tensor]) -> None:
    expected = head_checkpoint_state(model)
    require(set(state) == set(expected), f"head_checkpoint_key_closure:missing={sorted(set(expected)-set(state))}:extra={sorted(set(state)-set(expected))}")
    current = model.state_dict()
    for name, value in state.items():
        require(current[name].shape == value.shape, f"head_checkpoint_shape:{name}")
        current[name] = value.to(dtype=current[name].dtype, device=current[name].device)
    model.load_state_dict(current, strict=True)


def forward_model(
    model: nn.Module,
    lane: str,
    batch: Mapping[str, Any],
    target_graphs: Mapping[str, Mapping[str, Tensor]] | None,
) -> dict[str, Tensor]:
    require("teacher_source" not in batch, "teacher_source_model_feature_forbidden")
    if target_graphs is not None:
        require("teacher_source" not in target_graphs, "teacher_source_target_feature_forbidden")
    if lane == "A_DOMAIN":
        return model(batch["input_ids"], batch["attention_mask"], batch["residue_mask"], batch["structure"], batch["m2_base"])  # type: ignore[operator]
    if lane == "B_VHH3D":
        return model(batch)  # type: ignore[operator]
    require(target_graphs is not None, "target_graphs_required")
    return model(  # type: ignore[operator]
        batch["input_ids"], batch["attention_mask"], batch["residue_mask"],
        batch["vhh_aa_index"], batch["vhh_region_index"], batch["vhh_confidence"],
        batch["vhh_edge_index"], batch["vhh_edge_features"], target_graphs,
        batch["structure"], batch["m2_base"],
    )


def _per_candidate_masked_mean(values: Tensor, weights: Tensor, mask: Tensor) -> tuple[Tensor, Tensor]:
    require(values.shape == weights.shape == mask.shape and values.ndim >= 2, "masked_component_shape")
    flattened_values = values.reshape(len(values), -1)
    flattened_weights = (weights * mask.to(weights.dtype)).reshape(len(values), -1)
    available = flattened_weights.sum(1) > 0
    result = (flattened_values * flattened_weights).sum(1) / flattened_weights.sum(1).clamp_min(torch.finfo(values.dtype).eps)
    return result, available


def balanced_soft_bce_per_candidate_receptor(
    logits: Tensor,
    targets: Tensor,
    uncertainty_weights: Tensor,
    mask: Tensor,
    *,
    positive_class_fraction: float,
    epsilon: float,
) -> tuple[Tensor, Tensor, dict[str, Tensor]]:
    """Balance soft positive and negative BCE mass within one receptor.

    Inputs begin with the candidate dimension and contain only one receptor.
    A soft target contributes ``target`` positive mass and ``1-target``
    negative mass.  Therefore an exact zero remains an observed negative, but
    the number of zeros cannot overwhelm the positive term.  If a candidate
    has only one class, its available class receives full weight rather than
    being halved or imputed.
    """

    require(
        logits.shape == targets.shape == uncertainty_weights.shape == mask.shape
        and logits.ndim >= 2,
        "balanced_contact_shape",
    )
    require(0.0 < positive_class_fraction < 1.0, "contact_positive_class_fraction_range")
    require(math.isfinite(epsilon) and epsilon > 0.0, "contact_balance_epsilon_range")
    require(bool(torch.all(torch.isfinite(logits))), "contact_logits_nonfinite")
    require(bool(torch.all(torch.isfinite(targets))), "contact_targets_nonfinite")
    require(bool(torch.all((targets >= 0.0) & (targets <= 1.0))), "contact_targets_range")
    require(bool(torch.all(torch.isfinite(uncertainty_weights))), "contact_uncertainty_nonfinite")
    require(bool(torch.all(uncertainty_weights >= 0.0)), "contact_uncertainty_negative")
    flat_logits = logits.reshape(len(logits), -1)
    flat_targets = targets.to(dtype=logits.dtype).reshape(len(logits), -1)
    flat_weights = (
        uncertainty_weights.to(dtype=logits.dtype) * mask.to(dtype=logits.dtype)
    ).reshape(len(logits), -1)
    positive_weights = flat_weights * flat_targets
    negative_weights = flat_weights * (1.0 - flat_targets)
    positive_mass = positive_weights.sum(1)
    negative_mass = negative_weights.sum(1)
    has_positive = positive_mass > epsilon
    has_negative = negative_mass > epsilon
    available = has_positive | has_negative
    positive_mean = (
        F.softplus(-flat_logits) * positive_weights
    ).sum(1) / positive_mass.clamp_min(epsilon)
    negative_mean = (
        F.softplus(flat_logits) * negative_weights
    ).sum(1) / negative_mass.clamp_min(epsilon)
    both = has_positive & has_negative
    positive_only = has_positive & ~has_negative
    negative_only = has_negative & ~has_positive
    result = torch.zeros_like(positive_mean)
    result = torch.where(
        both,
        positive_class_fraction * positive_mean + (1.0 - positive_class_fraction) * negative_mean,
        result,
    )
    result = torch.where(positive_only, positive_mean, result)
    result = torch.where(negative_only, negative_mean, result)
    audit = {
        "positive_mass": positive_mass.sum(),
        "negative_mass": negative_mass.sum(),
        "both_class_candidates": both.to(logits.dtype).sum(),
        "positive_only_candidates": positive_only.to(logits.dtype).sum(),
        "negative_only_candidates": negative_only.to(logits.dtype).sum(),
        "unavailable_candidates": (~available).to(logits.dtype).sum(),
    }
    return result, available, audit


def _mean_receptor_losses(values: Sequence[Tensor], availability: Sequence[Tensor]) -> tuple[Tensor, Tensor]:
    require(len(values) == len(availability) == len(RECEPTOR_NAMES), "contact_receptor_count")
    stacked_values = torch.stack(tuple(values), dim=1)
    stacked_available = torch.stack(tuple(availability), dim=1)
    require(stacked_values.shape == stacked_available.shape, "contact_receptor_shape")
    weights = stacked_available.to(stacked_values.dtype)
    result = (stacked_values * weights).sum(1) / weights.sum(1).clamp_min(1.0)
    # Dual-receptor supervision remains unavailable if either receptor has no
    # observed class mass; no missing receptor is silently imputed.
    return result, stacked_available.all(1)


def contact_loss_amendment_contract(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": CONTACT_LOSS_AMENDMENT_SCHEMA,
        "normalization": CONTACT_LOSS_NORMALIZATION,
        "positive_class_fraction": args.contact_positive_class_fraction,
        "epsilon": args.contact_balance_epsilon,
        "gradient_telemetry_batches_per_epoch": args.component_gradient_telemetry_batches,
        "marginal_contact_weight": args.marginal_contact_weight,
        "pair_contact_weight": args.pair_contact_weight,
        "exact_zero_is_observed_negative": True,
        "soft_target_contributes_positive_and_negative_mass": True,
        "class_missing_policy": "available_class_receives_full_weight; both_missing_is_unavailable",
        "source_normalization": "0.5*V4D+0.5*V4H after candidate/receptor reduction",
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def validate_contact_loss_amendment(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Validate the independent, pre-formal contact-loss amendment.

    The original Residue V2 preregistration remains byte-identical.  This
    amendment is the sole authority for contact normalization, telemetry, and
    the calibrated marginal/pair weights used by a formal invocation.
    """

    require(path.is_file() and not path.is_symlink(), "contact_loss_amendment_missing_or_symlink")
    payload = json.loads(path.read_text())
    require(isinstance(payload, Mapping), "contact_loss_amendment_not_object")
    required = {
        "schema_version", "status", "normalization", "positive_class_fraction", "epsilon",
        "gradient_telemetry_batches_per_epoch", "marginal_contact_weight", "pair_contact_weight",
        "exact_zero_is_observed_negative", "soft_target_contributes_positive_and_negative_mass",
        "class_missing_policy", "source_normalization", "calibration",
    }
    require(set(payload) == required, "contact_loss_amendment_field_closure")
    require(payload.get("schema_version") == CONTACT_LOSS_AMENDMENT_SCHEMA, "contact_loss_amendment_schema")
    require(payload.get("status") == CONTACT_LOSS_AMENDMENT_STATUS, "contact_loss_amendment_status")
    expected = contact_loss_amendment_contract(args)
    for name, value in expected.items():
        require(payload.get(name) == value, f"contact_loss_amendment_mismatch:{name}")

    calibration = payload.get("calibration")
    require(isinstance(calibration, Mapping), "contact_loss_calibration_not_object")
    calibration_required = {
        "schema_version", "status", "grid", "selection_rule", "target_fraction_min",
        "target_fraction_max", "hard_ceiling", "selected_grid_index", "selected_weights",
        "grid_results", "open_only", "optimizer_steps_before_observation",
        "gradient_batches_per_lane", "v4_f_test32_access_count", "input_hashes",
    }
    require(set(calibration) == calibration_required, "contact_loss_calibration_field_closure")
    require(calibration.get("schema_version") == "pvrig_v6_residue_v2_contact_gradient_calibration_v1", "contact_loss_calibration_schema")
    require(calibration.get("status") == "PASS_OPEN_ONLY_ONE_BATCH_PRESTEP_GRADIENT_CALIBRATION", "contact_loss_calibration_status")
    require(calibration.get("selection_rule") == "smallest_grid_entry_with_all_lanes_in_target_band_and_no_lane_above_hard_ceiling", "contact_loss_calibration_selection_rule")
    require(float(calibration.get("target_fraction_min", -1.0)) == CONTACT_GRADIENT_TARGET_MIN, "contact_loss_calibration_target_min")
    require(float(calibration.get("target_fraction_max", -1.0)) == CONTACT_GRADIENT_TARGET_MAX, "contact_loss_calibration_target_max")
    require(float(calibration.get("hard_ceiling", -1.0)) == CONTACT_GRADIENT_HARD_MAX, "contact_loss_calibration_hard_max")
    require(calibration.get("open_only") is True, "contact_loss_calibration_not_open_only")
    require(int(calibration.get("optimizer_steps_before_observation", -1)) == 0, "contact_loss_calibration_post_optimizer")
    require(int(calibration.get("gradient_batches_per_lane", -1)) == 1, "contact_loss_calibration_batch_count")
    require(int(calibration.get("v4_f_test32_access_count", -1)) == 0, "contact_loss_calibration_sealed_access")
    expected_grid = [
        {"marginal_contact_weight": marginal, "pair_contact_weight": pair}
        for marginal, pair in CONTACT_GRADIENT_GRID
    ]
    require(calibration.get("grid") == expected_grid, "contact_loss_calibration_grid")
    grid_results = calibration.get("grid_results")
    require(isinstance(grid_results, list) and len(grid_results) == len(CONTACT_GRADIENT_GRID), "contact_loss_calibration_grid_results")
    passing_indices: list[int] = []
    for index, ((marginal, pair), result) in enumerate(zip(CONTACT_GRADIENT_GRID, grid_results, strict=True)):
        require(isinstance(result, Mapping), f"contact_loss_calibration_grid_result_object:{index}")
        require(set(result) == {
            "grid_index", "marginal_contact_weight", "pair_contact_weight",
            "lane_direct_contact_gradient_fractions", "all_lanes_in_target_band", "hard_ceiling_pass",
        }, f"contact_loss_calibration_grid_result_fields:{index}")
        require(int(result.get("grid_index", -1)) == index, f"contact_loss_calibration_grid_index:{index}")
        require(float(result.get("marginal_contact_weight", -1.0)) == marginal, f"contact_loss_calibration_marginal:{index}")
        require(float(result.get("pair_contact_weight", -1.0)) == pair, f"contact_loss_calibration_pair:{index}")
        fractions = result.get("lane_direct_contact_gradient_fractions")
        require(isinstance(fractions, Mapping) and set(fractions) == set(LANES), f"contact_loss_calibration_lane_closure:{index}")
        values = [float(fractions[lane]) for lane in LANES]
        require(all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values), f"contact_loss_calibration_fraction_range:{index}")
        target_pass = all(CONTACT_GRADIENT_TARGET_MIN <= value <= CONTACT_GRADIENT_TARGET_MAX for value in values)
        hard_pass = all(value <= CONTACT_GRADIENT_HARD_MAX for value in values)
        require(result.get("all_lanes_in_target_band") is target_pass, f"contact_loss_calibration_target_flag:{index}")
        require(result.get("hard_ceiling_pass") is hard_pass, f"contact_loss_calibration_hard_flag:{index}")
        if target_pass and hard_pass:
            passing_indices.append(index)
    require(bool(passing_indices), "contact_loss_calibration_no_passing_grid")
    selected_index = int(calibration.get("selected_grid_index", -1))
    require(selected_index == passing_indices[0], "contact_loss_calibration_not_smallest_passing_grid")
    selected_marginal, selected_pair = CONTACT_GRADIENT_GRID[selected_index]
    require(calibration.get("selected_weights") == {
        "marginal_contact_weight": selected_marginal,
        "pair_contact_weight": selected_pair,
    }, "contact_loss_calibration_selected_weights")
    require(float(payload["marginal_contact_weight"]) == selected_marginal, "contact_loss_amendment_final_marginal_weight")
    require(float(payload["pair_contact_weight"]) == selected_pair, "contact_loss_amendment_final_pair_weight")
    input_hashes = calibration.get("input_hashes")
    require(isinstance(input_hashes, Mapping) and set(input_hashes) == set(LANES), "contact_loss_calibration_input_hash_closure")
    require(all(_is_sha256(input_hashes[lane]) for lane in LANES), "contact_loss_calibration_input_hash")
    return dict(payload)


def validate_contact_loss_amendment_v2_2(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Validate the production lane-specific V2.2 amendment.

    V1 remains readable by ``validate_contact_loss_amendment`` for historical
    compatibility, but formal training is authorized only by this schema.
    """

    require(path.is_file() and not path.is_symlink(), "contact_loss_amendment_missing_or_symlink")
    payload = json.loads(path.read_text())
    require(isinstance(payload, Mapping), "contact_loss_amendment_v2_2_not_object")
    required = {
        "schema_version", "status", "normalization", "positive_class_fraction", "epsilon",
        "gradient_telemetry_batches_per_epoch", "lane_weights",
        "exact_zero_is_observed_negative", "soft_target_contributes_positive_and_negative_mass",
        "class_missing_policy", "source_normalization", "calibration",
    }
    require(set(payload) == required, "contact_loss_amendment_v2_2_field_closure")
    require(payload.get("schema_version") == CONTACT_LOSS_AMENDMENT_SCHEMA_V2_2, "contact_loss_amendment_v2_2_schema")
    require(payload.get("status") == CONTACT_LOSS_AMENDMENT_STATUS, "contact_loss_amendment_v2_2_status")
    semantic = contact_loss_amendment_contract(args)
    for name in (
        "normalization", "positive_class_fraction", "epsilon", "gradient_telemetry_batches_per_epoch",
        "exact_zero_is_observed_negative", "soft_target_contributes_positive_and_negative_mass",
        "class_missing_policy", "source_normalization",
    ):
        require(payload.get(name) == semantic[name], f"contact_loss_amendment_v2_2_mismatch:{name}")

    lane_weights = payload.get("lane_weights")
    require(isinstance(lane_weights, Mapping) and set(lane_weights) == set(LANES), "contact_loss_amendment_v2_2_lane_closure")
    normalized_lane_weights: dict[str, dict[str, float]] = {}
    for lane in LANES:
        weights = lane_weights[lane]
        require(isinstance(weights, Mapping) and set(weights) == {
            "marginal_contact_weight", "pair_contact_weight",
        }, f"contact_loss_amendment_v2_2_lane_weight_fields:{lane}")
        marginal = float(weights["marginal_contact_weight"])
        pair = float(weights["pair_contact_weight"])
        require(marginal in CONTACT_GRADIENT_GRID_V2_2, f"contact_loss_amendment_v2_2_marginal_grid:{lane}")
        require(pair == marginal / 2.0, f"contact_loss_amendment_v2_2_pair_ratio:{lane}")
        normalized_lane_weights[lane] = {
            "marginal_contact_weight": marginal,
            "pair_contact_weight": pair,
        }
    selected_for_run = normalized_lane_weights[args.lane]
    require(float(args.marginal_contact_weight) == selected_for_run["marginal_contact_weight"], "contact_loss_amendment_v2_2_current_lane_marginal")
    require(float(args.pair_contact_weight) == selected_for_run["pair_contact_weight"], "contact_loss_amendment_v2_2_current_lane_pair")

    calibration = payload.get("calibration")
    require(isinstance(calibration, Mapping), "contact_loss_calibration_v2_2_not_object")
    calibration_required = {
        "schema_version", "status", "grid", "selection_rule", "target_fraction_min",
        "target_fraction_max", "hard_ceiling", "lane_selected_grid_index", "lane_weights",
        "lane_grid_results", "open_only", "optimizer_steps_before_observation",
        "gradient_batches_per_lane", "v4_f_test32_access_count", "input_hashes",
    }
    require(set(calibration) == calibration_required, "contact_loss_calibration_v2_2_field_closure")
    require(calibration.get("schema_version") == "pvrig_v6_residue_v2_contact_gradient_calibration_v2_2", "contact_loss_calibration_v2_2_schema")
    require(calibration.get("status") == "PASS_OPEN_ONLY_ONE_BATCH_PRESTEP_LANE_SPECIFIC_GRADIENT_CALIBRATION", "contact_loss_calibration_v2_2_status")
    require(calibration.get("selection_rule") == "per_lane_smallest_grid_entry_in_target_band_and_below_hard_ceiling", "contact_loss_calibration_v2_2_selection_rule")
    require(float(calibration.get("target_fraction_min", -1.0)) == CONTACT_GRADIENT_TARGET_MIN, "contact_loss_calibration_v2_2_target_min")
    require(float(calibration.get("target_fraction_max", -1.0)) == CONTACT_GRADIENT_TARGET_MAX, "contact_loss_calibration_v2_2_target_max")
    require(float(calibration.get("hard_ceiling", -1.0)) == CONTACT_GRADIENT_HARD_MAX, "contact_loss_calibration_v2_2_hard_max")
    require(calibration.get("open_only") is True, "contact_loss_calibration_v2_2_not_open_only")
    require(int(calibration.get("optimizer_steps_before_observation", -1)) == 0, "contact_loss_calibration_v2_2_post_optimizer")
    require(int(calibration.get("gradient_batches_per_lane", -1)) == 1, "contact_loss_calibration_v2_2_batch_count")
    require(int(calibration.get("v4_f_test32_access_count", -1)) == 0, "contact_loss_calibration_v2_2_sealed_access")
    expected_grid = [
        {"marginal_contact_weight": marginal, "pair_contact_weight": marginal / 2.0}
        for marginal in CONTACT_GRADIENT_GRID_V2_2
    ]
    require(calibration.get("grid") == expected_grid, "contact_loss_calibration_v2_2_grid")
    selected_indices = calibration.get("lane_selected_grid_index")
    results_by_lane = calibration.get("lane_grid_results")
    require(isinstance(selected_indices, Mapping) and set(selected_indices) == set(LANES), "contact_loss_calibration_v2_2_selected_lane_closure")
    require(isinstance(results_by_lane, Mapping) and set(results_by_lane) == set(LANES), "contact_loss_calibration_v2_2_result_lane_closure")
    for lane in LANES:
        results = results_by_lane[lane]
        require(isinstance(results, list) and len(results) == len(CONTACT_GRADIENT_GRID_V2_2), f"contact_loss_calibration_v2_2_grid_results:{lane}")
        passing: list[int] = []
        for index, (marginal, result) in enumerate(zip(CONTACT_GRADIENT_GRID_V2_2, results, strict=True)):
            require(isinstance(result, Mapping) and set(result) == {
                "grid_index", "marginal_contact_weight", "pair_contact_weight",
                "direct_contact_gradient_fraction", "in_target_band", "hard_ceiling_pass",
            }, f"contact_loss_calibration_v2_2_result_fields:{lane}:{index}")
            pair = marginal / 2.0
            require(int(result.get("grid_index", -1)) == index, f"contact_loss_calibration_v2_2_grid_index:{lane}:{index}")
            require(float(result.get("marginal_contact_weight", -1.0)) == marginal, f"contact_loss_calibration_v2_2_marginal:{lane}:{index}")
            require(float(result.get("pair_contact_weight", -1.0)) == pair, f"contact_loss_calibration_v2_2_pair:{lane}:{index}")
            fraction = float(result.get("direct_contact_gradient_fraction", -1.0))
            require(math.isfinite(fraction) and 0.0 <= fraction <= 1.0, f"contact_loss_calibration_v2_2_fraction:{lane}:{index}")
            target_pass = CONTACT_GRADIENT_TARGET_MIN <= fraction <= CONTACT_GRADIENT_TARGET_MAX
            hard_pass = fraction <= CONTACT_GRADIENT_HARD_MAX
            require(result.get("in_target_band") is target_pass, f"contact_loss_calibration_v2_2_target_flag:{lane}:{index}")
            require(result.get("hard_ceiling_pass") is hard_pass, f"contact_loss_calibration_v2_2_hard_flag:{lane}:{index}")
            if target_pass and hard_pass:
                passing.append(index)
        require(bool(passing), f"contact_loss_calibration_v2_2_no_passing_grid:{lane}")
        selected_index = int(selected_indices[lane])
        require(selected_index == passing[0], f"contact_loss_calibration_v2_2_not_smallest:{lane}")
        selected_marginal = CONTACT_GRADIENT_GRID_V2_2[selected_index]
        require(normalized_lane_weights[lane] == {
            "marginal_contact_weight": selected_marginal,
            "pair_contact_weight": selected_marginal / 2.0,
        }, f"contact_loss_calibration_v2_2_selected_weight:{lane}")
    require(calibration.get("lane_weights") == normalized_lane_weights, "contact_loss_calibration_v2_2_lane_weights")
    input_hashes = calibration.get("input_hashes")
    require(isinstance(input_hashes, Mapping) and set(input_hashes) == set(LANES), "contact_loss_calibration_v2_2_input_hash_closure")
    require(all(_is_sha256(input_hashes[lane]) for lane in LANES), "contact_loss_calibration_v2_2_input_hash")
    return dict(payload)


def loss_component_weights(args: argparse.Namespace, lane: str) -> dict[str, float]:
    weights = {
        "dual": float(args.dual_weight),
        "receptor": float(args.receptor_weight),
        "marginal": float(args.marginal_contact_weight),
        "ranking": float(args.ranking_weight),
        "residual": float(args.residual_l2_weight),
    }
    if lane == "D_FULL_PAIR":
        weights["pair"] = float(args.pair_contact_weight)
    return weights


def per_candidate_ranking_loss(
    prediction: Tensor,
    target: Tensor,
    parents: Sequence[str],
    *,
    minimum_delta: float,
    temperature: float,
) -> Tensor:
    result = prediction * 0.0
    counts = torch.zeros_like(prediction)
    for left in range(len(prediction)):
        for right in range(left + 1, len(prediction)):
            if parents[left] != parents[right]:
                continue
            delta = target[left] - target[right]
            if abs(float(delta.detach())) < minimum_delta:
                continue
            value = F.softplus(-torch.sign(delta) * (prediction[left] - prediction[right]) / temperature)
            contribution = value * 0.5
            result = result.index_add(0, torch.tensor([left, right], device=result.device), contribution.repeat(2))
            counts[left] += 0.5
            counts[right] += 0.5
    return result / counts.clamp_min(1.0)


def compute_v2_loss(
    output: Mapping[str, Tensor],
    batch: Mapping[str, Any],
    args: argparse.Namespace,
) -> tuple[Tensor, dict[str, Tensor]]:
    sources = batch["teacher_sources"]
    sample_weights = batch["weights"]
    target = batch["targets"]
    prediction = output["prediction"]
    dual = F.smooth_l1_loss(prediction[:, 2], target[:, 2], reduction="none", beta=args.huber_delta)
    receptor = F.smooth_l1_loss(prediction[:, :2], target[:, :2], reduction="none", beta=args.huber_delta).mean(1)
    marginal_logits = output.get("marginal_contact_logits", output.get("contact_logits"))
    require(marginal_logits is not None, "marginal_logits_missing")
    require(marginal_logits.shape[-1] == len(RECEPTOR_NAMES), "marginal_receptor_dimension")
    marginal_values: list[Tensor] = []
    marginal_availability: list[Tensor] = []
    contact_audit: dict[str, Tensor] = {}
    for receptor_index, receptor_name in enumerate(RECEPTOR_NAMES):
        values, available, audit = balanced_soft_bce_per_candidate_receptor(
            marginal_logits[..., receptor_index],
            batch["contact_targets"][..., receptor_index],
            batch["contact_uncertainty"][..., receptor_index],
            batch["contact_mask"][..., receptor_index],
            positive_class_fraction=args.contact_positive_class_fraction,
            epsilon=args.contact_balance_epsilon,
        )
        marginal_values.append(values)
        marginal_availability.append(available)
        for audit_name, audit_value in audit.items():
            contact_audit[f"audit_marginal_{receptor_name}_{audit_name}"] = audit_value
    marginal, marginal_available = _mean_receptor_losses(marginal_values, marginal_availability)
    ranking = per_candidate_ranking_loss(
        prediction[:, 2], target[:, 2], batch["parents"],
        minimum_delta=args.ranking_minimum_delta,
        temperature=args.ranking_temperature,
    )
    residual = output["residual"].square().mean(1)
    components: dict[str, tuple[Tensor, Tensor | None]] = {
        "dual": (dual, None),
        "receptor": (receptor, None),
        "marginal": (marginal, marginal_available),
        "ranking": (ranking, None),
        "residual": (residual, None),
    }
    if args.lane == "D_FULL_PAIR":
        pair_values = []
        pair_available = []
        for receptor in RECEPTOR_NAMES:
            logits = output[f"pair_logits_{receptor}"]
            values, available, audit = balanced_soft_bce_per_candidate_receptor(
                logits,
                batch[f"pair_targets_{receptor}"],
                batch[f"pair_uncertainty_{receptor}"],
                batch[f"pair_mask_{receptor}"],
                positive_class_fraction=args.contact_positive_class_fraction,
                epsilon=args.contact_balance_epsilon,
            )
            pair_values.append(values)
            pair_available.append(available)
            for audit_name, audit_value in audit.items():
                contact_audit[f"audit_pair_{receptor}_{audit_name}"] = audit_value
        pair, pair_dual_available = _mean_receptor_losses(pair_values, pair_available)
        components["pair"] = (pair, pair_dual_available)
    balanced: dict[str, Tensor] = {}
    source_means: dict[str, Tensor] = {}
    for name, (values, mask) in components.items():
        combined, means = source_balanced_component(
            values, sources, sample_weights=sample_weights, available_mask=mask,
        )
        balanced[name] = combined
        for source, value in means.items():
            source_means[f"{name}_{source}"] = value
    component_weights = loss_component_weights(args, args.lane)
    weighted = {name: component_weights[name] * balanced[name] for name in component_weights}
    total = torch.stack(tuple(weighted.values())).sum()
    contribution_denominator = torch.stack(tuple(value.detach().abs() for value in weighted.values())).sum().clamp_min(
        torch.finfo(total.dtype).eps
    )
    contribution = {
        f"contribution_fraction_{name}": value.detach().abs() / contribution_denominator
        for name, value in weighted.items()
    }
    weighted_parts = {f"weighted_{name}": value for name, value in weighted.items()}
    return total, {
        "total": total,
        **balanced,
        **source_means,
        **weighted_parts,
        **contribution,
        **contact_audit,
    }


def move_to_device(value: Any, device: torch.device) -> Any:
    if isinstance(value, Tensor):
        return value.to(device)
    if isinstance(value, Mapping):
        return {key: move_to_device(item, device) for key, item in value.items()}
    return value


def evaluation_metrics_by_source(
    records: Sequence[Mapping[str, Any]],
    *,
    prediction_field: str = "residue_prediction",
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    groups = {"GLOBAL": list(records)}
    groups.update({source: [row for row in records if row["teacher_source"] == source] for source in SOURCES})
    for source, rows in groups.items():
        if not rows:
            output[source] = {"rows": 0, "parents": 0, "status": "UNAVAILABLE_IN_THIS_SPLIT"}
            continue
        target = np.asarray([float(row["R_dual_min"]) for row in rows])
        prediction = np.asarray([float(row[prediction_field]) for row in rows])
        parents = [str(row["parent_framework_cluster"]) for row in rows]
        output[source] = v15.evaluation_metrics(target, prediction, parents)
        output[source]["rows"] = len(rows)
        output[source]["parents"] = len(set(parents))
    return output


def component_gradient_telemetry(
    parts: Mapping[str, Tensor],
    trainable_parameters: Sequence[Tensor],
    component_weights: Mapping[str, float],
) -> dict[str, Any]:
    """Return auditable raw/weighted L2 norms and weighted norm shares.

    ``torch.autograd.grad`` does not populate ``parameter.grad``.  The normal
    optimizer backward therefore remains unchanged.  Each raw component is
    differentiated once; candidate grid weights can then be evaluated without
    another forward pass, an optimizer step, or prediction metrics.
    """

    require(bool(trainable_parameters), "gradient_telemetry_no_trainable_parameters")
    names = [name for name in LOSS_COMPONENT_ORDER if name in parts and name in component_weights]
    require(bool(names), "gradient_telemetry_no_components")
    raw_norms: dict[str, float] = {}
    for name in names:
        value = parts[name]
        gradients = torch.autograd.grad(
            value,
            tuple(trainable_parameters),
            retain_graph=True,
            create_graph=False,
            allow_unused=True,
        )
        squared = torch.zeros((), device=value.device, dtype=torch.float64)
        for gradient in gradients:
            if gradient is not None:
                squared = squared + gradient.detach().double().square().sum()
        raw_norms[name] = float(torch.sqrt(squared).cpu())
    weights = {name: float(component_weights[name]) for name in names}
    weighted_norms = {name: abs(weights[name]) * raw_norms[name] for name in names}
    denominator = sum(weighted_norms.values())
    fractions = {
        name: (norm / denominator if denominator > 0.0 else 0.0)
        for name, norm in weighted_norms.items()
    }
    contact_names = {"marginal", "pair"} & set(names)
    return {
        "unweighted_gradient_l2_norm": raw_norms,
        "weighted_gradient_l2_norm": weighted_norms,
        "weighted_gradient_fraction": fractions,
        "component_weights": weights,
        "direct_contact_gradient_fraction": sum(fractions[name] for name in contact_names),
    }


def optimizer_step_count(optimizer: AdamW) -> int:
    steps: list[int] = []
    for state in optimizer.state.values():
        value = state.get("step", 0)
        if isinstance(value, Tensor):
            value = int(value.detach().cpu().item())
        steps.append(int(value))
    return max(steps, default=0)


def _mean_counter(counter: Counter[str], denominator: int) -> dict[str, float]:
    return {name: float(value) / max(1, denominator) for name, value in sorted(counter.items())}


def summarize_component_telemetry(
    inner_results: Sequence[Mapping[str, Any]],
    final_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Flatten every training segment's telemetry into the terminal result."""

    segments: list[dict[str, Any]] = []
    for inner in inner_results:
        inner_fold = int(inner["inner_fold"])
        for row in inner.get("history", []):
            telemetry = (row.get("train") or {}).get("component_telemetry")
            require(isinstance(telemetry, Mapping), f"inner_training_telemetry_missing:{inner_fold}:{row.get('epoch')}")
            segments.append({"stage": "inner_selection", "inner_fold": inner_fold, "epoch": row["epoch"], **dict(telemetry)})
    for row in final_result.get("training_history", []):
        telemetry = (row.get("train") or {}).get("component_telemetry")
        require(isinstance(telemetry, Mapping), f"final_refit_telemetry_missing:{row.get('epoch')}")
        segments.append({"stage": "final_refit", "epoch": row["epoch"], **dict(telemetry)})
    require(bool(segments), "terminal_component_telemetry_empty")
    aggregate: dict[str, Counter[str]] = {
        "gradient_fraction_mean": Counter(),
        "weighted_gradient_l2_norm_mean": Counter(),
        "unweighted_gradient_l2_norm_mean": Counter(),
        "weighted_contribution_fraction_mean": Counter(),
    }
    counts: Counter[str] = Counter()
    for segment in segments:
        for category in aggregate:
            values = segment.get(category) or {}
            require(isinstance(values, Mapping), f"telemetry_category_missing:{category}")
            for name, value in values.items():
                aggregate[category][str(name)] += float(value)
                counts[f"{category}:{name}"] += 1
    means = {
        category: {
            name: total / counts[f"{category}:{name}"]
            for name, total in sorted(counter.items())
        }
        for category, counter in aggregate.items()
    }
    return {
        "schema_version": "pvrig_v6_residue_v2_component_telemetry_terminal_v1",
        "training_segment_count": len(segments),
        "segments": segments,
        **means,
    }


def first_contact_gradient_calibration_observation(
    inner_results: Sequence[Mapping[str, Any]],
    *,
    lane: str,
    outer_fold: int,
) -> dict[str, Any]:
    require(bool(inner_results), "contact_gradient_calibration_inner_results_empty")
    first_inner = inner_results[0]
    history = first_inner.get("history") or []
    require(bool(history), "contact_gradient_calibration_history_empty")
    telemetry = ((history[0].get("train") or {}).get("component_telemetry") or {})
    observation = telemetry.get("calibration_observation_first_batch")
    require(isinstance(observation, Mapping), "contact_gradient_calibration_observation_missing")
    require(observation.get("lane") == lane, "contact_gradient_calibration_lane_mismatch")
    return {
        **dict(observation),
        "outer_fold": outer_fold,
        "inner_fold": int(first_inner["inner_fold"]),
        "training_stage": "first_inner_selection_epoch0_first_batch",
    }


def run_epoch(
    model: nn.Module,
    loader: DataLoader[Any],
    lane: str,
    target_graphs: Mapping[str, Mapping[str, Tensor]] | None,
    args: argparse.Namespace,
    device: torch.device,
    optimizer: AdamW | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    training = optimizer is not None
    model.train(training)
    model.backbone.eval()  # type: ignore[attr-defined]
    if training:
        optimizer.zero_grad(set_to_none=True)
    totals: Counter[str] = Counter()
    gradient_norm_totals: Counter[str] = Counter()
    unweighted_gradient_norm_totals: Counter[str] = Counter()
    gradient_fraction_totals: Counter[str] = Counter()
    contribution_fraction_totals: Counter[str] = Counter()
    contact_audit_totals: Counter[str] = Counter()
    gradient_batches_observed = 0
    first_gradient_observation: dict[str, Any] | None = None
    trainable_parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    component_weights = loss_component_weights(args, lane)
    records: list[dict[str, Any]] = []
    for batch_index, raw in enumerate(loader):
        batch = move_to_device(raw, device)
        with torch.set_grad_enabled(training), torch.autocast(
            device_type=device.type,
            dtype=torch.bfloat16,
            enabled=args.precision == "bf16" and device.type == "cuda",
        ):
            output = forward_model(model, lane, batch, target_graphs)
            if training:
                loss, parts = compute_v2_loss(output, batch, args)
        if training:
            for name, value in parts.items():
                if name.startswith("contribution_fraction_"):
                    contribution_fraction_totals[name.removeprefix("contribution_fraction_")] += float(value.detach().cpu())
                elif name.startswith("audit_"):
                    contact_audit_totals[name.removeprefix("audit_")] += float(value.detach().cpu())
            if batch_index < args.component_gradient_telemetry_batches:
                steps_before_observation = optimizer_step_count(optimizer)
                gradient = component_gradient_telemetry(parts, trainable_parameters, component_weights)
                gradient_batches_observed += 1
                gradient_norm_totals.update(gradient["weighted_gradient_l2_norm"])
                unweighted_gradient_norm_totals.update(gradient["unweighted_gradient_l2_norm"])
                gradient_fraction_totals.update(gradient["weighted_gradient_fraction"])
                if first_gradient_observation is None:
                    candidate_ids = [str(candidate) for candidate in batch["candidate_ids"]]
                    first_gradient_observation = {
                        "schema_version": "pvrig_v6_residue_v2_contact_gradient_observation_v1",
                        "lane": lane,
                        "gradient_batch_index": batch_index,
                        "gradient_batches_in_observation": 1,
                        "optimizer_steps_before_observation": steps_before_observation,
                        "candidate_ids_sha256": hashlib.sha256(
                            json.dumps(candidate_ids, separators=(",", ":")).encode()
                        ).hexdigest(),
                        "candidate_count": len(candidate_ids),
                        "teacher_source_counts": dict(sorted(Counter(batch["teacher_sources"]).items())),
                        "unweighted_gradient_l2_norm": gradient["unweighted_gradient_l2_norm"],
                        "component_weights": gradient["component_weights"],
                        "weighted_gradient_l2_norm": gradient["weighted_gradient_l2_norm"],
                        "weighted_gradient_fraction": gradient["weighted_gradient_fraction"],
                        "direct_contact_gradient_fraction": gradient["direct_contact_gradient_fraction"],
                        "open_only": True,
                        "v4_f_test32_access_count": 0,
                        "prediction_metrics_access_count": 0,
                    }
            (loss / args.gradient_accumulation).backward()
            should_step = (batch_index + 1) % args.gradient_accumulation == 0 or batch_index + 1 == len(loader)
            if should_step:
                torch.nn.utils.clip_grad_norm_([parameter for parameter in model.parameters() if parameter.requires_grad], args.gradient_clip)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
            for name, value in parts.items():
                totals[name] += float(value.detach().cpu())
        prediction = output["prediction"][:, 2].detach().float().cpu().numpy()
        base = batch["m2_base"][:, 2].detach().float().cpu().numpy()
        for item, candidate in enumerate(batch["candidate_ids"]):
            records.append({
                "candidate_id": candidate,
                "teacher_source": batch["teacher_sources"][item],
                "parent_framework_cluster": batch["parents"][item],
                "R_dual_min": float(batch["target_exact"][item]),
                "m2_prediction": float(base[item]),
                "residue_prediction": float(prediction[item]),
            })
    metrics = evaluation_metrics_by_source(records)
    metrics["M2_BASELINE"] = evaluation_metrics_by_source(records, prediction_field="m2_prediction")
    if training:
        metrics["loss"] = {name: total / max(1, len(loader)) for name, total in totals.items()}
        require(gradient_batches_observed > 0, "component_gradient_telemetry_not_observed")
        require(first_gradient_observation is not None, "component_gradient_first_observation_missing")
        metrics["component_telemetry"] = {
            "schema_version": "pvrig_v6_residue_v2_component_telemetry_epoch_v1",
            "contact_loss_normalization": CONTACT_LOSS_NORMALIZATION,
            "gradient_batches_requested": args.component_gradient_telemetry_batches,
            "gradient_batches_observed": gradient_batches_observed,
            "component_weights": component_weights,
            "weighted_gradient_l2_norm_mean": _mean_counter(gradient_norm_totals, gradient_batches_observed),
            "unweighted_gradient_l2_norm_mean": _mean_counter(unweighted_gradient_norm_totals, gradient_batches_observed),
            "gradient_fraction_mean": _mean_counter(gradient_fraction_totals, gradient_batches_observed),
            "direct_contact_gradient_fraction_mean": sum(
                value for name, value in _mean_counter(gradient_fraction_totals, gradient_batches_observed).items()
                if name in {"marginal", "pair"}
            ),
            "weighted_contribution_fraction_mean": _mean_counter(contribution_fraction_totals, len(loader)),
            "contact_balance_audit_mean_per_batch": _mean_counter(contact_audit_totals, len(loader)),
            "calibration_observation_first_batch": first_gradient_observation,
        }
        require(isinstance(loader.batch_sampler, DeterministicDomainBatchSampler), "training_sampler_not_domain_balanced")
        metrics["sampler_audit"] = loader.batch_sampler.audit_manifest()
    return metrics, records


def make_loader(
    rows: Sequence[v1.TrainingRow],
    indices: Sequence[int],
    tokenizer: Any,
    bases: Mapping[int, np.ndarray],
    teacher_sources: Sequence[str],
    contact_uncertainty: Mapping[int, np.ndarray],
    args: argparse.Namespace,
    *,
    graph_store: GraphCacheStore | None,
    pair_store: PairTargetStore | None,
    target_nodes: Mapping[str, int],
    training: bool,
    seed: int,
    epoch: int = 0,
) -> DataLoader[Any]:
    collator = V2Collator(
        rows, tokenizer, bases, teacher_sources, contact_uncertainty,
        graph_store=graph_store, pair_store=pair_store, target_nodes=target_nodes,
    )
    dataset = v1.IndexedDataset(indices)
    if training:
        local_sources = [teacher_sources[index] for index in indices]
        local_candidates = [rows[index].candidate_id for index in indices]
        sampler = DeterministicDomainBatchSampler(local_sources, local_candidates, seed=seed, epoch=epoch)
        return DataLoader(dataset, batch_sampler=sampler, num_workers=0, collate_fn=collator)
    return DataLoader(dataset, batch_size=args.evaluation_batch_size, shuffle=False, num_workers=0, collate_fn=collator)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def train_selection(
    args: argparse.Namespace,
    rows: Sequence[v1.TrainingRow],
    train_indices: Sequence[int],
    validation_indices: Sequence[int],
    train_bases: Mapping[int, np.ndarray],
    validation_bases: Mapping[int, np.ndarray],
    teacher_sources: Sequence[str],
    contact_uncertainty: Mapping[int, np.ndarray],
    graph_store: GraphCacheStore | None,
    pair_store: PairTargetStore | None,
    target_graphs: Mapping[str, Mapping[str, Tensor]] | None,
    seed: int,
) -> tuple[int, dict[str, Any]]:
    seed_everything(seed)
    device = torch.device(args.device)
    edge_dim = graph_store.edge_feature_dim if graph_store else 26
    target_dim = next(iter(target_graphs.values()))["node_features"].shape[1] if target_graphs else 1
    target_nodes = {name: len(target_graphs[name]["node_features"]) for name in RECEPTOR_NAMES} if target_graphs else {}
    model, tokenizer, contract = build_model(args, edge_feature_dim=edge_dim, target_node_dim=target_dim, device=device)
    target_device = move_to_device(target_graphs, device) if target_graphs else None
    optimizer = AdamW([parameter for parameter in model.parameters() if parameter.requires_grad], lr=args.head_learning_rate, weight_decay=args.weight_decay)
    history = []
    best_epoch, best_key = -1, None
    for epoch in range(args.max_epochs):
        train_loader = make_loader(
            rows, train_indices, tokenizer, train_bases, teacher_sources, contact_uncertainty, args,
            graph_store=graph_store, pair_store=pair_store, target_nodes=target_nodes,
            training=True, seed=seed, epoch=epoch,
        )
        validation_loader = make_loader(
            rows, validation_indices, tokenizer, validation_bases, teacher_sources, contact_uncertainty, args,
            graph_store=graph_store, pair_store=pair_store, target_nodes=target_nodes,
            training=False, seed=seed,
        )
        train_metrics, _ = run_epoch(model, train_loader, args.lane, target_device, args, device, optimizer)
        validation_metrics, _ = run_epoch(model, validation_loader, args.lane, target_device, args, device, None)
        key = v15.selection_key(validation_metrics["GLOBAL"])
        history.append({"epoch": epoch, "train": train_metrics, "validation": validation_metrics, "selection_key": list(key)})
        if best_key is None or key > best_key:
            best_key, best_epoch = key, epoch
    require(best_epoch >= 0, "selection_no_best_epoch")
    return best_epoch + 1, {"selected_epoch_count": best_epoch + 1, "history": history, "model_contract": contract}


def final_refit_and_evaluate(
    args: argparse.Namespace,
    rows: Sequence[v1.TrainingRow],
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    train_bases: Mapping[int, np.ndarray],
    test_bases: Mapping[int, np.ndarray],
    teacher_sources: Sequence[str],
    contact_uncertainty: Mapping[int, np.ndarray],
    graph_store: GraphCacheStore | None,
    pair_store: PairTargetStore | None,
    target_graphs: Mapping[str, Mapping[str, Tensor]] | None,
    epochs: int,
    seed: int,
) -> tuple[nn.Module, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    seed_everything(seed)
    device = torch.device(args.device)
    edge_dim = graph_store.edge_feature_dim if graph_store else 26
    target_dim = next(iter(target_graphs.values()))["node_features"].shape[1] if target_graphs else 1
    target_nodes = {name: len(target_graphs[name]["node_features"]) for name in RECEPTOR_NAMES} if target_graphs else {}
    model, tokenizer, contract = build_model(args, edge_feature_dim=edge_dim, target_node_dim=target_dim, device=device)
    target_device = move_to_device(target_graphs, device) if target_graphs else None
    optimizer = AdamW([parameter for parameter in model.parameters() if parameter.requires_grad], lr=args.head_learning_rate, weight_decay=args.weight_decay)
    history = []
    for epoch in range(epochs):
        loader = make_loader(
            rows, train_indices, tokenizer, train_bases, teacher_sources, contact_uncertainty, args,
            graph_store=graph_store, pair_store=pair_store, target_nodes=target_nodes,
            training=True, seed=seed, epoch=epoch,
        )
        metrics, _ = run_epoch(model, loader, args.lane, target_device, args, device, optimizer)
        history.append({"epoch": epoch, "train": metrics})
    evaluation = make_loader(
        rows, test_indices, tokenizer, test_bases, teacher_sources, contact_uncertainty, args,
        graph_store=graph_store, pair_store=pair_store, target_nodes=target_nodes,
        training=False, seed=seed,
    )
    metrics, records = run_epoch(model, evaluation, args.lane, target_device, args, device, None)
    return model, {"training_history": history, "outer_test": metrics}, records, contract


def validate_frozen_arguments(args: argparse.Namespace, preregistration: Mapping[str, Any]) -> dict[str, Any]:
    require(args.lane in LANES, "lane_invalid")
    require(args.precision in {"fp32", "bf16"}, "precision_invalid")
    require(args.outer_fold in range(5), "outer_fold_invalid")
    require(args.gradient_accumulation >= 1 and args.max_epochs >= 1, "training_dimensions_invalid")
    require(0.0 < args.contact_positive_class_fraction < 1.0, "contact_positive_class_fraction_range")
    require(math.isfinite(args.contact_balance_epsilon) and args.contact_balance_epsilon > 0.0, "contact_balance_epsilon_range")
    require(args.component_gradient_telemetry_batches >= 1, "component_gradient_telemetry_batches_range")
    require(abs(args.residual_scale - 0.02) < 1e-12, "residual_scale_not_frozen")
    if args.lane in GRAPH_LANES:
        require(args.graph_cache_dir is not None, "graph_cache_required_for_lane")
    if args.lane in TARGET_LANES:
        require(args.target_graph_pt is not None, "target_graph_required_for_lane")
    if args.lane in PAIR_LANES:
        require(args.pair_contact_tsv_gz is not None, "pair_targets_required_for_lane")
    if args.smoke_mode:
        require(args.contact_loss_amendment is None, "smoke_contact_loss_amendment_forbidden")
        amendment = {
            **contact_loss_amendment_contract(args),
            "status": "PREPRODUCTION_SMOKE_NOT_FORMAL_GOVERNANCE",
            "calibration": None,
        }
    else:
        require(args.contact_loss_amendment is not None, "formal_contact_loss_amendment_required")
        amendment = validate_contact_loss_amendment_v2_2(args.contact_loss_amendment, args)
        training = preregistration["training"]
        loss = preregistration["loss"]
        expected = {
            "head_learning_rate": training["head_learning_rate"],
            "weight_decay": training["weight_decay"],
            "dropout": training["dropout"],
            "max_epochs": training["maximum_epochs"],
            "gradient_accumulation": training["gradient_accumulation"],
            "dual_weight": loss["dual_weight"],
            "receptor_weight": loss["receptor_weight"],
            "ranking_weight": loss["ranking_weight"],
            "ranking_minimum_delta": loss["ranking_minimum_delta"],
            "ranking_temperature": loss["ranking_temperature"],
            "residual_l2_weight": loss["residual_l2_weight"],
        }
        for name, value in expected.items():
            observed = getattr(args, name)
            require(abs(float(observed) - float(value)) < 1e-12, f"frozen_argument_mismatch:{name}")
        require(args.graph_hidden_dim == 128 and args.structure_dim == 126, "frozen_model_dimension_mismatch")
        require(args.backbone_kind == "hf", "production_backbone_must_be_frozen_hf")
        require(args.precision == str(training["precision"]), "production_precision_not_frozen")
        require(args.contact_receipt is not None, "production_contact_receipt_required")
        if args.lane in TARGET_LANES:
            require(args.target_graph_receipt is not None, "production_target_graph_receipt_required")
    return amendment


def train(args: argparse.Namespace) -> dict[str, Any]:
    preregistration = load_preregistration(args.preregistration)
    contact_loss_amendment = validate_frozen_arguments(args, preregistration)
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "output_dir_must_not_exist")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    rows, feature_names, data_audit = v1.read_training_table(
        args.training_tsv, args.contact_tsv_gz,
        structure_prefixes=args.structure_prefix,
        structure_dim=args.structure_dim,
    )
    contact_receipt = validate_contact_receipt(args.contact_receipt, args.contact_tsv_gz) if args.contact_receipt is not None else None
    validate_outer_fold_closure(rows)
    teacher_sources, source_audit = load_teacher_metadata(
        args.training_tsv, rows, preregistration, smoke_mode=args.smoke_mode,
    )
    contact_uncertainty = load_contact_uncertainty(args.contact_tsv_gz, rows)
    graph_store = GraphCacheStore(args.graph_cache_dir, rows) if args.graph_cache_dir is not None else None
    target_graphs = load_target_graphs(args.target_graph_pt, graph_store.edge_feature_dim if graph_store else 26) if args.target_graph_pt is not None else None
    target_graph_receipt = validate_target_graph_receipt(args.target_graph_receipt, args.target_graph_pt) if args.target_graph_receipt is not None and args.target_graph_pt is not None else None
    target_nodes = {name: len(target_graphs[name]["node_features"]) for name in RECEPTOR_NAMES} if target_graphs else {}
    pair_store = PairTargetStore(args.pair_contact_tsv_gz, rows, target_nodes) if args.pair_contact_tsv_gz is not None else None
    arrays = v1.arrays_from_rows(rows)
    outer_test = [index for index, row in enumerate(rows) if row.outer_fold == args.outer_fold]
    outer_test_set = set(outer_test)
    outer_train = [index for index in range(len(rows)) if index not in outer_test_set]
    require(outer_train and outer_test, "outer_split_empty")
    require({rows[index].parent for index in outer_train}.isdisjoint(rows[index].parent for index in outer_test), "outer_parent_leakage")
    observed_inner = sorted({v15.parent_inner_fold(rows[index].parent, args.outer_fold) for index in outer_train})
    require(len(observed_inner) >= 2, "inner_fold_count_too_small")

    inner_results = []
    epoch_counts = []
    for inner_fold in observed_inner:
        validation = [index for index in outer_train if v15.parent_inner_fold(rows[index].parent, args.outer_fold) == inner_fold]
        selection_train = [index for index in outer_train if v15.parent_inner_fold(rows[index].parent, args.outer_fold) != inner_fold]
        require(selection_train and validation, f"inner_split_empty:{inner_fold}")
        require({rows[index].parent for index in selection_train}.isdisjoint(rows[index].parent for index in validation), f"inner_parent_leakage:{inner_fold}")
        crossfit, counts = v15.crossfit_m2(selection_train, arrays, args.outer_fold, args.ridge_alpha)
        train_bases = {index: crossfit[position] for position, index in enumerate(selection_train)}
        state = v1.fit_weighted_ridge(
            arrays["structure"][selection_train], arrays["targets"][selection_train], arrays["weights"][selection_train], args.ridge_alpha,
        )
        validation_prediction = v1.predict_ridge(state, arrays["structure"][validation])
        validation_bases = {index: validation_prediction[position] for position, index in enumerate(validation)}
        selected, result = train_selection(
            args, rows, selection_train, validation, train_bases, validation_bases,
            teacher_sources, contact_uncertainty, graph_store, pair_store, target_graphs,
            args.seed + args.outer_fold * 10000 + inner_fold * 100,
        )
        epoch_counts.append(selected)
        inner_results.append({"inner_fold": inner_fold, "crossfit_counts": counts, **result})
    final_epochs = v15.rounded_median_epoch(epoch_counts)
    final_crossfit, final_counts = v15.crossfit_m2(outer_train, arrays, args.outer_fold, args.ridge_alpha)
    train_bases = {index: final_crossfit[position] for position, index in enumerate(outer_train)}
    outer_state = v1.fit_weighted_ridge(
        arrays["structure"][outer_train], arrays["targets"][outer_train], arrays["weights"][outer_train], args.ridge_alpha,
    )
    outer_prediction = v1.predict_ridge(outer_state, arrays["structure"][outer_test])
    test_bases = {index: outer_prediction[position] for position, index in enumerate(outer_test)}
    model, final_result, records, contract = final_refit_and_evaluate(
        args, rows, outer_train, outer_test, train_bases, test_bases,
        teacher_sources, contact_uncertainty, graph_store, pair_store, target_graphs,
        final_epochs, args.seed + args.outer_fold * 10000 + 9000,
    )
    input_hashes = {
        "training_tsv": sha256_file(args.training_tsv),
        "contact_tsv_gz": sha256_file(args.contact_tsv_gz),
        "preregistration": sha256_file(args.preregistration),
    }
    if args.contact_loss_amendment is not None:
        input_hashes["contact_loss_amendment"] = sha256_file(args.contact_loss_amendment)
    if args.contact_receipt is not None:
        input_hashes["contact_receipt"] = sha256_file(args.contact_receipt)
    if args.target_graph_receipt is not None:
        input_hashes["target_graph_receipt"] = sha256_file(args.target_graph_receipt)
    if args.graph_cache_dir is not None:
        for name in ("graph_cache_v2.npz", "graph_manifest_v2.tsv", "graph_cache_receipt_v2.json"):
            path = args.graph_cache_dir / name
            require(path.is_file() and not path.is_symlink(), f"graph_binding_input_missing:{name}")
            input_hashes[f"graph_cache/{name}"] = sha256_file(path)
    for name, path in (("target_graph_pt", args.target_graph_pt), ("pair_contact_tsv_gz", args.pair_contact_tsv_gz)):
        if path is not None:
            input_hashes[name] = sha256_file(path)
    binding = {
        "schema_version": f"{SCHEMA_VERSION}_binding",
        "lane": args.lane,
        "outer_fold": args.outer_fold,
        "seed": args.seed,
        "input_hashes": input_hashes,
        "feature_names": feature_names,
        "model_contract": contract,
        "loss": {
            "dual_weight": args.dual_weight,
            "receptor_weight": args.receptor_weight,
            "marginal_contact_weight": args.marginal_contact_weight,
            "pair_contact_weight": args.pair_contact_weight if args.lane == "D_FULL_PAIR" else 0.0,
            "ranking_weight": args.ranking_weight,
            "residual_l2_weight": args.residual_l2_weight,
            "contact_loss_amendment": contact_loss_amendment,
        },
        "source_balance": "each component source-normalized then 0.5*V4D+0.5*V4H",
        "teacher_source_is_model_feature": False,
    }
    binding_hash = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    atomic_json(args.output_dir / "contract.json", {**binding, "binding_hash": binding_hash, "claim_boundary": CLAIM_BOUNDARY})
    atomic_torch_save(args.output_dir / "head_final.pt", {
        "schema_version": f"{SCHEMA_VERSION}_head_checkpoint",
        "binding_hash": binding_hash,
        "head_state": head_checkpoint_state(model),
        "claim_boundary": CLAIM_BOUNDARY,
    })
    prediction_path = args.output_dir / "outer_test_predictions.tsv"
    fields = [
        "candidate_id", "teacher_source", "parent_framework_cluster", "outer_fold", "R_dual_min",
        "m2_prediction", "residue_prediction", "lane", "model_version",
    ]
    with prediction_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for record in sorted(records, key=lambda item: item["candidate_id"]):
            writer.writerow({**record, "outer_fold": args.outer_fold, "lane": args.lane, "model_version": SCHEMA_VERSION})
    result = {
        "schema_version": f"{SCHEMA_VERSION}_result",
        "status": "PASS_OUTER_FOLD_COMPLETE",
        "lane": args.lane,
        "outer_fold": args.outer_fold,
        "binding_hash": binding_hash,
        "inner_results": inner_results,
        "selected_epoch_counts": epoch_counts,
        "final_epoch_count": final_epochs,
        "final_crossfit_counts": final_counts,
        "outer": final_result,
        "data_audit": data_audit,
        "source_audit": source_audit,
        "contact_loss_amendment": contact_loss_amendment,
        "contact_loss_amendment_sha256": (
            sha256_file(args.contact_loss_amendment) if args.contact_loss_amendment is not None else None
        ),
        "component_telemetry_terminal": summarize_component_telemetry(inner_results, final_result),
        "contact_gradient_calibration_observation": first_contact_gradient_calibration_observation(
            inner_results, lane=args.lane, outer_fold=args.outer_fold,
        ),
        "contact_receipt_status": contact_receipt["status"] if contact_receipt is not None else "SMOKE_NOT_REQUIRED",
        "target_graph_receipt_status": target_graph_receipt["status"] if target_graph_receipt is not None else "NOT_APPLICABLE_OR_SMOKE",
        "artifacts": {
            name: sha256_file(args.output_dir / name)
            for name in ("contract.json", "head_final.pt", "outer_test_predictions.tsv")
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(args.output_dir / "RESULT.json", result)
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--training-tsv", type=Path, required=True)
    value.add_argument("--contact-tsv-gz", type=Path, required=True)
    value.add_argument("--contact-receipt", type=Path)
    value.add_argument("--graph-cache-dir", type=Path)
    value.add_argument("--target-graph-pt", type=Path)
    value.add_argument("--target-graph-receipt", type=Path)
    value.add_argument("--pair-contact-tsv-gz", type=Path)
    value.add_argument("--preregistration", type=Path, required=True)
    value.add_argument("--contact-loss-amendment", type=Path)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--lane", choices=LANES, required=True)
    value.add_argument("--outer-fold", type=int, required=True)
    value.add_argument("--smoke-mode", action="store_true")
    value.add_argument("--structure-prefix", action="append", default=[])
    value.add_argument("--structure-dim", type=int, default=126)
    value.add_argument("--ridge-alpha", type=float, default=10.0)
    value.add_argument("--backbone-kind", choices=("tiny", "hf"), default="hf")
    value.add_argument("--model-path", type=Path)
    value.add_argument("--model-identity-file", type=Path)
    value.add_argument("--expected-model-sha256")
    value.add_argument("--trust-remote-code", action="store_true")
    value.add_argument("--tiny-hidden-size", type=int, default=16)
    value.add_argument("--graph-hidden-dim", type=int, default=128)
    value.add_argument("--dropout", type=float, default=0.25)
    value.add_argument("--residual-scale", type=float, default=0.02)
    value.add_argument("--huber-delta", type=float, default=0.03)
    value.add_argument("--dual-weight", type=float, default=1.0)
    value.add_argument("--receptor-weight", type=float, default=0.35)
    value.add_argument("--marginal-contact-weight", type=float, default=0.0001)
    value.add_argument("--pair-contact-weight", type=float, default=0.00005)
    value.add_argument("--contact-positive-class-fraction", type=float, default=0.5)
    value.add_argument("--contact-balance-epsilon", type=float, default=1e-8)
    value.add_argument("--component-gradient-telemetry-batches", type=int, default=1)
    value.add_argument("--ranking-weight", type=float, default=0.0001)
    value.add_argument("--ranking-minimum-delta", type=float, default=0.02)
    value.add_argument("--ranking-temperature", type=float, default=0.03)
    value.add_argument("--residual-l2-weight", type=float, default=0.05)
    value.add_argument("--max-epochs", type=int, default=8)
    value.add_argument("--gradient-accumulation", type=int, default=2)
    value.add_argument("--head-learning-rate", type=float, default=0.0001)
    value.add_argument("--weight-decay", type=float, default=0.02)
    value.add_argument("--gradient-clip", type=float, default=1.0)
    value.add_argument("--evaluation-batch-size", type=int, default=16)
    value.add_argument("--precision", choices=("fp32", "bf16"), default="bf16")
    value.add_argument("--seed", type=int, default=43)
    value.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.structure_prefix:
        args.structure_prefix = list(v15.STRUCTURE_PREFIXES)
    result = train(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
