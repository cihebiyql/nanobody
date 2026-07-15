#!/usr/bin/env python3
"""Build continuous V4-C teacher rows from a fresh dual-docking aggregate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "phase2_v4_c_continuous_teacher_v1"
EXPECTED_JOB_MANIFEST_SHA256 = "e159027b23e76b041a02f3034a204379053f9d0780e2f8bdfc599d431c1a425e"
EXPECTED_SPLIT_MANIFEST_SHA256 = "4660260cdf1f863281b12200aeee4b5d58b251ebd3774befae2eace9ca2465fe"
EXPECTED_CANDIDATES_SHA256 = "5e536f7178cb214102aef684c65fc97b4996d3b83de5b6f506ad2f9bf8e66c78"
EXPECTED_PROTOCOL_CORE_SHA256 = "e027143c22712b43d973709b278519a0cf414a9de182e094ea0cd8470d8295b8"
EXPECTED_PROTOCOL_LOCK_SHA256 = "6ea729edc9b070bba7271bea3c64da0fffad46921ea8899548eb9b1ad8a120a7"
EXPECTED_STABILITY_SPEC_SHA256 = "1370e47f5826528ec8e39cf1ca9e2407e8da3583e5926b2fa5ad726e78df62f4"
EXPECTED_TOTAL_JOBS = 1050
CONFORMATIONS = ("8x6b", "9e6y")
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
CLAIM_BOUNDARY = (
    "Fixed-PVRIG sequence-to-computational-dual-docking continuous teacher only; "
    "not binding, affinity, competition, experimental blocking, or Docking Gold."
)


class TeacherBuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_tsv_for_entities(path: Path, allowed_entities: set[str]) -> list[dict[str, str]]:
    """Stream a mixed aggregate and retain only preselected entity rows."""
    output = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if "entity_id" not in (reader.fieldnames or []):
            raise TeacherBuildError(f"entity_id_missing:{path}")
        for row in reader:
            if row["entity_id"] in allowed_entities:
                output.append(row)
    return output


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise TeacherBuildError("refusing_to_write_empty_teacher")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def as_float(value: Any, *, field: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise TeacherBuildError(f"invalid_float:{field}:{value!r}") from exc
    if not math.isfinite(output):
        raise TeacherBuildError(f"non_finite_float:{field}:{value!r}")
    return output


def soft_scale(value: float, threshold: float) -> float:
    if value < 0.0 or threshold <= 0.0:
        raise TeacherBuildError("soft_scale_requires_nonnegative_value_and_positive_threshold")
    return value / (value + threshold)


def native_pose_utility(row: Mapping[str, Any]) -> float:
    as_float(row.get("haddock_score"), field="haddock_score")
    as_float(row.get("air_energy"), field="air_energy")
    overlay_rmsd = as_float(row.get("overlay_rmsd_a"), field="overlay_rmsd_a")
    if overlay_rmsd > 1.0:
        raise TeacherBuildError(f"native_overlay_rmsd_above_1A:{overlay_rmsd}")
    full_hotspot = as_float(row.get("hotspot_overlap"), field="hotspot_overlap")
    holdout_hotspot = as_float(row.get("holdout_overlap"), field="holdout_overlap")
    total_occlusion = as_float(row.get("total_occlusion"), field="total_occlusion")
    cdr3_occlusion = as_float(row.get("cdr3_occlusion"), field="cdr3_occlusion")
    cdr3_fraction = as_float(row.get("cdr3_fraction"), field="cdr3_fraction")
    base_score = (
        0.15 * min(max(full_hotspot / 23.0, 0.0), 1.0)
        + 0.25 * min(max(holdout_hotspot / 11.0, 0.0), 1.0)
        + 0.25 * soft_scale(total_occlusion, 500.0)
        + 0.20 * soft_scale(cdr3_occlusion, 100.0)
        + 0.15 * soft_scale(cdr3_fraction, 0.15)
    )
    pvrig_clashes = as_float(
        row.get("vhh_pvrig_clash_residue_pairs"),
        field="vhh_pvrig_clash_residue_pairs",
    )
    clash_reliability = 1.0 / (1.0 + pvrig_clashes / 5.0)
    score = base_score * clash_reliability
    if not 0.0 <= score <= 1.0:
        raise TeacherBuildError(f"pose_utility_out_of_bounds:{score}")
    return score


def rank_weights(count: int) -> list[float]:
    if count < 1:
        raise TeacherBuildError("rank_weights_requires_positive_count")
    raw = [1.0 / math.log2(rank + 1.0) for rank in range(1, count + 1)]
    total = sum(raw)
    return [value / total for value in raw]


def mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        raise TeacherBuildError("mean_requires_values")
    return sum(values) / len(values)


def nested_metric(payload: Mapping[str, Any], *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise TeacherBuildError(f"raw_pose_metric_missing:{'.'.join(path)}")
        value = value[key]
    return value


def raw_pose_rows_for_jobs(
    results_root: Path,
    selected_jobs: list[dict[str, str]],
    successful_job_ids: set[str],
) -> tuple[list[dict[str, str]], str]:
    """Open only result JSON files belonging to the preselected development IDs."""
    output: list[dict[str, str]] = []
    evidence_bindings: list[tuple[str, str]] = []
    for job in selected_jobs:
        job_id = job["job_id"]
        if job_id not in successful_job_ids:
            continue
        path = results_root / job_id / "job_result.json"
        if not path.is_file():
            raise TeacherBuildError(f"selected_success_job_result_missing:{job_id}")
        raw = path.read_bytes()
        evidence_bindings.append((job_id, hashlib.sha256(raw).hexdigest()))
        evidence = json.loads(raw)
        if evidence.get("job_id") != job_id or evidence.get("job_hash") != job.get("job_hash"):
            raise TeacherBuildError(f"raw_job_identity_or_hash_mismatch:{job_id}")
        if evidence.get("protocol_core_sha256") != EXPECTED_PROTOCOL_CORE_SHA256:
            raise TeacherBuildError(f"raw_job_protocol_core_mismatch:{job_id}")
        for pose in evidence.get("pose_scores", []):
            model = Path(str(pose.get("pose", ""))).name
            if not model:
                raise TeacherBuildError(f"raw_pose_model_missing:{job_id}")
            haddock = pose.get("haddock_io") or {}
            for score in pose.get("scores", []):
                reference = str(score.get("reference_id", "")).lower()
                if reference not in CONFORMATIONS:
                    raise TeacherBuildError(f"raw_pose_reference_invalid:{job_id}:{reference}")
                clashes = nested_metric(score, "clashes_2p5a")
                output.append(
                    {
                        "job_id": job_id,
                        "model": model,
                        "scoring_reference": reference,
                        "haddock_score": str(haddock.get("score", "")),
                        "air_energy": str(haddock.get("unw_energies.air", "")),
                        "hotspot_overlap": str(nested_metric(score, "hotspot_overlap", "full", "count")),
                        "anchor_overlap": str(nested_metric(score, "hotspot_overlap", "anchor", "count")),
                        "holdout_overlap": str(nested_metric(score, "hotspot_overlap", "holdout", "count")),
                        "total_occlusion": str(nested_metric(score, "vhh_pvrl2_occlusion", "residue_pair_count")),
                        "cdr3_occlusion": str(
                            nested_metric(
                                score,
                                "vhh_pvrl2_occlusion",
                                "by_vhh_region_pair_count",
                                "cdr3",
                            )
                        ),
                        "cdr3_fraction": str(nested_metric(score, "vhh_pvrl2_occlusion", "cdr3_fraction")),
                        "vhh_pvrig_clash_residue_pairs": str(
                            nested_metric(clashes, "vhh_pvrig", "residue_pair_count")
                        ),
                        "vhh_pvrl2_clash_residue_pairs": str(
                            nested_metric(clashes, "vhh_pvrl2", "residue_pair_count")
                        ),
                        "overlay_rmsd_a": str(nested_metric(score, "overlay", "t_ca_rmsd_a")),
                    }
                )
    binding_payload = json.dumps(sorted(evidence_bindings), separators=(",", ":"))
    return output, hashlib.sha256(binding_payload.encode("utf-8")).hexdigest()


def job_summary(
    job_id: str,
    dock_conformation: str,
    pose_rows: list[dict[str, str]],
    job_result: Mapping[str, str],
) -> dict[str, Any]:
    by_model: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in pose_rows:
        reference = row["scoring_reference"].lower()
        if reference in by_model[row["model"]]:
            raise TeacherBuildError(
                f"duplicate_model_reference:{job_id}:{row['model']}:{reference}"
            )
        by_model[row["model"]][reference] = row
    complete = [
        refs for refs in by_model.values() if set(refs) == set(CONFORMATIONS)
    ]
    if len(complete) < 4:
        raise TeacherBuildError(f"job_has_fewer_than_4_complete_models:{job_id}:{len(complete)}")

    def score_key(refs: Mapping[str, Mapping[str, str]]) -> tuple[float, str]:
        native = refs[dock_conformation]
        score = as_float(native.get("haddock_score"), field="haddock_score")
        return score, native.get("model", "")

    complete.sort(key=score_key)
    weights = rank_weights(len(complete))
    metric_fields = (
        "hotspot_overlap",
        "anchor_overlap",
        "holdout_overlap",
        "total_occlusion",
        "cdr3_occlusion",
        "cdr3_fraction",
        "vhh_pvrig_clash_residue_pairs",
        "vhh_pvrl2_clash_residue_pairs",
        "overlay_rmsd_a",
    )
    agreement = as_float(
        job_result.get("model_native_cross_support_agreement_fraction", 0.0),
        field="model_native_cross_support_agreement_fraction",
    )
    consensus = as_float(
        job_result.get("model_pair_consensus_fraction", 0.0),
        field="model_pair_consensus_fraction",
    )
    raw_utility = sum(
        weight * native_pose_utility(refs[dock_conformation])
        for weight, refs in zip(weights, complete)
    )
    model_count_reliability = 0.5 + 0.5 * min(len(complete) / 8.0, 1.0)
    agreement_reliability = 0.5 + 0.25 * agreement + 0.25 * consensus
    summary: dict[str, Any] = {
        "job_id": job_id,
        "dock_conformation": dock_conformation,
        "seed": str(job_result.get("seed", "")),
        "complete_model_count": len(complete),
        "job_utility_raw": raw_utility,
        "job_utility": raw_utility * model_count_reliability * agreement_reliability,
        "model_count_reliability": model_count_reliability,
        "agreement_reliability": agreement_reliability,
        "native_cross_support_agreement": agreement,
        "model_pair_consensus_fraction": consensus,
        "model_strict_a_fraction": as_float(
            job_result.get("model_strict_a_fraction", 0.0),
            field="model_strict_a_fraction",
        ),
    }
    for field in metric_fields:
        summary[field] = sum(
            weight * as_float(refs[dock_conformation].get(field), field=field)
            for weight, refs in zip(weights, complete)
        )
    return summary


def build_candidate_teacher(
    split_row: Mapping[str, str],
    job_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    by_conformation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in job_summaries:
        by_conformation[row["dock_conformation"]].append(row)
    if set(by_conformation) != set(CONFORMATIONS):
        raise TeacherBuildError(f"candidate_missing_conformation:{split_row['candidate_id']}")
    for conformation in CONFORMATIONS:
        if len(by_conformation[conformation]) < 2:
            raise TeacherBuildError(
                f"candidate_has_fewer_than_2_successful_seeds:{split_row['candidate_id']}:{conformation}"
            )

    receptor_scores = {
        conformation: statistics.median(
            row["job_utility"] for row in by_conformation[conformation]
        )
        for conformation in CONFORMATIONS
    }
    receptor_sd = {
        conformation: statistics.pstdev(
            row["job_utility"] for row in by_conformation[conformation]
        )
        for conformation in CONFORMATIONS
    }
    r8 = receptor_scores["8x6b"]
    r9 = receptor_scores["9e6y"]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": split_row["candidate_id"],
        "sequence_sha256": split_row["sequence_sha256"],
        "sequence": split_row["sequence"],
        "cdr1": split_row["cdr1"],
        "cdr2": split_row["cdr2"],
        "cdr3": split_row["cdr3"],
        "phase": split_row["phase"],
        "scaffold_id": split_row["scaffold_id"],
        "h3_regime": split_row["h3_regime"],
        "near_cdr3_family_id": split_row["near_cdr3_family_id"],
        "selection_bucket": split_row["selection_bucket"],
        "model_split": split_row["model_split"],
        "R_8X6B": round(r8, 9),
        "R_9E6Y": round(r9, 9),
        "R_dual_mean": round((r8 + r9) / 2.0, 9),
        "R_dual_min": round(min(r8, r9), 9),
        "R_dual_gap": round(abs(r8 - r9), 9),
        "seed_sd_8X6B": round(receptor_sd["8x6b"], 9),
        "seed_sd_9E6Y": round(receptor_sd["9e6y"], 9),
        "successful_seed_count_8X6B": len(by_conformation["8x6b"]),
        "successful_seed_count_9E6Y": len(by_conformation["9e6y"]),
        "native_cross_support_agreement_mean": round(
            mean(row["native_cross_support_agreement"] for row in job_summaries), 9
        ),
        "model_pair_consensus_fraction_mean": round(
            mean(row["model_pair_consensus_fraction"] for row in job_summaries), 9
        ),
        "model_strict_a_fraction_mean": round(
            mean(row["model_strict_a_fraction"] for row in job_summaries), 9
        ),
        "model_count_reliability_mean": round(
            mean(row["model_count_reliability"] for row in job_summaries), 9
        ),
        "agreement_reliability_mean": round(
            mean(row["agreement_reliability"] for row in job_summaries), 9
        ),
    }
    for conformation in CONFORMATIONS:
        suffix = "8X6B" if conformation == "8x6b" else "9E6Y"
        for field in (
            "hotspot_overlap",
            "anchor_overlap",
            "holdout_overlap",
            "total_occlusion",
            "cdr3_occlusion",
            "cdr3_fraction",
            "vhh_pvrig_clash_residue_pairs",
            "vhh_pvrl2_clash_residue_pairs",
            "overlay_rmsd_a",
        ):
            result[f"{field}_median_{suffix}"] = round(
                statistics.median(row[field] for row in by_conformation[conformation]), 9
            )
    missing_seed_fraction = sum(
        3 - len(by_conformation[conformation]) for conformation in CONFORMATIONS
    ) / 6.0
    result["missing_seed_fraction"] = round(missing_seed_fraction, 9)
    result["teacher_uncertainty"] = round(
        max(receptor_sd.values()) + abs(r8 - r9) + 0.1 * missing_seed_fraction,
        9,
    )
    result["claim_boundary"] = CLAIM_BOUNDARY
    return result


def validate_evaluator(
    evaluator: Mapping[str, Any],
    *,
    job_results_sha256: str | None = None,
    pose_scores_sha256: str | None = None,
) -> None:
    failures: list[str] = []
    if evaluator.get("status") != "PASS":
        failures.append(f"evaluator_status_{evaluator.get('status', 'MISSING')}")
    if evaluator.get("evidence_mode") != "production_pose_backed":
        failures.append("evaluator_not_production_pose_backed")
    if evaluator.get("unlockable") is not True:
        failures.append("evaluator_unlockable_not_true")
    if int(evaluator.get("job_count", 0) or 0) != EXPECTED_TOTAL_JOBS:
        failures.append("evaluator_job_count_not_1050")
    if evaluator.get("job_manifest_sha256") != EXPECTED_JOB_MANIFEST_SHA256:
        failures.append("evaluator_job_manifest_sha256_mismatch")
    if evaluator.get("protocol_lock_sha256") != EXPECTED_PROTOCOL_LOCK_SHA256:
        failures.append("evaluator_protocol_lock_sha256_mismatch")
    if evaluator.get("protocol_core_sha256") != EXPECTED_PROTOCOL_CORE_SHA256:
        failures.append("evaluator_protocol_core_sha256_mismatch")
    if evaluator.get("candidates_sha256") != EXPECTED_CANDIDATES_SHA256:
        failures.append("evaluator_candidates_sha256_mismatch")
    if evaluator.get("stability_gate_spec_sha256") != EXPECTED_STABILITY_SPEC_SHA256:
        failures.append("evaluator_stability_spec_sha256_mismatch")
    if not evaluator.get("job_set_hash"):
        failures.append("evaluator_job_set_hash_missing")
    gates = evaluator.get("gates", {})
    if not isinstance(gates, Mapping) or not gates:
        failures.append("evaluator_gates_missing")
        gates = {}
    failed_gates = sorted(
        name for name, payload in gates.items()
        if not isinstance(payload, Mapping) or payload.get("status") != "PASS"
    )
    if failed_gates:
        failures.append("evaluator_nonpass_gates:" + ";".join(failed_gates))
    terminal = gates.get("all_jobs_terminal", {}).get("status")
    if terminal != "PASS":
        failures.append(f"all_jobs_terminal_gate_{terminal or 'MISSING'}")
    if job_results_sha256 is not None and evaluator.get("job_results_sha256") != job_results_sha256:
        failures.append("job_results_file_not_bound_to_evaluator")
    if pose_scores_sha256 is not None and evaluator.get("pose_scores_sha256") != pose_scores_sha256:
        failures.append("pose_scores_file_not_bound_to_evaluator")
    if failures:
        raise TeacherBuildError("teacher_release_gate_failed:" + ",".join(failures))


def build_teacher_rows(
    split_rows: list[dict[str, str]],
    job_manifest: list[dict[str, str]],
    job_results: list[dict[str, str]],
    pose_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if len({row["candidate_id"] for row in split_rows}) != len(split_rows):
        raise TeacherBuildError("duplicate_candidate_in_selected_split")
    if len({row["job_id"] for row in job_manifest}) != len(job_manifest):
        raise TeacherBuildError("duplicate_job_id_in_selected_manifest")
    if len({row["job_id"] for row in job_results}) != len(job_results):
        raise TeacherBuildError("duplicate_job_id_in_selected_results")
    jobs_by_id = {row["job_id"]: row for row in job_manifest}
    results_by_id = {row["job_id"]: row for row in job_results}
    expected_jobs = len(split_rows) * 6
    if len(jobs_by_id) != expected_jobs or set(results_by_id) != set(jobs_by_id):
        raise TeacherBuildError(
            f"selected_job_result_closure_failed:expected={expected_jobs}:"
            f"jobs={len(jobs_by_id)}:results={len(results_by_id)}"
        )
    for job_id, result in results_by_id.items():
        manifest = jobs_by_id.get(job_id)
        if manifest is None or result.get("job_hash") != manifest.get("job_hash"):
            raise TeacherBuildError(f"job_hash_closure_failed:{job_id}")

    poses_by_job: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pose_rows:
        poses_by_job[row["job_id"]].append(row)
    summaries_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job_id, manifest in jobs_by_id.items():
        if manifest.get("entity_type") != "candidate":
            raise TeacherBuildError(f"non_candidate_job_in_selected_manifest:{job_id}")
        result = results_by_id[job_id]
        if str(result.get("state", "")).upper() not in SUCCESS_STATES:
            continue
        if str(result.get("pose_backed_2x2", "")).lower() != "true":
            continue
        summaries_by_candidate[manifest["entity_id"]].append(
            job_summary(job_id, manifest["conformation"], poses_by_job[job_id], result)
        )

    output = [
        build_candidate_teacher(split_row, summaries_by_candidate[split_row["candidate_id"]])
        for split_row in split_rows
    ]
    output.sort(key=lambda row: row["candidate_id"])
    return output


def select_open_split(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected = [row for row in rows if row["model_split"] == "OPEN_DEVELOPMENT"]
    if len(selected) != 96:
        raise TeacherBuildError(f"expected_96_open_rows_got_{len(selected)}")
    return selected


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_c/dual128_split_manifest.tsv",
    )
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--job-results", type=Path, required=True)
    parser.add_argument("--pose-scores", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if sha256_file(args.split_manifest) != EXPECTED_SPLIT_MANIFEST_SHA256:
        raise TeacherBuildError("split_manifest_file_sha256_mismatch")
    split_rows = select_open_split(read_tsv(args.split_manifest))
    allowed_entities = {row["candidate_id"] for row in split_rows}
    job_results_sha256 = sha256_file(args.job_results)
    pose_scores_sha256 = sha256_file(args.pose_scores)
    evaluator = json.loads(args.evaluator.read_text(encoding="utf-8"))
    validate_evaluator(
        evaluator,
        job_results_sha256=job_results_sha256,
        pose_scores_sha256=pose_scores_sha256,
    )
    if sha256_file(args.job_manifest) != EXPECTED_JOB_MANIFEST_SHA256:
        raise TeacherBuildError("job_manifest_file_sha256_mismatch")
    selected_jobs = [
        row
        for row in read_tsv(args.job_manifest)
        if row.get("entity_type") == "candidate" and row.get("entity_id") in allowed_entities
    ]
    selected_results = read_tsv_for_entities(args.job_results, allowed_entities)
    successful_job_ids = {
        row["job_id"]
        for row in selected_results
        if str(row.get("state", "")).upper() in SUCCESS_STATES
        and str(row.get("pose_backed_2x2", "")).lower() == "true"
    }
    raw_pose_rows, raw_evidence_hash_chain = raw_pose_rows_for_jobs(
        args.results_root,
        selected_jobs,
        successful_job_ids,
    )
    selected = build_teacher_rows(
        split_rows,
        selected_jobs,
        selected_results,
        raw_pose_rows,
    )
    write_tsv(args.out, selected)
    audit_path = args.out.with_suffix(args.out.suffix + ".audit.json")
    write_json(
        audit_path,
        {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_V4_C_CONTINUOUS_TEACHER_RELEASE",
            "release": "open_development_only",
            "row_count": len(selected),
            "retrospective_challenge_labels_read": False,
            "inputs": {
                "split_manifest_sha256": sha256_file(args.split_manifest),
                "job_manifest_sha256": sha256_file(args.job_manifest),
                "job_results_sha256": job_results_sha256,
                "pose_scores_sha256_for_evaluator_binding_only": pose_scores_sha256,
                "evaluator_sha256": sha256_file(args.evaluator),
                "selected_raw_result_root": str(args.results_root),
                "selected_successful_job_count": len(successful_job_ids),
                "selected_raw_result_sha256_chain": raw_evidence_hash_chain,
            },
            "output": {"path": str(args.out), "sha256": sha256_file(args.out)},
            "primary_target": "R_dual_min",
            "claim_boundary": CLAIM_BOUNDARY,
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "release": "open_development_only",
                "row_count": len(selected),
                "out": str(args.out),
                "audit": str(audit_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
