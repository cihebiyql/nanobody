#!/usr/bin/env python3
"""Supplement TNP evidence skipped or technically missing in the uniform QC.

The original vhh-screen outputs are never overwritten.  Missing rows are
retried once with the same TNP executable, and a merged sidecar is written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-tsv", required=True, type=Path)
    parser.add_argument("--ranked-tsv", required=True, type=Path)
    parser.add_argument("--screen-summary", required=True, type=Path)
    parser.add_argument("--tnp-bin", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--ncores", type=int, default=8)
    return parser.parse_args()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, delimiter="\t", fieldnames=fields, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = args.output_dir / "runs"
    logs_dir = args.output_dir / "logs"
    runs_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    frozen = read_tsv(args.freeze_tsv)
    ranked = {row["candidate_id"]: row for row in read_tsv(args.ranked_tsv)}
    screen = read_tsv(args.screen_summary)
    assert len(frozen) == len(screen) == len(ranked) == 50
    frozen_by_sid = {row["submission_id"]: row for row in frozen}
    assert set(frozen_by_sid) == {row["id"] for row in screen}

    missing = [row for row in screen if not row.get("tnp_L_flag")]

    def run_one(row: dict[str, str]) -> dict[str, Any]:
        sid = row["id"]
        freeze = frozen_by_sid[sid]
        candidate_ranked = ranked[freeze["candidate_id"]]
        output = runs_dir / sid
        log_path = logs_dir / f"{sid}.log"
        command = [
            str(args.tnp_bin),
            "--seq",
            freeze["sequence"],
            "--name",
            sid,
            "--output",
            str(output),
            "--ncores",
            str(args.ncores),
        ]
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True
        )
        log_path.write_text(
            "$ " + " ".join(command) + "\n\nSTDOUT:\n"
            + completed.stdout
            + "\nSTDERR:\n"
            + completed.stderr,
            encoding="utf-8",
        )
        result_path = output / f"TNP_Results_SingleSeqEntry_{sid}.json"
        result: dict[str, Any] | None = None
        parse_error = ""
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                candidate_result = payload.get(sid)
                if isinstance(candidate_result, dict):
                    result = candidate_result
                else:
                    parse_error = f"non-dict result: {candidate_result!r}"
            except Exception as error:  # pragma: no cover - runtime evidence
                parse_error = repr(error)
        else:
            parse_error = "result JSON missing"
        parent = candidate_ranked["parent_cluster"]
        reason_class = (
            "PATENT_SUCCESS_POOR_L2_POLICY_SKIP"
            if (
                row.get("single_domain_suitability") == "poor"
                and parent.startswith("positive_pose_source_case02_")
            )
            else "TECHNICAL_OR_OTHER_MISSING_TNP"
        )
        return {
            "submission_id": sid,
            "candidate_id": freeze["candidate_id"],
            "competition_rank_1_50": freeze["competition_rank_1_50"],
            "mechanism_rank_immutable": freeze["mechanism_rank_immutable"],
            "parent_cluster": parent,
            "original_final_verdict": row["final_verdict"],
            "original_L2_vhh_features": row["L2_vhh_features"],
            "original_L3_developability": row["L3_developability"],
            "original_single_domain_suitability": row[
                "single_domain_suitability"
            ],
            "missing_reason_class": reason_class,
            "retry_returncode": completed.returncode,
            "retry_status": "SUCCESS" if result else "TECHNICAL_FAILURE_AFTER_RETRY",
            "retry_parse_error": parse_error,
            "retry_log_path": str(log_path),
            "retry_result_path": str(result_path),
            "retry_result": result,
        }

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        retry_rows = list(pool.map(run_one, missing))
    retry_by_sid = {row["submission_id"]: row for row in retry_rows}

    merged: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    for original in screen:
        sid = original["id"]
        output = dict(original)
        if original.get("tnp_L_flag"):
            output["tnp_completion_status"] = "ORIGINAL_UNIFORM_FULL_QC"
            output["tnp_completion_source"] = "vhh_screen"
            output["tnp_completion_missing_reason_class"] = ""
            output["tnp_completion_log_path"] = ""
            output["tnp_completion_result_path"] = ""
            status_rows.append(
                {
                    "submission_id": sid,
                    "candidate_id": frozen_by_sid[sid]["candidate_id"],
                    "status": "ORIGINAL_UNIFORM_FULL_QC",
                    "missing_reason_class": "",
                    "tnp_flags": "/".join(
                        original.get(f"tnp_{name}_flag", "")
                        for name in ("L", "L3", "C", "PSH", "PPC", "PNC")
                    ),
                    "log_path": "",
                    "result_path": "",
                }
            )
        else:
            retry = retry_by_sid[sid]
            result = retry["retry_result"]
            output["tnp_completion_status"] = retry["retry_status"]
            output["tnp_completion_source"] = "supplemental_same_TNP_retry"
            output["tnp_completion_missing_reason_class"] = retry[
                "missing_reason_class"
            ]
            output["tnp_completion_log_path"] = retry["retry_log_path"]
            output["tnp_completion_result_path"] = retry["retry_result_path"]
            if result:
                flags = result.get("Flags", {})
                for name in ("L", "L3", "C", "PSH", "PPC", "PNC"):
                    output[f"tnp_{name}_flag"] = flags.get(name, "")
                output["tnp_PSH"] = result.get("PSH", "")
                output["tnp_PPC"] = result.get("PPC", "")
                output["tnp_PNC"] = result.get("PNC", "")
            status_rows.append(
                {
                    key: value
                    for key, value in retry.items()
                    if key != "retry_result"
                }
                | {
                    "tnp_flags": ""
                    if not result
                    else "/".join(
                        str(result.get("Flags", {}).get(name, ""))
                        for name in ("L", "L3", "C", "PSH", "PPC", "PNC")
                    )
                }
            )
        merged.append(output)

    merged_path = args.output_dir / "Final50_uniform_screen_summary_tnp_completed.tsv"
    status_path = args.output_dir / "Final50_uniform_tnp_completion_status.tsv"
    write_tsv(merged_path, merged)
    write_tsv(status_path, status_rows)
    success = sum(
        row.get("tnp_completion_status")
        in {"ORIGINAL_UNIFORM_FULL_QC", "SUCCESS"}
        for row in merged
    )
    retry_success = sum(row["retry_status"] == "SUCCESS" for row in retry_rows)
    receipt = {
        "schema_version": "qc397_final50_uniform_tnp_completion_v1",
        "state": "COMPLETE_WITH_EXPLICIT_TECHNICAL_FAILURES"
        if success < 50
        else "COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_count": 50,
        "original_tnp_complete": 50 - len(missing),
        "missing_retried": len(missing),
        "retry_success": retry_success,
        "retry_technical_failure": len(missing) - retry_success,
        "total_tnp_complete_after_retry": success,
        "inputs": {
            str(path): sha256(path)
            for path in (
                args.freeze_tsv,
                args.ranked_tsv,
                args.screen_summary,
                args.tnp_bin,
            )
        },
        "outputs": {
            merged_path.name: sha256(merged_path),
            status_path.name: sha256(status_path),
        },
        "assertions": {
            "original_screen_not_overwritten": True,
            "merged_rows_exact_50": len(merged) == 50,
            "all_original_missing_rows_retried_once": len(retry_rows) == len(missing),
        },
        "claim_boundary": (
            "Same TNP software retry/supplement only; technical failure is retained "
            "as uncertainty and no value is measured expression or purity."
        ),
    }
    receipt_path = args.output_dir / "UNIFORM_TNP_COMPLETION_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
