#!/usr/bin/env python3
"""Build Phase 2 V2.5 connected-component splits and sealed formal manifests."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
ROOT = EXP_DIR.parents[1]
DEFAULT_REGISTRY = EXP_DIR / "data_splits/evidence_registry_v2_5.csv"
DEFAULT_TRAIN = EXP_DIR / "data_splits/phase2_v2_5_train_manifest.csv"
DEFAULT_DEV = EXP_DIR / "data_splits/phase2_v2_5_dev_manifest.csv"
DEFAULT_FORMAL_BLINDED = EXP_DIR / "data_splits/phase2_v2_5_generic_formal_manifest_blinded.csv"
DEFAULT_FORMAL_LABELS = EXP_DIR / "data_splits/phase2_v2_5_generic_formal_labels_sealed.csv"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v2_5_split_seal_audit_v1.json"

SEED = 20260711
GENERIC_FORMAL_ALLOWED_USE = "EXPERIMENTAL_RANKING_ONLY"
GENERIC_FORMAL_OPEN_STATUS = "OPEN_DEVELOPMENT"
PVRIG_FORMAL_SEALED_STATUSES = {"SEALED_BLINDED", "SEALED_LABELS"}
LABEL_COLUMNS = [
    "label_value", "label_unit", "label_direction", "normalized_label_value",
    "preference_label", "truth_label", "binary_label", "rank_label", "delta_label",
]
REQUIRED_FIELDS = [
    "sample_id", "vhh_sequence", "sequence_sha256", "target_id", "target_sequence_sha256",
    "target_construct", "label_axis", "evidence_level", "ground_truth_kind", "source_id",
    "source_path_or_locator", "allowed_use", "forbidden_use", "family_id",
    "leakage_group_id", "split_group_id", "sealed_status", "dataset_version",
]
CONDITIONAL_FIELDS = [
    "label_value", "label_unit", "label_direction", "assay_type", "assay_batch",
    "replicate_count", "mutation", "reference_sample_id", "pose_id", "pose_qc_status",
]
LEAKAGE_COLUMNS = [
    "sequence_sha256", "vhh_identity_cluster", "cdr3_cluster", "cdr3", "target_sequence_sha256",
    "target_family", "target_construct", "pdb_id", "structure_group_id", "assay_batch",
    "source_group_id", "source_document_id", "patent_family_id", "base_mutant_group_id",
    "reference_sample_id", "leakage_group_id", "split_group_id",
]
FORMAL_METADATA_COLUMNS = [
    "sample_id", "split", "split_view", "split_group_id", "vhh_sequence", "sequence_sha256",
    "target_id", "target_sequence_sha256", "target_construct", "target_family", "label_axis",
    "evidence_level", "ground_truth_kind", "assay_type", "assay_batch", "source_id",
    "source_path_or_locator", "allowed_use", "forbidden_use", "family_id", "leakage_group_id",
    "vhh_identity_cluster", "cdr3_cluster", "cdr3", "pdb_id", "structure_group_id",
    "assay_batch_group_id", "source_group_id", "source_document_id", "patent_family_id",
    "base_mutant_group_id", "reference_sample_id", "sealed_status", "dataset_version",
    "missing_reason",
]
FORMAL_LABEL_COLUMNS = [
    "sample_id", "split_group_id", "label_axis", "evidence_level", "ground_truth_kind",
    "label_value", "label_unit", "label_direction", "assay_type", "assay_batch", "source_id",
    "dataset_version", "sealed_status",
]


class UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra


def clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."} else text


def normalize_sequence(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper() if "A" <= ch <= "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sequence_hash(sequence: Any) -> str:
    return hashlib.sha256(normalize_sequence(sequence).encode("ascii")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def truthy(value: Any) -> bool:
    return clean(value).lower() in {"1", "true", "yes", "y"}


def evidence_rank(value: Any) -> int | None:
    text = clean(value).upper()
    if text.startswith("E") and text[1:].isdigit():
        return int(text[1:])
    if text.isdigit():
        return int(text)
    return None


def is_pvrig_target(value: Any) -> bool:
    return "PVRIG" in clean(value).upper()


def ensure_columns(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = ""
    return out


def canonicalize_registry(frame: pd.DataFrame) -> pd.DataFrame:
    optional_fields = ["missing_reason", "target_family", "split_view", "assay_batch_group_id"]
    out = ensure_columns(frame, dict.fromkeys(REQUIRED_FIELDS + CONDITIONAL_FIELDS + LEAKAGE_COLUMNS + optional_fields))
    out["sample_id"] = out["sample_id"].map(clean)
    if out["sample_id"].eq("").any() or out["sample_id"].duplicated().any():
        raise ValueError("V2.5 registry requires unique non-empty sample_id values")
    out["vhh_sequence"] = out["vhh_sequence"].map(normalize_sequence)
    blank_seq = out["vhh_sequence"].eq("")
    if blank_seq.any():
        raise ValueError(f"V2.5 registry has empty vhh_sequence rows: {out.loc[blank_seq, 'sample_id'].tolist()[:5]}")
    computed_hashes = out["vhh_sequence"].map(sequence_hash)
    supplied_hashes = out["sequence_sha256"].map(clean)
    hash_mismatch = supplied_hashes.ne("") & supplied_hashes.ne(computed_hashes)
    if hash_mismatch.any():
        raise ValueError(f"sequence_sha256 mismatch rows: {out.loc[hash_mismatch, 'sample_id'].tolist()[:5]}")
    out["sequence_sha256"] = computed_hashes
    for column in ["target_id", "target_sequence_sha256", "target_construct", "label_axis", "evidence_level", "ground_truth_kind", "source_id", "source_path_or_locator", "allowed_use", "forbidden_use", "family_id", "leakage_group_id", "sealed_status", "dataset_version"]:
        out[column] = out[column].map(clean)
    missing_required = {column: out.loc[out[column].eq(""), "sample_id"].tolist()[:5] for column in REQUIRED_FIELDS if column != "split_group_id" and out[column].eq("").any()}
    if missing_required:
        raise ValueError(f"V2.5 registry missing required fields: {missing_required}")
    validate_label_policy(out)
    return out


def validate_label_policy(frame: pd.DataFrame) -> None:
    level = frame["evidence_level"].map(evidence_rank)
    ground_truth = frame["ground_truth_kind"].map(lambda v: clean(v).lower())
    label_axis = frame["label_axis"].map(lambda v: clean(v).lower())
    allowed = frame["allowed_use"].map(lambda v: clean(v).lower())
    missing_reason = frame.get("missing_reason", pd.Series([""] * len(frame))).map(clean)

    bad_proxy_truth = frame.index[
        ((level == 2) | (level == 3))
        & (ground_truth.str.contains("verified_nonbinder|verified_non-binder|blocker_positive|experimental", regex=True))
    ].tolist()
    if bad_proxy_truth:
        raise ValueError(f"Proxy evidence cannot be verified/blocker truth: {frame.loc[bad_proxy_truth, 'sample_id'].tolist()[:5]}")
    bad_e2_bce = frame.index[(level == 2) & allowed.str.contains("ordinary_bce|verified_binary|calibration", regex=True)].tolist()
    if bad_e2_bce:
        raise ValueError(f"E2 constructed proxy cannot be ordinary BCE/calibration eligible: {frame.loc[bad_e2_bce, 'sample_id'].tolist()[:5]}")
    assay_backed = level.isin([4, 5, 6])
    for column in ["label_value", "label_unit", "label_direction", "assay_type", "assay_batch", "replicate_count"]:
        blanks = frame[column].map(clean).eq("")
        bad = frame.index[assay_backed & blanks & missing_reason.eq("")].tolist()
        if bad:
            raise ValueError(f"Assay-backed rows missing {column} without missing_reason: {frame.loc[bad, 'sample_id'].tolist()[:5]}")
    mutation_rows = label_axis.str.contains("mutation", regex=False) | ground_truth.str.contains("mutation", regex=False)
    for column in ["mutation", "reference_sample_id", "label_value"]:
        bad = frame.index[mutation_rows & frame[column].map(clean).eq("") & missing_reason.eq("")].tolist()
        if bad:
            raise ValueError(f"Mutation-effect rows missing {column}: {frame.loc[bad, 'sample_id'].tolist()[:5]}")
    pose_rows = level.eq(3) | ground_truth.str.contains("pose", regex=False)
    for column in ["pose_id", "pose_qc_status"]:
        bad = frame.index[pose_rows & frame[column].map(clean).eq("") & missing_reason.eq("")].tolist()
        if bad:
            raise ValueError(f"Pose proxy rows missing {column}: {frame.loc[bad, 'sample_id'].tolist()[:5]}")


def cleaned_column(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.get(column, pd.Series("", index=frame.index, dtype=object)).map(clean)


def assay_batch_leakage_keys(frame: pd.DataFrame) -> pd.Series:
    """Return only shared assay batches that carry experiment-level leakage meaning."""
    batch = cleaned_column(frame, "assay_batch")
    source = cleaned_column(frame, "source_id")
    target = cleaned_column(frame, "target_sequence_sha256")
    explicit = cleaned_column(frame, "assay_batch_group_id")
    keys = pd.Series("", index=frame.index, dtype=object)

    explicit_mask = explicit.ne("")
    keys.loc[explicit_mask] = explicit.loc[explicit_mask].map(lambda value: f"explicit:{value}")
    candidates = pd.DataFrame({"source": source, "batch": batch, "target": target}, index=frame.index)
    candidates = candidates[batch.ne("") & ~explicit_mask]
    for (source_id, batch_id), indexes in candidates.groupby(["source", "batch"], sort=False).groups.items():
        if len(indexes) < 2:
            continue
        source_rows = candidates[candidates["source"].eq(source_id)]
        dataset_level_constant = (
            source_rows["batch"].nunique() == 1
            and source_rows.loc[source_rows["target"].ne(""), "target"].nunique() > 1
        )
        if not dataset_level_constant:
            keys.loc[indexes] = f"{source_id}:{batch_id}"
    return keys


def leakage_key_values(frame: pd.DataFrame) -> dict[str, pd.Series]:
    values = {column: cleaned_column(frame, column) for column in LEAKAGE_COLUMNS}
    values["assay_batch"] = assay_batch_leakage_keys(frame)
    target_family = values["target_family"]
    values["target_family"] = target_family.where(target_family.ne(""), cleaned_column(frame, "target_id"))
    return values


def assign_connected_components(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    ids = out["sample_id"].astype(str).tolist()
    id_set = set(ids)
    uf = UnionFind(ids)
    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key_name, values in leakage_key_values(out).items():
        if key_name == "split_group_id":
            continue
        for index, value in values.items():
            if value:
                by_key[(key_name, value)].append(clean(out.at[index, "sample_id"]))
    for members in by_key.values():
        first = members[0]
        for member in members[1:]:
            uf.union(first, member)
    for _, row in out.iterrows():
        reference = clean(row.get("reference_sample_id"))
        if reference in id_set:
            uf.union(clean(row["sample_id"]), reference)
    components: dict[str, list[str]] = defaultdict(list)
    for sample_id in ids:
        components[uf.find(sample_id)].append(sample_id)
    stable_ids: dict[str, str] = {}
    for members in components.values():
        token = "|".join(sorted(members))
        stable = f"cc_{sha256_text(token)[:16]}"
        for member in members:
            stable_ids[member] = stable
    out["split_group_id"] = out["sample_id"].map(stable_ids)
    return out


def stable_order(values: Iterable[str], seed: int = SEED) -> list[str]:
    return sorted(values, key=lambda v: sha256_text(f"{seed}|{v}"))


def select_groups_near_target(
    row_counts: dict[str, int],
    target_rows: float,
    allocation_pool: set[str],
    minimum_pool_groups_remaining: int,
    seed: int,
) -> set[str]:
    selected: set[str] = set()
    selected_rows = 0
    candidates = set(row_counts) & allocation_pool
    while candidates - selected:
        options = [
            group_id
            for group_id in candidates - selected
            if len(allocation_pool - selected - {group_id}) >= minimum_pool_groups_remaining
        ]
        if not options:
            break
        ordered = stable_order(options, seed)
        best = min(ordered, key=lambda group_id: abs(target_rows - selected_rows - row_counts[group_id]))
        current_distance = abs(target_rows - selected_rows)
        next_distance = abs(target_rows - selected_rows - row_counts[best])
        if selected and next_distance >= current_distance:
            break
        selected.add(best)
        selected_rows += row_counts[best]
        if next_distance == 0:
            break
    return selected


def choose_splits(frame: pd.DataFrame, dev_fraction: float = 0.20, formal_fraction: float = 0.20, seed: int = SEED) -> pd.Series:
    if not 0.0 <= formal_fraction < 1.0 or not 0.0 <= dev_fraction < 1.0:
        raise ValueError("Split fractions must be in [0, 1)")
    components = frame.groupby("split_group_id", sort=False)
    component_ids = set(components.groups)
    generic_group_row_counts: dict[str, int] = {}
    generic_formal_row_counts: dict[str, int] = {}
    prospective_pvrig_groups: set[str] = set()
    for group_id, group in components:
        level = group["evidence_level"].map(evidence_rank)
        target_is_pvrig = group["target_id"].map(is_pvrig_target)
        sealed = group["sealed_status"].map(lambda value: clean(value).upper())
        allowed = group["allowed_use"].map(lambda value: clean(value).upper())
        forbidden = group["forbidden_use"].map(lambda value: clean(value).upper())
        assay_backed = level.isin([4, 5, 6])
        generic_assay = (~target_is_pvrig) & assay_backed
        generic_ranking = generic_assay & allowed.eq(GENERIC_FORMAL_ALLOWED_USE)
        generic_formal_rows = generic_ranking & sealed.eq(GENERIC_FORMAL_OPEN_STATUS)
        if generic_assay.any():
            generic_group_row_counts[group_id] = int(generic_assay.sum())
        pvrig_assay = target_is_pvrig & assay_backed
        if (
            generic_formal_rows.any()
            and int(generic_formal_rows.sum()) == int(generic_assay.sum())
            and not pvrig_assay.any()
        ):
            generic_formal_row_counts[group_id] = int(generic_assay.sum())

        pvrig_formal_rows = (
            target_is_pvrig
            & level.eq(6)
            & allowed.eq(GENERIC_FORMAL_ALLOWED_USE)
            & sealed.isin(PVRIG_FORMAL_SEALED_STATUSES)
            & ~forbidden.str.contains("TARGET_FORMAL|FORMAL_CLAIM|FORMAL_EVALUATION", regex=True)
        )
        prospective_pvrig = (
            target_is_pvrig.all()
            and pvrig_formal_rows.any()
            and int(pvrig_formal_rows.sum()) == int(pvrig_assay.sum())
        )
        if prospective_pvrig:
            prospective_pvrig_groups.add(group_id)

    generic_group_ids = set(generic_group_row_counts)
    generic_formal_groups: set[str] = set()
    generic_dev_groups: set[str] = set()
    # Oversized components stay in train when either holdout would be farther from its target.
    requested_formal_rows = sum(generic_group_row_counts.values()) * formal_fraction
    requested_dev_rows = sum(generic_group_row_counts.values()) * dev_fraction
    dominant_cutoff = 2.0 * max(requested_formal_rows, requested_dev_rows, 1.0)
    protected_train_groups = {
        group_id for group_id, count in generic_group_row_counts.items() if count > dominant_cutoff
    }
    holdout_pool = generic_group_ids - protected_train_groups

    # Balance formal and dev against generic assay rows only; metadata volume is irrelevant.
    if formal_fraction > 0.0 and generic_group_ids:
        if not generic_formal_row_counts:
            raise ValueError("Generic formal split requested but no assay-backed rows are formal eligible")
        if dev_fraction <= 0.0 or len(generic_group_ids) < 3 or len(holdout_pool) < 2:
            raise ValueError("Requested generic formal split would exhaust generic train or dev ranking groups")
        if not (set(generic_formal_row_counts) & holdout_pool):
            raise ValueError("Generic formal split requested but no eligible component can leave train intact")
        max_holdout_rows = sum(generic_group_row_counts[group_id] for group_id in holdout_pool)
        requested_holdout_rows = requested_formal_rows + requested_dev_rows
        if not protected_train_groups:
            max_holdout_rows -= min(generic_group_row_counts[group_id] for group_id in holdout_pool)
            if requested_holdout_rows > max_holdout_rows:
                raise ValueError("Requested generic formal split would exhaust generic train or dev ranking groups")
        actual_holdout_target = min(requested_holdout_rows, max_holdout_rows)
        scale = actual_holdout_target / requested_holdout_rows if requested_holdout_rows > 0 else 0.0
        formal_target = max(1.0, requested_formal_rows * scale)
        minimum_after_formal = 1 if protected_train_groups else 2
        generic_formal_groups = select_groups_near_target(
            generic_formal_row_counts,
            formal_target,
            holdout_pool,
            minimum_after_formal,
            seed,
        )
        if not generic_formal_groups:
            raise ValueError("Generic formal split requested but no eligible component was selected")
        selected_formal_rows = sum(generic_group_row_counts[group_id] for group_id in generic_formal_groups)
        remaining_holdout_pool = holdout_pool - generic_formal_groups
        dev_target = max(1.0, actual_holdout_target - selected_formal_rows)
        generic_dev_groups = select_groups_near_target(
            generic_group_row_counts,
            dev_target,
            remaining_holdout_pool,
            0 if protected_train_groups else 1,
            seed,
        )
    elif dev_fraction > 0.0 and len(generic_group_ids) >= 2:
        generic_dev_groups = select_groups_near_target(
            generic_group_row_counts,
            max(1.0, requested_dev_rows),
            generic_group_ids,
            1,
            seed,
        )

    generic_train_groups = generic_group_ids - generic_formal_groups - generic_dev_groups
    if generic_formal_groups and (not generic_dev_groups or not generic_train_groups):
        raise ValueError("Requested generic formal split would exhaust generic train or dev ranking groups")

    formal_groups = generic_formal_groups | prospective_pvrig_groups
    # Auxiliary and non-formal PVRIG components are allocated only after generic quotas are fixed.
    other_groups = component_ids - generic_group_ids - formal_groups
    other_dev_groups: set[str] = set()
    if dev_fraction > 0.0 and other_groups:
        target_other_dev_rows = max(
            1,
            int(round(sum(len(components.get_group(group_id)) for group_id in other_groups) * dev_fraction)),
        )
        selected_other_rows = 0
        for group_id in stable_order(other_groups, seed):
            other_dev_groups.add(group_id)
            selected_other_rows += int(len(components.get_group(group_id)))
            if selected_other_rows >= target_other_dev_rows:
                break

    dev_groups = generic_dev_groups | other_dev_groups
    split_by_group = {group_id: "formal" for group_id in formal_groups}
    split_by_group.update({group_id: "dev" for group_id in dev_groups})
    return frame["split_group_id"].map(lambda group_id: split_by_group.get(group_id, "train"))


def make_formal_blinded(formal: pd.DataFrame) -> pd.DataFrame:
    blinded = ensure_columns(formal, FORMAL_METADATA_COLUMNS)[[c for c in FORMAL_METADATA_COLUMNS if c in ensure_columns(formal, FORMAL_METADATA_COLUMNS).columns]].copy()
    for column in LABEL_COLUMNS:
        if column in blinded.columns:
            raise ValueError(f"Blinded formal manifest exposes label column: {column}")
    blinded["sealed_status"] = "SEALED_BLINDED"
    return blinded


def make_formal_labels(formal: pd.DataFrame) -> pd.DataFrame:
    level = formal.get("evidence_level", pd.Series("", index=formal.index)).map(evidence_rank)
    target_is_pvrig = formal.get("target_id", pd.Series("", index=formal.index)).map(is_pvrig_target)
    allowed = cleaned_column(formal, "allowed_use").str.upper()
    sealed = cleaned_column(formal, "sealed_status").str.upper()
    forbidden = cleaned_column(formal, "forbidden_use").str.upper()
    generic_formal = (~target_is_pvrig) & level.isin([4, 5, 6]) & allowed.eq(GENERIC_FORMAL_ALLOWED_USE)
    pvrig_formal = (
        target_is_pvrig
        & level.eq(6)
        & allowed.eq(GENERIC_FORMAL_ALLOWED_USE)
        & sealed.isin(PVRIG_FORMAL_SEALED_STATUSES)
        & ~forbidden.str.contains("TARGET_FORMAL|FORMAL_CLAIM|FORMAL_EVALUATION", regex=True)
    )
    labeled = generic_formal | pvrig_formal
    for column in ["label_value", "label_unit", "label_direction"]:
        labeled &= cleaned_column(formal, column).ne("")
    labels = ensure_columns(formal.loc[labeled], FORMAL_LABEL_COLUMNS)[FORMAL_LABEL_COLUMNS].copy()
    labels["sealed_status"] = "SEALED_LABELS"
    return labels


def leakage_overlap_audit(split_frame: pd.DataFrame) -> dict[str, Any]:
    audit: dict[str, Any] = {}
    split_names = split_frame.get("split", pd.Series("", index=split_frame.index)).map(clean)
    pairs = [("train", "dev"), ("train", "formal"), ("dev", "formal")]
    for column, values in leakage_key_values(split_frame).items():
        column_audit: dict[str, int] = {}
        for left, right in pairs:
            left_values = {value for value in values.loc[split_names.eq(left)] if value}
            right_values = {value for value in values.loc[split_names.eq(right)] if value}
            column_audit[f"{left}_vs_{right}"] = len(left_values & right_values)
        audit[column] = column_audit
    return audit


def assert_zero_leakage_overlap(audit: dict[str, Any]) -> None:
    failures = {
        f"{key}.{pair}": int(count)
        for key, pairs in audit.items()
        if isinstance(pairs, dict)
        for pair, count in pairs.items()
        if int(count) != 0
    }
    if failures:
        raise ValueError(f"Nonzero split leakage overlap on supported keys: {failures}")


def assert_no_formal_label_leakage(train: pd.DataFrame, dev: pd.DataFrame, formal_blinded: pd.DataFrame) -> None:
    for name, frame in [("train", train), ("dev", dev), ("formal_blinded", formal_blinded)]:
        forbidden = [column for column in LABEL_COLUMNS if column in frame.columns] if name == "formal_blinded" else []
        if forbidden:
            raise ValueError(f"{name} exposes formal label columns: {forbidden}")
    formal_ids = set(formal_blinded.get("sample_id", pd.Series(dtype=str)).map(clean))
    if formal_ids:
        for name, frame in [("train", train), ("dev", dev)]:
            overlap = set(frame.get("sample_id", pd.Series(dtype=str)).map(clean)) & formal_ids
            if overlap:
                raise ValueError(f"{name} includes formal sample IDs: {sorted(overlap)[:5]}")


def build_splits(
    registry_path: Path,
    train_path: Path,
    dev_path: Path,
    formal_blinded_path: Path,
    formal_labels_path: Path,
    audit_path: Path,
    dev_fraction: float = 0.20,
    formal_fraction: float = 0.20,
    seed: int = SEED,
) -> dict[str, Any]:
    registry = canonicalize_registry(pd.read_csv(registry_path))
    split_frame = assign_connected_components(registry)
    split_frame["split"] = choose_splits(split_frame, dev_fraction=dev_fraction, formal_fraction=formal_fraction, seed=seed)
    split_frame["split_view"] = split_frame.apply(
        lambda row: "prospective_pvrig_formal" if row["split"] == "formal" and is_pvrig_target(row["target_id"]) else (
            "generic_heldout_target_family" if row["split"] == "formal" else "target_within_family_leave_block_out"
        ),
        axis=1,
    )
    train = split_frame[split_frame["split"] == "train"].copy()
    dev = split_frame[split_frame["split"] == "dev"].copy()
    formal = split_frame[split_frame["split"] == "formal"].copy()
    formal_blinded = make_formal_blinded(formal)
    formal_labels = make_formal_labels(formal)
    assert_no_formal_label_leakage(train, dev, formal_blinded)
    leakage_audit = leakage_overlap_audit(split_frame)
    assert_zero_leakage_overlap(leakage_audit)

    for path, frame in [(train_path, train), (dev_path, dev), (formal_blinded_path, formal_blinded), (formal_labels_path, formal_labels)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    output_hashes = {
        "train_manifest": file_sha256(train_path),
        "dev_manifest": file_sha256(dev_path),
        "formal_manifest_blinded": file_sha256(formal_blinded_path),
        "formal_labels_sealed": file_sha256(formal_labels_path),
    }
    formal_has_pvrig = formal["target_id"].map(is_pvrig_target).any() if not formal.empty else False
    audit = {
        "schema_version": "phase2_v2_5_split_seal_v1",
        "status": "PASS",
        "created_at_utc": now_utc(),
        "seed": seed,
        "input_sha256": {"registry": file_sha256(registry_path)},
        "output_sha256": output_hashes,
        "chronology": [
            {"event": "registry_loaded", "path": str(registry_path), "sha256": file_sha256(registry_path)},
            {"event": "connected_components_assigned", "component_count": int(split_frame["split_group_id"].nunique())},
            {"event": "zero_supported_key_overlap_asserted"},
            {"event": "formal_labels_sealed", "path": str(formal_labels_path), "sha256": output_hashes["formal_labels_sealed"]},
            {"event": "formal_manifest_blinded", "path": str(formal_blinded_path), "sha256": output_hashes["formal_manifest_blinded"]},
        ],
        "row_counts": {"train": int(len(train)), "dev": int(len(dev)), "formal_blinded": int(len(formal_blinded)), "formal_labels_sealed": int(len(formal_labels))},
        "split_group_counts": split_frame.groupby("split")["split_group_id"].nunique().astype(int).to_dict(),
        "formal_scope": "PVRIG_TARGET_FORMAL" if formal_has_pvrig else "GENERIC_FORMAL_ONLY",
        "formal_labels_read_by_train_or_dev": False,
        "leakage_overlap_audit": leakage_audit,
        "label_columns_absent_from_formal_blinded": not any(column in formal_blinded.columns for column in LABEL_COLUMNS),
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    return audit


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--train-out", type=Path, default=DEFAULT_TRAIN)
    parser.add_argument("--dev-out", type=Path, default=DEFAULT_DEV)
    parser.add_argument("--formal-blinded-out", type=Path, default=DEFAULT_FORMAL_BLINDED)
    parser.add_argument("--formal-labels-out", type=Path, default=DEFAULT_FORMAL_LABELS)
    parser.add_argument("--audit-out", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--dev-fraction", type=float, default=0.20)
    parser.add_argument("--formal-fraction", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=SEED)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audit = build_splits(
        args.registry, args.train_out, args.dev_out, args.formal_blinded_out,
        args.formal_labels_out, args.audit_out, args.dev_fraction, args.formal_fraction, args.seed,
    )
    print(json.dumps({"status": audit["status"], "row_counts": audit["row_counts"], "formal_scope": audit["formal_scope"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
