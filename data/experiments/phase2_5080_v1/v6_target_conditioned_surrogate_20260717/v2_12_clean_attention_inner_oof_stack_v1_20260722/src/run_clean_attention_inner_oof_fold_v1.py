#!/usr/bin/env python3
"""Train one leakage-safe whole-parent inner-OOF clean-attention fold.

Only frozen sequence tokens, label-free VHH residue graphs, and fixed public
8X6B/9E6Y target graphs can reach the neural forward.  M2, C2, contact labels,
candidate/parent IDs, teacher source, Docking poses, and pose-derived features
are excluded by a positive input allowlist inherited from the frozen V2.5
orthogonal trainer.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor, nn


SCHEMA_VERSION = "pvrig_v2_12_clean_attention_inner_oof_fold_runner_v1"
CONTRACT_SCHEMA = "pvrig_v2_12_clean_attention_inner_oof_fold_contract_v1"
LANE = "B_CLEAN_TARGET_ATTENTION"
RECEPTORS = ("8x6b", "9e6y")
DIRECT_TARGETS = ("R_8X6B", "R_9E6Y")
DERIVED_TARGET = "R_dual_min"
PREDICTION_NAME = "inner_oof_fold_predictions.tsv"
CHECKPOINT_NAME = "inner_oof_clean_attention_head_final.pt"
RESULT_NAME = "RESULT.json"
HISTORY_NAME = "epoch_history.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")

CLAIM_BOUNDARY = (
    "Train9849 whole-parent inner-OOF sequence plus label-free VHH monomer graph plus "
    "fixed public 8X6B/9E6Y target-graph approximation of independent dual-receptor "
    "computational Docking geometry; whole-parent OOF only (not CDR3/sequence-family OOD), "
    "no open-development or frozen-test model fitting, and not binding, affinity, experimental "
    "blocking, Docking Gold, or submission evidence."
)

FORBIDDEN_NEURAL_INPUTS = {
    "m2", "m2_base", "m2_outputs", "c2", "coarse_pose", "structure",
    "structure_features", "contact", "contact_targets", "pair_targets",
    "candidate_id", "candidate_ids", "parent", "parents", "parent_id",
    "parent_framework_cluster", "campaign_id", "teacher_source", "docking_pose",
    "docking_pose_features", "pose_features",
}
REQUIRED_TRAINING_FIELDS = {
    "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster",
    "sample_weight", "R_8X6B", "R_9E6Y", "R_dual_min",
}
GRAPH_ARRAY_ALLOWLIST = {
    "aa_index", "region_index", "confidence", "edge_index", "edge_features",
    "node_offsets", "edge_offsets",
}


class CleanAttentionError(RuntimeError):
    """Fail-closed clean-attention runner error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CleanAttentionError(message)


