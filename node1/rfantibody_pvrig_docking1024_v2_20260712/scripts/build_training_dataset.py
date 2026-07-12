#!/usr/bin/env python3
"""Build the final PVRIG RFantibody training dataset tables.

The builder is intentionally partial-tolerant: it keeps every candidate row,
records missing/deferred signals explicitly, and only enforces completion gates
when --mode final is requested.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "pvrig_training_dataset_v1"
MIN_FINAL_COMPLETED_DOCKING = 1000
KNOWN_POSITIVE_SPLIT = "calibration_holdout"
TRAIN_SPLIT = "train"
VALID_SPLITS = (TRAIN_SPLIT, "validation", "test", KNOWN_POSITIVE_SPLIT, "deferred")
MISSING = "missing"
DEFERRED = "deferred"
UNKNOWN = "unknown"
VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")

KEY_ALIASES = {
    "candidate_id": ("candidate_id", "design_id", "id", "name"),
    "sequence": ("sequence", "vh_sequence", "vhh_sequence", "aa_sequence"),
    "arm_id": ("arm_id", "generation_arm", "arm"),
    "backbone_group_id": ("backbone_group_id", "backbone_id", "backbone", "bb_group"),
    "sequence_group_id": ("sequence_group_id", "sequence_sha256", "seq_group", "near_sequence_family"),
    "scaffold_id": ("scaffold_id", "scaffold"),
    "h3_regime": ("h3_regime", "cdr3_regime"),
    "cdr3": ("cdr3", "CDR3", "imgt_cdr3", "IMGT_CDR3"),
    "known_positive": ("known_positive", "exact_known_positive_match", "is_known_positive", "leakage_known_positive"),
}

NUMERIC_ALIASES = {
    "rf2_recovery_rmsd": (
        "rf2_recovery_rmsd", "target_aligned_antibody_rmsd",
        "best_target_aligned_antibody_rmsd", "recovery_rmsd", "rf2_rmsd", "rmsd",
    ),
    "rf2_plddt": ("rf2_plddt", "pred_lddt", "best_pred_lddt", "plddt", "mean_plddt"),
    "monomer_qc_score": ("monomer_qc_score", "nbb2_qc_score", "qc_score"),
    "monomer_clash_score": ("monomer_clash_score", "clash_score", "nbb2_clash_score"),
    "baseline_affinity_proxy": ("baseline_affinity_proxy", "affinity_proxy", "ddg_proxy", "score"),
    "baseline_blocker_geometry": ("baseline_blocker_geometry", "blocker_geometry", "epitope_overlap", "hotspot_overlap"),
}

HADDOCK_PATTERNS = {
    "haddock_score": re.compile(r"(?:HADDOCK\s+)?score\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.I),
    "vdw_energy": re.compile(r"(?:vdw|van\s+der\s+waals)\s*(?:energy)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.I),
    "electrostatic_energy": re.compile(r"(?:elec|electrostatic)\s*(?:energy)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.I),
    "desolvation_energy": re.compile(r"(?:desolv|desolvation)\s*(?:energy)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.I),
    "air_energy": re.compile(r"(?:air|restraint)\s*(?:energy)?\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.I),
    "buried_surface_area": re.compile(r"(?:bsa|buried\s+surface\s+area)\s*[:=]?\s*(-?\d+(?:\.\d+)?)", re.I),
}

OUTPUT_FILES = (
    "candidates.tsv",
    "rf2_metrics.tsv",
    "monomer_qc.tsv",
    "docking_runs.tsv",
    "docking_pose_features.tsv",
    "candidate_summary.tsv",
    "splits_by_backbone.tsv",
    "failures.tsv",
    "dataset_manifest.json",
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ";".join(str(item) for item in value)
    return str(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pick(row: dict[str, str], aliases: Iterable[str], default: str = "") -> str:
    lower = {key.lower(): value for key, value in row.items()}
    for key in aliases:
        if key in row and row[key] not in (None, ""):
            return str(row[key])
        if key.lower() in lower and lower[key.lower()] not in (None, ""):
            return str(lower[key.lower()])
    return default


def parse_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "known_positive", "positive"}


def parse_fasta(path: Path) -> dict[str, list[str]]:
    references: dict[str, list[str]] = defaultdict(list)
    if not path.is_file():
        return references
    name = ""
    chunks: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name and chunks:
                references["".join(chunks).upper()].append(name)
            name, chunks = line[1:], []
        else:
            chunks.append(line.replace(" ", ""))
    if name and chunks:
        references["".join(chunks).upper()].append(name)
    return references


def normalize_candidates(rows: list[dict[str, str]], known_fasta: Path) -> list[dict[str, object]]:
    references = parse_fasta(known_fasta)
    normalized: list[dict[str, object]] = []
    seen_ids: Counter[str] = Counter()
    seen_sequences: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        candidate_id = pick(row, KEY_ALIASES["candidate_id"], f"candidate_{index:05d}")
        sequence = pick(row, KEY_ALIASES["sequence"]).upper()
        sequence_hash = hashlib.sha256(sequence.encode()).hexdigest() if sequence else ""
        if not sequence:
            raise ValueError(f"candidate {candidate_id} has an empty sequence")
        if set(sequence) - VALID_AA:
            raise ValueError(f"candidate {candidate_id} contains noncanonical amino acids")
        seen_ids[candidate_id] += 1
        seen_sequences[sequence_hash] += 1
        exact_matches = references.get(sequence, [])
        known_positive = truthy(pick(row, KEY_ALIASES["known_positive"])) or bool(exact_matches)
        normalized.append(
            {
                "candidate_id": candidate_id,
                "source_candidate_id": pick(row, KEY_ALIASES["candidate_id"], candidate_id),
                "sequence": sequence,
                "sequence_sha256": sequence_hash,
                "arm_id": pick(row, KEY_ALIASES["arm_id"], UNKNOWN),
                "backbone_group_id": pick(row, KEY_ALIASES["backbone_group_id"], f"unknown_backbone_{index:05d}"),
                "exact_sequence_group_id": pick(row, KEY_ALIASES["sequence_group_id"], sequence_hash),
                "sequence_group_id": sequence_hash,
                "cdr3": pick(row, KEY_ALIASES["cdr3"]).upper(),
                "scaffold_id": pick(row, KEY_ALIASES["scaffold_id"], UNKNOWN),
                "h3_regime": pick(row, KEY_ALIASES["h3_regime"], UNKNOWN),
                "known_positive": known_positive,
                "known_positive_ids": ";".join(exact_matches),
                "source_status": pick(row, ("status", "candidate_status"), "candidate"),
            }
        )
    duplicate_ids = [value for value, count in seen_ids.items() if count > 1]
    duplicate_sequences = [value for value, count in seen_sequences.items() if count > 1]
    if duplicate_ids:
        raise ValueError(f"candidate_id values are not unique: {duplicate_ids[:5]}")
    if duplicate_sequences:
        raise ValueError(f"candidate sequences are not exact-unique: {len(duplicate_sequences)} duplicate groups")
    assign_near_sequence_families(normalized)
    return normalized


def assign_near_sequence_families(candidates: list[dict[str, object]], threshold: float = 0.80) -> None:
    """Cluster near CDR3 neighbours so they cannot cross dataset splits."""
    parent = list(range(len(candidates)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for left in range(len(candidates)):
        cdr_left = str(candidates[left].get("cdr3") or "")
        if not cdr_left:
            continue
        for right in range(left + 1, len(candidates)):
            cdr_right = str(candidates[right].get("cdr3") or "")
            if not cdr_right or abs(len(cdr_left) - len(cdr_right)) > 2:
                continue
            if SequenceMatcher(None, cdr_left, cdr_right, autojunk=False).ratio() >= threshold:
                union(left, right)

    members: defaultdict[int, list[int]] = defaultdict(list)
    for index in range(len(candidates)):
        members[find(index)].append(index)
    for indices in members.values():
        signature = "|".join(sorted(str(candidates[index].get("cdr3") or candidates[index]["sequence_sha256"]) for index in indices))
        family_id = "cdr3fam_" + hashlib.sha256(signature.encode()).hexdigest()[:16]
        for index in indices:
            candidates[index]["sequence_group_id"] = family_id
            candidates[index]["near_sequence_family_size"] = len(indices)


def index_by_candidate(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = pick(row, KEY_ALIASES["candidate_id"])
        if candidate_id and candidate_id not in indexed:
            indexed[candidate_id] = row
    return indexed


def metric_value(row: dict[str, str] | None, key: str) -> float | None:
    if row is None:
        return None
    return parse_float(pick(row, NUMERIC_ALIASES[key]))


def status_from(value: float | None, present: bool) -> str:
    if value is not None:
        return "present"
    return MISSING if not present else "unparsed"


def read_model_lines(path: Path) -> list[str]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def parse_haddock_remarks(path: Path) -> dict[str, object]:
    features: dict[str, object] = {key: "" for key in HADDOCK_PATTERNS}
    remark_count = 0
    energy_header: list[str] = []
    for raw in read_model_lines(path):
        if not raw.startswith("REMARK"):
            continue
        remark_count += 1
        text = raw[6:].strip()
        if "total,bonds,angles,improper,dihe,vdw,elec,air" in text.replace(" ", "").lower():
            energy_header = [item.strip().lower() for item in text.split(",")]
            continue
        if text.lower().startswith("energies:") and energy_header:
            try:
                values = [float(item.strip()) for item in text.split(":", 1)[1].split(",")]
            except ValueError:
                values = []
            if len(values) == len(energy_header):
                mapping = dict(zip(energy_header, values))
                features["vdw_energy"] = mapping.get("vdw", "")
                features["electrostatic_energy"] = mapping.get("elec", "")
                features["air_energy"] = mapping.get("air", "")
        for key, pattern in HADDOCK_PATTERNS.items():
            if features[key] != "":
                continue
            match = pattern.search(text)
            if match:
                features[key] = match.group(1)
    features["remark_count"] = remark_count
    features["haddock_remark_parse_status"] = "parsed" if any(features[key] != "" for key in HADDOCK_PATTERNS) else "no_score_remark"
    return features


def infer_candidate_id(path: Path, candidate_ids: set[str]) -> str:
    text = "/".join(path.parts)
    matches = [candidate_id for candidate_id in candidate_ids if candidate_id in text]
    if matches:
        return sorted(matches, key=len, reverse=True)[0]
    for part in reversed(path.parts):
        stem = Path(part).stem
        if stem in candidate_ids:
            return stem
    return ""


def collect_docking_pose_features(docking_root: Path, candidate_ids: set[str]) -> list[dict[str, object]]:
    if not docking_root or not docking_root.exists():
        return []
    rows: list[dict[str, object]] = []
    pdbs = list(docking_root.rglob("cluster_*_model_*.pdb"))
    pdbs.extend(docking_root.rglob("cluster_*_model_*.pdb.gz"))
    for pdb in sorted(pdbs):
        if "6_seletopclusts" not in pdb.parts:
            continue
        candidate_id = infer_candidate_id(pdb, candidate_ids)
        if not candidate_id:
            continue
        features = parse_haddock_remarks(pdb)
        rows.append(
            {
                "candidate_id": candidate_id,
                "model_path": str(pdb),
                "model_sha256": sha256_file(pdb),
                "selected_model": True,
                **features,
            }
        )
    return rows


def docking_runs_from_features(features: list[dict[str, object]], explicit_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for row in explicit_rows:
        candidate_id = pick(row, KEY_ALIASES["candidate_id"])
        if not candidate_id:
            continue
        status = pick(row, ("docking_status", "status", "state"), UNKNOWN)
        rows[candidate_id] = {
            "candidate_id": candidate_id,
            "docking_status": status,
            "run_id": pick(row, ("run_id", "docking_run_id")),
            "selected_model_path": pick(row, ("selected_model_path", "model_path", "pdb_path")),
            "missingness_reason": "",
        }
    by_candidate: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for feature in features:
        by_candidate[str(feature["candidate_id"])].append(feature)
    for candidate_id, models in by_candidate.items():
        scored = [model for model in models if parse_float(model.get("haddock_score")) is not None]
        best = min(scored, key=lambda model: parse_float(model.get("haddock_score")) or 0.0) if scored else models[0]
        rows[candidate_id] = {
            "candidate_id": candidate_id,
            "docking_status": "completed" if scored else "completed_unscored",
            "run_id": rows.get(candidate_id, {}).get("run_id", ""),
            "selected_model_path": best.get("model_path", ""),
            "missingness_reason": "" if scored else "haddock_score_remark_missing",
        }
    return [rows[key] for key in sorted(rows)]


def split_tokens(candidate: dict[str, object]) -> tuple[str, str, str]:
    return (
        f"backbone:{candidate['backbone_group_id']}",
        f"arm:{candidate['arm_id']}",
        f"sequence_family:{candidate['sequence_group_id']}",
    )


def assign_splits(candidates: list[dict[str, object]]) -> dict[str, str]:
    # Union by all leakage keys so any shared backbone, arm, or near-sequence family stays in one split.
    parent: dict[str, str] = {}

    def find(token: str) -> str:
        parent.setdefault(token, token)
        if parent[token] != token:
            parent[token] = find(parent[token])
        return parent[token]

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    candidate_tokens: dict[str, tuple[str, str, str]] = {}
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        tokens = split_tokens(candidate)
        candidate_tokens[cid] = tokens
        union(tokens[0], tokens[1])
        union(tokens[0], tokens[2])

    groups: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for candidate in candidates:
        groups[find(candidate_tokens[str(candidate["candidate_id"])][0])].append(candidate)

    assignments: dict[str, str] = {}
    split_cycle = (TRAIN_SPLIT, TRAIN_SPLIT, TRAIN_SPLIT, TRAIN_SPLIT, TRAIN_SPLIT, TRAIN_SPLIT, TRAIN_SPLIT, "validation", "test", TRAIN_SPLIT)
    for index, key in enumerate(sorted(groups)):
        group_split = split_cycle[index % len(split_cycle)]
        if any(bool(candidate["known_positive"]) for candidate in groups[key]):
            group_split = KNOWN_POSITIVE_SPLIT
        for candidate in groups[key]:
            assignments[str(candidate["candidate_id"])] = group_split
    return assignments


def build_tables(args: argparse.Namespace) -> dict[str, object]:
    input_candidates = read_tsv(args.candidates)
    if not input_candidates:
        raise ValueError(f"candidate table is required and empty/missing: {args.candidates}")
    candidates = normalize_candidates(input_candidates, args.known_positives)
    candidate_ids = {str(row["candidate_id"]) for row in candidates}

    rf2_raw = read_tsv(args.rf2_metrics)
    qc_raw = read_tsv(args.monomer_qc)
    baseline_raw = read_tsv(args.baseline_postprocess)
    docking_explicit = read_tsv(args.docking_runs)
    rf2_by_id = index_by_candidate(rf2_raw)
    qc_by_id = index_by_candidate(qc_raw)
    baseline_by_id = index_by_candidate(baseline_raw)
    pose_features = collect_docking_pose_features(args.haddock_root, candidate_ids)
    docking_runs = docking_runs_from_features(pose_features, docking_explicit)
    docking_by_id = {str(row["candidate_id"]): row for row in docking_runs}
    features_by_id: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in pose_features:
        features_by_id[str(row["candidate_id"])].append(row)

    rf2_completed_ids = {
        pick(row, KEY_ALIASES["candidate_id"])
        for row in rf2_raw
        if pick(row, KEY_ALIASES["candidate_id"])
        and not pick(row, ("rf2_status", "status"), "").startswith("RF2_FAILED")
        and (
            pick(row, ("rf2_status", "status"), "")
            or pick(row, ("pred_lddt", "rf2_plddt", "plddt"), "")
        )
    }
    nbb2_success_ids = {
        pick(row, KEY_ALIASES["candidate_id"])
        for row in qc_raw
        if pick(row, KEY_ALIASES["candidate_id"])
        and (
            pick(row, ("nbb2_status", "status"), "") == "success"
            or parse_float(pick(row, ("monomer_qc_score", "nbb2_qc_score"), "")) == 1.0
        )
    }
    for source_name, source_ids in (
        ("rf2", {pick(row, KEY_ALIASES["candidate_id"]) for row in rf2_raw if pick(row, KEY_ALIASES["candidate_id"])}),
        ("monomer_qc", {pick(row, KEY_ALIASES["candidate_id"]) for row in qc_raw if pick(row, KEY_ALIASES["candidate_id"])}),
        ("docking", {pick(row, KEY_ALIASES["candidate_id"]) for row in docking_explicit if pick(row, KEY_ALIASES["candidate_id"])}),
    ):
        unknown_ids = sorted(source_ids - candidate_ids)
        if unknown_ids:
            raise ValueError(f"{source_name} table contains candidate IDs outside the frozen cohort: {unknown_ids[:5]}")

    split_assignments = assign_splits(candidates)
    failures: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        rf2 = rf2_by_id.get(cid)
        qc = qc_by_id.get(cid)
        baseline = baseline_by_id.get(cid)
        docking = docking_by_id.get(cid)
        best_pose = best_pose_for(features_by_id.get(cid, []))
        rf2_recovery = metric_value(rf2, "rf2_recovery_rmsd")
        rf2_plddt = metric_value(rf2, "rf2_plddt")
        monomer_qc = metric_value(qc, "monomer_qc_score")
        affinity_proxy = metric_value(baseline, "baseline_affinity_proxy")
        blocker_geometry = metric_value(baseline, "baseline_blocker_geometry")
        pose_quality = parse_float(best_pose.get("haddock_score")) if best_pose else None
        split = split_assignments[cid]
        row = {
            **candidate,
            "split": split,
            "binder_axis_status": DEFERRED,
            "binder_label": "calibration_positive" if candidate["known_positive"] else UNKNOWN,
            "pose_quality_status": status_from(pose_quality, bool(best_pose)),
            "pose_quality_haddock_score": pose_quality,
            "affinity_proxy_status": status_from(affinity_proxy, baseline is not None),
            "affinity_proxy_score": affinity_proxy,
            "blocker_geometry_status": status_from(blocker_geometry, baseline is not None),
            "blocker_geometry_score": blocker_geometry,
            "rf2_recovery_status": status_from(rf2_recovery, rf2 is not None),
            "rf2_recovery_rmsd": rf2_recovery,
            "rf2_plddt": rf2_plddt,
            "monomer_qc_status": status_from(monomer_qc, qc is not None),
            "monomer_qc_score": monomer_qc,
            "docking_status": str(docking.get("docking_status")) if docking else MISSING,
            "selected_model_path": str(docking.get("selected_model_path")) if docking else "",
            "training_eligible": split == TRAIN_SPLIT and not candidate["known_positive"] and str(docking.get("docking_status", "")) == "completed" if docking else False,
        }
        summaries.append(row)
        add_missing_failures(failures, row, rf2, qc, baseline, docking, best_pose)

    split_rows = build_split_rows(candidates, split_assignments)
    rf2_rows = normalize_rf2_rows(candidates, rf2_raw)
    qc_rows = normalize_metric_rows(candidates, qc_by_id, ["monomer_qc_score", "monomer_clash_score"], "monomer_qc")

    completed_docking = sum(1 for row in summaries if row["docking_status"] == "completed")
    if args.mode == "final":
        final_errors = []
        if len(candidates) != 1024:
            final_errors.append(f"frozen candidate count {len(candidates)} != 1024")
        if len(rf2_completed_ids) < 1000:
            final_errors.append(f"completed RF2 candidates {len(rf2_completed_ids)} < 1000")
        if len(nbb2_success_ids) < 1000:
            final_errors.append(f"successful NBB2 candidates {len(nbb2_success_ids)} < 1000")
        if completed_docking < MIN_FINAL_COMPLETED_DOCKING:
            final_errors.append(f"completed docking candidates {completed_docking} < {MIN_FINAL_COMPLETED_DOCKING}")
        leaked = [row["candidate_id"] for row in summaries if row["known_positive"] and row["split"] == TRAIN_SPLIT]
        if leaked:
            final_errors.append(f"known positives assigned to train: {len(leaked)}")
        if final_errors:
            raise ValueError("final dataset gate failed: " + "; ".join(final_errors))

    output_tables = {
        "candidates.tsv": candidates,
        "rf2_metrics.tsv": rf2_rows,
        "monomer_qc.tsv": qc_rows,
        "docking_runs.tsv": complete_docking_runs(candidates, docking_by_id),
        "docking_pose_features.tsv": pose_features,
        "candidate_summary.tsv": summaries,
        "splits_by_backbone.tsv": split_rows,
        "failures.tsv": failures,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "source_files": source_manifest(args),
        "output_files": {},
        "candidate_count": len(candidates),
        "completed_docking_candidates": completed_docking,
        "completed_rf2_candidates": len(rf2_completed_ids),
        "successful_nbb2_candidates": len(nbb2_success_ids),
        "known_positive_count": sum(1 for row in candidates if row["known_positive"]),
        "split_counts": dict(sorted(Counter(split_assignments.values()).items())),
        "missingness_counts": dict(sorted(Counter(row["failure_type"] for row in failures).items())),
        "axis_contract": {
            "binder": "binder_label is never inferred from pose, affinity, blocker geometry, or RF2 recovery",
            "pose_quality": "pose_quality_haddock_score is parsed from HADDOCK raw PDB REMARK lines",
            "affinity_proxy": "baseline postprocess proxy kept separate from binder labels",
            "blocker_geometry": "hotspot/interface geometry proxy kept separate from affinity and binder axes",
            "rf2_recovery": "RF2 recovery metrics kept separate from docking and blocker axes",
        },
        "final_gate": {
            "required_candidate_count": 1024,
            "min_completed_rf2_candidates": 1000,
            "min_successful_nbb2_candidates": 1000,
            "min_completed_docking_candidates": MIN_FINAL_COMPLETED_DOCKING,
        },
    }
    return {"tables": output_tables, "manifest": manifest}


def best_pose_for(rows: list[dict[str, object]]) -> dict[str, object]:
    scored = [row for row in rows if parse_float(row.get("haddock_score")) is not None]
    if scored:
        return min(scored, key=lambda row: parse_float(row.get("haddock_score")) or 0.0)
    return rows[0] if rows else {}


def add_missing_failures(failures: list[dict[str, object]], summary: dict[str, object], rf2: object, qc: object, baseline: object, docking: object, pose: object) -> None:
    checks = [
        (rf2 is None, "missing_rf2_metrics", "RF2 recovery axis absent"),
        (qc is None, "missing_monomer_qc", "NBB2/monomer QC axis absent"),
        (baseline is None, "missing_baseline_postprocess", "affinity/blocker proxy axes absent"),
        (docking is None, "missing_docking_run", "HADDOCK run absent"),
        (not pose, "missing_docking_pose_features", "selected/raw HADDOCK PDB features absent"),
        (summary["known_positive"] and summary["split"] != KNOWN_POSITIVE_SPLIT, "known_positive_split_violation", "known positives must be calibration/holdout only"),
    ]
    for failed, failure_type, message in checks:
        if failed:
            failures.append(
                {
                    "candidate_id": summary["candidate_id"],
                    "failure_type": failure_type,
                    "severity": "deferred" if failure_type.startswith("missing_") else "error",
                    "message": message,
                }
            )


def build_split_rows(candidates: list[dict[str, object]], assignments: dict[str, str]) -> list[dict[str, object]]:
    grouped: defaultdict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for candidate in candidates:
        split = assignments[str(candidate["candidate_id"])]
        grouped[(str(candidate["backbone_group_id"]), str(candidate["arm_id"]), str(candidate["sequence_group_id"]), split)].append(str(candidate["candidate_id"]))
    return [
        {
            "backbone_group_id": key[0],
            "arm_id": key[1],
            "sequence_group_id": key[2],
            "split": key[3],
            "candidate_count": len(ids),
            "candidate_ids": ";".join(sorted(ids)),
        }
        for key, ids in sorted(grouped.items())
    ]


def normalize_metric_rows(candidates: list[dict[str, object]], raw_by_id: dict[str, dict[str, str]], fields: list[str], source: str) -> list[dict[str, object]]:
    rows = []
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        raw = raw_by_id.get(cid)
        row: dict[str, object] = {"candidate_id": cid, "source_table": source, "status": "present" if raw else MISSING}
        for field in fields:
            row[field] = metric_value(raw, field) if raw else ""
        rows.append(row)
    return rows


def normalize_rf2_rows(candidates: list[dict[str, object]], raw_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    candidate_ids = {str(candidate["candidate_id"]) for candidate in candidates}
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        candidate_id = pick(raw, KEY_ALIASES["candidate_id"])
        if candidate_id not in candidate_ids:
            continue
        seen.add(candidate_id)
        rows.append({"source_table": "rf2_metrics", "status": "present", **raw, "candidate_id": candidate_id})
    for candidate_id in sorted(candidate_ids - seen):
        rows.append(
            {
                "candidate_id": candidate_id,
                "source_table": "rf2_metrics",
                "status": MISSING,
                "rf2_status": MISSING,
                "rf2_failure_label_policy": "missing_is_not_a_negative_sample",
            }
        )
    return rows


def complete_docking_runs(candidates: list[dict[str, object]], docking_by_id: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        if cid in docking_by_id:
            rows.append(docking_by_id[cid])
        else:
            rows.append({"candidate_id": cid, "docking_status": MISSING, "run_id": "", "selected_model_path": "", "missingness_reason": "docking_not_run_or_not_found"})
    return rows


def source_manifest(args: argparse.Namespace) -> dict[str, dict[str, object]]:
    paths = {
        "candidates": args.candidates,
        "rf2_metrics": args.rf2_metrics,
        "monomer_qc": args.monomer_qc,
        "docking_runs": args.docking_runs,
        "baseline_postprocess": args.baseline_postprocess,
        "known_positives": args.known_positives,
    }
    manifest = {}
    for name, path in paths.items():
        manifest[name] = {"path": str(path), "exists": path.is_file(), "sha256": sha256_file(path) if path.is_file() else ""}
    manifest["haddock_root"] = {"path": str(args.haddock_root), "exists": args.haddock_root.exists()}
    return manifest


def write_outputs(output_dir: Path, payload: dict[str, object]) -> None:
    tables: dict[str, list[dict[str, object]]] = payload["tables"]  # type: ignore[assignment]
    field_order = {
        "candidates.tsv": ["candidate_id", "source_candidate_id", "sequence", "sequence_sha256", "cdr3", "arm_id", "backbone_group_id", "exact_sequence_group_id", "sequence_group_id", "near_sequence_family_size", "scaffold_id", "h3_regime", "known_positive", "known_positive_ids", "source_status"],
        "rf2_metrics.tsv": ["candidate_id", "seed", "gpu_id", "source_table", "status", "rf2_status", "rf2_reason", "old_gate_status", "formal_multiseed_gate_status", "interaction_pae", "pred_lddt", "pae", "target_aligned_antibody_rmsd", "target_aligned_cdr_rmsd", "framework_aligned_antibody_rmsd", "framework_aligned_cdr_rmsd", "rf2_output_pdb", "rf2_failure_label_policy"],
        "monomer_qc.tsv": ["candidate_id", "source_table", "status", "monomer_qc_score", "monomer_clash_score"],
        "docking_runs.tsv": ["candidate_id", "docking_status", "run_id", "selected_model_path", "missingness_reason"],
        "docking_pose_features.tsv": ["candidate_id", "model_path", "model_sha256", "selected_model", "haddock_score", "vdw_energy", "electrostatic_energy", "desolvation_energy", "air_energy", "buried_surface_area", "remark_count", "haddock_remark_parse_status"],
        "candidate_summary.tsv": ["candidate_id", "sequence_sha256", "arm_id", "backbone_group_id", "sequence_group_id", "known_positive", "known_positive_ids", "split", "binder_axis_status", "binder_label", "pose_quality_status", "pose_quality_haddock_score", "affinity_proxy_status", "affinity_proxy_score", "blocker_geometry_status", "blocker_geometry_score", "rf2_recovery_status", "rf2_recovery_rmsd", "rf2_plddt", "monomer_qc_status", "monomer_qc_score", "docking_status", "selected_model_path", "training_eligible"],
        "splits_by_backbone.tsv": ["backbone_group_id", "arm_id", "sequence_group_id", "split", "candidate_count", "candidate_ids"],
        "failures.tsv": ["candidate_id", "failure_type", "severity", "message"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_FILES:
        if name == "dataset_manifest.json":
            continue
        write_tsv(output_dir / name, tables[name], field_order[name])
    manifest: dict[str, object] = payload["manifest"]  # type: ignore[assignment]
    output_file_manifest = {}
    for name in OUTPUT_FILES:
        if name == "dataset_manifest.json":
            continue
        path = output_dir / name
        output_file_manifest[name] = {"path": str(path), "sha256": sha256_file(path), "rows": len(tables[name])}
    manifest["output_files"] = output_file_manifest
    (output_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def default_path(root: Path, *names: str) -> Path:
    for name in names:
        path = root / name
        if path.exists():
            return path
    return root / names[0]


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/training_dataset"))
    parser.add_argument("--mode", choices=("partial", "final"), default="partial")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--rf2-metrics", type=Path)
    parser.add_argument("--monomer-qc", type=Path)
    parser.add_argument("--docking-runs", type=Path)
    parser.add_argument("--haddock-root", type=Path)
    parser.add_argument("--baseline-postprocess", type=Path)
    parser.add_argument("--known-positives", type=Path, default=Path("inputs/leakage_reference.fasta"))
    args = parser.parse_args()
    args.candidates = args.candidates or default_path(args.input_dir, "candidates.tsv")
    args.rf2_metrics = args.rf2_metrics or default_path(args.input_dir, "rf2_metrics.tsv")
    args.monomer_qc = args.monomer_qc or default_path(args.input_dir, "monomer_qc.tsv", "nbb2_qc.tsv")
    args.docking_runs = args.docking_runs or default_path(args.input_dir, "docking_runs.tsv")
    if args.haddock_root is None:
        input_haddock = default_path(args.input_dir, "haddock_runs", "docking_runs_raw")
        args.haddock_root = input_haddock if input_haddock.exists() else project_root / "docking" / "haddock"
    args.baseline_postprocess = args.baseline_postprocess or default_path(args.input_dir, "baseline_postprocess.tsv", "dual_baseline_postprocess.tsv")
    return args


def main() -> int:
    args = parse_args()
    payload = build_tables(args)
    write_outputs(args.output_dir, payload)
    manifest = payload["manifest"]
    print(json.dumps({"schema_version": SCHEMA_VERSION, "mode": args.mode, "output_dir": str(args.output_dir), "candidate_count": manifest["candidate_count"], "completed_docking_candidates": manifest["completed_docking_candidates"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
