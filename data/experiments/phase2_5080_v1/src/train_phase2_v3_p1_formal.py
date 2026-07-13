#!/usr/bin/env python3
"""Train formal multi-parent V3-P models without opening formal test labels.

Training consumes a train/dev-only teacher table and contact-frequency file.
The frozen all-candidate selection manifest is used for label-free test
inference, so checkpoint selection cannot depend on formal test labels.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np
import torch
from torch import nn
from torch.nn.utils.rnn import pad_sequence
from torch.utils.data import DataLoader, Dataset

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_phase2_v2_3 as v23  # noqa: E402
from phase2_v3_p1_model import (  # noqa: E402
    PVRIGModelConfig,
    PVRIGV3P1Model,
    RELEVANCE_TO_TIER,
    TIER_NAMES,
    TIER_TO_RELEVANCE,
    assert_backbone_frozen,
    checkpoint_model_metadata,
    generic_replay_consistency_loss,
    ordinal_cumulative_loss,
    teacher_auxiliary_losses,
    within_campaign_rank_loss,
)


DEFAULT_PREPARED = EXP_DIR / "prepared/pvrig_teacher_formal_v1"
DEFAULT_FORMAL_DATA = EXP_DIR / "prepared/phase2_v3_p1_formal"
DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"
DEFAULT_TARGET = DATA_ROOT / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_TARGET_MAPPING = DATA_ROOT / "model_data/pvrig_target_domain_mapping_v1.csv"
DEFAULT_RECONCILIATION = DATA_ROOT / "structures/PVRIG_numbering_reconciliation.csv"
DEFAULT_HOTSPOT = DATA_ROOT / "structures/PVRIG_hotspot_set_v1.csv"
DEFAULT_PDB_8X6B = DATA_ROOT / "structures/8X6B.pdb"
DEFAULT_PDB_9E6Y = DATA_ROOT / "structures/9E6Y.pdb"
DEFAULT_INTERFACE_8X6B = DATA_ROOT / "structures/PVRIG_interface_residues_8X6B.csv"
DEFAULT_INTERFACE_9E6Y = DATA_ROOT / "structures/PVRIG_interface_residues_9E6Y.csv"
DEFAULT_SOURCE_CHECKPOINT = EXP_DIR / "checkpoints/phase2_v2_3_strict_seed67_best_checkpoint.pt"
DEFAULT_CONFIG = EXP_DIR / "configs/phase2_v3_p1_formal.json"
DEFAULT_PREREGISTRATION = EXP_DIR / "audits/phase2_v3_p1_preregistration.json"
DEFAULT_TEST_SPEC = EXP_DIR / "audits/phase2_v3_p1_test_spec.json"
DEFAULT_OUT = EXP_DIR / "runs/phase2_v3_p1_formal"
DEFAULT_GENERIC_REPLAY = EXP_DIR / "prepared/phase2_v3_p1_generic_replay/generic_replay_train256_v1.csv"

CLAIM_BOUNDARY = "pvrig_docking_geometry_surrogate_not_binding_or_experimental_blocking_truth"
SCHEMA_VERSION = "phase2_v3_p1_formal_training_v1"
GEOMETRY_FIELDS = (
    "median_hotspot_overlap_8x6b",
    "median_hotspot_overlap_9e6y",
    "median_total_occlusion_8x6b",
    "median_total_occlusion_9e6y",
    "median_cdr3_occlusion_8x6b",
    "median_cdr3_occlusion_9e6y",
    "topk_a_or_b_fraction",
    "teacher_relevance_mean",
)
RESIDUE_RE = re.compile(r"^([^:]+):(-?\d+)([A-Za-z]?):([A-Za-z]{3})$")


@dataclass
class FormalTrainConfig:
    # These two files must be physically train/dev-only. Full Teacher500 label
    # files are deliberately not accepted by this trainer.
    teacher_open_csv: str = str(DEFAULT_FORMAL_DATA / "pvrig_teacher_train_dev_v1.csv")
    contact_open_jsonl: str = str(DEFAULT_FORMAL_DATA / "pvrig_contact_train_dev_v1.jsonl")
    formal_blinded_csv: str = str(DEFAULT_FORMAL_DATA / "pvrig_teacher_formal_blinded_v1.csv")
    selection_csv: str = str(DEFAULT_SELECTION)
    cache_manifest: str = str(DEFAULT_PREPARED / "model_inputs/esm2_8m_cache/manifest.csv")
    cdr_mask_csv: str = str(DEFAULT_PREPARED / "model_inputs/vhh_cdr_type_masks.csv")
    target_fasta: str = str(DEFAULT_TARGET)
    target_mapping_csv: str = str(DEFAULT_TARGET_MAPPING)
    hotspot_csv: str = str(DEFAULT_HOTSPOT)
    reconciliation_csv: str = str(DEFAULT_RECONCILIATION)
    pdb_8x6b: str = str(DEFAULT_PDB_8X6B)
    pdb_9e6y: str = str(DEFAULT_PDB_9E6Y)
    interface_8x6b_csv: str = str(DEFAULT_INTERFACE_8X6B)
    interface_9e6y_csv: str = str(DEFAULT_INTERFACE_9E6Y)
    source_checkpoint: str = str(DEFAULT_SOURCE_CHECKPOINT)
    config_json: str = str(DEFAULT_CONFIG)
    preregistration_json: str = str(DEFAULT_PREREGISTRATION)
    test_spec_json: str = str(DEFAULT_TEST_SPEC)
    generic_replay_csv: str = str(DEFAULT_GENERIC_REPLAY)
    generic_replay_cache_manifest: str = str(EXP_DIR / "prepared/esm2_8m_v2_3_cache/manifest.csv")
    generic_replay_cdr_mask_csv: str = str(EXP_DIR / "data_splits/vhh_cdr_type_masks_v2_3.csv")
    generic_replay_size: int = 256
    out_root: str = str(DEFAULT_OUT)
    seeds: tuple[int, ...] = (83, 89, 97)
    epochs: int = 30
    batch_size: int = 32
    replay_batch_size: int = 16
    learning_rate: float = 3e-4
    weight_decay: float = 1e-4
    early_stopping_patience: int = 7
    contact_dim: int = 64
    pooled_dim: int = 48
    hidden_dim: int = 128
    structure_dim: int = 8
    structure_projection_dim: int = 16
    dropout: float = 0.1
    ordinal_weight: float = 1.0
    geometry_weight: float = 0.7
    contact_weight: float = 0.5
    paratope_weight: float = 0.25
    epitope_weight: float = 0.25
    campaign_rank_weight: float = 0.5
    generic_replay_weight: float = 0.3
    ranking_margin: float = 0.2
    gradient_clip: float = 1.0
    use_amp: bool = True
    num_workers: int = 0
    device: str = "cuda"
    expected_total_candidates: int = 500
    expected_train_candidates: int = 350
    expected_dev_candidates: int = 75
    expected_test_candidates: int = 75
    expected_train_parents: int = 28
    expected_dev_parents: int = 6
    expected_test_parents: int = 6
    expected_hotspot_residues: int = 23
    enforce_formal_governance: bool = True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_fasta(path: Path) -> str:
    sequence = "".join(
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(">")
    )
    if not sequence:
        raise ValueError(f"No sequence found in {path}")
    return sequence


def parse_residue_label(label: str) -> tuple[str, int, str, str]:
    match = RESIDUE_RE.fullmatch(label)
    if not match:
        raise ValueError(f"Invalid residue label: {label}")
    return match.group(1), int(match.group(2)), match.group(3), match.group(4).upper()


def pvrig_pdb_to_model_index(reconciliation_csv: Path, target_sequence: str) -> dict[tuple[str, int, str], int]:
    mapping: dict[tuple[str, int, str], int] = {}
    for row in read_csv(reconciliation_csv):
        if row["pdb_id"].upper() != "8X6B" or row["pvrig_chain"] != "B":
            continue
        model_index = int(row["uniprot_position"]) - 39
        if not 0 <= model_index < len(target_sequence):
            continue
        if target_sequence[model_index] != row["pdb_aa"] and "SEQADV" not in row.get("note", ""):
            raise ValueError(f"8X6B/target residue mismatch at target index {model_index}")
        mapping[("B", int(row["pdb_resseq"]), row["pdb_icode"].strip())] = model_index
    if not mapping:
        raise ValueError("No 8X6B PVRIG residues map to the target sequence")
    return mapping


def target_weights(mapping_csv: Path, target_sequence: str, expected_count: int) -> torch.Tensor:
    weights = torch.zeros(len(target_sequence), dtype=torch.float32)
    for row in read_csv(mapping_csv):
        if row["in_model_domain"] != "yes":
            continue
        index = int(row["model_index_0based"])
        if target_sequence[index] != row["aa"]:
            raise ValueError(f"Target mapping mismatch at model index {index}")
        weights[index] = float(row.get("target_weight", "") or 0.0)
    observed = int((weights > 0).sum())
    if expected_count and observed != expected_count:
        raise ValueError(f"Expected {expected_count} weighted PVRIG residues, found {observed}")
    return weights


def hotspot_weights(hotspot_csv: Path, target_sequence: str, expected_count: int) -> torch.Tensor:
    weights = torch.zeros(len(target_sequence), dtype=torch.float32)
    for row in read_csv(hotspot_csv):
        weight = float(row["priority_weight"])
        if weight <= 0:
            continue
        index = int(row["uniprot_position"]) - 39
        if not 0 <= index < len(target_sequence) or target_sequence[index] != row["uniprot_aa"]:
            raise ValueError(f"Frozen hotspot does not map to target sequence: {row['hotspot_id']}")
        weights[index] = max(float(weights[index]), weight)
    observed = int((weights > 0).sum())
    if observed != expected_count:
        raise ValueError(f"Expected {expected_count} frozen hotspot residues, found {observed}")
    return weights


def build_conformer_features(
    pdb_id: str,
    pdb_path: Path,
    interface_csv: Path,
    reconciliation_csv: Path,
    target_sequence: str,
) -> torch.Tensor:
    """Build deterministic resolved/interface/geometry features for one conformer."""
    reconciliation = [row for row in read_csv(reconciliation_csv) if row["pdb_id"].upper() == pdb_id.upper()]
    if not reconciliation:
        raise ValueError(f"No reconciliation rows for {pdb_id}")
    chain = reconciliation[0]["pvrig_chain"]
    model_index = {
        (int(row["pdb_resseq"]), row["pdb_icode"].strip()): int(row["uniprot_position"]) - 39
        for row in reconciliation
        if 0 <= int(row["uniprot_position"]) - 39 < len(target_sequence)
    }
    interface = {
        (int(row["pvrig_resseq"]), row["pvrig_icode"].strip()): float(row["min_heavy_atom_distance_a"])
        for row in read_csv(interface_csv)
        if row["pdb_id"].upper() == pdb_id.upper() and row["pvrig_chain"] == chain
    }
    ca: dict[tuple[int, str], tuple[float, float, float, float]] = {}
    for line in pdb_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM") or line[21].strip() != chain or line[12:16].strip() != "CA":
            continue
        altloc = line[16].strip()
        if altloc not in {"", "A"}:
            continue
        key = (int(line[22:26]), line[26].strip())
        ca.setdefault(key, (float(line[30:38]), float(line[38:46]), float(line[46:54]), float(line[60:66])))
    coordinates = np.asarray([value[:3] for key, value in ca.items() if key in model_index], dtype=np.float32)
    if not len(coordinates):
        raise ValueError(f"No reconciled CA coordinates for {pdb_id}")
    center = coordinates.mean(0)
    scale = float(np.sqrt(np.mean(np.sum((coordinates - center) ** 2, axis=1)))) or 1.0
    features = torch.zeros((len(target_sequence), 8), dtype=torch.float32)
    coordinate_by_index: dict[int, np.ndarray] = {}
    for key, (x, y, z, bfactor) in ca.items():
        index = model_index.get(key)
        if index is None:
            continue
        coordinate = np.asarray((x, y, z), dtype=np.float32)
        coordinate_by_index[index] = coordinate
        distance = interface.get(key)
        features[index, 0] = 1.0
        features[index, 1] = float(distance is not None)
        features[index, 2] = math.exp(-distance / 4.5) if distance is not None else 0.0
        features[index, 3:6] = torch.from_numpy((coordinate - center) / scale)
        features[index, 6] = max(0.0, min(1.5, bfactor / 100.0))
    for index, coordinate in coordinate_by_index.items():
        neighbors = [coordinate_by_index[neighbor] for neighbor in (index - 1, index + 1) if neighbor in coordinate_by_index]
        if neighbors:
            mean_step = float(np.mean([np.linalg.norm(coordinate - neighbor) for neighbor in neighbors]))
            features[index, 7] = min(mean_step / 4.0, 2.0)
    return features


def _sequence(row: dict[str, str]) -> str:
    return (row.get("vhh_sequence") or row.get("sequence") or "").strip().upper()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.strip().upper().encode()).hexdigest()


def _campaign_id(row: dict[str, str]) -> str:
    return "|".join((row.get("parent_id", ""), row.get("target_patch_id", ""), row.get("design_mode", "")))


def validate_selection(rows: list[dict[str, str]], cfg: FormalTrainConfig) -> None:
    required = {
        "candidate_id", "vhh_sequence", "parent_framework_cluster", "formal_split",
        "generic_binding_prior", "generic_binding_model", "cheap_qc_score", "model_uncertainty",
        "parent_id", "target_patch_id", "design_mode",
    }
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"Selection manifest missing columns: {sorted(missing)}")
    if len(rows) != cfg.expected_total_candidates or len({row["candidate_id"] for row in rows}) != len(rows):
        raise ValueError("Selection candidate count or uniqueness does not match the frozen contract")
    split_counts = Counter(row["formal_split"] for row in rows)
    expected_counts = {
        "train": cfg.expected_train_candidates,
        "dev": cfg.expected_dev_candidates,
        "test": cfg.expected_test_candidates,
    }
    if split_counts != Counter(expected_counts):
        raise ValueError(f"Frozen split counts changed: {dict(split_counts)} != {expected_counts}")
    parent_splits: dict[str, set[str]] = {}
    for row in rows:
        parent_splits.setdefault(row["parent_framework_cluster"], set()).add(row["formal_split"])
        prior = float(row["generic_binding_prior"])
        if not math.isfinite(prior) or not 0.0 <= prior <= 1.0:
            raise ValueError(f"Invalid generic binding prior for {row['candidate_id']}")
        if "meanpool" not in row["generic_binding_model"].lower():
            raise ValueError("V3-P accepts only the frozen mean-pooled generic_binding_prior scalar")
    leaked = {parent: splits for parent, splits in parent_splits.items() if len(splits) != 1}
    if leaked:
        raise ValueError(f"Parent framework cluster leakage: {list(leaked.items())[:3]}")
    observed_parents = Counter()
    for parent, splits in parent_splits.items():
        observed_parents[next(iter(splits))] += 1
    expected_parents = {
        "train": cfg.expected_train_parents,
        "dev": cfg.expected_dev_parents,
        "test": cfg.expected_test_parents,
    }
    if observed_parents != Counter(expected_parents):
        raise ValueError(f"Frozen parent split counts changed: {dict(observed_parents)} != {expected_parents}")


def validate_open_teacher(
    teacher_rows: list[dict[str, str]],
    contact_rows: list[dict[str, Any]],
    selection: dict[str, dict[str, str]],
) -> None:
    open_ids = {candidate_id for candidate_id, row in selection.items() if row["formal_split"] in {"train", "dev"}}
    teacher_ids = {row["candidate_id"] for row in teacher_rows}
    contact_ids = {str(row["candidate_id"]) for row in contact_rows}
    if len(teacher_ids) != len(teacher_rows) or len(contact_ids) != len(contact_rows):
        raise ValueError("Open teacher/contact files contain duplicate candidates")
    if teacher_ids != open_ids or contact_ids != open_ids:
        raise ValueError("Open teacher/contact IDs must exactly equal frozen train+dev IDs")
    for row in teacher_rows:
        candidate_id = row["candidate_id"]
        split = row.get("formal_split") or selection[candidate_id]["formal_split"]
        if split not in {"train", "dev"}:
            raise ValueError("Formal test labels are forbidden in the V3-P trainer")
        if selection[candidate_id]["formal_split"] != split:
            raise ValueError(f"Teacher split mismatch for {candidate_id}")
        if row.get("teacher_completeness", "COMPLETE") != "COMPLETE":
            raise ValueError(f"Incomplete teacher record: {candidate_id}")
        tier = row["provisional_stable_geometry_tier"]
        if tier not in TIER_TO_RELEVANCE:
            raise ValueError(f"Invalid geometry tier for {candidate_id}: {tier}")
        if _sequence(row) and _sequence(row) != _sequence(selection[candidate_id]):
            raise ValueError(f"Teacher/selection sequence mismatch for {candidate_id}")
        for field in GEOMETRY_FIELDS:
            if not math.isfinite(float(row[field])):
                raise ValueError(f"Non-finite {field} for {candidate_id}")
    for row in contact_rows:
        candidate_id = str(row["candidate_id"])
        split = str(row.get("formal_split") or selection[candidate_id]["formal_split"])
        if split not in {"train", "dev"}:
            raise ValueError("Formal test contact-frequency labels are forbidden in the V3-P trainer")


def teacher_contact_matrix(
    record: dict[str, Any],
    vhh_length: int,
    target_length: int,
    pvrig_mapping: dict[tuple[str, int, str], int],
) -> torch.Tensor:
    matrix = torch.zeros((vhh_length, target_length), dtype=torch.float32)
    for pair in record.get("pair_frequencies", []):
        v_chain, v_resseq, _, _ = parse_residue_label(str(pair["vhh_residue"]))
        p_chain, p_resseq, p_icode, _ = parse_residue_label(str(pair["pvrig_residue"]))
        if v_chain != "A":
            raise ValueError(f"Unexpected VHH chain {v_chain}")
        v_index = v_resseq - 1
        p_index = pvrig_mapping.get((p_chain, p_resseq, p_icode))
        if not 0 <= v_index < vhh_length or p_index is None:
            raise ValueError(f"Unmapped teacher contact for {record.get('candidate_id')}: {pair}")
        frequency = float(pair["frequency"])
        if not 0.0 <= frequency <= 1.0:
            raise ValueError("Contact frequencies must be in [0, 1]")
        matrix[v_index, p_index] = max(matrix[v_index, p_index], frequency)
    return matrix


def load_backbone_checkpoint(path: Path) -> tuple[v23.Config, dict[str, torch.Tensor]]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    raw_config = payload.get("cfg") or payload.get("backbone_cfg")
    state = payload.get("model") or payload.get("model_state_dict")
    if not isinstance(raw_config, dict) or not isinstance(state, dict):
        raise ValueError("Unsupported V2.3 source checkpoint")
    return v23.Config(**raw_config), state


class FormalTeacherDataset(Dataset):
    def __init__(
        self,
        split: str,
        rows: list[dict[str, str]],
        selection: dict[str, dict[str, str]],
        contacts: dict[str, dict[str, Any]],
        cache: v23.ESM2Cache,
        cdrs: v23.CDRMaskStore,
        backbone_cfg: v23.Config,
        target_sequence: str,
        pvrig_mapping: dict[tuple[str, int, str], int],
    ) -> None:
        self.rows: list[dict[str, Any]] = []
        self.cache = cache
        self.cdrs = cdrs
        self.backbone_cfg = backbone_cfg
        self.target_sequence = target_sequence
        for teacher in rows:
            candidate_id = teacher["candidate_id"]
            source = selection[candidate_id]
            if source["formal_split"] != split:
                continue
            sequence = _sequence(source)
            if not cache.has(sequence) or not cdrs.has_cdr3(sequence):
                raise ValueError(f"Missing complete VHH model inputs for {candidate_id}")
            contact = teacher_contact_matrix(contacts[candidate_id], len(sequence), len(target_sequence), pvrig_mapping)
            self.rows.append(
                {
                    "candidate_id": candidate_id,
                    "parent_framework_cluster": source["parent_framework_cluster"],
                    "formal_split": split,
                    "sequence_sha256": source.get("sequence_sha256") or sequence_sha256(sequence),
                    "campaign_id": _campaign_id(source),
                    "sequence": sequence,
                    "generic_binding_prior": float(source["generic_binding_prior"]),
                    "tier": teacher["provisional_stable_geometry_tier"],
                    "relevance": TIER_TO_RELEVANCE[teacher["provisional_stable_geometry_tier"]],
                    "geometry": [float(teacher[field]) for field in GEOMETRY_FIELDS],
                    "contact": contact,
                    "paratope": contact.max(1).values,
                    "epitope": contact.max(0).values,
                }
            )
        self.rows.sort(key=lambda row: row["candidate_id"])

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        vhh = self.cache.get(row["sequence"], self.backbone_cfg.max_vhh_len)
        cdr = self.cdrs.get(row["sequence"], self.backbone_cfg.max_vhh_len)[: len(vhh)]
        antigen = self.cache.get(self.target_sequence, self.backbone_cfg.max_antigen_len)
        return {**row, "vhh": vhh, "cdr": cdr, "antigen": antigen}


class InferenceDataset(Dataset):
    def __init__(
        self,
        rows: Iterable[dict[str, str]],
        cache: v23.ESM2Cache,
        cdrs: v23.CDRMaskStore,
        backbone_cfg: v23.Config,
        target_sequence: str,
    ) -> None:
        self.rows = sorted(list(rows), key=lambda row: row["candidate_id"])
        self.cache = cache
        self.cdrs = cdrs
        self.backbone_cfg = backbone_cfg
        self.target_sequence = target_sequence

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        sequence = _sequence(row)
        if not self.cache.has(sequence) or not self.cdrs.has_cdr3(sequence):
            raise ValueError(f"Missing complete model inputs for {row['candidate_id']}")
        return {
            "candidate_id": row["candidate_id"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "formal_split": row["formal_split"],
            "sequence_sha256": row.get("sequence_sha256") or sequence_sha256(sequence),
            "generic_binding_prior": float(row["generic_binding_prior"]),
            "cheap_qc_score": float(row.get("cheap_qc_score", 0.0)),
            "model_uncertainty": float(row.get("model_uncertainty", 0.0)),
            "vhh": self.cache.get(sequence, self.backbone_cfg.max_vhh_len),
            "cdr": self.cdrs.get(sequence, self.backbone_cfg.max_vhh_len),
            "antigen": self.cache.get(self.target_sequence, self.backbone_cfg.max_antigen_len),
        }


class GenericReplayDataset(Dataset):
    """Optional unlabeled replay pairs for frozen-backbone consistency."""

    def __init__(
        self,
        path: Path,
        cache: v23.ESM2Cache,
        cdrs: v23.CDRMaskStore,
        cfg: v23.Config,
        maximum_rows: int,
    ) -> None:
        if path.suffix == ".jsonl":
            source_rows = [row for row in read_jsonl(path) if row.get("split") == "train"]
            source_rows.sort(
                key=lambda row: hashlib.sha256(f"v3p-replay-v1\t{row['complex_id']}".encode()).hexdigest()
            )
            selected: list[dict[str, Any]] = []
            seen_groups: set[str] = set()
            for source in source_rows:
                group = str(source.get("split_group_id") or source["complex_id"])
                vhh_sequence = str(source["vhh_seq"]).strip().upper()
                antigen_sequence = str(source["antigen_seq"]).strip().upper()
                if group in seen_groups or not cache.has(vhh_sequence) or not cache.has(antigen_sequence) or not cdrs.has_cdr3(vhh_sequence):
                    continue
                seen_groups.add(group)
                selected.append(
                    {
                        "sample_id": str(source["complex_id"]),
                        "vhh_sequence": vhh_sequence,
                        "antigen_sequence": antigen_sequence,
                        "contact_pairs": source["positive_pairs"],
                        "source_split": "train",
                        "split_group_id": group,
                    }
                )
                if len(selected) == maximum_rows:
                    break
            self.rows = selected
            if len(self.rows) != maximum_rows:
                raise ValueError(f"Could select only {len(self.rows)}/{maximum_rows} cache-complete train replay rows")
        else:
            self.rows = read_csv(path)
            required = {
                "sample_id", "vhh_sequence", "antigen_sequence", "contact_pairs_json",
                "vhh_paratope_mask", "antigen_epitope_mask",
            }
            if not self.rows or required - set(self.rows[0]):
                raise ValueError(f"Generic replay CSV missing columns: {sorted(required - set(self.rows[0] if self.rows else {}))}")
            if len(self.rows) != maximum_rows:
                raise ValueError(f"Frozen generic replay row count changed: {len(self.rows)} != {maximum_rows}")
        self.cache = cache
        self.cdrs = cdrs
        self.cfg = cfg

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        vhh_sequence = row["vhh_sequence"].strip().upper()
        antigen_sequence = row["antigen_sequence"].strip().upper()
        if not self.cache.has(vhh_sequence) or not self.cache.has(antigen_sequence) or not self.cdrs.has_cdr3(vhh_sequence):
            raise ValueError(f"Missing replay model input for {row['sample_id']}")
        contact = torch.zeros((len(vhh_sequence), len(antigen_sequence)), dtype=torch.float32)
        pairs = row.get("contact_pairs")
        if pairs is None:
            pairs = json.loads(row["contact_pairs_json"])
        for pair in pairs:
            vhh_index, antigen_index = int(pair[0]), int(pair[1])
            if not 0 <= vhh_index < len(vhh_sequence) or not 0 <= antigen_index < len(antigen_sequence):
                raise ValueError(f"Replay contact index out of range for {row['sample_id']}")
            contact[vhh_index, antigen_index] = 1.0
        paratope = contact.max(1).values
        epitope = contact.max(0).values
        if "vhh_paratope_mask" in row:
            paratope = v23.mask_from_string(row["vhh_paratope_mask"], len(vhh_sequence))
            epitope = v23.mask_from_string(row["antigen_epitope_mask"], len(antigen_sequence))
        return {
            "candidate_id": row["sample_id"],
            "parent_framework_cluster": "GENERIC_REPLAY",
            "formal_split": "replay",
            "sequence_sha256": sequence_sha256(vhh_sequence),
            "generic_binding_prior": 0.5,
            "cheap_qc_score": 0.0,
            "model_uncertainty": 0.0,
            "vhh": self.cache.get(vhh_sequence, self.cfg.max_vhh_len),
            "cdr": self.cdrs.get(vhh_sequence, self.cfg.max_vhh_len),
            "antigen": self.cache.get(antigen_sequence, self.cfg.max_antigen_len),
            "contact": contact,
            "paratope": paratope,
            "epitope": epitope,
        }

    def manifest_rows(self) -> list[dict[str, object]]:
        return [
            {
                "sample_id": row["sample_id"],
                "sequence_sha256": sequence_sha256(str(row["vhh_sequence"])),
                "antigen_sequence_sha256": sequence_sha256(str(row["antigen_sequence"])),
                "source_split": row.get("source_split", "train"),
                "split_group_id": row.get("split_group_id", row["sample_id"]),
            }
            for row in self.rows
        ]


class CampaignBatchSampler:
    """Keep each small parent/patch/mode campaign intact within a minibatch."""

    def __init__(self, dataset: FormalTeacherDataset, batch_size: int, generator: torch.Generator) -> None:
        self.batch_size = batch_size
        self.generator = generator
        groups: dict[str, list[int]] = {}
        for index, row in enumerate(dataset.rows):
            groups.setdefault(row["campaign_id"], []).append(index)
        if any(len(indices) > batch_size for indices in groups.values()):
            raise ValueError("Campaign exceeds batch_size and cannot preserve rank pairs")
        self.groups = [groups[name] for name in sorted(groups)]
        self.row_count = len(dataset)

    def __iter__(self) -> Iterator[list[int]]:
        group_order = torch.randperm(len(self.groups), generator=self.generator).tolist()
        batch: list[int] = []
        for group_index in group_order:
            group = self.groups[group_index]
            local_order = torch.randperm(len(group), generator=self.generator).tolist()
            ordered_group = [group[index] for index in local_order]
            if batch and len(batch) + len(ordered_group) > self.batch_size:
                yield batch
                batch = []
            batch.extend(ordered_group)
        if batch:
            yield batch

    def __len__(self) -> int:
        return math.ceil(self.row_count / self.batch_size)


def _pad_teacher_matrix(batch: list[dict[str, Any]], key: str, rows: int, columns: int | None = None) -> torch.Tensor:
    if columns is None:
        output = torch.zeros((len(batch), rows), dtype=torch.float32)
        for index, row in enumerate(batch):
            length = min(rows, len(row[key]))
            output[index, :length] = row[key][:length]
        return output
    output = torch.zeros((len(batch), rows, columns), dtype=torch.float32)
    for index, row in enumerate(batch):
        value = row[key]
        value_rows = min(rows, value.shape[0])
        value_columns = min(columns, value.shape[1])
        output[index, :value_rows, :value_columns] = value[:value_rows, :value_columns]
    return output


def collate_model_inputs(batch: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "candidate_id": [row["candidate_id"] for row in batch],
        "parent_framework_cluster": [row["parent_framework_cluster"] for row in batch],
        "formal_split": [row["formal_split"] for row in batch],
        "sequence_sha256": [row["sequence_sha256"] for row in batch],
        "vhh": pad_sequence([row["vhh"] for row in batch], batch_first=True),
        "cdr": pad_sequence([row["cdr"][: len(row["vhh"])] for row in batch], batch_first=True, padding_value=v23.PAD_CDR),
        "antigen": pad_sequence([row["antigen"] for row in batch], batch_first=True),
        "generic_binding_prior": torch.tensor([row["generic_binding_prior"] for row in batch], dtype=torch.float32),
        "cheap_qc_score": torch.tensor([row.get("cheap_qc_score", 0.0) for row in batch], dtype=torch.float32),
        "model_uncertainty": torch.tensor([row.get("model_uncertainty", 0.0) for row in batch], dtype=torch.float32),
    }


def collate_teacher(batch: list[dict[str, Any]]) -> dict[str, Any]:
    output = collate_model_inputs(batch)
    max_vhh = output["vhh"].shape[1]
    max_antigen = output["antigen"].shape[1]
    campaigns = {name: index for index, name in enumerate(sorted({row["campaign_id"] for row in batch}))}
    output.update(
        {
            "tier": [row["tier"] for row in batch],
            "relevance": torch.tensor([row["relevance"] for row in batch], dtype=torch.long),
            "geometry": torch.tensor([row["geometry"] for row in batch], dtype=torch.float32),
            "contact": _pad_teacher_matrix(batch, "contact", max_vhh, max_antigen),
            "paratope": _pad_teacher_matrix(batch, "paratope", max_vhh),
            "epitope": _pad_teacher_matrix(batch, "epitope", max_antigen),
            "campaign_codes": torch.tensor([campaigns[row["campaign_id"]] for row in batch], dtype=torch.long),
        }
    )
    return output


def collate_replay(batch: list[dict[str, Any]]) -> dict[str, Any]:
    output = collate_model_inputs(batch)
    max_vhh = output["vhh"].shape[1]
    max_antigen = output["antigen"].shape[1]
    output.update(
        {
            "contact": _pad_teacher_matrix(batch, "contact", max_vhh, max_antigen),
            "paratope": _pad_teacher_matrix(batch, "paratope", max_vhh),
            "epitope": _pad_teacher_matrix(batch, "epitope", max_antigen),
        }
    )
    return output


def rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks


def spearman(actual: Sequence[float], predicted: Sequence[float]) -> float:
    if len(actual) < 2:
        return 0.0
    x = rankdata(np.asarray(actual, dtype=np.float64))
    y = rankdata(np.asarray(predicted, dtype=np.float64))
    if np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def ndcg(actual: Sequence[int], predicted: Sequence[float]) -> float:
    if not actual:
        return 0.0
    y = np.asarray(actual, dtype=np.float64)
    score = np.asarray(predicted, dtype=np.float64)
    order = np.argsort(-score, kind="mergesort")
    ideal = np.argsort(-y, kind="mergesort")
    discounts = np.log2(np.arange(2, len(y) + 2))
    dcg = float(np.sum((np.power(2.0, y[order]) - 1.0) / discounts))
    idcg = float(np.sum((np.power(2.0, y[ideal]) - 1.0) / discounts))
    return dcg / idcg if idcg > 0 else 0.0


def g1_g2_recall_at_top_fraction(
    actual: Sequence[int], predicted: Sequence[float], fraction: float = 0.2
) -> float:
    positives = {index for index, relevance in enumerate(actual) if relevance >= TIER_TO_RELEVANCE["G2"]}
    if not positives:
        return 0.0
    count = max(1, math.ceil(len(actual) * fraction))
    ranked = np.argsort(-np.asarray(predicted, dtype=np.float64), kind="mergesort")[:count]
    return len(positives & set(int(value) for value in ranked)) / len(positives)


def compute_teacher_loss(
    outputs: dict[str, torch.Tensor],
    batch: dict[str, Any],
    geometry_mean: torch.Tensor,
    geometry_std: torch.Tensor,
    cfg: FormalTrainConfig,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    device = outputs["geometry"].device
    relevance = batch["relevance"].to(device)
    geometry = batch["geometry"].to(device)
    ordinal = ordinal_cumulative_loss(outputs["cumulative_logits"], relevance)
    regression = nn.functional.smooth_l1_loss(outputs["geometry"], (geometry - geometry_mean) / geometry_std)
    auxiliaries = teacher_auxiliary_losses(
        outputs,
        batch["contact"].to(device),
        batch["paratope"].to(device),
        batch["epitope"].to(device),
    )
    rank = within_campaign_rank_loss(
        outputs["predicted_relevance"],
        relevance,
        batch["campaign_codes"].to(device),
        cfg.ranking_margin,
    )
    total = (
        cfg.ordinal_weight * ordinal
        + cfg.geometry_weight * regression
        + cfg.contact_weight * auxiliaries["contact"]
        + cfg.paratope_weight * auxiliaries["paratope"]
        + cfg.epitope_weight * auxiliaries["epitope"]
        + cfg.campaign_rank_weight * rank
    )
    return total, {"ordinal": ordinal, "geometry": regression, **auxiliaries, "campaign_rank": rank}


def _model_forward(
    model: PVRIGV3P1Model,
    batch: dict[str, Any],
    device: torch.device,
    zero_hotspots: bool = False,
    control_type: str = "full",
    control_seed: int = 0,
) -> dict[str, torch.Tensor]:
    hotspots = torch.zeros(batch["antigen"].shape[1], device=device) if zero_hotspots else None
    structure = (
        torch.zeros((batch["antigen"].shape[1], model.config.structure_dim), device=device)
        if zero_hotspots else None
    )
    return model(
        batch["vhh"].to(device),
        batch["cdr"].to(device),
        batch["antigen"].to(device),
        batch["generic_binding_prior"].to(device),
        hotspot_weights=hotspots,
        structure_8x6b=structure,
        structure_9e6y=structure,
        control_type=control_type,
        control_seed=control_seed,
    )


@torch.inference_mode()
def evaluate_dev(
    model: PVRIGV3P1Model,
    loader: DataLoader,
    device: torch.device,
    geometry_mean: torch.Tensor,
    geometry_std: torch.Tensor,
    cfg: FormalTrainConfig,
) -> dict[str, float]:
    model.eval()
    losses: list[float] = []
    actual_relevance: list[int] = []
    predicted_relevance: list[float] = []
    actual_geometry: list[list[float]] = []
    predicted_geometry: list[list[float]] = []
    for batch in loader:
        with torch.amp.autocast(device_type=device.type, enabled=cfg.use_amp and device.type == "cuda"):
            outputs = _model_forward(model, batch, device)
            loss, _ = compute_teacher_loss(outputs, batch, geometry_mean, geometry_std, cfg)
        losses.append(float(loss.cpu()))
        predictions = outputs["predicted_relevance"].float().cpu().tolist()
        geometry = (outputs["geometry"].float().cpu() * geometry_std.cpu()) + geometry_mean.cpu()
        actual_relevance.extend(batch["relevance"].tolist())
        predicted_relevance.extend(predictions)
        actual_geometry.extend(batch["geometry"].tolist())
        predicted_geometry.extend(geometry.tolist())
    actual_array = np.asarray(actual_geometry, dtype=np.float64)
    predicted_array = np.asarray(predicted_geometry, dtype=np.float64)
    relevance_spearman = spearman(actual_relevance, predicted_relevance)
    teacher_relevance_index = GEOMETRY_FIELDS.index("teacher_relevance_mean")
    teacher_relevance_mean_spearman = spearman(
        actual_array[:, teacher_relevance_index], predicted_array[:, teacher_relevance_index]
    )
    relevance_ndcg = ndcg(actual_relevance, predicted_relevance)
    recall_at_20 = g1_g2_recall_at_top_fraction(actual_relevance, predicted_relevance)
    metrics = {
        "loss": statistics.mean(losses) if losses else float("inf"),
        "ndcg": relevance_ndcg,
        "g1_g2_recall_at_top_20_percent": recall_at_20,
        "spearman": relevance_spearman,
        "teacher_relevance_mean_spearman": teacher_relevance_mean_spearman,
        "normalized_selection_composite": statistics.mean(
            (relevance_ndcg, recall_at_20, (teacher_relevance_mean_spearman + 1.0) / 2.0)
        ),
        "ordinal_mae": float(np.mean(np.abs(np.asarray(actual_relevance) - np.asarray(predicted_relevance)))),
    }
    for index, field in enumerate(GEOMETRY_FIELDS):
        metrics[f"{field}_mae"] = float(np.mean(np.abs(actual_array[:, index] - predicted_array[:, index])))
        metrics[f"{field}_spearman"] = spearman(actual_array[:, index], predicted_array[:, index])
    return metrics


@torch.inference_mode()
def predict_label_free(
    model: PVRIGV3P1Model,
    loader: DataLoader,
    device: torch.device,
    geometry_mean: torch.Tensor,
    geometry_std: torch.Tensor,
    control_type: str = "full",
    control_seed: int = 0,
) -> list[dict[str, object]]:
    model.eval()
    rows: list[dict[str, object]] = []
    for batch in loader:
        outputs = _model_forward(model, batch, device, control_type=control_type, control_seed=control_seed)
        tier_probabilities = outputs["tier_probabilities"].float().cpu()
        relevance = outputs["predicted_relevance"].float().cpu()
        geometry = outputs["geometry"].float().cpu() * geometry_std.cpu() + geometry_mean.cpu()
        for index, candidate_id in enumerate(batch["candidate_id"]):
            row: dict[str, object] = {
                "candidate_id": candidate_id,
                "formal_split": batch["formal_split"][index],
                "sequence_sha256": batch["sequence_sha256"][index],
                "parent_framework_cluster": batch["parent_framework_cluster"][index],
                "predicted_relevance": float(relevance[index]),
                "generic_binding_prior": float(batch["generic_binding_prior"][index]),
            }
            row.update({f"predicted_{tier}_probability": float(tier_probabilities[index, pos]) for pos, tier in enumerate(TIER_NAMES)})
            row.update({f"predicted_{field}": float(geometry[index, pos]) for pos, field in enumerate(GEOMETRY_FIELDS)})
            rows.append(row)
    return rows


@torch.inference_mode()
def build_label_free_baseline_registry(
    model: PVRIGV3P1Model,
    loader: DataLoader,
    device: torch.device,
) -> list[dict[str, object]]:
    model.eval()
    rows: list[dict[str, object]] = []
    hotspot = model.default_hotspot_weights.to(device).gt(0).view(1, 1, -1)
    for batch in loader:
        outputs = _model_forward(model, batch, device)
        valid = outputs["valid_contact_mask"]
        local_hotspot = hotspot[:, :, : valid.shape[2]] & valid
        probabilities = torch.sigmoid(outputs["base_contact_logits"])
        hotspot_mass = (probabilities * local_hotspot).sum((1, 2)) / local_hotspot.float().sum((1, 2)).clamp_min(1.0)
        for index, candidate_id in enumerate(batch["candidate_id"]):
            prior = float(batch["generic_binding_prior"][index])
            uncertainty = float(batch["model_uncertainty"][index])
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "sequence_sha256": batch["sequence_sha256"][index],
                    "formal_split": batch["formal_split"][index],
                    "parent_framework_cluster": batch["parent_framework_cluster"][index],
                    "baseline_generic_binding_prior": prior,
                    "baseline_cheap_qc_score": float(batch["cheap_qc_score"][index]),
                    "baseline_uncertainty_penalized": prior - uncertainty,
                    "baseline_hotspot_contact_mass": float(hotspot_mass[index].cpu()),
                }
            )
    return rows


def binary_average_precision(labels: Sequence[int], scores: Sequence[float]) -> float:
    y = np.asarray(labels, dtype=np.int64)
    s = np.asarray(scores, dtype=np.float64)
    positives = int(y.sum())
    if not positives:
        return 0.0
    order = np.argsort(-s, kind="mergesort")
    ranked = y[order]
    precision = np.cumsum(ranked) / np.arange(1, len(ranked) + 1)
    return float(np.sum(precision * ranked) / positives)


@torch.inference_mode()
def evaluate_generic_replay_retention(
    model: PVRIGV3P1Model,
    loader: DataLoader,
    device: torch.device,
) -> dict[str, float]:
    model.eval()
    labels: dict[str, list[int]] = {"contact": [], "paratope": []}
    adapted: dict[str, list[float]] = {"contact": [], "paratope": []}
    frozen: dict[str, list[float]] = {"contact": [], "paratope": []}
    for batch in loader:
        outputs = _model_forward(model, batch, device, zero_hotspots=True)
        contact_mask = outputs["valid_contact_mask"].cpu()
        vhh_mask = (~outputs["vhh_padding_mask"]).cpu()
        labels["contact"].extend(batch["contact"][contact_mask].round().int().tolist())
        adapted["contact"].extend(torch.sigmoid(outputs["contact_logits"]).cpu()[contact_mask].tolist())
        frozen["contact"].extend(torch.sigmoid(outputs["base_contact_logits"]).cpu()[contact_mask].tolist())
        labels["paratope"].extend(batch["paratope"][vhh_mask].round().int().tolist())
        adapted["paratope"].extend(torch.sigmoid(outputs["paratope_logits"]).cpu()[vhh_mask].tolist())
        frozen["paratope"].extend(torch.sigmoid(outputs["base_paratope_logits"]).cpu()[vhh_mask].tolist())
    metrics: dict[str, float] = {}
    for task in ("contact", "paratope"):
        frozen_auprc = binary_average_precision(labels[task], frozen[task])
        adapted_auprc = binary_average_precision(labels[task], adapted[task])
        metrics[f"frozen_{task}_auprc"] = frozen_auprc
        metrics[f"adapted_{task}_auprc"] = adapted_auprc
        metrics[f"{task}_auprc_retention_fraction"] = adapted_auprc / frozen_auprc if frozen_auprc > 0 else 0.0
    return metrics


def write_csv_atomic(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def save_torch_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def rng_state() -> dict[str, Any]:
    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
    }


def restore_rng_state(state: dict[str, Any]) -> None:
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"])
    if torch.cuda.is_available() and state.get("cuda"):
        torch.cuda.set_rng_state_all(state["cuda"])


def cycle(loader: DataLoader) -> Iterator[dict[str, Any]]:
    while True:
        yield from loader


def resolve_device(requested: str) -> torch.device:
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested for formal V3-P training but unavailable")
    return torch.device(requested)


def referenced_cache_hashes(manifest_path: Path) -> dict[str, str]:
    rows = read_csv(manifest_path)
    paths = sorted({str((manifest_path.parent / row["shard_path"]).resolve()) for row in rows})
    return {path: sha256_file(Path(path)) for path in paths}


def artifact_hashes(cfg: FormalTrainConfig) -> dict[str, Any]:
    paths = {
        "teacher_open_csv": Path(cfg.teacher_open_csv),
        "contact_open_jsonl": Path(cfg.contact_open_jsonl),
        "formal_blinded_csv": Path(cfg.formal_blinded_csv),
        "selection_csv": Path(cfg.selection_csv),
        "cache_manifest": Path(cfg.cache_manifest),
        "cdr_mask_csv": Path(cfg.cdr_mask_csv),
        "target_fasta": Path(cfg.target_fasta),
        "target_mapping_csv": Path(cfg.target_mapping_csv),
        "hotspot_csv": Path(cfg.hotspot_csv),
        "reconciliation_csv": Path(cfg.reconciliation_csv),
        "pdb_8x6b": Path(cfg.pdb_8x6b),
        "pdb_9e6y": Path(cfg.pdb_9e6y),
        "interface_8x6b_csv": Path(cfg.interface_8x6b_csv),
        "interface_9e6y_csv": Path(cfg.interface_9e6y_csv),
        "source_checkpoint": Path(cfg.source_checkpoint),
        "config_json": Path(cfg.config_json),
        "trainer_source": Path(__file__).resolve(),
        "model_source": SCRIPT_DIR / "phase2_v3_p1_model.py",
        "v2_3_backbone_source": SCRIPT_DIR / "train_phase2_v2_3.py",
        "preregistration_json": Path(cfg.preregistration_json),
        "test_spec_json": Path(cfg.test_spec_json),
    }
    if cfg.generic_replay_csv:
        paths["generic_replay_csv"] = Path(cfg.generic_replay_csv)
        if not cfg.generic_replay_cache_manifest or not cfg.generic_replay_cdr_mask_csv:
            raise ValueError("Generic replay requires its own cache manifest and CDR mask CSV")
        paths["generic_replay_cache_manifest"] = Path(cfg.generic_replay_cache_manifest)
        paths["generic_replay_cdr_mask_csv"] = Path(cfg.generic_replay_cdr_mask_csv)
    result = {
        "files": {name: sha256_file(path) for name, path in paths.items()},
        "cache_shards": referenced_cache_hashes(Path(cfg.cache_manifest)),
    }
    if cfg.generic_replay_csv:
        result["generic_replay_cache_shards"] = referenced_cache_hashes(Path(cfg.generic_replay_cache_manifest))
    return result


def validate_governance(cfg: FormalTrainConfig) -> dict[str, Any]:
    prereg_path = Path(cfg.preregistration_json)
    test_spec_path = Path(cfg.test_spec_json)
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    test_spec = json.loads(test_spec_path.read_text(encoding="utf-8"))
    if prereg.get("status") != "FROZEN_BEFORE_FORMAL_TEACHER_LABELS_AND_TEST_UNSEAL":
        raise ValueError("V3-P preregistration is not in the frozen pre-label state")
    if test_spec.get("status") != "FROZEN_BEFORE_FORMAL_TEST_UNSEAL":
        raise ValueError("V3-P test specification is not frozen")
    if tuple(prereg["training"]["seeds"]) != (83, 89, 97):
        raise ValueError("Frozen V3-P seeds changed")
    expected_losses = prereg["architecture"]["losses"]
    observed_losses = {
        "generic_replay": cfg.generic_replay_weight,
        "geometry_regression": cfg.geometry_weight,
        "ordinal_tier": cfg.ordinal_weight,
        "pose_contact_frequency": cfg.contact_weight,
        "within_campaign_rank": cfg.campaign_rank_weight,
    }
    if observed_losses != expected_losses:
        raise ValueError(f"Configured loss weights differ from preregistration: {observed_losses} != {expected_losses}")
    verified: dict[str, dict[str, str]] = {}
    for name, record in prereg["frozen_inputs"].items():
        path = DATA_ROOT / record["path"]
        observed = sha256_file(path)
        if observed != record["sha256"]:
            raise ValueError(f"Frozen preregistration input hash changed: {name}")
        verified[name] = {"path": str(path), "sha256": observed}
    frozen_selection = (DATA_ROOT / prereg["frozen_inputs"]["teacher500_selection_manifest"]["path"]).resolve()
    if Path(cfg.selection_csv).resolve() != frozen_selection:
        raise ValueError("Configured Teacher500 selection is not the preregistered frozen manifest")
    configured_frozen_paths = {
        "hotspot_set": cfg.hotspot_csv,
        "interface_8x6b": cfg.interface_8x6b_csv,
        "interface_9e6y": cfg.interface_9e6y_csv,
        "structure_8x6b": cfg.pdb_8x6b,
        "structure_9e6y": cfg.pdb_9e6y,
    }
    for name, configured_path in configured_frozen_paths.items():
        expected_path = (DATA_ROOT / prereg["frozen_inputs"][name]["path"]).resolve()
        if Path(configured_path).resolve() != expected_path:
            raise ValueError(f"Configured {name} is not the preregistered frozen artifact")
    declared_prereg = (DATA_ROOT / test_spec["preregistration_path"]).resolve()
    if prereg_path.resolve() != declared_prereg:
        raise ValueError("Test specification points to a different preregistration")
    return {
        "status": "PASS_FORMAL_GOVERNANCE_PREFLIGHT",
        "preregistration_sha256": sha256_file(prereg_path),
        "test_spec_sha256": sha256_file(test_spec_path),
        "verified_frozen_inputs": verified,
        "loss_weights": observed_losses,
        "seeds": [83, 89, 97],
    }


def build_datasets(cfg: FormalTrainConfig, backbone_cfg: v23.Config) -> tuple[dict[str, Dataset], dict[str, Any]]:
    selection_rows = read_csv(Path(cfg.selection_csv))
    validate_selection(selection_rows, cfg)
    selection = {row["candidate_id"]: row for row in selection_rows}
    formal_blinded = read_csv(Path(cfg.formal_blinded_csv))
    forbidden_blinded = {"provisional_stable_geometry_tier", "geometry_tier_index", *GEOMETRY_FIELDS}
    if formal_blinded and forbidden_blinded & set(formal_blinded[0]):
        raise ValueError("Formal blinded inference CSV contains forbidden teacher label columns")
    expected_test_ids = {row["candidate_id"] for row in selection_rows if row["formal_split"] == "test"}
    if {row["candidate_id"] for row in formal_blinded} != expected_test_ids:
        raise ValueError("Formal blinded inference IDs do not match the frozen test split")
    for row in formal_blinded:
        source = selection[row["candidate_id"]]
        for field in ("sequence_sha256", "parent_framework_cluster", "formal_split"):
            if row[field] != source[field]:
                raise ValueError(f"Formal blinded identity mismatch for {row['candidate_id']} field={field}")
    teacher_rows = read_csv(Path(cfg.teacher_open_csv))
    contact_rows = read_jsonl(Path(cfg.contact_open_jsonl))
    validate_open_teacher(teacher_rows, contact_rows, selection)
    contacts = {str(row["candidate_id"]): row for row in contact_rows}
    target_sequence = read_fasta(Path(cfg.target_fasta))
    mapping = pvrig_pdb_to_model_index(Path(cfg.reconciliation_csv), target_sequence)
    # Validate the model-domain mapping, then source the actual mask from the
    # preregistered hotspot artifact rather than an unfrozen derived table.
    target_weights(Path(cfg.target_mapping_csv), target_sequence, cfg.expected_hotspot_residues)
    hotspot_values = hotspot_weights(Path(cfg.hotspot_csv), target_sequence, cfg.expected_hotspot_residues)
    structure_8x6b = build_conformer_features(
        "8X6B", Path(cfg.pdb_8x6b), Path(cfg.interface_8x6b_csv), Path(cfg.reconciliation_csv), target_sequence
    )
    structure_9e6y = build_conformer_features(
        "9E6Y", Path(cfg.pdb_9e6y), Path(cfg.interface_9e6y_csv), Path(cfg.reconciliation_csv), target_sequence
    )
    cache = v23.ESM2Cache(Path(cfg.cache_manifest), backbone_cfg.esm_dim)
    cdrs = v23.CDRMaskStore(Path(cfg.cdr_mask_csv))
    datasets: dict[str, Dataset] = {
        split: FormalTeacherDataset(split, teacher_rows, selection, contacts, cache, cdrs, backbone_cfg, target_sequence, mapping)
        for split in ("train", "dev")
    }
    datasets["test"] = InferenceDataset(
        formal_blinded,
        cache,
        cdrs,
        backbone_cfg,
        target_sequence,
    )
    datasets["baseline"] = InferenceDataset(
        [*(row for row in selection_rows if row["formal_split"] == "dev"), *formal_blinded],
        cache,
        cdrs,
        backbone_cfg,
        target_sequence,
    )
    if cfg.generic_replay_csv:
        replay_cache = v23.ESM2Cache(Path(cfg.generic_replay_cache_manifest), backbone_cfg.esm_dim)
        replay_cdrs = v23.CDRMaskStore(Path(cfg.generic_replay_cdr_mask_csv))
        datasets["replay"] = GenericReplayDataset(
            Path(cfg.generic_replay_csv), replay_cache, replay_cdrs, backbone_cfg, cfg.generic_replay_size
        )
    if len(datasets["train"]) != cfg.expected_train_candidates or len(datasets["dev"]) != cfg.expected_dev_candidates:
        raise ValueError("Open teacher datasets do not match frozen train/dev counts")
    if len(datasets["test"]) != cfg.expected_test_candidates:
        raise ValueError("Label-free test inference dataset does not match frozen count")
    return datasets, {
        "hotspot_weights": hotspot_values,
        "structure_8x6b": structure_8x6b,
        "structure_9e6y": structure_9e6y,
        "target_sequence": target_sequence,
    }


def shuffle_teacher_labels(dataset: FormalTeacherDataset, seed: int) -> None:
    """Apply one deterministic split-local permutation to all teacher targets."""
    generator = torch.Generator().manual_seed(seed + 30_000)
    permutation = torch.randperm(len(dataset.rows), generator=generator).tolist()
    target_keys = ("tier", "relevance", "geometry", "contact", "paratope", "epitope")
    sources = [{key: row[key] for key in target_keys} for row in dataset.rows]
    for destination, source_index in zip(dataset.rows, permutation):
        source = sources[source_index]
        destination["tier"] = source["tier"]
        destination["relevance"] = source["relevance"]
        destination["geometry"] = list(source["geometry"])
        contact = torch.zeros_like(destination["contact"])
        source_contact = source["contact"]
        rows = min(contact.shape[0], source_contact.shape[0])
        columns = min(contact.shape[1], source_contact.shape[1])
        contact[:rows, :columns] = source_contact[:rows, :columns]
        destination["contact"] = contact
        destination["paratope"] = contact.max(1).values
        destination["epitope"] = contact.max(0).values


def train_seed(
    cfg: FormalTrainConfig,
    seed: int,
    run_dir: Path,
    resume: bool = False,
    stop_after_epoch: int = 0,
    control_type: str = "full",
) -> dict[str, Any]:
    allowed_controls = {"full", "vhh_only", "hotspot_shuffle", "antigen_ablation", "target_permutation", "label_shuffle"}
    if control_type not in allowed_controls:
        raise ValueError(f"Unsupported formal control: {control_type}")
    governance = (
        validate_governance(cfg)
        if cfg.enforce_formal_governance
        else {"status": "DISABLED_FOR_SYNTHETIC_OR_DEVELOPMENT_FIXTURE"}
    )
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = resolve_device(cfg.device)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.set_float32_matmul_precision("high")

    backbone_cfg, backbone_state = load_backbone_checkpoint(Path(cfg.source_checkpoint))
    datasets, shared = build_datasets(cfg, backbone_cfg)
    if control_type == "label_shuffle":
        # The null must not use real dev labels for checkpoint selection.
        shuffle_teacher_labels(datasets["train"], seed)
        shuffle_teacher_labels(datasets["dev"], seed + 1_000_000)
    train_geometry = torch.tensor([row["geometry"] for row in datasets["train"].rows], dtype=torch.float32)
    geometry_mean = train_geometry.mean(0).to(device)
    geometry_std = train_geometry.std(0, unbiased=False).clamp_min(1e-6).to(device)

    generator = torch.Generator().manual_seed(seed + 10_000)
    replay_generator = torch.Generator().manual_seed(seed + 20_000)
    campaign_sampler = CampaignBatchSampler(datasets["train"], cfg.batch_size, generator)
    loaders = {
        "train": DataLoader(
            datasets["train"], batch_sampler=campaign_sampler,
            num_workers=cfg.num_workers, collate_fn=collate_teacher,
        ),
        "dev": DataLoader(datasets["dev"], batch_size=cfg.batch_size, shuffle=False, collate_fn=collate_teacher),
        "test": DataLoader(datasets["test"], batch_size=cfg.batch_size, shuffle=False, collate_fn=collate_model_inputs),
        "baseline": DataLoader(datasets["baseline"], batch_size=cfg.batch_size, shuffle=False, collate_fn=collate_model_inputs),
    }
    if "replay" in datasets:
        loaders["replay"] = DataLoader(
            datasets["replay"], batch_size=cfg.replay_batch_size, shuffle=True,
            generator=replay_generator, collate_fn=collate_replay,
        )

    backbone = v23.CrossContactNetV23(backbone_cfg)
    backbone.load_state_dict(backbone_state)
    model_cfg = PVRIGModelConfig(
        contact_dim=cfg.contact_dim,
        pooled_dim=cfg.pooled_dim,
        hidden_dim=cfg.hidden_dim,
        geometry_dim=len(GEOMETRY_FIELDS),
        structure_dim=cfg.structure_dim,
        structure_projection_dim=cfg.structure_projection_dim,
        dropout=cfg.dropout,
    )
    model = PVRIGV3P1Model(
        backbone,
        model_cfg,
        shared["hotspot_weights"],
        shared["structure_8x6b"],
        shared["structure_9e6y"],
    ).to(device)
    assert_backbone_frozen(model)
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=cfg.learning_rate,
        weight_decay=cfg.weight_decay,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=cfg.use_amp and device.type == "cuda")
    hashes = artifact_hashes(cfg)
    config_fingerprint = sha256_json({"config": asdict(cfg), "control_type": control_type})
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(run_dir / "config_resolved.json", asdict(cfg))
    governance_path = run_dir / "formal_governance_preflight.json"
    write_json_atomic(governance_path, governance)
    if "replay" in datasets:
        write_csv_atomic(run_dir / "generic_replay_manifest.csv", datasets["replay"].manifest_rows())
    baseline_path = run_dir / "baseline_registry.csv"
    write_csv_atomic(baseline_path, build_label_free_baseline_registry(model, loaders["baseline"], device))

    history: list[dict[str, Any]] = []
    best_metric = -float("inf")
    best_loss = float("inf")
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    stale = 0
    start_epoch = 1
    last_path = run_dir / "last_checkpoint.pt"
    if resume:
        if not last_path.exists():
            raise FileNotFoundError(f"Resume checkpoint does not exist: {last_path}")
        checkpoint = torch.load(last_path, map_location="cpu", weights_only=False)
        if checkpoint["seed"] != seed or checkpoint["artifact_hashes"] != hashes or checkpoint["config_fingerprint"] != config_fingerprint:
            raise ValueError("Resume checkpoint seed, artifacts, or configuration changed")
        model.load_trainable_state_dict(checkpoint["head_state"])
        optimizer.load_state_dict(checkpoint["optimizer_state"])
        scaler.load_state_dict(checkpoint["scaler_state"])
        history = checkpoint["history"]
        best_metric = float(checkpoint["best_metric"])
        best_loss = float(checkpoint["best_loss"])
        best_epoch = int(checkpoint["best_epoch"])
        best_state = checkpoint["best_head_state"]
        stale = int(checkpoint["stale"])
        start_epoch = int(checkpoint["epoch"]) + 1
        generator.set_state(checkpoint["train_generator_state"])
        replay_generator.set_state(checkpoint["replay_generator_state"])
        restore_rng_state(checkpoint["rng_state"])

    status = "PASS_FORMAL_TRAINING_COMPLETE"
    for epoch in range(start_epoch, cfg.epochs + 1):
        model.train()
        # Restart at each epoch so the saved generator state is sufficient for
        # bitwise-equivalent epoch-boundary resume, including replay batches.
        replay_iterator = cycle(loaders["replay"]) if "replay" in loaders else None
        batch_losses: list[float] = []
        component_values: dict[str, list[float]] = {
            name: [] for name in ("ordinal", "geometry", "contact", "paratope", "epitope", "campaign_rank", "generic_replay")
        }
        for batch in loaders["train"]:
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, enabled=cfg.use_amp and device.type == "cuda"):
                outputs = _model_forward(model, batch, device)
                loss, components = compute_teacher_loss(outputs, batch, geometry_mean, geometry_std, cfg)
                replay_loss = loss.sum() * 0.0
                if replay_iterator is not None:
                    replay_outputs = _model_forward(model, next(replay_iterator), device, zero_hotspots=True)
                    replay_loss = generic_replay_consistency_loss(replay_outputs)
                    loss = loss + cfg.generic_replay_weight * replay_loss
            if not torch.isfinite(loss):
                raise RuntimeError(f"Non-finite V3-P loss at seed={seed} epoch={epoch}")
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_((parameter for parameter in model.parameters() if parameter.requires_grad), cfg.gradient_clip)
            scaler.step(optimizer)
            scaler.update()
            batch_losses.append(float(loss.detach().cpu()))
            for name, value in components.items():
                component_values[name].append(float(value.detach().cpu()))
            component_values["generic_replay"].append(float(replay_loss.detach().cpu()))

        dev_metrics = evaluate_dev(model, loaders["dev"], device, geometry_mean, geometry_std, cfg)
        record = {
            "epoch": epoch,
            "train_loss": statistics.mean(batch_losses),
            **{f"train_{name}_loss": statistics.mean(values) for name, values in component_values.items()},
            "dev": dev_metrics,
        }
        history.append(record)
        print(json.dumps({"seed": seed, **record}, sort_keys=True), flush=True)
        selection_metric = dev_metrics["normalized_selection_composite"]
        improved = selection_metric > best_metric + 1e-12 or (
            abs(selection_metric - best_metric) <= 1e-12 and dev_metrics["loss"] < best_loss - 1e-12
        )
        if improved:
            best_metric = selection_metric
            best_loss = dev_metrics["loss"]
            best_epoch = epoch
            best_state = model.trainable_state_dict()
            stale = 0
        else:
            stale += 1

        save_torch_atomic(
            last_path,
            {
                "schema_version": SCHEMA_VERSION,
                "seed": seed,
                "control_type": control_type,
                "epoch": epoch,
                "head_state": model.trainable_state_dict(),
                "optimizer_state": optimizer.state_dict(),
                "scaler_state": scaler.state_dict(),
                "best_head_state": best_state,
                "best_metric": best_metric,
                "best_loss": best_loss,
                "best_epoch": best_epoch,
                "stale": stale,
                "history": history,
                "rng_state": rng_state(),
                "train_generator_state": generator.get_state(),
                "replay_generator_state": replay_generator.get_state(),
                "artifact_hashes": hashes,
                "config_fingerprint": config_fingerprint,
            },
        )
        if stop_after_epoch and epoch >= stop_after_epoch:
            status = "PAUSED_RESUMABLE"
            break
        if stale >= cfg.early_stopping_patience:
            break

    if status == "PAUSED_RESUMABLE":
        summary = {
            "schema_version": SCHEMA_VERSION,
            "seed": seed,
            "status": status,
            "control_type": control_type,
            "formal_governance_preflight_sha256": sha256_file(governance_path),
            "last_checkpoint": str(last_path),
            "completed_epoch": history[-1]["epoch"],
            "claim_boundary": CLAIM_BOUNDARY,
        }
        write_json_atomic(run_dir / "summary.json", summary)
        return summary
    if best_state is None:
        raise RuntimeError("No dev-selected V3-P checkpoint was produced")

    model.load_trainable_state_dict(best_state)
    best_checkpoint = run_dir / "best_checkpoint.pt"
    save_torch_atomic(
        best_checkpoint,
        {
            "schema_version": SCHEMA_VERSION,
            "seed": seed,
            "head_state": best_state,
            "backbone_cfg": asdict(backbone_cfg),
            "source_backbone_checkpoint": cfg.source_checkpoint,
            "source_backbone_checkpoint_sha256": hashes["files"]["source_checkpoint"],
            "config_fingerprint": config_fingerprint,
            "preregistration_sha256": hashes["files"]["preregistration_json"],
            "test_spec_sha256": hashes["files"]["test_spec_json"],
            "artifact_hashes": hashes,
            "formal_governance_preflight": governance,
            "formal_governance_preflight_sha256": sha256_file(governance_path),
            "geometry_fields": list(GEOMETRY_FIELDS),
            "geometry_mean": geometry_mean.cpu(),
            "geometry_std": geometry_std.cpu(),
            "model_metadata": checkpoint_model_metadata(model),
            "best_epoch": best_epoch,
            "dev_selection_metric": "normalized_mean(ndcg,g1_g2_recall_at_top_20_percent,(teacher_relevance_mean_spearman+1)/2)",
            "best_dev_normalized_composite": best_metric,
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    test_predictions = predict_label_free(model, loaders["test"], device, geometry_mean, geometry_std)
    if any(row["formal_split"] != "test" for row in test_predictions):
        raise AssertionError("Non-test rows leaked into evaluator-facing predictions")
    prediction_path = run_dir / "test_predictions.csv"
    write_csv_atomic(prediction_path, test_predictions)
    dev_prediction_path = run_dir / "dev_predictions.csv"
    write_csv_atomic(
        dev_prediction_path,
        predict_label_free(model, loaders["dev"], device, geometry_mean, geometry_std),
    )
    if control_type == "full":
        inference_controls = ("vhh_only", "hotspot_shuffle", "antigen_ablation", "target_permutation")
    elif control_type == "label_shuffle":
        inference_controls = ("label_shuffle",)
    else:
        inference_controls = (control_type,)
    control_rows: list[dict[str, object]] = []
    for inference_control in inference_controls:
        forward_control = "full" if inference_control == "label_shuffle" else inference_control
        rows = predict_label_free(
            model,
            loaders["test"],
            device,
            geometry_mean,
            geometry_std,
            control_type=forward_control,
            control_seed=seed,
        )
        control_rows.extend(
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "formal_split": row["formal_split"],
                "parent_framework_cluster": row["parent_framework_cluster"],
                "seed": seed,
                "control_type": inference_control,
                "predicted_relevance": row["predicted_relevance"],
            }
            for row in rows
        )
    control_path = run_dir / "control_predictions.csv"
    write_csv_atomic(control_path, control_rows)
    final_dev = evaluate_dev(model, loaders["dev"], device, geometry_mean, geometry_std, cfg)
    if "replay" in loaders:
        retention_metrics: dict[str, Any] = evaluate_generic_replay_retention(
            model,
            DataLoader(datasets["replay"], batch_size=cfg.replay_batch_size, shuffle=False, collate_fn=collate_replay),
            device,
        )
        retention_metrics["status"] = "PASS_GENERIC_REPLAY_RETENTION_MEASURED"
    else:
        retention_metrics = {
            "status": "NOT_CONFIGURED",
            "contact_auprc_retention_fraction": None,
            "paratope_auprc_retention_fraction": None,
        }
    retention_path = run_dir / "generic_replay_retention.json"
    write_json_atomic(
        retention_path,
        {"schema_version": "phase2_v3_p1_generic_replay_retention_v1", "per_seed": {str(seed): retention_metrics}},
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "status": status,
        "control_type": control_type,
        "best_epoch": best_epoch,
        "best_dev_metrics": final_dev,
        "dev_selection_policy": "maximum_dev_normalized_composite_then_minimum_dev_loss",
        "test_predictions_path": str(prediction_path),
        "test_predictions_sha256": sha256_file(prediction_path),
        "dev_predictions_path": str(dev_prediction_path),
        "dev_predictions_sha256": sha256_file(dev_prediction_path),
        "control_predictions_path": str(control_path),
        "control_predictions_sha256": sha256_file(control_path),
        "control_prediction_types": list(inference_controls),
        "test_prediction_columns_are_label_free": True,
        "best_checkpoint": str(best_checkpoint),
        "best_checkpoint_sha256": sha256_file(best_checkpoint),
        "config_fingerprint": config_fingerprint,
        "preregistration_sha256": hashes["files"]["preregistration_json"],
        "test_spec_sha256": hashes["files"]["test_spec_json"],
        "formal_governance_preflight": governance,
        "formal_governance_preflight_path": str(governance_path),
        "formal_governance_preflight_sha256": sha256_file(governance_path),
        "baseline_registry_path": str(baseline_path),
        "baseline_registry_sha256": sha256_file(baseline_path),
        "frozen_backbone": True,
        "generic_binding_prior_policy": "frozen_meanpool_v3_full_scalar_only",
        "forbidden_pair_heads": ["v2_3_pair_head", "v3_g2_failed_pair_head"],
        "generic_replay_enabled": "replay" in datasets,
        "generic_replay_retention_path": str(retention_path),
        "generic_replay_retention_sha256": sha256_file(retention_path),
        "generic_replay_retention": retention_metrics,
        "dataset_sizes": {name: len(dataset) for name, dataset in datasets.items()},
        "artifact_hashes": hashes,
        "history": history,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json_atomic(run_dir / "summary.json", summary)
    return summary


def run_training(
    cfg: FormalTrainConfig,
    run_root: Path | None = None,
    resume: bool = False,
    stop_after_epoch: int = 0,
    control_type: str = "full",
) -> dict[str, Any]:
    if cfg.enforce_formal_governance and tuple(cfg.seeds) != (83, 89, 97):
        raise ValueError("Formal V3-P run requires exact preregistered seeds 83,89,97")
    if run_root is None:
        run_id = time.strftime("phase2_v3_p1_formal_%Y%m%d_%H%M%S")
        run_root = Path(cfg.out_root) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    seed_summaries = [
        train_seed(
            cfg,
            seed,
            run_root / f"seed_{seed}",
            resume=resume,
            stop_after_epoch=stop_after_epoch,
            control_type=control_type,
        )
        for seed in cfg.seeds
    ]
    status = "PAUSED_RESUMABLE" if any(summary["status"] == "PAUSED_RESUMABLE" for summary in seed_summaries) else "PASS_FORMAL_MULTISEED_COMPLETE"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run_root": str(run_root),
        "seeds": list(cfg.seeds),
        "control_type": control_type,
        "seed_summaries": seed_summaries,
        "test_label_access": "NONE_TRAINER_USES_LABEL_FREE_SELECTION_ROWS_FOR_TEST_INFERENCE",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    retention = {
        str(seed_summary["seed"]): seed_summary.get(
            "generic_replay_retention",
            {
                "status": "NOT_AVAILABLE_FOR_PAUSED_RUN",
                "contact_auprc_retention_fraction": None,
                "paratope_auprc_retention_fraction": None,
            },
        )
        for seed_summary in seed_summaries
    }
    write_json_atomic(
        run_root / "generic_replay_retention.json",
        {"schema_version": "phase2_v3_p1_generic_replay_retention_v1", "per_seed": retention},
    )
    write_json_atomic(run_root / "training_summary.json", summary)
    return summary


def load_config(path: Path) -> FormalTrainConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    allowed = {field.name for field in fields(FormalTrainConfig)}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"Unknown formal V3-P config fields: {sorted(unknown)}")
    if "seeds" in payload:
        payload["seeds"] = tuple(int(value) for value in payload["seeds"])
    return FormalTrainConfig(**payload)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--control",
        choices=("full", "vhh_only", "hotspot_shuffle", "antigen_ablation", "target_permutation", "label_shuffle"),
        default="full",
    )
    parser.add_argument("--stop-after-epoch", type=int, default=0, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    summary = run_training(
        cfg,
        args.run_dir,
        resume=args.resume,
        stop_after_epoch=args.stop_after_epoch,
        control_type=args.control,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
