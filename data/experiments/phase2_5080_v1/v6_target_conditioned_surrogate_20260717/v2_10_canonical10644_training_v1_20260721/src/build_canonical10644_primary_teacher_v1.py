#!/usr/bin/env python3
"""Materialize the V2.10 canonical open teacher with joint CDR3 isolation.

The numeric access boundary is deliberate: canonical split and label status
are checked before any target is converted to float.  Frozen, already
quarantined, and TECHNICAL_NA rows therefore have zero numeric-target parses.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "pvrig_v2_10_canonical10644_teacher_builder_v1"
RECEIPT_SCHEMA = "pvrig_v2_10_canonical10644_materialization_receipt_v1"
SPLIT_SCHEMA = "pvrig_v2_9_whole_parent_split_v1"
CLAIM = (
    "Open-development sequence-to-independent-dual-receptor computational "
    "Docking geometry weak supervision only; not binding, affinity, "
    "experimental blocking, Docking Gold, frozen-test, or formal validation."
)
AA = set("ACDEFGHIKLMNPQRSTVWY")
OPEN_SPLITS = {"train", "development"}
CANONICAL_SPLITS = OPEN_SPLITS | {"frozen_test", "quarantine_cdr3_overlap"}
WEAK_LABEL = "WEAK_LABEL_AVAILABLE"
TECHNICAL_NA = "TECHNICAL_NA"
OUTPUT_COLUMNS = (
    "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster",
    "cdr1", "cdr2", "cdr3", "sample_weight", "R_8X6B", "R_9E6Y",
    "R_dual_min", "teacher_source", "teacher_reliability",
)
LEGACY_REQUIRED = set(OUTPUT_COLUMNS)
CANONICAL_METADATA_REQUIRED = {
    "candidate_id", "sequence", "sequence_sha256", "cdr1", "cdr2", "cdr3",
    "parent_framework_cluster", "training_label_status", "parent_only_model_split",
    "canonical_model_split", "R8_primary_seed917", "R9_primary_seed917",
    "R_dual_min", "successful_dual_seed_count",
}
QUARANTINE_COLUMNS = (
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "cdr3",
    "original_split", "owner_split", "joint_cdr3_family_id",
    "joint_cdr3_family_size", "quarantine_reason",
)
WEIGHT_BY_SEED_COUNT = {1: 0.65, 2: 0.80, 3: 1.00}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_set_hash(values: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(set(values))) + "\n").encode()).hexdigest()


def verify_regular_hash(path: Path, expected: str, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label}_not_regular:{path}")
    require(len(expected) == 64, f"{label}_expected_hash_invalid")
    require(sha256_file(path) == expected, f"{label}_hash_mismatch")


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"{label}_not_regular:{path}")
    payload = json.loads(path.read_text())
    require(isinstance(payload, dict), f"{label}_not_object")
    return payload


def validate_sequence(raw: dict[str, str], source: str) -> dict[str, str]:
    candidate_id = raw["candidate_id"].strip()
    sequence = raw["sequence"].strip().upper()
    sequence_sha = raw["sequence_sha256"].strip()
    require(candidate_id, f"empty_candidate_id:{source}")
    require(sequence and set(sequence) <= AA, f"invalid_sequence:{candidate_id}")
    require(hashlib.sha256(sequence.encode("ascii")).hexdigest() == sequence_sha, f"sequence_hash:{candidate_id}")
    parent = raw["parent_framework_cluster"].strip()
    require(parent, f"empty_parent:{candidate_id}")
    result = {
        "candidate_id": candidate_id,
        "sequence_sha256": sequence_sha,
        "sequence": sequence,
        "parent_framework_cluster": parent,
    }
    for key in ("cdr1", "cdr2", "cdr3"):
        value = raw[key].strip().upper()
        require(value and value in sequence, f"invalid_{key}:{candidate_id}")
        result[key] = value
    return result


def parse_exact_geometry(
    *, candidate_id: str, r8_raw: str, r9_raw: str, dual_raw: str,
) -> tuple[float, float, float]:
    r8, r9, dual = float(r8_raw), float(r9_raw), float(dual_raw)
    require(all(math.isfinite(value) for value in (r8, r9, dual)), f"nonfinite_geometry:{candidate_id}")
    require(abs(min(r8, r9) - dual) < 2e-8, f"truth_exact_min:{candidate_id}")
    return r8, r9, dual


def validate_release_receipt(path: Path, expected_sha256: str) -> dict[str, Any]:
    verify_regular_hash(path, expected_sha256, "canonical_release_receipt")
    receipt = load_json(path, "canonical_release_receipt")
    require(receipt.get("schema_version") == "pvrig_v29_canonical_training_release_v1", "release_receipt_schema")
    require(receipt.get("status") == "PASS_CANONICAL_RELEASE", "release_receipt_status")
    require(
        receipt.get("target_contract", {}).get("uniform_training_target")
        == "R_dual_min=min(R8_primary_seed917,R9_primary_seed917)",
        "release_target_contract",
    )
    return receipt


def load_legacy_d0(
    teacher_path: Path,
    manifest_path: Path,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    manifest = load_json(manifest_path, "legacy_manifest")
    require(manifest.get("schema_version") == SPLIT_SCHEMA, "legacy_split_schema")
    require(manifest.get("data_version") == "D0", "legacy_not_D0")
    require(manifest.get("open_only") is True, "legacy_not_open")
    require(manifest.get("frozen_test_access_count") == 0, "legacy_frozen_access")
    require(manifest.get("sealed_truth_access_count", 0) == 0, "legacy_sealed_access")
    require(manifest.get("training_tsv_sha256") == sha256_file(teacher_path), "legacy_teacher_manifest_hash")
    train_parents = set(manifest.get("train_parents", []))
    dev_parents = set(manifest.get("score_parents", []))
    frozen_parents = set(manifest.get("frozen_test_parents", []))
    require(train_parents and dev_parents and frozen_parents, "legacy_parent_sets_empty")
    require(train_parents.isdisjoint(dev_parents | frozen_parents), "legacy_parent_overlap")
    require(dev_parents.isdisjoint(frozen_parents), "legacy_dev_frozen_overlap")
    require(stable_set_hash(train_parents) == manifest.get("train_parent_set_sha256"), "legacy_train_parent_hash")
    require(stable_set_hash(dev_parents) == manifest.get("score_parent_set_sha256"), "legacy_dev_parent_hash")
    require(stable_set_hash(frozen_parents) == manifest.get("frozen_test_parent_set_sha256"), "legacy_frozen_parent_hash")

    rows: list[dict[str, str]] = []
    ids: set[str] = set()
    sequences: set[str] = set()
    with teacher_path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(LEGACY_REQUIRED.issubset(set(reader.fieldnames or [])), "legacy_columns_missing")
        for raw in reader:
            seq = validate_sequence(raw, "legacy_D0")
            candidate_id = seq["candidate_id"]
            require(candidate_id not in ids, f"duplicate_legacy_candidate:{candidate_id}")
            require(seq["sequence_sha256"] not in sequences, f"duplicate_legacy_sequence:{candidate_id}")
            parent = seq["parent_framework_cluster"]
            require(parent not in frozen_parents, f"legacy_frozen_parent:{candidate_id}")
            if parent in train_parents:
                assigned_split = "train"
            elif parent in dev_parents:
                assigned_split = "development"
            else:
                raise RuntimeError(f"legacy_parent_outside_manifest:{candidate_id}")
            r8, r9, dual = parse_exact_geometry(
                candidate_id=candidate_id,
                r8_raw=raw["R_8X6B"], r9_raw=raw["R_9E6Y"], dual_raw=raw["R_dual_min"],
            )
            weight = float(raw["sample_weight"])
            require(math.isfinite(weight) and weight > 0, f"legacy_weight:{candidate_id}")
            rows.append({
                **seq,
                "sample_weight": f"{weight:.9g}",
                "R_8X6B": f"{r8:.9f}",
                "R_9E6Y": f"{r9:.9f}",
                "R_dual_min": f"{dual:.9f}",
                "teacher_source": raw["teacher_source"].strip(),
                "teacher_reliability": raw["teacher_reliability"].strip(),
                "_assigned_split": assigned_split,
                "_input_source": "legacy_D0",
            })
            ids.add(candidate_id)
            sequences.add(seq["sequence_sha256"])
    require(len(rows) == int(manifest["expected_total_rows"]), "legacy_total_count")
    return rows, manifest


def load_canonical_open(
    path: Path,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Gate split/status before numeric conversion, then parse only open labels."""
    rows: list[dict[str, str]] = []
    ids: set[str] = set()
    sequences: set[str] = set()
    parent_splits: dict[str, str] = {}
    counters: Counter[str] = Counter()
    numeric_parse_by_split: Counter[str] = Counter()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(CANONICAL_METADATA_REQUIRED.issubset(set(reader.fieldnames or [])), "canonical_columns_missing")
        for raw in reader:
            # Label-free identity/split fields are validated first.
            seq = validate_sequence(raw, "canonical_release")
            candidate_id = seq["candidate_id"]
            require(candidate_id not in ids, f"duplicate_canonical_candidate:{candidate_id}")
            require(seq["sequence_sha256"] not in sequences, f"duplicate_canonical_sequence:{candidate_id}")
            canonical_split = raw["canonical_model_split"].strip()
            parent_split = raw["parent_only_model_split"].strip()
            status = raw["training_label_status"].strip()
            require(canonical_split in CANONICAL_SPLITS, f"invalid_canonical_split:{candidate_id}")
            require(parent_split in {"train", "development", "frozen_test"}, f"invalid_parent_split:{candidate_id}")
            require(status in {WEAK_LABEL, TECHNICAL_NA}, f"invalid_label_status:{candidate_id}")
            parent = seq["parent_framework_cluster"]
            if parent in parent_splits:
                require(parent_splits[parent] == parent_split, f"canonical_parent_split_inconsistent:{parent}")
            parent_splits[parent] = parent_split
            counters[f"{canonical_split}|{status}"] += 1
            ids.add(candidate_id)
            sequences.add(seq["sequence_sha256"])

            # Critical access boundary: return before numeric parsing.
            if canonical_split not in OPEN_SPLITS or status != WEAK_LABEL:
                if status == TECHNICAL_NA:
                    require(
                        not raw["R8_primary_seed917"].strip()
                        and not raw["R9_primary_seed917"].strip()
                        and not raw["R_dual_min"].strip(),
                        f"technical_na_numeric_imputation:{candidate_id}",
                    )
                continue
            require(parent_split == canonical_split, f"open_parent_canonical_split_mismatch:{candidate_id}")
            r8, r9, dual = parse_exact_geometry(
                candidate_id=candidate_id,
                r8_raw=raw["R8_primary_seed917"],
                r9_raw=raw["R9_primary_seed917"],
                dual_raw=raw["R_dual_min"],
            )
            numeric_parse_by_split[canonical_split] += 1
            seed_count = int(raw["successful_dual_seed_count"])
            require(seed_count in WEIGHT_BY_SEED_COUNT, f"unsupported_seed_count:{candidate_id}:{seed_count}")
            rows.append({
                **seq,
                "sample_weight": f"{WEIGHT_BY_SEED_COUNT[seed_count]:.9g}",
                "R_8X6B": f"{r8:.9f}",
                "R_9E6Y": f"{r9:.9f}",
                "R_dual_min": f"{dual:.9f}",
                "teacher_source": "V29_CANONICAL_PRIMARY_SEED917",
                "teacher_reliability": f"DUAL_{seed_count}_SEED",
                "_assigned_split": canonical_split,
                "_input_source": "V29_canonical_release",
            })
    split_sets = {
        split: {parent for parent, value in parent_splits.items() if value == split}
        for split in ("train", "development", "frozen_test")
    }
    require(all(split_sets.values()), "canonical_parent_split_set_empty")
    require(split_sets["train"].isdisjoint(split_sets["development"] | split_sets["frozen_test"]), "canonical_parent_overlap")
    require(split_sets["development"].isdisjoint(split_sets["frozen_test"]), "canonical_dev_frozen_overlap")
    return rows, {
        "all_candidate_rows": len(ids),
        "status_split_counts": dict(sorted(counters.items())),
        "numeric_parse_by_split": dict(sorted(numeric_parse_by_split.items())),
        "numeric_parse_frozen_test": 0,
        "numeric_parse_quarantine": 0,
        "numeric_parse_technical_na": 0,
        "parent_sets": {key: sorted(value) for key, value in split_sets.items()},
    }


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left, right = self.find(left), self.find(right)
        if left == right:
            return
        if self.rank[left] < self.rank[right]:
            left, right = right, left
        self.parent[right] = left
        if self.rank[left] == self.rank[right]:
            self.rank[left] += 1


