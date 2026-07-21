#!/usr/bin/env python3
"""Build a canonical, leakage-aware PVRIG V29 docking-teacher release.

This adapter deliberately separates computational blocker-like geometry from
binding, affinity, expression, purity, and experimental blocking.  Technical
failures remain NA.  The uniform training target is the exact minimum of the
two independently docked receptor-conformation scores at primary seed 917.
Additional seeds are retained as reliability evidence, not used to redefine
the uniform primary target.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import tarfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CONFORMATIONS = ("8x6b", "9e6y")
PRIMARY_SEED = 917
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
SOURCE_PRIORITY = {"stage3": 0, "stage2": 1, "lab": 2, "external": 3}
CLAIM_BOUNDARY = (
    "PVRIG independent dual-conformation computational blocker-like geometry weak label only; "
    "not binding, affinity, competition, experimental blocking, expression, purity, or Docking Gold."
)
SCHEMA_VERSION = "pvrig_v29_canonical_training_release_v1"


class ReleaseError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_hash(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and path.stat().st_size > 0, f"missing_or_empty_tsv:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = [dict(row) for row in reader]
        fields = list(reader.fieldnames or [])
    require(fields and None not in fields and all(None not in row for row in rows), f"ragged_tsv:{path}")
    return fields, rows


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    require(bool(rows), f"refuse_empty_tsv:{path}")
    output_fields = fields or list(rows[0])
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=output_fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, buffer.getvalue())


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return default
    return output if math.isfinite(output) else default


def strict_float(value: Any, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as error:
        raise ReleaseError(f"invalid_float:{field}:{value!r}") from error
    require(math.isfinite(output), f"nonfinite_float:{field}:{value!r}")
    return output


def metric(score: dict[str, Any], *path: str, default: float = 0.0) -> float:
    value: Any = score
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return as_float(value, default)


def required_metric(score: dict[str, Any], *path: str) -> float:
    value: Any = score
    for key in path:
        require(isinstance(value, dict) and key in value, f"required_metric_missing:{'.'.join(path)}")
        value = value[key]
    return strict_float(value, ".".join(path))


def geometry_class_from_values(hotspot: float, total: float, cdr3: float, fraction: float) -> str:
    if hotspot >= 14 and total >= 500 and cdr3 >= 100 and fraction >= 0.15:
        return "A"
    if hotspot >= 14 and total < 50:
        return "C"
    if hotspot >= 10 and total >= 100 and cdr3 >= 20 and fraction >= 0.10:
        return "B"
    return "E"


def pair_label(left: str, right: str) -> str:
    if left == right == "A":
        return "STRICT_A"
    if left in {"A", "B"} and right in {"A", "B"}:
        return "SUPPORTED_AB"
    return "OTHER"


def pair_ordinal(label: str) -> int:
    return {"OTHER": 0, "SUPPORTED_AB": 1, "STRICT_A": 2}.get(label, 0)


def soft(value: float, threshold: float) -> float:
    return value / (value + threshold) if value > 0 else 0.0


def geometry_utility(values: dict[str, Any]) -> float:
    """Frozen V29 continuous geometry utility before job reliability factors.

    This is the V4-F continuous geometry base, without a VHH-PVRIG clash term
    because the V29 portable score schema does not contain that field. HADDOCK
    score is used only to select/order the fixed Top-8 models.
    """
    hotspot = as_float(values.get("hotspot_overlap"))
    holdout = as_float(values.get("holdout_overlap"))
    total = as_float(values.get("total_occlusion"))
    cdr3 = as_float(values.get("cdr3_occlusion"))
    fraction = as_float(values.get("cdr3_fraction"))
    return (
        0.15 * min(max(hotspot / 23.0, 0.0), 1.0)
        + 0.25 * min(max(holdout / 11.0, 0.0), 1.0)
        + 0.25 * soft(total, 500.0)
        + 0.20 * soft(cdr3, 100.0)
        + 0.15 * soft(fraction, 0.15)
    )


def geometry_margin(values: dict[str, Any]) -> float:
    return min(
        as_float(values.get("hotspot_overlap")) / 14.0,
        as_float(values.get("total_occlusion")) / 500.0,
        as_float(values.get("cdr3_occlusion")) / 100.0,
        as_float(values.get("cdr3_fraction")) / 0.15,
    )


def normalized_score_from_raw(score: dict[str, Any]) -> dict[str, Any]:
    values = {
        "scoring_reference": str(score.get("reference_id", "")).lower(),
        "hotspot_overlap": int(required_metric(score, "hotspot_overlap", "full", "count")),
        "anchor_overlap": int(required_metric(score, "hotspot_overlap", "anchor", "count")),
        "holdout_overlap": int(required_metric(score, "hotspot_overlap", "holdout", "count")),
        "total_occlusion": int(required_metric(score, "vhh_pvrl2_occlusion", "residue_pair_count")),
        "cdr3_occlusion": int(required_metric(score, "vhh_pvrl2_occlusion", "by_vhh_region_pair_count", "cdr3")),
        "cdr3_fraction": required_metric(score, "vhh_pvrl2_occlusion", "cdr3_fraction"),
        "clash_atom_pairs": int(required_metric(score, "clashes_2p5a", "atom_pair_count")),
        "clash_residue_pairs": int(required_metric(score, "clashes_2p5a", "residue_pair_count")),
        "overlay_rmsd_a": required_metric(score, "overlay", "t_ca_rmsd_a"),
    }
    require(values["scoring_reference"] in CONFORMATIONS, f"invalid_scoring_reference:{values['scoring_reference']}")
    values["geometry_class"] = geometry_class_from_values(
        values["hotspot_overlap"], values["total_occlusion"], values["cdr3_occlusion"], values["cdr3_fraction"]
    )
    values["geometry_margin"] = geometry_margin(values)
    values["geometry_utility"] = geometry_utility(values)
    values["score_payload_sha256"] = canonical_json_hash(score)
    return values


def normalized_score_from_external(row: dict[str, str]) -> dict[str, Any]:
    values = {
        "scoring_reference": row["scoring_reference"].lower(),
        "hotspot_overlap": int(strict_float(row.get("hotspot_overlap"), "external.hotspot_overlap")),
        "anchor_overlap": int(strict_float(row.get("anchor_overlap"), "external.anchor_overlap")),
        "holdout_overlap": int(strict_float(row.get("holdout_overlap"), "external.holdout_overlap")),
        "total_occlusion": int(strict_float(row.get("total_occlusion"), "external.total_occlusion")),
        "cdr3_occlusion": int(strict_float(row.get("cdr3_occlusion"), "external.cdr3_occlusion")),
        "cdr3_fraction": strict_float(row.get("cdr3_fraction"), "external.cdr3_fraction"),
        "clash_atom_pairs": int(strict_float(row.get("clash_atom_pairs"), "external.clash_atom_pairs")),
        "clash_residue_pairs": int(strict_float(row.get("clash_residue_pairs"), "external.clash_residue_pairs")),
        "overlay_rmsd_a": strict_float(row.get("overlay_rmsd_a"), "external.overlay_rmsd_a"),
    }
    require(values["scoring_reference"] in CONFORMATIONS, f"invalid_external_scoring_reference:{values['scoring_reference']}")
    values["geometry_class"] = geometry_class_from_values(
        values["hotspot_overlap"], values["total_occlusion"], values["cdr3_occlusion"], values["cdr3_fraction"]
    )
    values["geometry_margin"] = geometry_margin(values)
    values["geometry_utility"] = geometry_utility(values)
    values["score_payload_sha256"] = canonical_json_hash(values)
    return values


def summarize_models(models: list[dict[str, Any]], conformation: str) -> dict[str, Any]:
    complete = [model for model in models if set(model.get("scores", {})) == set(CONFORMATIONS)]
    complete.sort(key=lambda model: (strict_float(model.get("haddock_score"), "haddock_score"), str(model.get("model", ""))))
    fixed = complete[:8]
    require(len(fixed) >= 4, "fewer_than_4_complete_models")
    raw_weights = [1.0 / math.log2(rank + 1) for rank in range(1, len(fixed) + 1)]
    weights = [value / sum(raw_weights) for value in raw_weights]
    native_utilities = [strict_float(model["scores"][conformation]["geometry_utility"], "geometry_utility") for model in fixed]
    raw_score = sum(weight * value for weight, value in zip(weights, native_utilities))
    reliability = 0.5 + 0.5 * min(len(fixed) / 8.0, 1.0)
    other = "9e6y" if conformation == "8x6b" else "8x6b"
    labels = [pair_label(model["scores"][conformation]["geometry_class"], model["scores"][other]["geometry_class"]) for model in fixed]
    agreements = [
        (model["scores"][conformation]["geometry_class"] in {"A", "B"})
        == (model["scores"][other]["geometry_class"] in {"A", "B"})
        for model in fixed
    ]
    consensus = max(Counter(labels).values()) / len(labels)
    agreement = sum(agreements) / len(agreements)
    job_score = raw_score * reliability * (0.5 + 0.25 * agreement + 0.25 * consensus)
    representative = fixed[0]
    representative_label = labels[0]
    top_model_ids = [str(model["model"]) for model in fixed]
    top_pose_paths = [str(model.get("pose_path", "")) for model in fixed]
    top_score_hashes = [
        canonical_json_hash({ref: model["scores"][ref]["score_payload_sha256"] for ref in CONFORMATIONS}) for model in fixed
    ]
    return {
        "fixed_top8_count": len(fixed),
        "job_geometry_score": job_score,
        "raw_rank_weighted_geometry_score": raw_score,
        "model_pair_consensus_fraction": consensus,
        "model_native_cross_support_agreement_fraction": agreement,
        "model_strict_a_fraction": labels.count("STRICT_A") / len(labels),
        "representative_model": representative["model"],
        "representative_pair_label": representative_label,
        "representative_pair_support_ordinal": pair_ordinal(representative_label),
        "top8_model_ids": ",".join(top_model_ids),
        "top8_pose_paths": "|".join(top_pose_paths),
        "top8_score_payload_sha256": ",".join(top_score_hashes),
        "fixed_models": fixed,
    }


def parse_full_result(task: tuple[str, str, str, str, str]) -> dict[str, Any]:
    source, job_id, conformation, path_text, storage_kind = task
    path = Path(path_text)
    try:
        if storage_kind == "tar.gz":
            with tarfile.open(path, "r:gz") as archive:
                members = [member for member in archive.getmembers() if member.isfile() and member.name.endswith(f"results/{job_id}/job_result.json")]
                require(len(members) == 1, f"archive_job_result_member_count:{len(members)}")
                extracted = archive.extractfile(members[0])
                require(extracted is not None, "archive_job_result_extract_failed")
                raw_bytes = extracted.read()
                evidence_path = f"{path}::{members[0].name}"
        else:
            require(storage_kind == "json", f"unsupported_storage_kind:{storage_kind}")
            raw_bytes = path.read_bytes()
            evidence_path = str(path)
        payload = json.loads(raw_bytes)
        raw_state = str(payload.get("state", "")).upper()
        require(raw_state in SUCCESS_STATES, f"job_result_state_not_success:{raw_state or 'MISSING'}")
        models: list[dict[str, Any]] = []
        for pose in payload.get("pose_scores", []):
            score_by_ref = {
                str(score.get("reference_id", "")).lower(): normalized_score_from_raw(score)
                for score in pose.get("scores", [])
            }
            models.append(
                {
                    "model": Path(str(pose.get("pose", ""))).name,
                    "pose_path": str(pose.get("pose", "")),
                    "haddock_score": strict_float((pose.get("haddock_io") or {}).get("score"), "haddock_io.score"),
                    "air_energy": as_float((pose.get("haddock_io") or {}).get("unw_energies.air")),
                    "scores": score_by_ref,
                }
            )
        summary = summarize_models(models, conformation)
        return {
            "source": source,
            "job_id": job_id,
            "state": raw_state,
            "job_hash": str(payload.get("job_hash", "")),
            "protocol_core_sha256": str(payload.get("protocol_core_sha256", "")),
            "selected_model_count": int(as_float(payload.get("selected_model_count"), len(models))),
            "evidence_path": evidence_path,
            "evidence_sha256": sha256_bytes(raw_bytes),
            **summary,
        }
    except Exception as error:
        return {
            "source": source,
            "job_id": job_id,
            "state": "SCORING_TECHNICAL_FAILURE",
            "failure_reason": f"{type(error).__name__}:{error}",
            "evidence_path": str(path),
        }


def external_results(external_root: Path) -> dict[str, dict[str, Any]]:
    _, job_rows = read_tsv(external_root / "reports/external_job_results.tsv")
    _, pose_rows = read_tsv(external_root / "reports/external_pose_scores.tsv")
    by_job_model: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in pose_rows:
        job_id = row["job_id"]
        model = row["model"]
        current = by_job_model[job_id].setdefault(
            model,
            {
                "model": model,
                "pose_path": model,
                "haddock_score": strict_float(row.get("haddock_score"), "external.haddock_score"),
                "air_energy": as_float(row.get("air_energy")),
                "scores": {},
            },
        )
        current["scores"][row["scoring_reference"].lower()] = normalized_score_from_external(row)
    output: dict[str, dict[str, Any]] = {}
    require(len({row["job_id"] for row in job_rows}) == len(job_rows), "duplicate_external_job_id")
    for row in job_rows:
        job_id = row["job_id"]
        state = row.get("state", "").upper()
        item: dict[str, Any] = {
            "source": "external",
            "job_id": job_id,
            "state": state,
            "job_hash": row.get("job_hash", ""),
            "protocol_core_sha256": "",
            "selected_model_count": int(as_float(row.get("selected_model_count"))),
            "evidence_path": str(external_root / "reports/external_pose_scores.tsv"),
            "evidence_sha256": "",
        }
        if state in SUCCESS_STATES:
            try:
                item.update(summarize_models(list(by_job_model.get(job_id, {}).values()), row["conformation"].lower()))
            except Exception as error:
                item["state"] = "SCORING_TECHNICAL_FAILURE"
                item["failure_reason"] = f"{type(error).__name__}:{error}"
        output[job_id] = item
    return output


def load_statuses(path: Path, source: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    if not path.is_dir():
        return output
    for item in path.glob("*.json"):
        try:
            payload = json.loads(item.read_text())
        except Exception as error:
            output[item.stem] = {"source": source, "status": "STATUS_PARSE_FAILURE", "reason": str(error)}
            continue
        output[item.stem] = {
            "source": source,
            "status": str(payload.get("status") or payload.get("state") or "").upper(),
            "attempts": int(as_float(payload.get("attempts"))),
            "return_code": payload.get("return_code", ""),
            "stage": payload.get("stage", ""),
            "reason": payload.get("reason") or payload.get("error") or payload.get("failure_reason") or "",
        }
    return output


def collect_full_tasks(
    manifest: dict[str, dict[str, str]], source: str, results_root: Path, archive_root: Path | None = None
) -> list[tuple[str, str, str, str, str]]:
    tasks: list[tuple[str, str, str, str, str]] = []
    if not results_root.is_dir():
        return tasks
    for path in results_root.glob("*/job_result.json"):
        job_id = path.parent.name
        job = manifest.get(job_id)
        if job is not None:
            archive_path = archive_root / f"{job_id}.tar.gz" if archive_root is not None else None
            if archive_path is not None and archive_path.is_file():
                tasks.append((source, job_id, job["conformation"].lower(), str(archive_path), "tar.gz"))
            else:
                tasks.append((source, job_id, job["conformation"].lower(), str(path), "json"))
    return tasks


def source_signature(result: dict[str, Any]) -> tuple[Any, ...]:
    return (
        result.get("job_hash", ""),
        round(as_float(result.get("job_geometry_score")), 12),
        result.get("representative_pair_label", ""),
        result.get("top8_model_ids", ""),
    )


def pose_rows_for_selected(job: dict[str, str], selected: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for rank, model in enumerate(selected.get("fixed_models", []), 1):
        for reference in CONFORMATIONS:
            score = model["scores"][reference]
            output.append(
                {
                    "job_id": job["job_id"],
                    "candidate_id": job["entity_id"],
                    "sequence_sha256": job["sequence_sha256"],
                    "seed": job["seed"],
                    "dock_conformation": job["conformation"],
                    "source": selected["source"],
                    "top8_rank": rank,
                    "model": model["model"],
                    "pose_path": model.get("pose_path", ""),
                    "pose_pdb_sha256": "",
                    "pose_artifact_state": "PATH_RECORDED_PDB_HASH_NOT_MIRRORED",
                    "haddock_score": model.get("haddock_score", ""),
                    "air_energy": model.get("air_energy", ""),
                    **score,
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )
    return output


class UnionFind:
    def __init__(self, values: Iterable[str]):
        self.parent = {value: value for value in values}
        self.size = {value: 1 for value in values}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            parent = self.parent[value]
            self.parent[value] = root
            value = parent
        return root

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        if self.size[a] < self.size[b]:
            a, b = b, a
        self.parent[b] = a
        self.size[a] += self.size[b]


def cdr3_families(cdr3_values: Iterable[str]) -> dict[str, str]:
    """Cluster equal-length CDR3s connected at >=80% Hamming identity."""
    unique = sorted(set(cdr3_values))
    uf = UnionFind(unique)
    by_length: dict[int, list[str]] = defaultdict(list)
    for sequence in unique:
        by_length[len(sequence)].append(sequence)
    for length, sequences in by_length.items():
        max_distance = math.floor(0.20 * length + 1e-12)
        if max_distance <= 0:
            continue
        block_count = max_distance + 1
        boundaries = [round(index * length / block_count) for index in range(block_count + 1)]
        buckets: dict[tuple[int, str], list[str]] = defaultdict(list)
        compared: set[tuple[str, str]] = set()
        for sequence in sequences:
            candidates: set[str] = set()
            for index in range(block_count):
                key = (index, sequence[boundaries[index] : boundaries[index + 1]])
                candidates.update(buckets[key])
            for other in candidates:
                pair = (other, sequence) if other < sequence else (sequence, other)
                if pair in compared:
                    continue
                compared.add(pair)
                distance = sum(left != right for left, right in zip(sequence, other))
                if distance <= max_distance:
                    uf.union(sequence, other)
            for index in range(block_count):
                key = (index, sequence[boundaries[index] : boundaries[index + 1]])
                buckets[key].append(sequence)
    members: dict[str, list[str]] = defaultdict(list)
    for sequence in unique:
        members[uf.find(sequence)].append(sequence)
    mapping: dict[str, str] = {}
    for group in members.values():
        family_hash = sha256_text("\n".join(sorted(group)))[:16]
        for sequence in group:
            mapping[sequence] = f"CDR3F80_{family_hash}"
    return mapping


def assign_leakage_safe_splits(candidate_rows: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, Any]]:
    """Preserve parent-held-out splits and quarantine cross-split CDR3 families.

    The V29 graph that simultaneously connects global parent clusters and
    global CDR3 families has one giant component, so a non-trivial strict
    70/15/15 split is mathematically impossible.  Parent isolation is the hard
    rule.  Near-CDR3 families spanning parent folds are owned by one fold and
    non-owner rows are quarantined from formal train/dev/test metrics.
    """
    family_by_cdr3 = cdr3_families(str(row["cdr3"]) for row in candidate_rows)
    parent_base_splits: dict[str, set[str]] = defaultdict(set)
    family_base_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in candidate_rows:
        row["cdr3_family_id"] = family_by_cdr3[row["cdr3"]]
        base_split = row["model_split"]
        require(base_split in {"train", "development", "frozen_test"}, f"invalid_base_split:{base_split}")
        parent_base_splits[row["parent_framework_cluster"]].add(base_split)
        family_base_counts[row["cdr3_family_id"]][base_split] += 1
    require(all(len(values) == 1 for values in parent_base_splits.values()), "base_parent_split_leakage")
    family_owner: dict[str, str] = {}
    priority = {"train": 2, "development": 1, "frozen_test": 0}
    for family, counts in family_base_counts.items():
        family_owner[family] = (
            "train"
            if "train" in counts
            else max(counts, key=lambda split: (counts[split], priority[split], sha256_text(f"{family}:{split}")))
        )
    assignment: dict[str, str] = {}
    final_counts = Counter()
    quarantined_families: set[str] = set()
    for row in candidate_rows:
        base_split = row["model_split"]
        owner = family_owner[row["cdr3_family_id"]]
        final_split = base_split if base_split == owner else "quarantine_cdr3_overlap"
        assignment[row["sequence_sha256"]] = final_split
        row["parent_only_model_split"] = base_split
        row["cdr3_family_owner_split"] = owner
        row["split_exclusion_reason"] = "" if final_split == base_split else "CDR3_FAMILY_CROSSES_PARENT_HELD_OUT_FOLDS"
        final_counts[final_split] += 1
        if final_split != base_split:
            quarantined_families.add(row["cdr3_family_id"])
    parent_splits: dict[str, set[str]] = defaultdict(set)
    family_splits: dict[str, set[str]] = defaultdict(set)
    for row in candidate_rows:
        split = assignment[row["sequence_sha256"]]
        if split == "quarantine_cdr3_overlap":
            continue
        parent_splits[row["parent_framework_cluster"]].add(split)
        family_splits[row["cdr3_family_id"]].add(split)
    require(all(len(values) == 1 for values in parent_splits.values()), "parent_split_leakage")
    require(all(len(values) == 1 for values in family_splits.values()), "cdr3_family_split_leakage")
    audit = {
        "algorithm": "frozen_parent_split_then_cdr3_hamming80_equal_length_cross_fold_quarantine_v1",
        "candidate_count": len(candidate_rows),
        "parent_cluster_count": len(parent_base_splits),
        "cdr3_family_count": len(family_base_counts),
        "base_split_counts": dict(sorted(Counter(row["model_split"] for row in candidate_rows).items())),
        "final_split_counts": dict(sorted(final_counts.items())),
        "cross_base_split_cdr3_family_count": sum(len(counts) > 1 for counts in family_base_counts.values()),
        "quarantined_cdr3_family_count": len(quarantined_families),
        "parent_cross_split_count": sum(len(values) > 1 for values in parent_splits.values()),
        "cdr3_family_cross_split_count": sum(len(values) > 1 for values in family_splits.values()),
        "strict_joint_parent_and_global_cdr3_split_note": "The full bipartite graph is one component; quarantining non-owner CDR3-family rows is required for non-trivial evaluation folds.",
    }
    return assignment, audit


def build(args: argparse.Namespace) -> dict[str, Any]:
    master = args.master_root.resolve()
    mirror = args.mirror_root.resolve()
    external = args.external_root.resolve()
    final_output = args.output_root.resolve()
    require(not final_output.exists(), f"output_exists:{final_output}")
    output = final_output.with_name(f".{final_output.name}.building.{os.getpid()}")
    require(not output.exists(), f"staging_output_exists:{output}")
    output.mkdir(parents=True)
    for directory in ("reports", "release", "audit", "scripts", "logs"):
        (output / directory).mkdir()

    manifest_fields, manifest_rows = read_tsv(master / "manifests/docking_jobs.tsv")
    require(len(manifest_rows) == 24826, f"master_job_count:{len(manifest_rows)}")
    manifest = {row["job_id"]: row for row in manifest_rows}
    require(len(manifest) == len(manifest_rows), "duplicate_master_job_id")
    require(len({row["protocol_core_sha256"] for row in manifest_rows}) == 1, "multiple_protocol_core_hashes")

    _, candidates = read_tsv(master / "inputs/candidates_128.tsv")
    require(len(candidates) == 9934, f"candidate_count:{len(candidates)}")
    require(len({row["sequence_sha256"] for row in candidates}) == len(candidates), "candidate_sequence_hash_duplicates")
    for row in candidates:
        require(sha256_text(row["sequence"]) == row["sequence_sha256"], f"sequence_hash_mismatch:{row['candidate_id']}")

    _, monomer_rows = read_tsv(master / "inputs/candidate_monomers_manifest.tsv")
    monomer_by_id = {row["candidate_id"]: row for row in monomer_rows}
    _, allocation_rows = read_tsv(master / "inputs/docking_allocation25000.tsv")
    provenance_by_id: dict[str, dict[str, str]] = {}
    provenance_fields = ["model_split", "acquisition_lane", "design_method", "target_patch", "design_mode", "protocol_id", "claim_boundary"]
    for row in allocation_rows:
        candidate_id = row["candidate_id"]
        current = provenance_by_id.setdefault(candidate_id, {field: row.get(field, "") for field in provenance_fields})
        require(all(current[field] == row.get(field, "") for field in provenance_fields), f"provenance_conflict:{candidate_id}")

    full_roots = {
        "lab": (master / "results", None),
        "stage2": (mirror / "stage2/results", mirror / "stage2/compressed_queue"),
        "stage3": (mirror / "stage3_node20/results", None),
    }
    tasks = [
        task
        for source, (root, archive_root) in full_roots.items()
        for task in collect_full_tasks(manifest, source, root, archive_root)
    ]
    parsed: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for index, result in enumerate(executor.map(parse_full_result, tasks, chunksize=8), 1):
            parsed.append(result)
            if index % 500 == 0:
                print(json.dumps({"event": "parsed_full_results", "done": index, "total": len(tasks)}), flush=True)
    parsed.extend(external_results(external).values())

    results_by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in parsed:
        results_by_job[result["job_id"]].append(result)
    statuses_by_source = {
        "lab": load_statuses(master / "status/jobs", "lab"),
        "stage2": load_statuses(mirror / "stage2/status/jobs", "stage2"),
        "stage3": load_statuses(mirror / "stage3_node20/status/jobs", "stage3"),
        "external": load_statuses(external / "status/jobs", "external"),
    }

    canonical_jobs: list[dict[str, Any]] = []
    pose_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    duplicate_conflicts: list[dict[str, Any]] = []
    selected_results: dict[str, dict[str, Any]] = {}
    for job in manifest_rows:
        job_id = job["job_id"]
        available = results_by_job.get(job_id, [])
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in available:
            by_source[item["source"]].append(item)
        for source, source_items in by_source.items():
            source_signatures = {source_signature(item) for item in source_items}
            require(len(source_signatures) == 1, f"conflicting_results_within_source:{source}:{job_id}")
        available = [sorted(items, key=lambda item: (str(item.get("evidence_sha256", "")), str(item.get("evidence_path", ""))))[0] for items in by_source.values()]
        successful = [item for item in available if item.get("state", "").upper() in SUCCESS_STATES and "job_geometry_score" in item]
        successful.sort(key=lambda item: SOURCE_PRIORITY.get(item["source"], 99))
        selected = successful[0] if successful else None
        signatures = {source_signature(item) for item in successful}
        source_conflict = len(signatures) > 1
        if source_conflict:
            duplicate_conflicts.append(
                {
                    "job_id": job_id,
                    "sources": ",".join(item["source"] for item in successful),
                    "signatures": json.dumps([source_signature(item) for item in successful], separators=(",", ":")),
                    "selected_source": selected["source"] if selected else "",
                }
            )
        if selected is not None:
            require(not selected.get("job_hash") or selected["job_hash"] == job["job_hash"], f"job_hash_mismatch:{job_id}")
            selected_results[job_id] = selected
            row = {
                **job,
                "canonical_state": "SUCCESS",
                "technical_failure_reason": "",
                "selected_source": selected["source"],
                "available_success_sources": ",".join(item["source"] for item in successful),
                "duplicate_success_source_count": len(successful),
                "duplicate_source_conflict": str(source_conflict).lower(),
                "selected_model_count": selected.get("selected_model_count", ""),
                "fixed_top8_count": selected["fixed_top8_count"],
                "job_geometry_score": f"{selected['job_geometry_score']:.9f}",
                "raw_rank_weighted_geometry_score": f"{selected['raw_rank_weighted_geometry_score']:.9f}",
                "model_pair_consensus_fraction": f"{selected['model_pair_consensus_fraction']:.6f}",
                "model_native_cross_support_agreement_fraction": f"{selected['model_native_cross_support_agreement_fraction']:.6f}",
                "model_strict_a_fraction": f"{selected['model_strict_a_fraction']:.6f}",
                "representative_model": selected["representative_model"],
                "representative_pair_label": selected["representative_pair_label"],
                "representative_pair_support_ordinal": selected["representative_pair_support_ordinal"],
                "top8_model_ids": selected["top8_model_ids"],
                "top8_pose_paths": selected["top8_pose_paths"],
                "top8_score_payload_sha256": selected["top8_score_payload_sha256"],
                "evidence_path": selected.get("evidence_path", ""),
                "evidence_sha256": selected.get("evidence_sha256", ""),
                "claim_boundary": CLAIM_BOUNDARY,
            }
            canonical_jobs.append(row)
            pose_rows.extend(pose_rows_for_selected(job, selected))
        else:
            status_evidence = [source_rows[job_id] for source_rows in statuses_by_source.values() if job_id in source_rows]
            raw_states = sorted({item.get("status", "") for item in status_evidence if item.get("status")})
            parse_failures = [item.get("failure_reason", "") for item in available if item.get("failure_reason")]
            reason = ";".join(raw_states + parse_failures) or "NO_SUCCESS_EVIDENCE"
            row = {
                **job,
                "canonical_state": "TECHNICAL_NA",
                "technical_failure_reason": reason,
                "selected_source": "",
                "available_success_sources": "",
                "duplicate_success_source_count": 0,
                "duplicate_source_conflict": "false",
                "claim_boundary": CLAIM_BOUNDARY,
            }
            canonical_jobs.append(row)
            failures.append(
                {
                    "job_id": job_id,
                    "candidate_id": job["entity_id"],
                    "sequence_sha256": job["sequence_sha256"],
                    "conformation": job["conformation"],
                    "seed": job["seed"],
                    "canonical_state": "TECHNICAL_NA",
                    "technical_failure_reason": reason,
                    "status_evidence": json.dumps(status_evidence, sort_keys=True, separators=(",", ":")),
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )

    by_candidate_seed: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in canonical_jobs:
        by_candidate_seed[(row["entity_id"], int(row["seed"]))][row["conformation"]] = row
    seed_labels: list[dict[str, Any]] = []
    for (candidate_id, seed), by_conf in sorted(by_candidate_seed.items()):
        complete = all(by_conf.get(conf, {}).get("canonical_state") == "SUCCESS" for conf in CONFORMATIONS)
        if complete:
            r8 = as_float(by_conf["8x6b"]["job_geometry_score"])
            r9 = as_float(by_conf["9e6y"]["job_geometry_score"])
            ordinal8 = int(by_conf["8x6b"]["representative_pair_support_ordinal"])
            ordinal9 = int(by_conf["9e6y"]["representative_pair_support_ordinal"])
            technical = ""
        else:
            r8 = r9 = math.nan
            ordinal8 = ordinal9 = -1
            technical = ";".join(
                f"{conf}:{by_conf.get(conf, {}).get('technical_failure_reason', 'MISSING_JOB')}" for conf in CONFORMATIONS
                if by_conf.get(conf, {}).get("canonical_state") != "SUCCESS"
            )
        seed_labels.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": next(row["sequence_sha256"] for row in by_conf.values()),
                "seed": seed,
                "dual_state": "COMPLETE_DUAL_SUCCESS" if complete else "TECHNICAL_NA",
                "R8_geometry": f"{r8:.9f}" if complete else "",
                "R9_geometry": f"{r9:.9f}" if complete else "",
                "R_dual_exact_min": f"{min(r8, r9):.9f}" if complete else "",
                "8x6b_pair_support_ordinal": ordinal8 if complete else "",
                "9e6y_pair_support_ordinal": ordinal9 if complete else "",
                "dual_exact_min_pair_support_ordinal": min(ordinal8, ordinal9) if complete else "",
                "technical_failure_reason": technical,
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )

    seed_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in seed_labels:
        seed_by_candidate[row["candidate_id"]].append(row)
    candidate_rows: list[dict[str, Any]] = []
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    for candidate_id, candidate in sorted(candidate_by_id.items()):
        rows = seed_by_candidate[candidate_id]
        complete_rows = [row for row in rows if row["dual_state"] == "COMPLETE_DUAL_SUCCESS"]
        primary = next((row for row in rows if int(row["seed"]) == PRIMARY_SEED), None)
        primary_complete = bool(primary and primary["dual_state"] == "COMPLETE_DUAL_SUCCESS")
        r8_values = [as_float(row["R8_geometry"]) for row in complete_rows]
        r9_values = [as_float(row["R9_geometry"]) for row in complete_rows]
        dual_values = [as_float(row["R_dual_exact_min"]) for row in complete_rows]
        provenance = provenance_by_id.get(candidate_id, {})
        monomer = monomer_by_id.get(candidate_id, {})
        candidate_rows.append(
            {
                **candidate,
                "canonical_candidate_id": candidate_id,
                "duplicate_candidate_ids": candidate_id,
                "sequence_length": len(candidate["sequence"]),
                "cdr3_length": len(candidate["cdr3"]),
                **{field: provenance.get(field, "") for field in provenance_fields},
                "monomer_pdb_path": monomer.get("frozen_monomer_path", ""),
                "monomer_pdb_sha256": monomer.get("sha256", ""),
                "training_label_status": "WEAK_LABEL_AVAILABLE" if primary_complete else "TECHNICAL_NA",
                "docking_evidence_tier": f"DUAL_{len(complete_rows)}_SEED" if complete_rows else "TECHNICAL_NA",
                "successful_dual_seed_count": len(complete_rows),
                "successful_dual_seed_ids": ",".join(str(row["seed"]) for row in complete_rows),
                "R8_primary_seed917": primary["R8_geometry"] if primary_complete else "",
                "R9_primary_seed917": primary["R9_geometry"] if primary_complete else "",
                "R_dual_min": primary["R_dual_exact_min"] if primary_complete else "",
                "primary_dual_exact_min_pair_support_ordinal": primary["dual_exact_min_pair_support_ordinal"] if primary_complete else "",
                "R8_multiseed_median": f"{statistics.median(r8_values):.9f}" if r8_values else "",
                "R9_multiseed_median": f"{statistics.median(r9_values):.9f}" if r9_values else "",
                "R_dual_multiseed_exact_min": f"{min(statistics.median(r8_values), statistics.median(r9_values)):.9f}" if r8_values and r9_values else "",
                "seed_dispersion_Rdual": f"{statistics.pstdev(dual_values):.9f}" if len(dual_values) >= 2 else "0.000000000" if dual_values else "",
                "technical_failure_reason": "" if primary_complete else (primary or {}).get("technical_failure_reason", "PRIMARY_SEED_MISSING"),
                "label_scope": CLAIM_BOUNDARY,
            }
        )

    split_assignment, split_audit = assign_leakage_safe_splits(candidate_rows)
    for row in candidate_rows:
        row["canonical_model_split"] = split_assignment[row["sequence_sha256"]]

    success_jobs = sum(row["canonical_state"] == "SUCCESS" for row in canonical_jobs)
    technical_jobs = len(canonical_jobs) - success_jobs
    primary_success = sum(row["training_label_status"] == "WEAK_LABEL_AVAILABLE" for row in candidate_rows)
    require(success_jobs == 24815, f"successful_job_count:{success_jobs}")
    require(technical_jobs == 11, f"technical_na_job_count:{technical_jobs}")
    require(primary_success == 9927, f"primary_dual_success_count:{primary_success}")
    require(len(failures) == 11, f"failure_rows:{len(failures)}")

    write_tsv(output / "reports/canonical_job_results.tsv", canonical_jobs)
    write_tsv(output / "reports/canonical_top8_pose_scores.tsv", pose_rows)
    write_tsv(output / "reports/candidate_seed_dual_labels.tsv", seed_labels)
    write_tsv(output / "reports/technical_failures_na.tsv", failures)
    if duplicate_conflicts:
        write_tsv(output / "audit/duplicate_source_conflicts.tsv", duplicate_conflicts)
    else:
        write_tsv(output / "audit/duplicate_source_conflicts.tsv", [{"status": "NO_CONFLICTS"}])
    write_tsv(output / "release/pvrig_v29_sequence_docking_weaklabels.tsv", candidate_rows)
    write_json(output / "audit/split_audit.json", split_audit)

    readme = f"""# PVRIG V29 canonical Docking teacher release

