#!/usr/bin/env python3
"""Validate the frozen 150K panel and emit label-free Stage-0 prior ranks."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable


SCHEMA = "pvrig_v2_19_top150k_stage0_priors_v1"
CLAIM = (
    "Label-free generic binding, naturalness and developability priors only; "
    "not Docking geometry truth, binding probability, Kd or experimental blocking."
)
AA = set("ACDEFGHIKLMNPQRSTVWY")
EXPECTED_ROWS = 150000


class Stage0Error(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise Stage0Error(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def percentile_ranks(values: list[float]) -> list[float]:
    """Tie-aware [0,1] percentile ranks with larger values better."""
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    result = [0.0] * len(values)
    pos = 0
    denominator = max(1, len(values) - 1)
    while pos < len(order):
        end = pos + 1
        while end < len(order) and values[order[end]] == values[order[pos]]:
            end += 1
        average_position = (pos + end - 1) / 2.0
        rank = average_position / denominator
        for j in range(pos, end):
            result[order[j]] = rank
        pos = end
    return result


def finite(row: dict[str, str], key: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, ValueError) as exc:
        raise Stage0Error(f"invalid_numeric:{row.get('candidate_id','')}:{key}") from exc
    require(math.isfinite(value), f"nonfinite:{row.get('candidate_id','')}:{key}")
    return value


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"input_not_regular:{path}")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return fields, rows


def write_tsv(rows: Iterable[dict[str, object]], fields: list[str]) -> str:
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def run(args: argparse.Namespace) -> dict[str, object]:
    require(not args.output_dir.exists(), f"output_dir_exists:{args.output_dir}")
    observed_sha = sha256_file(args.input)
    require(observed_sha == args.expected_sha256, "input_sha256_mismatch")
    fields, rows = read_rows(args.input)
    required = {
        "candidate_id", "sequence", "sequence_sha256", "parent_id", "parent_cluster",
        "cdr1_after", "cdr2_after", "cdr3_after", "generator", "design_mode",
        "target_patch_assignment", "deepnano_binding_prior", "nanobind_binding_prior",
        "mean_self_probability", "AbNatiV VHH Score", "production_proxy_score",
        "binding_consensus_weak_prior", "prestructure_multimetric_score",
        "nbb2_status", "tnp_status", "tnp_review_tier", "tnp_red_flag_count",
        "tnp_amber_flag_count", "multimetric_hard_gate", "nbb2_pdb_sha256",
        "nbb2_nbb2_archive_path", "nbb2_nbb2_archive_member"
    }
    require(required <= set(fields), f"missing_columns:{sorted(required-set(fields))}")
    require(len(rows) == args.expected_rows, f"row_count:{len(rows)}")
    require(len({row["candidate_id"] for row in rows}) == len(rows), "duplicate_candidate_id")
    require(len({row["sequence_sha256"] for row in rows}) == len(rows), "duplicate_sequence_sha256")
    for row in rows:
        candidate = row["candidate_id"]
        sequence = row["sequence"].strip().upper()
        require(sequence and set(sequence) <= AA, f"invalid_sequence:{candidate}")
        require(hashlib.sha256(sequence.encode()).hexdigest() == row["sequence_sha256"],
                f"sequence_sha256_mismatch:{candidate}")
        require(row["nbb2_status"] == "SUCCESS", f"nbb2_not_success:{candidate}")
        require(row["tnp_status"] == "PASS", f"tnp_not_pass:{candidate}")
        require(row["multimetric_hard_gate"].lower() == "true", f"hard_gate_fail:{candidate}")

    channels: dict[str, list[float]] = {
        "deepnano": [finite(row, "deepnano_binding_prior") for row in rows],
        "nanobind": [finite(row, "nanobind_binding_prior") for row in rows],
        "sapiens": [finite(row, "mean_self_probability") for row in rows],
        "abnativ": [finite(row, "AbNatiV VHH Score") for row in rows],
        "production": [finite(row, "production_proxy_score") for row in rows],
        "binding_consensus": [finite(row, "binding_consensus_weak_prior") for row in rows],
        "prestructure": [finite(row, "prestructure_multimetric_score") for row in rows],
    }
    ranks = {name: percentile_ranks(values) for name, values in channels.items()}
    weights = {
        "deepnano": 0.10, "nanobind": 0.10, "sapiens": 0.10, "abnativ": 0.10,
        "production": 0.20, "binding_consensus": 0.15, "prestructure": 0.25,
    }
    out: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        red = int(row["tnp_red_flag_count"])
        amber = int(row["tnp_amber_flag_count"])
        penalty = 0.08 * red + 0.015 * amber
        score = sum(weights[name] * ranks[name][index] for name in weights) - penalty
        item: dict[str, object] = {
            "candidate_id": row["candidate_id"],
            "sequence": row["sequence"],
            "sequence_sha256": row["sequence_sha256"],
            "parent_id": row["parent_id"],
            "parent_framework_cluster": row["parent_cluster"],
            "cdr1": row["cdr1_after"], "cdr2": row["cdr2_after"], "cdr3": row["cdr3_after"],
            "target_patch_id": row["target_patch_assignment"],
            "design_method": row["generator"], "design_mode": row["design_mode"],
            "nbb2_pdb_sha256": row["nbb2_pdb_sha256"],
            "nbb2_archive_path": row["nbb2_nbb2_archive_path"],
            "nbb2_archive_member": row["nbb2_nbb2_archive_member"],
            "tnp_review_tier": row["tnp_review_tier"],
            "tnp_red_flag_count": red, "tnp_amber_flag_count": amber,
            "stage0_prior_score": f"{score:.12g}",
        }
        for name in weights:
            item[f"{name}_rank"] = f"{ranks[name][index]:.12g}"
        out.append(item)
    out.sort(key=lambda row: (-float(row["stage0_prior_score"]), str(row["candidate_id"])))
    for rank, row in enumerate(out, start=1):
        row["stage0_prior_rank"] = rank
        row["stage0_broad_pool"] = "true" if rank <= args.broad_pool_rows else "false"

    output_fields = list(out[0])
    table_path = args.output_dir / "STAGE0_LABEL_FREE_PRIORS.tsv"
    receipt_path = args.output_dir / "RUN_RECEIPT.json"
    atomic_text(table_path, write_tsv(out, output_fields))
    receipt = {
        "schema_version": SCHEMA,
        "status": "PASS_TOP150K_STAGE0_LABEL_FREE_PRIORS",
        "claim_boundary": CLAIM,
        "input": str(args.input), "input_sha256": observed_sha,
        "rows": len(rows), "parents": len({row["parent_cluster"] for row in rows}),
        "broad_pool_rows": args.broad_pool_rows,
        "weights": weights,
        "output": str(table_path), "output_sha256": sha256_file(table_path),
        "docking_truth_access_count": 0,
        "experimental_label_access_count": 0,
    }
    atomic_text(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    atomic_text(args.output_dir / "SHA256SUMS", "".join(
        f"{sha256_file(path)}  {path.name}\n" for path in (receipt_path, table_path)
    ))
    return receipt


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--expected-sha256", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--expected-rows", type=int, default=EXPECTED_ROWS)
    p.add_argument("--broad-pool-rows", type=int, default=45000)
    return p


def main() -> int:
    print(json.dumps(run(parser().parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
