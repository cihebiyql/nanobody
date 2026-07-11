#!/usr/bin/env python3
"""Score PVRIG/VHH candidates with the Phase 2 V2.4 listwise ranking prior.

The V2.4 score is a ranking prior only. Constructed N1/N2/N3 rows are proxy
contrasts, not verified non-binders, and calibration is intentionally
NOT_APPLICABLE unless a separate verified binary calibration set exists.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import torch
from torch.nn.utils.rnn import pad_sequence

from train_phase2_v2_3 import CDRMaskStore, ESM2Cache, clean, seq_hash
from train_phase2_v2_4 import Config, CrossContactNetV24, load_config

DEFAULT_OUT_ROOT = Path("experiments/phase2_5080_v1")
DEFAULT_CHECKPOINT = DEFAULT_OUT_ROOT / "checkpoints/phase2_v2_4_best_checkpoint.pt"
DEFAULT_CONFIG = DEFAULT_OUT_ROOT / "configs/phase2_v2_4_listwise_5080_16gb.json"
DEFAULT_V2_2_TOP50 = DEFAULT_OUT_ROOT / "predictions/pvrig_top_candidates_phase2_v2_2_full2277.csv"
DEFAULT_CANDIDATES = Path("model_data/mvp_candidates_v0.csv")
DEFAULT_TARGET_FASTA = Path("model_data/pvrig_target_ectodomain_proxy_v1.fasta")
DEFAULT_OUTPUT = DEFAULT_OUT_ROOT / "predictions/pvrig_candidate_ranking_ai_prior_v2_4.csv"
DEFAULT_CACHE_MANIFEST = DEFAULT_OUT_ROOT / "prepared/esm2_8m_v2_3_cache/manifest.csv"
DEFAULT_CDR_MASKS = DEFAULT_OUT_ROOT / "data_splits/vhh_cdr_type_masks_v2_3.csv"
DEFAULT_CONTROLS = DEFAULT_OUT_ROOT / "data_splits/pvrig_validation_controls_v2_4.csv"

CHECKPOINT_SCHEMA_VERSION = "phase2_v2_4_listwise_ranking_checkpoint_v1"
SCHEMA_VERSION = "pvrig_vhh_phase2_v2_4_listwise_ranking_ai_prior_v1"
BOUNDARY_NOTE = (
    "V2.4 ranking AI prior only; sigmoid proxy is not a calibrated blocker probability; "
    "constructed N1/N2/N3 contrasts are not verified non-binders"
)
CALIBRATION_STATUS = "NOT_APPLICABLE"
CONSTRUCTED_POLICY = "constructed_preference_not_verified_nonbinder"
EXCLUDED_LEAKAGE_LABELS = {"EXACT_KNOWN_POSITIVE", "NEAR_KNOWN_POSITIVE"}
EXCLUDED_ROLE_TOKENS = (
    "known_pvrig_blocking_positive_control",
    "known_positive_calibration",
    "mutant_or_leakage_control",
    "base_reference",
    "constructed_contrastive_candidate",
)
CONSTRUCTED_NEGATIVE_PREFIXES = ("N1", "N2", "N3")
HASH_COLUMNS = ("vhh_sequence_sha256", "sequence_sha256", "vhh_seq_sha256")


def resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def read_fasta(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing FASTA: {path}")
    seq = "".join(line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.startswith(">"))
    if not seq:
        raise ValueError(f"Empty FASTA sequence: {path}")
    return clean(seq).upper()


def stable_row_hash(parts: Iterable[Any]) -> str:
    return hashlib.sha256("\x1f".join(clean(part) for part in parts).encode("utf-8")).hexdigest()


def load_checkpoint_config(checkpoint_path: Path, fallback_config_path: Path | None = None) -> tuple[Config, dict[str, Any]]:
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Missing V2.4 checkpoint: {checkpoint_path}")
    ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    schema = clean(ckpt.get("schema_version"))
    if schema != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError(f"Incompatible V2.4 checkpoint schema: expected {CHECKPOINT_SCHEMA_VERSION}, observed {schema or 'MISSING'}")
    raw_cfg = ckpt.get("cfg")
    if raw_cfg is None:
        if fallback_config_path is None:
            raise ValueError("V2.4 checkpoint missing cfg and no fallback config was supplied")
        cfg = load_config(fallback_config_path)
    else:
        allowed = {f.name for f in fields(Config)}
        unknown = set(raw_cfg) - allowed
        if unknown:
            raise ValueError(f"Checkpoint config has unknown V2.4 fields: {sorted(unknown)}")
        cfg = Config(**{**asdict(Config()), **raw_cfg})
    return cfg, ckpt


def load_model_from_checkpoint(checkpoint_path: Path, fallback_config_path: Path | None, device: torch.device) -> tuple[CrossContactNetV24, Config, dict[str, Any]]:
    cfg, ckpt = load_checkpoint_config(checkpoint_path, fallback_config_path)
    model = CrossContactNetV24(cfg).to(device)
    state = ckpt.get("model")
    if not isinstance(state, dict):
        raise ValueError(f"Checkpoint missing model state dict: {checkpoint_path}")
    model.load_state_dict(state)
    model.eval()
    return model, cfg, ckpt


def load_default_candidates(top50_path: Path, candidate_table_path: Path, limit: int) -> pd.DataFrame:
    if not top50_path.exists():
        raise FileNotFoundError(f"Missing default V2.2 top candidate file: {top50_path}")
    if not candidate_table_path.exists():
        raise FileNotFoundError(f"Missing candidate sequence table: {candidate_table_path}")
    top = pd.read_csv(top50_path).head(limit).copy()
    top.insert(0, "source_v2_2_rank", np.arange(1, len(top) + 1, dtype=int))
    candidates = pd.read_csv(candidate_table_path)
    missing = {"candidate_id", "vhh_seq"} - set(candidates.columns)
    if missing:
        raise ValueError(f"Candidate table missing columns: {sorted(missing)}")
    merged = top.merge(candidates, on="candidate_id", how="left", suffixes=("", "_candidate"))
    if merged["vhh_seq"].isna().any():
        missing_ids = merged.loc[merged["vhh_seq"].isna(), "candidate_id"].astype(str).tolist()
        raise ValueError(f"Default candidate IDs missing sequences: {missing_ids[:5]}")
    return merged


def load_candidate_override(path: Path, candidate_table_path: Path | None, limit: int | None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing candidate override CSV: {path}")
    df = pd.read_csv(path).copy()
    if "vhh_seq" not in df.columns:
        if "candidate_id" not in df.columns or candidate_table_path is None:
            raise ValueError("Candidate override must include vhh_seq, or candidate_id plus --candidate-table")
        df = df.merge(pd.read_csv(candidate_table_path), on="candidate_id", how="left", suffixes=("", "_candidate"))
    if limit is not None:
        df = df.head(limit).copy()
    missing = {"candidate_id", "vhh_seq"} - set(df.columns)
    if missing:
        raise ValueError(f"Candidate input missing columns: {sorted(missing)}")
    if df["vhh_seq"].isna().any():
        raise ValueError("Candidate input contains rows without vhh_seq")
    return df


def validate_candidate_identity(df: pd.DataFrame, target_seq: str | None = None) -> None:
    seen: dict[str, str] = {}
    for idx, row in df.iterrows():
        candidate_id = clean(row.get("candidate_id"))
        seq = clean(row.get("vhh_seq")).upper()
        digest = seq_hash(seq)
        for column in HASH_COLUMNS:
            if column in df.columns and clean(row.get(column)) and clean(row.get(column)).lower() != digest:
                raise ValueError(f"Candidate identity mismatch for {candidate_id or idx}: {column} does not match vhh_seq")
        if candidate_id in seen and seen[candidate_id] != digest:
            raise ValueError(f"Candidate identity mismatch: duplicate candidate_id {candidate_id} has multiple sequences")
        seen[candidate_id] = digest
        if target_seq and "target_sequence_sha256" in df.columns and clean(row.get("target_sequence_sha256")):
            if clean(row.get("target_sequence_sha256")).lower() != seq_hash(target_seq):
                raise ValueError(f"Candidate identity mismatch for {candidate_id or idx}: target_sequence_sha256 does not match target FASTA")


def _load_control_hashes(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    df = pd.read_csv(path)
    hashes: set[str] = set()
    if "sequence_sha256" in df.columns:
        if "candidate_ranking_allowed" in df.columns:
            disallowed = df[df["candidate_ranking_allowed"].astype(str).str.lower().isin({"false", "0", "no"})]
        else:
            disallowed = df
        hashes.update(clean(value).lower() for value in disallowed["sequence_sha256"].dropna().tolist() if clean(value))
    return hashes


def exclusion_reason(row: pd.Series, control_hashes: set[str] | None = None) -> str:
    labels = [clean(row.get("leakage_label")), clean(row.get("source_leakage_label")), clean(row.get("label_hint"))]
    for label in labels:
        if label in EXCLUDED_LEAKAGE_LABELS:
            return f"excluded_leakage_{label}"
    seq = clean(row.get("vhh_seq")).upper()
    if control_hashes and seq_hash(seq).lower() in control_hashes:
        return "excluded_v2_4_positive_or_mutant_control_hash"
    negative_type = clean(row.get("negative_type"))
    if negative_type.startswith(CONSTRUCTED_NEGATIVE_PREFIXES):
        return "excluded_constructed_n1_n2_n3_proxy_contrast"
    if clean(row.get("proxy_label_policy")) == CONSTRUCTED_POLICY:
        return "excluded_constructed_proxy_not_verified_nonbinder"
    for column in ("candidate_role", "control_role", "family", "control_expected_role"):
        value = clean(row.get(column)).lower()
        if any(token in value for token in EXCLUDED_ROLE_TOKENS):
            return "excluded_positive_mutant_or_constructed_control_role"
    if clean(row.get("candidate_ranking_allowed")).lower() in {"false", "0", "no"}:
        return "excluded_candidate_ranking_not_allowed"
    return ""


def split_exclusions(df: pd.DataFrame, control_hashes: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    reasons = df.apply(lambda row: exclusion_reason(row, control_hashes), axis=1)
    kept = df[reasons == ""].copy().reset_index(drop=True)
    excluded = df[reasons != ""].copy().reset_index(drop=True)
    if not excluded.empty:
        excluded["exclusion_reason"] = reasons[reasons != ""].values
    return kept, excluded


def summarize_vector(values: np.ndarray, seq: str, top_k: int = 5) -> dict[str, Any]:
    if values.size == 0:
        return {"top": [], "mean": 0.0, "max": 0.0}
    order = np.argsort(-values)[: min(top_k, values.size)]
    return {
        "top": [
            {"rank": int(i + 1), "position_1based": int(idx + 1), "aa": seq[int(idx)] if int(idx) < len(seq) else "", "score": float(values[int(idx)])}
            for i, idx in enumerate(order)
        ],
        "mean": float(np.mean(values)),
        "max": float(np.max(values)),
    }


def summarize_contacts(contact_probs: np.ndarray, vhh_seq: str, antigen_seq: str, cdr_mask: np.ndarray, top_k: int = 10) -> dict[str, Any]:
    if contact_probs.size == 0:
        return {"top_pairs": [], "top20_mean": 0.0, "cdr3_top20_mean": 0.0, "cdr3_mean": 0.0}
    flat = contact_probs.reshape(-1)
    top_idx = np.argsort(-flat)[: min(top_k, flat.size)]
    la = contact_probs.shape[1]
    pairs = []
    for rank, idx in enumerate(top_idx, start=1):
        vi = int(idx // la)
        ai = int(idx % la)
        pairs.append({
            "rank": rank,
            "vhh_position_1based": vi + 1,
            "vhh_aa": vhh_seq[vi] if vi < len(vhh_seq) else "",
            "cdr_type": int(cdr_mask[vi]) if vi < len(cdr_mask) else 0,
            "target_position_1based": ai + 1,
            "target_aa": antigen_seq[ai] if ai < len(antigen_seq) else "",
            "contact_ai_prior": float(contact_probs[vi, ai]),
        })
    top20 = np.sort(flat)[-min(20, flat.size):]
    cdr3_rows = np.where(cdr_mask[: contact_probs.shape[0]] == 3)[0]
    if cdr3_rows.size:
        cdr3_flat = contact_probs[cdr3_rows, :].reshape(-1)
        cdr3_top20 = np.sort(cdr3_flat)[-min(20, cdr3_flat.size):]
        cdr3_top20_mean = float(np.mean(cdr3_top20)) if cdr3_top20.size else 0.0
        cdr3_mean = float(np.mean(cdr3_flat)) if cdr3_flat.size else 0.0
    else:
        cdr3_top20_mean = 0.0
        cdr3_mean = 0.0
    return {"top_pairs": pairs, "top20_mean": float(np.mean(top20)), "cdr3_top20_mean": cdr3_top20_mean, "cdr3_mean": cdr3_mean}


def minmax(series: pd.Series) -> pd.Series:
    vals = pd.to_numeric(series, errors="coerce").fillna(0.0)
    lo = float(vals.min()) if len(vals) else 0.0
    hi = float(vals.max()) if len(vals) else 0.0
    if hi - lo < 1e-12:
        return pd.Series([0.0] * len(vals), index=series.index)
    return (vals - lo) / (hi - lo)


def score_candidates(model: CrossContactNetV24, cfg: Config, cache: ESM2Cache, cdrs: CDRMaskStore, candidates: pd.DataFrame, target_seq: str, device: torch.device, batch_size: int = 8) -> pd.DataFrame:
    target_emb = cache.get(target_seq, cfg.max_antigen_len)
    rows: list[dict[str, Any]] = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(candidates), batch_size):
            batch = candidates.iloc[start:start + batch_size]
            vhh_tensors: list[torch.Tensor] = []
            cdr_tensors: list[torch.Tensor] = []
            seqs: list[str] = []
            for _, row in batch.iterrows():
                seq = clean(row["vhh_seq"]).upper()
                emb = cache.get(seq, cfg.max_vhh_len)
                cdr = cdrs.get(seq, cfg.max_vhh_len)[: emb.shape[0]]
                vhh_tensors.append(emb)
                cdr_tensors.append(cdr)
                seqs.append(seq)
            vhh = pad_sequence(vhh_tensors, batch_first=True).to(device)
            cdr = pad_sequence(cdr_tensors, batch_first=True, padding_value=0).to(device)
            antigen = pad_sequence([target_emb] * len(vhh_tensors), batch_first=True).to(device)
            hv, ha, vm, am = model.encode(vhh, cdr, antigen)
            pair_logits = model.pair_logits_from_encoded(hv, ha, vm, am, cdr)
            para_logits, epi_logits = model.site_logits(hv, ha)
            contact_logits = model.contact_logits(hv, ha)
            pair_logits_cpu = pair_logits.detach().cpu().numpy()
            pair_sigmoid_cpu = torch.sigmoid(pair_logits).detach().cpu().numpy()
            para = torch.sigmoid(para_logits).detach().cpu().numpy()
            epi = torch.sigmoid(epi_logits).detach().cpu().numpy()
            contacts = torch.sigmoid(contact_logits).detach().cpu().numpy()
            for local_i, (_, source_row) in enumerate(batch.iterrows()):
                lv = int((~vm[local_i]).sum().detach().cpu())
                la = int((~am[local_i]).sum().detach().cpu())
                cdr_np = cdr[local_i, :lv].detach().cpu().numpy().astype(int)
                contact_summary = summarize_contacts(contacts[local_i, :lv, :la], seqs[local_i], target_seq[:la], cdr_np)
                passthrough = {("source_input_rank" if column == "rank" else str(column)): ("" if pd.isna(value) else value) for column, value in source_row.items() if column != "vhh_seq"}
                candidate_id = clean(source_row.get("candidate_id"))
                vhh_digest = seq_hash(seqs[local_i])
                target_digest = seq_hash(target_seq)
                passthrough.update({
                    "schema_version": SCHEMA_VERSION,
                    "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
                    "candidate_id": candidate_id,
                    "vhh_sequence": seqs[local_i],
                    "vhh_sequence_sha256": vhh_digest,
                    "target_sequence": target_seq,
                    "target_sequence_sha256": target_digest,
                    "candidate_identity_sha256": stable_row_hash([candidate_id, vhh_digest, target_digest]),
                    "phase2_v2_4_pair_ranking_logit": float(pair_logits_cpu[local_i]),
                    "phase2_v2_4_sigmoid_pair_ranking_ai_prior": float(pair_sigmoid_cpu[local_i]),
                    "phase2_v2_4_paratope_ai_prior_json": json.dumps(summarize_vector(para[local_i, :lv], seqs[local_i]), ensure_ascii=False, sort_keys=True),
                    "phase2_v2_4_epitope_ai_prior_json": json.dumps(summarize_vector(epi[local_i, :la], target_seq[:la]), ensure_ascii=False, sort_keys=True),
                    "phase2_v2_4_contact_hotspot_ai_prior_json": json.dumps(contact_summary, ensure_ascii=False, sort_keys=True),
                    "phase2_v2_4_contact_top20_mean_ai_prior": contact_summary["top20_mean"],
                    "phase2_v2_4_cdr3_contact_top20_mean_ai_prior": contact_summary["cdr3_top20_mean"],
                    "phase2_v2_4_cdr3_contact_mean_ai_prior": contact_summary["cdr3_mean"],
                    "phase2_v2_4_boundary_note": BOUNDARY_NOTE,
                    "phase2_v2_4_constructed_negative_semantics": "N1/N2/N3 constructed rows are excluded from ordinary ranks and are not verified non-binders",
                    "phase2_v2_4_calibration_status": CALIBRATION_STATUS,
                    "calibration_status": CALIBRATION_STATUS,
                })
                rows.append(passthrough)
    out = pd.DataFrame(rows)
    if not out.empty:
        out["phase2_v2_4_pair_ranking_logit_norm"] = minmax(out["phase2_v2_4_pair_ranking_logit"])
        out["phase2_v2_4_sigmoid_pair_ranking_ai_prior_norm"] = minmax(out["phase2_v2_4_sigmoid_pair_ranking_ai_prior"])
        out["phase2_v2_4_contact_top20_mean_ai_prior_norm"] = minmax(out["phase2_v2_4_contact_top20_mean_ai_prior"])
        out["phase2_v2_4_cdr3_contact_top20_mean_ai_prior_norm"] = minmax(out["phase2_v2_4_cdr3_contact_top20_mean_ai_prior"])
        out["phase2_v2_4_combined_ranking_ai_prior"] = (
            0.45 * out["phase2_v2_4_pair_ranking_logit_norm"]
            + 0.25 * out["phase2_v2_4_cdr3_contact_top20_mean_ai_prior_norm"]
            + 0.20 * out["phase2_v2_4_contact_top20_mean_ai_prior_norm"]
            + 0.10 * out["phase2_v2_4_sigmoid_pair_ranking_ai_prior_norm"]
        )
        out = out.sort_values("phase2_v2_4_combined_ranking_ai_prior", ascending=False).reset_index(drop=True)
        out.insert(0, "rank", np.arange(1, len(out) + 1, dtype=int))
    return out


def validate_cache_and_masks(candidates: pd.DataFrame, target_seq: str, cache: ESM2Cache, cdrs: CDRMaskStore) -> None:
    missing_cache: list[str] = []
    missing_cdr: list[str] = []
    for seq in [target_seq] + [clean(s).upper() for s in candidates["vhh_seq"].tolist()]:
        if not cache.has(seq):
            missing_cache.append(seq_hash(seq))
    for seq in [clean(s).upper() for s in candidates["vhh_seq"].tolist()]:
        if not cdrs.has(seq):
            missing_cdr.append(seq_hash(seq))
    if missing_cache:
        raise ValueError(f"Missing frozen ESM2 cache embeddings; first={missing_cache[0]} count={len(missing_cache)}")
    if missing_cdr:
        raise ValueError(f"Missing VHH CDR type masks; first={missing_cdr[0]} count={len(missing_cdr)}")


def write_exclusions(excluded: pd.DataFrame, output_path: Path) -> Path | None:
    if excluded.empty:
        return None
    path = output_path.with_suffix(".excluded.csv")
    cols = [c for c in ["candidate_id", "exclusion_reason", "source_leakage_label", "leakage_label", "label_hint", "candidate_role", "control_role", "negative_type", "proxy_label_policy", "candidate_ranking_allowed"] if c in excluded.columns]
    excluded[cols].to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
    return path


def run_scoring(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    checkpoint = resolve_path(root, args.checkpoint)
    fallback_config = resolve_path(root, args.config) if args.config else None
    device = torch.device(args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu"))
    model, cfg, ckpt = load_model_from_checkpoint(checkpoint, fallback_config, device)
    cfg.root = str(root)
    cache_path = resolve_path(root, args.esm2_cache_manifest or cfg.esm2_cache_manifest or DEFAULT_CACHE_MANIFEST)
    cdr_path = resolve_path(root, args.cdr_mask_csv or cfg.cdr_mask_csv or DEFAULT_CDR_MASKS)
    cache = ESM2Cache(cache_path, cfg.esm_dim)
    cdrs = CDRMaskStore(cdr_path)
    candidate_table = resolve_path(root, args.candidate_table)
    candidates = load_candidate_override(resolve_path(root, args.candidates), candidate_table, args.limit) if args.candidates else load_default_candidates(resolve_path(root, args.v2_2_top50), candidate_table, args.limit)
    target_seq = read_fasta(resolve_path(root, args.target_fasta))
    validate_candidate_identity(candidates, target_seq)
    control_hashes = _load_control_hashes(resolve_path(root, args.pvrig_controls_csv)) if args.pvrig_controls_csv else set()
    kept, excluded = split_exclusions(candidates, control_hashes)
    validate_cache_and_masks(kept, target_seq, cache, cdrs)
    out = score_candidates(model, cfg, cache, cdrs, kept, target_seq, device, batch_size=args.batch_size)
    if not out.empty:
        out["phase2_v2_4_seed"] = int(cfg.seed)
        out["phase2_v2_4_checkpoint_epoch"] = int(ckpt.get("epoch", -1))
        out["phase2_v2_4_checkpoint_best_score"] = float(ckpt.get("best_score", 0.0))
        out["phase2_v2_4_run_id"] = clean(ckpt.get("run_id"))
    output = resolve_path(root, args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False, quoting=csv.QUOTE_MINIMAL)
    excluded_path = write_exclusions(excluded, output)
    meta = {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "boundary_note": BOUNDARY_NOTE,
        "calibration": {"status": CALIBRATION_STATUS, "reason": "candidate scoring has no verified positive-and-negative probability labels"},
        "checkpoint": str(checkpoint),
        "checkpoint_epoch": int(ckpt.get("epoch", -1)),
        "best_score": float(ckpt.get("best_score", 0.0)),
        "cache_manifest": str(cache_path),
        "cdr_mask_csv": str(cdr_path),
        "target_fasta": str(resolve_path(root, args.target_fasta)),
        "target_sequence_sha256": seq_hash(target_seq),
        "input_candidates": int(len(candidates)),
        "ranked_candidates": int(len(out)),
        "excluded_candidates": int(len(excluded)),
        "output": str(output),
        "excluded_output": str(excluded_path) if excluded_path else "",
        "device": str(device),
    }
    meta_path = output.with_suffix(".metadata.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    meta["metadata"] = str(meta_path)
    return meta


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--v2-2-top50", default=str(DEFAULT_V2_2_TOP50))
    parser.add_argument("--candidate-table", default=str(DEFAULT_CANDIDATES))
    parser.add_argument("--candidates", default="")
    parser.add_argument("--target-fasta", default=str(DEFAULT_TARGET_FASTA))
    parser.add_argument("--esm2-cache-manifest", default="")
    parser.add_argument("--cdr-mask-csv", default="")
    parser.add_argument("--pvrig-controls-csv", default=str(DEFAULT_CONTROLS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    print(json.dumps(run_scoring(parse_args(argv)), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