## 使用边界

本发布包只表示 **PVRIG 双构象计算阻断样几何弱标签**。它不是结合概率、Kd、IC50、表达量、纯度、实验阻断结果或 Docking Gold。

## 统一标签

- 主训练标签固定为 seed 917：`R_dual_min = min(R8_primary_seed917, R9_primary_seed917)`。
- seed 1931/3253 仅用于重复性、离散度和噪声建模，不能改变全体候选的统一主标签口径。
- 任何 Docking/评分技术失败均为 `TECHNICAL_NA`，不能填 0，也不能作为生物学负样本。
- 每个 job 按 HADDOCK score 从低到高固定 Top-8，再计算 rank-weighted blocker-like geometry utility。

## 切分

- `parent_only_model_split`：原冻结 parent 隔离切分。
- `cdr3_family_id`：等长 CDR3、Hamming identity >=80% 的连通家族。
- `canonical_model_split`：正式模型切分。跨 parent fold 的 CDR3 family 由一个 fold 持有，其余成员标记为 `quarantine_cdr3_overlap`，不进入正式 train/dev/test 指标。
- 原因：全局 parent-CDR3 二部图是一个连通分量；若同时硬保留全部序列并严格隔离两类 group，只能得到“全部进入一个 fold”的无效切分。

## 主要文件