def mismatch_limit(length: int) -> int:
    return int(math.floor(length * 0.20 + 1e-12))


def joint_cdr3_quarantine(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    """Build equal-length Hamming>=80% components; train owns mixed components."""
    uf = UnionFind(len(rows))
    by_length: dict[int, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        by_length[len(row["cdr3"])].append(index)
    edge_count = 0
    for length, indices in sorted(by_length.items()):
        allowed = mismatch_limit(length)
        for offset, left in enumerate(indices):
            left_seq = rows[left]["cdr3"]
            for right in indices[offset + 1:]:
                mismatches = 0
                for aa_left, aa_right in zip(left_seq, rows[right]["cdr3"]):
                    if aa_left != aa_right:
                        mismatches += 1
                        if mismatches > allowed:
                            break
                if mismatches <= allowed:
                    uf.union(left, right)
                    edge_count += 1
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        components[uf.find(index)].append(index)

    quarantine_indices: set[int] = set()
    quarantine_rows: list[dict[str, str]] = []
    mixed_components = 0
    for indices in components.values():
        splits = {rows[index]["_assigned_split"] for index in indices}
        if len(splits) == 1:
            continue
        require(splits == {"train", "development"}, f"unexpected_joint_component_splits:{splits}")
        mixed_components += 1
        owner_split = "train"
        family_basis = "\n".join(sorted(rows[index]["sequence_sha256"] for index in indices)) + "\n"
        family_id = "CDR3J80_" + hashlib.sha256(family_basis.encode()).hexdigest()[:16]
        for index in indices:
            row = rows[index]
            if row["_assigned_split"] == owner_split:
                continue
            quarantine_indices.add(index)
            quarantine_rows.append({
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "parent_framework_cluster": row["parent_framework_cluster"],
                "cdr3": row["cdr3"],
                "original_split": row["_assigned_split"],
                "owner_split": owner_split,
                "joint_cdr3_family_id": family_id,
                "joint_cdr3_family_size": str(len(indices)),
                "quarantine_reason": "JOINT_CDR3_HAMMING80_COMPONENT_OWNED_BY_TRAIN",
            })
    kept = [row for index, row in enumerate(rows) if index not in quarantine_indices]
    quarantine_rows.sort(key=lambda row: row["candidate_id"])
    return kept, quarantine_rows, {
        "joint_graph_nodes": len(rows),
        "joint_graph_edges": edge_count,
        "joint_graph_components": len(components),
        "mixed_split_components": mixed_components,
        "new_quarantine_rows": len(quarantine_rows),
    }


def write_tsv(path: Path, rows: list[dict[str, str]], columns: Iterable[str]) -> None:
    columns = tuple(columns)
    require(bool(rows), f"empty_output:{path.name}")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row[key] for key in columns} for row in rows)


