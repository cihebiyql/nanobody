#!/usr/bin/env python3
"""Delete only Node1-verified heavy payload while retaining bxcpu resume stubs."""

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import sys
from typing import Any, Dict, Iterable, List


SAFE_JOB_ID = re.compile(r"[A-Za-z0-9_.-]+")


def _remove(path: pathlib.Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def prune_jobs(root: pathlib.Path, job_ids: Iterable[str]) -> Dict[str, Any]:
    pruned: List[str] = []
    skipped: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []
    for job_id in job_ids:
        job_id = job_id.strip()
        if not job_id:
            continue
        if not SAFE_JOB_ID.fullmatch(job_id):
            errors.append({"job_id": job_id, "error": "unsafe_job_id"})
            continue
        status_path = root / "status/jobs" / f"{job_id}.json"
        result_dir = root / "results" / job_id
        result_path = result_dir / "job_result.json"
        run_dir = root / "runs" / job_id
        worker_log = root / "worker_logs" / f"{job_id}.log"
        compact = root / "compressed_queue" / f"{job_id}.tar.gz"
        try:
            status = json.loads(status_path.read_text())
            state = status.get("status")
            terminal_failure = state == "FAILED_MAX_ATTEMPTS" or (
                state == "FAILED" and int(status.get("attempts", 0) or 0) >= 2
            )
            if terminal_failure:
                _remove(run_dir)
                _remove(result_dir)
                _remove(worker_log)
                _remove(compact)
                pruned.append(job_id)
                continue
            if state != "SUCCESS":
                skipped.append({"job_id": job_id, "reason": "not_terminal_success"})
                continue

            if result_path.is_file():
                result = json.loads(result_path.read_text())
                if result.get("state") != "SUCCESS":
                    raise RuntimeError("job_result is not SUCCESS")
                if result.get("job_id") not in (None, job_id):
                    raise RuntimeError("job_result identity mismatch")
            else:
                if run_dir.is_dir() or worker_log.exists() or compact.exists():
                    raise RuntimeError(
                        "job_result missing while unpruned heavy payload remains"
                    )
                result = {}
                result_dir.mkdir(parents=True, exist_ok=True)

            already_offloaded = result.get("offloaded_to_node1") is True
            if not already_offloaded and not compact.is_file():
                raise RuntimeError(
                    "SUCCESS payload lacks compressed evidence before first prune"
                )

            _remove(run_dir)
            if result_dir.is_dir():
                for child in list(result_dir.iterdir()):
                    if child.name != "job_result.json":
                        _remove(child)
            _remove(worker_log)
            _remove(compact)

            stub = {
                "state": "SUCCESS",
                "job_id": result.get("job_id", job_id),
                "job_hash": result.get("job_hash") or status.get("job_hash"),
                "protocol_core_sha256": result.get("protocol_core_sha256")
                or status.get("protocol_core_sha256"),
                "selected_model_count": result.get("selected_model_count")
                or status.get("selected_model_count"),
                "selected_models": result.get("selected_models", []),
                "full_result_in_compact_archive": True,
                "offloaded_to_node1": True,
                "offloaded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            temporary = result_path.with_name(
                f".{result_path.name}.offload.{os.getpid()}"
            )
            temporary.write_text(json.dumps(stub, sort_keys=True) + "\n")
            os.replace(temporary, result_path)
            if not status_path.is_file() or not result_path.is_file():
                raise RuntimeError("resume stubs missing after prune")
            pruned.append(job_id)
        except Exception as exc:
            errors.append({"job_id": job_id, "error": repr(exc)})
    return {"pruned": pruned, "skipped": skipped, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, required=True)
    args = parser.parse_args()
    payload = prune_jobs(args.root, sys.stdin)
    print(json.dumps(payload, sort_keys=True))
    return 0 if not payload["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
