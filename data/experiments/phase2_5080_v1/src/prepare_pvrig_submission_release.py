#!/usr/bin/env python3
"""Build a deterministic, computation-only PVRIG Top50/Top10 release.

The release requires an upstream open-only geometry shortlist, a complete
Top20 pose bundle, explicit manual computational pose verdicts, and a frozen
Top10 selection. It does not infer binding, affinity, competition, or
experimental blocking.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CLAIM_BOUNDARY = (
    "Competition computational-priority release only; not binding probability, "
    "affinity/Kd, competition, blockade, or experimental blocking evidence."
)
RANKING_CLAIM_BOUNDARY = (
    "Computational dual-conformation geometry priority and pose-review routing only; "
    "not binder probability, affinity/Kd, competition, or experimental blocking."
)
GENERIC_PRIOR_CLAIM_BOUNDARY = (
    "relative_generic_binding_prior_for_teacher_sampling_not_pvrig_binding_or_blocking_truth"
)
OPEN_SPLITS = {"OPEN_TRAIN", "OPEN_DEVELOPMENT"}
OPEN_GEOMETRY_STATUSES = {
    "OPEN_USABLE",
    "OPEN_AVAILABLE",
    "OPEN_GEOMETRY_AVAILABLE",
    "OPEN_COMPLETE",
    "OPEN_PASS",
    "OPEN_AVAILABLE_V4D_COMPUTATIONAL_GEOMETRY",
}
ACCEPTED_TOP10_VERDICTS = {
    "ACCEPT_COMPUTATIONAL_PRIORITY",
    "ACCEPT_DIVERSITY_HEDGE",
}
ALL_VERDICTS = ACCEPTED_TOP10_VERDICTS | {
    "REVIEW_SINGLE_RECEPTOR",
    "REVIEW_DEVELOPABILITY",
    "REJECT_IMPLAUSIBLE_POSE",
}
CONFORMATIONS = {"8x6b", "9e6y"}
SEEDS = {"917", "1931", "3253"}
AA = set("ACDEFGHIKLMNPQRSTVWY")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

SHORTLIST_REQUIRED = {
    "candidate_id", "rank", "sequence", "sequence_sha256", "source_cohort",
    "parent_id", "scaffold_id", "target_patch_id", "design_mode", "cdr1",
    "cdr2", "cdr3", "cdr3_length", "fast_hard_fail", "full_qc_status",
    "official_validator_pass", "max_positive_cdr_identity", "exact_positive_id",
    "leakage_status", "developability_score", "expression_purity_risk_score",
    "anarci_status", "imgt_chain_type", "abnativ_status", "abnativ_vhh_score",
    "generic_binding_prior", "generic_prior_claim_boundary", "monomer_status",
    "monomer_sha256", "monomer_sequence_match",
    "geometry_status", "r_8x6b", "r_9e6y", "r_dual_min", "r_dual_gap",
    "geometry_uncertainty", "successful_seeds_8x6b", "successful_seeds_9e6y",
    "full_sequence_cluster", "cdr3_cluster", "angle_family",
    "v4d_teacher_model_split", "geometry_rank_score", "selection_reason",
    "ranking_claim_boundary",
}
POSE_FIELDS = {
    "candidate_id", "rank", "conformation", "seed", "job_id", "job_hash",
    "model", "HADDOCK_score", "geometry_8x6b_summary",
    "geometry_9e6y_summary", "source_sha256", "target_sha256",
    "bundle_relpath", "claim_boundary",
}
LINEAGE_FIELDS = [
    "rank", "candidate_id", "sequence_sha256", "parent_id", "scaffold_id",
    "arm_id", "design_mode", "target_patch_id", "h3_regime",
    "backbone_group_id", "backbone_index", "mpnn_index", "cdr1", "cdr2",
    "cdr3", "cdr3_length", "full_sequence_cluster", "cdr3_cluster",
    "angle_family",
]
RANKED_FIELDS = [
    "rank", "candidate_id", "sequence", "geometry_rank_score", "r_dual_min",
    "r_8x6b", "r_9e6y", "r_dual_gap", "geometry_uncertainty",
    "generic_binding_prior", "developability_score",
    "expression_purity_risk_score", "abnativ_vhh_score",
    "max_positive_cdr_identity", "parent_id", "target_patch_id", "design_mode",
    "full_sequence_cluster", "cdr3_cluster", "selection_reason",
    "ranking_claim_boundary",
]


class ReleaseError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ReleaseError(f"Missing or empty table: {path}")
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fields = list(reader.fieldnames or [])
        if not fields or len(fields) != len(set(fields)):
            raise ReleaseError(f"Invalid table header: {path}")
        rows = list(reader)
    if not rows:
        raise ReleaseError(f"Table has no rows: {path}")
    return fields, rows, delimiter


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ReleaseError(f"Missing or empty JSON: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"Malformed JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ReleaseError(f"JSON root must be an object: {path}")
    return payload


def required(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if value is None or str(value).strip() == "":
        raise ReleaseError(f"Missing {field} for {row.get('candidate_id', '<unknown>')}")
    return str(value).strip()


def safe_component(value: str, label: str) -> str:
    if not value or value in {".", ".."} or any(char in value for char in "/\\\x00"):
        raise ReleaseError(f"Unsafe {label}: {value!r}")
    return value


def number(value: Any, label: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise ReleaseError(f"Invalid numeric {label}: {value!r}") from exc
    if not math.isfinite(output):
        raise ReleaseError(f"Non-finite numeric {label}: {value!r}")
    return output


def is_true(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "pass"}


def open_geometry(status: str) -> bool:
    normalized = status.strip().upper()
    return normalized in OPEN_GEOMETRY_STATUSES or (
        normalized.startswith("OPEN_")
        and any(token in normalized for token in ("USABLE", "AVAILABLE", "COMPLETE", "PASS"))
        and "SEALED" not in normalized
    )


def write_table(
    path: Path, rows: Iterable[Mapping[str, Any]], fields: Sequence[str], delimiter: str
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fields), delimiter=delimiter,
            lineterminator="\n", extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def validate_shortlist(path: Path, audit_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    fields, rows, _delimiter = read_table(path)
    missing = sorted(SHORTLIST_REQUIRED - set(fields))
    if missing:
        raise ReleaseError("Shortlist missing fields: " + ", ".join(missing))
    if len(rows) != 50:
        raise ReleaseError(f"Top50 shortlist must contain exactly 50 rows, found {len(rows)}")

    identifiers: list[str] = []
    sequence_hashes: list[str] = []
    ranks: list[int] = []
    for row in rows:
        candidate = safe_component(required(row, "candidate_id"), "candidate_id")
        identifiers.append(candidate)
        try:
            rank = int(required(row, "rank"))
        except ValueError as exc:
            raise ReleaseError(f"Invalid rank for {candidate}") from exc
        ranks.append(rank)
        sequence = required(row, "sequence").upper()
        if not sequence or set(sequence) - AA:
            raise ReleaseError(f"Non-standard amino-acid sequence for {candidate}")
        digest = required(row, "sequence_sha256").lower()
        if digest != sha256_bytes(sequence.encode("ascii")):
            raise ReleaseError(f"Sequence SHA256 mismatch for {candidate}")
        sequence_hashes.append(digest)
        if required(row, "source_cohort").upper() != "FULLQC290_PRIMARY":
            raise ReleaseError(f"Non-FullQC290 candidate in Top50: {candidate}")
        split = required(row, "v4d_teacher_model_split").upper()
        if split == "PROSPECTIVE_COMPUTATIONAL_TEST" or "SEALED" in split or "TEST" in split:
            raise ReleaseError(f"Refusing sealed/test candidate before pose access: {candidate}")
        if split not in OPEN_SPLITS:
            raise ReleaseError(f"Candidate is not in an open split: {candidate} ({split})")
        if not open_geometry(required(row, "geometry_status")):
            raise ReleaseError(f"Open geometry is incomplete for {candidate}")
        if not required(row, "full_qc_status").upper().startswith("COMPLETE_HARD_PASS"):
            raise ReleaseError(f"Full-QC hard gate failed for {candidate}")
        if is_true(required(row, "fast_hard_fail")):
            raise ReleaseError(f"Fast hard-fail candidate in Top50: {candidate}")
        if not is_true(required(row, "official_validator_pass")):
            raise ReleaseError(f"Official validator gate failed for {candidate}")
        if not is_true(required(row, "anarci_status")):
            raise ReleaseError(f"ANARCI gate failed for {candidate}")
        if required(row, "imgt_chain_type").upper() != "H":
            raise ReleaseError(f"Unexpected IMGT chain type for {candidate}")
        if required(row, "abnativ_status").upper() != "SCORED":
            raise ReleaseError(f"AbNatiV score is incomplete for {candidate}")
        if required(row, "monomer_status").upper() != "FROZEN_NBB2_SEQUENCE_VERIFIED":
            raise ReleaseError(f"Frozen NBB2 monomer is incomplete for {candidate}")
        if not is_true(required(row, "monomer_sequence_match")):
            raise ReleaseError(f"NBB2 monomer sequence mismatch for {candidate}")
        if not HEX64.fullmatch(required(row, "monomer_sha256").lower()):
            raise ReleaseError(f"Invalid NBB2 monomer hash for {candidate}")
        leakage = required(row, "leakage_status").upper()
        if leakage in {"KNOWN_POSITIVE", "LEAKAGE", "FAIL"}:
            raise ReleaseError(f"Known-positive/leakage candidate in Top50: {candidate}")
        if row.get("exact_positive_id", "").strip():
            raise ReleaseError(f"Exact positive identity present for {candidate}")
        for field in (
            "parent_id", "target_patch_id", "design_mode", "backbone_index",
            "mpnn_index", "cdr1", "cdr2", "cdr3", "full_sequence_cluster",
            "cdr3_cluster",
        ):
            required(row, field)
        if required(row, "generic_prior_claim_boundary") != GENERIC_PRIOR_CLAIM_BOUNDARY:
            raise ReleaseError(f"Generic-prior claim boundary drift for {candidate}")
        if required(row, "ranking_claim_boundary") != RANKING_CLAIM_BOUNDARY:
            raise ReleaseError(f"Geometry-ranking claim boundary drift for {candidate}")
        if number(required(row, "max_positive_cdr_identity"), "max_positive_cdr_identity") >= 0.80:
            raise ReleaseError(f"Positive CDR identity >= 0.80 for {candidate}")
        for field in (
            "geometry_rank_score", "r_8x6b", "r_9e6y", "r_dual_min",
            "r_dual_gap", "geometry_uncertainty", "developability_score",
            "expression_purity_risk_score", "abnativ_vhh_score",
            "generic_binding_prior", "successful_seeds_8x6b", "successful_seeds_9e6y",
        ):
            number(required(row, field), field)
        if min(
            number(row["successful_seeds_8x6b"], "successful_seeds_8x6b"),
            number(row["successful_seeds_9e6y"], "successful_seeds_9e6y"),
        ) < 2:
            raise ReleaseError(f"Fewer than two successful seeds for {candidate}")

    if ranks != list(range(1, 51)):
        raise ReleaseError("Top50 ranks must be exactly 1..50 in row order")
    if len(set(identifiers)) != 50 or len(set(sequence_hashes)) != 50:
        raise ReleaseError("Top50 candidate IDs and sequence hashes must be unique")

    audit = load_json(audit_path)
    if audit.get("status") != "PASS_OPEN_GEOMETRY_SHORTLIST":
        raise ReleaseError("Geometry shortlist audit is not PASS")
    if audit.get("shortlist_count") != 50 or audit.get("sealed_fullqc_excluded_count") != 32:
        raise ReleaseError("Geometry shortlist audit counts do not close")
    if audit.get("eligible_open_rows") != 258:
        raise ReleaseError("Geometry shortlist audit does not contain open258")
    if audit.get("output_sha256", {}).get("shortlist50") != sha256_file(path):
        raise ReleaseError("Geometry shortlist audit is not hash-bound to this Top50")
    if audit.get("shortlist_parent_max", 99) > 3:
        raise ReleaseError("Geometry shortlist parent cap was not enforced")
    if audit.get("shortlist_parent_patch_mode_max", 99) > 2:
        raise ReleaseError("Geometry shortlist parent/patch/mode cap was not enforced")
    if audit.get("shortlist_cdr3_cluster_max", 99) > 2:
        raise ReleaseError("Geometry shortlist CDR3 cap was not enforced")
    actual_parent_max = max(Counter(row["parent_id"] for row in rows).values())
    actual_combo_max = max(
        Counter(
            (row["parent_id"], row["target_patch_id"], row["design_mode"])
            for row in rows
        ).values()
    )
    actual_cdr3_max = max(Counter(row["cdr3_cluster"] for row in rows).values())
    if actual_parent_max > 3 or actual_parent_max != audit.get("shortlist_parent_max"):
        raise ReleaseError("Actual Top50 parent cap does not match the audit")
    if actual_combo_max > 2 or actual_combo_max != audit.get("shortlist_parent_patch_mode_max"):
        raise ReleaseError("Actual Top50 parent/patch/mode cap does not match the audit")
    if actual_cdr3_max > 2 or actual_cdr3_max != audit.get("shortlist_cdr3_cluster_max"):
        raise ReleaseError("Actual Top50 CDR3 cap does not match the audit")
    return fields, rows


def validate_top10(
    path: Path, shortlist: list[dict[str, str]], verdicts: Mapping[str, dict[str, str]]
) -> list[dict[str, str]]:
    fields, rows, _delimiter = read_table(path)
    required_fields = {"candidate_id", "portfolio_rank", "selection_reason"}
    missing = sorted(required_fields - set(fields))
    if missing:
        raise ReleaseError("Top10 selection missing fields: " + ", ".join(missing))
    if len(rows) != 10:
        raise ReleaseError(f"Top10 selection must contain exactly 10 rows, found {len(rows)}")
    by_candidate = {row["candidate_id"]: row for row in shortlist}
    selected: list[dict[str, str]] = []
    for index, selection in enumerate(rows, start=1):
        candidate = safe_component(required(selection, "candidate_id"), "candidate_id")
        try:
            portfolio_rank = int(required(selection, "portfolio_rank"))
        except ValueError as exc:
            raise ReleaseError(f"Invalid Top10 portfolio_rank for {candidate}") from exc
        if portfolio_rank != index:
            raise ReleaseError("Top10 portfolio ranks must be exactly 1..10 in row order")
        if candidate not in by_candidate or int(by_candidate[candidate]["rank"]) > 20:
            raise ReleaseError(f"Top10 candidate is not in pose-reviewed Top20: {candidate}")
        verdict = verdicts.get(candidate)
        if verdict is None:
            raise ReleaseError(f"Top10 candidate lacks a pose verdict: {candidate}")
        if verdict["verdict"] not in ACCEPTED_TOP10_VERDICTS:
            raise ReleaseError(f"Top10 candidate has unresolved/rejected pose verdict: {candidate}")
        merged = dict(by_candidate[candidate])
        merged["portfolio_rank"] = str(portfolio_rank)
        merged["top10_selection_reason"] = required(selection, "selection_reason")
        merged["pose_review_verdict"] = verdict["verdict"]
        merged["pose_review_reviewer"] = verdict["reviewer"]
        merged["pose_review_notes"] = verdict["review_notes"]
        selected.append(merged)

    if len({row["candidate_id"] for row in selected}) != 10:
        raise ReleaseError("Top10 contains duplicate candidates")
    cdr3_counts = Counter(row["cdr3_cluster"] for row in selected)
    parent_counts = Counter(row["parent_id"] for row in selected)
    patches = {row["target_patch_id"] for row in selected}
    if len(cdr3_counts) < 5 or max(cdr3_counts.values()) > 2:
        raise ReleaseError("Top10 must contain >=5 CDR3 clusters with max 2 per cluster")
    if len(parent_counts) < 4 or max(parent_counts.values()) > 2:
        raise ReleaseError("Top10 must contain >=4 parent families with max 2 per parent")
    if patches != {"A_CENTER", "B_LOWER", "C_CROSS"}:
        raise ReleaseError("Top10 must represent A_CENTER, B_LOWER, and C_CROSS")
    return selected


def validate_verdicts(path: Path, expected_candidates: set[str]) -> dict[str, dict[str, str]]:
    fields, rows, _delimiter = read_table(path)
    missing = sorted({"candidate_id", "verdict", "reviewer", "review_notes"} - set(fields))
    if missing:
        raise ReleaseError("Pose verdict table missing fields: " + ", ".join(missing))
    if len(rows) != 20:
        raise ReleaseError(f"Pose verdict table must contain exactly 20 rows, found {len(rows)}")
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate = required(row, "candidate_id")
        verdict = required(row, "verdict").upper()
        if verdict not in ALL_VERDICTS:
            raise ReleaseError(f"Unsupported pose verdict for {candidate}: {verdict}")
        if candidate in output:
            raise ReleaseError(f"Duplicate pose verdict for {candidate}")
        output[candidate] = {
            "candidate_id": candidate,
            "verdict": verdict,
            "reviewer": required(row, "reviewer"),
            "review_notes": required(row, "review_notes"),
        }
    if set(output) != expected_candidates:
        raise ReleaseError("Pose verdict IDs do not exactly match ranked Top20")
    return output


def validate_pose_bundle(
    manifest_path: Path,
    audit_path: Path,
    shortlist_path: Path,
    shortlist: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    fields, rows, _delimiter = read_table(manifest_path)
    missing = sorted(POSE_FIELDS - set(fields))
    if missing:
        raise ReleaseError("Pose manifest missing fields: " + ", ".join(missing))
    if len(rows) != 360:
        raise ReleaseError(f"Pose manifest must contain exactly 360 rows, found {len(rows)}")
    top20 = {row["candidate_id"]: row for row in shortlist[:20]}
    by_candidate: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        candidate = required(row, "candidate_id")
        if candidate not in top20:
            raise ReleaseError(f"Pose manifest contains a non-Top20 candidate: {candidate}")
        if required(row, "rank") != top20[candidate]["rank"]:
            raise ReleaseError(f"Pose rank mismatch for {candidate}")
        conformation = required(row, "conformation").lower()
        seed = required(row, "seed")
        if conformation not in CONFORMATIONS or seed not in SEEDS:
            raise ReleaseError(f"Unsupported pose conformation/seed for {candidate}")
        safe_component(required(row, "model"), "pose model")
        safe_component(required(row, "job_id"), "job_id")
        if not HEX64.fullmatch(required(row, "job_hash").lower()):
            raise ReleaseError(f"Invalid pose job hash for {candidate}")
        number(required(row, "HADDOCK_score"), "HADDOCK_score")
        for field in ("geometry_8x6b_summary", "geometry_9e6y_summary"):
            try:
                summary = json.loads(required(row, field))
            except json.JSONDecodeError as exc:
                raise ReleaseError(f"Malformed {field} for {candidate}") from exc
            if not isinstance(summary, dict) or not summary:
                raise ReleaseError(f"Empty {field} for {candidate}")
        source_hash = required(row, "source_sha256").lower()
        target_hash = required(row, "target_sha256").lower()
        if source_hash != target_hash or not HEX64.fullmatch(target_hash):
            raise ReleaseError(f"Pose source/target hash mismatch for {candidate}")
        relpath = Path(required(row, "bundle_relpath"))
        if relpath.is_absolute() or ".." in relpath.parts:
            raise ReleaseError(f"Unsafe pose bundle path for {candidate}: {relpath}")
        by_candidate[candidate].append(row)
    if set(by_candidate) != set(top20):
        raise ReleaseError("Pose manifest candidate set does not close against Top20")
    for candidate, candidate_rows in by_candidate.items():
        if len(candidate_rows) != 18:
            raise ReleaseError(f"Expected 18 poses for {candidate}, found {len(candidate_rows)}")
        counts = Counter((row["conformation"].lower(), row["seed"]) for row in candidate_rows)
        expected = {(conformation, seed): 3 for conformation in CONFORMATIONS for seed in SEEDS}
        if counts != expected:
            raise ReleaseError(f"Pose 2x3x3 closure failed for {candidate}")

    audit = load_json(audit_path)
    if audit.get("status") != "PASS_OPEN_ONLY_V4D_POSE_REVIEW":
        raise ReleaseError("Pose-review audit is not PASS")
    if (
        audit.get("candidate_count") != 20
        or audit.get("successful_job_count") != 120
        or audit.get("manifest_pose_count") != 360
    ):
        raise ReleaseError("Pose-review audit counts do not close")
    if audit.get("input_sha256", {}).get("shortlist") != sha256_file(shortlist_path):
        raise ReleaseError("Pose-review audit is not bound to this Top50 shortlist")
    return fields, rows


def frozen_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def freeze_inputs_and_pose_sources(
    outdir: Path,
    args: argparse.Namespace,
    pose_fields: list[str],
    pose_rows: list[dict[str, str]],
) -> tuple[Path, list[dict[str, str]]]:
    frozen = outdir / "frozen_inputs"
    frozen.mkdir(parents=True)
    frozen_copy(args.shortlist, frozen / "shortlist50.tsv")
    frozen_copy(args.shortlist_audit, frozen / "geometry_shortlist_audit.json")
    frozen_copy(args.top10_selection, frozen / "top10_selection.tsv")
    frozen_copy(args.pose_audit, frozen / "pose_review_audit.json")
    frozen_copy(args.pose_verdicts, frozen / "pose_review_verdicts.tsv")

    normalized: list[dict[str, str]] = []
    pose_root = args.pose_manifest.resolve().parent
    for row in pose_rows:
        item = dict(row)
        source = (pose_root / row["bundle_relpath"]).resolve()
        try:
            source.relative_to(pose_root)
        except ValueError as exc:
            raise ReleaseError(f"Top20 pose escapes pose bundle: {source}") from exc
        if not source.is_file() or source.stat().st_size == 0:
            raise ReleaseError(f"Missing Top20 pose source: {source}")
        if sha256_file(source) != row["target_sha256"]:
            raise ReleaseError(f"Top20 pose hash mismatch: {source}")
        relpath = Path("top20_pose_sources") / row["candidate_id"] / row["conformation"] / row["seed"] / row["model"]
        target = frozen / relpath
        frozen_copy(source, target)
        item["bundle_relpath"] = relpath.as_posix()
        normalized.append(item)
    frozen_manifest = frozen / "pose_review_manifest.tsv"
    write_table(frozen_manifest, normalized, pose_fields, "\t")
    return frozen_manifest, normalized


def write_fasta(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="ascii") as handle:
        for row in rows:
            handle.write(
                f">{row['candidate_id']} rank={row['rank']} "
                f"computational_priority_score={row['geometry_rank_score']}\n"
            )
            handle.write(row["sequence"].upper() + "\n")


def write_top10_fasta(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="ascii") as handle:
        for row in rows:
            handle.write(
                f">{row['candidate_id']} portfolio_rank={row['portfolio_rank']} "
                f"top50_rank={row['rank']}\n{row['sequence'].upper()}\n"
            )


def build_dossiers(
    outdir: Path,
    top10: list[dict[str, str]],
    pose_rows: list[dict[str, str]],
) -> None:
    root = outdir / "submission_top10_dossier"
    root.mkdir()
    by_candidate: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pose_rows:
        if row["candidate_id"] in {item["candidate_id"] for item in top10}:
            by_candidate[row["candidate_id"]].append(row)
    for row in top10:
        candidate = row["candidate_id"]
        folder = root / f"{int(row['portfolio_rank']):02d}_{candidate}"
        folder.mkdir()
        pose_lines = []
        for pose in sorted(
            by_candidate[candidate],
            key=lambda item: (item["conformation"], int(item["seed"]), float(item["HADDOCK_score"]), item["model"]),
        ):
            source = outdir / "frozen_inputs" / pose["bundle_relpath"]
            destination = folder / "poses" / pose["conformation"] / pose["seed"] / pose["model"]
            frozen_copy(source, destination)
            if sha256_file(destination) != pose["target_sha256"]:
                raise ReleaseError(f"Dossier pose copy hash mismatch: {destination}")
            pose_lines.append(
                f"| {pose['conformation']} | {pose['seed']} | {pose['model']} | "
                f"{pose['HADDOCK_score']} | `{destination.relative_to(folder).as_posix()}` |"
            )
        dossier = f"""# Top10 computational dossier: {candidate}

