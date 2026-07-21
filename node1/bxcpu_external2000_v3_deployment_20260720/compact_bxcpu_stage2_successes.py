#!/usr/bin/env python3
"""Compact published SUCCESS payloads on bxcpu without removing resume stubs."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--recent-seconds", type=int, default=0)
    parser.add_argument("--minimum-age-seconds", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--poll-seconds", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    args = parser.parse_args()
    root = Path(args.root)
    queue = root / "compressed_queue"
    queue.mkdir(parents=True, exist_ok=True)
    lock_root = queue / ".locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    events = queue / "COMPACTION_EVENTS.jsonl"

    while True:
        completed = 0
        statuses = sorted((root / "status/jobs").glob("*.json"), key=lambda p: p.stat().st_mtime)
        for status_path in statuses:
            if args.limit and completed >= args.limit:
                break
            job_id = status_path.stem
            shard = int(hashlib.sha256(job_id.encode()).hexdigest()[:16], 16) % args.shard_count
            if shard != args.shard_index:
                continue
            run_dir = root / "runs" / job_id
            result_dir = root / "results" / job_id
            result_json = result_dir / "job_result.json"
            archive = queue / f"{job_id}.tar.gz"
            if archive.exists() or not run_dir.is_dir() or not result_json.is_file():
                continue
            age = time.time() - status_path.stat().st_mtime
            if args.recent_seconds and age > args.recent_seconds:
                continue
            if age < args.minimum_age_seconds:
                continue
            try:
                lock = lock_root / job_id
                try:
                    lock.mkdir()
                except FileExistsError:
                    continue
                if archive.exists() or not run_dir.is_dir():
                    lock.rmdir()
                    continue
                status = json.loads(status_path.read_text())
                result = json.loads(result_json.read_text())
                if status.get("status") != "SUCCESS" or result.get("state") != "SUCCESS":
                    lock.rmdir()
                    continue
                relative = [f"status/jobs/{job_id}.json", f"results/{job_id}", f"runs/{job_id}"]
                worker_log = root / "worker_logs" / f"{job_id}.log"
                if worker_log.exists():
                    relative.append(f"worker_logs/{job_id}.log")
                partial = archive.with_suffix(".tar.gz.partial")
                if partial.exists():
                    partial.unlink()
                subprocess.run(
                    ["tar", "-C", str(root), "-czf", str(partial), *relative],
                    check=True,
                )
                subprocess.run(["tar", "-tzf", str(partial)], check=True, stdout=subprocess.DEVNULL)
                os.replace(partial, archive)
                shutil.rmtree(run_dir)
                for child in list(result_dir.iterdir()):
                    if child.name == "job_result.json":
                        continue
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                if worker_log.exists():
                    worker_log.unlink()
                minimal_result = {
                    "state": "SUCCESS",
                    "job_id": result.get("job_id", job_id),
                    "job_hash": result.get("job_hash"),
                    "protocol_core_sha256": result.get("protocol_core_sha256"),
                    "selected_model_count": result.get("selected_model_count"),
                    "offloaded_to_compact_archive": True,
                }
                result_tmp = result_json.with_suffix(".json.compact_tmp")
                result_tmp.write_text(json.dumps(minimal_result, sort_keys=True) + "\n")
                os.replace(str(result_tmp), str(result_json))
                lock.rmdir()
                with events.open("a") as handle:
                    handle.write(json.dumps({"time": time.time(), "job_id": job_id, "archive_bytes": archive.stat().st_size}) + "\n")
                completed += 1
            except Exception as exc:
                try:
                    lock.rmdir()
                except Exception:
                    pass
                with events.open("a") as handle:
                    handle.write(json.dumps({"time": time.time(), "job_id": job_id, "error": repr(exc)}) + "\n")
        print(json.dumps({"completed_this_pass": completed, "time": time.time()}), flush=True)
        if not args.poll_seconds:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
