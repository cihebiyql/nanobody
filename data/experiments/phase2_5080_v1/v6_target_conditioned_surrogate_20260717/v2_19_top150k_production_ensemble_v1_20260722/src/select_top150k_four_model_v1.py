#!/usr/bin/env python3
"""Fuse frozen L1/B/S0/M2 predictions and select an auditable Top 5%."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from io import StringIO
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "pvrig_v2_19_top150k_four_model_selection_v1"
CLAIM = (
    "Consensus ranking of label-free computational Docking-geometry surrogates; "
    "not calibrated binding, Kd, experimental blocking probability, or Docking truth."
)
FORBIDDEN = ("truth", "teacher", "experimental", "docking_gold", "r_dual_min_truth")
S0 = "S0_MATCHED_ESM2_650M_PCA_ELASTICNET__Rdual_rank_percentile"
M2 = "M2_STRUCTURE_ALPHA10__Rdual_rank_percentile"


class SelectionError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SelectionError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path, role: str) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"{role}_not_regular")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        require(fields and len(fields) == len(set(fields)), f"{role}_header")
        for field in fields:
            lowered = field.lower()
            require(not any(token in lowered for token in FORBIDDEN), f"{role}_forbidden_field:{field}")
        rows = [dict(row) for row in reader]
    return fields, rows


def by_id(rows: Sequence[Mapping[str, str]], role: str) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        candidate = row.get("candidate_id", "")
        require(candidate and candidate not in result, f"{role}_duplicate:{candidate}")
        result[candidate] = row
    return result


def number(row: Mapping[str, str], field: str, candidate: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, ValueError) as exc:
        raise SelectionError(f"invalid_numeric:{candidate}:{field}") from exc
    require(math.isfinite(value), f"nonfinite:{candidate}:{field}")
    return value


def atomic_write(path: Path, payload: str) -> None:
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def tsv(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    return buffer.getvalue()


def select_diverse(remaining: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in remaining:
        grouped[str(row["parent_framework_cluster"])].append(row)
    for values in grouped.values():
        values.sort(key=lambda row: (-float(row["four_model_ensemble_utility"]), str(row["candidate_id"])))
    selected: list[dict[str, Any]] = []
    parents = sorted(grouped)
    while len(selected) < count and any(grouped.values()):
        for parent in parents:
            if grouped[parent] and len(selected) < count:
                selected.append(grouped[parent].pop(0))
    require(len(selected) == count, "diversity_quota_unfilled")
    return selected


def run(args: argparse.Namespace) -> dict[str, Any]:
    require(not args.output_dir.exists(), "output_dir_exists")
    _, stage0_rows = read_tsv(args.stage0, "stage0")
    mm_fields, mm_rows = read_tsv(args.multimodal, "multimodal")
    _, l1_rows = read_tsv(args.l1, "l1")
    _, b_rows = read_tsv(args.b, "b")
    require({S0, M2} <= set(mm_fields), "multimodal_rank_fields_missing")
    tables = [by_id(rows, role) for rows, role in ((stage0_rows,"stage0"),(mm_rows,"multimodal"),(l1_rows,"l1"),(b_rows,"b"))]
    ids = set(tables[0])
    require(len(ids) == args.expected_rows and all(set(table) == ids for table in tables[1:]), "candidate_closure")
    records: list[dict[str, Any]] = []
    for candidate in sorted(ids):
        stage0, mm, l1, b = (table[candidate] for table in tables)
        hashes = {row.get("sequence_sha256", "") for row in (stage0, mm, l1, b)}
        require(len(hashes) == 1 and "" not in hashes, f"sequence_hash_closure:{candidate}")
        l1_utility = 1.0 - number(l1, "ensemble_conservative_top_fraction", candidate)
        b_utility = 1.0 - number(b, "ensemble_conservative_top_fraction", candidate)
        s0_utility = number(mm, S0, candidate)
        m2_utility = number(mm, M2, candidate)
        utilities = (l1_utility, b_utility, s0_utility, m2_utility)
        require(all(0.0 <= value <= 1.0 for value in utilities), f"utility_range:{candidate}")
        ensemble = 0.50*l1_utility + 0.15*b_utility + 0.15*s0_utility + 0.20*m2_utility
        support = sum(value >= 0.95 for value in utilities)
        spread = statistics.pstdev(utilities)
        record = {
            "candidate_id": candidate, "sequence": stage0["sequence"],
            "sequence_sha256": stage0["sequence_sha256"],
            "parent_framework_cluster": stage0["parent_framework_cluster"],
            "cdr3": stage0["cdr3"], "target_patch_id": stage0["target_patch_id"],
            "design_method": stage0["design_method"], "tnp_review_tier": stage0["tnp_review_tier"],
            "l1_utility": f"{l1_utility:.12g}", "b_utility": f"{b_utility:.12g}",
            "s0_utility": f"{s0_utility:.12g}", "m2_utility": f"{m2_utility:.12g}",
            "four_model_ensemble_utility": f"{ensemble:.12g}",
            "model_rank_spread": f"{spread:.12g}", "top5_model_support_count": support,
            "l1_prediction_std": l1["ensemble_R_dual_std"],
            "b_prediction_std": b["ensemble_R_dual_std"],
            "l1_receptor_gap": l1["ensemble_receptor_gap_abs"],
            "b_receptor_gap": b["ensemble_receptor_gap_abs"],
            "claim_boundary": CLAIM,
        }
        records.append(record)
    records.sort(key=lambda row: (-float(row["four_model_ensemble_utility"]), str(row["candidate_id"])))
    for rank, row in enumerate(records, start=1):
        row["four_model_global_rank"] = rank
        row["stage1_top20pct"] = "true" if rank <= args.stage1_rows else "false"
        row["high_confidence_core_flag"] = "true" if (
            int(row["top5_model_support_count"]) >= 2
            and float(row["model_rank_spread"]) <= 0.20
            and row["tnp_review_tier"] != "HIGH_RISK_REVIEW"
        ) else "false"

    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in records:
        if len(chosen) == args.exploitation_rows: break
        chosen.append(row); used.add(str(row["candidate_id"])); row["selection_channel"] = "CONSENSUS_EXPLOITATION"
    rescue_pool = sorted((row for row in records if row["candidate_id"] not in used),
        key=lambda row: (-max(float(row["l1_utility"]),float(row["b_utility"])),
                         -min(float(row["l1_utility"]),float(row["b_utility"])),str(row["candidate_id"])))
    for row in rescue_pool[:args.rescue_rows]:
        chosen.append(row); used.add(str(row["candidate_id"])); row["selection_channel"] = "TARGET_MODEL_RESCUE"
    diversity_pool = [row for row in records[:args.stage1_rows] if row["candidate_id"] not in used]
    for row in select_diverse(diversity_pool, args.diversity_rows):
        chosen.append(row); used.add(str(row["candidate_id"])); row["selection_channel"] = "PARENT_BALANCED_DIVERSITY"
    require(len(chosen) == args.final_rows and len(used) == args.final_rows, "final_quota")
    chosen.sort(key=lambda row: (-float(row["four_model_ensemble_utility"]), str(row["candidate_id"])))
    for rank, row in enumerate(chosen, start=1): row["final_portfolio_rank"] = rank

    args.output_dir.mkdir(parents=True)
    all_fields = list(records[0])
    selected_fields = list(chosen[0])
    all_path = args.output_dir / "FULL150K_FOUR_MODEL_SCORES.tsv"
    stage1_path = args.output_dir / "STAGE1_TOP30000_FOR_C2.tsv"
    selected_path = args.output_dir / "TOP7500_FOUR_MODEL_PRELIMINARY.tsv"
    core_path = args.output_dir / "TOP7500_HIGH_CONFIDENCE_CORE.tsv"
    atomic_write(all_path, tsv(records, all_fields))
    atomic_write(stage1_path, tsv(records[:args.stage1_rows], all_fields))
    atomic_write(selected_path, tsv(chosen, selected_fields))
    core = [row for row in chosen if row["high_confidence_core_flag"] == "true"]
    atomic_write(core_path, tsv(core, selected_fields))
    outputs = {path.name: sha256_file(path) for path in (all_path,stage1_path,selected_path,core_path)}
    receipt = {
        "schema_version": SCHEMA, "status": "PASS_TOP150K_FOUR_MODEL_PRELIMINARY_SELECTION",
        "claim_boundary": CLAIM, "rows": len(records), "stage1_rows": args.stage1_rows,
        "final_rows": len(chosen), "high_confidence_core_rows": len(core),
        "weights": {"L1":0.50,"M2":0.20,"S0":0.15,"B":0.15},
        "channels": dict(Counter(row["selection_channel"] for row in chosen)),
        "parent_counts": dict(Counter(row["parent_framework_cluster"] for row in chosen)),
        "inputs": {"stage0":sha256_file(args.stage0),"multimodal":sha256_file(args.multimodal),"L1":sha256_file(args.l1),"B":sha256_file(args.b)},
        "outputs": outputs, "docking_truth_access_count": 0, "experimental_label_access_count": 0,
        "next_step": "Run frozen C2 coarse-pose on Stage1 Top30000 and issue refined final Top7500."
    }
    receipt_path = args.output_dir / "RUN_RECEIPT.json"
    atomic_write(receipt_path, json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    atomic_write(args.output_dir/"SHA256SUMS", "".join(f"{sha256_file(p)}  {p.name}\n" for p in (all_path,stage1_path,selected_path,core_path,receipt_path)))
    return receipt


def parser() -> argparse.ArgumentParser:
    value=argparse.ArgumentParser(description=__doc__)
    value.add_argument("--stage0",type=Path,required=True); value.add_argument("--multimodal",type=Path,required=True)
    value.add_argument("--l1",type=Path,required=True); value.add_argument("--b",type=Path,required=True)
    value.add_argument("--expected-rows",type=int,default=150000); value.add_argument("--stage1-rows",type=int,default=30000)
    value.add_argument("--final-rows",type=int,default=7500); value.add_argument("--exploitation-rows",type=int,default=6750)
    value.add_argument("--rescue-rows",type=int,default=500); value.add_argument("--diversity-rows",type=int,default=250)
    value.add_argument("--output-dir",type=Path,required=True); return value


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()),sort_keys=True))