- Portfolio rank: {row['portfolio_rank']}
- Top50 rank: {row['rank']}
- Parent: {row['parent_id']}
- Patch/mode: {row['target_patch_id']} / {row['design_mode']}
- CDR3: `{row['cdr3']}`
- CDR3 cluster: `{row['cdr3_cluster']}`
- R_8X6B / R_9E6Y: {row['r_8x6b']} / {row['r_9e6y']}
- R_dual_min / gap: {row['r_dual_min']} / {row['r_dual_gap']}
- Computational pose verdict: {row['pose_review_verdict']}
- Reviewer: {row['pose_review_reviewer']}
- Review notes: {row['pose_review_notes']}
- Selection reason: {row['top10_selection_reason']}

## Copied poses

| Conformation | Seed | Model | HADDOCK score | Relative path |
| --- | ---: | --- | ---: | --- |
{os.linesep.join(pose_lines)}

## Claim boundary

{CLAIM_BOUNDARY}
"""
        (folder / "DOSSIER.md").write_text(dossier, encoding="utf-8")


def write_provenance(outdir: Path, hashes: Mapping[str, str]) -> None:
    rows = "\n".join(f"| `{name}` | `{digest}` |" for name, digest in sorted(hashes.items()))
    content = f"""# Source and model provenance

