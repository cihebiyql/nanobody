#!/usr/bin/env python3
"""Run resumable adaptive-seed dual docking and publish research rankings."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFORMATIONS = ("8x6b", "9e6y")
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
CLAIM = (
    "Adaptive-seed 8X6B/9E6Y computational blocker-like geometry ranking only; "
    "not binding, affinity, competition, experimental blocking, Docking Gold, or formal validation."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"empty_rows:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_scorer(path: Path):
    spec = importlib.util.spec_from_file_location("v4h_docking_scorer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_scorer:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "utility", None)):
        raise RuntimeError("scorer_missing_utility")
    return module


def summarize_job_fixed_top8(result: dict[str, Any], conformation: str, scorer: Any) -> float:
    complete = []
    for pose in result.get("pose_scores", []):
        reference_scores = {
            str(item["reference_id"]).lower(): item for item in pose.get("scores", [])
        }
        if set(reference_scores) == set(CONFORMATIONS):
            complete.append(
                (
                    float((pose.get("haddock_io") or {})["score"]),
                    str(pose.get("pose", "")),
                    reference_scores,
                )
            )
    if len(complete) < 4:
        raise RuntimeError("fewer_than_4_complete_models")
    complete.sort(key=lambda item: (item[0], item[1]))
    complete = complete[:8]
    raw_weights = [1 / math.log2(rank + 1) for rank in range(1, len(complete) + 1)]
    weights = [value / sum(raw_weights) for value in raw_weights]
    score = sum(
        weight * scorer.utility(item[2][conformation])
        for weight, item in zip(weights, complete)
    )
    reliability = 0.5 + 0.5 * min(len(complete) / 8, 1)

    def geometry_class(item: dict[str, Any]) -> str:
        hotspot = float(item["hotspot_overlap"]["full"]["count"])
        occlusion = item["vhh_pvrl2_occlusion"]
        total = float(occlusion["residue_pair_count"])
        cdr3 = float(occlusion["by_vhh_region_pair_count"]["cdr3"])
        fraction = float(occlusion["cdr3_fraction"])
        if hotspot >= 14 and total >= 500 and cdr3 >= 100 and fraction >= 0.15:
            return "A"
        if hotspot >= 14 and total < 50:
            return "C"
        if hotspot >= 10 and total >= 100 and cdr3 >= 20 and fraction >= 0.10:
            return "B"
        return "E"

    other = "9e6y" if conformation == "8x6b" else "8x6b"
    pairs = [
        (geometry_class(item[2][conformation]), geometry_class(item[2][other]))
        for item in complete
    ]
    support = [(left in {"A", "B"}) == (right in {"A", "B"}) for left, right in pairs]
    labels = [
        "STRICT_A"
        if left == right == "A"
        else "SUPPORTED_AB"
        if left in {"A", "B"} and right in {"A", "B"}
        else "OTHER"
        for left, right in pairs
    ]
    agreement = sum(support) / len(support)
    consensus = max(labels.count(label) for label in set(labels)) / len(labels)
    return score * reliability * (0.5 + 0.25 * agreement + 0.25 * consensus)


def job_status(root: Path, job_id: str) -> str:
    path = root / "status" / "jobs" / f"{job_id}.json"
    if not path.is_file():
        return "PENDING"
    return str(json.loads(path.read_text()).get("status", "PENDING")).upper()


def run_job_list(root: Path, path: Path, max_parallel: int, scratch: Path) -> dict[str, object]:
    jobs = read_tsv(path)
    env = {
        **os.environ,
        "PVRIG_PROJECT_ROOT": str(root),
        "PVRIG_LOCAL_SCRATCH_ROOT": str(scratch),
        "HADDOCK3": "/data/qlyu/anaconda3/envs/haddock3/bin/haddock3",
        "PATH": "/data/qlyu/anaconda3/envs/haddock3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONOPTIMIZE": "0",
    }
    command = [
        "/data/qlyu/anaconda3/envs/haddock3/bin/python",
        "scripts/run_controller.py",
        "--job-list",
        str(path.relative_to(root)),
        "--poll-seconds",
        "30",
        "--max-parallel",
        str(max_parallel),
        "--max-attempts",
        "2",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log = root / "logs" / f"{path.stem}.controller.log"
    log.write_text(completed.stdout)
    counts = Counter(job_status(root, row["job_id"]) for row in jobs)
    terminal = counts["SUCCESS"] + counts["FAILED_MAX_ATTEMPTS"]
    if terminal != len(jobs):
        raise RuntimeError(f"job_list_not_terminal:{path.name}:{dict(counts)}")
    payload = {
        "job_list": str(path.relative_to(root)),
        "job_list_sha256": sha256(path),
        "job_count": len(jobs),
        "controller_returncode": completed.returncode,
        "terminal_counts": dict(sorted(counts.items())),
        "completed_at_utc": now(),
    }
    write_json(root / "status" / f"{path.stem}.terminal.json", payload)
    return payload


def verify_smoke(root: Path, scorer: Any) -> dict[str, object]:
    jobs = read_tsv(root / "manifests" / "smoke_jobs.tsv")
    reasons = []
    for row in jobs:
        result_path = root / "results" / row["job_id"] / "job_result.json"
        if job_status(root, row["job_id"]) != "SUCCESS" or not result_path.is_file():
            reasons.append(f"{row['job_id']}:missing_success")
            continue
        result = json.loads(result_path.read_text())
        if str(result.get("state", "")).upper() not in SUCCESS_STATES:
            reasons.append(f"{row['job_id']}:result_state")
            continue
        try:
            summarize_job_fixed_top8(result, row["conformation"], scorer)
        except Exception as error:
            reasons.append(f"{row['job_id']}:scoring:{type(error).__name__}:{error}")
    payload = {
        "status": "PASS" if not reasons else "FAIL",
        "job_count": len(jobs),
        "reasons": reasons,
        "verified_at_utc": now(),
        "claim_boundary": CLAIM,
    }
    write_json(root / "reports" / "RESEARCH_SMOKE_VALIDATION.json", payload)
    if reasons:
        raise RuntimeError(f"research_smoke_failed:{reasons}")
    return payload


def rank_candidates(root: Path, scorer: Any, label: str) -> list[dict[str, object]]:
    candidates = read_tsv(root / "inputs" / "candidates_290.tsv")
    by_id = {row["candidate_id"]: row for row in candidates}
    jobs = [row for row in read_tsv(root / "manifests" / "docking_jobs.tsv") if row["entity_type"] == "candidate"]
    scores: dict[str, dict[str, list[tuple[int, float]]]] = defaultdict(lambda: defaultdict(list))
    failures: dict[str, list[str]] = defaultdict(list)
    for job in jobs:
        status = job_status(root, job["job_id"])
        if status == "PENDING":
            continue
        if status != "SUCCESS":
            failures[job["entity_id"]].append(f"{job['conformation']}:s{job['seed']}:{status}")
            continue
        result_path = root / "results" / job["job_id"] / "job_result.json"
        if not result_path.is_file():
            failures[job["entity_id"]].append(f"{job['conformation']}:s{job['seed']}:RESULT_MISSING")
            continue
        try:
            result = json.loads(result_path.read_text())
            value = float(summarize_job_fixed_top8(result, job["conformation"], scorer))
            if not math.isfinite(value):
                raise ValueError("nonfinite")
            scores[job["entity_id"]][job["conformation"]].append((int(job["seed"]), value))
        except Exception as error:
            failures[job["entity_id"]].append(
                f"{job['conformation']}:s{job['seed']}:SCORING:{type(error).__name__}:{error}"
            )

    rows: list[dict[str, object]] = []
    for candidate_id, candidate in by_id.items():
        by_conf = scores[candidate_id]
        counts = {conf: len(by_conf[conf]) for conf in CONFORMATIONS}
        analyzable = all(counts[conf] >= 1 for conf in CONFORMATIONS)
        medians = {
            conf: statistics.median(value for _, value in by_conf[conf])
            for conf in CONFORMATIONS
            if counts[conf]
        }
        min_seed_count = min(counts.values()) if analyzable else 0
        raw = min(medians.values()) if analyzable else None
        confidence_factor = {0: 0.0, 1: 0.80, 2: 0.90}.get(min_seed_count, 1.0)
        dispersion = max(
            (
                statistics.pstdev(value for _, value in by_conf[conf])
                for conf in CONFORMATIONS
                if counts[conf] >= 2
            ),
            default=0.0,
        )
        rows.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": candidate["sequence_sha256"],
                "parent_framework_cluster": candidate["parent_framework_cluster"],
                "target_patch_id": candidate["target_patch_id"],
                "design_mode": candidate["design_mode"],
                "docking_evidence_tier": f"DUAL_{min_seed_count}_SEED" if analyzable else "TECHNICAL_INCOMPLETE",
                "successful_seed_count_8X6B": counts["8x6b"],
                "successful_seed_ids_8X6B": ",".join(str(seed) for seed, _ in sorted(by_conf["8x6b"])),
                "successful_seed_count_9E6Y": counts["9e6y"],
                "successful_seed_ids_9E6Y": ",".join(str(seed) for seed, _ in sorted(by_conf["9e6y"])),
                "median_score_8X6B": f"{medians['8x6b']:.9f}" if "8x6b" in medians else "",
                "median_score_9E6Y": f"{medians['9e6y']:.9f}" if "9e6y" in medians else "",
                "R_dual_min": f"{raw:.9f}" if raw is not None else "",
                "seed_dispersion_max": f"{dispersion:.9f}" if analyzable else "",
                "confidence_adjusted_score": f"{raw * confidence_factor:.9f}" if raw is not None else "",
                "technical_reasons": ";".join(failures[candidate_id]),
                "ranking_release": label,
                "claim_boundary": CLAIM,
            }
        )
    rows.sort(
        key=lambda row: (
            -int(str(row["docking_evidence_tier"]).split("_")[1])
            if str(row["docking_evidence_tier"]).startswith("DUAL_")
            else 1,
            -float(row["confidence_adjusted_score"] or -1),
            str(row["candidate_id"]),
        )
    )
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    write_tsv(root / "release" / f"{label}_ranking.tsv", rows)
    return rows


def diversity_select(rows: list[dict[str, object]], count: int) -> list[dict[str, object]]:
    eligible = [row for row in rows if row["R_dual_min"] != ""]
    if len(eligible) < count:
        raise RuntimeError(f"insufficient_analyzable_candidates:{len(eligible)}:{count}")
    parents = sorted({str(row["parent_framework_cluster"]) for row in eligible})
    minimum_per_parent = max(1, count // (2 * len(parents)))
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    for parent in parents:
        for row in [item for item in eligible if item["parent_framework_cluster"] == parent][
            :minimum_per_parent
        ]:
            selected.append(row)
            selected_ids.add(str(row["candidate_id"]))
    parent_cap = math.ceil(count / len(parents) * 1.5)
    patch_cap = math.ceil(count / 3 * 1.3)
    mode_cap = math.ceil(count / 2 * 1.2)
    parent_counts = Counter(str(row["parent_framework_cluster"]) for row in selected)
    patch_counts = Counter(str(row["target_patch_id"]) for row in selected)
    mode_counts = Counter(str(row["design_mode"]) for row in selected)
    for row in eligible:
        if len(selected) >= count:
            break
        candidate_id = str(row["candidate_id"])
        parent = str(row["parent_framework_cluster"])
        patch = str(row["target_patch_id"])
        mode = str(row["design_mode"])
        if candidate_id in selected_ids:
            continue
        if parent_counts[parent] >= parent_cap or patch_counts[patch] >= patch_cap or mode_counts[mode] >= mode_cap:
            continue
        selected.append(row)
        selected_ids.add(candidate_id)
        parent_counts[parent] += 1
        patch_counts[patch] += 1
        mode_counts[mode] += 1
    if len(selected) < count:
        for row in eligible:
            if len(selected) >= count:
                break
            if str(row["candidate_id"]) not in selected_ids:
                selected.append(row)
                selected_ids.add(str(row["candidate_id"]))
    return selected[:count]


def write_selected_job_list(
    root: Path, selected: list[dict[str, object]], seed: int, name: str
) -> Path:
    selected_ids = {str(row["candidate_id"]) for row in selected}
    jobs = [
        row
        for row in read_tsv(root / "manifests" / "docking_jobs.tsv")
        if row["entity_type"] == "candidate"
        and row["entity_id"] in selected_ids
        and int(row["seed"]) == seed
    ]
    if len(jobs) != len(selected_ids) * 2:
        raise RuntimeError(f"selected_job_shape:{name}:{len(jobs)}:{len(selected_ids)}")
    path = root / "manifests" / name
    write_tsv(path, jobs)
    write_tsv(root / "release" / f"{Path(name).stem}_candidates.tsv", selected)
    return path


def run(root: Path, scorer_path: Path, max_parallel: int, stage2_count: int, stage3_count: int) -> dict[str, object]:
    scorer = load_scorer(scorer_path)
    scratch = Path(f"/tmp/{root.name}")
    scratch.mkdir(parents=True, exist_ok=True)
    if "nfs" in subprocess.check_output(["stat", "-f", "-c", "%T", str(scratch)], text=True).lower():
        raise RuntimeError("scratch_on_nfs")
    smoke_terminal = run_job_list(root, root / "manifests" / "smoke_jobs.tsv", min(4, max_parallel), scratch)
    smoke = verify_smoke(root, scorer)

    stage1_path = root / "manifests" / "stage1_all_seed917.tsv"
    stage1_terminal = run_job_list(root, stage1_path, max_parallel, scratch)
    stage1_rows = rank_candidates(root, scorer, "stage1_seed917")
    stage1_analyzable = sum(row["R_dual_min"] != "" for row in stage1_rows)
    stage2_selected = diversity_select(stage1_rows, min(stage2_count, stage1_analyzable))
    stage2_path = write_selected_job_list(root, stage2_selected, 1931, "stage2_selected_seed1931.tsv")
    stage2_terminal = run_job_list(root, stage2_path, max_parallel, scratch)
    stage2_rows = rank_candidates(root, scorer, "stage2_seed917_1931")
    stage2_ids = {str(row["candidate_id"]) for row in stage2_selected}
    stage3_source = [row for row in stage2_rows if str(row["candidate_id"]) in stage2_ids]
    stage2_analyzable = sum(row["R_dual_min"] != "" for row in stage3_source)
    stage3_selected = diversity_select(stage3_source, min(stage3_count, stage2_analyzable))
    stage3_path = write_selected_job_list(root, stage3_selected, 3253, "stage3_selected_seed3253.tsv")
    stage3_terminal = run_job_list(root, stage3_path, max_parallel, scratch)
    final_rows = rank_candidates(root, scorer, "final_adaptive_seed")

    payload = {
        "schema_version": "phase2_v4_h_research_adaptive_docking_terminal_v1",
        "status": "PASS_ADAPTIVE_DUAL_DOCKING_TERMINAL_WITH_EXPLICIT_TECHNICAL_STATES",
        "candidate_count": len(final_rows),
        "stage2_selected_count": len(stage2_selected),
        "stage3_selected_count": len(stage3_selected),
        "final_ranking_sha256": sha256(root / "release" / "final_adaptive_seed_ranking.tsv"),
        "smoke": smoke,
        "terminals": {
            "smoke": smoke_terminal,
            "stage1": stage1_terminal,
            "stage2": stage2_terminal,
            "stage3": stage3_terminal,
        },
        "completed_at_utc": now(),
        "claim_boundary": CLAIM,
    }
    write_json(root / "release" / "ADAPTIVE_DOCKING_RECEIPT.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--scorer", type=Path, required=True)
    parser.add_argument("--max-parallel", type=int, default=12)
    parser.add_argument("--stage2-count", type=int, default=384)
    parser.add_argument("--stage3-count", type=int, default=128)
    args = parser.parse_args()
    lock_path = args.root / "status" / "adaptive_orchestrator.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("adaptive_orchestrator_already_active")
        print(
            json.dumps(
                run(
                    args.root.resolve(),
                    args.scorer.resolve(),
                    args.max_parallel,
                    args.stage2_count,
                    args.stage3_count,
                ),
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