def sha256_file(path: Path) -> str:
    require(path.exists() and path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    try:
        torch.save(payload, temporary)
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_tsv(path: Path, label: str) -> tuple[list[str], list[dict[str, str]]]:
    require(path.exists() and path.is_file() and not path.is_symlink(), f"{label}_invalid")
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(fields and rows, f"{label}_empty")
    return fields, rows


def _workspace_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[5] / path


def load_contract(path: Path) -> dict[str, Any]:
    require(path.exists() and path.is_file() and not path.is_symlink(), "contract_invalid")
    contract = json.loads(path.read_text(encoding="utf-8"))
    require(contract.get("schema_version") == CONTRACT_SCHEMA, "contract_schema_invalid")
    require(contract.get("status") == "FROZEN_INNER_OOF_PRE_LAUNCH", "contract_status_invalid")
    require(contract.get("lane") == LANE, "contract_lane_invalid")
    require(contract.get("contact_supervision_enabled") is False, "contract_contact_must_be_disabled")
    return contract


def _verify_bound_file(binding: Mapping[str, Any], label: str) -> Path:
    path = _workspace_path(str(binding.get("path", "")))
    expected = str(binding.get("sha256", "")).lower()
    require(bool(SHA256_RE.fullmatch(expected)), f"{label}_expected_sha256_invalid")
    require(sha256_file(path) == expected, f"{label}_sha256_mismatch")
    return path


def load_frozen_ortho_modules(contract: Mapping[str, Any]) -> tuple[Any, Any]:
    model_path = _verify_bound_file(dict(contract.get("ortho_model") or {}), "ortho_model")
    trainer_path = _verify_bound_file(dict(contract.get("ortho_trainer") or {}), "ortho_trainer")
    model_spec = importlib.util.spec_from_file_location("residue_model_v2_5_ortho", model_path)
    require(model_spec is not None and model_spec.loader is not None, "ortho_model_import_spec")
    model_module = importlib.util.module_from_spec(model_spec)
    sys.modules[model_spec.name] = model_module
    model_spec.loader.exec_module(model_module)
    trainer_spec = importlib.util.spec_from_file_location("train_v2_5_ortho_heads", trainer_path)
    require(trainer_spec is not None and trainer_spec.loader is not None, "ortho_trainer_import_spec")
    trainer_module = importlib.util.module_from_spec(trainer_spec)
    sys.modules[trainer_spec.name] = trainer_module
    trainer_spec.loader.exec_module(trainer_module)
    require(model_module.LANE_B == trainer_module.LANE_B == LANE, "ortho_lane_binding_invalid")
    return model_module, trainer_module


@dataclass(frozen=True)
class CandidateRow:
    candidate_id: str
    sequence_sha256: str
    sequence: str
    parent: str
    sample_weight: float
    targets: tuple[float, float]


@dataclass(frozen=True)
class Split:
    train_indices: tuple[int, ...]
    development_indices: tuple[int, ...]
    train_parents: tuple[str, ...]
    development_parents: tuple[str, ...]
    split_id: str


def load_rows(path: Path, expected_rows: int) -> list[CandidateRow]:
    fields, raw = _read_tsv(path, "training_table")
    require(REQUIRED_TRAINING_FIELDS <= set(fields), f"training_fields_missing:{sorted(REQUIRED_TRAINING_FIELDS-set(fields))}")
    rows: list[CandidateRow] = []
    seen: set[str] = set()
    for source in raw:
        candidate_id = source["candidate_id"].strip()
        sequence = source["sequence"].strip().upper()
        sequence_digest = source["sequence_sha256"].strip().lower()
        require(candidate_id and candidate_id not in seen, f"candidate_duplicate:{candidate_id}")
        require(bool(AA_RE.fullmatch(sequence)), f"sequence_invalid:{candidate_id}")
        require(hashlib.sha256(sequence.encode("ascii")).hexdigest() == sequence_digest, f"sequence_sha256_mismatch:{candidate_id}")
        weight = float(source["sample_weight"])
        r8, r9 = float(source["R_8X6B"]), float(source["R_9E6Y"])
        dual = float(source["R_dual_min"])
        require(all(math.isfinite(value) for value in (weight, r8, r9, dual)), f"nonfinite_training_value:{candidate_id}")
        require(weight > 0.0, f"sample_weight_nonpositive:{candidate_id}")
        require(abs(dual - min(r8, r9)) <= 1e-12, f"truth_exact_min_mismatch:{candidate_id}")
        seen.add(candidate_id)
        rows.append(CandidateRow(candidate_id, sequence_digest, sequence, source["parent_framework_cluster"].strip(), weight, (r8, r9)))
    require(len(rows) == expected_rows, f"training_row_count_mismatch:{len(rows)}!={expected_rows}")
    return rows


def _stable_set_hash(values: Iterable[str]) -> str:
    return hashlib.sha256("".join(f"{value}\n" for value in sorted(set(values))).encode()).hexdigest()


def load_split(path: Path, rows: Sequence[CandidateRow], expected_train: int, expected_development: int) -> Split:
    require(path.exists() and path.is_file() and not path.is_symlink(), "split_manifest_invalid")
    payload = json.loads(path.read_text(encoding="utf-8"))
    train_parents = tuple(payload.get("train_parents") or ())
    development_parents = tuple(payload.get("score_parents") or ())
    frozen = set(payload.get("frozen_test_parents") or ())
    require(train_parents and development_parents, "split_parent_sets_empty")
    require(not (set(train_parents) & set(development_parents)), "train_development_parent_overlap")
    require(not ((set(train_parents) | set(development_parents)) & frozen), "open_frozen_parent_overlap")
    require(_stable_set_hash(train_parents) == payload.get("train_parent_set_sha256"), "train_parent_set_sha256_mismatch")
    require(_stable_set_hash(development_parents) == payload.get("score_parent_set_sha256"), "development_parent_set_sha256_mismatch")
    train, development = [], []
    allowed = set(train_parents) | set(development_parents)
    for index, row in enumerate(rows):
        require(row.parent in allowed, f"candidate_parent_not_open_split:{row.candidate_id}:{row.parent}")
        (train if row.parent in set(train_parents) else development).append(index)
    require(len(train) == expected_train, f"train_count_mismatch:{len(train)}!={expected_train}")
    require(len(development) == expected_development, f"development_count_mismatch:{len(development)}!={expected_development}")
    require({rows[index].parent for index in train} == set(train_parents), "train_parent_closure")
    require({rows[index].parent for index in development} == set(development_parents), "development_parent_closure")
    return Split(tuple(train), tuple(development), train_parents, development_parents, str(payload.get("split_id", "")))


class GraphCacheStore:
    """Random access to only the permitted label-free graph arrays."""

    def __init__(self, directory: Path, rows: Sequence[CandidateRow], *, require_full_receipt: bool = True) -> None:
        cache = directory / "graph_cache_v2.npz"
        manifest_path = directory / "graph_manifest_v2.tsv"
        receipt_path = directory / "graph_cache_receipt_v2.json"
        require(all(path.is_file() and not path.is_symlink() for path in (cache, manifest_path, receipt_path)), "graph_cache_delivery_incomplete")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        require(receipt.get("status") == "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE", "graph_cache_status_invalid")
        require((receipt.get("outputs") or {}).get(cache.name) == sha256_file(cache), "graph_cache_sha256_mismatch")
        require((receipt.get("outputs") or {}).get(manifest_path.name) == sha256_file(manifest_path), "graph_manifest_sha256_mismatch")
        fields, manifest_rows = _read_tsv(manifest_path, "graph_manifest")
        require({"entity_id", "sequence_sha256", "monomer_sha256", "node_start", "node_end", "edge_start", "edge_end"} <= set(fields), "graph_manifest_fields_missing")
        self.manifest = {row["entity_id"]: row for row in manifest_rows}
        require(len(self.manifest) == len(manifest_rows), "graph_manifest_duplicate_entity")
        require(set(self.manifest) == {row.candidate_id for row in rows}, "graph_candidate_exact_closure")
        for row in rows:
            require(self.manifest[row.candidate_id]["sequence_sha256"] == row.sequence_sha256, f"graph_sequence_sha256_mismatch:{row.candidate_id}")
        with np.load(cache, allow_pickle=False) as archive:
            require(GRAPH_ARRAY_ALLOWLIST <= set(archive.files), "graph_array_allowlist_missing")
            self.arrays = {name: archive[name] for name in GRAPH_ARRAY_ALLOWLIST}
        self.edge_feature_dim = int(receipt["counts"]["edge_feature_dim"])
        self.receipt = receipt
        self.input_hashes = {
            cache.name: sha256_file(cache),
            manifest_path.name: sha256_file(manifest_path),
            receipt_path.name: sha256_file(receipt_path),
        }
        if require_full_receipt:
            wrapper_path = directory.parent / "MATERIALIZATION_RECEIPT.json"
            prepared_path = directory.parent / "canonical10644_label_free_graph_input_manifest_v1.tsv"
            prepare_receipt_path = directory.parent / "PREPARE_RECEIPT.json"
            require(all(path.is_file() and not path.is_symlink() for path in (wrapper_path, prepared_path, prepare_receipt_path)), "full10644_graph_wrapper_missing")
            wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
            prepare_receipt = json.loads(prepare_receipt_path.read_text(encoding="utf-8"))
            self.input_hashes.update({
                wrapper_path.name: sha256_file(wrapper_path),
                prepared_path.name: sha256_file(prepared_path),
                prepare_receipt_path.name: sha256_file(prepare_receipt_path),
            })
            require(wrapper.get("status") == "PASS_CANONICAL10644_LABEL_FREE_GRAPH_MATERIALIZED", "full10644_graph_wrapper_status")
            require((wrapper.get("outputs") or {}).get(cache.name) == sha256_file(cache), "full10644_wrapper_cache_hash")
            require((wrapper.get("outputs") or {}).get(manifest_path.name) == sha256_file(manifest_path), "full10644_wrapper_manifest_hash")
            require((prepare_receipt.get("outputs") or {}).get(prepared_path.name) == sha256_file(prepared_path), "prepared_graph_input_hash")
            _prepared_fields, prepared_rows = _read_tsv(prepared_path, "prepared_graph_input")
            prepared = {row["candidate_id"]: row for row in prepared_rows}
            require(len(prepared) == len(rows) and set(prepared) == set(self.manifest), "prepared_graph_input_exact_closure")
            for row in rows:
                source, graph = prepared[row.candidate_id], self.manifest[row.candidate_id]
                require((source["sequence_sha256"], source["monomer_sha256"]) == (graph["sequence_sha256"], graph["monomer_sha256"]), f"prepared_graph_triplet_mismatch:{row.candidate_id}")

    def graph(self, candidate_id: str) -> dict[str, np.ndarray]:
        source = self.manifest[candidate_id]
        node_start, node_end = int(source["node_start"]), int(source["node_end"])
        edge_start, edge_end = int(source["edge_start"]), int(source["edge_end"])
        edge_index = self.arrays["edge_index"][:, edge_start:edge_end] - node_start
        require(bool(np.all((edge_index >= 0) & (edge_index < node_end-node_start))), f"graph_edge_bounds:{candidate_id}")
        return {
            "aa_index": self.arrays["aa_index"][node_start:node_end],
            "region_index": self.arrays["region_index"][node_start:node_end],
            "confidence": self.arrays["confidence"][node_start:node_end],
            "edge_index": edge_index,
            "edge_features": self.arrays["edge_features"][edge_start:edge_end],
        }


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower() in FORBIDDEN_NEURAL_INPUTS or _contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def load_target_graphs(path: Path, expected_edge_dim: int, receipt_path: Path | None = None) -> dict[str, dict[str, Tensor]]:
    require(path.is_file() and not path.is_symlink(), "target_graph_pt_invalid")
    if receipt_path is not None:
        require(receipt_path.is_file() and not receipt_path.is_symlink(), "target_graph_receipt_invalid")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        require(receipt.get("status") == "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED", "target_graph_status_invalid")
        require((receipt.get("outputs") or {}).get(path.name) == sha256_file(path), "target_graph_receipt_hash_mismatch")
        sealed = receipt.get("sealed_boundary") or {}
        require(sealed.get("candidate_docking_pose_files_opened") == 0, "target_graph_pose_access_nonzero")
        require(sealed.get("teacher_source_is_model_feature") is False, "target_graph_teacher_source_feature")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if isinstance(payload, Mapping) and "target_graphs" in payload:
        payload = payload["target_graphs"]
    require(isinstance(payload, Mapping) and set(payload) == set(RECEPTORS), "target_receptor_closure")
    require(not _contains_forbidden_key(payload), "target_graph_forbidden_key")
    output: dict[str, dict[str, Tensor]] = {}
    node_dim = None
    required = {"node_features", "edge_index", "edge_features", "interface_mask", "hotspot_mask"}
    for receptor in RECEPTORS:
        graph = payload[receptor]
        require(isinstance(graph, Mapping) and required <= set(graph), f"target_graph_fields:{receptor}")
        tensors = {field: graph[field].detach().cpu() for field in required}
        require(tensors["edge_features"].shape[1] == expected_edge_dim, f"target_edge_dim:{receptor}")
        node_dim = tensors["node_features"].shape[1] if node_dim is None else node_dim
        require(tensors["node_features"].shape[1] == node_dim, "target_node_dim_mismatch")
        output[receptor] = tensors
    return output


class TinyTokenizer:
    def __call__(self, sequences: Sequence[str], **_: Any) -> dict[str, Tensor]:
        width = max(len(sequence) for sequence in sequences) + 2
        input_ids = torch.zeros((len(sequences), width), dtype=torch.long)
        attention = torch.zeros_like(input_ids)
        special = torch.zeros_like(input_ids)
        for item, sequence in enumerate(sequences):
            valid = len(sequence) + 2
            input_ids[item, 0] = 1
            input_ids[item, 1:valid-1] = torch.tensor([(ord(aa) % 20) + 3 for aa in sequence])
            input_ids[item, valid-1] = 2
            attention[item, :valid] = 1
            special[item, 0] = special[item, valid-1] = 1
        return {"input_ids": input_ids, "attention_mask": attention, "special_tokens_mask": special}


class TinyBackbone(nn.Module):
    def __init__(self, hidden: int = 16) -> None:
        super().__init__()
        self.embedding = nn.Embedding(32, hidden)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Any:
        del attention_mask
        return type("Output", (), {"last_hidden_state": self.embedding(input_ids)})()


class CleanCollator:
    def __init__(self, rows: Sequence[CandidateRow], tokenizer: Any, graphs: GraphCacheStore, weights: Mapping[int, float]) -> None:
        self.rows, self.tokenizer, self.graphs, self.weights = rows, tokenizer, graphs, dict(weights)

    def __call__(self, indices: Sequence[int]) -> dict[str, Tensor]:
        selected = [self.rows[index] for index in indices]
        encoded = self.tokenizer([row.sequence for row in selected], padding=True, truncation=False, return_tensors="pt", return_special_tokens_mask=True)
        require("special_tokens_mask" in encoded, "tokenizer_special_tokens_mask_missing")
        residue_mask = encoded["attention_mask"].bool() & ~encoded["special_tokens_mask"].bool()
        batch_size, width = encoded["input_ids"].shape
        aa = torch.zeros((batch_size, width), dtype=torch.long)
        region = torch.zeros((batch_size, width), dtype=torch.long)
        confidence = torch.zeros((batch_size, width), dtype=torch.float32)
        edge_indices, edge_features = [], []
        for item, row in enumerate(selected):
            positions = residue_mask[item].nonzero(as_tuple=False).flatten()
            graph = self.graphs.graph(row.candidate_id)
            require(len(positions) == len(row.sequence) == len(graph["aa_index"]), f"token_graph_alignment:{row.candidate_id}")
            aa[item, positions] = torch.from_numpy(graph["aa_index"]).long()
            region[item, positions] = torch.from_numpy(graph["region_index"]).long()
            confidence[item, positions] = torch.from_numpy(graph["confidence"]).float()
            local = torch.from_numpy(graph["edge_index"]).long()
            edge_indices.append(torch.stack((positions[local[0]], positions[local[1]])) + item * width)
            edge_features.append(torch.from_numpy(graph["edge_features"]).float())
        batch: dict[str, Tensor] = {
            "input_ids": encoded["input_ids"].long(),
            "attention_mask": encoded["attention_mask"].long(),
            "residue_mask": residue_mask,
            "vhh_aa_index": aa,
            "vhh_region_index": region,
            "vhh_confidence": confidence,
            "vhh_edge_index": torch.cat(edge_indices, dim=1),
            "vhh_edge_features": torch.cat(edge_features, dim=0),
            "targets": torch.tensor([row.targets for row in selected], dtype=torch.float32),
            "hierarchy_weights": torch.tensor([self.weights.get(index, 1.0) for index in indices], dtype=torch.float32),
        }
        require(not (set(batch) & FORBIDDEN_NEURAL_INPUTS), "collator_forbidden_input_key")
        return batch


def move(value: Any, device: torch.device) -> Any:
    if isinstance(value, Tensor):
        return value.to(device)
    if isinstance(value, Mapping):
        return {key: move(item, device) for key, item in value.items()}
    return value


def iter_batches(indices: Sequence[int], collator: CleanCollator, batch_size: int, *, shuffle_seed: int | None) -> Iterable[tuple[list[int], dict[str, Tensor]]]:
    selected = list(indices)
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(selected)
    for start in range(0, len(selected), batch_size):
        batch_indices = selected[start:start+batch_size]
        yield batch_indices, collator(batch_indices)


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0 + 1.0
        start = end
    return ranks


def spearman(target: np.ndarray, prediction: np.ndarray) -> float:
    left, right = _rankdata(target), _rankdata(prediction)
    if np.std(left) == 0.0 or np.std(right) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def regression_metrics(target: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    delta = prediction - target
    return {"spearman": spearman(target, prediction), "mae": float(np.mean(np.abs(delta))), "rmse": float(np.sqrt(np.mean(delta*delta)))}


def ranked_indices(candidate_ids: Sequence[str], values: np.ndarray) -> list[int]:
    require(len(candidate_ids) == len(values), "ranking_length_mismatch")
    return sorted(range(len(values)), key=lambda index: (-float(values[index]), candidate_ids[index]))


def binary_ndcg(candidate_ids: Sequence[str], relevance: np.ndarray, score: np.ndarray, k: int) -> float:
    require(0 < k <= len(candidate_ids), "ndcg_k_invalid")
    order = ranked_indices(candidate_ids, score)[:k]
    discounts = np.log2(np.arange(2, len(order) + 2, dtype=np.float64))
    dcg = float(np.sum(relevance[order] / discounts))
    positives = min(int(np.sum(relevance)), k)
    if positives == 0:
        return 0.0
    ideal_discounts = np.log2(np.arange(2, positives + 2, dtype=np.float64))
    return dcg / float(np.sum(1.0 / ideal_discounts))


def enrichment_table(candidate_ids: Sequence[str], truth: np.ndarray, score: np.ndarray) -> list[dict[str, Any]]:
    require(len(candidate_ids) == len(truth) == len(score) and len(truth) > 0, "enrichment_length_invalid")
    count = len(truth)
    true_order = ranked_indices(candidate_ids, truth)
    predicted_order = ranked_indices(candidate_ids, score)
    result: list[dict[str, Any]] = []
    for true_fraction in (0.10, 0.20):
        positives = max(1, math.ceil(count * true_fraction))
        true_indices = set(true_order[:positives])
        prevalence = positives / count
        relevance = np.asarray([1.0 if index in true_indices else 0.0 for index in range(count)])
        for budget_fraction in (0.05, 0.10, 0.20):
            selected = max(1, math.ceil(count * budget_fraction))
            predicted_indices = set(predicted_order[:selected])
            hits = len(true_indices & predicted_indices)
            precision = hits / selected
            result.append({
                "true_top_fraction": true_fraction,
                "predicted_budget_fraction": budget_fraction,
                "n": count,
                "positives": positives,
                "selected": selected,
                "hits": hits,
                "precision": precision,
                "recall": hits / positives,
                "enrichment_factor": precision / prevalence,
                "binary_ndcg": binary_ndcg(candidate_ids, relevance, score, selected),
            })
    return result


def within_parent_top20(
    candidate_ids: Sequence[str],
    parents: Sequence[str],
    truth: np.ndarray,
    score: np.ndarray,
) -> dict[str, Any]:
    require(len(candidate_ids) == len(parents) == len(truth) == len(score), "within_parent_length_mismatch")
    groups: dict[str, list[int]] = defaultdict(list)
    for index, parent in enumerate(parents):
        groups[parent].append(index)
    details: list[dict[str, Any]] = []
    for parent, indices in sorted(groups.items()):
        selected = max(1, math.ceil(len(indices) * 0.20))
        true_order = sorted(indices, key=lambda index: (-float(truth[index]), candidate_ids[index]))[:selected]
        predicted_order = sorted(indices, key=lambda index: (-float(score[index]), candidate_ids[index]))[:selected]
        hits = len(set(true_order) & set(predicted_order))
        recall = hits / selected
        details.append({
            "parent": parent,
            "n": len(indices),
            "k": selected,
            "hits": hits,
            "recall": recall,
            "enrichment_factor": recall / (selected / len(indices)),
        })
    require(bool(details), "within_parent_empty")
    return {
        "macro_recall": float(np.mean([item["recall"] for item in details])),
        "macro_enrichment_factor": float(np.mean([item["enrichment_factor"] for item in details])),
        "parents": details,
    }


def comprehensive_metrics(
    candidate_ids: Sequence[str],
    parents: Sequence[str],
    target: np.ndarray,
    prediction: np.ndarray,
) -> dict[str, Any]:
    require(target.shape == prediction.shape == (len(candidate_ids), 2), "metric_shape_invalid")
    target_dual = np.min(target, axis=1)
    prediction_dual = np.min(prediction, axis=1)
    enrichment = enrichment_table(candidate_ids, target_dual, prediction_dual)
    lookup = {(item["true_top_fraction"], item["predicted_budget_fraction"]): item for item in enrichment}
    parent_metrics = within_parent_top20(candidate_ids, parents, target_dual, prediction_dual)
    return {
        "R_8X6B": regression_metrics(target[:, 0], prediction[:, 0]),
        "R_9E6Y": regression_metrics(target[:, 1], prediction[:, 1]),
        "R_dual_min": regression_metrics(target_dual, prediction_dual),
        "early_enrichment": enrichment,
        "primary_early_enrichment": {
            "recall_true_top20_at_budget20": lookup[(0.20, 0.20)]["recall"],
            "ef_true_top10_at_budget10": lookup[(0.10, 0.10)]["enrichment_factor"],
            "binary_ndcg_true_top10_at_budget10": lookup[(0.10, 0.10)]["binary_ndcg"],
            "within_parent_macro_recall_top20": parent_metrics["macro_recall"],
        },
        "within_parent_top20": parent_metrics,
    }


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_backbone(args: argparse.Namespace) -> tuple[nn.Module, Any, int, str]:
    if args.backbone_kind == "tiny":
        require(args.tiny_e2e, "tiny_backbone_test_only")
        backbone, tokenizer, hidden, identity = TinyBackbone(args.tiny_hidden_size), TinyTokenizer(), args.tiny_hidden_size, "tiny_synthetic"
    else:
        require(args.model_path is not None and args.model_path.is_dir() and not args.model_path.is_symlink(), "local_model_directory_required")
        require(args.model_identity_file is not None and args.model_identity_file.is_file() and not args.model_identity_file.is_symlink(), "model_identity_file_required")
        identity = sha256_file(args.model_identity_file)
        require(args.expected_model_sha256 == identity, "model_identity_sha256_mismatch")
        try:
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:
            raise CleanAttentionError("transformers_required") from error
        tokenizer = AutoTokenizer.from_pretrained(str(args.model_path), local_files_only=True, trust_remote_code=False)
        dtype = torch.bfloat16 if args.backbone_dtype == "bf16" else torch.float32
        backbone = AutoModel.from_pretrained(str(args.model_path), local_files_only=True, trust_remote_code=False, torch_dtype=dtype)
        hidden = getattr(backbone.config, "hidden_size", None) or getattr(backbone.config, "d_model", None)
        require(hidden is not None, "backbone_hidden_size_missing")
    for parameter in backbone.parameters():
        parameter.requires_grad_(False)
    return backbone, tokenizer, int(hidden), identity


def build_clean_model(args: argparse.Namespace, contract: Mapping[str, Any], edge_dim: int, target_dim: int) -> tuple[nn.Module, Any, Any, Any, str]:
    model_module, trainer_module = load_frozen_ortho_modules(contract)
    backbone, tokenizer, hidden, identity = load_backbone(args)
    config = model_module.ResidueV25OrthoConfig.for_lane(
        LANE,
        backbone_hidden_size=hidden,
        target_node_dim=target_dim,
        edge_feature_dim=edge_dim,
        graph_hidden_dim=args.graph_hidden_dim,
        dropout=args.dropout,
        enable_contact_evidence=False,
        contact_encoder_gradient="detached",
    )
    model = trainer_module.build_model(LANE, backbone, config)
    loss = trainer_module.OrthoLossConfig(
        receptor_weight=args.receptor_weight,
        dual_weight=args.dual_weight,
        marginal_weight=0.0,
        pair_weight=0.0,
        huber_beta=args.huber_beta,
        softmin_tau=args.softmin_tau,
    )
    trainer_module.trainer_contract(LANE, model, loss)
    require(model.head.contact_interaction is None and model.head.contact_calibration is None, "contact_modules_must_be_absent")
    return model, tokenizer, loss, trainer_module, identity


def evaluate(
    model: nn.Module,
    trainer: Any,
    rows: Sequence[CandidateRow],
    indices: Sequence[int],
    collator: CleanCollator,
    target_graphs: Mapping[str, Mapping[str, Tensor]],
    device: torch.device,
    precision: str,
    batch_size: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    model.eval()
    target_device = move(target_graphs, device)
    truth, predicted = [], []
    records: list[dict[str, str]] = []
    exact_min_max_abs_error = 0.0
    with torch.no_grad():
        for batch_indices, raw in iter_batches(indices, collator, batch_size, shuffle_seed=None):
            batch = move(raw, device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=precision == "bf16"):
                output = trainer.forward_lane(model, LANE, batch, target_device)
            receptor = output["receptor_predictions"].float().cpu().numpy()
            exact = np.minimum(receptor[:, 0], receptor[:, 1])
            reported_exact = output["exact_min_dual"].float().cpu().numpy()
            batch_exact_error = float(np.max(np.abs(exact - reported_exact)))
            require(batch_exact_error <= 1e-7, f"model_exact_min_mismatch:{batch_exact_error}")
            exact_min_max_abs_error = max(exact_min_max_abs_error, batch_exact_error)
            targets = raw["targets"].numpy()
            truth.append(targets)
            predicted.append(receptor)
            for local, index in enumerate(batch_indices):
                row = rows[index]
                records.append({
                    "candidate_id": row.candidate_id,
                    "parent_framework_cluster": row.parent,
                    "target_R_8X6B": f"{targets[local,0]:.12g}",
                    "target_R_9E6Y": f"{targets[local,1]:.12g}",
                    "target_R_dual_min": f"{min(targets[local]):.12g}",
                    "prediction_R_8X6B": f"{receptor[local,0]:.12g}",
                    "prediction_R_9E6Y": f"{receptor[local,1]:.12g}",
                    "prediction_R_dual_min": f"{exact[local]:.12g}",
                    "exact_min_abs_error": f"{abs(exact[local]-reported_exact[local]):.12g}",
                })
    target_array, prediction_array = np.concatenate(truth), np.concatenate(predicted)
    metrics = comprehensive_metrics(
        [rows[index].candidate_id for index in indices],
        [rows[index].parent for index in indices],
        target_array,
        prediction_array,
    )
    metrics["exact_min_max_abs_error"] = exact_min_max_abs_error
    metrics["rows"] = len(records)
    return metrics, records


def _write_predictions(path: Path, records: Sequence[Mapping[str, str]]) -> None:
    require(bool(records), "predictions_empty")
    from io import StringIO
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(records[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    _atomic_text(path, buffer.getvalue())


def train(args: argparse.Namespace) -> dict[str, Any]:
    seed_everything(args.seed)
    contract = load_contract(args.contract)
    if not args.tiny_e2e:
        fixed = contract["fixed_hyperparameters"]
        observed = {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "gradient_accumulation": args.gradient_accumulation,
            "precision": args.precision,
            "learning_rate": args.learning_rate,
            "weight_decay": args.weight_decay,
            "graph_hidden_dim": args.graph_hidden_dim,
            "dropout": args.dropout,
            "receptor_weight": args.receptor_weight,
            "dual_weight": args.dual_weight,
            "huber_beta": args.huber_beta,
            "softmin_tau": args.softmin_tau,
        }
        require(observed == fixed, f"fixed_hyperparameter_drift:{observed}")
        task = contract.get("task") or {}
        require(args.seed == int(task.get("seed", -1)), f"seed_not_frozen:{args.seed}")
        require(int(task.get("fold_id", -1)) in range(5), "fold_id_not_frozen")
    expected = contract["expected_counts"]
    training_path = _verify_bound_file(contract["training_table"], "training_table")
    split_path = _verify_bound_file(contract["split_manifest"], "split_manifest")
    target_receipt_path = _verify_bound_file(contract["fixed_target_graph"]["receipt"], "target_graph_receipt")
    target_path = _verify_bound_file(contract["fixed_target_graph"]["torch_artifact"], "target_graph_pt")
    rows = load_rows(training_path, int(expected["total"]))
    split = load_split(split_path, rows, int(expected["train"]), int(expected["score"]))
    graph_store = GraphCacheStore(args.graph_cache_dir, rows, require_full_receipt=not args.tiny_e2e)
    target_graphs = load_target_graphs(target_path, graph_store.edge_feature_dim, target_receipt_path)
    target_dim = int(next(iter(target_graphs.values()))["node_features"].shape[1])
    model, tokenizer, loss_config, trainer, model_identity = build_clean_model(args, contract, graph_store.edge_feature_dim, target_dim)
    weights = {index: rows[index].sample_weight for index in split.train_indices}
    collator = CleanCollator(rows, tokenizer, graph_store, weights)
    probe = collator(split.train_indices[: min(2, len(split.train_indices))])
    neural = trainer.neural_forward_kwargs(probe, target_graphs)
    require(set(neural) == set(trainer.NEURAL_REQUIRED_BATCH_FIELDS) | {"target_graphs"}, "neural_allowlist_drift")
    require(not (set(neural) & FORBIDDEN_NEURAL_INPUTS), "neural_forbidden_input_detected")

    require(not args.output_dir.exists(), "output_dir_exists")
    args.output_dir.mkdir(parents=True)
    _atomic_json(args.output_dir / "RUNNING.json", {
        "schema_version": SCHEMA_VERSION,
        "status": "RUNNING_FIXED_EPOCH_CLEAN_ATTENTION_INNER_OOF_FOLD",
        "seed": args.seed,
        "fold_id": int(contract["task"]["fold_id"]),
        "split_id": split.split_id,
        "lane": LANE,
    })
    device = torch.device(args.device)
    require(device.type != "cuda" or torch.cuda.is_available(), "cuda_unavailable")
    model.to(device)
    target_device = move(target_graphs, device)
    optimizer, optimizer_audit = trainer.build_optimizer(
        model,
        trainer.OptimizerConfig(learning_rate=args.learning_rate, weight_decay=args.weight_decay, contact_learning_rate_multiplier=1.0),
    )
    require(optimizer_audit["contact"]["parameter_values"] == 0, "optimizer_contact_parameters_nonzero")
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    history: list[dict[str, Any]] = []
    optimizer_steps = 0
    for epoch in range(args.epochs):
        model.train()
        model.backbone.eval()
        optimizer.zero_grad(set_to_none=True)
        sums: dict[str, float] = defaultdict(float)
        batches = 0
        for _batch_indices, raw in iter_batches(split.train_indices, collator, args.batch_size, shuffle_seed=args.seed + epoch):
            batch = move(raw, device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=args.precision == "bf16"):
                output = trainer.forward_lane(model, LANE, batch, target_device)
                total, parts = trainer.compute_loss(output, batch, LANE, loss_config)
            (total / args.gradient_accumulation).backward()
            batches += 1
            for name, value in parts.items():
                sums[name] += float(value.detach().cpu())
            if batches % args.gradient_accumulation == 0:
                nn.utils.clip_grad_norm_(trainable, args.gradient_clip, error_if_nonfinite=True)
                optimizer.step()
                trainer.assert_train_state_finite(model, optimizer)
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1
        require(batches > 0, f"epoch_empty:{epoch}")
        remainder = batches % args.gradient_accumulation
        if remainder:
            correction = args.gradient_accumulation / remainder
            for parameter in trainable:
                if parameter.grad is not None:
                    parameter.grad.mul_(correction)
            nn.utils.clip_grad_norm_(trainable, args.gradient_clip, error_if_nonfinite=True)
            optimizer.step()
            trainer.assert_train_state_finite(model, optimizer)
            optimizer.zero_grad(set_to_none=True)
            optimizer_steps += 1
        epoch_record = {"epoch": epoch + 1, "batches": batches, **{name: value/batches for name, value in sorted(sums.items())}}
        history.append(epoch_record)
        _atomic_json(args.output_dir / HISTORY_NAME, {"selection": "NONE_FIXED_EPOCH_ONLY", "epochs": history})

    metrics, records = evaluate(model, trainer, rows, split.development_indices, collator, target_graphs, device, args.precision, args.eval_batch_size)
    row_by_id = {row.candidate_id: row for row in rows}
    for record in records:
        record["sequence_sha256"] = row_by_id[record["candidate_id"]].sequence_sha256
        record["fold_id"] = str(int(contract["task"]["fold_id"]))
        record["seed"] = str(args.seed)
    prediction_path = args.output_dir / PREDICTION_NAME
    _write_predictions(prediction_path, records)
    checkpoint_path = args.output_dir / CHECKPOINT_NAME
    _atomic_torch_save(checkpoint_path, {
        "schema_version": SCHEMA_VERSION,
        "lane": LANE,
        "seed": args.seed,
        "split_id": split.split_id,
        "head_config": asdict(model.head.config),
        "head_state_dict": {name: value.detach().cpu() for name, value in model.head.state_dict().items()},
        "backbone_identity_sha256": model_identity,
    })
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V2_12_CLEAN_ATTENTION_INNER_OOF_FOLD_TRAINING",
        "lane": LANE,
        "claim_boundary": CLAIM_BOUNDARY,
        "seed": args.seed,
        "fold_id": int(contract["task"]["fold_id"]),
        "split": {
            "split_id": split.split_id,
            "train_rows": len(split.train_indices),
            "score_rows": len(split.development_indices),
            "train_parents": len(split.train_parents),
            "score_parents": len(split.development_parents),
            "whole_parent_overlap": 0,
        },
        "training": {
            "fixed_epochs": args.epochs,
            "selection": "NONE_FIXED_EPOCH_ONLY",
            "optimizer_steps": optimizer_steps,
            "batch_size": args.batch_size,
            "gradient_accumulation": args.gradient_accumulation,
            "precision": args.precision,
            "loss": asdict(loss_config),
            "optimizer_parameter_roles": optimizer_audit,
            "weighting": "manifest_sample_weight_normalized_within_each_minibatch",
        },
        "metrics": metrics,
        "neural_input_firewall": {
            "allowlist": list(trainer.NEURAL_REQUIRED_BATCH_FIELDS) + ["target_graphs"],
            "forbidden": sorted(FORBIDDEN_NEURAL_INPUTS),
            "candidate_id_input_count": 0,
            "parent_id_input_count": 0,
            "m2_input_count": 0,
            "c2_input_count": 0,
            "contact_input_count": 0,
            "candidate_docking_pose_input_count": 0,
        },
        "input_bindings": {
            "contract_sha256": sha256_file(args.contract),
            "training_table_sha256": sha256_file(training_path),
            "split_manifest_sha256": sha256_file(split_path),
            "target_graph_receipt_sha256": sha256_file(target_receipt_path),
            "target_graph_pt_sha256": sha256_file(target_path),
            "ortho_model_sha256": str(contract["ortho_model"]["sha256"]),
            "ortho_trainer_sha256": str(contract["ortho_trainer"]["sha256"]),
            "backbone_identity_file_sha256": model_identity,
            "graph_bundle_sha256": graph_store.input_hashes,
        },
        "outputs": {
            PREDICTION_NAME: sha256_file(prediction_path),
            CHECKPOINT_NAME: sha256_file(checkpoint_path),
            HISTORY_NAME: sha256_file(args.output_dir / HISTORY_NAME),
        },
        "backbone_identity_sha256": model_identity,
        "exact_min_inference": True,
        "open_development_access_count": 0,
        "frozen_test_access_count": 0,
    }
    _atomic_json(args.output_dir / RESULT_NAME, receipt)
    (args.output_dir / "RUNNING.json").unlink()
    return receipt


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--contract", type=Path, required=True)
    value.add_argument("--graph-cache-dir", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--device", default="cuda:0")
    value.add_argument("--seed", type=int, required=True)
    value.add_argument("--epochs", type=int, default=8)
    value.add_argument("--batch-size", type=int, default=8)
    value.add_argument("--eval-batch-size", type=int, default=16)
    value.add_argument("--gradient-accumulation", type=int, default=4)
    value.add_argument("--precision", choices=("fp32", "bf16"), default="bf16")
    value.add_argument("--learning-rate", type=float, default=1e-4)
    value.add_argument("--weight-decay", type=float, default=0.02)
    value.add_argument("--gradient-clip", type=float, default=1.0)
    value.add_argument("--graph-hidden-dim", type=int, default=128)
    value.add_argument("--dropout", type=float, default=0.25)
    value.add_argument("--receptor-weight", type=float, default=1.0)
    value.add_argument("--dual-weight", type=float, default=0.5)
    value.add_argument("--huber-beta", type=float, default=0.03)
    value.add_argument("--softmin-tau", type=float, default=0.02)
    value.add_argument("--backbone-kind", choices=("hf", "tiny"), default="hf")
    value.add_argument("--backbone-dtype", choices=("fp32", "bf16"), default="bf16")
    value.add_argument("--model-path", type=Path)
    value.add_argument("--model-identity-file", type=Path)
    value.add_argument("--expected-model-sha256")
    value.add_argument("--tiny-hidden-size", type=int, default=16)
    value.add_argument("--tiny-e2e", action="store_true")
    return value


def validate_args(args: argparse.Namespace) -> None:
    require(args.epochs > 0 and args.batch_size > 0 and args.eval_batch_size > 0, "training_count_invalid")
    require(args.gradient_accumulation > 0, "gradient_accumulation_invalid")
    require(args.learning_rate > 0 and args.weight_decay >= 0 and args.gradient_clip > 0, "optimizer_config_invalid")
    require(args.precision == "fp32" or args.device.startswith("cuda"), "bf16_requires_cuda")
    if args.backbone_kind == "hf":
        require(not args.tiny_e2e, "hf_tiny_e2e_invalid")
        require(args.model_path is not None and args.model_identity_file is not None and args.expected_model_sha256, "hf_model_binding_required")


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    validate_args(args)
    result = train(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