def create_manifest(
    teacher_path: Path,
    rows: list[dict[str, str]],
    frozen_parents: set[str],
    split_id: str,
) -> dict[str, Any]:
    train_parents = {row["parent_framework_cluster"] for row in rows if row["_assigned_split"] == "train"}
    dev_parents = {row["parent_framework_cluster"] for row in rows if row["_assigned_split"] == "development"}
    require(train_parents and dev_parents and frozen_parents, "final_parent_set_empty")
    require(train_parents.isdisjoint(dev_parents | frozen_parents), "final_parent_overlap")
    require(dev_parents.isdisjoint(frozen_parents), "final_dev_frozen_overlap")
    train_rows = sum(row["_assigned_split"] == "train" for row in rows)
    dev_rows = len(rows) - train_rows
    return {
        "schema_version": SPLIT_SCHEMA,
        "data_version": "D1",
        "split_id": split_id,
        "open_only": True,
        "frozen_test_access_count": 0,
        "sealed_truth_access_count": 0,
        "training_tsv_sha256": sha256_file(teacher_path),
        "train_parents": sorted(train_parents),
        "score_parents": sorted(dev_parents),
        "frozen_test_parents": sorted(frozen_parents),
        "train_parent_set_sha256": stable_set_hash(train_parents),
        "score_parent_set_sha256": stable_set_hash(dev_parents),
        "frozen_test_parent_set_sha256": stable_set_hash(frozen_parents),
        "expected_total_rows": len(rows),
        "expected_train_rows": train_rows,
        "expected_score_rows": dev_rows,
        "joint_cdr3_isolation": "equal_length_hamming_identity_gte_0.80_connected_components_train_owner_v1",
        "claim_boundary": CLAIM,
    }


