#!/usr/bin/env python3
"""Status-check or execute an authorized V2.4 nested cross-fit DAG.

Execution is fail-closed: a pre-calibration dry-run graph, a null command, a
sealed V4-F/test32 token, an unknown dependency, a cycle, or a pre-existing
partial output blocks launch.  This file is not invoked by local tests with
``--execute`` and does not inspect prediction metrics.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "pvrig_v2_4_strict_double_whole_parent_crossfit_plan_v1"
AUTHORIZATION = "I_ACCEPT_OPEN_DEVELOPMENT_TRAINING"
GPU_KINDS = {"GPU_BASE_TRAIN_INNER", "GPU_BASE_REFIT_OUTER_TRAIN"}
V4F = re.compile(r"(^|[/\\._-])v4[/\\._-]?f($|[/\\._-])|test32", re.I)


class GraphExecutionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GraphExecutionError(message)


def load_graph(path: Path) -> dict[str, Any]:
    require(not V4F.search(str(path.resolve())), f"sealed_graph_path:{path}")
    graph = json.loads(path.read_text(encoding="utf-8"))
    require(graph.get("schema_version") == SCHEMA, "graph_schema")
    require(graph.get("sealed_evaluation_access_count") == 0, "sealed_access_nonzero")
    require(graph.get("prediction_metrics_access_count") == 0, "prediction_metrics_access_nonzero")
    require(not V4F.search(json.dumps(graph).lower()), "sealed_token_in_graph")
    jobs = graph.get("jobs")
    require(isinstance(jobs, list) and jobs, "jobs_missing")
    ids = [job.get("job_id") for job in jobs]
    require(all(isinstance(value, str) and value for value in ids), "job_id_invalid")
    require(len(ids) == len(set(ids)), "job_id_duplicate")
    known = set(ids)
    for job in jobs:
        require(set(job.get("dependencies") or []).issubset(known), f"unknown_dependency:{job['job_id']}")
        require(isinstance(job.get("expected_result"), str) and job["expected_result"], f"expected_result_missing:{job['job_id']}")
    pending = {job["job_id"]: set(job["dependencies"]) for job in jobs}
    resolved: set[str] = set()
    while pending:
        ready = {jid for jid, deps in pending.items() if deps <= resolved}
        require(bool(ready), "job_graph_cycle")
        resolved.update(ready)
        pending = {jid: deps for jid, deps in pending.items() if jid not in ready}
    return graph


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_execution_artifacts(graph: Mapping[str, Any]) -> None:
    artifacts = list((graph.get("code_contracts") or {}).values())
    artifacts.extend(graph["canonical_inputs"][name] for name in ("training_tsv", "outer_manifest", "inner_manifest", "contact_formula"))
    artifacts.extend(graph["split_manifests"].values())
    require(bool(artifacts), "execution_artifact_contract_empty")
    for artifact in artifacts:
        path = Path(str(artifact.get("node1_path", "")))
        require(path.is_file(), f"execution_artifact_missing:{path}")
        require(sha256_file(path) == artifact.get("sha256"), f"execution_artifact_hash:{path}")


def status(graph: Mapping[str, Any]) -> dict[str, Any]:
    states = Counter()
    for job in graph["jobs"]:
        result = Path(job["expected_result"])
        if result.is_file():
            states["COMPLETE_ARTIFACT_PRESENT"] += 1
        elif result.exists():
            states["BLOCKED_EXPECTED_RESULT_NOT_REGULAR_FILE"] += 1
        else:
            states["PENDING"] += 1
    return {
        "status": "PASS_GRAPH_STATUS_ONLY_NO_EXECUTION",
        "graph_status": graph["status"],
        "execution_authorized": graph["execution_authorized"],
        "job_count": len(graph["jobs"]),
        "job_states": dict(sorted(states.items())),
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
    }


def run_one(job: Mapping[str, Any], log_root: Path) -> dict[str, Any]:
    command = job.get("command")
    require(isinstance(command, list) and command and all(isinstance(v, str) and v for v in command), f"command_not_frozen:{job['job_id']}")
    output = Path(job["expected_result"])
    require(not output.exists(), f"expected_result_preexists:{job['job_id']}:{output}")
    if job["kind"] in GPU_KINDS:
        require(not output.parent.exists() or not any(output.parent.iterdir()), f"partial_output_directory:{job['job_id']}:{output.parent}")
    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"{job['job_id'].replace('/', '_')}.log"
    require(not log_path.exists(), f"log_preexists:{log_path}")
    env = os.environ.copy()
    env.update({
        "OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "8",
        "NUMEXPR_NUM_THREADS": "8", "TOKENIZERS_PARALLELISM": "false",
    })
    if job["kind"] in GPU_KINDS:
        env["CUDA_VISIBLE_DEVICES"] = str(job["physical_gpu"])
    started = time.time()
    with log_path.open("x", encoding="utf-8") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, check=False)
    require(completed.returncode == 0, f"job_failed:{job['job_id']}:{completed.returncode}:{log_path}")
    require(output.is_file(), f"expected_result_missing_after_success:{job['job_id']}:{output}")
    return {"job_id": job["job_id"], "elapsed_seconds": time.time() - started, "log_path": str(log_path)}


def execute(graph: Mapping[str, Any], authorization: str, log_root: Path, max_cpu_jobs: int) -> dict[str, Any]:
    require(graph.get("execution_authorized") is True, "graph_not_execution_authorized")
    require(graph.get("status") == "READY_EXECUTABLE_POSTCALIBRATION_FREEZE", "graph_status_not_ready")
    require(authorization == AUTHORIZATION, "explicit_execution_authorization_token_required")
    require(max_cpu_jobs > 0, "max_cpu_jobs")
    validate_execution_artifacts(graph)
    jobs = {job["job_id"]: job for job in graph["jobs"]}
    complete = {jid for jid, item in jobs.items() if Path(item["expected_result"]).is_file()}
    pending = set(jobs) - complete
    running: dict[concurrent.futures.Future, str] = {}
    busy_gpus: set[int] = set()
    running_cpu = 0
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3 + max_cpu_jobs) as pool:
        while pending or running:
            launched = False
            for jid in sorted(pending):
                item = jobs[jid]
                if not set(item["dependencies"]) <= complete:
                    continue
                if item["kind"] in GPU_KINDS:
                    gpu = int(item["physical_gpu"])
                    if gpu in busy_gpus:
                        continue
                    busy_gpus.add(gpu)
                else:
                    if running_cpu >= max_cpu_jobs:
                        continue
                    running_cpu += 1
                future = pool.submit(run_one, item, log_root)
                running[future] = jid
                pending.remove(jid)
                launched = True
            if not running:
                require(not pending, "scheduler_deadlock")
                break
            if not launched or len(running) >= 3 + max_cpu_jobs:
                done, _ = concurrent.futures.wait(running, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    jid = running.pop(future)
                    item = jobs[jid]
                    try:
                        result = future.result()
                    finally:
                        if item["kind"] in GPU_KINDS:
                            busy_gpus.discard(int(item["physical_gpu"]))
                        else:
                            running_cpu -= 1
                    results.append(result)
                    complete.add(jid)
    return {
        "status": "PASS_AUTHORIZED_GRAPH_EXECUTION_COMPLETE",
        "completed_job_count": len(complete),
        "newly_executed_job_count": len(results),
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-graph", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--authorization-token", default="")
    parser.add_argument("--log-root", type=Path)
    parser.add_argument("--max-cpu-jobs", type=int, default=3)
    args = parser.parse_args()
    graph = load_graph(args.job_graph.resolve())
    if args.status:
        result = status(graph)
    else:
        require(args.log_root is not None, "log_root_required")
        result = execute(graph, args.authorization_token, args.log_root.resolve(), args.max_cpu_jobs)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
