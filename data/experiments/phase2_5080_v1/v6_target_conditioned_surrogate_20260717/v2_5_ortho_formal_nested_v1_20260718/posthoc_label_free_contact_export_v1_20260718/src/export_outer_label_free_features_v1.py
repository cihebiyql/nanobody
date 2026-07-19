#!/usr/bin/env python3
"""Replay frozen V2.5 outer-refit heads on strictly label-free inputs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
from torch import Tensor, nn


SCHEMA = "pvrig_v2_5_label_free_contact_export_contract_v1"
OUTPUT_SCHEMA = "pvrig_v2_5_label_free_contact_export_v1"
LANE = "E_DECOUPLED_CONTACT_SHARED"
SEEDS = (43, 97, 193)
PANEL_FIELDS = ("candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster", "outer_fold")
SOURCE_PREDICTION_FIELDS = (
    "candidate_id", "neural_R8", "neural_R9", "neural_Rdual",
    "contact_score_R8", "contact_score_R9",
)
PAIR_FEATURES = (
    "hotspot_mass_8x6b", "interface_specificity_8x6b", "cdr1_contact_mass_8x6b",
    "cdr2_contact_mass_8x6b", "cdr3_contact_mass_8x6b", "contact_entropy_8x6b",
    "hotspot_mass_9e6y", "interface_specificity_9e6y", "cdr1_contact_mass_9e6y",
    "cdr2_contact_mass_9e6y", "cdr3_contact_mass_9e6y", "contact_entropy_9e6y",
    "dual_hotspot_min", "conformer_hotspot_gap",
)
ENSEMBLE_FEATURES = (
    "neural_R8", "neural_R9", "neural_Rdual", "contact_score_R8", "contact_score_R9", *PAIR_FEATURES,
)


class ExportError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExportError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_sealed_path(path: Path) -> None:
    normalized = str(path).lower().replace("-", "_")
    require("v4_f" not in normalized and "test32" not in normalized, f"sealed_path_forbidden:{path}")


def verify_record(value: Mapping[str, Any], label: str) -> Path:
    path = Path(str(value.get("path", "")))
    reject_sealed_path(path)
    require(path.is_file() and not path.is_symlink(), f"{label}_missing_or_symlink:{path}")
    require(path.stat().st_size == int(value.get("bytes", -1)), f"{label}_bytes:{path}")
    require(sha256_file(path) == value.get("sha256"), f"{label}_sha256:{path}")
    return path


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


@dataclass(frozen=True)
class PanelRow:
    candidate_id: str
    sequence: str
    sequence_sha256: str
    parent: str
    outer_fold: int


def load_panel(path: Path) -> list[PanelRow]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(tuple(reader.fieldnames or ()) == PANEL_FIELDS, "label_free_panel_fields_not_exact")
        raw = list(reader)
    rows = []
    seen: set[str] = set()
    for source in raw:
        candidate = source["candidate_id"]
        sequence = source["sequence"].strip().upper()
        require(candidate and candidate not in seen, f"panel_candidate_duplicate_or_blank:{candidate}")
        require(sequence and hashlib.sha256(sequence.encode()).hexdigest() == source["sequence_sha256"], f"panel_sequence_hash:{candidate}")
        require(source["parent_framework_cluster"], f"panel_parent_blank:{candidate}")
        rows.append(PanelRow(candidate, sequence, source["sequence_sha256"], source["parent_framework_cluster"], int(source["outer_fold"])))
        seen.add(candidate)
    require(rows, "panel_empty")
    return rows


class LabelFreeGraphStore:
    def __init__(self, directory: Path, records: Mapping[str, Mapping[str, Any]], rows: Sequence[PanelRow]) -> None:
        reject_sealed_path(directory)
        require(directory.is_dir() and not directory.is_symlink(), "graph_cache_dir")
        paths = {name: verify_record(records[name], f"graph_{name}") for name in records}
        require(set(paths) == {"graph_manifest_v2.tsv", "graph_cache_receipt_v2.json", "graph_cache_v2.npz"}, "graph_file_closure")
        require(all(path.parent.resolve() == directory.resolve() for path in paths.values()), "graph_record_directory_mismatch")
        receipt = json.loads(paths["graph_cache_receipt_v2.json"].read_text())
        require(receipt.get("status") == "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE", "graph_receipt_status")
        require("teacher" not in str(receipt.get("claim_boundary", "")).lower() or "no" in str(receipt.get("claim_boundary", "")).lower(), "graph_receipt_claim")
        require(receipt.get("outputs", {}).get("graph_manifest_v2.tsv") == records["graph_manifest_v2.tsv"]["sha256"], "graph_manifest_receipt_hash")
        require(receipt.get("outputs", {}).get("graph_cache_v2.npz") == records["graph_cache_v2.npz"]["sha256"], "graph_npz_receipt_hash")
        with paths["graph_manifest_v2.tsv"].open(newline="") as handle:
            manifest_rows = list(csv.DictReader(handle, delimiter="\t"))
        self.manifest = {row["entity_id"]: row for row in manifest_rows}
        require(len(self.manifest) == len(manifest_rows), "graph_manifest_duplicate")
        require(set(self.manifest) == {row.candidate_id for row in rows}, "graph_candidate_exact_closure")
        require(int(receipt["counts"].get("entities", len(rows))) == len(rows), "graph_receipt_entity_count")
        for row in rows:
            require(self.manifest[row.candidate_id]["sequence_sha256"] == row.sequence_sha256, f"graph_sequence_hash:{row.candidate_id}")
        self.arrays = np.load(paths["graph_cache_v2.npz"], mmap_mode="r")
        expected_arrays = {"aa_index", "region_index", "confidence", "edge_index", "edge_features"}
        require(expected_arrays <= set(self.arrays.files), "graph_arrays_missing")
        self.edge_feature_dim = int(self.arrays["edge_features"].shape[1])
        require(self.edge_feature_dim == int(receipt["counts"]["edge_feature_dim"]), "graph_edge_feature_dim")
        require(int(receipt["counts"].get("nodes", len(self.arrays["aa_index"]))) == len(self.arrays["aa_index"]), "graph_receipt_node_count")
        require(int(receipt["counts"].get("edges", self.arrays["edge_index"].shape[1])) == self.arrays["edge_index"].shape[1], "graph_receipt_edge_count")

    def graph(self, candidate: str) -> dict[str, np.ndarray]:
        row = self.manifest[candidate]
        ns, ne = int(row["node_start"]), int(row["node_end"])
        es, ee = int(row["edge_start"]), int(row["edge_end"])
        edge_index = self.arrays["edge_index"][:, es:ee] - ns
        require(bool(np.all((edge_index >= 0) & (edge_index < ne - ns))), f"graph_edge_bounds:{candidate}")
        return {
            "aa_index": self.arrays["aa_index"][ns:ne],
            "region_index": self.arrays["region_index"][ns:ne],
            "confidence": self.arrays["confidence"][ns:ne],
            "edge_index": edge_index,
            "edge_features": self.arrays["edge_features"][es:ee],
        }


def contains_forbidden_source_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower() in {"teacher_source", "source_id", "campaign_id"} or contains_forbidden_source_key(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_forbidden_source_key(item) for item in value)
    return False


def load_target_graph(path: Path, edge_dim: int) -> dict[str, dict[str, Tensor]]:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if isinstance(payload, Mapping) and "target_graphs" in payload:
        payload = payload["target_graphs"]
    require(isinstance(payload, Mapping) and set(payload) == {"8x6b", "9e6y"}, "target_receptor_closure")
    require(not contains_forbidden_source_key(payload), "target_forbidden_source_key")
    output = {}
    for receptor in ("8x6b", "9e6y"):
        graph = payload[receptor]
        required = {"node_features", "edge_index", "edge_features", "interface_mask", "hotspot_mask"}
        require(isinstance(graph, Mapping) and required <= set(graph), f"target_fields:{receptor}")
        tensors = {name: graph[name].detach().cpu() for name in required}
        require(tensors["edge_features"].shape[1] == edge_dim, f"target_edge_dim:{receptor}")
        require(tensors["interface_mask"].shape == tensors["hotspot_mask"].shape == (len(tensors["node_features"]),), f"target_masks:{receptor}")
        output[receptor] = tensors
    require(output["8x6b"]["node_features"].shape[1] == output["9e6y"]["node_features"].shape[1], "target_node_dim")
    return output


class TinyTokenizer:
    pad_token_id = 0
    def __init__(self) -> None:
        self.vocab = {aa: index + 3 for index, aa in enumerate("ACDEFGHIKLMNPQRSTVWYX")}
    def __call__(self, sequences: Sequence[str], **_: Any) -> dict[str, Tensor]:
        encoded = [[1] + [self.vocab.get(aa, self.vocab["X"]) for aa in sequence] + [2] for sequence in sequences]
        width = max(map(len, encoded))
        ids, attention, special = [], [], []
        for value in encoded:
            padding = width - len(value)
            ids.append(value + [0] * padding)
            attention.append([1] * len(value) + [0] * padding)
            special.append([1] + [0] * (len(value) - 2) + [1] + [1] * padding)
        return {"input_ids": torch.tensor(ids), "attention_mask": torch.tensor(attention), "special_tokens_mask": torch.tensor(special)}


class TinyBackbone(nn.Module):
    def __init__(self, hidden: int, seed: int) -> None:
        super().__init__()
        generator_state = torch.random.get_rng_state()
        torch.manual_seed(seed)
        self.embedding = nn.Embedding(32, hidden)
        torch.random.set_rng_state(generator_state)
        self.config = SimpleNamespace(hidden_size=hidden)
    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Any:
        del attention_mask
        return SimpleNamespace(last_hidden_state=self.embedding(input_ids))


def load_model_module(path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(f"v25_export_model_{sha256_file(path)[:12]}", path)
    require(specification is not None and specification.loader is not None, "model_import_spec")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def load_backbone(contract: Mapping[str, Any]) -> tuple[nn.Module, Any, int]:
    kind = contract.get("kind")
    if kind == "tiny_test_only":
        require(contract.get("test_fixture") is True, "tiny_backbone_not_test_fixture")
        hidden, seed = int(contract["hidden_size"]), int(contract["initialization_seed"])
        return TinyBackbone(hidden, seed), TinyTokenizer(), hidden
    require(kind == "hf_local", "backbone_kind")
    model_path = Path(str(contract.get("model_path", "")))
    reject_sealed_path(model_path)
    require(model_path.is_dir() and not model_path.is_symlink(), "hf_model_path")
    identity = verify_record(contract["model_identity_file"], "model_identity")
    require(sha256_file(identity) == contract.get("expected_model_identity_sha256"), "model_identity_expected_hash")
    try:
        from transformers import AutoModel, AutoTokenizer
    except ImportError as error:
        raise ExportError("transformers_required") from error
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=False)
    backbone = AutoModel.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=False)
    hidden = getattr(backbone.config, "hidden_size", None) or getattr(backbone.config, "d_model", None)
    require(hidden is not None, "backbone_hidden_size")
    return backbone, tokenizer, int(hidden)


def collate(rows: Sequence[PanelRow], tokenizer: Any, graph_store: LabelFreeGraphStore) -> dict[str, Any]:
    encoded = tokenizer([row.sequence for row in rows], padding=True, truncation=False, return_tensors="pt", return_special_tokens_mask=True)
    require("special_tokens_mask" in encoded, "tokenizer_special_mask")
    residue_mask = encoded["attention_mask"].bool() & ~encoded["special_tokens_mask"].bool()
    batch_size, width = encoded["input_ids"].shape
    aa = torch.zeros((batch_size, width), dtype=torch.long)
    region = torch.zeros((batch_size, width), dtype=torch.long)
    confidence = torch.zeros((batch_size, width), dtype=torch.float32)
    edges, edge_features = [], []
    for item, row in enumerate(rows):
        positions = residue_mask[item].nonzero(as_tuple=False).flatten()
        graph = graph_store.graph(row.candidate_id)
        require(len(positions) == len(graph["aa_index"]), f"graph_token_alignment:{row.candidate_id}")
        aa[item, positions] = torch.from_numpy(np.asarray(graph["aa_index"]))
        region[item, positions] = torch.from_numpy(np.asarray(graph["region_index"]))
        confidence[item, positions] = torch.from_numpy(np.asarray(graph["confidence"]))
        local = torch.from_numpy(np.asarray(graph["edge_index"])).long()
        edges.append(torch.stack((positions[local[0]], positions[local[1]])) + item * width)
        edge_features.append(torch.from_numpy(np.asarray(graph["edge_features"])).float())
    return {
        "candidate_ids": [row.candidate_id for row in rows],
        "input_ids": encoded["input_ids"], "attention_mask": encoded["attention_mask"],
        "residue_mask": residue_mask, "vhh_aa_index": aa, "vhh_region_index": region,
        "vhh_confidence": confidence, "vhh_edge_index": torch.cat(edges, dim=1),
        "vhh_edge_features": torch.cat(edge_features, dim=0),
    }


def move(value: Any, device: torch.device) -> Any:
    if isinstance(value, Tensor):
        return value.to(device)
    if isinstance(value, Mapping):
        return {key: move(item, device) for key, item in value.items()}
    return value


def build_model(module: Any, backbone: nn.Module, hidden: int, target_graphs: Mapping[str, Mapping[str, Tensor]], edge_dim: int, checkpoint_path: Path, source_split_id: str) -> nn.Module:
    config = module.ResidueV25OrthoConfig(
        backbone_hidden_size=hidden,
        target_node_dim=int(target_graphs["8x6b"]["node_features"].shape[1]),
        edge_feature_dim=edge_dim,
        graph_hidden_dim=128,
        dropout=0.25,
        enable_contact_evidence=True,
        contact_encoder_gradient="shared",
    )
    model = module.OrthogonalResidueSurrogate(backbone, module.OrthogonalTargetHead(config))
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    require(payload.get("schema_version") == "pvrig_v2_5_ortho_real_head_checkpoint_v1", "checkpoint_schema")
    require(payload.get("lane") == LANE, "checkpoint_lane")
    require(payload.get("source_split_id") == source_split_id, "checkpoint_source_split_id")
    state = payload.get("head_state")
    require(isinstance(state, Mapping) and state, "checkpoint_head_state")
    require(all(str(name).startswith("head.") for name in state), "checkpoint_head_prefix")
    stripped = {str(name)[5:]: tensor for name, tensor in state.items()}
    require(set(stripped) == set(model.head.state_dict()), "checkpoint_head_key_closure")
    model.head.load_state_dict(stripped, strict=True)
    return model


def source_predictions(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(tuple(reader.fieldnames or ()) == SOURCE_PREDICTION_FIELDS, "source_prediction_fields")
        rows = list(reader)
    result = {row["candidate_id"]: row for row in rows}
    require(len(result) == len(rows), "source_prediction_duplicate")
    return result


def score_seed(
    model: nn.Module,
    score_rows: Sequence[PanelRow],
    tokenizer: Any,
    graph_store: LabelFreeGraphStore,
    target_graphs: Mapping[str, Mapping[str, Tensor]],
    source: Mapping[str, Mapping[str, str]],
    *,
    seed: int,
    device_name: str,
    batch_size: int,
    replay_atol: float,
) -> list[dict[str, Any]]:
    require(set(source) == {row.candidate_id for row in score_rows}, f"source_candidate_closure:{seed}")
    device = torch.device(device_name)
    model.to(device).eval()
    targets = move(target_graphs, device)
    records = []
    with torch.no_grad():
        for start in range(0, len(score_rows), batch_size):
            batch_rows = score_rows[start:start + batch_size]
            raw = collate(batch_rows, tokenizer, graph_store)
            batch = move(raw, device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                output = model(
                    input_ids=batch["input_ids"], attention_mask=batch["attention_mask"],
                    residue_mask=batch["residue_mask"], vhh_aa_index=batch["vhh_aa_index"],
                    vhh_region_index=batch["vhh_region_index"], vhh_confidence=batch["vhh_confidence"],
                    vhh_edge_index=batch["vhh_edge_index"], vhh_edge_features=batch["vhh_edge_features"],
                    target_graphs=targets,
                )
            receptor = output["receptor_predictions"].float().cpu().numpy()
            dual = output["exact_min_dual"].float().cpu().numpy()
            pair = output["pair_summary"].float().cpu().numpy()
            contact = output["contact_composite"].float().cpu().numpy()
            require(pair.shape == (len(batch_rows), 14) and contact.shape == (len(batch_rows), 2), "output_feature_shape")
            for item, row in enumerate(batch_rows):
                expected = source[row.candidate_id]
                observed_values = (receptor[item, 0], receptor[item, 1], dual[item], contact[item, 0], contact[item, 1])
                expected_values = tuple(float(expected[name]) for name in SOURCE_PREDICTION_FIELDS[1:])
                require(all(math.isfinite(float(value)) for value in observed_values), f"prediction_nonfinite:{seed}:{row.candidate_id}")
                require(abs(float(dual[item]) - min(float(receptor[item, 0]), float(receptor[item, 1]))) <= 1e-7, f"exact_min:{seed}:{row.candidate_id}")
                require(all(abs(float(left) - right) <= replay_atol for left, right in zip(observed_values, expected_values)), f"source_prediction_replay:{seed}:{row.candidate_id}")
                record: dict[str, Any] = {
                    "candidate_id": row.candidate_id, "parent_framework_cluster": row.parent,
                    "outer_fold": row.outer_fold, "seed": seed,
                    "neural_R8": float(receptor[item, 0]), "neural_R9": float(receptor[item, 1]),
                    "neural_Rdual": float(dual[item]), "contact_score_R8": float(contact[item, 0]),
                    "contact_score_R9": float(contact[item, 1]),
                }
                record.update({name: float(pair[item, index]) for index, name in enumerate(PAIR_FEATURES)})
                records.append(record)
    require(len(records) == len(score_rows), f"seed_row_closure:{seed}")
    return records


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    require(rows, f"empty_output:{path.name}")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def ensemble_rows(per_seed: Sequence[Mapping[str, Any]], rows: Sequence[PanelRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in per_seed:
        grouped.setdefault(str(record["candidate_id"]), []).append(record)
    output = []
    for row in rows:
        values = sorted(grouped.get(row.candidate_id, []), key=lambda value: int(value["seed"]))
        require(tuple(int(value["seed"]) for value in values) == SEEDS, f"ensemble_seed_closure:{row.candidate_id}")
        record: dict[str, Any] = {"candidate_id": row.candidate_id, "parent_framework_cluster": row.parent, "outer_fold": row.outer_fold}
        for feature in ENSEMBLE_FEATURES:
            vector = np.asarray([float(value[feature]) for value in values], dtype=np.float64)
            record[f"{feature}_mean"] = float(vector.mean())
            record[f"{feature}_std"] = float(vector.std(ddof=0))
        require(abs(record["neural_Rdual_mean"] - np.mean([min(float(v["neural_R8"]), float(v["neural_R9"])) for v in values])) <= 1e-12, f"ensemble_dual_semantics:{row.candidate_id}")
        output.append(record)
    return output


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--contract-json", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--device", default="cuda")
    value.add_argument("--batch-size", type=int, default=8)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    reject_sealed_path(args.contract_json); reject_sealed_path(args.output_dir)
    require(args.contract_json.is_file() and not args.contract_json.is_symlink(), "contract_json")
    require(not args.output_dir.exists(), "output_dir_exists")
    require(args.batch_size > 0, "batch_size")
    contract_sha = sha256_file(args.contract_json)
    contract = json.loads(args.contract_json.read_text())
    require(contract.get("schema_version") == SCHEMA and contract.get("status") == "FROZEN_LABEL_FREE_EXPORT_CONTRACT", "contract_schema_or_status")
    require(contract.get("lane") == LANE and tuple(contract.get("seeds", [])) == SEEDS, "contract_lane_or_seeds")
    require(tuple(int(item.get("seed")) for item in contract.get("outer_refits", [])) == SEEDS, "contract_outer_refit_seed_order")
    require(int(contract.get("teacher_metric_files_read", -1)) == 0 and int(contract.get("v4_f_test32_access_count", -1)) == 0, "contract_forbidden_access")
    require(math.isfinite(float(contract.get("replay_atol", -1))) and 0.0 < float(contract["replay_atol"]) <= 1e-4, "contract_replay_atol")
    require(contract.get("pair_summary_feature_scope") == "FUTURE_VERSION_DIAGNOSTIC_ONLY_NOT_CURRENT_V2_5_SELECTION", "pair_feature_scope")
    inputs = contract["inputs"]
    panel_path = verify_record(inputs["label_free_panel"], "label_free_panel")
    target_path = verify_record(inputs["target_graph"], "target_graph")
    model_source = verify_record(inputs["model_source"], "model_source")
    split_path = verify_record(inputs["split_manifest"], "split_manifest")
    rows = load_panel(panel_path)
    split = json.loads(split_path.read_text())
    outer_fold = int(contract["outer_fold"])
    require(split.get("open_only") is True and int(split.get("v4_f_test32_access_count", -1)) == 0, "split_not_open")
    require(int(split.get("outer_fold")) == outer_fold, "split_fold")
    train_parents, score_parents = set(split["train_parents"]), set(split["score_parents"])
    require(train_parents and score_parents and train_parents.isdisjoint(score_parents), "split_parent_overlap")
    require({row.parent for row in rows} == train_parents | score_parents, "split_parent_exact_closure")
    score_rows = [row for row in rows if row.parent in score_parents]
    require(score_rows and all(row.outer_fold == outer_fold for row in score_rows), "score_outer_fold")
    graph_store = LabelFreeGraphStore(Path(inputs["graph_cache"]["path"]), inputs["graph_cache"]["files"], rows)
    target_graphs = load_target_graph(target_path, graph_store.edge_feature_dim)
    module = load_model_module(model_source)
    backbone, tokenizer, hidden = load_backbone(contract["backbone"])
    all_records = []
    checkpoint_receipts = []
    for item in contract["outer_refits"]:
        seed = int(item["seed"])
        result_path = verify_record(item["result_receipt"], f"result_receipt_{seed}")
        result = json.loads(result_path.read_text())
        require(result.get("status") == "PASS_FORMAL_OUTER_REFIT" and result.get("lane", {}).get("variant") == LANE, f"result_contract:{seed}")
        require(int(result.get("outer_fold")) == outer_fold and int(result.get("formal_seed")) == seed, f"result_scope:{seed}")
        require(int(result.get("prediction_metrics_access_count", -1)) == 0 and int(result.get("v4_f_test32_access_count", -1)) == 0, f"result_access:{seed}")
        require(result.get("neural_input_firewall", {}).get("M2_126D_ID_pose_inputs") == 0, f"result_firewall:{seed}")
        require(str(result.get("formal_hparam_id")) == str(item.get("formal_hparam_id")), f"result_hparam:{seed}")
        require(str(result.get("source_split", {}).get("split_id")) == str(split.get("split_id")) == str(item.get("source_split_id")), f"result_split_id:{seed}")
        checkpoint = verify_record(item["checkpoint"], f"checkpoint_{seed}")
        source_path = verify_record(item["source_predictions_no_metrics"], f"source_predictions_{seed}")
        artifacts = result.get("artifacts", {})
        require(artifacts.get("neural_head", {}).get("sha256") == sha256_file(checkpoint), f"result_checkpoint_hash:{seed}")
        require(artifacts.get("predictions_no_metrics", {}).get("sha256") == sha256_file(source_path), f"result_source_prediction_hash:{seed}")
        model_contract = result.get("model_contract", {})
        config = model_contract.get("config", {})
        require(model_contract.get("contact_feedback_to_scalar") is False, f"result_contact_firewall:{seed}")
        require(config.get("enable_contact_evidence") is True and config.get("contact_encoder_gradient") == "shared", f"result_contact_config:{seed}")
        require(int(config.get("graph_hidden_dim", -1)) == 128 and float(config.get("dropout", -1)) == 0.25, f"result_model_config:{seed}")
        require(int(config.get("backbone_hidden_size", -1)) == hidden, f"result_backbone_hidden:{seed}")
        require(int(config.get("edge_feature_dim", -1)) == graph_store.edge_feature_dim, f"result_edge_dim:{seed}")
        require(int(config.get("target_node_dim", -1)) == int(target_graphs["8x6b"]["node_features"].shape[1]), f"result_target_dim:{seed}")
        model = build_model(module, backbone, hidden, target_graphs, graph_store.edge_feature_dim, checkpoint, str(split.get("split_id")))
        records = score_seed(model, score_rows, tokenizer, graph_store, target_graphs, source_predictions(source_path), seed=seed, device_name=args.device, batch_size=args.batch_size, replay_atol=float(contract["replay_atol"]))
        all_records.extend(records)
        checkpoint_receipts.append({"seed": seed, "checkpoint_sha256": sha256_file(checkpoint), "replayed_rows": len(records)})
    require(tuple(sorted({int(row["seed"]) for row in all_records})) == SEEDS, "output_seed_closure")
    ensemble = ensemble_rows(all_records, score_rows)
    args.output_dir.mkdir(parents=True)
    seed_path = args.output_dir / "OUTER_TEST_SEED_FEATURES.tsv"
    ensemble_path = args.output_dir / "OUTER_TEST_ENSEMBLE_FEATURES.tsv"
    write_tsv(seed_path, all_records); write_tsv(ensemble_path, ensemble)
    sums = args.output_dir / "SHA256SUMS"
    sums.write_text(f"{sha256_file(seed_path)}  {seed_path.name}\n{sha256_file(ensemble_path)}  {ensemble_path.name}\n")
    receipt = {
        "schema_version": OUTPUT_SCHEMA,
        "status": "PASS_LABEL_FREE_OUTER_CONTACT_REPLAY",
        "outer_fold": outer_fold, "lane": LANE, "seeds": list(SEEDS),
        "rows_per_seed": len(score_rows), "seed_rows": len(all_records), "ensemble_rows": len(ensemble),
        "contract": {"path": str(args.contract_json.resolve()), "sha256": contract_sha},
        "checkpoints": checkpoint_receipts,
        "outputs": {
            seed_path.name: {"sha256": sha256_file(seed_path), "rows": len(all_records)},
            ensemble_path.name: {"sha256": sha256_file(ensemble_path), "rows": len(ensemble)},
        },
        "source_prediction_replay": "PASS_ALL_SCALAR_AND_CONTACT_COMPOSITE_WITHIN_FROZEN_ATOL",
        "pair_summary_dimensions": 14,
        "ensemble_std_semantics": "population_std_ddof_0_across_seeds_43_97_193",
        "pair_summary_feature_scope": "FUTURE_VERSION_DIAGNOSTIC_ONLY_NOT_CURRENT_V2_5_SELECTION",
        "teacher_metric_files_read": 0,
        "v4_f_test32_access_count": 0,
    }
    atomic_json(args.output_dir / "EXPORT_RECEIPT.json", receipt)
    print(json.dumps({"status": receipt["status"], "rows": len(ensemble)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    raise SystemExit(main())
