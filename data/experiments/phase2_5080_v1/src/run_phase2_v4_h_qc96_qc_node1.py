#!/usr/bin/env python3
"""Run frozen H2 Fast-QC, H3 Full-QC, and H4 pure-QC V4-H selection."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

CLAIM = (
    "Sequence/developability QC-qualified prospective candidate panel only; not Docking geometry, "
    "binding, affinity, competition, experimental blocking, or Docking Gold."
)
FORBIDDEN_FIELD_TOKENS = (
    "model_score", "model_prediction", "docking_score", "docking_label", "geometry_label",
    "r_dual", "g_tier", "binding_label", "affinity", "experimental_label", "blocker_label",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any], mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        temp = Path(handle.name)
    temp.chmod(mode)
    os.replace(temp, path)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temp = Path(handle.name)
    os.replace(temp, path)


def hard_pass(row: Mapping[str, str]) -> bool:
    value = str(row.get("hard_fail", "")).strip().lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"invalid_hard_fail:{row.get('candidate_id', '')}:{value}")
    return value == "false"


def compute_h4_capacity(
    candidates: Sequence[Mapping[str, str]], full_by_id: Mapping[str, Mapping[str, str]]
) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in candidates:
        grouped[str(row["parent_framework_cluster"])].append(row)
    capacity: list[dict[str, Any]] = []
    ready: list[tuple[int, str]] = []
    for parent, rows in grouped.items():
        queue_rank = {int(row["parent_queue_rank"]) for row in rows}
        if len(queue_rank) != 1:
            raise RuntimeError(f"parent_queue_rank_inconsistent:{parent}")
        strata: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
        full_pass_count = 0
        for row in rows:
            cid = str(row["candidate_id"])
            full = full_by_id.get(cid)
            if full is not None and hard_pass(full):
                full_pass_count += 1
                strata[(str(row["target_patch_id"]), str(row["design_mode"]))].append(row)
        stratum_counts = {
            f"{patch}|{mode}": len(strata.get((patch, mode), []))
            for patch in ("A_CENTER", "B_LOWER", "C_CROSS")
            for mode in ("H3", "H1H3")
        }
        is_ready = full_pass_count >= 24 and len(strata) == 6 and min(stratum_counts.values()) >= 4
        capacity.append({
            "parent_queue_rank": next(iter(queue_rank)), "parent_framework_cluster": parent,
            "full_qc_hard_pass_count": full_pass_count,
            **{f"full_pass_{key.replace('|', '_')}": value for key, value in stratum_counts.items()},
            "capacity_state": "QC_CAPACITY_READY" if is_ready else "INSUFFICIENT_QC_CAPACITY",
        })
        if is_ready:
            ready.append((next(iter(queue_rank)), parent))
    capacity.sort(key=lambda row: int(row["parent_queue_rank"]))
    ready.sort()
    return capacity, ready


def h4_select(
    candidates: Sequence[Mapping[str, str]],
    full_by_id: Mapping[str, Mapping[str, str]],
    *,
    seed: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in candidates:
        grouped[str(row["parent_framework_cluster"])].append(row)
    capacity, ready = compute_h4_capacity(candidates, full_by_id)
    if len(ready) < 4:
        raise RuntimeError(f"FAIL_V4_H_INSUFFICIENT_QC_QUALIFIED_PARENT_CAPACITY:{len(ready)}")
    selected_parents = {parent for _, parent in ready[:4]}
    selected: list[dict[str, Any]] = []
    for parent in sorted(selected_parents, key=lambda value: next(rank for rank, item in ready if item == value)):
        parent_rows = grouped[parent]
        for patch in ("A_CENTER", "B_LOWER", "C_CROSS"):
            for mode in ("H3", "H1H3"):
                rows = [
                    dict(row) for row in parent_rows
                    if row["target_patch_id"] == patch and row["design_mode"] == mode
                    and hard_pass(full_by_id[str(row["candidate_id"])])
                ]
                for row in rows:
                    row["h4_selection_hash"] = sha256_text(
                        "|".join((seed, str(row["candidate_id"]), str(row["sequence_sha256"])))
                    )
                rows.sort(key=lambda row: (row["h4_selection_hash"], row["candidate_id"]))
                if len(rows) < 4:
                    raise RuntimeError(f"selected_parent_stratum_lt4:{parent}:{patch}:{mode}")
                for rank, row in enumerate(rows[:4], 1):
                    row["h4_selection_rank_in_stratum"] = rank
                    row["selection_stratum"] = f"{parent}|{patch}|{mode}"
                    row["model_split"] = "V4_H_QC96_PROSPECTIVE_HOLDOUT"
                    row["tnp_supervision_state"] = "NOT_RUN_DEFERRED_NA"
                    row["tnp_score"] = ""
                    row["tnp_red_flag"] = ""
                    row["tnp_yellow_flag"] = ""
                    row["full_qc_and_docking_policy"] = (
                        "frozen_after_label_free_full_qc;no_model_reselection;no_replacement;"
                        "independent_dual_receptor_docking_only_after_prediction_freeze"
                    )
                    row["claim_boundary"] = CLAIM
                    selected.append(row)
    selected.sort(key=lambda row: (int(row["parent_queue_rank"]), row["target_patch_id"], row["design_mode"], int(row["h4_selection_rank_in_stratum"])))
    if len(selected) != 96 or len({row["candidate_id"] for row in selected}) != 96:
        raise RuntimeError("h4_96_id_closure_failed")
    if Counter(row["parent_framework_cluster"] for row in selected) != Counter({parent: 24 for parent in selected_parents}):
        raise RuntimeError("h4_4x24_parent_closure_failed")
    stratum_counts = Counter(row["selection_stratum"] for row in selected)
    if len(stratum_counts) != 24 or set(stratum_counts.values()) != {4}:
        raise RuntimeError("h4_24x4_stratum_closure_failed")
    return selected, capacity


class QCRuntime:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.config = json.loads((self.root / "config/generation_config.json").read_text())
        self.freeze_path = self.root / "IMPLEMENTATION_FREEZE.json"
        self.freeze = json.loads(self.freeze_path.read_text())
        self.generation_receipt_path = self.root / "outputs/v4_h_h1_generation_receipt.json"
        self.input_manifest = self.root / "outputs/v4_h_h1_candidates1440.tsv"
        self.fasta = self.root / "outputs/v4_h_h1_candidates1440.fasta"
        self.cascade = self.root / "qc/cascade"
        self.outputs = self.root / "qc/outputs"
        self.status = self.root / "status"

    def validate_input(self, verify_runtime: bool = True) -> list[dict[str, str]]:
        if self.root != Path(self.config["remote_root"]) or not str(self.root).startswith("/data1/qlyu/projects/"):
            raise RuntimeError("noncanonical_qc_root")
        if self.freeze.get("status") != "FROZEN_BEFORE_ANY_REAL_GENERATION":
            raise RuntimeError("implementation_not_frozen")
        for rel, digest in self.freeze.get("package_hashes", {}).items():
            path = self.root / rel
            if not path.is_file() or path.is_symlink() or sha256(path) != digest:
                raise RuntimeError(f"frozen_package_hash_mismatch:{rel}")
        receipt = json.loads(self.generation_receipt_path.read_text())
        if receipt.get("status") != "PASS_V4_H_H1_1440_EXACT_UNIQUE_GENERATED":
            raise RuntimeError("h1_generation_receipt_not_pass")
        if receipt.get("outputs", {}).get(self.input_manifest.name) != sha256(self.input_manifest):
            raise RuntimeError("h1_manifest_receipt_hash_mismatch")
        if receipt.get("outputs", {}).get(self.fasta.name) != sha256(self.fasta):
            raise RuntimeError("h1_fasta_receipt_hash_mismatch")
        fields, rows = read_tsv(self.input_manifest)
        if len(rows) != 1440 or len({row["candidate_id"] for row in rows}) != 1440 or len({row["sequence_sha256"] for row in rows}) != 1440:
            raise RuntimeError("h1_1440_input_closure_failed")
        if any(any(token in field.lower() for token in FORBIDDEN_FIELD_TOKENS) for field in fields):
            raise RuntimeError("forbidden_label_or_model_field_in_h1_manifest")
        strata = Counter((row["parent_framework_cluster"], row["target_patch_id"], row["design_mode"]) for row in rows)
        if len(strata) != 72 or set(strata.values()) != {20}:
            raise RuntimeError("h1_12x6x20_stratum_closure_failed")
        if any(int(value) != 0 for value in self.config["label_path_access"].values()):
            raise RuntimeError("label_or_model_path_access_nonzero")
        if verify_runtime:
            qc = self.config["qc"]
            for key in ("screen", "python", "runtime_manifest"):
                spec = qc[key]
                path = Path(spec["path"])
                if not path.is_file() or path.is_symlink() or sha256(path) != spec["sha256"]:
                    raise RuntimeError(f"qc_runtime_hash_mismatch:{key}")
            runtime_manifest = json.loads(Path(qc["runtime_manifest"]["path"]).read_text())
            if runtime_manifest.get("status") != "PASS_SSD_RUNTIME_CLOSURE_FROZEN" or runtime_manifest.get("forbidden_runtime_prefix_hits") != 0:
                raise RuntimeError("qc_runtime_manifest_not_ssd_closed")
        return rows

    def command(self, stage: str) -> list[str]:
        qc = self.config["qc"]
        runtime = Path(qc["runtime_root"])
        return [
            qc["python"]["path"], qc["screen"]["path"], str(self.fasta), "-o", str(self.cascade),
            "--qc-bin", str(runtime / "bin/vhh-competition-qc"),
            "--local-positive-cdr-csv", str(runtime / "references/local_pvrig_positive_vhh_cdrs.csv"),
            "--muscle-bin", str(runtime / "bin/muscle"), "--stage", stage,
            "--fast-chunk-size", "60", "--full-chunk-size", "60", "--chunk-jobs", "12",
            "--full-chunk-jobs", "12", "--workers", "2", "--tnp-ncores", "1",
            "--identity-cache-size", "500000", "--full-qc-limit", "0", "--geometry-limit", "1440",
            "--geometry-pool-size", "1440", "--geometry-cluster-limit", "1440", "--skip-final-diversity",
        ]

    def env(self) -> dict[str, str]:
        runtime = Path(self.config["qc"]["runtime_root"])
        return {
            "HOME": os.environ.get("HOME", "/home/qlyu"), "USER": os.environ.get("USER", "qlyu"),
            "LANG": os.environ.get("LANG", "C.UTF-8"), "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PATH": f"{runtime / 'bin'}:/data1/qlyu/anaconda3/envs/boltz/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PYTHONPATH": f"{runtime / 'validator_src'}:{runtime / 'src'}",
            "AB_DATA_VALIDATOR_SRC": str(runtime / "validator_src"),
            "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1", "TOKENIZERS_PARALLELISM": "false", "CUDA_VISIBLE_DEVICES": "",
        }

    def run_stage(self, stage: str) -> None:
        logs = self.root / "qc/logs"
        logs.mkdir(parents=True, exist_ok=True)
        command = self.command(stage)
        if "--full-run-tnp" in command:
            raise RuntimeError("tnp_execution_forbidden_by_frozen_policy")
        atomic_json(logs / f"{stage}.command.json", {"command": command, "started_at_utc": now()})
        with (logs / f"{stage}.stdout.log").open("w") as out, (logs / f"{stage}.stderr.log").open("w") as err:
            completed = subprocess.run(command, env=self.env(), stdout=out, stderr=err, check=False, text=True)
        if completed.returncode:
            raise RuntimeError(f"qc_stage_failed:{stage}:{completed.returncode}")

    @staticmethod
    def verify_sequence_closure(rows: Sequence[Mapping[str, str]], source_by: Mapping[str, Mapping[str, str]], label: str) -> None:
        seen: set[str] = set()
        for row in rows:
            cid = row.get("candidate_id", "")
            if cid in seen or cid not in source_by:
                raise RuntimeError(f"{label}_id_closure:{cid}")
            seen.add(cid)
            sequence = row.get("sequence", "")
            source = source_by[cid]
            if not sequence or sequence != source["sequence"] or sha256_text(sequence) != source["sequence_sha256"]:
                raise RuntimeError(f"{label}_sequence_sha256_closure:{cid}")

    def persist_failure_terminal(
        self, source: Sequence[Mapping[str, str]], fast_by: Mapping[str, Mapping[str, str]],
        full_by: Mapping[str, Mapping[str, str]], reason: str,
    ) -> None:
        self.outputs.mkdir(parents=True, exist_ok=True)
        capacity, ready = compute_h4_capacity(source, full_by)
        capacity_path = self.outputs / "v4_h_h3_parent_capacity.tsv"
        write_tsv(capacity_path, capacity, list(capacity[0]))
        joined = []
        for row in source:
            cid = row["candidate_id"]
            fast = fast_by.get(cid)
            full = full_by.get(cid)
            joined.append({
                "candidate_id": cid, "sequence_sha256": row["sequence_sha256"],
                "parent_queue_rank": row["parent_queue_rank"], "parent_framework_cluster": row["parent_framework_cluster"],
                "target_patch_id": row["target_patch_id"], "design_mode": row["design_mode"],
                "fast_hard_fail": "" if fast is None else str(not hard_pass(fast)),
                "full_qc_state": (
                    ("NOT_RUN_FAST_HARD_FAIL" if fast is not None and not hard_pass(fast) else "NOT_RUN_NO_FULL_SURVIVOR_TERMINAL")
                    if full is None else ("HARD_PASS" if hard_pass(full) else "HARD_FAIL")
                ),
                "tnp_supervision_state": "NOT_RUN_DEFERRED_NA", "tnp_score": "", "tnp_red_flag": "", "tnp_yellow_flag": "",
            })
        states_path = self.outputs / "v4_h_h2_h3_candidate_qc_states.tsv"
        write_tsv(states_path, joined, list(joined[0]))
        audit = {
            "schema_version": "phase2_v4_h_qc96_h2_h4_failure_audit_v1",
            "status": "FAIL_V4_H_INSUFFICIENT_QC_QUALIFIED_PARENT_CAPACITY",
            "reason": reason, "input_rows": 1440, "fast_rows": len(fast_by), "full_rows": len(full_by),
            "qc_capacity_ready_parent_count": len(ready), "tnp_run": False,
            "tnp_policy": "DEFERRED_THREE_STATE_NA_NO_IMPUTATION", "label_path_access": self.config["label_path_access"],
            "output_sha256": {capacity_path.name: sha256(capacity_path), states_path.name: sha256(states_path)},
            "claim_boundary": CLAIM,
        }
        audit_path = self.outputs / "qc96_failure_audit_v1.json"
        atomic_json(audit_path, audit, 0o444)
        atomic_json(self.outputs / "qc96_failure_receipt_v1.json", {
            **audit, "schema_version": "phase2_v4_h_qc96_failure_receipt_v1", "published_at_utc": now(),
            "audit_sha256": sha256(audit_path), "implementation_freeze_sha256": sha256(self.freeze_path),
            "qc96_manifest_published": False,
        }, 0o444)

    def publish(self, source: list[dict[str, str]]) -> dict[str, Any]:
        state = json.loads((self.cascade / "cascade_state.json").read_text())
        for stage in ("prepare", "fast", "merge_fast", "full", "merge_full"):
            if state.get("stages", {}).get(stage, {}).get("status") != "complete":
                raise RuntimeError(f"cascade_stage_not_complete:{stage}")
        _, fast = read_tsv(self.cascade / "fast_merged.tsv")
        _, shortlist = read_tsv(self.cascade / "full_qc_shortlist.tsv")
        _, full = read_tsv(self.cascade / "full_merged.tsv")
        source_by = {row["candidate_id"]: row for row in source}
        self.verify_sequence_closure(fast, source_by, "fast")
        self.verify_sequence_closure(shortlist, source_by, "shortlist")
        self.verify_sequence_closure(full, source_by, "full")
        source_ids = {row["candidate_id"] for row in source}
        fast_by = {row["candidate_id"]: row for row in fast}
        full_by = {row["candidate_id"]: row for row in full}
        if len(fast) != 1440 or set(fast_by) != source_ids:
            raise RuntimeError("fast_1440_exact_id_closure_failed")
        fast_pass = {cid for cid, row in fast_by.items() if hard_pass(row)}
        if set(row["candidate_id"] for row in shortlist) != fast_pass or set(full_by) != fast_pass:
            raise RuntimeError("full_all_fast_survivors_no_cap_no_replacement_closure_failed")
        expected_fast_chunks = math.ceil(1440 / 60)
        expected_full_chunks = math.ceil(len(fast_pass) / 60) if fast_pass else 0
        if len(list((self.cascade / "fast_chunks").glob("chunk_*/complete.json"))) != expected_fast_chunks:
            raise RuntimeError("fast_chunk_completion_count_failed")
        if len(list((self.cascade / "full_chunks").glob("chunk_*/complete.json"))) != expected_full_chunks:
            raise RuntimeError("full_chunk_completion_count_failed")
        self.outputs.mkdir(parents=True, exist_ok=True)
        joined: list[dict[str, Any]] = []
        for row in source:
            cid = row["candidate_id"]
            joined.append({
                "candidate_id": cid, "sequence_sha256": row["sequence_sha256"],
                "parent_queue_rank": row["parent_queue_rank"], "parent_framework_cluster": row["parent_framework_cluster"],
                "target_patch_id": row["target_patch_id"], "design_mode": row["design_mode"],
                "fast_hard_fail": str(not hard_pass(fast_by[cid])),
                "full_qc_state": "NOT_RUN_FAST_HARD_FAIL" if cid not in full_by else ("HARD_PASS" if hard_pass(full_by[cid]) else "HARD_FAIL"),
                "tnp_supervision_state": "NOT_RUN_DEFERRED_NA", "tnp_score": "", "tnp_red_flag": "", "tnp_yellow_flag": "",
            })
        attrition_path = self.outputs / "v4_h_h2_h3_candidate_qc_states.tsv"
        write_tsv(attrition_path, joined, list(joined[0]))
        capacity, ready = compute_h4_capacity(source, full_by)
        capacity_path = self.outputs / "v4_h_h3_parent_capacity.tsv"
        write_tsv(capacity_path, capacity, list(capacity[0]))
        if len(ready) < 4:
            self.persist_failure_terminal(source, fast_by, full_by, f"ready_parent_count={len(ready)}")
            raise RuntimeError(f"FAIL_V4_H_INSUFFICIENT_QC_QUALIFIED_PARENT_CAPACITY:{len(ready)}")
        selected, capacity = h4_select(source, full_by, seed=self.config["qc"]["h4_selection_seed"])
        manifest_path = self.outputs / "qc96_manifest_v1.tsv"
        manifest_fields = [
            "candidate_id", "sequence_sha256", "sequence", "parent_id", "parent_framework_cluster",
            "parent_queue_rank", "target_patch_id", "design_mode", "cdr1_after", "cdr2_after", "cdr3_after",
            "cdr3_length", "h4_selection_hash", "h4_selection_rank_in_stratum", "selection_stratum", "model_split",
            "tnp_supervision_state", "tnp_score", "tnp_red_flag", "tnp_yellow_flag", "full_qc_and_docking_policy",
            "claim_boundary",
        ]
        write_tsv(manifest_path, selected, manifest_fields)
        audit = {
            "schema_version": "phase2_v4_h_qc96_h2_h4_audit_v1",
            "status": "PASS_V4_H_QC96_FROZEN_AFTER_LABEL_FREE_FULL_QC",
            "input_rows": 1440, "fast_hard_pass": len(fast_pass), "fast_hard_fail": 1440 - len(fast_pass),
            "full_rows": len(full), "full_hard_pass": sum(hard_pass(row) for row in full),
            "full_hard_fail": sum(not hard_pass(row) for row in full),
            "qc_capacity_ready_parent_count": sum(row["capacity_state"] == "QC_CAPACITY_READY" for row in capacity),
            "selected_rows": 96, "selected_parent_count": 4, "selected_per_parent": 24,
            "selected_per_stratum": 4, "tnp_run": False, "tnp_policy": "DEFERRED_THREE_STATE_NA_NO_IMPUTATION",
            "no_model_or_docking_reselection": True, "no_replacement": True,
            "label_path_access": self.config["label_path_access"],
            "output_sha256": {
                attrition_path.name: sha256(attrition_path), capacity_path.name: sha256(capacity_path),
                manifest_path.name: sha256(manifest_path),
            }, "claim_boundary": CLAIM,
        }
        audit_path = self.outputs / "qc96_audit_v1.json"
        atomic_json(audit_path, audit, 0o444)
        receipt = {
            **audit, "schema_version": "phase2_v4_h_qc96_receipt_v1", "published_at_utc": now(),
            "audit_sha256": sha256(audit_path), "implementation_freeze_sha256": sha256(self.freeze_path),
            "receipt_publication_order": "LAST_AFTER_H2_H3_AND_4x6x4_H4_CLOSURE",
        }
        atomic_json(self.outputs / "qc96_receipt_v1.json", receipt, 0o444)
        return receipt

    def run(self) -> dict[str, Any]:
        self.status.mkdir(parents=True, exist_ok=True)
        lock = (self.status / "qc.lock").open("w")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("qc_runner_already_active") from error
        source = self.validate_input(verify_runtime=True)
        atomic_json(self.status / "qc.running.json", {
            "status": "RUNNING_V4_H_H2_H3_H4", "pid": os.getpid(), "started_at_utc": now(),
            "maximum_cpu_workers": 24, "gpu_count": 0, "tnp_policy": "DEFERRED_THREE_STATE_NA_NO_IMPUTATION",
            "label_path_access": self.config["label_path_access"], "claim_boundary": CLAIM,
        })
        self.run_stage("prepare")
        self.run_stage("fast")
        _, fast_rows = read_tsv(self.cascade / "fast_merged.tsv")
        source_by = {row["candidate_id"]: row for row in source}
        self.verify_sequence_closure(fast_rows, source_by, "fast")
        fast_by = {row["candidate_id"]: row for row in fast_rows}
        if not any(hard_pass(row) for row in fast_rows):
            self.persist_failure_terminal(source, fast_by, {}, "zero_fast_qc_survivors")
            raise RuntimeError("FAIL_V4_H_INSUFFICIENT_QC_QUALIFIED_PARENT_CAPACITY:zero_fast_survivors")
        self.run_stage("full")
        receipt = self.publish(source)
        atomic_json(self.status / "qc.complete.json", {
            "status": receipt["status"], "pid": os.getpid(), "finished_at_utc": now(),
            "receipt_sha256": sha256(self.outputs / "qc96_receipt_v1.json"),
            "label_path_access": self.config["label_path_access"], "claim_boundary": CLAIM,
        }, 0o444)
        (self.status / "qc.running.json").unlink(missing_ok=True)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.smoke_test:
        print(json.dumps({"status": "PASS_V4_H_QC_RUNNER_SMOKE", "root": str(root)}, sort_keys=True))
        return 0
    try:
        runtime = QCRuntime(root)
        if args.preflight:
            rows = runtime.validate_input()
            result = {"status": "PASS_H2_H4_ZERO_WORK_PREFLIGHT", "candidate_count": len(rows), "label_path_access": runtime.config["label_path_access"], "claim_boundary": CLAIM}
        else:
            result = runtime.run()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except BaseException as error:
        failure = {"status": "FAIL_V4_H_H2_H3_OR_H4", "failed_at_utc": now(), "pid": os.getpid(), "error": f"{type(error).__name__}:{error}", "claim_boundary": CLAIM}
        try:
            atomic_json(root / "status/qc.failed.json", failure, 0o444)
        except Exception:
            pass
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
