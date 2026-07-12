#!/usr/bin/env python3
"""Train a single-framework V3-P1 sequence-to-geometry pipeline smoke.

The generic V2.3/V3-G backbone remains frozen. Only a small PVRIG contact
adapter plus ordinal and geometry heads are trained. This run validates model
plumbing; it cannot support an unseen-parent or experimental blocking claim.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

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
import train_phase2_v2_3 as v23

DEFAULT_TEACHER = EXP_DIR / "prepared/pvrig_teacher_pilot96/candidate_summary.csv"
DEFAULT_CONTACTS = EXP_DIR / "prepared/pvrig_teacher_pilot96/pose_contact_frequency.jsonl"
DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_pilot96/pvrig_teacher_pilot96_manifest.tsv"
DEFAULT_CACHE = EXP_DIR / "prepared/pvrig_teacher_pilot96/model_inputs/esm2_8m_cache/manifest.csv"
DEFAULT_CDR = EXP_DIR / "prepared/pvrig_teacher_pilot96/model_inputs/vhh_cdr_type_masks.csv"
DEFAULT_TARGET = DATA_ROOT / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_TARGET_MAPPING = DATA_ROOT / "model_data/pvrig_target_domain_mapping_v1.csv"
DEFAULT_RECONCILIATION = DATA_ROOT / "structures/PVRIG_numbering_reconciliation.csv"
DEFAULT_CHECKPOINT = EXP_DIR / "checkpoints/phase2_v2_3_strict_seed67_best_checkpoint.pt"
DEFAULT_OUT = EXP_DIR / "runs/phase2_v3_p1_pilot_smoke"

CLAIM_BOUNDARY = "single_framework_pipeline_smoke_not_formal_pvrig_binding_or_blocking_truth"
TIER_TO_RELEVANCE = {"G1": 4, "G2": 3, "G3": 2, "G4": 1, "G5": 0}
RELEVANCE_TO_TIER = {value: key for key, value in TIER_TO_RELEVANCE.items()}
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
class SmokeConfig:
    teacher_csv: str = str(DEFAULT_TEACHER)
    contact_jsonl: str = str(DEFAULT_CONTACTS)
    selection_tsv: str = str(DEFAULT_SELECTION)
    cache_manifest: str = str(DEFAULT_CACHE)
    cdr_mask_csv: str = str(DEFAULT_CDR)
    target_fasta: str = str(DEFAULT_TARGET)
    target_mapping_csv: str = str(DEFAULT_TARGET_MAPPING)
    reconciliation_csv: str = str(DEFAULT_RECONCILIATION)
    source_checkpoint: str = str(DEFAULT_CHECKPOINT)
    out_root: str = str(DEFAULT_OUT)
    seed: int = 83
    epochs: int = 20
    batch_size: int = 8
    learning_rate: float = 5e-4
    weight_decay: float = 1e-4
    contact_dim: int = 48
    hidden_dim: int = 64
    ordinal_weight: float = 1.0
    regression_weight: float = 0.5
    contact_weight: float = 0.5
    monotonic_weight: float = 0.1
    negative_contact_weight: float = 0.25
    use_amp: bool = True
    max_train_batches: int = 0
    max_eval_batches: int = 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_fasta(path: Path) -> str:
    return "".join(
        line.strip().upper()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(">")
    )


def stable_split(group: str) -> str:
    value = int(hashlib.sha256(f"v3p1-pilot-split\t{group}".encode()).hexdigest()[:8], 16)
    return "dev" if value % 5 == 0 else "train"


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
        uniprot_position = int(row["uniprot_position"])
        model_index = uniprot_position - 39
        if not 0 <= model_index < len(target_sequence):
            continue
        if target_sequence[model_index] != row["pdb_aa"]:
            raise ValueError(f"8X6B/target residue mismatch at UniProt {uniprot_position}")
        mapping[("B", int(row["pdb_resseq"]), row["pdb_icode"].strip())] = model_index
    if not mapping:
        raise ValueError("No 8X6B PVRIG residues mapped into the model target")
    return mapping


def target_weights(mapping_csv: Path, target_sequence: str) -> torch.Tensor:
    weights = torch.zeros(len(target_sequence), dtype=torch.float32)
    seen = 0
    for row in read_csv(mapping_csv):
        if row["in_model_domain"] != "yes":
            continue
        index = int(row["model_index_0based"])
        if target_sequence[index] != row["aa"]:
            raise ValueError(f"Target mapping mismatch at model index {index}")
        weight = float(row["target_weight"] or 0.0)
        weights[index] = weight
        seen += int(weight > 0)
    if seen != 23:
        raise ValueError(f"Expected 23 weighted PVRIG interface residues, found {seen}")
    return weights


def contact_matrix(
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
            raise ValueError(f"Unexpected VHH chain: {v_chain}")
        v_index = v_resseq - 1
        p_index = pvrig_mapping.get((p_chain, p_resseq, p_icode))
        if not 0 <= v_index < vhh_length or p_index is None:
            raise ValueError(f"Unmapped teacher contact: {pair}")
        matrix[v_index, p_index] = max(matrix[v_index, p_index], float(pair["frequency"]))
    return matrix


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


def spearman(values: Sequence[float], predictions: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    x = rankdata(np.asarray(values, dtype=np.float64))
    y = rankdata(np.asarray(predictions, dtype=np.float64))
    if np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def load_backbone_checkpoint(path: Path) -> tuple[v23.Config, dict[str, torch.Tensor]]:
    source = torch.load(path, map_location="cpu", weights_only=False)
    if "cfg" in source:
        config = source["cfg"]
    elif "backbone_cfg" in source:
        config = source["backbone_cfg"]
    else:
        raise ValueError("Unsupported source checkpoint: missing cfg/backbone_cfg")
    state = source.get("model") or source.get("model_state_dict")
    if not isinstance(state, dict):
        raise ValueError("Unsupported source checkpoint: missing model state")
    return v23.Config(**config), state


class PilotTeacherDataset(Dataset):
    def __init__(
        self,
        split: str,
        cfg: v23.Config,
        cache: v23.ESM2Cache,
        cdrs: v23.CDRMaskStore,
        teacher_rows: list[dict[str, str]],
        selection: dict[str, dict[str, str]],
        contacts: dict[str, dict[str, Any]],
        target_sequence: str,
        pvrig_mapping: dict[tuple[str, int, str], int],
    ):
        self.rows: list[dict[str, Any]] = []
        self.cfg = cfg
        self.cache = cache
        self.cdrs = cdrs
        self.target_sequence = target_sequence
        for teacher in teacher_rows:
            candidate_id = teacher["candidate_id"]
            source = selection[candidate_id]
            group = f"{source['hotspot_set']}:{source['backbone_index']}"
            if stable_split(group) != split:
                continue
            if teacher["teacher_completeness"] != "COMPLETE":
                continue
            sequence = teacher["sequence"]
            if not cache.has(sequence) or not cdrs.has_cdr3(sequence):
                raise ValueError(f"Missing model input for {candidate_id}")
            contact = contact_matrix(contacts[candidate_id], len(sequence), len(target_sequence), pvrig_mapping)
            self.rows.append(
                {
                    "candidate_id": candidate_id,
                    "group": group,
                    "sequence": sequence,
                    "tier": teacher["provisional_stable_geometry_tier"],
                    "relevance": TIER_TO_RELEVANCE[teacher["provisional_stable_geometry_tier"]],
                    "geometry": [float(teacher[field]) for field in GEOMETRY_FIELDS],
                    "contact": contact,
                }
            )
        self.rows.sort(key=lambda row: row["candidate_id"])

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        sequence = row["sequence"]
        vhh = self.cache.get(sequence, self.cfg.max_vhh_len)
        cdr = self.cdrs.get(sequence, self.cfg.max_vhh_len)[: len(vhh)]
        antigen = self.cache.get(self.target_sequence, self.cfg.max_antigen_len)
        return {
            **row,
            "vhh": vhh,
            "cdr": cdr,
            "antigen": antigen,
        }


def collate_pilot(batch: list[dict[str, Any]]) -> dict[str, Any]:
    max_vhh = max(len(row["vhh"]) for row in batch)
    target_length = batch[0]["contact"].shape[1]
    contacts = torch.zeros((len(batch), max_vhh, target_length), dtype=torch.float32)
    for index, row in enumerate(batch):
        contacts[index, : row["contact"].shape[0]] = row["contact"]
    return {
        "candidate_id": [row["candidate_id"] for row in batch],
        "group": [row["group"] for row in batch],
        "tier": [row["tier"] for row in batch],
        "vhh": pad_sequence([row["vhh"] for row in batch], batch_first=True),
        "cdr": pad_sequence([row["cdr"] for row in batch], batch_first=True, padding_value=v23.PAD_CDR),
        "antigen": pad_sequence([row["antigen"] for row in batch], batch_first=True),
        "relevance": torch.tensor([row["relevance"] for row in batch], dtype=torch.long),
        "geometry": torch.tensor([row["geometry"] for row in batch], dtype=torch.float32),
        "contact": contacts,
    }


class PVRIGPilotHead(nn.Module):
    def __init__(self, backbone: v23.CrossContactNetV23, cfg: SmokeConfig, hotspot_weights: torch.Tensor):
        super().__init__()
        self.backbone = backbone
        for parameter in self.backbone.parameters():
            parameter.requires_grad = False
        d_model = backbone.cfg.d_model
        self.q = nn.Linear(d_model, cfg.contact_dim)
        self.k = nn.Linear(d_model, cfg.contact_dim)
        self.contact_bias_v = nn.Linear(d_model, 1)
        self.contact_bias_a = nn.Linear(d_model, 1)
        self.contact_scale = nn.Parameter(torch.tensor(0.1))
        self.v_pool = nn.Sequential(nn.Linear(d_model, 32), nn.GELU())
        feature_dim = 32 + 12
        self.shared = nn.Sequential(
            nn.Linear(feature_dim, cfg.hidden_dim),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(cfg.hidden_dim, cfg.hidden_dim),
            nn.GELU(),
        )
        self.ordinal = nn.Linear(cfg.hidden_dim, 4)
        self.geometry = nn.Linear(cfg.hidden_dim, len(GEOMETRY_FIELDS))
        self.register_buffer("hotspot_weights", hotspot_weights.float())

    def forward(self, vhh: torch.Tensor, cdr: torch.Tensor, antigen: torch.Tensor) -> dict[str, torch.Tensor]:
        self.backbone.eval()
        with torch.no_grad():
            hv, ha, v_mask, a_mask = self.backbone.encode(vhh, cdr, antigen)
            base_contact = self.backbone.contact_logits(hv, ha)
            generic_logit = self.backbone.pair_logits_from_encoded(hv, ha, v_mask, a_mask, cdr)
        adapter = torch.bmm(self.q(hv), self.k(ha).transpose(1, 2)) / math.sqrt(float(self.q.out_features))
        adapter = adapter + self.contact_bias_v(hv) + self.contact_bias_a(ha).transpose(1, 2)
        contact_logits = base_contact + self.contact_scale * adapter
        valid = (~v_mask).unsqueeze(2) & (~a_mask).unsqueeze(1)
        probs = torch.sigmoid(contact_logits).masked_fill(~valid, 0.0)

        v_valid = (~v_mask).float().unsqueeze(-1)
        pooled = (hv * v_valid).sum(1) / v_valid.sum(1).clamp_min(1.0)
        hotspot = self.hotspot_weights[: ha.shape[1]].view(1, 1, -1)
        interface_mask = hotspot.gt(0) & valid
        noninterface_mask = hotspot.eq(0) & valid

        def masked_mean(mask: torch.Tensor) -> torch.Tensor:
            return (probs * mask).sum((1, 2)) / mask.float().sum((1, 2)).clamp_min(1.0)

        hotspot_mean = masked_mean(interface_mask)
        noninterface_mean = masked_mean(noninterface_mask)
        weighted_hotspot = (probs * hotspot * valid).sum((1, 2)) / (hotspot * valid).sum((1, 2)).clamp_min(1.0)
        flat = probs.masked_fill(~valid, -1.0).flatten(1)
        top = torch.topk(flat, k=min(20, flat.shape[1]), dim=1).values.clamp_min(0.0)
        top1 = top[:, 0]
        top5 = top[:, : min(5, top.shape[1])].mean(1)
        top20 = top.mean(1)
        cdr_stats: list[torch.Tensor] = []
        for cdr_type in (1, 2, 3):
            mask = (cdr == cdr_type).unsqueeze(2) & interface_mask
            cdr_stats.append(masked_mean(mask))
        valid_count = valid.float().sum((1, 2)).clamp_min(1.0)
        entropy = -(probs.clamp_min(1e-6) * probs.clamp_min(1e-6).log() * valid).sum((1, 2)) / valid_count
        engineered = torch.stack(
            [
                hotspot_mean,
                noninterface_mean,
                weighted_hotspot,
                hotspot_mean - noninterface_mean,
                top1,
                top5,
                top20,
                *cdr_stats,
                entropy,
            ],
            dim=1,
        )
        features = torch.cat([self.v_pool(pooled), engineered, torch.sigmoid(generic_logit).unsqueeze(1)], dim=1)
        hidden = self.shared(features)
        return {
            "ordinal_logits": self.ordinal(hidden),
            "geometry": self.geometry(hidden),
            "contact_logits": contact_logits,
            "valid_contact_mask": valid,
            "generic_binding_prior": torch.sigmoid(generic_logit),
        }


def ordinal_targets(relevance: torch.Tensor) -> torch.Tensor:
    return (relevance.unsqueeze(1) > torch.arange(4, device=relevance.device).unsqueeze(0)).float()


def contact_loss(
    logits: torch.Tensor,
    targets: torch.Tensor,
    valid: torch.Tensor,
    negative_weight: float,
) -> torch.Tensor:
    positive = (targets > 0) & valid
    negative = (targets == 0) & valid
    positive_loss = nn.functional.binary_cross_entropy_with_logits(logits[positive], targets[positive]) if positive.any() else logits.sum() * 0.0
    negative_loss = nn.functional.binary_cross_entropy_with_logits(logits[negative], targets[negative]) if negative.any() else logits.sum() * 0.0
    return positive_loss + negative_weight * negative_loss


def compute_loss(
    outputs: dict[str, torch.Tensor],
    batch: dict[str, Any],
    geometry_mean: torch.Tensor,
    geometry_std: torch.Tensor,
    cfg: SmokeConfig,
) -> tuple[torch.Tensor, dict[str, float]]:
    relevance = batch["relevance"].to(outputs["ordinal_logits"].device)
    geometry = batch["geometry"].to(outputs["geometry"].device)
    contacts = batch["contact"].to(outputs["contact_logits"].device)
    ordinal = nn.functional.binary_cross_entropy_with_logits(outputs["ordinal_logits"], ordinal_targets(relevance))
    probabilities = torch.sigmoid(outputs["ordinal_logits"])
    monotonic = torch.relu(probabilities[:, 1:] - probabilities[:, :-1]).mean()
    regression = nn.functional.smooth_l1_loss(outputs["geometry"], (geometry - geometry_mean) / geometry_std)
    contact = contact_loss(outputs["contact_logits"], contacts, outputs["valid_contact_mask"], cfg.negative_contact_weight)
    total = (
        cfg.ordinal_weight * ordinal
        + cfg.regression_weight * regression
        + cfg.contact_weight * contact
        + cfg.monotonic_weight * monotonic
    )
    return total, {
        "ordinal": float(ordinal.detach().cpu()),
        "regression": float(regression.detach().cpu()),
        "contact": float(contact.detach().cpu()),
        "monotonic": float(monotonic.detach().cpu()),
    }


def evaluate(
    model: PVRIGPilotHead,
    loader: DataLoader,
    device: torch.device,
    geometry_mean: torch.Tensor,
    geometry_std: torch.Tensor,
    cfg: SmokeConfig,
) -> tuple[dict[str, float], list[dict[str, object]]]:
    model.eval()
    losses: list[float] = []
    true_rel: list[int] = []
    pred_rel: list[float] = []
    true_geometry: list[list[float]] = []
    pred_geometry: list[list[float]] = []
    contact_positive_mae: list[float] = []
    predictions: list[dict[str, object]] = []
    with torch.inference_mode():
        for batch_index, batch in enumerate(loader, start=1):
            if cfg.max_eval_batches and batch_index > cfg.max_eval_batches:
                break
            with torch.amp.autocast(device_type=device.type, enabled=cfg.use_amp and device.type == "cuda"):
                outputs = model(batch["vhh"].to(device), batch["cdr"].to(device), batch["antigen"].to(device))
                loss, _ = compute_loss(outputs, batch, geometry_mean, geometry_std, cfg)
            losses.append(float(loss.cpu()))
            ordinal_prob = torch.sigmoid(outputs["ordinal_logits"]).float().cpu()
            relevance_score = ordinal_prob.sum(1)
            geometry = (outputs["geometry"].float().cpu() * geometry_std.cpu()) + geometry_mean.cpu()
            contact_prob = torch.sigmoid(outputs["contact_logits"]).float().cpu()
            positive = batch["contact"] > 0
            for index, candidate_id in enumerate(batch["candidate_id"]):
                actual_rel = int(batch["relevance"][index])
                score = float(relevance_score[index])
                actual_geometry = batch["geometry"][index].tolist()
                predicted_geometry = geometry[index].tolist()
                if positive[index].any():
                    contact_positive_mae.append(float(torch.abs(contact_prob[index][positive[index]] - batch["contact"][index][positive[index]]).mean()))
                true_rel.append(actual_rel)
                pred_rel.append(score)
                true_geometry.append(actual_geometry)
                pred_geometry.append(predicted_geometry)
                predictions.append(
                    {
                        "candidate_id": candidate_id,
                        "split": "dev",
                        "true_tier": RELEVANCE_TO_TIER[actual_rel],
                        "true_relevance": actual_rel,
                        "predicted_relevance": score,
                        "predicted_tier": RELEVANCE_TO_TIER[max(0, min(4, int(round(score))))],
                        "generic_binding_prior": float(outputs["generic_binding_prior"][index].float().cpu()),
                        **{f"true_{field}": actual_geometry[pos] for pos, field in enumerate(GEOMETRY_FIELDS)},
                        **{f"predicted_{field}": predicted_geometry[pos] for pos, field in enumerate(GEOMETRY_FIELDS)},
                    }
                )
    pred_array = np.asarray(pred_geometry, dtype=np.float64)
    true_array = np.asarray(true_geometry, dtype=np.float64)
    metrics: dict[str, float] = {
        "loss": statistics.mean(losses) if losses else 0.0,
        "ordinal_mae": float(np.mean(np.abs(np.asarray(true_rel) - np.asarray(pred_rel)))) if true_rel else 0.0,
        "ordinal_spearman": spearman(true_rel, pred_rel),
        "contact_positive_mae": statistics.mean(contact_positive_mae) if contact_positive_mae else 0.0,
    }
    for index, field in enumerate(GEOMETRY_FIELDS):
        metrics[f"{field}_mae"] = float(np.mean(np.abs(true_array[:, index] - pred_array[:, index]))) if len(true_array) else 0.0
        metrics[f"{field}_spearman"] = spearman(true_array[:, index], pred_array[:, index]) if len(true_array) else 0.0
    return metrics, predictions


def train(cfg: SmokeConfig) -> dict[str, Any]:
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.manual_seed_all(cfg.seed)
        torch.set_float32_matmul_precision("high")

    teacher_rows = read_csv(Path(cfg.teacher_csv))
    selection_rows = read_csv(Path(cfg.selection_tsv), delimiter="\t")
    contact_rows = read_jsonl(Path(cfg.contact_jsonl))
    if len(teacher_rows) != 96 or len(contact_rows) != 96:
        raise ValueError("V3-P1 pilot smoke requires 96 complete teacher candidates")
    selection = {row["candidate_id"]: row for row in selection_rows}
    contacts = {row["candidate_id"]: row for row in contact_rows}
    if set(selection) != {row["candidate_id"] for row in teacher_rows} or set(contacts) != set(selection):
        raise ValueError("Teacher, selection, and contact candidate IDs do not match")

    backbone_cfg, backbone_state = load_backbone_checkpoint(Path(cfg.source_checkpoint))
    cache = v23.ESM2Cache(Path(cfg.cache_manifest), backbone_cfg.esm_dim)
    cdrs = v23.CDRMaskStore(Path(cfg.cdr_mask_csv))
    target_sequence = read_fasta(Path(cfg.target_fasta))
    pdb_mapping = pvrig_pdb_to_model_index(Path(cfg.reconciliation_csv), target_sequence)
    hotspot = target_weights(Path(cfg.target_mapping_csv), target_sequence)
    datasets = {
        split: PilotTeacherDataset(
            split,
            backbone_cfg,
            cache,
            cdrs,
            teacher_rows,
            selection,
            contacts,
            target_sequence,
            pdb_mapping,
        )
        for split in ("train", "dev")
    }
    if not datasets["train"] or not datasets["dev"]:
        raise ValueError("Stable pilot split produced an empty train or dev set")

    train_geometry = torch.tensor([row["geometry"] for row in datasets["train"].rows], dtype=torch.float32)
    geometry_mean = train_geometry.mean(0).to(device)
    geometry_std = train_geometry.std(0, unbiased=False).clamp_min(1e-6).to(device)
    generator = torch.Generator().manual_seed(cfg.seed)
    loaders = {
        "train": DataLoader(datasets["train"], batch_size=cfg.batch_size, shuffle=True, generator=generator, collate_fn=collate_pilot),
        "dev": DataLoader(datasets["dev"], batch_size=cfg.batch_size, shuffle=False, collate_fn=collate_pilot),
    }

    backbone = v23.CrossContactNetV23(backbone_cfg)
    backbone.load_state_dict(backbone_state)
    model = PVRIGPilotHead(backbone, cfg, hotspot).to(device)
    trainable = [name for name, parameter in model.named_parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=cfg.learning_rate,
        weight_decay=cfg.weight_decay,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=cfg.use_amp and device.type == "cuda")

    run_id = time.strftime("phase2_v3_p1_pilot_smoke_%Y%m%d_%H%M%S") + f"_seed{cfg.seed}"
    run_dir = Path(cfg.out_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "config_resolved.json").write_text(json.dumps(asdict(cfg), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    baseline_predictions = [statistics.mean(row["relevance"] for row in datasets["train"].rows)] * len(datasets["dev"])
    baseline_metrics = {
        "constant_train_mean_ordinal_mae": float(
            np.mean(np.abs(np.asarray([row["relevance"] for row in datasets["dev"].rows]) - np.asarray(baseline_predictions)))
        ),
        "constant_train_mean_ordinal_spearman": 0.0,
    }
    history: list[dict[str, Any]] = []
    best_loss = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        model.backbone.eval()
        batch_losses: list[float] = []
        components: dict[str, list[float]] = {name: [] for name in ("ordinal", "regression", "contact", "monotonic")}
        for batch_index, batch in enumerate(loaders["train"], start=1):
            if cfg.max_train_batches and batch_index > cfg.max_train_batches:
                break
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast(device_type=device.type, enabled=cfg.use_amp and device.type == "cuda"):
                outputs = model(batch["vhh"].to(device), batch["cdr"].to(device), batch["antigen"].to(device))
                loss, parts = compute_loss(outputs, batch, geometry_mean, geometry_std, cfg)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_((parameter for parameter in model.parameters() if parameter.requires_grad), 1.0)
            scaler.step(optimizer)
            scaler.update()
            batch_losses.append(float(loss.detach().cpu()))
            for name, value in parts.items():
                components[name].append(value)
        dev_metrics, _ = evaluate(model, loaders["dev"], device, geometry_mean, geometry_std, cfg)
        record = {
            "epoch": epoch,
            "train_loss": statistics.mean(batch_losses),
            **{f"train_{name}": statistics.mean(values) for name, values in components.items()},
            "dev": dev_metrics,
        }
        history.append(record)
        print(json.dumps(record, sort_keys=True), flush=True)
        if dev_metrics["loss"] < best_loss:
            best_loss = dev_metrics["loss"]
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
                if not name.startswith("backbone.")
            }
    if best_state is None:
        raise RuntimeError("No V3-P1 pilot checkpoint produced")
    model.load_state_dict(best_state, strict=False)
    final_metrics, predictions = evaluate(model, loaders["dev"], device, geometry_mean, geometry_std, cfg)

    checkpoint_path = run_dir / "checkpoint.pt"
    torch.save(
        {
            "schema_version": "phase2_v3_p1_pilot_smoke_checkpoint_v1",
            "head_state": best_state,
            "backbone_cfg": asdict(backbone_cfg),
            "source_checkpoint": cfg.source_checkpoint,
            "smoke_cfg": asdict(cfg),
            "geometry_fields": GEOMETRY_FIELDS,
            "geometry_mean": geometry_mean.cpu(),
            "geometry_std": geometry_std.cpu(),
            "trainable_parameters": trainable,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        checkpoint_path,
    )
    with (run_dir / "dev_predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)

    summary: dict[str, Any] = {
        "status": "PASS_PIPELINE_SMOKE_COMPLETED",
        "schema_version": "phase2_v3_p1_pilot_smoke_summary_v1",
        "run_dir": str(run_dir),
        "device": str(device),
        "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else "",
        "dataset_sizes": {split: len(dataset) for split, dataset in datasets.items()},
        "dataset_groups": {split: len({row["group"] for row in dataset.rows}) for split, dataset in datasets.items()},
        "tier_counts": {
            split: dict(sorted(Counter(row["tier"] for row in dataset.rows).items()))
            for split, dataset in datasets.items()
        },
        "baseline_metrics": baseline_metrics,
        "final_dev_metrics": final_metrics,
        "history": history,
        "trainable_parameters": trainable,
        "frozen_backbone": True,
        "artifact_sha256": {
            "teacher_csv": sha256_file(Path(cfg.teacher_csv)),
            "contact_jsonl": sha256_file(Path(cfg.contact_jsonl)),
            "selection_tsv": sha256_file(Path(cfg.selection_tsv)),
            "cache_manifest": sha256_file(Path(cfg.cache_manifest)),
            "cdr_mask_csv": sha256_file(Path(cfg.cdr_mask_csv)),
            "source_checkpoint": sha256_file(Path(cfg.source_checkpoint)),
            "checkpoint": sha256_file(checkpoint_path),
        },
        "formal_readiness": "NOT_READY_SINGLE_PARENT_PILOT_ONLY",
        "known_limitations": [
            "all candidates share h-NbBCII10",
            "9E6Y is rescoring of 8X6B-generated poses rather than independent docking",
            "pilot input lacks explicit dual-conformer residue structure channels",
            "no experimental binding or blocking labels are used",
        ],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    for field in (
        "teacher_csv",
        "contact_jsonl",
        "selection_tsv",
        "cache_manifest",
        "cdr_mask_csv",
        "target_fasta",
        "target_mapping_csv",
        "reconciliation_csv",
        "source_checkpoint",
        "out_root",
    ):
        parser.add_argument(f"--{field.replace('_', '-')}", default=getattr(SmokeConfig(), field))
    parser.add_argument("--seed", type=int, default=83)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=5e-4)
    parser.add_argument("--max-train-batches", type=int, default=0)
    parser.add_argument("--max-eval-batches", type=int, default=0)
    parser.add_argument("--no-amp", action="store_true")
    args = parser.parse_args(argv)
    return args


def main() -> None:
    args = parse_args()
    defaults = SmokeConfig()
    values = asdict(defaults)
    for key in values:
        if hasattr(args, key):
            values[key] = getattr(args, key)
    values["use_amp"] = not args.no_amp
    print(json.dumps(train(SmokeConfig(**values)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
