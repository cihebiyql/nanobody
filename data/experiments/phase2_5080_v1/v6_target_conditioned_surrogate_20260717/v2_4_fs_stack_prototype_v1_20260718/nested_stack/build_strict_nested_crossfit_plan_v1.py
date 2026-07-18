#!/usr/bin/env python3
"""Plan and postprocess strict double whole-parent V2.4 stacking.

The planning path is read-only with respect to model training.  It validates
the canonical open-development manifests, materializes trainer split JSONs,
and emits a dependency DAG.  A graph is executable only when the supplied
deployment manifest is already post-calibration/frozen and contains exact
per-lane trainer argv.  The postprocessing subcommands convert completed base
trainer outputs into the role-separated V2.4 evidence contract.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "pvrig_v2_4_strict_double_whole_parent_crossfit_plan_v1"
TRAINER_SPLIT_SCHEMA = "pvrig_v2_4_open_base_split_manifest_v1"
PROVENANCE_SCHEMA = "pvrig_v2_4_component_provenance_v2"
BASE_ROW_SCHEMA = "pvrig_v2_4_receptor_base_feature_row_v2"
META_ROW_SCHEMA = "pvrig_v2_4_outer_meta_prediction_row_v2"
INNER_ROLE = "INNER_OOF_BASE_FEATURE"
OUTER_BASE_ROLE = "OUTER_TEST_BASE_FEATURE"
OUTER_META_ROLE = "OUTER_TEST_META_PREDICTION"
LANES = ("B_TARGET_NO_CONTACT", "C_SPLIT_MARGINAL", "D_SPLIT_PAIR")
EXCLUDED_LANE = "A_VHH_ONLY"
LANE_GPU = {
    "B_TARGET_NO_CONTACT": 2,
    "C_SPLIT_MARGINAL": 4,
    "D_SPLIT_PAIR": 5,
}
OUTER_FOLDS = tuple(range(5))
INNER_FOLDS = tuple(range(5))
CANONICAL_TRAINING_SHA = "47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1"
CANONICAL_OUTER_SHA = "ce49916385ccb792b4b03dda72889ab8c72aaccd662ccfcdb1d30874bdd81e55"
CANONICAL_INNER_SHA = "b56cd47d2ea030cbf52cf2a966f503c1e5b8f9755329de62ad8e4343f32b6073"
CONTACT_FORMULA_SHA = "7abe8e845b33ef7c77a61397a826fb3e6f94fb34122b7abbc2ddbd77c6db2ec7"
CLAIM_BOUNDARY = (
    "Open-development computational surrogate of independent 8X6B/9E6Y "
    "Docking geometry; not binding probability, affinity, experimental "
    "blocking, Docking Gold, or submission evidence."
)
V4F = re.compile(r"(^|[/\\._-])v4[/\\._-]?f($|[/\\._-])|test32", re.I)

BASE_COLUMNS = (
    "schema_version", "evidence_role", "candidate_id", "teacher_source",
    "parent_framework_cluster", "outer_fold", "inner_fold", "R_8X6B",
    "R_9E6Y", "R_dual_min", "M2_R8", "neural_R8", "contact_score_R8",
    "M2_R9", "neural_R9", "contact_score_R9", "split_manifest_path",
    "split_manifest_sha256", "split_train_parent_set_sha256",
    "split_score_parent_set_sha256", "M2_training_parent_set_sha256",
    "M2_component_receipt_sha256", "M2_artifact_path",
    "neural_training_parent_set_sha256", "neural_component_receipt_sha256",
    "neural_checkpoint_path", "contact_training_parent_set_sha256",
    "contact_component_receipt_sha256", "contact_checkpoint_path",
    "contact_formula_receipt_sha256", "contact_formula_artifact_path",
)
META_COLUMNS = (
    "schema_version", "evidence_role", "candidate_id", "teacher_source",
    "parent_framework_cluster", "outer_fold", "R_8X6B", "R_9E6Y",
    "R_dual_min", "prediction_R8", "prediction_R9",
    "prediction_R_dual_min", "split_manifest_path", "split_manifest_sha256",
    "split_train_parent_set_sha256", "split_score_parent_set_sha256",
    "outer_base_feature_evidence_path", "outer_base_feature_evidence_sha256",
    "fit_inner_oof_evidence_path", "fit_inner_oof_evidence_sha256",
    "fit_inner_oof_parent_set_sha256", "scaling_fit_parent_set_sha256",
    "meta_training_parent_set_sha256", "meta_model_receipt_sha256",
    "meta_model_artifact_path",
)


class NestedPlanError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise NestedPlanError(message)


def reject_sealed(value: str | Path, context: str) -> None:
    require(not V4F.search(str(value)), f"sealed_v4f_forbidden:{context}:{value}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parent_sha(parents: Iterable[str]) -> str:
    payload = "".join(f"{p}\n" for p in sorted(set(parents))).encode()
    return hashlib.sha256(payload).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    reject_sealed(path.resolve(), "tsv_path")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(bool(rows), f"empty_tsv:{path}")
    return rows


def write_tsv(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            require(set(row) == set(columns), f"row_column_mismatch:{path}")
            writer.writerow(row)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_json(path: Path) -> dict[str, Any]:
    reject_sealed(path.resolve(), "json_path")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), f"json_not_object:{path}")
    return payload


def validate_canonical_inputs(
    training_path: Path, outer_path: Path, inner_path: Path,
) -> tuple[
    dict[str, dict[str, str]], list[dict[str, str]], list[dict[str, str]],
    dict[tuple[int, int], dict[str, Any]], dict[int, dict[str, Any]],
]:
    require(sha256_file(training_path) == CANONICAL_TRAINING_SHA, "training_sha_not_canonical")
    require(sha256_file(outer_path) == CANONICAL_OUTER_SHA, "outer_sha_not_canonical")
    require(sha256_file(inner_path) == CANONICAL_INNER_SHA, "inner_sha_not_canonical")
    training = read_tsv(training_path)
    outer = read_tsv(outer_path)
    inner = read_tsv(inner_path)
    require(len(training) == 1507, "training_count_not_1507")
    by_candidate = {row["candidate_id"]: row for row in training}
    require(len(by_candidate) == len(training), "training_candidate_duplicate")
    sources = {row["teacher_source"] for row in training}
    require(
        sources == {"V4D_OPEN_MULTI_SEED", "V4H_ADAPTIVE_SEED_RANKING"},
        f"teacher_source_closure:{sorted(sources)}",
    )
    for row in training:
        reject_sealed(row["teacher_source"], f"teacher_source:{row['candidate_id']}")
        reject_sealed(row["candidate_id"], "candidate_id")
    parent_source: dict[str, str] = {}
    for row in training:
        previous = parent_source.setdefault(row["parent_framework_cluster"], row["teacher_source"])
        require(previous == row["teacher_source"], f"parent_cross_source:{row['parent_framework_cluster']}")
    all_candidates = set(by_candidate)
    all_parents = {row["parent_framework_cluster"] for row in training}
    require(len(all_parents) == 31, "parent_count_not_31")

    outer_groups: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in outer:
        outer_groups[int(row["outer_fold"])].append(row)
    require(set(outer_groups) == set(OUTER_FOLDS), "outer_fold_closure")
    outer_contract: dict[int, dict[str, Any]] = {}
    for fold in OUTER_FOLDS:
        rows = outer_groups[fold]
        require(len(rows) == 1507, f"outer_candidate_count:{fold}")
        require({r["candidate_id"] for r in rows} == all_candidates, f"outer_candidate_closure:{fold}")
        roles_by_parent: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            truth = by_candidate[row["candidate_id"]]
            require(row["teacher_source"] == truth["teacher_source"], f"outer_source_identity:{fold}")
            require(row["parent_framework_cluster"] == truth["parent_framework_cluster"], f"outer_parent_identity:{fold}")
            roles_by_parent[row["parent_framework_cluster"]].add(row["candidate_role"])
        require(all(len(v) == 1 for v in roles_by_parent.values()), f"outer_parent_split:{fold}")
        train = {p for p, v in roles_by_parent.items() if v == {"train"}}
        score = {p for p, v in roles_by_parent.items() if v == {"score"}}
        require(train and score and train.isdisjoint(score) and train | score == all_parents, f"outer_parent_partition:{fold}")
        train_digest, score_digest = parent_sha(train), parent_sha(score)
        require({r["train_parent_set_sha256"] for r in rows} == {train_digest}, f"outer_train_digest:{fold}")
        require({r["score_parent_set_sha256"] for r in rows} == {score_digest}, f"outer_score_digest:{fold}")
        outer_contract[fold] = {"train": train, "score": score, "train_sha": train_digest, "score_sha": score_digest}

    inner_groups: dict[tuple[int, int], list[dict[str, str]]] = defaultdict(list)
    for row in inner:
        inner_groups[(int(row["outer_fold"]), int(row["inner_fold"]))].append(row)
    require(set(inner_groups) == {(o, i) for o in OUTER_FOLDS for i in INNER_FOLDS}, "inner_fold_closure")
    inner_contract: dict[tuple[int, int], dict[str, Any]] = {}
    for outer_fold in OUTER_FOLDS:
        scored_once: Counter[str] = Counter()
        expected_parents = outer_contract[outer_fold]["train"]
        expected_candidates = {c for c, r in by_candidate.items() if r["parent_framework_cluster"] in expected_parents}
        score_parent_union: set[str] = set()
        for inner_fold in INNER_FOLDS:
            rows = inner_groups[(outer_fold, inner_fold)]
            require({r["candidate_id"] for r in rows} == expected_candidates, f"inner_candidate_closure:{outer_fold}:{inner_fold}")
            roles_by_parent: dict[str, set[str]] = defaultdict(set)
            for row in rows:
                truth = by_candidate[row["candidate_id"]]
                require(row["teacher_source"] == truth["teacher_source"], f"inner_source_identity:{outer_fold}:{inner_fold}")
                require(row["parent_framework_cluster"] == truth["parent_framework_cluster"], f"inner_parent_identity:{outer_fold}:{inner_fold}")
                roles_by_parent[row["parent_framework_cluster"]].add(row["candidate_role"])
            require(all(len(v) == 1 for v in roles_by_parent.values()), f"inner_parent_split:{outer_fold}:{inner_fold}")
            train = {p for p, v in roles_by_parent.items() if v == {"train"}}
            score = {p for p, v in roles_by_parent.items() if v == {"score"}}
            require(train and score and train.isdisjoint(score) and train | score == expected_parents, f"inner_parent_partition:{outer_fold}:{inner_fold}")
            require(not score_parent_union.intersection(score), f"inner_score_parent_repeated:{outer_fold}:{inner_fold}")
            score_parent_union.update(score)
            for row in rows:
                if row["candidate_role"] == "score":
                    scored_once[row["candidate_id"]] += 1
            train_digest, score_digest = parent_sha(train), parent_sha(score)
            require({r["train_parent_set_sha256"] for r in rows} == {train_digest}, f"inner_train_digest:{outer_fold}:{inner_fold}")
            require({r["score_parent_set_sha256"] for r in rows} == {score_digest}, f"inner_score_digest:{outer_fold}:{inner_fold}")
            require({r["outer_train_parent_set_sha256"] for r in rows} == {outer_contract[outer_fold]["train_sha"]}, f"inner_outer_train_digest:{outer_fold}:{inner_fold}")
            inner_contract[(outer_fold, inner_fold)] = {"train": train, "score": score, "train_sha": train_digest, "score_sha": score_digest}
        require(score_parent_union == expected_parents, f"inner_score_parent_partition:{outer_fold}")
        require(set(scored_once) == expected_candidates and set(scored_once.values()) == {1}, f"inner_candidate_scored_once:{outer_fold}")
    return by_candidate, outer, inner, inner_contract, outer_contract


def trainer_split_payload(
    *, split_id: str, outer_fold: int, train: set[str], score: set[str],
    train_digest: str, score_digest: str, fixed_epochs: int,
    source_manifest_sha: str, training_sha: str,
) -> dict[str, Any]:
    return {
        "schema_version": TRAINER_SPLIT_SCHEMA,
        "split_id": split_id,
        "outer_fold": outer_fold,
        "train_parents": sorted(train),
        "score_parents": sorted(score),
        "fixed_epochs": fixed_epochs,
        "open_only": True,
        "v4_f_test32_access_count": 0,
        "train_parent_set_sha256": train_digest,
        "score_parent_set_sha256": score_digest,
        "source_split_manifest_sha256": source_manifest_sha,
        "training_tsv_sha256": training_sha,
    }


def substitute_trainer_command(
    deployment: Mapping[str, Any], lane: str, split_path: str, output_dir: str,
) -> list[str] | None:
    trainer = deployment.get("trainer") or {}
    lane_argv = trainer.get("lane_outer_extra_argv")
    if not deployment.get("production_authorized") or not isinstance(lane_argv, dict):
        return None
    require(set(lane_argv) >= set(LANES), "frozen_lane_argv_missing")
    artifacts = deployment["artifacts"]
    values = {
        "python": deployment["python"], "trainer": artifacts["trainer"]["node1_path"],
        "lane": lane, "output_dir": output_dir, "split_manifest": split_path,
        "training_tsv": artifacts["training_tsv"]["node1_path"],
        "dual_marginal_tsv_gz": artifacts["dual_marginal_tsv_gz"]["node1_path"],
        "vhh_graph_dir": str(Path(artifacts["vhh_graph_cache_npz"]["node1_path"]).parent),
        "base_target_pt": artifacts["base_target_pt"]["node1_path"],
        "dual_pair_tsv_gz": artifacts["dual_pair_tsv_gz"]["node1_path"],
        "contact_formula": artifacts["contact_formula"]["node1_path"],
        "esm2_650m_identity": artifacts["esm2_650m_identity"]["node1_path"],
    }
    command = [str(token).format(**values) for token in trainer["argv_template"]]
    command.extend(str(v) for v in lane_argv[lane])
    return command


def job(job_id: str, kind: str, dependencies: Sequence[str], **kwargs: Any) -> dict[str, Any]:
    return {"job_id": job_id, "kind": kind, "dependencies": list(dependencies), **kwargs}


def plan(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    require(not output_dir.exists(), f"output_dir_exists:{output_dir}")
    for value, context in ((args.runtime_root, "runtime_root"), (args.planner_node1_path, "planner_node1_path"),
                           (args.feature_validator_node1_path, "feature_validator"), (args.stack_fitter_node1_path, "stack_fitter")):
        reject_sealed(value, context)
    by_candidate, _, _, inner_contract, outer_contract = validate_canonical_inputs(
        args.training_tsv.resolve(), args.outer_manifest.resolve(), args.inner_manifest.resolve()
    )
    require(sha256_file(args.contact_formula.resolve()) == CONTACT_FORMULA_SHA, "contact_formula_sha")
    deployment = load_json(args.deployment_manifest.resolve())
    planner_local = Path(__file__).resolve()
    runner_local = planner_local.with_name("run_strict_nested_crossfit_graph_v1.py")
    validator_local = planner_local.parents[1] / "feature_contract" / "src" / "validate_receptor_compact_evidence_v2.py"
    stack_local = planner_local.parents[1] / "src" / "fit_shared_nonnegative_stack_v2.py"
    require(runner_local.is_file() and validator_local.is_file() and stack_local.is_file(), "nested_stack_code_artifact_missing")
    output_dir.mkdir(parents=True)
    split_dir = output_dir / "trainer_splits"
    split_dir.mkdir()
    node_split_root = Path(args.node1_plan_root) / "trainer_splits"
    fixed_epochs = int((deployment.get("trainer") or {}).get("frozen_noncalibration_parameters", {}).get("fixed_epochs", 0))
    require(fixed_epochs > 0, "fixed_epochs_missing")
    split_outputs: dict[str, Any] = {}
    for outer_fold in OUTER_FOLDS:
        c = outer_contract[outer_fold]
        payload = trainer_split_payload(
            split_id=f"outer_development_{outer_fold}", outer_fold=outer_fold,
            train=c["train"], score=c["score"], train_digest=c["train_sha"],
            score_digest=c["score_sha"], fixed_epochs=fixed_epochs,
            source_manifest_sha=CANONICAL_OUTER_SHA, training_sha=CANONICAL_TRAINING_SHA,
        )
        local = split_dir / f"outer_{outer_fold}.json"
        atomic_json(local, payload)
        split_outputs[f"outer_{outer_fold}"] = {"local_path": str(local), "node1_path": str(node_split_root / local.name), "sha256": sha256_file(local)}
        for inner_fold in INNER_FOLDS:
            ic = inner_contract[(outer_fold, inner_fold)]
            payload = trainer_split_payload(
                split_id=f"outer_{outer_fold}_inner_{inner_fold}", outer_fold=outer_fold,
                train=ic["train"], score=ic["score"], train_digest=ic["train_sha"],
                score_digest=ic["score_sha"], fixed_epochs=fixed_epochs,
                source_manifest_sha=CANONICAL_INNER_SHA, training_sha=CANONICAL_TRAINING_SHA,
            )
            local = split_dir / f"outer_{outer_fold}_inner_{inner_fold}.json"
            atomic_json(local, payload)
            split_outputs[f"outer_{outer_fold}_inner_{inner_fold}"] = {"local_path": str(local), "node1_path": str(node_split_root / local.name), "sha256": sha256_file(local)}

    jobs: list[dict[str, Any]] = []
    runtime = Path(args.runtime_root)
    planner = args.planner_node1_path
    validator = args.feature_validator_node1_path
    stack_fitter = args.stack_fitter_node1_path
    canonical_inner_node = args.inner_manifest_node1_path
    canonical_outer_node = args.outer_manifest_node1_path
    formula_node = args.contact_formula_node1_path
    executable = bool(deployment.get("production_authorized") and isinstance((deployment.get("trainer") or {}).get("lane_outer_extra_argv"), dict))

    for outer_fold in OUTER_FOLDS:
        for lane in LANES:
            prefix = f"o{outer_fold}.{lane}"
            inner_train_ids = []
            for inner_fold in INNER_FOLDS:
                jid = f"{prefix}.inner{inner_fold}.base_train"
                inner_train_ids.append(jid)
                out = runtime / "inner_base" / lane / f"outer_{outer_fold}" / f"inner_{inner_fold}"
                split_node = split_outputs[f"outer_{outer_fold}_inner_{inner_fold}"]["node1_path"]
                jobs.append(job(
                    jid, "GPU_BASE_TRAIN_INNER", [], lane=lane, physical_gpu=LANE_GPU[lane],
                    outer_fold=outer_fold, inner_fold=inner_fold, output_dir=str(out),
                    split_manifest=str(split_node), expected_result=str(out / "RESULT.json"),
                    command=substitute_trainer_command(deployment, lane, str(split_node), str(out)),
                ))
            inner_evidence = runtime / "evidence" / lane / f"outer_{outer_fold}" / "inner_oof_base.tsv"
            inner_prov = runtime / "evidence" / lane / f"outer_{outer_fold}" / "inner_oof_provenance.json"
            assemble_inner = f"{prefix}.inner_oof.assemble"
            jobs.append(job(
                assemble_inner, "CPU_ASSEMBLE_INNER_OOF_BASE_FEATURE", inner_train_ids,
                lane=lane, outer_fold=outer_fold, output_tsv=str(inner_evidence),
                provenance_json=str(inner_prov), command=[deployment["python"], planner, "assemble-base",
                    "--job-graph", str(Path(args.node1_plan_root) / "job_graph.json"), "--outer-fold", str(outer_fold),
                    "--lane", lane, "--role", "inner", "--output-tsv", str(inner_evidence),
                    "--provenance-json", str(inner_prov)], expected_result=str(inner_evidence),
            ))
            validate_inner = f"{prefix}.inner_oof.validate"
            inner_report = inner_evidence.with_suffix(".validation.json")
            jobs.append(job(
                validate_inner, "CPU_VALIDATE_INNER_OOF_BASE_FEATURE", [assemble_inner], lane=lane,
                outer_fold=outer_fold, command=[deployment["python"], validator,
                    "--evidence-tsv", str(inner_evidence), "--split-manifest-tsv", canonical_inner_node,
                    "--provenance-json", str(inner_prov), "--contact-formula-json", formula_node,
                    "--report-json", str(inner_report)], expected_result=str(inner_report),
            ))
            stack_dir = runtime / "stack" / lane / f"outer_{outer_fold}"
            outer_base = runtime / "evidence" / lane / f"outer_{outer_fold}" / "outer_test_base.tsv"
            fit_meta = f"{prefix}.meta.fit"
            # The score TSV is intentionally produced later.  At execution the
            # scheduler starts fit only after both validated evidence artifacts
            # exist; this avoids fitting or scoring on an unvalidated file.
            outer_refit = f"{prefix}.outer.base_refit"
            outer_out = runtime / "outer_base" / lane / f"outer_{outer_fold}"
            outer_split_node = split_outputs[f"outer_{outer_fold}"]["node1_path"]
            jobs.append(job(
                fit_meta, "CPU_FIT_FIVE_PARAMETER_META", [validate_inner, f"{prefix}.outer_base.validate"],
                lane=lane, outer_fold=outer_fold, command=[deployment["python"], stack_fitter,
                    "--fit-tsv", str(inner_evidence), "--score-tsv", str(outer_base),
                    "--output-dir", str(stack_dir)], expected_result=str(stack_dir / "receipt.json"),
            ))
            jobs.append(job(
                outer_refit, "GPU_BASE_REFIT_OUTER_TRAIN", [], lane=lane, physical_gpu=LANE_GPU[lane],
                outer_fold=outer_fold, inner_fold=None, output_dir=str(outer_out),
                split_manifest=str(outer_split_node), expected_result=str(outer_out / "RESULT.json"),
                command=substitute_trainer_command(deployment, lane, str(outer_split_node), str(outer_out)),
            ))
            outer_prov = outer_base.with_name("outer_test_provenance.json")
            assemble_outer = f"{prefix}.outer_base.assemble"
            jobs.append(job(
                assemble_outer, "CPU_ASSEMBLE_OUTER_TEST_BASE_FEATURE", [outer_refit], lane=lane,
                outer_fold=outer_fold, output_tsv=str(outer_base), provenance_json=str(outer_prov),
                command=[deployment["python"], planner, "assemble-base", "--job-graph",
                    str(Path(args.node1_plan_root) / "job_graph.json"), "--outer-fold", str(outer_fold),
                    "--lane", lane, "--role", "outer", "--output-tsv", str(outer_base),
                    "--provenance-json", str(outer_prov)], expected_result=str(outer_base),
            ))
            validate_outer = f"{prefix}.outer_base.validate"
            outer_report = outer_base.with_suffix(".validation.json")
            jobs.append(job(
                validate_outer, "CPU_VALIDATE_OUTER_TEST_BASE_FEATURE", [assemble_outer], lane=lane,
                outer_fold=outer_fold, command=[deployment["python"], validator,
                    "--evidence-tsv", str(outer_base), "--split-manifest-tsv", canonical_outer_node,
                    "--provenance-json", str(outer_prov), "--contact-formula-json", formula_node,
                    "--report-json", str(outer_report)], expected_result=str(outer_report),
            ))
            meta_tsv = outer_base.with_name("outer_test_meta_prediction.tsv")
            meta_prov = outer_base.with_name("outer_test_meta_provenance.json")
            materialize_meta = f"{prefix}.meta.materialize"
            jobs.append(job(
                materialize_meta, "CPU_MATERIALIZE_OUTER_TEST_META_PREDICTION", [fit_meta], lane=lane,
                outer_fold=outer_fold, command=[deployment["python"], planner, "materialize-meta",
                    "--job-graph", str(Path(args.node1_plan_root) / "job_graph.json"),
                    "--outer-fold", str(outer_fold), "--lane", lane,
                    "--inner-evidence-tsv", str(inner_evidence), "--outer-base-tsv", str(outer_base),
                    "--stack-output-dir", str(stack_dir), "--output-tsv", str(meta_tsv),
                    "--provenance-json", str(meta_prov)], expected_result=str(meta_tsv),
            ))
            validate_meta = f"{prefix}.meta.validate"
            meta_report = meta_tsv.with_suffix(".validation.json")
            jobs.append(job(
                validate_meta, "CPU_VALIDATE_OUTER_TEST_META_PREDICTION", [materialize_meta], lane=lane,
                outer_fold=outer_fold, command=[deployment["python"], validator,
                    "--evidence-tsv", str(meta_tsv), "--split-manifest-tsv", canonical_outer_node,
                    "--provenance-json", str(meta_prov), "--contact-formula-json", formula_node,
                    "--report-json", str(meta_report)], expected_result=str(meta_report),
            ))

    ids = {j["job_id"] for j in jobs}
    require(len(ids) == len(jobs), "job_id_duplicate")
    for item in jobs:
        require(set(item["dependencies"]).issubset(ids), f"unknown_dependency:{item['job_id']}")
    # Detect cycles without considering list order.
    pending = {j["job_id"]: set(j["dependencies"]) for j in jobs}
    resolved: set[str] = set()
    while pending:
        ready = {jid for jid, deps in pending.items() if deps <= resolved}
        require(bool(ready), "job_graph_cycle")
        resolved.update(ready)
        pending = {jid: deps for jid, deps in pending.items() if jid not in ready}
    counts = Counter(j["kind"] for j in jobs)
    graph = {
        "schema_version": SCHEMA,
        "status": "READY_EXECUTABLE_POSTCALIBRATION_FREEZE" if executable else "DRY_RUN_PENDING_POSTCALIBRATION_FREEZE_DO_NOT_EXECUTE",
        "execution_authorized": executable,
        "claim_boundary": CLAIM_BOUNDARY,
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
        "canonical_inputs": {
            "training_tsv": {"path": str(args.training_tsv.resolve()), "node1_path": deployment["artifacts"]["training_tsv"]["node1_path"], "sha256": CANONICAL_TRAINING_SHA, "candidates": len(by_candidate)},
            "outer_manifest": {"path": str(args.outer_manifest.resolve()), "node1_path": args.outer_manifest_node1_path, "sha256": CANONICAL_OUTER_SHA},
            "inner_manifest": {"path": str(args.inner_manifest.resolve()), "node1_path": args.inner_manifest_node1_path, "sha256": CANONICAL_INNER_SHA},
            "contact_formula": {"path": str(args.contact_formula.resolve()), "node1_path": args.contact_formula_node1_path, "sha256": CONTACT_FORMULA_SHA},
            "deployment_manifest": {"path": str(args.deployment_manifest.resolve()), "sha256": sha256_file(args.deployment_manifest.resolve())},
        },
        "code_contracts": {
            "planner": {"path": str(planner_local), "node1_path": args.planner_node1_path, "sha256": sha256_file(planner_local)},
            "runner": {"path": str(runner_local), "node1_path": str(Path(args.planner_node1_path).with_name(runner_local.name)), "sha256": sha256_file(runner_local)},
            "feature_validator_v2": {"path": str(validator_local), "node1_path": args.feature_validator_node1_path, "sha256": sha256_file(validator_local)},
            "stack_fitter_v2": {"path": str(stack_local), "node1_path": args.stack_fitter_node1_path, "sha256": sha256_file(stack_local)},
        },
        "stack_lanes": list(LANES),
        "diagnostic_exclusions": {EXCLUDED_LANE: "contact score is diagnostic non-stack VHH marginal mean"},
        "resources": {
            "physical_gpu_by_lane": LANE_GPU,
            "gpu_training_jobs": counts["GPU_BASE_TRAIN_INNER"] + counts["GPU_BASE_REFIT_OUTER_TRAIN"],
            "inner_gpu_jobs": counts["GPU_BASE_TRAIN_INNER"],
            "outer_refit_gpu_jobs": counts["GPU_BASE_REFIT_OUTER_TRAIN"],
            "cpu_postprocess_jobs": len(jobs) - counts["GPU_BASE_TRAIN_INNER"] - counts["GPU_BASE_REFIT_OUTER_TRAIN"],
            "max_concurrent_gpu_jobs": 3,
            "gpu1_status": "reserved_for_excluded_A_diagnostic_or_idle_not_part_of_stack",
        },
        "split_manifests": split_outputs,
        "jobs": jobs,
        "job_counts": dict(sorted(counts.items())),
        "strictness": {
            "meta_fit_rows": "inner whole-parent OOF only",
            "meta_evaluation_rows": "outer held-out whole parents only",
            "outer_labels_used_for_meta_fit": False,
            "same_rows_fit_and_evaluate_meta": False,
            "base_refit_scope": "outer-train parents only",
            "exact_min": "prediction_R_dual_min=min(prediction_R8,prediction_R9)",
        },
    }
    graph_path = output_dir / "job_graph.json"
    atomic_json(graph_path, graph)
    receipt = {
        "schema_version": "pvrig_v2_4_nested_crossfit_plan_receipt_v1",
        "status": graph["status"],
        "job_graph_path": str(graph_path),
        "job_graph_sha256": sha256_file(graph_path),
        "job_count": len(jobs),
        "gpu_training_job_count": graph["resources"]["gpu_training_jobs"],
        "split_manifest_count": len(split_outputs),
        "training_or_prediction_executed": False,
        "sealed_evaluation_access_count": 0,
    }
    atomic_json(output_dir / "receipt.json", receipt)
    return receipt


def select_graph_jobs(graph: Mapping[str, Any], outer_fold: int, lane: str, kind: str) -> list[Mapping[str, Any]]:
    result = [j for j in graph["jobs"] if j.get("outer_fold") == outer_fold and j.get("lane") == lane and j["kind"] == kind]
    require(bool(result), f"job_selection_empty:{outer_fold}:{lane}:{kind}")
    return result


def validate_completed_base_output(output_dir: Path, lane: str, train_sha: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    result = load_json(output_dir / "RESULT.json")
    require(result.get("status") == "PASS_OPEN_BASE_SPLIT_COMPLETE", f"base_result_status:{output_dir}")
    require(result.get("lane") == lane, f"base_lane:{output_dir}")
    require((result.get("split") or {}).get("train_parent_set_sha256") == train_sha, f"base_train_parent_digest:{output_dir}")
    require(result.get("open_only") is True and result.get("v4_f_test32_access_count") == 0, f"base_not_open:{output_dir}")
    require(result.get("contact_score_stack_eligible") is True, f"base_contact_not_stack_eligible:{output_dir}")
    require(result.get("contact_score_formula_receipt_sha256") == CONTACT_FORMULA_SHA, f"base_formula_sha:{output_dir}")
    prediction_path = output_dir / result["artifacts"]["predictions"]["path"]
    require(sha256_file(prediction_path) == result["artifacts"]["predictions"]["sha256"], f"base_prediction_hash:{output_dir}")
    rows = read_tsv(prediction_path)
    require(len(rows) == int(result["artifacts"]["predictions"]["rows"]), f"base_prediction_count:{output_dir}")
    return rows, result


def add_provenance_block(section: dict[str, Any], receipt_sha: str, block: Mapping[str, Any], context: str) -> None:
    previous = section.get(receipt_sha)
    require(previous is None or previous == dict(block), f"component_receipt_collision:{context}:{receipt_sha}")
    section[receipt_sha] = dict(block)


def assemble_base(args: argparse.Namespace) -> dict[str, Any]:
    graph = load_json(args.job_graph.resolve())
    require(graph.get("schema_version") == SCHEMA, "job_graph_schema")
    require(args.lane in LANES and args.outer_fold in OUTER_FOLDS, "base_identity")
    role = INNER_ROLE if args.role == "inner" else OUTER_BASE_ROLE
    kind = "GPU_BASE_TRAIN_INNER" if args.role == "inner" else "GPU_BASE_REFIT_OUTER_TRAIN"
    jobs = sorted(select_graph_jobs(graph, args.outer_fold, args.lane, kind), key=lambda j: -1 if j.get("inner_fold") is None else j["inner_fold"])
    split_artifact = graph["canonical_inputs"]["inner_manifest" if args.role == "inner" else "outer_manifest"]
    split_rows = read_tsv(Path(split_artifact.get("node1_path", split_artifact["path"])))
    split_index = {
        ((int(r["outer_fold"]), int(r["inner_fold"]), r["candidate_id"]) if args.role == "inner" else (int(r["outer_fold"]), r["candidate_id"])): r
        for r in split_rows
    }
    evidence: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {"schema_version": PROVENANCE_SCHEMA, "m2_components": {}, "neural_components": {}, "contact_components": {}, "meta_models": {}}
    seen: set[str] = set()
    formula_artifact = graph["canonical_inputs"]["contact_formula"]
    formula_path = str(Path(formula_artifact.get("node1_path", formula_artifact["path"])).resolve())
    manifest_path = str(Path(split_artifact.get("node1_path", split_artifact["path"])).resolve())
    manifest_sha = graph["canonical_inputs"]["inner_manifest" if args.role == "inner" else "outer_manifest"]["sha256"]
    for planned in jobs:
        split_payload = load_json(Path(planned["split_manifest"]))
        train_parents = split_payload["train_parents"]
        train_sha = split_payload["train_parent_set_sha256"]
        rows, result = validate_completed_base_output(Path(planned["output_dir"]), args.lane, train_sha)
        artifact = result["artifacts"]
        base_dir = Path(planned["output_dir"])
        m2_path = (base_dir / artifact["m2_ridge"]["path"]).resolve()
        neural_path = (base_dir / artifact["neural_head"]["path"]).resolve()
        component_path = (base_dir / artifact["component_receipts"]["path"]).resolve()
        require(sha256_file(m2_path) == artifact["m2_ridge"]["sha256"], f"m2_hash:{base_dir}")
        require(sha256_file(neural_path) == artifact["neural_head"]["sha256"], f"neural_hash:{base_dir}")
        require(sha256_file(component_path) == artifact["component_receipts"]["sha256"], f"component_hash:{base_dir}")
        # RESULT.json is the actual per-split component receipt binding the
        # split, all component artifact hashes, and the formula receipt.
        component_receipt = sha256_file(base_dir / "RESULT.json")
        m2_receipt = neural_receipt = component_receipt
        fold_value = str(planned["inner_fold"]) if args.role == "inner" else "NONE"
        block = {"outer_fold": str(args.outer_fold), "inner_fold": fold_value,
                 "training_parent_framework_clusters": train_parents, "training_parent_set_sha256": train_sha}
        add_provenance_block(provenance["m2_components"], m2_receipt, {**block, "artifact_path": str(m2_path)}, "M2")
        add_provenance_block(provenance["neural_components"], neural_receipt, {**block, "artifact_path": str(neural_path)}, "neural")
        add_provenance_block(provenance["contact_components"], neural_receipt, {**block, "artifact_path": str(neural_path)}, "contact")
        for pred in rows:
            candidate = pred["candidate_id"]
            require(candidate not in seen, f"base_candidate_duplicate:{candidate}")
            seen.add(candidate)
            key = ((args.outer_fold, int(planned["inner_fold"]), candidate) if args.role == "inner" else (args.outer_fold, candidate))
            split = split_index.get(key)
            require(split is not None and split["candidate_role"] == "score", f"base_candidate_not_score:{key}")
            require(pred["teacher_source"] == split["teacher_source"] and pred["parent_framework_cluster"] == split["parent_framework_cluster"], f"base_identity_mismatch:{candidate}")
            r8, r9 = float(pred["truth_R8"]), float(pred["truth_R9"])
            require(math.isclose(float(pred["truth_Rdual"]), min(r8, r9), rel_tol=0, abs_tol=1e-12), f"truth_min:{candidate}")
            evidence.append({
                "schema_version": BASE_ROW_SCHEMA, "evidence_role": role, "candidate_id": candidate,
                "teacher_source": pred["teacher_source"], "parent_framework_cluster": pred["parent_framework_cluster"],
                "outer_fold": str(args.outer_fold), "inner_fold": fold_value,
                "R_8X6B": pred["truth_R8"], "R_9E6Y": pred["truth_R9"], "R_dual_min": pred["truth_Rdual"],
                "M2_R8": pred["M2_R8"], "neural_R8": pred["neural_R8"], "contact_score_R8": pred["contact_score_R8"],
                "M2_R9": pred["M2_R9"], "neural_R9": pred["neural_R9"], "contact_score_R9": pred["contact_score_R9"],
                "split_manifest_path": manifest_path, "split_manifest_sha256": manifest_sha,
                "split_train_parent_set_sha256": split["train_parent_set_sha256"], "split_score_parent_set_sha256": split["score_parent_set_sha256"],
                "M2_training_parent_set_sha256": train_sha, "M2_component_receipt_sha256": m2_receipt, "M2_artifact_path": str(m2_path),
                "neural_training_parent_set_sha256": train_sha, "neural_component_receipt_sha256": neural_receipt, "neural_checkpoint_path": str(neural_path),
                "contact_training_parent_set_sha256": train_sha, "contact_component_receipt_sha256": neural_receipt, "contact_checkpoint_path": str(neural_path),
                "contact_formula_receipt_sha256": CONTACT_FORMULA_SHA, "contact_formula_artifact_path": formula_path,
            })
    expected = {r["candidate_id"] for r in split_rows if int(r["outer_fold"]) == args.outer_fold and r["candidate_role"] == "score"}
    require(seen == expected, f"assembled_base_candidate_closure:{args.role}:{args.outer_fold}:{args.lane}")
    write_tsv(args.output_tsv.resolve(), BASE_COLUMNS, evidence)
    atomic_json(args.provenance_json.resolve(), provenance)
    receipt = {"status": f"PASS_{role}", "rows": len(evidence), "evidence_sha256": sha256_file(args.output_tsv.resolve()),
               "provenance_sha256": sha256_file(args.provenance_json.resolve()), "sealed_evaluation_access_count": 0}
    atomic_json(args.output_tsv.resolve().with_suffix(".assembly_receipt.json"), receipt)
    return receipt


def materialize_meta(args: argparse.Namespace) -> dict[str, Any]:
    graph = load_json(args.job_graph.resolve())
    require(graph.get("schema_version") == SCHEMA, "job_graph_schema")
    require(args.lane in LANES and args.outer_fold in OUTER_FOLDS, "meta_identity")
    inner_path, outer_path = args.inner_evidence_tsv.resolve(), args.outer_base_tsv.resolve()
    inner_rows, outer_rows = read_tsv(inner_path), read_tsv(outer_path)
    require({r["evidence_role"] for r in inner_rows} == {INNER_ROLE}, "meta_fit_role")
    require({r["evidence_role"] for r in outer_rows} == {OUTER_BASE_ROLE}, "meta_score_role")
    fit_parents = sorted({r["parent_framework_cluster"] for r in inner_rows})
    outer_train_sha = outer_rows[0]["split_train_parent_set_sha256"]
    require(parent_sha(fit_parents) == outer_train_sha, "meta_inner_parent_closure")
    require({r["parent_framework_cluster"] for r in outer_rows}.isdisjoint(fit_parents), "meta_outer_parent_leakage")
    stack_dir = args.stack_output_dir.resolve()
    stack_receipt = load_json(stack_dir / "receipt.json")
    model_path = stack_dir / "model.json"
    pred_path = stack_dir / "outer_test_meta_predictions.tsv"
    require(sha256_file(model_path) == stack_receipt["model_json_sha256"], "meta_model_hash")
    require(sha256_file(pred_path) == stack_receipt["prediction_tsv_sha256"], "meta_prediction_hash")
    predictions = {r["candidate_id"]: r for r in read_tsv(pred_path)}
    require(set(predictions) == {r["candidate_id"] for r in outer_rows}, "meta_prediction_candidate_closure")
    outer_artifact = graph["canonical_inputs"]["outer_manifest"]
    outer_manifest = Path(outer_artifact.get("node1_path", outer_artifact["path"])).resolve()
    outer_manifest_sha = graph["canonical_inputs"]["outer_manifest"]["sha256"]
    meta_receipt_sha = sha256_file(stack_dir / "receipt.json")
    provenance = {"schema_version": PROVENANCE_SCHEMA, "m2_components": {}, "neural_components": {}, "contact_components": {}, "meta_models": {
        meta_receipt_sha: {
            "outer_fold": str(args.outer_fold), "inner_fold": "NONE", "artifact_path": str(model_path.resolve()),
            "training_parent_framework_clusters": fit_parents, "training_parent_set_sha256": outer_train_sha,
            "fit_inner_oof_evidence_path": str(inner_path), "fit_inner_oof_evidence_sha256": sha256_file(inner_path),
            "fit_inner_oof_parent_framework_clusters": fit_parents, "fit_inner_oof_parent_set_sha256": outer_train_sha,
            "scaling_fit_parent_framework_clusters": fit_parents, "scaling_fit_parent_set_sha256": outer_train_sha,
            "scaling_contract": "weighted_shared_receptor_zscore_meta_train_only_v1", "fixed_ridge_alpha": 0.001,
            "fixed_condition_number_ceiling": 1000000.0, "parameter_count": 5, "shared_nonnegative_slopes": True,
        }
    }}
    meta_rows = []
    for base in outer_rows:
        pred = predictions[base["candidate_id"]]
        p8, p9, pd = float(pred["prediction_R8"]), float(pred["prediction_R9"]), float(pred["prediction_R_dual_min"])
        require(math.isclose(pd, min(p8, p9), rel_tol=0, abs_tol=1e-12), f"prediction_exact_min:{base['candidate_id']}")
        meta_rows.append({
            "schema_version": META_ROW_SCHEMA, "evidence_role": OUTER_META_ROLE, "candidate_id": base["candidate_id"],
            "teacher_source": base["teacher_source"], "parent_framework_cluster": base["parent_framework_cluster"],
            "outer_fold": str(args.outer_fold), "R_8X6B": base["R_8X6B"], "R_9E6Y": base["R_9E6Y"], "R_dual_min": base["R_dual_min"],
            "prediction_R8": pred["prediction_R8"], "prediction_R9": pred["prediction_R9"], "prediction_R_dual_min": pred["prediction_R_dual_min"],
            "split_manifest_path": str(outer_manifest), "split_manifest_sha256": outer_manifest_sha,
            "split_train_parent_set_sha256": base["split_train_parent_set_sha256"], "split_score_parent_set_sha256": base["split_score_parent_set_sha256"],
            "outer_base_feature_evidence_path": str(outer_path), "outer_base_feature_evidence_sha256": sha256_file(outer_path),
            "fit_inner_oof_evidence_path": str(inner_path), "fit_inner_oof_evidence_sha256": sha256_file(inner_path),
            "fit_inner_oof_parent_set_sha256": outer_train_sha, "scaling_fit_parent_set_sha256": outer_train_sha,
            "meta_training_parent_set_sha256": outer_train_sha, "meta_model_receipt_sha256": meta_receipt_sha,
            "meta_model_artifact_path": str(model_path.resolve()),
        })
    write_tsv(args.output_tsv.resolve(), META_COLUMNS, meta_rows)
    atomic_json(args.provenance_json.resolve(), provenance)
    receipt = {"status": "PASS_OUTER_TEST_META_PREDICTION_MATERIALIZED", "rows": len(meta_rows),
               "fit_inner_oof_sha256": sha256_file(inner_path), "outer_base_sha256": sha256_file(outer_path),
               "meta_prediction_sha256": sha256_file(args.output_tsv.resolve()), "outer_labels_used_for_fit": False,
               "same_rows_fit_and_evaluate_meta": False, "sealed_evaluation_access_count": 0}
    atomic_json(args.output_tsv.resolve().with_suffix(".materialization_receipt.json"), receipt)
    return receipt


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    sub = value.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    for name in ("training-tsv", "outer-manifest", "inner-manifest", "deployment-manifest", "contact-formula", "output-dir"):
        p.add_argument(f"--{name}", type=Path, required=True)
    p.add_argument("--runtime-root", required=True)
    p.add_argument("--node1-plan-root", required=True)
    p.add_argument("--planner-node1-path", required=True)
    p.add_argument("--feature-validator-node1-path", required=True)
    p.add_argument("--stack-fitter-node1-path", required=True)
    p.add_argument("--inner-manifest-node1-path", required=True)
    p.add_argument("--outer-manifest-node1-path", required=True)
    p.add_argument("--contact-formula-node1-path", required=True)
    a = sub.add_parser("assemble-base")
    a.add_argument("--job-graph", type=Path, required=True)
    a.add_argument("--outer-fold", type=int, required=True)
    a.add_argument("--lane", choices=LANES, required=True)
    a.add_argument("--role", choices=("inner", "outer"), required=True)
    a.add_argument("--output-tsv", type=Path, required=True)
    a.add_argument("--provenance-json", type=Path, required=True)
    m = sub.add_parser("materialize-meta")
    m.add_argument("--job-graph", type=Path, required=True)
    m.add_argument("--outer-fold", type=int, required=True)
    m.add_argument("--lane", choices=LANES, required=True)
    m.add_argument("--inner-evidence-tsv", type=Path, required=True)
    m.add_argument("--outer-base-tsv", type=Path, required=True)
    m.add_argument("--stack-output-dir", type=Path, required=True)
    m.add_argument("--output-tsv", type=Path, required=True)
    m.add_argument("--provenance-json", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    result = plan(args) if args.command == "plan" else assemble_base(args) if args.command == "assemble-base" else materialize_meta(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
