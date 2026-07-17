#!/usr/bin/env python3
"""Evaluate frozen M1/M2 models on a nonterminal V4-H success snapshot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = "phase2_v4_h_partial_success_preview_evaluation_v1"
STATUS = "COMPLETE_PARTIAL_SUCCESS_PREVIEW_EVALUATION_NOT_TERMINAL"
EXPECTED_SEQUENCE_SHA256 = "a87d37d9edf130b2eb82e301746d52abee4a56fd7babf5bde4b5b0eefcc92fbc"
EXPECTED_STRUCTURE_SHA256 = "f864c675db2c9ec449e52a7debacdd283ff5d404f40b6abfbd9cb0ef3e6b9d5a"
EXPECTED_PREREG_SHA256 = "153a86688528a7431e0224b53f12e0f212d73846c386f66e609df1043b760f4d"
EXPECTED_TERMINAL_EVALUATOR_SHA256 = "a23cde3b21b37916e80bcab8ca5da0e18685388c3a414bb76673dd10b8b775e2"
EXPECTED_ROWS = 1320
CLAIM_BOUNDARY = (
    "Partial active-campaign development preview only; not terminal teacher, "
    "Docking Gold, binding, affinity, competition, experimental blocking, "
    "formal validation, or final submission authority."
)


class PreviewError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreviewError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(bool(rows), f"empty_table:{path.name}")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    atomic_write(path, buffer.getvalue().encode("utf-8"))


def load_metric_module(path: Path):
    spec = importlib.util.spec_from_file_location("v4h_partial_preview_metrics", path)
    require(spec is not None and spec.loader is not None, "cannot_load_metric_module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def evaluate(
    teacher_path: Path,
    snapshot_receipt_path: Path,
    sequence_path: Path,
    structure_path: Path,
    preregistration_path: Path,
    terminal_evaluator_path: Path,
    output_dir: Path,
    *,
    expected_teacher_sha256: str,
    expected_snapshot_receipt_sha256: str,
    expected_sequence_sha256: str = EXPECTED_SEQUENCE_SHA256,
    expected_structure_sha256: str = EXPECTED_STRUCTURE_SHA256,
    expected_prereg_sha256: str = EXPECTED_PREREG_SHA256,
    expected_terminal_evaluator_sha256: str = EXPECTED_TERMINAL_EVALUATOR_SHA256,
    expected_rows: int = EXPECTED_ROWS,
    bootstrap_replicates: int = 5000,
    bootstrap_seed: int = 20260717,
) -> dict[str, Any]:
    require(not output_dir.exists() and not output_dir.is_symlink(), f"output_exists:{output_dir}")
    for path, expected, error in (
        (teacher_path, expected_teacher_sha256, "teacher_hash_mismatch"),
        (snapshot_receipt_path, expected_snapshot_receipt_sha256, "snapshot_receipt_hash_mismatch"),
        (sequence_path, expected_sequence_sha256, "sequence_hash_mismatch"),
        (structure_path, expected_structure_sha256, "structure_hash_mismatch"),
        (preregistration_path, expected_prereg_sha256, "preregistration_hash_mismatch"),
        (terminal_evaluator_path, expected_terminal_evaluator_sha256, "metric_module_hash_mismatch"),
    ):
        require(sha256_file(path) == expected, error)
    receipt = json.loads(snapshot_receipt_path.read_text())
    require(receipt.get("status") == "COMPLETE_PARTIAL_DEVELOPMENT_PREVIEW_SNAPSHOT_NOT_TERMINAL", "snapshot_status_invalid")
    require(receipt.get("campaign_terminal") is False, "snapshot_must_be_nonterminal")
    require(receipt.get("candidate_rows") == expected_rows, "snapshot_candidate_rows_invalid")
    require((receipt.get("outputs") or {}).get("partial_teacher", {}).get("sha256") == expected_teacher_sha256, "snapshot_teacher_hash_mismatch")
    require(receipt.get("new_completions_after_snapshot_included") is False, "snapshot_boundary_invalid")
    require(receipt.get("model_or_threshold_changes_permitted_from_preview") is False, "preview_change_gate_invalid")

    teacher_rows = load_tsv(teacher_path)
    sequence_rows = load_tsv(sequence_path)
    structure_rows = load_tsv(structure_path)
    require(len(teacher_rows) == len(sequence_rows) == len(structure_rows) == expected_rows, "row_count_invalid")
    teacher_by_id = {row["candidate_id"]: row for row in teacher_rows}
    sequence_by_id = {row["candidate_id"]: row for row in sequence_rows}
    structure_by_id = {row["candidate_id"]: row for row in structure_rows}
    require(len(teacher_by_id) == len(sequence_by_id) == len(structure_by_id) == expected_rows, "candidate_ids_not_unique")
    require(set(teacher_by_id) == set(sequence_by_id) == set(structure_by_id), "candidate_set_mismatch")
    metric = load_metric_module(terminal_evaluator_path)
    analyzable: list[dict[str, Any]] = []
    incomplete: list[dict[str, str]] = []
    for candidate_id in sorted(teacher_by_id):
        teacher = teacher_by_id[candidate_id]
        sequence = sequence_by_id[candidate_id]
        structure = structure_by_id[candidate_id]
        for field in ("sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"):
            require(teacher[field] == sequence[field] == structure[field], f"metadata_mismatch:{candidate_id}:{field}")
        state = teacher["preview_state"]
        if state == "PARTIAL_ANALYZABLE":
            require(teacher["R_dual_min"].strip(), f"preview_target_missing:{candidate_id}")
            target = float(teacher["R_dual_min"])
            values = (target, float(sequence["predicted_R_dual_min_sequence_only"]), float(structure["predicted_R_dual_min_structure_only"]))
            require(all(np.isfinite(value) for value in values), f"preview_value_nonfinite:{candidate_id}")
            analyzable.append({
                "candidate_id":candidate_id, "parent_framework_cluster":teacher["parent_framework_cluster"],
                "target_patch_id":teacher["target_patch_id"], "design_mode":teacher["design_mode"],
                "target":values[0], "m1":values[1], "m2":values[2],
            })
        elif state == "PARTIAL_INCOMPLETE":
            require(not teacher["R_dual_min"].strip(), f"incomplete_target_not_empty:{candidate_id}")
            require(teacher["partial_incomplete_reason"].strip(), f"incomplete_reason_missing:{candidate_id}")
            incomplete.append(teacher)
        else:
            raise PreviewError(f"preview_state_invalid:{candidate_id}:{state}")
    require(len(analyzable) >= 4, "analyzable_rows_too_few")
    y=np.asarray([row["target"] for row in analyzable],dtype=np.float64)
    m1=np.asarray([row["m1"] for row in analyzable],dtype=np.float64)
    m2=np.asarray([row["m2"] for row in analyzable],dtype=np.float64)
    groups=[row["parent_framework_cluster"] for row in analyzable]
    global_metrics={"M1_SEQUENCE_ONLY":metric.metrics(y,m1),"M2_STRUCTURE_ONLY":metric.metrics(y,m2)}
    bootstrap=metric.group_bootstrap_delta(y,m1,m2,groups,bootstrap_replicates,bootstrap_seed)
    centered_y=metric.parent_center(y,groups)
    parent_centered={
        "M1_SEQUENCE_ONLY_spearman":metric.spearman(centered_y,metric.parent_center(m1,groups)),
        "M2_STRUCTURE_ONLY_spearman":metric.spearman(centered_y,metric.parent_center(m2,groups)),
    }
    per_parent=[]
    for parent in sorted(set(groups)):
        indices=np.asarray([i for i,g in enumerate(groups) if g==parent],dtype=np.int64)
        if len(indices)<4: continue
        s1=metric.spearman(y[indices],m1[indices]);s2=metric.spearman(y[indices],m2[indices])
        per_parent.append({
            "schema_version":SCHEMA_VERSION,"parent_framework_cluster":parent,"analyzable_rows":len(indices),
            "M1_sequence_spearman":f"{s1:.12g}","M2_structure_spearman":f"{s2:.12g}",
            "delta_M2_minus_M1":f"{s2-s1:.12g}","claim_boundary":CLAIM_BOUNDARY,
        })
    require(bool(per_parent), "no_parent_metrics")
    p1=np.asarray([float(row["M1_sequence_spearman"]) for row in per_parent]);p2=np.asarray([float(row["M2_structure_spearman"]) for row in per_parent])
    macro={
        "parent_count":len(per_parent),"M1_mean":float(np.mean(p1)),"M1_median":float(np.median(p1)),
        "M2_mean":float(np.mean(p2)),"M2_median":float(np.median(p2)),
    }
    coverage: dict[str,Any]={}
    for field in ("parent_framework_cluster","target_patch_id","design_mode"):
        planned=Counter(row[field] for row in teacher_rows); observed=Counter(row[field] for row in analyzable)
        coverage[field]={key:{"planned":planned[key],"analyzable":observed[key],"fraction":observed[key]/planned[key]} for key in sorted(planned)}
    output_dir.mkdir(parents=True)
    parent_path=output_dir/"partial_preview_per_parent_v1.tsv";write_tsv(parent_path,per_parent)
    audit={
        "schema_version":SCHEMA_VERSION,"status":STATUS,"claim_boundary":CLAIM_BOUNDARY,
        "campaign_terminal":False,"candidate_rows":expected_rows,"analyzable_rows":len(analyzable),"partial_incomplete_rows":len(incomplete),
        "incomplete_reasons":dict(sorted(Counter(row["partial_incomplete_reason"] for row in incomplete).items())),
        "global_metrics":global_metrics,"paired_parent_group_bootstrap":bootstrap,"parent_centered":parent_centered,
        "per_parent_macro":macro,"coverage":coverage,
        "selection_bias_warning":"Active job-order/success snapshot; coverage is not a random sample and most evidence is single-seed.",
        "model_or_threshold_changes_authorized":False,"terminal_evaluation_still_required":True,
        "input_hashes":{"teacher":expected_teacher_sha256,"snapshot_receipt":expected_snapshot_receipt_sha256,"sequence":expected_sequence_sha256,"structure":expected_structure_sha256,"preregistration":expected_prereg_sha256,"metric_module":expected_terminal_evaluator_sha256},
        "outputs":{"per_parent":{"path":parent_path.name,"sha256":sha256_file(parent_path)}},
    }
    audit_path=output_dir/"partial_success_preview_evaluation_v1.audit.json"
    atomic_write(audit_path,(json.dumps(audit,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+"\n").encode())
    result={
        "status":STATUS,"campaign_terminal":False,"analyzable_rows":len(analyzable),"partial_incomplete_rows":len(incomplete),
        "global_metrics":global_metrics,"parent_centered":parent_centered,"bootstrap":bootstrap,
        "audit_sha256":sha256_file(audit_path),"terminal_evaluation_still_required":True,
    }
    receipt_path=output_dir/"partial_success_preview_evaluation_v1.receipt.json"
    atomic_write(receipt_path,(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+"\n").encode())
    result["receipt_sha256"]=sha256_file(receipt_path)
    return result


def parse_args() -> argparse.Namespace:
    parser=argparse.ArgumentParser()
    parser.add_argument("--teacher",type=Path,required=True);parser.add_argument("--snapshot-receipt",type=Path,required=True)
    parser.add_argument("--sequence-ranking",type=Path,required=True);parser.add_argument("--structure-ranking",type=Path,required=True)
    parser.add_argument("--preregistration",type=Path,required=True);parser.add_argument("--terminal-evaluator",type=Path,required=True)
    parser.add_argument("--expected-teacher-sha256",required=True);parser.add_argument("--expected-snapshot-receipt-sha256",required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    return parser.parse_args()


def main() -> int:
    args=parse_args()
    result=evaluate(args.teacher,args.snapshot_receipt,args.sequence_ranking,args.structure_ranking,args.preregistration,args.terminal_evaluator,args.output_dir,expected_teacher_sha256=args.expected_teacher_sha256,expected_snapshot_receipt_sha256=args.expected_snapshot_receipt_sha256)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False));return 0


if __name__=="__main__": raise SystemExit(main())
