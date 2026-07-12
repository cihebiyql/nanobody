#!/usr/bin/env python3
"""Build the auditable PVRIG docking-teacher v1 calibration replay.

The builder consumes existing 8X6B/9E6Y calibration outputs. It preserves
pose-level evidence, aggregates candidate-level stability, and extracts soft
PVRIG-VHH residue-contact frequencies from the aligned 8X6B pose files.
Docking-derived labels remain computational geometry proxies, not binding or
blocking ground truth.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_POSITIVE_ROOT = WORKSPACE_ROOT / "docking/calibration/patent_success_validation"
DEFAULT_MUTANT_ROOT = WORKSPACE_ROOT / "docking/calibration/mutant_validation_panel"
DEFAULT_PREPARED = EXP_DIR / "prepared/pvrig_teacher_v1"
DEFAULT_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_v1_manifest.csv"
DEFAULT_AUDIT_JSON = EXP_DIR / "audits/pvrig_teacher_v1_audit.json"
DEFAULT_AUDIT_MD = EXP_DIR / "audits/PVRIG_TEACHER_V1_AUDIT.md"

SCHEMA_VERSION = "pvrig_teacher_v1_calibration_replay"
CLAIM_BOUNDARY = "docking_geometry_surrogate_for_frontscreen_only_not_binding_or_blocker_proof"
BASELINES = ("8x6b", "9e6y")
CONSENSUS_RELEVANCE = {
    "CONSENSUS_BLOCKER_LIKE_A": 4,
    "SINGLE_BASELINE_BLOCKER_RECHECK": 3,
    "BLOCKER_PLAUSIBLE_B": 2,
    "EVIDENCE_INFERENCE_ONLY_E": 0,
}
RELEVANCE_WEIGHTS = {4: 1.0, 3: 0.85, 2: 0.65, 1: 0.35, 0: 0.15}
TIER_BY_RELEVANCE = {4: "G1", 3: "G2", 2: "G3", 1: "G4", 0: "G5"}
CLUSTER_RE = re.compile(r"cluster_(\d+)_model_\d+")

POSE_FIELDS = [
    "schema_version",
    "candidate_id",
    "candidate_name",
    "family",
    "calibration_role",
    "model",
    "cluster_id",
    "haddock_rank",
    "consensus_class",
    "pose_relevance",
    "pose_tier",
    "baseline_classes",
    "blocker_like_count",
    "plausible_count",
    "binder_like_count",
    "evidence_only_count",
    "class_8x6b",
    "hotspot_overlap_8x6b",
    "total_occlusion_8x6b",
    "cdr3_occlusion_8x6b",
    "cdr3_fraction_8x6b",
    "class_9e6y",
    "hotspot_overlap_9e6y",
    "total_occlusion_9e6y",
    "cdr3_occlusion_9e6y",
    "cdr3_fraction_9e6y",
    "pose_generation_receptor",
    "independent_9e6y_docking",
    "contact_pose_path",
    "contact_extraction_status",
    "contact_residue_pair_count",
    "claim_boundary",
]

CANDIDATE_FIELDS = [
    "schema_version",
    "candidate_id",
    "candidate_name",
    "family",
    "calibration_role",
    "calibration_only",
    "submission_eligible",
    "sequence",
    "sequence_sha256",
    "pose_count",
    "valid_baseline_pair_count",
    "topk_aa_fraction",
    "topk_single_a_fraction",
    "topk_plausible_b_fraction",
    "topk_c_fraction",
    "topk_e_fraction",
    "topk_a_or_b_fraction",
    "blocker_supporting_cluster_count",
    "aa_supporting_cluster_count",
    "pose_cluster_count",
    "pose_cluster_entropy",
    "median_hotspot_overlap_8x6b",
    "median_hotspot_overlap_9e6y",
    "median_total_occlusion_8x6b",
    "median_total_occlusion_9e6y",
    "median_cdr3_occlusion_8x6b",
    "median_cdr3_occlusion_9e6y",
    "median_cdr3_fraction_8x6b",
    "median_cdr3_fraction_9e6y",
    "teacher_relevance_mean",
    "teacher_relevance_median",
    "teacher_relevance_max",
    "best_pose_vs_median_gap",
    "best_evidence_tier",
    "provisional_stable_geometry_tier",
    "provisional_rule_status",
    "valid_contact_pose_count",
    "failed_contact_pose_count",
    "teacher_completeness",
    "pose_generation_receptor",
    "independent_9e6y_docking",
    "claim_boundary",
]

MANIFEST_FIELDS = [
    "schema_version",
    "candidate_id",
    "candidate_name",
    "family",
    "sequence",
    "sequence_sha256",
    "calibration_role",
    "calibration_only",
    "submission_eligible",
    "split",
    "parent_framework_cluster",
    "leakage_status",
    "workdir",
    "consensus_csv",
    "claim_boundary",
]


@dataclass(frozen=True)
class Atom:
    chain: str
    resseq: int
    icode: str
    resname: str
    x: float
    y: float
    z: float

    @property
    def residue_label(self) -> str:
        suffix = self.icode.strip()
        return f"{self.chain}:{self.resseq}{suffix}:{self.resname}"


@dataclass(frozen=True)
class Case:
    candidate_id: str
    candidate_name: str
    family: str
    sequence: str
    calibration_role: str
    workdir: Path
    consensus_csv: Path


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."} else text


def as_int(value: object, default: int = 0) -> int:
    text = clean(value)
    try:
        return int(float(text))
    except ValueError:
        return default


def as_float(value: object, default: float = 0.0) -> float:
    text = clean(value)
    try:
        return float(text)
    except ValueError:
        return default


def format_float(value: float | None, digits: int = 6) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_csv(path: Path, rows: Sequence[dict[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_single_fasta(path: Path) -> str:
    sequence: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            continue
        sequence.append(line.strip())
    return "".join(sequence).upper()


def find_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected one match under {root} for {pattern!r}; found {len(matches)}")
    return matches[0]


def discover_cases(positive_root: Path, mutant_root: Path) -> list[Case]:
    cases: list[Case] = []
    for row in read_csv(positive_root / "batch_manifest.csv"):
        candidate_id = clean(row["calibration_name"])
        workdir = positive_root / candidate_id
        sequence = read_single_fasta(find_one(workdir / "inputs", "*.fasta"))
        cases.append(
            Case(
                candidate_id=candidate_id,
                candidate_name=clean(row["molecule_name"]),
                family=clean(row["family"]),
                sequence=sequence,
                calibration_role="known_positive_calibration_only",
                workdir=workdir,
                consensus_csv=find_one(workdir / "reports", "*_8x6b_9e6y_consensus.csv"),
            )
        )
    for row in read_csv(mutant_root / "mutant_panel.csv"):
        candidate_id = clean(row["mutant_name"])
        workdir = mutant_root / "workdirs" / candidate_id
        role = (
            "known_positive_reference_calibration_only"
            if clean(row["control_type"]) == "base_reference"
            else "known_positive_derived_mutant_calibration_only"
        )
        cases.append(
            Case(
                candidate_id=candidate_id,
                candidate_name=candidate_id,
                family=clean(row["family"]),
                sequence=clean(row["sequence"]).upper(),
                calibration_role=role,
                workdir=workdir,
                consensus_csv=find_one(workdir / "reports", "*_8x6b_9e6y_consensus.csv"),
            )
        )
    ids = [case.candidate_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate calibration candidate_id values")
    return cases


def consensus_relevance(row: dict[str, str]) -> int:
    consensus_class = clean(row.get("consensus_class"))
    if consensus_class in CONSENSUS_RELEVANCE:
        return CONSENSUS_RELEVANCE[consensus_class]
    blocker = as_int(row.get("blocker_like_count"))
    plausible = as_int(row.get("plausible_count"))
    binder = as_int(row.get("binder_like_count"))
    if blocker >= 2:
        return 4
    if blocker == 1:
        return 3
    if plausible:
        return 2
    if binder or "BINDER" in consensus_class:
        return 1
    return 0


def cluster_id(model: str) -> str:
    match = CLUSTER_RE.fullmatch(model)
    return f"cluster_{match.group(1)}" if match else f"unparsed:{model}"


def median_field(rows: Sequence[dict[str, object]], field: str) -> float | None:
    values = [as_float(row.get(field)) for row in rows if clean(row.get(field))]
    return statistics.median(values) if values else None


def normalized_cluster_entropy(cluster_ids: Sequence[str]) -> float:
    counts = Counter(cluster_ids)
    if len(counts) <= 1:
        return 0.0
    total = sum(counts.values())
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    return entropy / math.log(len(counts))


def provisional_stable_tier(rows: Sequence[dict[str, object]], min_clusters: int) -> str:
    for relevance in (4, 3, 2, 1):
        supporting = {
            clean(row["cluster_id"])
            for row in rows
            if as_int(row["pose_relevance"]) >= relevance
        }
        if len(supporting) >= min_clusters:
            return TIER_BY_RELEVANCE[relevance]
    return "G5"


def parse_atom_line(line: str) -> Atom | None:
    if not (line.startswith("ATOM  ") or line.startswith("HETATM")):
        return None
    try:
        name = line[12:16].strip().upper()
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if not element:
            letters = "".join(char for char in name if char.isalpha())
            element = letters[:1]
        if element == "H" or name.startswith("H"):
            return None
        return Atom(
            chain=line[21].strip() or "_",
            resseq=int(line[22:26]),
            icode=line[26].strip(),
            resname=line[17:20].strip().upper(),
            x=float(line[30:38]),
            y=float(line[38:46]),
            z=float(line[46:54]),
        )
    except ValueError:
        return None


def parse_atoms(path: Path) -> list[Atom]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        return [atom for line in handle if (atom := parse_atom_line(line)) is not None]


def residue_contact_pairs(
    path: Path,
    vhh_chain: str,
    pvrig_chain: str,
    cutoff_a: float,
) -> set[tuple[str, str]]:
    atoms = parse_atoms(path)
    vhh = [atom for atom in atoms if atom.chain == vhh_chain]
    pvrig = [atom for atom in atoms if atom.chain == pvrig_chain]
    if not vhh or not pvrig:
        raise ValueError(f"Missing chains in {path}: vhh={len(vhh)} pvrig={len(pvrig)}")
    cell = cutoff_a
    grid: dict[tuple[int, int, int], list[Atom]] = defaultdict(list)
    for atom in pvrig:
        grid[(math.floor(atom.x / cell), math.floor(atom.y / cell), math.floor(atom.z / cell))].append(atom)
    cutoff_sq = cutoff_a * cutoff_a
    pairs: set[tuple[str, str]] = set()
    for va in vhh:
        origin = (math.floor(va.x / cell), math.floor(va.y / cell), math.floor(va.z / cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for pa in grid.get((origin[0] + dx, origin[1] + dy, origin[2] + dz), []):
                        distance_sq = (va.x - pa.x) ** 2 + (va.y - pa.y) ** 2 + (va.z - pa.z) ** 2
                        if distance_sq <= cutoff_sq:
                            pairs.add((va.residue_label, pa.residue_label))
    return pairs


def classification_rows(case: Case, baseline: str) -> dict[str, dict[str, str]]:
    path = find_one(case.workdir / "reports", f"*_{baseline}_blocker_classification.csv")
    return {clean(row["model"]): row for row in read_csv(path)}


def contact_source(case: Case, model: str) -> tuple[Path, str, str, float]:
    score_path = case.workdir / "reports/8x6b_baseline/per_model_scores" / f"{model}_8x6b_pose_score.csv"
    if not score_path.exists():
        raise FileNotFoundError(score_path)
    rows = read_csv(score_path)
    if len(rows) != 1:
        raise ValueError(f"Expected one score row: {score_path}")
    row = rows[0]
    pose_path = Path(clean(row["pose_pdb"]))
    if not pose_path.exists():
        # Recorded paths are absolute local paths, but keep replay relocatable.
        pose_path = case.workdir / "haddock3/top_models_aligned_to_8x6b" / f"{model}_aligned_to_8x6b.pdb"
    return pose_path, clean(row.get("vhh_chain")) or "A", clean(row.get("pvrig_chain")) or "B", as_float(row.get("contact_cutoff_a"), 4.5)


def build_case_pose_rows(case: Case, top_k: int, extract_contacts: bool) -> tuple[list[dict[str, object]], list[set[tuple[str, str]] | None]]:
    consensus = sorted(read_csv(case.consensus_csv), key=lambda row: as_int(row.get("best_haddock_rank"), 10**9))[:top_k]
    by_baseline = {baseline: classification_rows(case, baseline) for baseline in BASELINES}
    pose_rows: list[dict[str, object]] = []
    contacts: list[set[tuple[str, str]] | None] = []
    for row in consensus:
        model = clean(row["model"])
        baseline_rows = {baseline: by_baseline[baseline].get(model) for baseline in BASELINES}
        missing = [baseline for baseline, value in baseline_rows.items() if value is None]
        if missing:
            raise ValueError(f"{case.candidate_id} {model}: missing classifications {missing}")
        relevance = consensus_relevance(row)
        out: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": case.candidate_id,
            "candidate_name": case.candidate_name,
            "family": case.family,
            "calibration_role": case.calibration_role,
            "model": model,
            "cluster_id": cluster_id(model),
            "haddock_rank": clean(row.get("best_haddock_rank")),
            "consensus_class": clean(row.get("consensus_class")),
            "pose_relevance": relevance,
            "pose_tier": TIER_BY_RELEVANCE[relevance],
            "baseline_classes": clean(row.get("baseline_classes")),
            "blocker_like_count": clean(row.get("blocker_like_count")),
            "plausible_count": clean(row.get("plausible_count")),
            "binder_like_count": clean(row.get("binder_like_count")),
            "evidence_only_count": clean(row.get("evidence_only_count")),
            "pose_generation_receptor": "8X6B",
            "independent_9e6y_docking": "false",
            "claim_boundary": CLAIM_BOUNDARY,
        }
        for baseline, source in baseline_rows.items():
            assert source is not None
            out.update(
                {
                    f"class_{baseline}": clean(source.get("blocker_class")),
                    f"hotspot_overlap_{baseline}": clean(source.get("hotspot_overlap_count")),
                    f"total_occlusion_{baseline}": clean(source.get("total_vhh_pvrl2_residue_pair_occlusion")),
                    f"cdr3_occlusion_{baseline}": clean(source.get("cdr3_pvrl2_residue_pair_occlusion")),
                    f"cdr3_fraction_{baseline}": clean(source.get("cdr3_occlusion_fraction")),
                }
            )
        pair_set: set[tuple[str, str]] | None = None
        try:
            pose_path, vhh_chain, pvrig_chain, cutoff = contact_source(case, model)
            out["contact_pose_path"] = str(pose_path)
            if extract_contacts:
                pair_set = residue_contact_pairs(pose_path, vhh_chain, pvrig_chain, cutoff)
                out["contact_extraction_status"] = "ok"
                out["contact_residue_pair_count"] = len(pair_set)
            else:
                out["contact_extraction_status"] = "skipped_by_request"
                out["contact_residue_pair_count"] = ""
        except (FileNotFoundError, ValueError) as error:
            out["contact_pose_path"] = ""
            out["contact_extraction_status"] = f"failed:{type(error).__name__}:{error}"
            out["contact_residue_pair_count"] = ""
        pose_rows.append(out)
        contacts.append(pair_set)
    return pose_rows, contacts


def contact_frequency_record(
    case: Case,
    pose_rows: Sequence[dict[str, object]],
    contacts: Sequence[set[tuple[str, str]] | None],
) -> dict[str, object]:
    cluster_counts = Counter(clean(row["cluster_id"]) for row in pose_rows)
    pair_weights: defaultdict[tuple[str, str], float] = defaultdict(float)
    vhh_weights: defaultdict[str, float] = defaultdict(float)
    pvrig_weights: defaultdict[str, float] = defaultdict(float)
    total_weight = 0.0
    valid_poses = 0
    for row, pair_set in zip(pose_rows, contacts, strict=True):
        if pair_set is None:
            continue
        rank = max(1, as_int(row["haddock_rank"], 1))
        relevance = as_int(row["pose_relevance"])
        rank_weight = 1.0 / math.log2(rank + 1.0)
        cluster_weight = 1.0 / cluster_counts[clean(row["cluster_id"])]
        weight = rank_weight * cluster_weight * RELEVANCE_WEIGHTS[relevance]
        total_weight += weight
        valid_poses += 1
        vhh_seen: set[str] = set()
        pvrig_seen: set[str] = set()
        for vhh_residue, pvrig_residue in pair_set:
            pair_weights[(vhh_residue, pvrig_residue)] += weight
            vhh_seen.add(vhh_residue)
            pvrig_seen.add(pvrig_residue)
        for residue in vhh_seen:
            vhh_weights[residue] += weight
        for residue in pvrig_seen:
            pvrig_weights[residue] += weight

    def normalize(mapping: dict[object, float]) -> list[tuple[object, float]]:
        if total_weight <= 0:
            return []
        return sorted(((key, value / total_weight) for key, value in mapping.items()), key=lambda item: (-item[1], str(item[0])))

    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": case.candidate_id,
        "candidate_name": case.candidate_name,
        "family": case.family,
        "calibration_role": case.calibration_role,
        "top_k": len(pose_rows),
        "valid_contact_pose_count": valid_poses,
        "failed_contact_pose_count": len(pose_rows) - valid_poses,
        "pose_weight_sum": round(total_weight, 8),
        "weight_formula": "rank=1/log2(rank+1);cluster=1/n_cluster_poses;relevance={4:1,3:0.85,2:0.65,1:0.35,0:0.15}",
        "pair_frequencies": [
            {"vhh_residue": key[0], "pvrig_residue": key[1], "frequency": round(value, 8)}
            for key, value in normalize(pair_weights)
        ],
        "vhh_residue_frequencies": [
            {"residue": key, "frequency": round(value, 8)} for key, value in normalize(vhh_weights)
        ],
        "pvrig_residue_frequencies": [
            {"residue": key, "frequency": round(value, 8)} for key, value in normalize(pvrig_weights)
        ],
        "claim_boundary": CLAIM_BOUNDARY,
    }


def candidate_summary(case: Case, pose_rows: Sequence[dict[str, object]], contact_record: dict[str, object], min_clusters: int) -> dict[str, object]:
    count = len(pose_rows)
    relevance = [as_int(row["pose_relevance"]) for row in pose_rows]
    class_counts = Counter(clean(row["consensus_class"]) for row in pose_rows)
    c_count = sum(1 for value in relevance if value == 1)
    e_count = sum(1 for value in relevance if value == 0)
    blocker_clusters = {clean(row["cluster_id"]) for row in pose_rows if as_int(row["pose_relevance"]) >= 2}
    aa_clusters = {clean(row["cluster_id"]) for row in pose_rows if as_int(row["pose_relevance"]) == 4}
    valid_baselines = sum(
        bool(clean(row.get("class_8x6b"))) and bool(clean(row.get("class_9e6y"))) for row in pose_rows
    )
    valid_contacts = as_int(contact_record["valid_contact_pose_count"])
    median_relevance = statistics.median(relevance) if relevance else 0.0
    max_relevance = max(relevance, default=0)
    completeness = "COMPLETE" if valid_baselines == count and valid_contacts == count else "INCOMPLETE"
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": case.candidate_id,
        "candidate_name": case.candidate_name,
        "family": case.family,
        "calibration_role": case.calibration_role,
        "calibration_only": "true",
        "submission_eligible": "false",
        "sequence": case.sequence,
        "sequence_sha256": sha256_text(case.sequence),
        "pose_count": count,
        "valid_baseline_pair_count": valid_baselines,
        "topk_aa_fraction": format_float(class_counts["CONSENSUS_BLOCKER_LIKE_A"] / count if count else 0.0),
        "topk_single_a_fraction": format_float(class_counts["SINGLE_BASELINE_BLOCKER_RECHECK"] / count if count else 0.0),
        "topk_plausible_b_fraction": format_float(class_counts["BLOCKER_PLAUSIBLE_B"] / count if count else 0.0),
        "topk_c_fraction": format_float(c_count / count if count else 0.0),
        "topk_e_fraction": format_float(e_count / count if count else 0.0),
        "topk_a_or_b_fraction": format_float(sum(value >= 2 for value in relevance) / count if count else 0.0),
        "blocker_supporting_cluster_count": len(blocker_clusters),
        "aa_supporting_cluster_count": len(aa_clusters),
        "pose_cluster_count": len({clean(row["cluster_id"]) for row in pose_rows}),
        "pose_cluster_entropy": format_float(normalized_cluster_entropy([clean(row["cluster_id"]) for row in pose_rows])),
        "median_hotspot_overlap_8x6b": format_float(median_field(pose_rows, "hotspot_overlap_8x6b")),
        "median_hotspot_overlap_9e6y": format_float(median_field(pose_rows, "hotspot_overlap_9e6y")),
        "median_total_occlusion_8x6b": format_float(median_field(pose_rows, "total_occlusion_8x6b")),
        "median_total_occlusion_9e6y": format_float(median_field(pose_rows, "total_occlusion_9e6y")),
        "median_cdr3_occlusion_8x6b": format_float(median_field(pose_rows, "cdr3_occlusion_8x6b")),
        "median_cdr3_occlusion_9e6y": format_float(median_field(pose_rows, "cdr3_occlusion_9e6y")),
        "median_cdr3_fraction_8x6b": format_float(median_field(pose_rows, "cdr3_fraction_8x6b")),
        "median_cdr3_fraction_9e6y": format_float(median_field(pose_rows, "cdr3_fraction_9e6y")),
        "teacher_relevance_mean": format_float(statistics.mean(relevance) if relevance else 0.0),
        "teacher_relevance_median": format_float(median_relevance),
        "teacher_relevance_max": max_relevance,
        "best_pose_vs_median_gap": format_float(max_relevance - median_relevance),
        "best_evidence_tier": TIER_BY_RELEVANCE[max_relevance],
        "provisional_stable_geometry_tier": provisional_stable_tier(pose_rows, min_clusters),
        "provisional_rule_status": "PROVISIONAL_CALIBRATION_REPLAY_NOT_FROZEN_TRAINING_LABEL",
        "valid_contact_pose_count": valid_contacts,
        "failed_contact_pose_count": as_int(contact_record["failed_contact_pose_count"]),
        "teacher_completeness": completeness,
        "pose_generation_receptor": "8X6B",
        "independent_9e6y_docking": "false",
        "claim_boundary": CLAIM_BOUNDARY,
    }


def manifest_row(case: Case) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": case.candidate_id,
        "candidate_name": case.candidate_name,
        "family": case.family,
        "sequence": case.sequence,
        "sequence_sha256": sha256_text(case.sequence),
        "calibration_role": case.calibration_role,
        "calibration_only": "true",
        "submission_eligible": "false",
        "split": "calibration_only",
        "parent_framework_cluster": f"known_positive_family_{case.family}",
        "leakage_status": "KNOWN_POSITIVE_OR_DERIVATIVE_EXCLUDED_FROM_CANDIDATES",
        "workdir": str(case.workdir),
        "consensus_csv": str(case.consensus_csv),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")


def write_audit_markdown(path: Path, audit: dict[str, object]) -> None:
    pose_classes = audit["pose_consensus_class_counts"]
    lines = [
        "# PVRIG Teacher V1 Calibration Replay Audit",
        "",
        f"- Status: `{audit['status']}`",
        f"- Cases: `{audit['case_count']}` (`{audit['positive_case_count']}` positive, `{audit['mutant_control_case_count']}` mutant/control).",
        f"- Pose rows: `{audit['pose_count']}`.",
        f"- Contact extraction: `{audit['contact_pose_success_count']}/{audit['pose_count']}`.",
        f"- Complete candidate summaries: `{audit['complete_candidate_count']}/{audit['case_count']}`.",
        f"- Claim boundary: `{CLAIM_BOUNDARY}`.",
        "",
        "## Pose consensus classes",
        "",
        "| Class | Count |",
        "| --- | ---: |",
    ]
    for key, value in sorted(pose_classes.items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Important boundaries",
            "",
            "- The candidate tier is provisional until the 96-candidate production pilot is audited.",
            "- Calibration positives and their derivatives remain leakage-excluded and submission-ineligible.",
            "- 9E6Y values are reference-interface rescoring of the same 8X6B-generated pose set unless explicitly marked otherwise.",
            "- Contact frequencies are docking-derived soft labels, not crystallographic contacts.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, object]:
    cases = discover_cases(args.positive_root, args.mutant_root)
    pose_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    contact_rows: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []
    for case in cases:
        case_pose_rows, contacts = build_case_pose_rows(case, args.top_k, not args.skip_contacts)
        contact_record = contact_frequency_record(case, case_pose_rows, contacts)
        pose_rows.extend(case_pose_rows)
        contact_rows.append(contact_record)
        candidate_rows.append(candidate_summary(case, case_pose_rows, contact_record, args.min_supporting_clusters))
        manifest_rows.append(manifest_row(case))

    args.prepared_out.mkdir(parents=True, exist_ok=True)
    candidate_path = args.prepared_out / "candidate_summary.csv"
    pose_path = args.prepared_out / "pose_summary.csv"
    contact_path = args.prepared_out / "pose_contact_frequency.jsonl"
    config_path = args.prepared_out / "teacher_config.json"
    write_csv(candidate_path, candidate_rows, CANDIDATE_FIELDS)
    write_csv(pose_path, pose_rows, POSE_FIELDS)
    write_jsonl(contact_path, contact_rows)
    write_csv(args.manifest_out, manifest_rows, MANIFEST_FIELDS)

    config = {
        "schema_version": SCHEMA_VERSION,
        "top_k": args.top_k,
        "contact_cutoff_source": "per-pose score CSV, expected 4.5 A",
        "pose_generation_receptor": "8X6B",
        "independent_9e6y_docking": False,
        "min_supporting_clusters_for_provisional_stable_tier": args.min_supporting_clusters,
        "consensus_relevance": CONSENSUS_RELEVANCE,
        "relevance_weights": RELEVANCE_WEIGHTS,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    positive_ids = {case.candidate_id for case in cases if case.calibration_role == "known_positive_calibration_only"}
    pose_class_counts = Counter(clean(row["consensus_class"]) for row in pose_rows)
    audit: dict[str, object] = {
        "status": "PASS",
        "schema_version": SCHEMA_VERSION,
        "case_count": len(cases),
        "positive_case_count": len(positive_ids),
        "mutant_control_case_count": len(cases) - len(positive_ids),
        "pose_count": len(pose_rows),
        "pose_consensus_class_counts": dict(sorted(pose_class_counts.items())),
        "contact_pose_success_count": sum(clean(row["contact_extraction_status"]) == "ok" for row in pose_rows),
        "contact_pose_failure_count": sum(clean(row["contact_extraction_status"]) != "ok" for row in pose_rows),
        "complete_candidate_count": sum(clean(row["teacher_completeness"]) == "COMPLETE" for row in candidate_rows),
        "output_sha256": {
            str(candidate_path): sha256_file(candidate_path),
            str(pose_path): sha256_file(pose_path),
            str(contact_path): sha256_file(contact_path),
            str(config_path): sha256_file(config_path),
            str(args.manifest_out): sha256_file(args.manifest_out),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if len(cases) != 47 or len(positive_ids) != 11 or len(pose_rows) != 466:
        audit["status"] = "FAIL_UNEXPECTED_CALIBRATION_COUNTS"
    if not args.skip_contacts and audit["contact_pose_failure_count"]:
        audit["status"] = "FAIL_CONTACT_EXTRACTION_INCOMPLETE"
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_audit_markdown(args.audit_md, audit)
    if audit["status"] != "PASS":
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-root", type=Path, default=DEFAULT_POSITIVE_ROOT)
    parser.add_argument("--mutant-root", type=Path, default=DEFAULT_MUTANT_ROOT)
    parser.add_argument("--prepared-out", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT_JSON)
    parser.add_argument("--audit-md", type=Path, default=DEFAULT_AUDIT_MD)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--min-supporting-clusters", type=int, default=2)
    parser.add_argument("--skip-contacts", action="store_true")
    args = parser.parse_args(argv)
    if args.top_k <= 0:
        parser.error("--top-k must be positive")
    if args.min_supporting_clusters <= 0:
        parser.error("--min-supporting-clusters must be positive")
    return args


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
