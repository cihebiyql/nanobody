#!/usr/bin/env python3
"""Terminalize the frozen V4-F96 Fast-QC run when no candidate is eligible.

This recovery never changes a gate and never launches Full-QC.  It validates
the exact already-produced V2 evidence and publishes an immutable eligibility
receipt whose hard-pass count is zero.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path("/data1/qlyu/projects/pvrig_v4_f_holdout96_full_qc_recovery_v2_20260717")
OUTPUT_ROOT = Path("/data1/qlyu/projects/pvrig_v4_f_holdout96_zero_eligible_terminal_v2_1_20260717")
PROTOCOL_NAME = "phase2_v4_f_holdout96_zero_eligible_terminal_v2_1_recovery_protocol.json"
FREEZE_NAME = "IMPLEMENTATION_FREEZE.json"
CLAIM = (
    "Frozen V4-F96 sequence/Fast-QC eligibility attrition only; not Full-QC evidence for any "
    "candidate, not Docking, geometry, binding, affinity, competition, experimental blocking, "
    "blocker probability, or Docking Gold."
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"json_object_required:{path}")
    return value


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(raw, path)
        path.chmod(0o444)
    finally:
        if os.path.exists(raw):
            os.unlink(raw)


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(raw, path)
        path.chmod(0o444)
    finally:
        if os.path.exists(raw):
            os.unlink(raw)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def validate_hashes(source: Path, protocol: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in protocol["source_hashes"].items():
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"source_regular_file_required:{relative}")
        value = sha256(path)
        if value != expected:
            raise RuntimeError(f"source_hash_mismatch:{relative}:{value}:{expected}")
        observed[relative] = value
    return observed


def validate_fast_chunks(source: Path, protocol: dict[str, Any]) -> str:
    files = sorted((source / "cascade/fast_chunks").glob("chunk_*/complete.json"))
    if len(files) != 8:
        raise RuntimeError(f"fast_chunk_count:{len(files)}")
    lines: list[str] = []
    total = 0
    for path in files:
        if path.is_symlink():
            raise RuntimeError(f"fast_chunk_symlink:{path}")
        payload = read_json(path)
        if payload.get("status") != "complete" or int(payload.get("candidate_count", -1)) != 12:
            raise RuntimeError(f"fast_chunk_not_complete:{path.name}")
        total += int(payload["candidate_count"])
        lines.append(f"{path.relative_to(source)}\t{sha256(path)}\n")
    if total != 96:
        raise RuntimeError(f"fast_chunk_candidate_total:{total}")
    digest = hashlib.sha256("".join(lines).encode()).hexdigest()
    if digest != protocol["fast_chunk_completion_set_sha256"]:
        raise RuntimeError(f"fast_chunk_set_hash_mismatch:{digest}")
    return digest


def validate_source(source: Path, protocol: dict[str, Any]) -> dict[str, Any]:
    observed_hashes = validate_hashes(source, protocol)
    manifest = read_tsv(source / "inputs/prospective_holdout96_manifest.tsv")
    fast = read_tsv(source / "cascade/fast_merged.tsv")
    if len(manifest) != 96 or len(fast) != 96:
        raise RuntimeError(f"row_count_closure:{len(manifest)}:{len(fast)}")
    manifest_by_id = {row["candidate_id"]: row for row in manifest}
    fast_by_id = {row["candidate_id"]: row for row in fast}
    if len(manifest_by_id) != 96 or len(fast_by_id) != 96 or set(manifest_by_id) != set(fast_by_id):
        raise RuntimeError("candidate_id_closure_failed")
    for candidate_id, row in fast_by_id.items():
        source_row = manifest_by_id[candidate_id]
        if row.get("sequence") != source_row.get("sequence"):
            raise RuntimeError(f"sequence_binding_failed:{candidate_id}")
        expected_sequence_hash = hashlib.sha256(row["sequence"].encode()).hexdigest()
        if source_row.get("sequence_sha256") != expected_sequence_hash:
            raise RuntimeError(f"manifest_sequence_hash_failed:{candidate_id}")
        if row.get("hard_fail", "").lower() != "true":
            raise RuntimeError(f"nonzero_eligible_candidate:{candidate_id}")
        if row.get("external_binder_status") != "NOT_PROVIDED" or row.get("external_binder_score"):
            raise RuntimeError(f"model_score_present:{candidate_id}")

    state = read_json(source / "cascade/cascade_state.json").get("stages", {})
    for stage in ("prepare", "fast", "merge_fast", "full"):
        if state.get(stage, {}).get("status") != "complete":
            raise RuntimeError(f"stage_not_complete:{stage}")
    if int(state["merge_fast"].get("hard_pass", -1)) != 0:
        raise RuntimeError("merge_fast_nonzero_hard_pass")
    if state["full"].get("reason") != "no survivors" or int(state["full"].get("chunks", -1)) != 0:
        raise RuntimeError("full_stage_not_zero_survivor")
    if "merge_full" in state:
        raise RuntimeError("unexpected_merge_full_stage")
    if any((source / "cascade/full_chunks").glob("chunk_*/complete.json")):
        raise RuntimeError("unexpected_full_chunk_completion")
    for relative in (
        "cascade/full_qc_shortlist.tsv",
        "cascade/full_qc_shortlist.fasta",
        "cascade/full_qc_excluded_due_cap.tsv",
    ):
        if (source / relative).stat().st_size != 0:
            raise RuntimeError(f"nonempty_zero_eligible_artifact:{relative}")
    if (source / "cascade/full_merged.tsv").exists():
        raise RuntimeError("unexpected_full_merged")

    failure = read_json(source / "status/runner.failed.json")
    if failure.get("status") != "FAIL_V4_F96_FULL_QC_RECOVERY_V2" or failure.get("error") != "RuntimeError:cascade_stage_not_complete:merge_full":
        raise RuntimeError("unexpected_v2_failure_signature")
    for pid_file in ("status/runner.launch.pid", "status/deployment_waiter.pid"):
        path = source / pid_file
        if path.is_file():
            pid = int(path.read_text().strip())
            if process_alive(pid):
                raise RuntimeError(f"source_process_still_alive:{pid_file}:{pid}")

    fast_chunk_hash = validate_fast_chunks(source, protocol)
    reason_counts = Counter(row.get("reason_summary", "") for row in fast)
    fr4_counts = Counter(row["sequence"][-12:] for row in fast)
    return {
        "observed_source_hashes": observed_hashes,
        "fast_chunk_completion_set_sha256": fast_chunk_hash,
        "input_rows": 96,
        "fast_rows": 96,
        "fast_hard_pass": 0,
        "fast_hard_fail": 96,
        "full_eligible": 0,
        "reason_summary_counts": dict(sorted(reason_counts.items())),
        "sequence_suffix12_counts": dict(sorted(fr4_counts.items())),
        "manifest_candidate_id_sequence_sha256_pairs_sha256": hashlib.sha256(
            "".join(f"{row['candidate_id']}\t{row['sequence_sha256']}\n" for row in manifest).encode()
        ).hexdigest(),
    }


def validate_package(output: Path, protocol_path: Path, script_path: Path) -> dict[str, str]:
    for path in (protocol_path, script_path, output / FREEZE_NAME):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"package_regular_file_required:{path.name}")
    freeze = read_json(output / FREEZE_NAME)
    observed = {
        "protocol": sha256(protocol_path),
        "terminalizer": sha256(script_path),
    }
    expected = freeze.get("hashes", {})
    for name, value in observed.items():
        if expected.get(name) != value:
            raise RuntimeError(f"implementation_freeze_mismatch:{name}")
    return observed


def finalize(source: Path, output: Path, protocol_path: Path, script_path: Path) -> dict[str, Any]:
    protocol = read_json(protocol_path)
    if source.resolve() != Path(protocol["source_root"]).resolve() or output.resolve() != Path(protocol["output_root"]).resolve():
        raise RuntimeError("canonical_path_mismatch")
    package_hashes = validate_package(output, protocol_path, script_path)
    evidence = validate_source(source, protocol)
    if (output / "CANONICAL_ELIGIBILITY_RECEIPT.json").exists():
        raise RuntimeError("terminal_receipt_already_exists")
    for relative in ("outputs", "status"):
        path = output / relative
        if path.exists() and any(path.rglob("*")):
            raise RuntimeError(f"nonzero_terminalization_output:{relative}")

    tnp_rows = [
        {"candidate_id": row["candidate_id"], "tnp_supervision_state": "UPSTREAM_FAST_HARD_FAIL_NA", "tnp_score": "", "tnp_flag": ""}
        for row in read_tsv(source / "inputs/prospective_holdout96_manifest.tsv")
    ]
    tnp_path = output / "outputs/tnp_three_state_unrun_summary.tsv"
    write_tsv(tnp_path, tnp_rows, ["candidate_id", "tnp_supervision_state", "tnp_score", "tnp_flag"])
    summary = {
        "schema_version": "phase2_v4_f_holdout96_zero_eligible_terminal_summary_v2_1",
        "status": "PASS_COMPLETE_WITH_ZERO_ELIGIBLE",
        "terminal_state": "COMPLETE_WITH_ZERO_ELIGIBLE",
        "published_at_utc": utc_now(),
        **{key: evidence[key] for key in ("input_rows", "fast_rows", "fast_hard_pass", "fast_hard_fail", "full_eligible")},
        "full_qc_executed": False,
        "full_qc_rows": 0,
        "no_replacement": True,
        "no_imputation": True,
        "model_based_selection": False,
        "tnp_run": False,
        "tnp_policy": "UPSTREAM_FAST_HARD_FAIL_NA_NO_IMPUTATION",
        "tnp_state_counts": {"UPSTREAM_FAST_HARD_FAIL_NA": 96},
        "tnp_numeric_or_flag_nonblank": 0,
        "reason_summary_counts": evidence["reason_summary_counts"],
        "sequence_suffix12_counts": evidence["sequence_suffix12_counts"],
        "source_hashes": evidence["observed_source_hashes"],
        "fast_chunk_completion_set_sha256": evidence["fast_chunk_completion_set_sha256"],
        "manifest_candidate_id_sequence_sha256_pairs_sha256": evidence["manifest_candidate_id_sequence_sha256_pairs_sha256"],
        "tnp_state_summary_sha256": sha256(tnp_path),
        "label_path_access": {"model": 0, "v4_f_predictions": 0, "docking": 0, "geometry": 0, "experimental": 0},
        "claim_boundary": CLAIM,
    }
    summary_path = output / "outputs/eligibility_terminal_summary.json"
    write_json(summary_path, summary)
    receipt = {
        "schema_version": "phase2_v4_f_holdout96_canonical_eligibility_receipt_v2_1",
        "status": "PASS_CANONICAL_ELIGIBILITY_ZERO_HARDPASS",
        "published_at_utc": utc_now(),
        "hardpass_count": 0,
        "hardfail_count": 96,
        "eligible_candidate_ids": [],
        "downstream_docking_eligible_count": 0,
        "terminal_state": "COMPLETE_WITH_ZERO_ELIGIBLE",
        "no_replacement": True,
        "full_qc_executed": False,
        "hashes": {
            **package_hashes,
            "implementation_freeze": sha256(output / FREEZE_NAME),
            "eligibility_terminal_summary": sha256(summary_path),
            "tnp_three_state_unrun_summary": sha256(tnp_path),
        },
        "label_path_access": summary["label_path_access"],
        "claim_boundary": CLAIM,
    }
    write_json(output / "CANONICAL_ELIGIBILITY_RECEIPT.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.validate_only == args.finalize:
        raise SystemExit("choose exactly one of --validate-only or --finalize")
    protocol_path = OUTPUT_ROOT / PROTOCOL_NAME
    script_path = OUTPUT_ROOT / Path(__file__).name
    protocol = read_json(protocol_path)
    validate_package(OUTPUT_ROOT, protocol_path, script_path)
    if args.validate_only:
        result = validate_source(SOURCE_ROOT, protocol)
        print(json.dumps({"status": "PASS_ZERO_ELIGIBLE_SOURCE_VALIDATED", **result, "claim_boundary": CLAIM}, indent=2, sort_keys=True))
        return 0
    print(json.dumps(finalize(SOURCE_ROOT, OUTPUT_ROOT, protocol_path, script_path), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
