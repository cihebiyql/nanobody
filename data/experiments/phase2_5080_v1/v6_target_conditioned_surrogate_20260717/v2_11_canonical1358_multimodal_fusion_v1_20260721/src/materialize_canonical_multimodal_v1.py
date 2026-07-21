#!/usr/bin/env python3
"""Materialize the open-only canonical sequence/structure/coarse-pose intersection."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import torch

SCHEMA = "pvrig_v2_11_canonical_multimodal_materialization_v1"
CLAIM = (
    "Open-development approximation of independent 8X6B/9E6Y computational "
    "Docking geometry only; not binding, affinity, experimental blocking, "
    "Docking Gold, frozen-test, sealed truth, or submission evidence."
)
FORBIDDEN_PATH_TOKENS = ("test32", "sealed_truth", "frozen_test", "frozen-test", "v4_f")
TEACHER_FIELDS = (
    "candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster",
    "cdr1", "cdr2", "cdr3", "sample_weight", "R_8X6B", "R_9E6Y",
    "R_dual_min", "teacher_source", "teacher_reliability",
)
STRUCTURE_METADATA = {
    "schema_version", "candidate_id", "sequence_sha256", "model_split",
    "parent_framework_cluster", "target_patch_id", "design_mode", "monomer_sha256",
    "claim_boundary",
}
C2_EXCLUSIONS = {
    "8x6b__pose_count", "9e6y__pose_count",
    "8x6b__top20_score_entropy", "9e6y__top20_score_entropy",
}

class MaterializationError(RuntimeError):
    pass

def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)

def reject_path(path: Path, role: str) -> None:
    normalized = str(path.resolve()).lower().replace("-", "_")
    for token in FORBIDDEN_PATH_TOKENS:
        require(token.replace("-", "_") not in normalized, f"forbidden_{role}_path:{token}")

def require_regular(path: Path, role: str) -> None:
    reject_path(path, role)
    require(path.is_file() and not path.is_symlink(), f"{role}_not_regular:{path}")

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()

def stable_parent_hash(parents: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(set(parents))) + "\n").encode()).hexdigest()

def load_tsv(path: Path, role: str) -> tuple[list[str], list[dict[str, str]]]:
    require_regular(path, role)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(fields and rows, f"{role}_empty")
    return fields, rows

def unique_by(rows: list[dict[str, str]], key: str, role: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "").strip()
        require(value and value not in result, f"{role}_duplicate_or_blank:{value}")
        result[value] = row
    return result

def finite(raw: str, label: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise MaterializationError(f"invalid_numeric:{label}:{raw!r}") from exc
    require(math.isfinite(value), f"nonfinite:{label}")
    return value

def validate_hash(path: Path, expected: str | None, role: str) -> str:
    observed = sha256_file(path)
    if expected:
        require(observed == expected, f"{role}_sha256_mismatch:{observed}")
    return observed

def validate_cache(cache_dir: Path, expected_sha_by_id: dict[str, str]) -> dict[str, Any]:
    reject_path(cache_dir, "embedding_cache")
    receipt_path = cache_dir / "embedding_cache_receipt.json"
    require_regular(receipt_path, "embedding_cache_receipt")
    receipt = json.loads(receipt_path.read_text())
    require(receipt.get("schema_version") == "pvrig_v6_esm_embedding_cache_v1", "embedding_schema")
    seen: dict[str, str] = {}
    width: int | None = None
    for item in receipt.get("shards", []):
        shard = Path(item["path"])
        require(shard.parent.resolve() == (cache_dir / "shards").resolve(), "embedding_shard_outside_cache")
        require_regular(shard, "embedding_shard")
        require(sha256_file(shard) == item["sha256"], f"embedding_shard_hash:{shard.name}")
        payload = torch.load(shard, map_location="cpu", weights_only=False)
        ids = payload["metadata"]["candidate_ids"]
        hashes = payload["metadata"]["sequence_sha256"]
        values = payload["embeddings"].float().numpy()
        require(values.ndim == 2 and values.shape[0] == len(ids) == len(hashes), "embedding_shard_shape")
        width = values.shape[1] if width is None else width
        require(values.shape[1] == width and np.isfinite(values).all(), "embedding_width_or_finite")
        for candidate, sequence_sha in zip(ids, hashes):
            require(candidate not in seen, f"duplicate_embedding:{candidate}")
            seen[str(candidate)] = str(sequence_sha)
    require(int(receipt.get("rows", -1)) == len(seen), "embedding_receipt_rows")
    require(set(expected_sha_by_id) <= set(seen), "embedding_candidate_missing")
    for candidate, sequence_sha in expected_sha_by_id.items():
        require(seen[candidate] == sequence_sha, f"embedding_sequence_mismatch:{candidate}")
    return {
        "receipt_sha256": sha256_file(receipt_path),
        "cache_rows": len(seen),
        "embedding_width": width,
        "matched_rows": len(expected_sha_by_id),
    }

def atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text)
    os.replace(temporary, path)

def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    os.replace(temporary, path)

def materialize(args: argparse.Namespace) -> dict[str, Any]:
    output_dir: Path = args.output_dir
    reject_path(output_dir, "output")
    require(not output_dir.exists() and not output_dir.is_symlink(), "output_exists")
    paths = {
        "teacher": args.teacher,
        "split_manifest": args.split_manifest,
        "structure_v4d": args.structure_v4d,
        "structure_v4h": args.structure_v4h,
        "coarse_pose": args.coarse_pose,
    }
    expected = {
        "teacher": args.expected_teacher_sha256,
        "split_manifest": args.expected_split_sha256,
        "structure_v4d": args.expected_structure_v4d_sha256,
        "structure_v4h": args.expected_structure_v4h_sha256,
        "coarse_pose": args.expected_coarse_pose_sha256,
    }
    hashes = {}
    for role, path in paths.items():
        require_regular(path, role)
        hashes[role] = validate_hash(path, expected[role], role)

    teacher_fields, teacher_rows = load_tsv(args.teacher, "teacher")
    require(set(TEACHER_FIELDS) <= set(teacher_fields), "teacher_fields_missing")
    teacher = unique_by(teacher_rows, "candidate_id", "teacher")
    split = json.loads(args.split_manifest.read_text())
    require(split.get("open_only") is True, "split_not_open_only")
    require(split.get("training_tsv_sha256") == hashes["teacher"], "split_teacher_hash")
    require(int(split.get("frozen_test_access_count", -1)) == 0, "frozen_access_nonzero")
    require(int(split.get("sealed_truth_access_count", -1)) == 0, "sealed_access_nonzero")
    train_parents = set(split.get("train_parents", [])); dev_parents = set(split.get("score_parents", []))
    frozen_parents = set(split.get("frozen_test_parents", []))
    require(train_parents and dev_parents and train_parents.isdisjoint(dev_parents), "split_parent_invalid")
    require((train_parents | dev_parents).isdisjoint(frozen_parents), "open_frozen_parent_overlap")
    require(stable_parent_hash(train_parents) == split.get("train_parent_set_sha256"), "train_parent_hash")
    require(stable_parent_hash(dev_parents) == split.get("score_parent_set_sha256"), "dev_parent_hash")
    require(set(row["parent_framework_cluster"] for row in teacher_rows) <= train_parents | dev_parents, "teacher_parent_outside_open")

    s4_fields, s4_rows = load_tsv(args.structure_v4d, "structure_v4d")
    sh_fields, sh_rows = load_tsv(args.structure_v4h, "structure_v4h")
    structure_features4 = sorted(name for name in s4_fields if name not in STRUCTURE_METADATA)
    structure_featuresh = sorted(name for name in sh_fields if name not in STRUCTURE_METADATA)
    require(structure_features4 == structure_featuresh, "structure_feature_schema_mismatch")
    require(len(structure_features4) == args.expected_structure_features, "structure_feature_count")
    structure = unique_by(s4_rows + sh_rows, "candidate_id", "structure")

    c2_fields, c2_rows = load_tsv(args.coarse_pose, "coarse_pose")
    c2_metadata = {"candidate_id", "monomer_sha256", "feature_schema"}
    c2_features = [name for name in c2_fields if name not in c2_metadata]
    require(len(c2_features) == args.expected_coarse_features, "coarse_feature_count")
    c2_model_features = [name for name in c2_features if name not in C2_EXCLUSIONS]
    require(len(c2_model_features) == args.expected_coarse_model_features, "coarse_model_feature_count")
    coarse = unique_by(c2_rows, "candidate_id", "coarse_pose")

    candidates = sorted(set(teacher) & set(structure) & set(coarse))
    require(len(candidates) == args.expected_rows, f"intersection_rows:{len(candidates)}")
    output_rows = []
    split_counts = Counter(); source_counts = Counter(); reliability_counts = Counter()
    for candidate in candidates:
        t, s, c = teacher[candidate], structure[candidate], coarse[candidate]
        require(t["sequence_sha256"] == s["sequence_sha256"], f"teacher_structure_sequence:{candidate}")
        require(s["monomer_sha256"] == c["monomer_sha256"], f"structure_c2_monomer:{candidate}")
        r8 = finite(t["R_8X6B"], f"R8:{candidate}"); r9 = finite(t["R_9E6Y"], f"R9:{candidate}")
        dual = finite(t["R_dual_min"], f"Rdual:{candidate}")
        require(abs(dual - min(r8, r9)) < 2e-8, f"exact_min:{candidate}")
        parent = t["parent_framework_cluster"]
        model_split = "train" if parent in train_parents else "development"
        out: dict[str, Any] = {name: t[name] for name in TEACHER_FIELDS}
        out["model_split"] = model_split
        out["monomer_sha256"] = s["monomer_sha256"]
        for name in structure_features4:
            out[name] = f"{finite(s[name], f'structure:{candidate}:{name}'):.17g}"
        for name in c2_features:
            out[f"C2__{name}"] = f"{finite(c[name], f'c2:{candidate}:{name}'):.17g}"
        output_rows.append(out)
        split_counts[model_split] += 1; source_counts[t["teacher_source"]] += 1
        reliability_counts[t["teacher_reliability"]] += 1
    require(split_counts == Counter({"train": args.expected_train_rows, "development": args.expected_development_rows}), f"split_counts:{dict(split_counts)}")
    train_observed = {row["parent_framework_cluster"] for row in output_rows if row["model_split"] == "train"}
    dev_observed = {row["parent_framework_cluster"] for row in output_rows if row["model_split"] == "development"}
    require(train_observed.isdisjoint(dev_observed), "materialized_parent_overlap")

    cache_audit = validate_cache(args.esm2_650m_cache, {c: teacher[c]["sequence_sha256"] for c in candidates})
    output_dir.mkdir(parents=True)
    table = output_dir / "canonical_multimodal_open.tsv"
    fields = [*TEACHER_FIELDS, "model_split", "monomer_sha256", *structure_features4, *[f"C2__{n}" for n in c2_features]]
    write_tsv(table, output_rows, fields)
    manifest = {
        "schema_version": SCHEMA,
        "status": "PASS_OPEN_MULTIMODAL_INTERSECTION_MATERIALIZED",
        "claim_boundary": CLAIM,
        "rows": len(output_rows),
        "train_rows": split_counts["train"],
        "development_rows": split_counts["development"],
        "train_parents": sorted(train_observed),
        "development_parents": sorted(dev_observed),
        "train_parent_count": len(train_observed),
        "development_parent_count": len(dev_observed),
        "source_counts": dict(sorted(source_counts.items())),
        "reliability_counts": dict(sorted(reliability_counts.items())),
        "structure_feature_names": structure_features4,
        "structure_feature_count": len(structure_features4),
        "coarse_feature_names": c2_features,
        "coarse_model_feature_names": c2_model_features,
        "coarse_feature_count": len(c2_features),
        "coarse_model_feature_count": len(c2_model_features),
        "output_table_sha256": sha256_file(table),
        "input_sha256": hashes,
        "embedding_cache": cache_audit,
        "frozen_test_access_count": 0,
        "sealed_truth_access_count": 0,
    }
    manifest_path = output_dir / "MATERIALIZATION_RECEIPT.json"
    atomic_write(manifest_path, json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    sums = {table.name: sha256_file(table), manifest_path.name: sha256_file(manifest_path)}
    atomic_write(output_dir / "SHA256SUMS", "".join(f"{d}  {n}\n" for n, d in sorted(sums.items())))
    return {"status": manifest["status"], "rows": len(output_rows), "train_rows": split_counts["train"], "development_rows": split_counts["development"], "output_dir": str(output_dir)}

def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--teacher", type=Path, required=True)
    value.add_argument("--split-manifest", type=Path, required=True)
    value.add_argument("--structure-v4d", type=Path, required=True)
    value.add_argument("--structure-v4h", type=Path, required=True)
    value.add_argument("--coarse-pose", type=Path, required=True)
    value.add_argument("--esm2-650m-cache", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    for name in ("teacher", "split", "structure-v4d", "structure-v4h", "coarse-pose"):
        value.add_argument(f"--expected-{name}-sha256")
    value.add_argument("--expected-rows", type=int, default=1358)
    value.add_argument("--expected-train-rows", type=int, default=1282)
    value.add_argument("--expected-development-rows", type=int, default=76)
    value.add_argument("--expected-structure-features", type=int, default=126)
    value.add_argument("--expected-coarse-features", type=int, default=36)
    value.add_argument("--expected-coarse-model-features", type=int, default=32)
    return value

def main() -> int:
    result = materialize(parser().parse_args())
    print(json.dumps(result, sort_keys=True)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
