#!/usr/bin/env python3
"""Freeze a deterministic, leakage-safe generic-contact replay set for V3-P."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_SOURCE = EXP_DIR / "prepared/structure_contact_maps_v3_clustered.jsonl"
DEFAULT_CACHE_MANIFEST = EXP_DIR / "prepared/esm2_8m_v2_3_cache/manifest.csv"
DEFAULT_CDR_MASKS = EXP_DIR / "data_splits/vhh_cdr_type_masks_v2_3.csv"
DEFAULT_TEACHER500 = (
    EXP_DIR
    / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"
)
DEFAULT_OUTPUT = (
    EXP_DIR / "prepared/phase2_v3_p1_generic_replay/generic_replay_train256_v1.csv"
)
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p1_generic_replay_audit.json"

SCHEMA_VERSION = "phase2_v3_p1_generic_replay_v1"
SELECTION_SEED = "phase2-v3-p1-generic-replay-v1"
OUTPUT_FIELDS = (
    "sample_id",
    "vhh_sequence",
    "antigen_sequence",
    "contact_pairs_json",
    "vhh_paratope_mask",
    "antigen_epitope_mask",
)
LEAKAGE_KEYS = (
    "complex_id",
    "structure_group",
    "split_group_id",
    "vhh_cluster_id",
    "antigen_cluster_id",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.strip().upper().encode("utf-8")).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def stable_fallback(prefix: str, value: str) -> str:
    return f"{prefix}:sha256:{sequence_sha256(value)}"


def diversity_keys(row: dict[str, Any]) -> tuple[str, str, str, str]:
    structure = str(row.get("structure_group") or "").strip()
    if not structure:
        structure = str(row.get("pdb") or row.get("structure_member") or row["complex_id"]).strip()
        structure = f"structure:{structure}"
    antigen = str(row.get("antigen_cluster_id") or "").strip()
    if not antigen:
        antigen = stable_fallback("antigen", str(row["antigen_seq"]))
    vhh = str(row.get("vhh_cluster_id") or "").strip()
    if not vhh:
        vhh = stable_fallback("vhh", str(row["vhh_seq"]))
    split_group = str(row.get("split_group_id") or row["complex_id"]).strip()
    return structure, antigen, vhh, split_group


def normalize_pairs(row: dict[str, Any], vhh_length: int, antigen_length: int) -> list[list[int]]:
    raw = row.get("positive_pairs")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"Replay source row has no positive_pairs: {row.get('complex_id')}")
    pairs: set[tuple[int, int]] = set()
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"Invalid contact pair for {row.get('complex_id')}: {pair!r}")
        vhh_index, antigen_index = int(pair[0]), int(pair[1])
        if not 0 <= vhh_index < vhh_length or not 0 <= antigen_index < antigen_length:
            raise ValueError(f"Contact pair out of range for {row.get('complex_id')}: {pair!r}")
        pairs.add((vhh_index, antigen_index))
    return [[vhh_index, antigen_index] for vhh_index, antigen_index in sorted(pairs)]


def binary_mask(length: int, positive_indices: Iterable[int]) -> str:
    mask = ["0"] * length
    for index in positive_indices:
        mask[index] = "1"
    return "".join(mask)


def index_cache(rows: Sequence[dict[str, str]]) -> set[str]:
    hashes: set[str] = set()
    for row in rows:
        digest = str(row.get("sequence_sha256") or "").strip()
        if not digest or digest in hashes:
            raise ValueError(f"Cache manifest has missing or duplicate sequence_sha256: {digest!r}")
        hashes.add(digest)
    return hashes


def index_cdr_masks(rows: Sequence[dict[str, str]]) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        digest = str(row.get("sequence_hash") or "").strip()
        if not digest or digest in indexed:
            raise ValueError(f"CDR mask CSV has missing or duplicate sequence_hash: {digest!r}")
        try:
            mask = json.loads(row["cdr_mask_json"])
            expected_length = int(row["vhh_len"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid CDR mask row for {digest!r}") from exc
        if not isinstance(mask, list) or len(mask) != expected_length:
            raise ValueError(f"CDR mask length mismatch for {digest!r}")
        if row.get("vhh_seq") and sequence_sha256(row["vhh_seq"]) != digest:
            raise ValueError(f"CDR mask sequence hash mismatch for {digest!r}")
        indexed[digest] = row
    return indexed


def exact_row_signature(row: dict[str, Any]) -> str:
    payload = {
        "vhh_seq": str(row.get("vhh_seq") or "").strip().upper(),
        "antigen_seq": str(row.get("antigen_seq") or "").strip().upper(),
        "positive_pairs": row.get("positive_pairs"),
        "diversity_keys": diversity_keys(row),
        "split": str(row.get("split") or "").strip(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def eligible_train_rows(
    source_rows: Sequence[dict[str, Any]],
    cache_hashes: set[str],
    cdr_masks: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counters: Counter[str] = Counter(
        {
            "source_rows": 0,
            "source_train_rows": 0,
            "excluded_non_train": 0,
            "excluded_missing_cache": 0,
            "excluded_missing_cdr_mask": 0,
            "excluded_incomplete_cdr_mask": 0,
            "excluded_exact_duplicate": 0,
        }
    )
    by_sample: dict[str, dict[str, Any]] = {}
    signatures: dict[str, str] = {}
    for row in source_rows:
        counters["source_rows"] += 1
        if str(row.get("split") or "").strip() != "train":
            counters["excluded_non_train"] += 1
            continue
        counters["source_train_rows"] += 1
        sample_id = str(row.get("complex_id") or "").strip()
        vhh_sequence = str(row.get("vhh_seq") or "").strip().upper()
        antigen_sequence = str(row.get("antigen_seq") or "").strip().upper()
        if not sample_id or not vhh_sequence or not antigen_sequence:
            raise ValueError("Replay source row is missing complex_id, vhh_seq, or antigen_seq")
        vhh_hash = sequence_sha256(vhh_sequence)
        antigen_hash = sequence_sha256(antigen_sequence)
        if vhh_hash not in cache_hashes or antigen_hash not in cache_hashes:
            counters["excluded_missing_cache"] += 1
            continue
        mask_row = cdr_masks.get(vhh_hash)
        if mask_row is None:
            counters["excluded_missing_cdr_mask"] += 1
            continue
        mask = json.loads(mask_row["cdr_mask_json"])
        if mask_row.get("status") == "unresolved" or 3 not in mask:
            counters["excluded_incomplete_cdr_mask"] += 1
            continue
        normalized = {
            **row,
            "complex_id": sample_id,
            "vhh_seq": vhh_sequence,
            "antigen_seq": antigen_sequence,
        }
        signature = exact_row_signature(normalized)
        if sample_id in by_sample:
            if signatures[sample_id] != signature:
                raise ValueError(f"Conflicting duplicate replay sample_id: {sample_id}")
            counters["excluded_exact_duplicate"] += 1
            continue
        by_sample[sample_id] = normalized
        signatures[sample_id] = signature
    counters["eligible_unique_train_rows"] = len(by_sample)
    return list(by_sample.values()), dict(counters)


def select_diverse(rows: Sequence[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if len(rows) < count:
        raise ValueError(f"Could select only {len(rows)}/{count} cache-complete train replay rows")
    remaining = list(rows)
    selected: list[dict[str, Any]] = []
    seen_structure: set[str] = set()
    seen_antigen: set[str] = set()
    seen_vhh: set[str] = set()
    seen_split_group: set[str] = set()
    while len(selected) < count:
        def priority(row: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
            structure, antigen, vhh, split_group = diversity_keys(row)
            unseen = (
                structure not in seen_structure,
                antigen not in seen_antigen,
                vhh not in seen_vhh,
            )
            stable = hashlib.sha256(
                f"{SELECTION_SEED}\t{row['complex_id']}".encode("utf-8")
            ).hexdigest()
            return (
                -sum(unseen),
                -int(unseen[0]),
                -int(unseen[1]),
                -int(unseen[2]),
                -int(split_group not in seen_split_group),
                stable,
            )

        chosen = min(remaining, key=priority)
        remaining.remove(chosen)
        selected.append(chosen)
        structure, antigen, vhh, split_group = diversity_keys(chosen)
        seen_structure.add(structure)
        seen_antigen.add(antigen)
        seen_vhh.add(vhh)
        seen_split_group.add(split_group)
    return selected


def overlap_count(selected: Sequence[dict[str, Any]], holdout: Sequence[dict[str, Any]], key: str) -> int:
    selected_values = {str(row.get(key) or "").strip() for row in selected}
    holdout_values = {str(row.get(key) or "").strip() for row in holdout}
    selected_values.discard("")
    holdout_values.discard("")
    return len(selected_values & holdout_values)


def prepare(
    source_path: Path,
    cache_manifest_path: Path,
    cdr_masks_path: Path,
    teacher500_path: Path,
    output_path: Path,
    audit_path: Path,
    expected_rows: int = 256,
) -> dict[str, Any]:
    source_rows = read_jsonl(source_path)
    cache_hashes = index_cache(read_csv(cache_manifest_path))
    cdr_masks = index_cdr_masks(read_csv(cdr_masks_path))
    teacher_rows = read_csv(teacher500_path)
    eligible, eligibility_counts = eligible_train_rows(source_rows, cache_hashes, cdr_masks)
    selected = select_diverse(eligible, expected_rows)

    holdout = [row for row in source_rows if str(row.get("split") or "").strip() != "train"]
    holdout_overlap = {key: overlap_count(selected, holdout, key) for key in LEAKAGE_KEYS}
    selected_vhh_hashes = {sequence_sha256(str(row["vhh_seq"])) for row in selected}
    selected_antigen_hashes = {sequence_sha256(str(row["antigen_seq"])) for row in selected}
    holdout_vhh_hashes = {sequence_sha256(str(row["vhh_seq"])) for row in holdout}
    holdout_antigen_hashes = {sequence_sha256(str(row["antigen_seq"])) for row in holdout}
    holdout_overlap.update(
        {
            "vhh_sequence_sha256": len(selected_vhh_hashes & holdout_vhh_hashes),
            "antigen_sequence_sha256": len(selected_antigen_hashes & holdout_antigen_hashes),
        }
    )

    teacher_ids = {str(row.get("candidate_id") or "").strip() for row in teacher_rows}
    teacher_vhh_hashes = {
        str(row.get("sequence_sha256") or sequence_sha256(str(row.get("vhh_sequence") or ""))).strip()
        for row in teacher_rows
        if row.get("sequence_sha256") or row.get("vhh_sequence")
    }
    teacher_test_vhh_hashes = {
        str(row.get("sequence_sha256") or sequence_sha256(str(row.get("vhh_sequence") or ""))).strip()
        for row in teacher_rows
        if str(row.get("formal_split") or "").strip() == "test"
        and (row.get("sequence_sha256") or row.get("vhh_sequence"))
    }
    teacher_target_hashes = {
        str(row.get("target_sequence_sha256") or "").strip()
        for row in teacher_rows
        if row.get("target_sequence_sha256")
    }
    teacher_overlap = {
        "sample_id_vs_candidate_id": len({str(row["complex_id"]) for row in selected} & teacher_ids),
        "vhh_sequence_sha256_all": len(selected_vhh_hashes & teacher_vhh_hashes),
        "vhh_sequence_sha256_formal_test": len(selected_vhh_hashes & teacher_test_vhh_hashes),
        "antigen_sequence_sha256_vs_teacher_target": len(selected_antigen_hashes & teacher_target_hashes),
    }
    if any(holdout_overlap.values()):
        raise ValueError(f"Generic replay overlaps source holdout splits: {holdout_overlap}")
    if any(teacher_overlap.values()):
        raise ValueError(f"Generic replay overlaps Teacher500: {teacher_overlap}")

    output_rows: list[dict[str, str]] = []
    positive_pair_counts: list[int] = []
    for source in selected:
        vhh_sequence = str(source["vhh_seq"])
        antigen_sequence = str(source["antigen_seq"])
        pairs = normalize_pairs(source, len(vhh_sequence), len(antigen_sequence))
        positive_pair_counts.append(len(pairs))
        output_rows.append(
            {
                "sample_id": str(source["complex_id"]),
                "vhh_sequence": vhh_sequence,
                "antigen_sequence": antigen_sequence,
                "contact_pairs_json": json.dumps(pairs, separators=(",", ":")),
                "vhh_paratope_mask": binary_mask(len(vhh_sequence), (pair[0] for pair in pairs)),
                "antigen_epitope_mask": binary_mask(len(antigen_sequence), (pair[1] for pair in pairs)),
            }
        )
    write_csv(output_path, output_rows)

    structures = {diversity_keys(row)[0] for row in selected}
    antigens = {diversity_keys(row)[1] for row in selected}
    vhhs = {diversity_keys(row)[2] for row in selected}
    split_groups = {diversity_keys(row)[3] for row in selected}
    audit: dict[str, Any] = {
        "status": "PASS_PHASE2_V3_P1_GENERIC_REPLAY_FROZEN",
        "schema_version": SCHEMA_VERSION,
        "selection_seed": SELECTION_SEED,
        "expected_rows": expected_rows,
        "selected_rows": len(output_rows),
        "output_columns": list(OUTPUT_FIELDS),
        "eligibility_counts": eligibility_counts,
        "input_row_counts": {
            "source": len(source_rows),
            "cache_manifest": len(cache_hashes),
            "cdr_masks": len(cdr_masks),
            "teacher500": len(teacher_rows),
        },
        "source_split_counts": dict(
            sorted(Counter(str(row.get("split") or "").strip() for row in source_rows).items())
        ),
        "selected_diversity": {
            "unique_structure_groups": len(structures),
            "unique_antigen_clusters": len(antigens),
            "unique_vhh_clusters": len(vhhs),
            "unique_split_groups": len(split_groups),
        },
        "positive_pair_counts": {
            "minimum": min(positive_pair_counts),
            "maximum": max(positive_pair_counts),
            "total": sum(positive_pair_counts),
        },
        "model_input_closure": {
            "all_vhh_sequences_in_cache": True,
            "all_antigen_sequences_in_cache": True,
            "all_vhh_sequences_have_resolved_cdr3_mask": True,
        },
        "source_holdout_overlap": holdout_overlap,
        "teacher500_overlap": teacher_overlap,
        "selected_source_split_counts": {"train": len(output_rows)},
        "input_sha256": {
            "source": sha256_file(source_path),
            "cache_manifest": sha256_file(cache_manifest_path),
            "cdr_masks": sha256_file(cdr_masks_path),
            "teacher500": sha256_file(teacher500_path),
        },
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "claim_boundary": "generic_contact_replay_not_pvrig_binding_or_blocking_truth",
    }
    atomic_text(audit_path, json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--cache-manifest", type=Path, default=DEFAULT_CACHE_MANIFEST)
    parser.add_argument("--cdr-masks", type=Path, default=DEFAULT_CDR_MASKS)
    parser.add_argument("--teacher500", type=Path, default=DEFAULT_TEACHER500)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--expected-rows", type=int, default=256)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    audit = prepare(
        args.source,
        args.cache_manifest,
        args.cdr_masks,
        args.teacher500,
        args.output,
        args.audit,
        args.expected_rows,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