This release is derived from the frozen FullQC290 open-split shortlist and the
real V4-D Top20 pose-review bundle. Generic binding output remains a weak prior;
TNP, IgFold, and NBB2 are structural/developability annotations. No field in
this release is a calibrated binder probability, Kd, competition result, or
experimental blocking measurement.

| Frozen input | SHA256 |
| --- | --- |
{rows}

## Claim boundary

{CLAIM_BOUNDARY}
"""
    (outdir / "SOURCE_AND_MODEL_PROVENANCE.md").write_text(content, encoding="utf-8")


def write_clean_replay_script(outdir: Path) -> None:
    script = r'''#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON=${PYTHON:-python3}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
(cd "$ROOT" && sha256sum -c SHA256SUMS)
"$PYTHON" "$ROOT/tools/prepare_pvrig_submission_release.py" \
  --shortlist "$ROOT/frozen_inputs/shortlist50.tsv" \
  --shortlist-audit "$ROOT/frozen_inputs/geometry_shortlist_audit.json" \
  --top10-selection "$ROOT/frozen_inputs/top10_selection.tsv" \
  --pose-manifest "$ROOT/frozen_inputs/pose_review_manifest.tsv" \
  --pose-audit "$ROOT/frozen_inputs/pose_review_audit.json" \
  --pose-verdicts "$ROOT/frozen_inputs/pose_review_verdicts.tsv" \
  --outdir "$TMP/release"
cmp "$ROOT/SHA256SUMS" "$TMP/release/SHA256SUMS"
ORIGINAL_ARCHIVE=$(sha256sum "$ROOT/pvrig_submission_release_v1.tar.gz" | awk '{print $1}')
REPLAY_ARCHIVE=$(sha256sum "$TMP/release/pvrig_submission_release_v1.tar.gz" | awk '{print $1}')
[[ "$ORIGINAL_ARCHIVE" == "$REPLAY_ARCHIVE" ]]
ROOT="$ROOT" ORIGINAL_ARCHIVE="$ORIGINAL_ARCHIVE" REPLAY_ARCHIVE="$REPLAY_ARCHIVE" \
  "$PYTHON" - <<'PY'
import hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
root=Path(os.environ["ROOT"])
payload={
  "schema_version":"pvrig_submission_clean_replay_receipt_v1",
  "status":"PASS_CLEAN_REPLAY_BYTE_IDENTICAL",
  "claim_boundary":"Competition computational-priority package replay only; not biological validation.",
  "release_sha256sums_sha256":hashlib.sha256((root/"SHA256SUMS").read_bytes()).hexdigest(),
  "release_archive_sha256":os.environ["ORIGINAL_ARCHIVE"],
  "replay_archive_sha256":os.environ["REPLAY_ARCHIVE"],
  "replayed_at":datetime.now(timezone.utc).isoformat(),
}
(root/"clean_replay_receipt.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
PY
echo PASS_CLEAN_REPLAY_BYTE_IDENTICAL
'''
    target = outdir / "clean_replay.sh"
    target.write_text(script, encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_sha256sums(outdir: Path) -> Path:
    output = outdir / "SHA256SUMS"
    excluded = {"SHA256SUMS", "clean_replay_receipt.json", "pvrig_submission_release_v1.tar.gz"}
    files = sorted(
        path for path in outdir.rglob("*")
        if path.is_file() and path.name not in excluded
    )
    output.write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(outdir).as_posix()}\n"
            for path in files
        ),
        encoding="ascii",
    )
    return output


def write_archive(outdir: Path) -> Path:
    archive = outdir / "pvrig_submission_release_v1.tar.gz"
    paths = sorted(
        path for path in outdir.rglob("*")
        if path.is_file() and path != archive and path.name != "clean_replay_receipt.json"
    )
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as bundle:
                for path in paths:
                    arcname = path.relative_to(outdir).as_posix()
                    info = bundle.gettarinfo(str(path), arcname=arcname)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o755 if path.suffix == ".sh" else 0o644
                    with path.open("rb") as handle:
                        bundle.addfile(info, handle)
    return archive


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shortlist", type=Path, required=True)
    parser.add_argument("--shortlist-audit", type=Path, required=True)
    parser.add_argument("--top10-selection", type=Path, required=True)
    parser.add_argument("--pose-manifest", type=Path, required=True)
    parser.add_argument("--pose-audit", type=Path, required=True)
    parser.add_argument("--pose-verdicts", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.outdir.exists() and any(args.outdir.iterdir()):
        raise ReleaseError(f"Refusing to overwrite non-empty outdir: {args.outdir}")

    shortlist_fields, shortlist = validate_shortlist(args.shortlist, args.shortlist_audit)
    pose_fields, pose_rows = validate_pose_bundle(
        args.pose_manifest, args.pose_audit, args.shortlist, shortlist
    )
    top20_ids = {row["candidate_id"] for row in shortlist[:20]}
    verdicts = validate_verdicts(args.pose_verdicts, top20_ids)
    top10 = validate_top10(args.top10_selection, shortlist, verdicts)
    top10_ids = {row["candidate_id"] for row in top10}

    args.outdir.mkdir(parents=True, exist_ok=True)
    frozen_manifest, normalized_poses = freeze_inputs_and_pose_sources(
        args.outdir, args, pose_fields, pose_rows
    )
    frozen = args.outdir / "frozen_inputs"
    frozen_hashes = {
        path.name: sha256_file(path)
        for path in sorted(frozen.iterdir())
        if path.is_file()
    }

    write_fasta(args.outdir / "submission_top50.fasta", shortlist)
    write_table(args.outdir / "submission_top50_ranked.csv", shortlist, RANKED_FIELDS, ",")
    write_table(args.outdir / "submission_top50_lineage.csv", shortlist, LINEAGE_FIELDS, ",")
    evidence_rows = []
    top10_by_id = {row["candidate_id"]: row for row in top10}
    for row in shortlist:
        evidence = dict(row)
        selected = top10_by_id.get(row["candidate_id"])
        evidence["top10_portfolio_rank"] = selected["portfolio_rank"] if selected else ""
        evidence["pose_review_verdict"] = verdicts.get(row["candidate_id"], {}).get("verdict", "NOT_TOP20")
        evidence_rows.append(evidence)
    evidence_fields = shortlist_fields + ["top10_portfolio_rank", "pose_review_verdict"]
    write_table(args.outdir / "submission_top50_evidence.tsv", evidence_rows, evidence_fields, "\t")

    top10_fields = [
        "portfolio_rank", "rank", "candidate_id", "sequence", "sequence_sha256",
        "parent_id", "target_patch_id", "design_mode", "cdr3", "cdr3_cluster",
        "geometry_rank_score", "r_8x6b", "r_9e6y", "r_dual_min", "r_dual_gap",
        "developability_score", "expression_purity_risk_score",
        "generic_binding_prior", "pose_review_verdict", "pose_review_reviewer",
        "pose_review_notes", "top10_selection_reason", "ranking_claim_boundary",
    ]
    write_table(args.outdir / "submission_top10.csv", top10, top10_fields, ",")
    write_top10_fasta(args.outdir / "submission_top10.fasta", top10)
    build_dossiers(args.outdir, top10, normalized_poses)
    write_provenance(args.outdir, frozen_hashes)

    tools = args.outdir / "tools"
    tools.mkdir()
    frozen_copy(Path(__file__).resolve(), tools / Path(__file__).name)
    write_clean_replay_script(args.outdir)

    recipe = {
        "schema_version": "pvrig_submission_release_recipe_v1",
        "builder_sha256": sha256_file(Path(__file__).resolve()),
        "claim_boundary": CLAIM_BOUNDARY,
        "frozen_inputs": frozen_hashes,
        "command_inputs": {
            "shortlist": "frozen_inputs/shortlist50.tsv",
            "shortlist_audit": "frozen_inputs/geometry_shortlist_audit.json",
            "top10_selection": "frozen_inputs/top10_selection.tsv",
            "pose_manifest": "frozen_inputs/pose_review_manifest.tsv",
            "pose_audit": "frozen_inputs/pose_review_audit.json",
            "pose_verdicts": "frozen_inputs/pose_review_verdicts.tsv",
        },
    }
    write_json(args.outdir / "release_recipe.json", recipe)
    audit = {
        "schema_version": "pvrig_submission_release_audit_v1",
        "status": "PASS_COMPUTATIONAL_SUBMISSION_PACKAGE_READY",
        "claim_boundary": CLAIM_BOUNDARY,
        "top50_count": len(shortlist),
        "top10_count": len(top10),
        "top20_pose_candidate_count": len(top20_ids),
        "top20_pose_manifest_count": len(pose_rows),
        "frozen_top20_pose_count": len(normalized_poses),
        "top10_copied_pose_count": sum(
            row["candidate_id"] in top10_ids for row in normalized_poses
        ),
        "top10_unique_parent_count": len({row["parent_id"] for row in top10}),
        "top10_unique_cdr3_cluster_count": len({row["cdr3_cluster"] for row in top10}),
        "top10_patch_count": len({row["target_patch_id"] for row in top10}),
        "sealed_or_test_candidate_count": 0,
        "known_positive_or_exact_match_count": 0,
        "frozen_pose_manifest_sha256": sha256_file(frozen_manifest),
        "clean_replay_required": True,
    }
    write_json(args.outdir / "release_audit.json", audit)
    readme = f"""# PVRIG computational submission release

- Top50: 50 unique open FullQC290 candidates.
- Top10: 10 manually accepted computational pose-review candidates.
- Top20 pose manifest: 360 poses; Top10 dossier copies: 180 poses.
- Run `./clean_replay.sh` to generate `clean_replay_receipt.json`.

## Claim boundary

{CLAIM_BOUNDARY}
"""
    (args.outdir / "README_ZH.md").write_text(readme, encoding="utf-8")
    write_sha256sums(args.outdir)
    write_archive(args.outdir)
    return audit


def main(argv: Sequence[str] | None = None) -> int:
    audit = run(parse_args(argv))
    print(json.dumps(audit, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
