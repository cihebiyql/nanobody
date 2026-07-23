#!/usr/bin/env python3
"""Verify and merge frozen coarse-pose shards into the V2.11 32D C2 contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


PLAN_SCHEMA = "pvrig_v2_19_top30k_c2_shard_plan_v1"
PLAN_STATUS = "PASS_TOP30K_LABEL_FREE_C2_SHARD_PLAN"
RAW_SCHEMA = "pvrig_v2_5_label_free_coarse_pose_36d_v1"
RAW_RECEIPT_SCHEMA = "pvrig_v2_5_label_free_coarse_pose_pilot_v1"
RAW_RECEIPT_STATUS = "PASS_LABEL_FREE_COARSE_POSE_FEATURES"
SCHEMA = "pvrig_v2_19_top30k_c2_32d_closure_v1"
STATUS = "PASS_TOP30K_LABEL_FREE_C2_32D_CLOSURE"
CLAIM = "Frozen V2.5 monomer/fixed-target coarse-pose C2 features only; no candidate Docking pose, teacher, binding, or experimental truth."
EXCLUSIONS = {
    "8x6b__pose_count", "9e6y__pose_count",
    "8x6b__top20_score_entropy", "9e6y__top20_score_entropy",
}
ID_FIELDS = ("candidate_id", "monomer_sha256", "feature_schema")


class MergeError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise MergeError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ordered_id_sha256(ids: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest()


def read_tsv(path: Path, role: str) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"{role}_not_regular:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        require(fields and len(fields) == len(set(fields)), f"{role}_header")
        rows = list(reader)
    require(rows, f"{role}_empty")
    return fields, rows


def same_path(left: str, right: Path) -> bool:
    return Path(left).resolve() == right.resolve()


def atomic_write(path: Path, payload: bytes) -> None:
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def merge(args: argparse.Namespace) -> dict[str, Any]:
    require(not args.output_dir.exists() and not args.output_dir.is_symlink(), "output_dir_exists")
    require(args.plan.is_file() and not args.plan.is_symlink(), "plan_not_regular")
    require(sha256_file(args.plan) == args.expected_plan_sha256, "plan_hash")
    plan = json.loads(args.plan.read_text())
    require(plan.get("schema_version") == PLAN_SCHEMA and plan.get("status") == PLAN_STATUS, "plan_contract")
    require(plan.get("counts", {}).get("rows") == args.expected_rows, "plan_rows")
    targets = {
        "target_npz": (args.target_npz, args.target_npz_sha256),
        "target_pdb8": (args.target_pdb8, args.target_pdb8_sha256),
        "target_pdb9": (args.target_pdb9, args.target_pdb9_sha256),
    }
    for role, (path, expected) in targets.items():
        require(path.is_file() and not path.is_symlink(), f"{role}_not_regular")
        require(sha256_file(path) == expected, f"{role}_hash")

    merged: list[dict[str, str]] = []
    feature_names: list[str] | None = None
    shard_audit = []
    seen: set[str] = set()
    for shard in plan["shards"]:
        shard_id = shard["shard_id"]
        manifest = args.plan.parent / shard["relative_path"]
        require(sha256_file(manifest) == shard["sha256"], f"manifest_hash:{shard_id}")
        m_fields, m_rows = read_tsv(manifest, f"manifest:{shard_id}")
        require([r["candidate_id"] for r in m_rows] and
                ordered_id_sha256([r["candidate_id"] for r in m_rows]) == shard["ordered_candidate_id_sha256"],
                f"manifest_order:{shard_id}")
        output = args.shard_output_root / shard_id / "coarse_pose_features_36d.tsv"
        receipt_path = args.shard_output_root / shard_id / "FEATURE_RECEIPT.json"
        fields, rows = read_tsv(output, f"features:{shard_id}")
        require(len(rows) == len(m_rows) == shard["rows"], f"shard_rows:{shard_id}")
        require([r["candidate_id"] for r in rows] == [r["candidate_id"] for r in m_rows], f"shard_order:{shard_id}")
        numeric = [field for field in fields if field not in ID_FIELDS]
        require(len(numeric) == 36 and EXCLUSIONS <= set(numeric), f"raw_feature_contract:{shard_id}")
        selected = [field for field in numeric if field not in EXCLUSIONS]
        require(len(selected) == 32, f"selected_feature_count:{shard_id}")
        if feature_names is None:
            feature_names = selected
        require(selected == feature_names, f"feature_order:{shard_id}")
        require(receipt_path.is_file() and not receipt_path.is_symlink(), f"receipt:{shard_id}")
        receipt = json.loads(receipt_path.read_text())
        require(receipt.get("schema_version") == RAW_RECEIPT_SCHEMA and
                receipt.get("status") == RAW_RECEIPT_STATUS, f"receipt_contract:{shard_id}")
        require(receipt.get("candidate_count") == len(rows) and receipt.get("feature_count") == 36 and
                receipt.get("pose_count_per_receptor") == 300 and receipt.get("all_features_finite") is True,
                f"receipt_counts:{shard_id}")
        sealed = receipt.get("sealed_boundary", {})
        require(all(sealed.get(key) == 0 for key in (
            "candidate_docking_pose_files_opened", "teacher_label_files_opened", "v4_f_files_opened"
        )), f"sealed_boundary:{shard_id}")
        require(receipt.get("inputs", {}).get("candidate_manifest", {}).get("sha256") == shard["sha256"],
                f"receipt_manifest_hash:{shard_id}")
        for role, (path, expected) in targets.items():
            record = receipt.get("inputs", {}).get(role, {})
            require(record.get("sha256") == expected and same_path(record.get("path", ""), path),
                    f"receipt_target:{shard_id}:{role}")
        output_record = receipt.get("outputs", {})
        require(len(output_record) == 1, f"receipt_output_count:{shard_id}")
        recorded_path, recorded_hash = next(iter(output_record.items()))
        require(same_path(recorded_path, output) and recorded_hash == sha256_file(output),
                f"receipt_output:{shard_id}")
        for source, feature in zip(m_rows, rows):
            candidate = source["candidate_id"]
            require(candidate not in seen, f"duplicate_candidate:{candidate}"); seen.add(candidate)
            require(feature["feature_schema"] == RAW_SCHEMA, f"feature_schema:{candidate}")
            require(feature["monomer_sha256"] == source["monomer_sha256"], f"monomer_hash:{candidate}")
            result = {
                "candidate_id": candidate,
                "sequence_sha256": source["sequence_sha256"],
                "parent_framework_cluster": source["parent_framework_cluster"],
            }
            for name in selected:
                try: value = float(feature[name])
                except ValueError as exc: raise MergeError(f"not_numeric:{candidate}:{name}") from exc
                require(math.isfinite(value), f"not_finite:{candidate}:{name}")
                result[f"C2__{name}"] = format(value, ".12g")
            merged.append(result)
        shard_audit.append({"shard_id": shard_id, "rows": len(rows),
                            "feature_sha256": sha256_file(output), "receipt_sha256": sha256_file(receipt_path)})
    require(len(merged) == args.expected_rows and len(seen) == args.expected_rows, "merged_rows")
    require(ordered_id_sha256([r["candidate_id"] for r in merged]) == plan["ordered_candidate_id_sha256"],
            "merged_order")
    require(feature_names is not None, "no_features")
    args.output_dir.mkdir(parents=True)
    table = args.output_dir / "TOP30000_C2_32D.tsv"
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(merged[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(merged)
    atomic_write(table, stream.getvalue().encode())
    receipt = {
        "schema_version": SCHEMA, "status": STATUS, "claim_boundary": CLAIM,
        "counts": {"rows": len(merged), "raw_features": 36, "model_features": 32, "shards": len(shard_audit)},
        "inputs": {"plan_sha256": args.expected_plan_sha256,
                   **{role + "_sha256": expected for role, (_path, expected) in targets.items()}},
        "predeclared_exclusions": sorted(EXCLUSIONS), "feature_names": [f"C2__{n}" for n in feature_names],
        "shards": shard_audit,
        "output": {"path": str(table.resolve()), "sha256": sha256_file(table)},
        "invariants": {"candidate_set_exact": True, "sequence_sha256_join_exact": True,
                       "parent_join_exact": True, "all_features_finite": True,
                       "candidate_docking_pose_files_opened": 0, "teacher_label_values_read": 0},
    }
    receipt_path = args.output_dir / "RUN_RECEIPT.json"
    atomic_write(receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
    atomic_write(args.output_dir / "SHA256SUMS",
                 f"{sha256_file(table)}  {table.name}\n{sha256_file(receipt_path)}  {receipt_path.name}\n".encode())
    return {"status": STATUS, "rows": len(merged), "output_sha256": sha256_file(table)}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", type=Path, required=True); p.add_argument("--expected-plan-sha256", required=True)
    p.add_argument("--shard-output-root", type=Path, required=True)
    for role in ("target-npz", "target-pdb8", "target-pdb9"):
        p.add_argument(f"--{role}", type=Path, required=True); p.add_argument(f"--{role}-sha256", required=True)
    p.add_argument("--output-dir", type=Path, required=True); p.add_argument("--expected-rows", type=int, default=30000)
    return p


if __name__ == "__main__":
    print(json.dumps(merge(parser().parse_args()), sort_keys=True))
