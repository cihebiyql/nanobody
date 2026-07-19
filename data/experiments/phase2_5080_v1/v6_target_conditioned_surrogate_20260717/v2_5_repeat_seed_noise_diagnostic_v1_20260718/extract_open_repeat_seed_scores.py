#!/usr/bin/env python3
"""Extract open-development repeat-seed scalar geometry from raw job results.

This script deliberately opens only preselected candidate job_result.json files.
It does not train or evaluate a surrogate and does not touch V4-F/test32.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


CONFS = ("8x6b", "9e6y")
SUCCESS = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
CLAIM = (
    "Open-development repeated-seed computational dual-receptor docking geometry only; "
    "not binding, affinity, competition, experimental blocking, Docking Gold, or validation truth."
)
IMPLEMENTATION_VERSION = "v1_2_terminal_declared_v4h_success_seed_allowlist"


class ExtractionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ExtractionError("refusing_empty_output")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ExtractionError(f"cannot_load_module:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def soft_scale(value: float, threshold: float) -> float:
    if value < 0 or threshold <= 0:
        raise ExtractionError("invalid_soft_scale_input")
    return value / (value + threshold)


def nested(value: Mapping[str, Any], *keys: str) -> Any:
    out: Any = value
    for key in keys:
        if not isinstance(out, Mapping) or key not in out:
            raise ExtractionError(f"missing_nested_metric:{'.'.join(keys)}")
        out = out[key]
    return out


def v4d_pose_row(pose: Mapping[str, Any], score: Mapping[str, Any]) -> dict[str, Any]:
    clashes = nested(score, "clashes_2p5a")
    haddock = pose.get("haddock_io") or {}
    return {
        "model": Path(str(pose.get("pose", ""))).name,
        "haddock_score": float(haddock["score"]),
        "hotspot_overlap": float(nested(score, "hotspot_overlap", "full", "count")),
        "holdout_overlap": float(nested(score, "hotspot_overlap", "holdout", "count")),
        "total_occlusion": float(nested(score, "vhh_pvrl2_occlusion", "residue_pair_count")),
        "cdr3_occlusion": float(nested(score, "vhh_pvrl2_occlusion", "by_vhh_region_pair_count", "cdr3")),
        "cdr3_fraction": float(nested(score, "vhh_pvrl2_occlusion", "cdr3_fraction")),
        "vhh_pvrig_clash_residue_pairs": float(nested(clashes, "vhh_pvrig", "residue_pair_count")),
        "overlay_rmsd_a": float(nested(score, "overlay", "t_ca_rmsd_a")),
    }


def v4d_pose_utility(row: Mapping[str, Any]) -> float:
    if float(row["overlay_rmsd_a"]) > 1.0:
        raise ExtractionError(f"native_overlay_rmsd_above_1A:{row['overlay_rmsd_a']}")
    base = (
        0.15 * min(max(float(row["hotspot_overlap"]) / 23.0, 0.0), 1.0)
        + 0.25 * min(max(float(row["holdout_overlap"]) / 11.0, 0.0), 1.0)
        + 0.25 * soft_scale(float(row["total_occlusion"]), 500.0)
        + 0.20 * soft_scale(float(row["cdr3_occlusion"]), 100.0)
        + 0.15 * soft_scale(float(row["cdr3_fraction"]), 0.15)
    )
    return base / (1.0 + float(row["vhh_pvrig_clash_residue_pairs"]) / 5.0)


def geometry_class(row: Mapping[str, Any]) -> str:
    h, o, c, f = (float(row[k]) for k in ("hotspot_overlap", "total_occlusion", "cdr3_occlusion", "cdr3_fraction"))
    if h >= 14 and o >= 500 and c >= 100 and f >= 0.15:
        return "A"
    if h >= 14 and o < 50:
        return "C"
    if h >= 10 and o >= 100 and c >= 20 and f >= 0.10:
        return "B"
    return "E"


def rank_weights(n: int) -> list[float]:
    raw = [1.0 / math.log2(rank + 1.0) for rank in range(1, n + 1)]
    total = sum(raw)
    return [x / total for x in raw]


def score_v4d(raw: Mapping[str, Any], conformation: str) -> float:
    by_model: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for pose in raw.get("pose_scores", []):
        for score in pose.get("scores", []):
            ref = str(score.get("reference_id", "")).lower()
            if ref in CONFS:
                row = v4d_pose_row(pose, score)
                by_model[row["model"]][ref] = row
    complete = [refs for refs in by_model.values() if set(refs) == set(CONFS)]
    if len(complete) < 4:
        raise ExtractionError("v4d_fewer_than_4_complete_models")
    # V4-E's frozen retrospective method excludes native-overlay-invalid model
    # pairs before the per-job rank-weighted utility is calculated.
    complete = [refs for refs in complete if float(refs[conformation]["overlay_rmsd_a"]) <= 1.0]
    if len(complete) < 4:
        raise ExtractionError("v4d_fewer_than_4_models_after_native_overlay_qc")
    complete.sort(key=lambda refs: (float(refs[conformation]["haddock_score"]), str(refs[conformation]["model"])))
    weights = rank_weights(len(complete))
    other = "9e6y" if conformation == "8x6b" else "8x6b"
    native_classes = [geometry_class(refs[conformation]) for refs in complete]
    cross_classes = [geometry_class(refs[other]) for refs in complete]
    labels = ["STRICT_A" if a == b == "A" else "SUPPORTED_AB" if a in {"A", "B"} and b in {"A", "B"} else "OTHER" for a, b in zip(native_classes, cross_classes)]
    agreement = statistics.mean((a in {"A", "B"}) == (b in {"A", "B"}) for a, b in zip(native_classes, cross_classes))
    consensus = max(labels.count(x) for x in set(labels)) / len(labels)
    raw_score = sum(w * v4d_pose_utility(refs[conformation]) for w, refs in zip(weights, complete))
    return raw_score * (0.5 + 0.5 * min(len(complete) / 8.0, 1.0)) * (0.5 + 0.25 * agreement + 0.25 * consensus)


def extract(
    campaign: str,
    root: Path,
    output_dir: Path,
    adaptive_script: Path | None,
    scorer_script: Path | None,
) -> dict[str, Any]:
    candidates_path = root / "inputs" / "fullqc290_split_manifest.tsv"
    jobs_path = root / "manifests" / "docking_jobs.tsv"
    candidates = read_tsv(candidates_path)
    if campaign == "v4d":
        allowed_rows = [row for row in candidates if row.get("model_split") == "OPEN_TRAIN"]
        if len(allowed_rows) != 226:
            raise ExtractionError(f"v4d_open_train_count:{len(allowed_rows)}")
        scorer: Callable[[Mapping[str, Any], str], float] = score_v4d
        required_seed_count = 2
        declared_success_seeds: dict[tuple[str, str], set[int]] | None = None
    else:
        ranking_path = root / "release" / "final_adaptive_seed_ranking.tsv"
        ranking = read_tsv(ranking_path)
        repeated = {
            row["candidate_id"]
            for row in ranking
            if min(int(row["successful_seed_count_8X6B"]), int(row["successful_seed_count_9E6Y"])) >= 2
        }
        declared_success_seeds = {}
        for row in ranking:
            if row["candidate_id"] not in repeated:
                continue
            declared_success_seeds[(row["candidate_id"], "8x6b")] = {
                int(value) for value in row["successful_seed_ids_8X6B"].split(",") if value
            }
            declared_success_seeds[(row["candidate_id"], "9e6y")] = {
                int(value) for value in row["successful_seed_ids_9E6Y"].split(",") if value
            }
        allowed_rows = [row for row in candidates if row["candidate_id"] in repeated]
        if len(allowed_rows) != 364:
            raise ExtractionError(f"v4h_repeat_candidate_count:{len(allowed_rows)}")
        if adaptive_script is None or scorer_script is None:
            raise ExtractionError("v4h_requires_adaptive_and_scorer_scripts")
        adaptive = load_module(adaptive_script, "v4h_adaptive_extract")
        scorer_module = load_module(scorer_script, "v4h_scorer_extract")
        scorer = lambda raw, conf: float(adaptive.summarize_job_fixed_top8(raw, conf, scorer_module))
        required_seed_count = 2

    allowed = {row["candidate_id"]: row for row in allowed_rows}
    selected_jobs = [
        row for row in read_tsv(jobs_path)
        if row.get("entity_type") == "candidate" and row.get("entity_id") in allowed
        and (
            declared_success_seeds is None
            or int(row["seed"]) in declared_success_seeds[(row["entity_id"], row["conformation"])]
        )
    ]
    rows: list[dict[str, Any]] = []
    raw_bindings: list[dict[str, str]] = []
    for job in selected_jobs:
        path = root / "results" / job["job_id"] / "job_result.json"
        if not path.is_file():
            continue
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes)
        if str(raw.get("state", "")).upper() not in SUCCESS:
            continue
        if raw.get("job_id") != job["job_id"] or raw.get("job_hash") != job["job_hash"]:
            raise ExtractionError(f"job_identity_hash_mismatch:{job['job_id']}")
        for key in ("entity_id", "conformation", "seed"):
            raw_key = "dock_conformation" if key == "conformation" else key
            expected = job["entity_id"] if key == "entity_id" else job[key]
            if str(raw.get(raw_key, "")).lower() != str(expected).lower():
                raise ExtractionError(f"raw_identity_mismatch:{job['job_id']}:{key}")
        value = float(scorer(raw, job["conformation"]))
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ExtractionError(f"score_invalid:{job['job_id']}:{value}")
        result_sha = hashlib.sha256(raw_bytes).hexdigest()
        candidate = allowed[job["entity_id"]]
        rows.append({
            "schema_version": "pvrig_v2_5_open_repeat_seed_scalar_v1",
            "campaign": campaign.upper(),
            "candidate_id": job["entity_id"],
            "sequence_sha256": candidate["sequence_sha256"],
            "parent_framework_cluster": candidate["parent_framework_cluster"],
            "target_patch_id": candidate["target_patch_id"],
            "design_mode": candidate["design_mode"],
            "receptor": job["conformation"],
            "seed": int(job["seed"]),
            "score": f"{value:.12g}",
            "job_id": job["job_id"],
            "job_hash": job["job_hash"],
            "job_result_sha256": result_sha,
            "protocol_core_sha256": job["protocol_core_sha256"],
            "claim_boundary": CLAIM,
        })
        raw_bindings.append({"job_id": job["job_id"], "sha256": result_sha})

    keys = [(row["candidate_id"], row["receptor"], row["seed"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ExtractionError("duplicate_candidate_receptor_seed")
    by_candidate: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        by_candidate[row["candidate_id"]][row["receptor"]].add(int(row["seed"]))
    eligible = {
        cid for cid, by_conf in by_candidate.items()
        if set(by_conf) == set(CONFS) and len(by_conf["8x6b"] & by_conf["9e6y"]) >= required_seed_count
    }
    if set(allowed) != eligible:
        missing = sorted(set(allowed) - eligible)[:10]
        raise ExtractionError(f"candidate_repeat_closure_failed:{len(eligible)}:{missing}")
    rows.sort(key=lambda row: (row["campaign"], row["candidate_id"], row["seed"], row["receptor"]))
    out = output_dir / f"{campaign}_open_repeat_seed_scores.tsv"
    write_tsv(out, rows)
    binding_canonical = json.dumps(sorted(raw_bindings, key=lambda x: x["job_id"]), separators=(",", ":"), sort_keys=True)
    receipt = {
        "schema_version": "pvrig_v2_5_open_repeat_seed_extraction_receipt_v1",
        "implementation_version": IMPLEMENTATION_VERSION,
        "status": "PASS_OPEN_REPEAT_SEED_EXTRACTION",
        "campaign": campaign.upper(),
        "candidate_count": len(eligible),
        "score_row_count": len(rows),
        "source_root": str(root.resolve()),
        "source_candidates_sha256": sha256_file(candidates_path),
        "source_jobs_sha256": sha256_file(jobs_path),
        "output_sha256": sha256_file(out),
        "raw_job_result_binding_sha256": hashlib.sha256(binding_canonical.encode()).hexdigest(),
        "non_open_v4d_candidate_results_accessed": 0,
        "v4_f_or_test32_results_accessed": 0,
        "claim_boundary": CLAIM,
    }
    receipt_path = output_dir / f"{campaign}_open_repeat_seed_scores.receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--campaign", choices=("v4d", "v4h"), required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--adaptive-script", type=Path)
    p.add_argument("--scorer-script", type=Path)
    a = p.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps(extract(a.campaign, a.root.resolve(), a.output_dir.resolve(), a.adaptive_script, a.scorer_script), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
