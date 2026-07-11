#!/usr/bin/env python3
"""Build Phase 2 V2.5 evidence and external-usage manifests from local data."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from phase2_v2_5_contracts import (
    CANONICAL_FIELDS,
    EXTERNAL_MANIFEST_FIELDS,
    EXTERNAL_MANIFEST_VERSION,
    PVRIG_TARGET_ID,
    SCHEMA_VERSION,
    sequence_sha256,
    validate_evidence_registry,
    validate_external_manifest,
)

DATASET_VERSION = "phase2_v2_5_local_p0_20260711"
TARGET_CONSTRUCT = "Q6DKI7_structural_ectodomain_proxy_39_171"
NANOBIND_CHECKOUT = Path("datasets/10_github_repos/NanoBind")
NANOBIND_AFFINITY_FILE = Path("data/affinity/all.csv")
CONTACT_MAP_FILE = Path("experiments/phase2_5080_v1/prepared/structure_contact_maps_v3_clustered.jsonl")
NANOBIND_AFFINITY_COLUMNS = {
    "ID",
    "nanobody_chain",
    "seq_nanobody",
    "antigen_chain",
    "seq_antigen",
    "affinity",
}


def read_fasta_sequence(path: Path) -> str:
    parts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            continue
        parts.append(line.strip())
    sequence = "".join(parts).upper()
    if not sequence:
        raise ValueError(f"No FASTA sequence in {path}")
    return sequence


def _str_or_empty(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _clean_sequence(value: Any) -> str:
    return "".join(_str_or_empty(value).split()).upper()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_from_checkout(checkout: Path) -> str:
    git_dir = checkout / ".git"
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        raise ValueError(f"NanoBind checkout lacks git HEAD: {head_path}")
    head = head_path.read_text(encoding="ascii").strip()
    if head.startswith("ref: "):
        ref = head[5:].strip()
        loose_ref = git_dir / ref
        if loose_ref.is_file():
            commit = loose_ref.read_text(encoding="ascii").strip()
        else:
            commit = ""
            packed_refs = git_dir / "packed-refs"
            if packed_refs.is_file():
                for line in packed_refs.read_text(encoding="ascii").splitlines():
                    if line.startswith(("#", "^")):
                        continue
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref:
                        commit = parts[0]
                        break
    else:
        commit = head
    if len(commit) != 40 or any(char not in "0123456789abcdefABCDEF" for char in commit):
        raise ValueError(f"Cannot resolve exact NanoBind git commit from {head_path}")
    return commit.lower()


def base_record(
    *,
    sample_id: str,
    vhh_sequence: str,
    target_sequence: str,
    source_id: str,
    source_path: Path | str,
    family_id: str,
    leakage_group_id: str,
    split_group_id: str,
    target_id: str = PVRIG_TARGET_ID,
    target_construct: str = TARGET_CONSTRUCT,
    dataset_version: str = DATASET_VERSION,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "vhh_sequence": vhh_sequence,
        "sequence_sha256": sequence_sha256(vhh_sequence),
        "target_id": target_id,
        "target_sequence_sha256": sequence_sha256(target_sequence),
        "target_construct": target_construct,
        "label_axis": "control",
        "evidence_level": "E0",
        "ground_truth_kind": "control",
        "label_value": "",
        "label_unit": "",
        "label_direction": "",
        "assay_type": "",
        "assay_batch": "",
        "replicate_count": "",
        "source_id": source_id,
        "source_path_or_locator": str(source_path),
        "allowed_use": "CALIBRATION_LEAKAGE_CONTROL_ONLY",
        "forbidden_use": "ORDINARY_TRAIN|ORDINARY_TEST|CANDIDATE_RANKING|FORMAL_CLAIM|REDISTRIBUTION",
        "family_id": family_id,
        "leakage_group_id": leakage_group_id,
        "split_group_id": split_group_id,
        "sealed_status": "NOT_FORMAL",
        "dataset_version": dataset_version,
        "mutation": "",
        "reference_sample_id": "",
        "pose_id": "",
        "pose_qc_status": "",
        "missing_reason": "no_primary_assay_label_or_not_applicable_for_this_evidence_lane",
        "ordinary_train_allowed": "false",
        "ordinary_test_allowed": "false",
        "candidate_ranking_allowed": "false",
        "ordinary_bce_eligible": "false",
        "lane": "calibration_or_control_only",
        "notes": "",
    }


def build_contact_site_rows(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = root / CONTACT_MAP_FILE
    details: dict[str, Any] = {
        "source_path": str(path),
        "status": "EXCLUDED_SOURCE_MISSING",
        "source_row_count": 0,
        "included_complex_count": 0,
        "duplicate_source_rows_merged": 0,
        "excluded_row_count": 0,
        "exclusion_reasons": {},
    }
    if not path.is_file():
        details["exclusion_reasons"] = {"source_file_missing": 1}
        return [], details

    records: dict[str, dict[str, Any]] = {}
    signatures: dict[str, tuple[str, ...]] = {}
    source_lines: dict[str, list[int]] = {}
    exclusion_reasons: dict[str, int] = {}

    def exclude(reason: str) -> None:
        details["excluded_row_count"] += 1
        exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            details["source_row_count"] += 1
            try:
                source = json.loads(line)
            except json.JSONDecodeError:
                exclude("invalid_json")
                continue
            complex_id = _str_or_empty(source.get("complex_id")).strip()
            vhh_sequence = _clean_sequence(source.get("vhh_seq"))
            target_sequence = _clean_sequence(source.get("antigen_seq"))
            if not complex_id:
                exclude("missing_complex_id")
                continue
            if not vhh_sequence:
                exclude("missing_vhh_sequence")
                continue
            if not target_sequence:
                exclude("missing_target_sequence")
                continue
            if not source.get("positive_pairs"):
                exclude("missing_positive_contact_pairs")
                continue

            positive_contact_digest = hashlib.sha256(
                json.dumps(source.get("positive_pairs"), separators=(",", ":")).encode("ascii")
            ).hexdigest()
            signature = (
                vhh_sequence,
                target_sequence,
                _str_or_empty(source.get("pdb")),
                _str_or_empty(source.get("vhh_chain")),
                _str_or_empty(source.get("antigen_chain")),
                _str_or_empty(source.get("split")),
                _str_or_empty(source.get("split_group_id")),
                _str_or_empty(source.get("vhh_cluster_id")),
                _str_or_empty(source.get("antigen_cluster_id")),
                positive_contact_digest,
            )
            if complex_id in records:
                if signatures[complex_id] != signature:
                    raise ValueError(f"Conflicting contact records share complex_id={complex_id}")
                source_lines[complex_id].append(line_number)
                details["duplicate_source_rows_merged"] += 1
                continue

            target_hash = sequence_sha256(target_sequence)
            pdb_id = _str_or_empty(source.get("pdb"))
            vhh_chain = _str_or_empty(source.get("vhh_chain"))
            antigen_chain = _str_or_empty(source.get("antigen_chain"))
            source_split_group = _str_or_empty(source.get("split_group_id"))
            antigen_cluster = _str_or_empty(source.get("antigen_cluster_id"))
            record = base_record(
                sample_id=f"contact::{complex_id}",
                vhh_sequence=vhh_sequence,
                target_sequence=target_sequence,
                target_id=f"STRUCTURE_TARGET_SHA256_{target_hash}",
                target_construct=f"{pdb_id} antigen_chain={antigen_chain}; sequence from clustered contact map",
                source_id="structure_contact_maps_v3_clustered",
                source_path=path,
                family_id=antigen_cluster or f"structure_target_{target_hash}",
                leakage_group_id=source_split_group or f"contact_complex_{complex_id}",
                split_group_id=source_split_group or f"contact_complex_{complex_id}",
                dataset_version="structure_contact_maps_v3_clustered",
            )
            record.update(
                {
                    "label_axis": "contact",
                    "evidence_level": "E1",
                    "ground_truth_kind": "structural_contact_site",
                    "allowed_use": "CONTACT_SITE_GUARDRAIL_ONLY",
                    "forbidden_use": "WHOLE_PAIR_BINDING_TRUTH|VERIFIED_NONBINDER|BLOCKER_TRUTH|ORDINARY_BCE|FORMAL_PRIMARY|REDISTRIBUTION",
                    "missing_reason": "contact_pairs_are_stored_in_source_jsonl; scalar_assay_and_replicate_fields_not_applicable",
                    "ordinary_train_allowed": "true",
                    "ordinary_test_allowed": "true",
                    "candidate_ranking_allowed": "false",
                    "ordinary_bce_eligible": "false",
                    "lane": "contact_site_guardrail",
                    "notes": (
                        f"pdb_id={pdb_id}; vhh_chain={vhh_chain}; antigen_chain={antigen_chain}; "
                        f"positive_contact_pairs={len(source['positive_pairs'])}; "
                        f"negative_contact_pairs={len(source.get('negative_pairs', []))}; "
                        f"source_split={_str_or_empty(source.get('split'))}; source_jsonl_lines="
                    ),
                }
            )
            records[complex_id] = record
            signatures[complex_id] = signature
            source_lines[complex_id] = [line_number]

    for complex_id, record in records.items():
        line_list = ",".join(str(value) for value in source_lines[complex_id])
        record["source_path_or_locator"] = f"{path}#jsonl_lines={line_list}"
        record["notes"] += line_list

    details["included_complex_count"] = len(records)
    details["exclusion_reasons"] = exclusion_reasons
    if records and exclusion_reasons:
        details["status"] = "INCLUDED_WITH_EXCLUSIONS"
    elif records:
        details["status"] = "INCLUDED"
    else:
        details["status"] = "EXCLUDED_NO_VALID_SEQUENCE_RECORDS"
        if not exclusion_reasons:
            details["exclusion_reasons"] = {"no_source_rows": 1}
    return list(records.values()), details


def _valid_protein_sequence(sequence: str) -> bool:
    return bool(sequence) and sequence.isascii() and sequence.isalpha()


def _join_unique(values: pd.Series) -> str:
    return ",".join(dict.fromkeys(_str_or_empty(value) for value in values))


def build_nanobind_affinity_rows(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checkout = root / NANOBIND_CHECKOUT
    path = checkout / NANOBIND_AFFINITY_FILE
    if not path.is_file():
        raise ValueError(f"NanoBind measured affinity dataset is missing: {path}")
    commit = _git_commit_from_checkout(checkout)
    source_sha256 = _sha256_file(path)
    raw = pd.read_csv(path)
    missing_columns = sorted(NANOBIND_AFFINITY_COLUMNS - set(raw.columns))
    if missing_columns:
        raise ValueError(f"NanoBind affinity/all.csv missing columns: {missing_columns}")

    work = raw.copy()
    work["_csv_line"] = work.index + 2
    work["_vhh_sequence"] = work["seq_nanobody"].map(_clean_sequence)
    work["_target_sequence"] = work["seq_antigen"].map(_clean_sequence)
    work["_affinity_kd_m"] = pd.to_numeric(work["affinity"], errors="coerce")
    valid_sequence = work["_vhh_sequence"].map(_valid_protein_sequence) & work["_target_sequence"].map(_valid_protein_sequence)
    valid_affinity = work["_affinity_kd_m"].map(
        lambda value: pd.notna(value) and math.isfinite(float(value)) and float(value) > 0
    )
    valid = work[valid_sequence & valid_affinity].copy()
    invalid_sequence_count = int((~valid_sequence).sum())
    invalid_affinity_count = int((valid_sequence & ~valid_affinity).sum())

    rows: list[dict[str, Any]] = []
    grouped = valid.groupby(["_vhh_sequence", "_target_sequence"], sort=False, dropna=False)
    duplicate_group_count = 0
    for (vhh_sequence, target_sequence), group in grouped:
        if len(group) > 1:
            duplicate_group_count += 1
        vhh_hash = sequence_sha256(vhh_sequence)
        target_hash = sequence_sha256(target_sequence)
        pair_hash = hashlib.sha256(f"{vhh_hash}:{target_hash}".encode("ascii")).hexdigest()
        source_lines = ",".join(str(int(value)) for value in group["_csv_line"])
        source_ids = _join_unique(group["ID"])
        nanobody_chains = _join_unique(group["nanobody_chain"])
        antigen_chains = _join_unique(group["antigen_chain"])
        record = base_record(
            sample_id=f"nanobind_affinity_pair_sha256_{pair_hash}",
            vhh_sequence=vhh_sequence,
            target_sequence=target_sequence,
            target_id=f"NANOBIND_TARGET_SHA256_{target_hash}",
            target_construct=(
                "NanoBind affinity/all.csv seq_antigen; "
                f"source_accessions={source_ids}; antigen_chains={antigen_chains}"
            ),
            source_id="nanobind_affinity_all_csv",
            source_path=f"{path}#csv_lines={source_lines}",
            family_id=f"nanobind_target_family_{target_hash}",
            leakage_group_id=f"nanobind_exact_pair_{pair_hash}",
            split_group_id=f"nanobind_target_{target_hash}",
            dataset_version=f"nanobind_git_{commit}_all_csv_sha256_{source_sha256}",
        )
        record.update(
            {
                "label_axis": "binding",
                "evidence_level": "E4",
                "ground_truth_kind": "assay_backed_generic_binding_affinity",
                "label_value": float(group["_affinity_kd_m"].median()),
                "label_unit": "M",
                "label_direction": "lower_is_stronger_binding",
                "assay_type": "Kd",
                "assay_batch": f"NanoBind_affinity_all_csv_git_{commit[:12]}",
                "replicate_count": "",
                "allowed_use": "EXPERIMENTAL_RANKING_ONLY",
                "forbidden_use": "BLOCKER_TRUTH|BLOCKER_CLAIM|BINARY_BINDING_TRUTH|CALIBRATED_PROBABILITY|PVRIG_TARGET_READINESS|REDISTRIBUTION",
                "sealed_status": "OPEN_DEVELOPMENT",
                "missing_reason": (
                    "replicate_count_not_reported_in_nanobind_affinity_all_csv; "
                    "exact_duplicate_rows_aggregated_but_not_assumed_to_be_replicates; "
                    "mutation_reference_and_pose_fields_not_applicable"
                ),
                "ordinary_train_allowed": "true",
                "ordinary_test_allowed": "true",
                "candidate_ranking_allowed": "false",
                "ordinary_bce_eligible": "false",
                "lane": "generic_experimental_affinity_ranking",
                "notes": (
                    f"source_ids={source_ids}; nanobody_chains={nanobody_chains}; antigen_chains={antigen_chains}; "
                    f"source_csv_lines={source_lines}; source_row_count={len(group)}; aggregation=median_Kd_M; "
                    f"git_commit={commit}; source_sha256={source_sha256}; generic binding only, no blocker claim"
                ),
            }
        )
        rows.append(record)

    merged_count = int(len(valid) - len(rows))
    invalid_count = int(len(raw) - len(valid))
    details = {
        "status": "INCLUDED",
        "checkout_path": str(checkout),
        "source_path": str(path),
        "git_commit": commit,
        "source_sha256": source_sha256,
        "source_row_count": int(len(raw)),
        "valid_source_row_count": int(len(valid)),
        "canonical_pair_count": int(len(rows)),
        "duplicate_exact_pair_groups": int(duplicate_group_count),
        "duplicate_rows_merged": merged_count,
        "invalid_sequence_rows_excluded": invalid_sequence_count,
        "invalid_affinity_rows_excluded": invalid_affinity_count,
        "excluded_or_merged_count": invalid_count + merged_count,
        "aggregation_policy": "group exact normalized seq_nanobody+seq_antigen pairs and take median Kd in M",
    }
    return rows, details


def build_pvrig_control_rows(root: Path, target_sequence: str) -> list[dict[str, Any]]:
    path = root / "experiments/phase2_5080_v1/data_splits/pvrig_validation_controls_v2_4.csv"
    df = pd.read_csv(path)
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        sample_id = _str_or_empty(row["sample_id"])
        record = base_record(
            sample_id=sample_id,
            vhh_sequence=_str_or_empty(row["sequence"]),
            target_sequence=target_sequence,
            source_id="pvrig_validation_controls_v2_4",
            source_path=path,
            family_id=f"pvrig_family_{_str_or_empty(row.get('family'))}",
            leakage_group_id=f"pvrig_control_{_str_or_empty(row.get('family'))}_{_str_or_empty(row.get('control_role'))}",
            split_group_id=f"pvrig_control_block_{_str_or_empty(row.get('family'))}",
        )
        role = _str_or_empty(row.get("control_role"))
        if role == "known_positive_calibration":
            record.update(
                {
                    "label_axis": "blocking",
                    "evidence_level": "E5",
                    "ground_truth_kind": "known_positive_calibration_only",
                    "label_value": _str_or_empty(row.get("assay_ic50_nm")),
                    "label_unit": "nM_IC50",
                    "label_direction": "lower_is_stronger_blocking",
                    "assay_type": "historical_blocking_ic50",
                    "assay_batch": "case02_patent_success_validation",
                    "replicate_count": "",
                    "allowed_use": "CALIBRATION_LEAKAGE_CONTROL_ONLY",
                    "lane": "known_positive_calibration",
                    "notes": "Assay-backed PVRIG positive retained only for calibration/leakage exclusion, not ordinary truth.",
                }
            )
            if record["replicate_count"] == "":
                record["missing_reason"] = "historical_positive_has_no_local_replicate_count; kept calibration_only"
        elif role in {"mutant", "base_reference"}:
            record.update(
                {
                    "label_axis": "mutation_effect",
                    "evidence_level": "E0",
                    "ground_truth_kind": "mutation_control_without_measured_effect",
                    "allowed_use": "MUTATION_CONTROL_ONLY",
                    "mutation": _str_or_empty(row.get("control_role")),
                    "reference_sample_id": _str_or_empty(row.get("molecule_name")),
                    "lane": "mutation_or_base_reference_control_only",
                    "notes": "No local measured delta_Kd/delta_IC50/function-loss label; excluded from ordinary truth.",
                }
            )
        rows.append(record)
    return rows


def build_constructed_proxy_rows(root: Path, target_sequence: str) -> list[dict[str, Any]]:
    path = root / "experiments/phase2_5080_v1/data_splits/pair_ranking_groups_v2_4.csv"
    df = pd.read_csv(path)
    df = df[df["candidate_role"].astype(str).eq("constructed_contrastive_candidate")].copy()
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        sample_id = _str_or_empty(row["candidate_pair_id"])
        record = base_record(
            sample_id=sample_id,
            vhh_sequence=_str_or_empty(row["vhh_seq"]),
            target_sequence=target_sequence,
            source_id="pair_ranking_groups_v2_4",
            source_path=path,
            family_id=f"constructed_proxy_{_str_or_empty(row.get('negative_type'))}",
            leakage_group_id=f"ranking_group_{_str_or_empty(row.get('ranking_group_id'))}",
            split_group_id=f"proxy_stress_{_str_or_empty(row.get('ranking_group_id'))}",
        )
        record.update(
            {
                "label_axis": "proxy",
                "evidence_level": "E2",
                "ground_truth_kind": "constructed_proxy",
                "label_value": _str_or_empty(row.get("preference_label")),
                "label_unit": "constructed_preference",
                "label_direction": "positive_anchor_preferred_over_constructed_proxy",
                "source_id": "pair_ranking_groups_v2_4_constructed_only",
                "allowed_use": "PROXY_STRESS_ONLY",
                "forbidden_use": "ORDINARY_BCE|VERIFIED_NONBINDER|BLOCKER_TRUTH|CALIBRATION|FORMAL_PRIMARY|REDISTRIBUTION",
                "lane": "proxy_stress_only",
                "notes": f"{_str_or_empty(row.get('negative_type'))} is a constructed contrast, not an experimental non-binder.",
            }
        )
        rows.append(record)
    return rows


def load_candidate_sequences(root: Path) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for path in [
        root / "model_data/mvp_candidates_v0.csv",
        root / "experiments/phase2_5080_v1/predictions/pvrig_candidate_ranking_v2_4_p3_pose_fusion.csv",
    ]:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if {"candidate_id", "vhh_seq"}.issubset(df.columns):
            for _, row in df.dropna(subset=["candidate_id", "vhh_seq"]).iterrows():
                candidates.setdefault(_str_or_empty(row["candidate_id"]), _str_or_empty(row["vhh_seq"]))
    return candidates


def build_pose_proxy_rows(root: Path, target_sequence: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary_path = root / "experiments/phase2_5080_v1/prepared/pvrig_pose_proxy_summary_v2_4.csv"
    if summary_path.exists():
        summary = pd.read_csv(summary_path)
        controls = pd.read_csv(root / "experiments/phase2_5080_v1/data_splits/pvrig_validation_controls_v2_4.csv")
        sequence_by_id = dict(zip(controls["sample_id"], controls["sequence"]))
        for _, row in summary.iterrows():
            sample_id = _str_or_empty(row["sample_id"])
            sequence = sequence_by_id.get(sample_id, "X")
            if sequence == "X":
                continue
            record = base_record(
                sample_id=f"pose_summary::{sample_id}",
                vhh_sequence=sequence,
                target_sequence=target_sequence,
                source_id="pvrig_pose_proxy_summary_v2_4",
                source_path=summary_path,
                family_id=f"pose_summary_{_str_or_empty(row.get('source_lane'))}",
                leakage_group_id=f"pose_summary_{sample_id}",
                split_group_id=f"pose_proxy_{sample_id}",
            )
            record.update(
                {
                    "label_axis": "proxy",
                    "evidence_level": "E3",
                    "ground_truth_kind": "pose_proxy",
                    "allowed_use": "POSE_PROXY_TRIAGE_ONLY",
                    "forbidden_use": "EXPERIMENTAL_BINDING|EXPERIMENTAL_BLOCKING|ORDINARY_TRUTH|FORMAL_PRIMARY|REDISTRIBUTION",
                    "pose_id": f"pose_summary::{sample_id}",
                    "pose_qc_status": "summary_only_manual_review" if _bool_text(bool(row.get("manual_review_required"))) == "true" else "summary_only",
                    "lane": "pose_proxy_only",
                    "notes": "Docking summary is computational pose evidence only, not blocker truth.",
                }
            )
            rows.append(record)
    geometry_path = root / "experiments/phase2_5080_v1/prepared/p3_pose_geometry_features_v1.csv"
    if geometry_path.exists():
        geometry = pd.read_csv(geometry_path)
        candidate_sequences = load_candidate_sequences(root)
        for _, row in geometry.iterrows():
            sample_id = _str_or_empty(row["candidate_id"])
            sequence = candidate_sequences.get(sample_id, _str_or_empty(row.get("cdr3_seq"))) or "X"
            if sequence == "X":
                continue
            record = base_record(
                sample_id=f"pose_candidate::{sample_id}",
                vhh_sequence=sequence,
                target_sequence=target_sequence,
                source_id="p3_pose_geometry_features_v1",
                source_path=geometry_path,
                family_id="p3_candidate_pose_proxy",
                leakage_group_id=f"p3_pose_{sample_id}",
                split_group_id=f"p3_pose_proxy_{sample_id}",
            )
            record.update(
                {
                    "label_axis": "proxy",
                    "evidence_level": "E3",
                    "ground_truth_kind": "pose_proxy",
                    "allowed_use": "POSE_PROXY_TRIAGE_ONLY",
                    "forbidden_use": "EXPERIMENTAL_BINDING|EXPERIMENTAL_BLOCKING|ORDINARY_TRUTH|FORMAL_PRIMARY|REDISTRIBUTION",
                    "pose_id": _str_or_empty(row.get("pose_id")),
                    "pose_qc_status": _str_or_empty(row.get("qc_status")),
                    "lane": "pose_proxy_only",
                    "notes": "Optional P3 pose geometry is computational triage only; CDR3 sequence used as local candidate identity anchor.",
                }
            )
            rows.append(record)
    return rows


def _build_evidence_registry_with_details(root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    target_sequence = read_fasta_sequence(root / "model_data/pvrig_target_ectodomain_proxy_v1.fasta")
    contact_rows, contact_details = build_contact_site_rows(root)
    nanobind_rows, nanobind_details = build_nanobind_affinity_rows(root)
    rows: list[dict[str, Any]] = []
    rows.extend(build_pvrig_control_rows(root, target_sequence))
    rows.extend(contact_rows)
    rows.extend(build_constructed_proxy_rows(root, target_sequence))
    rows.extend(build_pose_proxy_rows(root, target_sequence))
    rows.extend(nanobind_rows)
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("No evidence rows found")
    df = df[CANONICAL_FIELDS]
    validate_evidence_registry(df)
    return df, {"contact_site_source": contact_details, "nanobind_affinity": nanobind_details}


def build_evidence_registry(root: Path) -> pd.DataFrame:
    return _build_evidence_registry_with_details(root)[0]


def _nanobind_checkout_license_files(checkout: Path) -> list[str]:
    if not checkout.is_dir():
        return []
    return sorted(
        path.name
        for path in checkout.iterdir()
        if path.is_file() and path.name.lower().startswith(("license", "copying"))
    )


def build_external_manifest(root: Path, nanobind_details: dict[str, Any] | None = None) -> pd.DataFrame:
    checkout = root / NANOBIND_CHECKOUT
    if nanobind_details is None:
        _, nanobind_details = build_nanobind_affinity_rows(root)
    license_files = _nanobind_checkout_license_files(checkout)
    license_note = ",".join(license_files) if license_files else "none"
    row = {
        "manifest_version": EXTERNAL_MANIFEST_VERSION,
        "source_id": "nanobind_affinity_all_csv",
        "source_family": "NanoBind",
        "source_version": (
            f"git:{nanobind_details['git_commit']};"
            f"sha256:{nanobind_details['source_sha256']}"
        ),
        "source_path_or_locator": nanobind_details["source_path"],
        "license_or_usage_status": "REVIEWED_LOCAL_USE",
        "redistribution_allowed": "false",
        "allowed_use": "REVIEWED_LOCAL_USE",
        "forbidden_use": "REDISTRIBUTION|BLOCKER_TRUTH|BLOCKER_CLAIM|BINARY_BINDING_TRUTH|CALIBRATED_PROBABILITY",
        "accession_mapping_status": "ID+nanobody_chain+antigen_chain retained in each canonical row locator/notes",
        "sequence_mapping_status": "seq_nanobody->vhh_sequence+sequence_sha256; seq_antigen->target_id+target_sequence_sha256",
        "unit_normalization_status": "affinity parsed as positive finite Kd in M; label_unit=M; lower_is_stronger_binding",
        "duplicate_policy": "exact normalized seq_nanobody+seq_antigen pairs aggregated by median Kd_M; source CSV lines retained",
        "excluded_row_count": str(nanobind_details["excluded_or_merged_count"]),
        "enters_training_or_evaluation": "true",
        "notes": (
            f"git_commit={nanobind_details['git_commit']}; source_sha256={nanobind_details['source_sha256']}; "
            f"raw_rows={nanobind_details['source_row_count']}; canonical_pairs={nanobind_details['canonical_pair_count']}; "
            f"duplicate_exact_pair_groups={nanobind_details['duplicate_exact_pair_groups']}; "
            f"duplicate_rows_merged={nanobind_details['duplicate_rows_merged']}; "
            f"license_files_in_actual_checkout={license_note}; license terms absent/unresolved, so local train/eval only and no redistribution"
        ),
    }
    df = pd.DataFrame([row], columns=EXTERNAL_MANIFEST_FIELDS)
    validate_external_manifest(df)
    return df


def write_jsonl(df: pd.DataFrame, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in df.to_dict(orient="records"):
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--evidence-csv", default="experiments/phase2_5080_v1/data_splits/evidence_registry_v2_5.csv")
    parser.add_argument("--evidence-jsonl", default="experiments/phase2_5080_v1/data_splits/evidence_registry_v2_5.jsonl")
    parser.add_argument("--external-manifest", default="experiments/phase2_5080_v1/data_splits/external_dataset_usage_manifest_v2_5.csv")
    parser.add_argument("--summary-json", default="experiments/phase2_5080_v1/audits/phase2_v2_5_evidence_registry_summary.json")
    parser.add_argument("--dry-run", action="store_true", help="Build and validate without writing output files.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    evidence, build_details = _build_evidence_registry_with_details(root)
    external = build_external_manifest(root, build_details["nanobind_affinity"])
    validation = validate_evidence_registry(evidence)
    validate_external_manifest(external)
    summary = {
        "status": validation.status,
        "schema_version": SCHEMA_VERSION,
        "row_count": validation.row_count,
        "evidence_level_counts": validation.evidence_level_counts,
        "data_readiness_status": validation.data_readiness_status,
        "target_readiness_target_id": PVRIG_TARGET_ID,
        "pvrig_target_assay_row_count": int(
            (evidence["target_id"].eq(PVRIG_TARGET_ID) & evidence["evidence_level"].isin(["E4", "E5", "E6"])).sum()
        ),
        "ordinary_negative_count": int((evidence["ground_truth_kind"] == "verified_nonbinder").sum()),
        "known_positive_ordinary_rows": int(evidence[evidence["ground_truth_kind"].str.contains("known_positive|calibration", case=False, na=False)]["ordinary_train_allowed"].map(lambda x: str(x).lower() == "true").sum()),
        "constructed_proxy_rows": int((evidence["evidence_level"] == "E2").sum()),
        "pose_proxy_rows": int((evidence["evidence_level"] == "E3").sum()),
        "contact_site_rows": int((evidence["evidence_level"] == "E1").sum()),
        "generic_e4_binding_rows": int(
            (evidence["evidence_level"].eq("E4") & evidence["target_id"].ne(PVRIG_TARGET_ID)).sum()
        ),
        "contact_site_source": build_details["contact_site_source"],
        "nanobind_affinity": build_details["nanobind_affinity"],
        "external_sources": external.to_dict(orient="records"),
    }
    if not args.dry_run:
        evidence_csv = root / args.evidence_csv
        evidence_jsonl = root / args.evidence_jsonl
        external_path = root / args.external_manifest
        summary_path = root / args.summary_json
        for path in [evidence_csv, evidence_jsonl, external_path, summary_path]:
            path.parent.mkdir(parents=True, exist_ok=True)
        evidence.to_csv(evidence_csv, index=False)
        write_jsonl(evidence, evidence_jsonl)
        external.to_csv(external_path, index=False)
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
        summary.update({"evidence_csv": str(evidence_csv), "evidence_jsonl": str(evidence_jsonl), "external_manifest": str(external_path), "summary_json": str(summary_path)})
    return summary


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