def gate_count(observed: int, expected: int | None, label: str) -> None:
    if expected is not None:
        require(observed == expected, f"{label}_mismatch:{observed}")


def materialize(
    *,
    legacy_d0_tsv: Path,
    legacy_d0_sha256: str,
    legacy_d0_manifest: Path,
    legacy_d0_manifest_sha256: str,
    canonical_tsv: Path,
    canonical_tsv_sha256: str,
    canonical_release_receipt: Path,
    canonical_release_receipt_sha256: str,
    output_dir: Path,
    split_id: str,
    expected_raw_union: int | None = 10645,
    expected_train: int | None = 9849,
    expected_development: int | None = 795,
    expected_final: int | None = 10644,
    expected_new_quarantine: int | None = 1,
) -> dict[str, Any]:
    verify_regular_hash(legacy_d0_tsv, legacy_d0_sha256, "legacy_d0")
    verify_regular_hash(legacy_d0_manifest, legacy_d0_manifest_sha256, "legacy_d0_manifest")
    verify_regular_hash(canonical_tsv, canonical_tsv_sha256, "canonical_tsv")
    release_receipt = validate_release_receipt(canonical_release_receipt, canonical_release_receipt_sha256)
    require(not output_dir.exists(), "output_dir_exists")

    legacy_rows, legacy_manifest = load_legacy_d0(legacy_d0_tsv, legacy_d0_manifest)
    canonical_rows, canonical_audit = load_canonical_open(canonical_tsv)
    legacy_ids = {row["candidate_id"] for row in legacy_rows}
    legacy_sequences = {row["sequence_sha256"] for row in legacy_rows}
    require(not (legacy_ids & {row["candidate_id"] for row in canonical_rows}), "cross_source_candidate_overlap")
    require(not (legacy_sequences & {row["sequence_sha256"] for row in canonical_rows}), "cross_source_sequence_overlap")
    raw_union = legacy_rows + canonical_rows
    gate_count(len(raw_union), expected_raw_union, "raw_union")
    kept, quarantined, graph_audit = joint_cdr3_quarantine(raw_union)
    kept.sort(key=lambda row: row["candidate_id"])
    train_count = sum(row["_assigned_split"] == "train" for row in kept)
    dev_count = len(kept) - train_count
    gate_count(train_count, expected_train, "train_rows")
    gate_count(dev_count, expected_development, "development_rows")
    gate_count(len(kept), expected_final, "final_rows")
    gate_count(len(quarantined), expected_new_quarantine, "new_quarantine")

    frozen_parents = set(canonical_audit["parent_sets"]["frozen_test"])
    require(
        stable_set_hash(frozen_parents) == legacy_manifest["frozen_test_parent_set_sha256"],
        "legacy_canonical_frozen_parent_hash_mismatch",
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent))
    try:
        teacher = temp_dir / "primary_D1_canonical10644_teacher.tsv"
        quarantine = temp_dir / "joint_cdr3_quarantine.tsv"
        manifest_path = temp_dir / "primary_D1_canonical10644_split_manifest.json"
        write_tsv(teacher, kept, OUTPUT_COLUMNS)
        write_tsv(quarantine, quarantined, QUARANTINE_COLUMNS)
        manifest = create_manifest(teacher, kept, frozen_parents, split_id)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        core_hashes = {
            teacher.name: sha256_file(teacher),
            manifest_path.name: sha256_file(manifest_path),
            quarantine.name: sha256_file(quarantine),
        }
        receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA,
            "status": "PASS_V2_10_CANONICAL10644_MATERIALIZED",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "claim_boundary": CLAIM,
            "inputs": {
                "legacy_d0_tsv": str(legacy_d0_tsv),
                "legacy_d0_sha256": legacy_d0_sha256,
                "legacy_d0_manifest": str(legacy_d0_manifest),
                "legacy_d0_manifest_sha256": legacy_d0_manifest_sha256,
                "canonical_tsv": str(canonical_tsv),
                "canonical_tsv_sha256": canonical_tsv_sha256,
                "canonical_release_receipt": str(canonical_release_receipt),
                "canonical_release_receipt_sha256": canonical_release_receipt_sha256,
                "canonical_protocol_core_sha256": release_receipt["protocol_core_sha256"],
            },
            "counts": {
                "legacy_D0_rows": len(legacy_rows),
                "canonical_open_rows": len(canonical_rows),
                "pre_joint_graph_union_rows": len(raw_union),
                "new_joint_cdr3_quarantine_rows": len(quarantined),
                "final_open_rows": len(kept),
                "final_train_rows": train_count,
                "final_development_rows": dev_count,
            },
            "canonical_access_audit": canonical_audit,
            "joint_cdr3_graph_audit": graph_audit,
            "new_quarantine_candidates": [
                {
                    "candidate_id": row["candidate_id"],
                    "sequence_sha256": row["sequence_sha256"],
                    "quarantine_reason": row["quarantine_reason"],
                }
                for row in quarantined
            ],
            "invariants": {
                "split_and_status_checked_before_numeric_parse": True,
                "frozen_numeric_parse_count": 0,
                "preexisting_quarantine_numeric_parse_count": 0,
                "technical_na_numeric_parse_count": 0,
                "cross_source_candidate_overlap": 0,
                "cross_source_sequence_overlap": 0,
                "R_dual_exact_min": True,
                "joint_CDR3_hamming80_cross_split_edges_after_quarantine": 0,
            },
            "output_sha256": core_hashes,
        }
        receipt_path = temp_dir / "MATERIALIZATION_RECEIPT.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        all_hashes = {**core_hashes, receipt_path.name: sha256_file(receipt_path)}
        (temp_dir / "SHA256SUMS").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in all_hashes.items())
        )
        os.replace(temp_dir, output_dir)
        return receipt
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-d0-tsv", type=Path, required=True)
    parser.add_argument("--legacy-d0-sha256", required=True)
    parser.add_argument("--legacy-d0-manifest", type=Path, required=True)
    parser.add_argument("--legacy-d0-manifest-sha256", required=True)
    parser.add_argument("--canonical-tsv", type=Path, required=True)
    parser.add_argument("--canonical-tsv-sha256", required=True)
    parser.add_argument("--canonical-release-receipt", type=Path, required=True)
    parser.add_argument("--canonical-release-receipt-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--split-id", required=True)
    parser.add_argument("--expected-raw-union", type=int, default=10645)
    parser.add_argument("--expected-train", type=int, default=9849)
    parser.add_argument("--expected-development", type=int, default=795)
    parser.add_argument("--expected-final", type=int, default=10644)
    parser.add_argument("--expected-new-quarantine", type=int, default=1)
    args = parser.parse_args()
    receipt = materialize(
        legacy_d0_tsv=args.legacy_d0_tsv,
        legacy_d0_sha256=args.legacy_d0_sha256,
        legacy_d0_manifest=args.legacy_d0_manifest,
        legacy_d0_manifest_sha256=args.legacy_d0_manifest_sha256,
        canonical_tsv=args.canonical_tsv,
        canonical_tsv_sha256=args.canonical_tsv_sha256,
        canonical_release_receipt=args.canonical_release_receipt,
        canonical_release_receipt_sha256=args.canonical_release_receipt_sha256,
        output_dir=args.output_dir,
        split_id=args.split_id,
        expected_raw_union=args.expected_raw_union,
        expected_train=args.expected_train,
        expected_development=args.expected_development,
        expected_final=args.expected_final,
        expected_new_quarantine=args.expected_new_quarantine,
    )
    print(json.dumps({
        "status": receipt["status"],
        "counts": receipt["counts"],
        "output_dir": str(args.output_dir),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
