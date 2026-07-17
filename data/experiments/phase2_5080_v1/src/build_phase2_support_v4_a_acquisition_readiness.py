#!/usr/bin/env python3
"""Freeze-safe, label-free Support V4-A teacher-acquisition pool builder.

The builder consumes only sequence/lineage identity, the completed Node1 Fast-QC
census, frozen parent roles, and identity-only exclusions.  It deliberately has
no interface for docking, V4-D geometry, V4-F labels, model scores, binding, or
experimental outcomes.

Production materialization is opt-in and is not performed by the implementation
freeze workflow.  The current artifact is an acquisition/readiness contract for
future Node1 teacher computation; it is not a Support-domain PASS.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "phase2_support_v4_a_acquisition_readiness_builder_v1"
SELECTION_SEED = "phase2_support_v4_a_label_free_20x36_20260717"
PATCHES = ("A_CENTER", "B_LOWER", "C_CROSS")
MODES = ("H3", "H1H3")

ROLE_OPEN_TRAIN = "OPEN_TRAIN"
ROLE_OPEN_DEVELOPMENT = "OPEN_DEVELOPMENT"
ROLE_FORMAL_TEST = "PROSPECTIVE_COMPUTATIONAL_TEST"
ROLE_V4_F = "V4_F"
ROLE_V4_G = "V4_G"
ROLE_RESERVE2 = "RESERVE2"
PARENT_ROLES = (
    ROLE_OPEN_TRAIN,
    ROLE_OPEN_DEVELOPMENT,
    ROLE_FORMAL_TEST,
    ROLE_V4_F,
    ROLE_V4_G,
    ROLE_RESERVE2,
)

ROLE_ACQUISITION = "FUTURE_NODE1_TEACHER_ACQUISITION"
ROLE_AUDIT = "LABEL_FREE_AUDIT"
ROWS_PER_PARENT = 36
ACQUISITION_ROWS_PER_PARENT = 24
AUDIT_ROWS_PER_PARENT = 12
ROWS_PER_PATCH = 12
ACQUISITION_ROWS_PER_PATCH = 8
AUDIT_ROWS_PER_PATCH = 4
MAX_POSITIVE_CDR_IDENTITY_EXCLUSIVE = 75.0

SUPPORT_V3_FROZEN_STATUS = "FAIL_RESEARCH_RANKING_AND_DIRECT_DOCKING_ROUTING_ONLY"
READINESS_STATUS = "FROZEN_FUTURE_NODE1_TEACHER_ACQUISITION_CAPACITY_ONLY"
CLAIM_BOUNDARY = (
    "A label-free capacity and acquisition design for future Node1 teacher "
    "computation. It is not Support-domain PASS, model correctness, docking "
    "geometry, binding, affinity, competition, Docking Gold, experimental "
    "blocking, or binding probability."
)

DATA_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PREREGISTRATION = DATA_ROOT / "experiments/phase2_5080_v1/audits/phase2_support_v4_a_acquisition_readiness_v1_preregistration.json"

ALLOWED_CANDIDATE_FIELDS = (
    "candidate_id",
    "vhh_sequence",
    "sequence_sha256",
    "parent_id",
    "parent_framework_cluster",
    "target_patch_id",
    "design_mode",
    "cdr3_after",
    "cdr3_length",
    "max_positive_cdr_identity",
)
ALLOWED_CENSUS_FIELDS = (
    "candidate_id",
    "sequence_sha256",
    "parent_framework_cluster",
    "fast_hard_fail",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def stable_hash(*parts: object) -> str:
    joined = "|".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def read_table(path: Path, delimiter: str) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = [dict(row) for row in reader]
        fields = list(reader.fieldnames or [])
    if not fields:
        raise RuntimeError(f"empty table header: {path}")
    return rows, fields


def require_fields(fields: Iterable[str], required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(fields))
    if missing:
        raise RuntimeError(f"{label} missing required fields: {missing}")


def validate_parent_role_partition(
    role_sets: Mapping[str, set[str]],
    *,
    expected_parent_count: int = 40,
    expected_open_train_count: int = 20,
) -> dict[str, str]:
    missing_roles = sorted(set(PARENT_ROLES) - set(role_sets))
    extra_roles = sorted(set(role_sets) - set(PARENT_ROLES))
    if missing_roles or extra_roles:
        raise RuntimeError(
            f"role partition keys mismatch: missing={missing_roles} extra={extra_roles}"
        )
    owners: dict[str, list[str]] = defaultdict(list)
    for role in PARENT_ROLES:
        for parent in role_sets[role]:
            owners[parent].append(role)
    overlap = {parent: roles for parent, roles in owners.items() if len(roles) != 1}
    if overlap:
        raise RuntimeError(f"parent role overlap: {overlap}")
    if len(owners) != expected_parent_count:
        raise RuntimeError(
            f"parent count mismatch: observed={len(owners)} expected={expected_parent_count}"
        )
    if len(role_sets[ROLE_OPEN_TRAIN]) != expected_open_train_count:
        raise RuntimeError(
            "OPEN_TRAIN parent count mismatch: "
            f"observed={len(role_sets[ROLE_OPEN_TRAIN])} expected={expected_open_train_count}"
        )
    return {parent: roles[0] for parent, roles in sorted(owners.items())}


def derive_parent_roles(
    v4d_rows: Sequence[Mapping[str, str]],
    v4f_rows: Sequence[Mapping[str, str]],
    v4g_rows: Sequence[Mapping[str, str]],
    reserve_rows: Sequence[Mapping[str, str]],
    *,
    expected_parent_count: int = 40,
    expected_open_train_count: int = 20,
) -> dict[str, str]:
    role_sets: dict[str, set[str]] = {role: set() for role in PARENT_ROLES}
    allowed_v4d = {ROLE_OPEN_TRAIN, ROLE_OPEN_DEVELOPMENT, ROLE_FORMAL_TEST}
    for row in v4d_rows:
        role = row["model_split"]
        if role not in allowed_v4d:
            raise RuntimeError(f"unknown V4-D parent role: {role}")
        role_sets[role].add(row["parent_framework_cluster"])
    role_sets[ROLE_V4_F] = {row["parent_framework_cluster"] for row in v4f_rows}
    role_sets[ROLE_V4_G] = {row["parent_framework_cluster"] for row in v4g_rows}
    role_sets[ROLE_RESERVE2] = {
        row["parent_framework_cluster"] for row in reserve_rows
    }
    return validate_parent_role_partition(
        role_sets,
        expected_parent_count=expected_parent_count,
        expected_open_train_count=expected_open_train_count,
    )


def _bool_text(value: str, label: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise RuntimeError(f"{label} must be exact True/False, observed={value!r}")


def collect_eligible_candidates(
    candidate_rows: Sequence[Mapping[str, str]],
    census_rows: Sequence[Mapping[str, str]],
    parent_roles: Mapping[str, str],
    *,
    calibration_sequence_sha256: set[str],
    prior_panel_candidate_ids: set[str],
    prior_panel_sequence_sha256: set[str],
) -> tuple[list[dict[str, str]], Counter[str]]:
    """Project only preregistered fields and apply label-free exclusions."""

    census_by_id: dict[str, Mapping[str, str]] = {}
    for row in census_rows:
        candidate_id = row["candidate_id"]
        if candidate_id in census_by_id:
            raise RuntimeError(f"duplicate census candidate_id: {candidate_id}")
        census_by_id[candidate_id] = row

    observed_ids: set[str] = set()
    observed_sequence_sha: dict[str, str] = {}
    eligible: list[dict[str, str]] = []
    exclusions: Counter[str] = Counter()

    for source in candidate_rows:
        candidate_id = source["candidate_id"]
        if candidate_id in observed_ids:
            raise RuntimeError(f"duplicate candidate_id: {candidate_id}")
        observed_ids.add(candidate_id)
        census = census_by_id.get(candidate_id)
        if census is None:
            raise RuntimeError(f"candidate missing from Fast-QC census: {candidate_id}")

        parent = source["parent_framework_cluster"]
        role = parent_roles.get(parent)
        if role is None:
            raise RuntimeError(f"candidate parent has no frozen role: {candidate_id} {parent}")
        if census["parent_framework_cluster"] != parent:
            raise RuntimeError(f"candidate/census parent mismatch: {candidate_id}")
        sequence = source["vhh_sequence"].strip().upper()
        sequence_sha = source["sequence_sha256"]
        if hashlib.sha256(sequence.encode("ascii")).hexdigest() != sequence_sha:
            raise RuntimeError(f"candidate sequence SHA256 mismatch: {candidate_id}")
        if census["sequence_sha256"] != sequence_sha:
            raise RuntimeError(f"candidate/census sequence SHA256 mismatch: {candidate_id}")
        prior_owner = observed_sequence_sha.setdefault(sequence_sha, candidate_id)
        if prior_owner != candidate_id:
            raise RuntimeError(
                f"duplicate source sequence SHA256: {prior_owner} and {candidate_id}"
            )

        if role != ROLE_OPEN_TRAIN:
            exclusions[f"FORBIDDEN_PARENT_ROLE_{role}"] += 1
            continue
        if _bool_text(census["fast_hard_fail"], f"fast_hard_fail:{candidate_id}"):
            exclusions["FAST_QC_HARD_FAIL"] += 1
            continue
        if candidate_id in prior_panel_candidate_ids:
            exclusions["PRIOR_PANEL_CANDIDATE_IDENTITY"] += 1
            continue
        if sequence_sha in prior_panel_sequence_sha256:
            exclusions["PRIOR_PANEL_SEQUENCE_IDENTITY"] += 1
            continue
        if sequence_sha in calibration_sequence_sha256:
            exclusions["KNOWN_CALIBRATION_EXACT_SEQUENCE"] += 1
            continue
        try:
            positive_identity = float(source["max_positive_cdr_identity"])
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                f"missing/non-numeric positive CDR identity: {candidate_id}"
            ) from error
        if positive_identity >= MAX_POSITIVE_CDR_IDENTITY_EXCLUSIVE:
            exclusions["POSITIVE_CDR_IDENTITY_GE_75"] += 1
            continue

        patch = source["target_patch_id"]
        mode = source["design_mode"]
        if patch not in PATCHES:
            raise RuntimeError(f"unknown target patch: {candidate_id} {patch}")
        if mode not in MODES:
            raise RuntimeError(f"unknown design mode: {candidate_id} {mode}")
        cdr3 = source["cdr3_after"].strip().upper()
        if not cdr3 or any(amino_acid not in "ACDEFGHIKLMNPQRSTVWY" for amino_acid in cdr3):
            raise RuntimeError(f"invalid CDR3: {candidate_id}")
        cdr3_length = int(source["cdr3_length"])
        if cdr3_length != len(cdr3):
            raise RuntimeError(f"CDR3 length mismatch: {candidate_id}")

        projected = {
            "candidate_id": candidate_id,
            "sequence": sequence,
            "sequence_sha256": sequence_sha,
            "parent_id": source["parent_id"],
            "parent_framework_cluster": parent,
            "parent_role": role,
            "target_patch_id": patch,
            "design_mode": mode,
            "cdr3": cdr3,
            "cdr3_length": str(cdr3_length),
            "max_positive_cdr_identity": f"{positive_identity:.6f}",
            "fast_qc_state": "HARD_PASS",
        }
        projected["selection_hash"] = stable_hash(
            SELECTION_SEED,
            candidate_id,
            sequence_sha,
            parent,
            patch,
            mode,
            cdr3,
        )
        eligible.append(projected)

    census_only = sorted(set(census_by_id) - observed_ids)
    if census_only:
        raise RuntimeError(
            f"Fast-QC census has candidate IDs absent from candidate source: {census_only[:5]}"
        )
    eligible.sort(key=lambda row: row["candidate_id"])
    return eligible, exclusions


def build_capacity_audit(
    eligible: Sequence[Mapping[str, str]],
    parent_summary_rows: Sequence[Mapping[str, str]],
    parent_roles: Mapping[str, str],
) -> list[dict[str, str]]:
    summaries = {
        row["parent_framework_cluster"]: row for row in parent_summary_rows
    }
    open_parents = sorted(
        parent for parent, role in parent_roles.items() if role == ROLE_OPEN_TRAIN
    )
    by_parent: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in eligible:
        by_parent[row["parent_framework_cluster"]].append(row)

    output: list[dict[str, str]] = []
    for parent in open_parents:
        summary = summaries.get(parent)
        if summary is None:
            raise RuntimeError(f"OPEN_TRAIN parent missing from parent census: {parent}")
        fast_pass = int(summary["fast_hard_pass_count"])
        if fast_pass < ROWS_PER_PARENT:
            raise RuntimeError(
                f"OPEN_TRAIN parent must have >= 36 Fast-QC hard-pass rows: {parent}={fast_pass}"
            )
        rows = by_parent[parent]
        unique_parent_cdr3 = {row["cdr3"] for row in rows}
        if len(unique_parent_cdr3) < ROWS_PER_PARENT:
            raise RuntimeError(
                f"insufficient unique CDR3 capacity: {parent}={len(unique_parent_cdr3)}"
            )
        patch_counts: dict[str, int] = {}
        patch_unique_counts: dict[str, int] = {}
        mode_counts = Counter(row["design_mode"] for row in rows)
        per_patch_mode: dict[str, int] = {}
        feasibility_quotas: dict[tuple[str, str, str], int] = {}
        for patch in PATCHES:
            patch_rows = [row for row in rows if row["target_patch_id"] == patch]
            patch_counts[patch] = len(patch_rows)
            patch_unique_counts[patch] = len({row["cdr3"] for row in patch_rows})
            if patch_counts[patch] < ROWS_PER_PATCH or patch_unique_counts[patch] < ROWS_PER_PATCH:
                raise RuntimeError(
                    f"insufficient patch capacity: {parent} {patch} rows={patch_counts[patch]} unique_cdr3={patch_unique_counts[patch]}"
                )
            for mode in MODES:
                per_patch_mode[f"{patch}|{mode}"] = len(
                    {
                        row["cdr3"]
                        for row in patch_rows
                        if row["design_mode"] == mode
                    }
                )
            mode_quotas = allocate_mode_quotas(
                {mode: per_patch_mode[f"{patch}|{mode}"] for mode in MODES}
            )
            for (mode, role), count in allocate_role_quotas(mode_quotas).items():
                feasibility_quotas[(patch, mode, role)] = count
        if not _unique_cdr3_feasible(
            _canonical_candidates_by_stratum_cdr3(rows),
            feasibility_quotas,
            set(),
        ):
            raise RuntimeError(
                f"global unique CDR3 quota assignment infeasible: {parent}"
            )
        modes_present = {mode for mode, count in mode_counts.items() if count}
        both_balanced = all(
            per_patch_mode[f"{patch}|{mode}"] >= ROWS_PER_PATCH // 2
            for patch in PATCHES
            for mode in MODES
        )
        if both_balanced:
            mode_state = "BALANCED_BOTH_MODES"
        elif len(modes_present) == 1:
            mode_state = "FORCED_SINGLE_MODE_BY_FAST_QC"
        else:
            mode_state = "MAXIMIZED_MODE_BALANCE_UNDER_FAST_QC"
        output.append(
            {
                "parent_framework_cluster": parent,
                "parent_role": ROLE_OPEN_TRAIN,
                "raw_fast_hard_pass_count": str(fast_pass),
                "identity_exclusion_eligible_count": str(len(rows)),
                "unique_cdr3_count": str(len(unique_parent_cdr3)),
                "A_CENTER_eligible": str(patch_counts["A_CENTER"]),
                "B_LOWER_eligible": str(patch_counts["B_LOWER"]),
                "C_CROSS_eligible": str(patch_counts["C_CROSS"]),
                "H3_eligible": str(mode_counts["H3"]),
                "H1H3_eligible": str(mode_counts["H1H3"]),
                "mode_coverage_state": mode_state,
                "global_unique_cdr3_quota_feasible": "True",
                "readiness_state": "READY_FOR_FUTURE_24_PLUS_12_ACQUISITION",
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    return output


def normalized_edit_distance(left: str, right: str) -> float:
    if left == right:
        return 0.0
    if not left or not right:
        return 1.0
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1] / max(len(left), len(right))


def allocate_mode_quotas(unique_counts: Mapping[str, int]) -> dict[str, int]:
    if sum(unique_counts.get(mode, 0) for mode in MODES) < ROWS_PER_PATCH:
        raise RuntimeError(f"insufficient total mode capacity: {dict(unique_counts)}")
    preferred = ROWS_PER_PATCH // len(MODES)
    quotas = {
        mode: min(unique_counts.get(mode, 0), preferred) for mode in MODES
    }
    remaining = ROWS_PER_PATCH - sum(quotas.values())
    while remaining:
        available = [
            mode for mode in MODES if quotas[mode] < unique_counts.get(mode, 0)
        ]
        if not available:
            raise RuntimeError(f"mode quota allocation exhausted: {dict(unique_counts)}")
        available.sort(
            key=lambda mode: (
                -(unique_counts.get(mode, 0) - quotas[mode]),
                MODES.index(mode),
            )
        )
        quotas[available[0]] += 1
        remaining -= 1
    return quotas


def allocate_role_quotas(mode_quotas: Mapping[str, int]) -> dict[tuple[str, str], int]:
    audit = {mode: mode_quotas[mode] // 3 for mode in MODES}
    remaining_audit = AUDIT_ROWS_PER_PATCH - sum(audit.values())
    fractional_order = sorted(
        MODES,
        key=lambda mode: (
            -((mode_quotas[mode] % 3) / 3),
            MODES.index(mode),
        ),
    )
    for mode in fractional_order:
        if not remaining_audit:
            break
        if audit[mode] < mode_quotas[mode]:
            audit[mode] += 1
            remaining_audit -= 1
    if remaining_audit:
        raise RuntimeError(f"could not allocate audit quota: {dict(mode_quotas)}")
    output: dict[tuple[str, str], int] = {}
    for mode in MODES:
        output[(mode, ROLE_AUDIT)] = audit[mode]
        output[(mode, ROLE_ACQUISITION)] = mode_quotas[mode] - audit[mode]
    if sum(value for (mode, role), value in output.items() if role == ROLE_ACQUISITION) != ACQUISITION_ROWS_PER_PATCH:
        raise RuntimeError("acquisition role quota mismatch")
    if sum(value for (mode, role), value in output.items() if role == ROLE_AUDIT) != AUDIT_ROWS_PER_PATCH:
        raise RuntimeError("audit role quota mismatch")
    return output


def _canonical_candidates_by_stratum_cdr3(
    rows: Sequence[Mapping[str, str]],
) -> dict[tuple[str, str, str], dict[str, Mapping[str, str]]]:
    output: dict[tuple[str, str, str], dict[str, Mapping[str, str]]] = defaultdict(dict)
    # Acquisition and audit use the same candidate pool; role is expanded below.
    for row in sorted(rows, key=lambda item: item["selection_hash"]):
        for role in (ROLE_ACQUISITION, ROLE_AUDIT):
            stratum = (row["target_patch_id"], row["design_mode"], role)
            output[stratum].setdefault(row["cdr3"], row)
    return output


def _unique_cdr3_feasible(
    candidates: Mapping[tuple[str, str, str], Mapping[str, Mapping[str, str]]],
    quotas: Mapping[tuple[str, str, str], int],
    used_cdr3: set[str],
) -> bool:
    slots: list[tuple[str, str, str]] = []
    for stratum in sorted(quotas):
        slots.extend([stratum] * quotas[stratum])
    if not slots:
        return True

    matched: dict[str, int] = {}

    def visit(slot_index: int, seen: set[str]) -> bool:
        stratum = slots[slot_index]
        options = [
            (row["selection_hash"], cdr3)
            for cdr3, row in candidates.get(stratum, {}).items()
            if cdr3 not in used_cdr3
        ]
        for _, cdr3 in sorted(options):
            if cdr3 in seen:
                continue
            seen.add(cdr3)
            previous_slot = matched.get(cdr3)
            if previous_slot is None or visit(previous_slot, seen):
                matched[cdr3] = slot_index
                return True
        return False

    return all(visit(slot_index, set()) for slot_index in range(len(slots)))


def _slot_order(quotas: Mapping[tuple[str, str, str], int]) -> list[tuple[str, str, str]]:
    remaining = dict(quotas)
    slots: list[tuple[str, str, str]] = []
    for role in (ROLE_ACQUISITION, ROLE_AUDIT):
        while any(value for key, value in remaining.items() if key[2] == role):
            for patch in PATCHES:
                for mode in MODES:
                    key = (patch, mode, role)
                    if remaining.get(key, 0):
                        slots.append(key)
                        remaining[key] -= 1
    if any(remaining.values()):
        raise RuntimeError(f"unconsumed slot quotas: {remaining}")
    return slots


def _validate_selected_parent(
    selected: Sequence[Mapping[str, str]], parent: str
) -> None:
    if len(selected) != ROWS_PER_PARENT:
        raise RuntimeError(f"selected parent row count mismatch: {parent}")
    if len({row["candidate_id"] for row in selected}) != ROWS_PER_PARENT:
        raise RuntimeError(f"duplicate selected candidate: {parent}")
    if len({row["sequence_sha256"] for row in selected}) != ROWS_PER_PARENT:
        raise RuntimeError(f"duplicate selected sequence: {parent}")
    if len({row["cdr3"] for row in selected}) != ROWS_PER_PARENT:
        raise RuntimeError(f"selected pool violates unique CDR3 contract: {parent}")
    if Counter(row["target_patch_id"] for row in selected) != Counter(
        {patch: ROWS_PER_PATCH for patch in PATCHES}
    ):
        raise RuntimeError(f"selected patch quotas mismatch: {parent}")
    if Counter(row["acquisition_role"] for row in selected) != Counter(
        {
            ROLE_ACQUISITION: ACQUISITION_ROWS_PER_PARENT,
            ROLE_AUDIT: AUDIT_ROWS_PER_PARENT,
        }
    ):
        raise RuntimeError(f"selected acquisition/audit quotas mismatch: {parent}")
    for patch in PATCHES:
        patch_rows = [row for row in selected if row["target_patch_id"] == patch]
        if Counter(row["acquisition_role"] for row in patch_rows) != Counter(
            {
                ROLE_ACQUISITION: ACQUISITION_ROWS_PER_PATCH,
                ROLE_AUDIT: AUDIT_ROWS_PER_PATCH,
            }
        ):
            raise RuntimeError(f"selected patch role quotas mismatch: {parent} {patch}")


def select_readiness_pool(
    eligible: Sequence[Mapping[str, str]], parent_roles: Mapping[str, str]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    open_parents = sorted(
        parent for parent, role in parent_roles.items() if role == ROLE_OPEN_TRAIN
    )
    by_parent: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in eligible:
        by_parent[row["parent_framework_cluster"]].append(row)

    all_selected: list[dict[str, str]] = []
    parent_audit: list[dict[str, str]] = []
    for parent in open_parents:
        parent_rows = by_parent[parent]
        if len(parent_rows) < ROWS_PER_PARENT:
            raise RuntimeError(f"insufficient eligible rows for parent: {parent}")
        quotas: dict[tuple[str, str, str], int] = {}
        parent_mode_state: list[str] = []
        for patch in PATCHES:
            unique_counts = {
                mode: len(
                    {
                        row["cdr3"]
                        for row in parent_rows
                        if row["target_patch_id"] == patch
                        and row["design_mode"] == mode
                    }
                )
                for mode in MODES
            }
            mode_quotas = allocate_mode_quotas(unique_counts)
            role_quotas = allocate_role_quotas(mode_quotas)
            for (mode, role), count in role_quotas.items():
                quotas[(patch, mode, role)] = count
            if all(mode_quotas[mode] == ROWS_PER_PATCH // 2 for mode in MODES):
                parent_mode_state.append("BALANCED")
            elif sum(mode_quotas[mode] > 0 for mode in MODES) == 1:
                parent_mode_state.append("SINGLE")
            else:
                parent_mode_state.append("MAXIMIZED")

        candidates = _canonical_candidates_by_stratum_cdr3(parent_rows)
        if not _unique_cdr3_feasible(candidates, quotas, set()):
            raise RuntimeError(f"unique CDR3 quota assignment infeasible: {parent}")

        remaining = dict(quotas)
        used_cdr3: set[str] = set()
        used_candidate_ids: set[str] = set()
        selected_parent: list[dict[str, str]] = []
        selected_lengths: set[int] = set()
        for stratum in _slot_order(quotas):
            patch, mode, role = stratum
            options: list[tuple[tuple[float, float, str], Mapping[str, str], float]] = []
            for cdr3, row in candidates.get(stratum, {}).items():
                if cdr3 in used_cdr3 or row["candidate_id"] in used_candidate_ids:
                    continue
                length_novelty = 1.0 if int(row["cdr3_length"]) not in selected_lengths else 0.0
                minimum_distance = (
                    min(normalized_edit_distance(cdr3, prior) for prior in used_cdr3)
                    if used_cdr3
                    else 1.0
                )
                options.append(
                    (
                        (-length_novelty, -minimum_distance, row["selection_hash"]),
                        row,
                        minimum_distance,
                    )
                )
            chosen: tuple[Mapping[str, str], float] | None = None
            for _, row, minimum_distance in sorted(options, key=lambda item: item[0]):
                remaining[stratum] -= 1
                feasible = _unique_cdr3_feasible(
                    candidates, remaining, used_cdr3 | {row["cdr3"]}
                )
                if feasible:
                    chosen = (row, minimum_distance)
                    break
                remaining[stratum] += 1
            if chosen is None:
                raise RuntimeError(
                    f"unique CDR3 diversity selection failed: {parent} {stratum}"
                )
            row, minimum_distance = chosen
            used_cdr3.add(row["cdr3"])
            used_candidate_ids.add(row["candidate_id"])
            selected_lengths.add(int(row["cdr3_length"]))
            output_row = dict(row)
            output_row.update(
                {
                    "acquisition_role": role,
                    "selection_rank_within_parent": str(len(selected_parent) + 1),
                    "cdr3_min_normalized_edit_distance_to_previous": f"{minimum_distance:.6f}",
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )
            selected_parent.append(output_row)

        _validate_selected_parent(selected_parent, parent)
        all_selected.extend(selected_parent)
        if parent_mode_state == ["BALANCED"] * len(PATCHES):
            mode_state = "BALANCED_BOTH_MODES"
        elif parent_mode_state == ["SINGLE"] * len(PATCHES):
            mode_state = "FORCED_SINGLE_MODE_BY_FAST_QC"
        else:
            mode_state = "MAXIMIZED_MODE_BALANCE_UNDER_FAST_QC"
        parent_audit.append(
            {
                "parent_framework_cluster": parent,
                "selected_rows": str(ROWS_PER_PARENT),
                "acquisition_rows": str(ACQUISITION_ROWS_PER_PARENT),
                "audit_rows": str(AUDIT_ROWS_PER_PARENT),
                "unique_cdr3_rows": str(ROWS_PER_PARENT),
                "mode_coverage_state": mode_state,
                "selection_state": READINESS_STATUS,
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )

    all_selected.sort(
        key=lambda row: (
            row["parent_framework_cluster"],
            int(row["selection_rank_within_parent"]),
        )
    )
    return all_selected, parent_audit


def _write_tsv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty TSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _resolve_input(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else DATA_ROOT / path


def _load_and_verify_preregistered_inputs(
    preregistration_path: Path, expected_preregistration_sha256: str
) -> tuple[dict, dict[str, Path]]:
    observed_prereg_sha = sha256_file(preregistration_path)
    if observed_prereg_sha != expected_preregistration_sha256:
        raise RuntimeError(
            "preregistration SHA256 mismatch: "
            f"observed={observed_prereg_sha} expected={expected_preregistration_sha256}"
        )
    prereg = json.loads(preregistration_path.read_text(encoding="utf-8"))
    if prereg["status"] != "FROZEN_BEFORE_SUPPORT_V4_A_PRODUCTION_SELECTION":
        raise RuntimeError(f"invalid preregistration status: {prereg['status']}")
    if prereg["version_boundary"]["support_v3_status_must_remain"] != SUPPORT_V3_FROZEN_STATUS:
        raise RuntimeError("Support V3 frozen FAIL boundary changed")
    paths: dict[str, Path] = {}
    for label, specification in prereg["frozen_inputs"].items():
        path = _resolve_input(specification["path"])
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"invalid frozen input: {label} {path}")
        observed = sha256_file(path)
        if observed != specification["sha256"]:
            raise RuntimeError(
                f"frozen input SHA256 mismatch: {label} observed={observed} expected={specification['sha256']}"
            )
        paths[label] = path
    return prereg, paths


def materialize_production_selection(
    preregistration_path: Path,
    expected_preregistration_sha256: str,
    output_dir: Path,
) -> dict:
    """Future explicit materializer; not invoked by the V4-A freeze workflow."""

    prereg, paths = _load_and_verify_preregistered_inputs(
        preregistration_path, expected_preregistration_sha256
    )
    if output_dir.exists():
        raise RuntimeError(f"output directory already exists: {output_dir}")

    candidate_rows, candidate_fields = read_table(paths["candidate_pool"], ",")
    census_rows, census_fields = read_table(paths["candidate_census"], "\t")
    parent_summary, _ = read_table(paths["parent_census"], "\t")
    v4d_rows, _ = read_table(paths["v4_d_split_manifest"], "\t")
    v4f_rows, _ = read_table(paths["v4_f_manifest"], "\t")
    v4g_rows, _ = read_table(paths["v4_g_manifest"], "\t")
    reserve_rows, _ = read_table(paths["reserve2_manifest"], "\t")
    calibration_rows, _ = read_table(
        paths["known_calibration_identity_exclusions"], "\t"
    )
    require_fields(candidate_fields, ALLOWED_CANDIDATE_FIELDS, "candidate pool")
    require_fields(census_fields, ALLOWED_CENSUS_FIELDS, "candidate census")

    parent_roles = derive_parent_roles(v4d_rows, v4f_rows, v4g_rows, reserve_rows)
    prior_ids = {row["candidate_id"] for row in [*v4d_rows, *v4f_rows, *v4g_rows]}
    prior_sha = {
        row["sequence_sha256"] for row in [*v4d_rows, *v4f_rows, *v4g_rows]
    }
    calibration_sha = {row["sequence_sha256"] for row in calibration_rows}
    eligible, exclusions = collect_eligible_candidates(
        candidate_rows,
        census_rows,
        parent_roles,
        calibration_sequence_sha256=calibration_sha,
        prior_panel_candidate_ids=prior_ids,
        prior_panel_sequence_sha256=prior_sha,
    )
    capacity_audit = build_capacity_audit(eligible, parent_summary, parent_roles)
    selected, selection_parent_audit = select_readiness_pool(eligible, parent_roles)
    if len(selected) != 20 * ROWS_PER_PARENT:
        raise RuntimeError(f"global selected row count mismatch: {len(selected)}")

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp.", dir=str(output_dir.parent))
    )
    try:
        _write_tsv(temporary / "support_v4_a_future_teacher_acquisition_pool_v1.tsv", selected)
        _write_tsv(temporary / "support_v4_a_parent_capacity_audit_v1.tsv", capacity_audit)
        _write_tsv(temporary / "support_v4_a_parent_selection_audit_v1.tsv", selection_parent_audit)
        audit = {
            "schema_version": "phase2_support_v4_a_acquisition_readiness_audit_v1",
            "status": READINESS_STATUS,
            "claim_boundary": CLAIM_BOUNDARY,
            "support_v3_status_preserved": SUPPORT_V3_FROZEN_STATUS,
            "selected_rows": len(selected),
            "open_train_parent_count": 20,
            "acquisition_rows": sum(row["acquisition_role"] == ROLE_ACQUISITION for row in selected),
            "audit_rows": sum(row["acquisition_role"] == ROLE_AUDIT for row in selected),
            "identity_exclusions": dict(sorted(exclusions.items())),
            "label_path_access": {
                "v4_d_geometry": 0,
                "v4_f_labels": 0,
                "docking": 0,
                "model_scores": 0,
                "experimental": 0,
            },
            "allowed_candidate_fields_used": list(ALLOWED_CANDIDATE_FIELDS),
            "allowed_census_fields_used": list(ALLOWED_CENSUS_FIELDS),
            "output_interpretation": "future teacher-acquisition capacity only; not domain PASS",
        }
        (temporary / "support_v4_a_acquisition_readiness_audit_v1.json").write_bytes(
            canonical_json_bytes(audit)
        )
        outputs = {
            path.name: sha256_file(path)
            for path in sorted(temporary.iterdir())
            if path.is_file()
        }
        receipt = {
            "schema_version": "phase2_support_v4_a_acquisition_readiness_receipt_v1",
            "status": READINESS_STATUS,
            "claim_boundary": CLAIM_BOUNDARY,
            "published_at_utc": datetime.now(timezone.utc).isoformat(),
            "preregistration_sha256": expected_preregistration_sha256,
            "input_sha256": {
                label: sha256_file(path) for label, path in sorted(paths.items())
            },
            "output_sha256": outputs,
            "receipt_publication_order": "LAST_AFTER_EXACT_ROLE_IDENTITY_QUOTA_AND_HASH_CLOSURE",
            "support_v3_status_preserved": SUPPORT_V3_FROZEN_STATUS,
            "production_interpretation": "future teacher acquisition only; not domain PASS",
        }
        (temporary / "support_v4_a_acquisition_readiness_receipt_v1.json").write_bytes(
            canonical_json_bytes(receipt)
        )
        os.replace(temporary, output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--materialize-production-selection",
        action="store_true",
        required=True,
        help="Explicit authorization required; implementation-freeze workflow never sets this flag.",
    )
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--expected-preregistration-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.materialize_production_selection:
        raise RuntimeError("--materialize-production-selection is required")
    receipt = materialize_production_selection(
        args.preregistration,
        args.expected_preregistration_sha256,
        args.output_dir,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