- `release/pvrig_v29_sequence_docking_weaklabels.tsv`：序列级训练标签与 split。
- `reports/candidate_seed_dual_labels.tsv`：候选×seed 双构象 exact-min。
- `reports/canonical_job_results.tsv`：24,826 个 job 的统一状态和 Top-8 摘要。
- `reports/canonical_top8_pose_scores.tsv`：Top-8×双 reference 的连续几何特征。
- `reports/technical_failures_na.tsv`：技术失败审计。
- `audit/split_audit.json`：parent/CDR3 family 泄漏检查。
- `READY.json`：完整发布标记；不存在时不得消费该目录。

## Pose 文件注意

发布包保存 Top-8 pose 的来源路径与 score-payload SHA256。部分 bxcpu/external 原始 PDB 未镜像到 Node1，因此 `pose_pdb_sha256` 为空并明确标记；训练标签可使用评分证据，但若训练三维 pose 模型，必须另行补齐并哈希绑定原始 PDB。
"""
    atomic_write_text(output / "README_ZH.md", readme)

    script_destination = output / "scripts/build_canonical_training_release.py"
    script_destination.write_bytes(Path(__file__).read_bytes())
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_CANONICAL_RELEASE",
        "created_at_utc": now_utc(),
        "counts": {
            "master_jobs": len(canonical_jobs),
            "successful_jobs": success_jobs,
            "technical_na_jobs": technical_jobs,
            "candidates_sequence_unique": len(candidate_rows),
            "primary_seed917_dual_success": primary_success,
            "candidate_seed_rows": len(seed_labels),
            "top8_pose_reference_rows": len(pose_rows),
            "duplicate_source_conflicts": len(duplicate_conflicts),
        },
        "target_contract": {
            "uniform_training_target": "R_dual_min=min(R8_primary_seed917,R9_primary_seed917)",
            "additional_seeds": "reliability_and_noise_evidence_only",
            "technical_failure_semantics": "NA_not_negative",
            "fixed_pose_selection": "lowest_HADDOCK_score_then_model_id_Top8",
            "geometry_utility": "0.15*clip(hotspot/23)+0.25*clip(holdout/11)+0.25*soft(total,500)+0.20*soft(cdr3,100)+0.15*soft(cdr3_fraction,0.15)",
            "job_reliability": "utility_rank_weighted_by_1/log2(rank+1)*model_count_reliability*(0.5+0.25*native_cross_agreement+0.25*pair_label_consensus)",
        },
        "protocol_core_sha256": next(iter({row["protocol_core_sha256"] for row in manifest_rows})),
        "source_paths": {
            "master": str(master),
            "mirror": str(mirror),
            "external": str(external),
        },
        "split_audit": split_audit,
        "pose_artifact_caveat": "Top8 pose source paths and score-payload hashes are retained; pose PDB hashes are blank where raw PDBs were not mirrored to Node1.",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(output / "RELEASE_RECEIPT.json", receipt)
    files = sorted(path for path in output.rglob("*") if path.is_file() and path.name not in {"SHA256SUMS", "READY.json"})
    checksum_text = "".join(f"{sha256_file(path)}  {path.relative_to(output)}\n" for path in files)
    atomic_write_text(output / "SHA256SUMS", checksum_text)
    ready = {
        "status": "READY",
        "schema_version": SCHEMA_VERSION,
        "release_receipt_sha256": sha256_file(output / "RELEASE_RECEIPT.json"),
        "sha256sums_sha256": sha256_file(output / "SHA256SUMS"),
        "completed_at_utc": now_utc(),
    }
    write_json(output / "READY.json", ready)
    os.replace(output, final_output)
    receipt.update(ready)
    receipt["output_root"] = str(final_output)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-root", type=Path, default=Path("/data/qlyu/projects/pvrig_v29_docking25k_v1_20260720"))
    parser.add_argument("--mirror-root", type=Path, default=Path("/data/qlyu/projects/pvrig_v29_bxcpu_results_mirror_20260720"))
    parser.add_argument("--external-root", type=Path, default=Path("/data/qlyu/projects/bxcpu_stage1_external2000_terminal_core_20260721T013848Z"))
    parser.add_argument("--output-root", type=Path, default=Path("/data1/qlyu/projects/pvrig_v29_canonical_training_release_v1_20260721"))
    parser.add_argument("--workers", type=int, default=16)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(build(args), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
