#!/usr/bin/env python3
"""Audit normalized Teacher500 fast/full-QC parity across Node1 and Node23."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_AUDIT_DIR = EXP_DIR / "audits/teacher500_full_qc_node1_node23_parity_v1"
DEFAULT_NODE23_ROOT = (
    EXP_DIR
    / "runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/cascade"
)

IGNORED_OPERATIONAL_FIELDS = {"rank", "intra_team_cluster_id"}
FLOAT_TOLERANCES = {"AbNatiV_VHH_score": 1e-6}
DECISION_FIELDS = (
    "candidate_id",
    "sequence",
    "official_validator_pass",
    "ANARCI_status",
    "IMGT_CDR1",
    "IMGT_CDR2",
    "IMGT_CDR3",
    "hard_fail",
    "recommendation",
    "developability_score",
    "expression_purity_risk_score",
    "final_score",
    "cascade_full_rank",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError(f"TSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def compare_tables(node1_path: Path, node23_path: Path) -> dict[str, Any]:
    fields1, rows1 = load_tsv(node1_path)
    fields23, rows23 = load_tsv(node23_path)
    reasons: list[str] = []
    if fields1 != fields23:
        reasons.append("header_mismatch")
    if len(rows1) != len(rows23):
        reasons.append(f"row_count_mismatch:{len(rows1)}:{len(rows23)}")

    ids1 = [row.get("candidate_id", "") for row in rows1]
    ids23 = [row.get("candidate_id", "") for row in rows23]
    if ids1 != ids23:
        reasons.append("candidate_id_or_order_mismatch")

    exact_differences: Counter[str] = Counter()
    ignored_differences: Counter[str] = Counter()
    tolerated_differences: Counter[str] = Counter()
    maximum_absolute_float_delta: dict[str, float] = defaultdict(float)
    examples: dict[str, dict[str, str]] = {}
    comparison_fields = fields1 if fields1 == fields23 else sorted(set(fields1) & set(fields23))

    for node1, node23 in zip(rows1, rows23):
        for field in comparison_fields:
            value1 = node1.get(field, "")
            value23 = node23.get(field, "")
            if value1 == value23:
                continue
            examples.setdefault(
                field,
                {
                    "candidate_id": node1.get("candidate_id", ""),
                    "node1": value1,
                    "node23": value23,
                },
            )
            if field in IGNORED_OPERATIONAL_FIELDS:
                ignored_differences[field] += 1
                continue
            if field in FLOAT_TOLERANCES:
                try:
                    delta = abs(float(value1) - float(value23))
                except ValueError:
                    exact_differences[field] += 1
                    continue
                maximum_absolute_float_delta[field] = max(
                    maximum_absolute_float_delta[field], delta
                )
                if delta <= FLOAT_TOLERANCES[field]:
                    tolerated_differences[field] += 1
                    continue
            exact_differences[field] += 1

    not_applicable_decision_fields: list[str] = []
    for field in DECISION_FIELDS:
        if field not in fields1 and field not in fields23:
            not_applicable_decision_fields.append(field)
            continue
        if field not in comparison_fields:
            reasons.append(f"one_sided_missing_decision_field:{field}")
            continue
        if any(row1[field] != row23[field] for row1, row23 in zip(rows1, rows23)):
            reasons.append(f"decision_field_mismatch:{field}")

    abnativ_presence_equal = all(
        bool(row1.get("AbNatiV_VHH_score", ""))
        == bool(row23.get("AbNatiV_VHH_score", ""))
        for row1, row23 in zip(rows1, rows23)
    )
    if not abnativ_presence_equal:
        reasons.append("abnativ_score_presence_mismatch")
    if exact_differences:
        reasons.append("non_normalized_field_mismatch")

    return {
        "status": "PASS" if not reasons else "FAIL",
        "reasons": reasons,
        "node1": {
            "path": str(node1_path),
            "sha256": sha256_file(node1_path),
            "rows": len(rows1),
        },
        "node23": {
            "path": str(node23_path),
            "sha256": sha256_file(node23_path),
            "rows": len(rows23),
        },
        "header_equal": fields1 == fields23,
        "candidate_id_and_order_equal": ids1 == ids23,
        "abnativ_score_presence_equal": abnativ_presence_equal,
        "decision_fields_exact": not any(
            reason.startswith("decision_field_mismatch:") for reason in reasons
        ),
        "not_applicable_decision_fields": not_applicable_decision_fields,
        "non_normalized_difference_counts": dict(sorted(exact_differences.items())),
        "ignored_operational_difference_counts": dict(
            sorted(ignored_differences.items())
        ),
        "tolerated_numeric_difference_counts": dict(
            sorted(tolerated_differences.items())
        ),
        "maximum_absolute_float_delta": dict(
            sorted(maximum_absolute_float_delta.items())
        ),
        "difference_examples": examples,
    }


def false_like(value: str) -> bool:
    return value.strip().lower() in {"", "0", "false", "no"}


def full_qc_counts(path: Path) -> dict[str, int]:
    _fields, rows = load_tsv(path)
    hard_pass = [row for row in rows if false_like(row.get("hard_fail", ""))]
    complete = [row for row in hard_pass if row.get("AbNatiV_VHH_score", "").strip()]
    unscorable = [row for row in hard_pass if not row.get("AbNatiV_VHH_score", "").strip()]
    return {
        "full_rows": len(rows),
        "full_hard_pass": len(hard_pass),
        "full_hard_fail": len(rows) - len(hard_pass),
        "full_hard_pass_with_complete_abnativ": len(complete),
        "full_hard_pass_abnativ_unscorable": len(unscorable),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    fast = compare_tables(args.node1_fast, args.node23_fast)
    full = compare_tables(args.node1_full, args.node23_full)
    node1_counts = full_qc_counts(args.node1_full)
    node23_counts = full_qc_counts(args.node23_full)
    reasons = []
    if fast["status"] != "PASS":
        reasons.append("fast_normalized_parity_failed")
    if full["status"] != "PASS":
        reasons.append("full_normalized_parity_failed")
    if node1_counts != node23_counts:
        reasons.append("full_qc_count_mismatch")
    expected_counts = {
        "full_rows": 327,
        "full_hard_pass": 302,
        "full_hard_fail": 25,
        "full_hard_pass_with_complete_abnativ": 290,
        "full_hard_pass_abnativ_unscorable": 12,
    }
    if node1_counts != expected_counts:
        reasons.append("unexpected_full_qc_counts")

    payload = {
        "schema_version": "teacher500_full_qc_node1_node23_normalized_parity_v1",
        "status": "PASS_NORMALIZED_DECISION_PARITY" if not reasons else "FAIL",
        "reasons": reasons,
        "normalization_policy": {
            "ignored_operational_fields": sorted(IGNORED_OPERATIONAL_FIELDS),
            "ignored_field_reason": (
                "chunk-local rank and deferred cluster labels depend on chunk execution order; "
                "cascade_full_rank, cluster size, decisions and scores remain compared"
            ),
            "float_tolerances": FLOAT_TOLERANCES,
            "decision_fields_require_exact_match": list(DECISION_FIELDS),
        },
        "fast": fast,
        "full": full,
        "full_qc_counts": node1_counts,
        "node1_remote_provenance": args.node1_remote_provenance,
        "claim_boundary": (
            "Cross-node computational QC reproducibility only; not experimental binding, "
            "affinity, expression, purity, or blocking evidence."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if reasons:
        raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node1-fast", type=Path, default=DEFAULT_AUDIT_DIR / "node1_fast_merged.tsv")
    parser.add_argument("--node1-full", type=Path, default=DEFAULT_AUDIT_DIR / "node1_full_merged.tsv")
    parser.add_argument("--node23-fast", type=Path, default=DEFAULT_NODE23_ROOT / "fast_merged.tsv")
    parser.add_argument("--node23-full", type=Path, default=DEFAULT_NODE23_ROOT / "full_merged.tsv")
    parser.add_argument("--out", type=Path, default=DEFAULT_AUDIT_DIR / "node1_node23_normalized_parity_receipt.json")
    parser.add_argument(
        "--node1-remote-provenance",
        default=(
            "/data/qlyu/projects/pvrig_competition_teacher500_full_qc_v1_scaled_20260715/"
            "cascade"
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    payload = run(args)
    print(json.dumps({"status": payload["status"], "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
