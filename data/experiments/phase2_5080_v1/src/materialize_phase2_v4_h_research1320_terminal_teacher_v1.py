#!/usr/bin/env python3
"""Materialize one immutable V4-H terminal teacher for research evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "phase2_v4_h_research1320_terminal_teacher_v1"
STATUS = "COMPLETE_V4_H_TERMINAL_IMMUTABLE_TEACHER"
EXPECTED_CANDIDATE_SHA256 = "f02cfeaac9775442bb1748c7bb63413a1077b5df11f9cd7214e983d0e51c0551"
EXPECTED_ROWS = 1320
OUTPUT_FIELDS = ("candidate_id", "teacher_state", "technical_incomplete_reason", "R_dual_min")
CLAIM_BOUNDARY = (
    "Terminal immutable V4-H computational dual-receptor docking-geometry "
    "teacher for research-only surrogate evaluation; not Docking Gold, binding, "
    "affinity, competition, experimental blocking, or formal prospective validation."
)


class TeacherError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TeacherError(message)


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
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def validate_terminal_block(name: str, block: Any) -> None:
    require(isinstance(block, dict), f"terminal_block_missing:{name}")
    job_count = int(block.get("job_count", -1))
    counts = block.get("terminal_counts") or {}
    require(job_count >= 0, f"terminal_job_count_invalid:{name}")
    require(set(counts) <= {"SUCCESS", "FAILED_MAX_ATTEMPTS"}, f"nonterminal_state_in_receipt:{name}")
    require(sum(int(value) for value in counts.values()) == job_count, f"terminal_count_mismatch:{name}")


def materialize(
    final_ranking_path: Path,
    adaptive_receipt_path: Path,
    candidates_path: Path,
    output_path: Path,
    terminal_receipt_path: Path,
    *,
    expected_final_ranking_sha256: str,
    expected_adaptive_receipt_sha256: str,
    expected_candidate_sha256: str = EXPECTED_CANDIDATE_SHA256,
    expected_rows: int = EXPECTED_ROWS,
) -> dict[str, Any]:
    require(not output_path.exists() and not output_path.is_symlink(), f"output_exists:{output_path}")
    require(not terminal_receipt_path.exists() and not terminal_receipt_path.is_symlink(), f"terminal_receipt_exists:{terminal_receipt_path}")
    require(sha256_file(final_ranking_path) == expected_final_ranking_sha256, "final_ranking_hash_mismatch")
    require(sha256_file(adaptive_receipt_path) == expected_adaptive_receipt_sha256, "adaptive_receipt_hash_mismatch")
    require(sha256_file(candidates_path) == expected_candidate_sha256, "candidate_manifest_hash_mismatch")
    adaptive = json.loads(adaptive_receipt_path.read_text())
    require(adaptive.get("status") == "PASS_ADAPTIVE_DUAL_DOCKING_TERMINAL_WITH_EXPLICIT_TECHNICAL_STATES", "adaptive_receipt_status_invalid")
    require(adaptive.get("candidate_count") == expected_rows, "adaptive_candidate_count_invalid")
    require(adaptive.get("final_ranking_sha256") == expected_final_ranking_sha256, "adaptive_final_ranking_hash_mismatch")
    terminals = adaptive.get("terminals") or {}
    require(set(terminals) == {"smoke", "stage1", "stage2", "stage3"}, "adaptive_terminal_blocks_invalid")
    for name, block in terminals.items():
        validate_terminal_block(name, block)

    _candidate_fields, candidate_rows = load_tsv(candidates_path)
    require(len(candidate_rows) == expected_rows, "candidate_row_count_invalid")
    candidate_by_id = {row["candidate_id"]: row for row in candidate_rows}
    require(len(candidate_by_id) == expected_rows, "candidate_ids_not_unique")
    ranking_fields, ranking_rows = load_tsv(final_ranking_path)
    required = {
        "candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode",
        "docking_evidence_tier", "successful_seed_count_8X6B", "successful_seed_count_9E6Y",
        "median_score_8X6B", "median_score_9E6Y", "R_dual_min", "technical_reasons",
    }
    require(required <= set(ranking_fields), "final_ranking_fields_missing")
    require(len(ranking_rows) == expected_rows, "final_ranking_row_count_invalid")
    ranking_by_id = {row["candidate_id"]: row for row in ranking_rows}
    require(len(ranking_by_id) == expected_rows, "final_ranking_candidate_ids_not_unique")
    require(set(ranking_by_id) == set(candidate_by_id), "candidate_ranking_set_mismatch")

    output_rows: list[dict[str, str]] = []
    incomplete_reasons: Counter[str] = Counter()
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        row = ranking_by_id[candidate_id]
        for field in ("sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode"):
            require(row[field] == candidate[field], f"candidate_ranking_metadata_mismatch:{candidate_id}:{field}")
        count8 = int(row["successful_seed_count_8X6B"])
        count9 = int(row["successful_seed_count_9E6Y"])
        target_text = row["R_dual_min"].strip()
        if target_text:
            require(count8 >= 1 and count9 >= 1, f"analyzable_seed_count_invalid:{candidate_id}")
            require(row["docking_evidence_tier"].startswith("DUAL_"), f"analyzable_tier_invalid:{candidate_id}")
            median8 = float(row["median_score_8X6B"])
            median9 = float(row["median_score_9E6Y"])
            target = float(target_text)
            require(all(math.isfinite(value) for value in (median8, median9, target)), f"analyzable_nonfinite:{candidate_id}")
            require(abs(target - min(median8, median9)) <= 1e-8, f"R_dual_min_consistency_failed:{candidate_id}")
            output_rows.append({
                "candidate_id": candidate_id,
                "teacher_state": "ANALYZABLE",
                "technical_incomplete_reason": "",
                "R_dual_min": f"{target:.9f}",
            })
        else:
            require(count8 == 0 or count9 == 0, f"missing_target_despite_dual_success:{candidate_id}")
            reason = row["technical_reasons"].strip()
            require(bool(reason), f"technical_incomplete_reason_missing:{candidate_id}")
            incomplete_reasons[reason] += 1
            output_rows.append({
                "candidate_id": candidate_id,
                "teacher_state": "TECHNICAL_INCOMPLETE",
                "technical_incomplete_reason": reason,
                "R_dual_min": "",
            })
    require(len(output_rows) == expected_rows, "teacher_output_row_count_invalid")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(output_rows)
    atomic_write(output_path, buffer.getvalue().encode("utf-8"))
    teacher_sha = sha256_file(output_path)
    state_counts = Counter(row["teacher_state"] for row in output_rows)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "campaign_terminal": True,
        "teacher_sha256": teacher_sha,
        "expected_candidate_rows": expected_rows,
        "teacher_state_counts": dict(sorted(state_counts.items())),
        "technical_incomplete_reasons": dict(sorted(incomplete_reasons.items())),
        "required_receptors": ["8X6B", "9E6Y"],
        "partial_teacher_consumption_forbidden": True,
        "source_hashes": {
            "final_adaptive_seed_ranking": expected_final_ranking_sha256,
            "adaptive_docking_receipt": expected_adaptive_receipt_sha256,
            "candidate_manifest": expected_candidate_sha256,
        },
        "numeric_imputation_performed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_write(terminal_receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": STATUS,
        "teacher_sha256": teacher_sha,
        "terminal_receipt_sha256": sha256_file(terminal_receipt_path),
        "row_count": expected_rows,
        "state_counts": dict(sorted(state_counts.items())),
        "numeric_imputation_performed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-ranking", type=Path, required=True)
    parser.add_argument("--adaptive-receipt", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--expected-final-ranking-sha256", required=True)
    parser.add_argument("--expected-adaptive-receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--terminal-receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = materialize(
        args.final_ranking, args.adaptive_receipt, args.candidates, args.output, args.terminal_receipt,
        expected_final_ranking_sha256=args.expected_final_ranking_sha256,
        expected_adaptive_receipt_sha256=args.expected_adaptive_receipt_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
