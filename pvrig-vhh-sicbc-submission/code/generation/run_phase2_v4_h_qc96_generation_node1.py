#!/usr/bin/env python3
"""Run frozen V4-H parent structures and real RFantibody generation on Node1."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M",
}
CLAIM = (
    "PVRIG-hotspot-conditioned RFantibody sequences; sequence/developability design evidence only, "
    "not Docking geometry, binding, affinity, competition, experimental blocking, or Docking Gold."
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


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str] | None = None) -> None:
    if not rows:
        raise ValueError(f"cannot_write_empty_tsv:{path}")
    if fields is None:
        fields = list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temp = Path(handle.name)
    os.replace(temp, path)


def pdb_chain_sequence(path: Path, chain_id: str = "H") -> str:
    residues: list[str] = []
    seen: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("ATOM") or len(line) < 27 or line[21:22] != chain_id:
                continue
            key = (line[22:26], line[26:27])
            if key in seen:
                continue
            seen.add(key)
            residue = line[17:20].strip().upper()
            if residue not in AA3_TO_1:
                raise RuntimeError(f"unsupported_residue:{path}:{residue}")
            residues.append(AA3_TO_1[residue])
    if not residues:
        raise RuntimeError(f"no_chain_sequence:{path}:{chain_id}")
    return "".join(residues)


def validate_candidate_sequence(sequence: str, parent: Mapping[str, str], mode: str) -> dict[str, Any]:
    if not sequence or set(sequence) - STANDARD_AA:
        raise RuntimeError("candidate_nonstandard_or_empty")
    source = parent["sequence"]
    h1_start, h1_end = int(parent["h1_start_1based"]) - 1, int(parent["h1_end_1based"])
    h2_start, h2_end = int(parent["h2_start_1based"]) - 1, int(parent["h2_end_1based"])
    h3_start = int(parent["h3_start_1based"]) - 1
    fr4 = parent["fr4_tail"]
    source_fr4 = source.rfind(fr4)
    candidate_fr4 = sequence.rfind(fr4)
    if source_fr4 < 0 or candidate_fr4 < 0 or not sequence.endswith(fr4):
        raise RuntimeError("candidate_fr4_anchor_or_suffix_failed")
    if sequence[:h1_start] != source[:h1_start]:
        raise RuntimeError("candidate_fr1_changed")
    if mode == "H3" and sequence[h1_start:h1_end] != source[h1_start:h1_end]:
        raise RuntimeError("candidate_h1_changed_in_h3_mode")
    if sequence[h1_end:h3_start] != source[h1_end:h3_start]:
        raise RuntimeError("candidate_protected_h1_to_h3_interval_changed")
    if sequence[h2_start:h2_end] != source[h2_start:h2_end]:
        raise RuntimeError("candidate_h2_changed")
    if sequence[candidate_fr4:] != source[source_fr4:]:
        raise RuntimeError("candidate_fr4_bytes_changed")
    cdr1 = sequence[h1_start:h1_end]
    cdr2 = sequence[h2_start:h2_end]
    cdr3 = sequence[h3_start:candidate_fr4]
    if not 5 <= len(cdr3) <= 20:
        raise RuntimeError(f"candidate_cdr3_length_outside_frozen_range:{len(cdr3)}")
    return {
        "cdr1": cdr1,
        "cdr2": cdr2,
        "cdr3": cdr3,
        "cdr3_length": len(cdr3),
        "candidate_fr4_start_1based": candidate_fr4 + 1,
    }


def select_exact_unique(
    rows: Sequence[dict[str, Any]], *, target: int, seed: str,
    excluded_sequence_hashes: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded_sequence_hashes = excluded_sequence_hashes or set()
    representative: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: str(item["raw_candidate_id"])):
        representative.setdefault(str(row["sequence_sha256"]), dict(row))
    ranked: list[dict[str, Any]] = []
    for row in representative.values():
        row["h1_selection_hash"] = sha256_text(
            "|".join(
                (
                    seed,
                    str(row["parent_framework_cluster"]),
                    str(row["target_patch_id"]),
                    str(row["design_mode"]),
                    str(row["raw_candidate_id"]),
                    str(row["sequence_sha256"]),
                )
            )
        )
        ranked.append(row)
    ranked.sort(key=lambda item: (str(item["h1_selection_hash"]), str(item["raw_candidate_id"])))
    available = [row for row in ranked if str(row["sequence_sha256"]) not in excluded_sequence_hashes]
    if len(available) < target:
        raise RuntimeError(f"stratum_exact_unique_capacity_after_global_dedup:{len(available)}:{target}")
    selected = available[:target]
    for index, row in enumerate(selected, 1):
        row["h1_selection_rank_in_stratum"] = index
        row["candidate_id"] = str(row["raw_candidate_id"]).replace("RAWV4H__", "V4H__", 1)
    return selected


def verify_hash_map(root: Path, mapping: Mapping[str, str]) -> None:
    observed_files = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file() and path.name != "complete.json"}
    if observed_files != set(mapping):
        raise RuntimeError(f"output_file_set_changed:{root}:{len(observed_files)}:{len(mapping)}")
    for relative, digest in mapping.items():
        path = root / relative
        if path.is_symlink() or sha256(path) != digest:
            raise RuntimeError(f"output_file_hash_changed:{root}:{relative}")


def build_hash_map(root: Path) -> dict[str, str]:
    symlinks = [path for path in root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise RuntimeError(f"symlink_in_new_output:{symlinks[0]}")
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "complete.json"
    }


class Runtime:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.config_path = self.root / "config/generation_config.json"
        self.config = json.loads(self.config_path.read_text())
        self.parents = read_tsv(self.root / "manifests/parent12_queue.tsv")
        self.tasks = read_tsv(self.root / "manifests/generation_tasks.tsv")
        self.freeze_path = self.root / "IMPLEMENTATION_FREEZE.json"
        self.freeze = json.loads(self.freeze_path.read_text())
        self.status = self.root / "status"
        self.logs = self.root / "logs"
        self.runtime = self.root / "runtime"
        self.outputs = self.root / "outputs"

    def verify_package(
        self, verify_tools: bool = True, verify_capacity: bool = True, require_zero_work: bool = False
    ) -> dict[str, Any]:
        expected_root = Path(self.config["remote_root"])
        if self.root != expected_root or not str(self.root).startswith("/data1/qlyu/projects/"):
            raise RuntimeError(f"noncanonical_production_root:{self.root}")
        if self.freeze.get("status") != "FROZEN_BEFORE_ANY_REAL_GENERATION":
            raise RuntimeError("implementation_not_frozen")
        for rel, digest in self.freeze.get("package_hashes", {}).items():
            path = self.root / rel
            if not path.is_file() or path.is_symlink() or sha256(path) != digest:
                raise RuntimeError(f"frozen_package_hash_mismatch:{rel}")
        if len(self.parents) != 12 or len({row["parent_framework_cluster"] for row in self.parents}) != 12:
            raise RuntimeError("parent12_queue_closure_failed")
        if [int(row["queue_rank"]) for row in self.parents] != list(range(1, 13)):
            raise RuntimeError("parent_queue_rank_order_failed")
        if len(self.tasks) != 72:
            raise RuntimeError("generation_task_count_not_72")
        if sum(int(row["expected_raw_records"]) for row in self.tasks) != 2592:
            raise RuntimeError("generation_raw_count_not_2592")
        expected_strata = Counter(
            (row["parent_framework_cluster"], row["patch_id"], row["design_mode"])
            for row in self.tasks
        )
        if len(expected_strata) != 72 or set(expected_strata.values()) != {1}:
            raise RuntimeError("generation_strata_closure_failed")
        if any(int(value) != 0 for value in self.config["label_path_access"].values()):
            raise RuntimeError("label_or_model_path_access_nonzero")
        policy = self.config["resource_policy"]
        if len(policy["gpu_ids"]) != 4 or len(policy["cpu_sets"]) != 4:
            raise RuntimeError("resource_policy_must_have_exactly_four_workers")
        if len(set(map(int, policy["gpu_ids"]))) != 4:
            raise RuntimeError("gpu_ids_not_four_unique")
        parsed_cpu_sets: list[set[int]] = []
        for spec in policy["cpu_sets"]:
            values: set[int] = set()
            for part in str(spec).split(","):
                if "-" in part:
                    lo, hi = map(int, part.split("-", 1)); values.update(range(lo, hi + 1))
                else:
                    values.add(int(part))
            parsed_cpu_sets.append(values)
        for left in range(len(parsed_cpu_sets)):
            for right in range(left + 1, len(parsed_cpu_sets)):
                if parsed_cpu_sets[left] & parsed_cpu_sets[right]:
                    raise RuntimeError("cpu_sets_overlap")
        cpu_union = set().union(*parsed_cpu_sets)
        node_cpu_count = os.cpu_count() or 0
        if any(len(values) != 8 for values in parsed_cpu_sets) or len(cpu_union) != 32:
            raise RuntimeError("cpu_sets_must_be_four_by_eight_exactly_32")
        if any(cpu < 0 or cpu >= node_cpu_count for cpu in cpu_union):
            raise RuntimeError("cpu_set_id_outside_node_cpu_count")
        if os.environ.get("PYTHONOPTIMIZE"):
            raise RuntimeError("pythonoptimize_forbidden")
        forbidden_environment_tokens = tuple(self.config["forbidden_environment_tokens"])
        for key, value in os.environ.items():
            combined = f"{key}={value}".lower()
            if any(token.lower() in combined for token in forbidden_environment_tokens):
                raise RuntimeError(f"forbidden_label_model_or_docking_environment:{key}")
        if require_zero_work:
            forbidden = []
            for relative in ("runtime/parents", "runtime/generation_tasks", "outputs", "qc"):
                path = self.root / relative
                forbidden.extend(item for item in path.rglob("*") if item.is_file()) if path.exists() else None
            if forbidden:
                raise RuntimeError(f"zero_work_preflight_found_scientific_output:{forbidden[0]}")
        if verify_tools:
            for key, spec in self.config["tools"].items():
                path = Path(spec["path"])
                if not path.is_file() or path.is_symlink() or sha256(path) != spec["sha256"]:
                    raise RuntimeError(f"tool_hash_mismatch:{key}")
        capacity: dict[str, Any] = {"checked": False}
        if verify_capacity:
            capacity = self._capacity_gate()
        return {
            "schema_version": "phase2_v4_h_qc96_h0_zero_work_preflight_v1",
            "status": "PASS_ZERO_WORK_PREFLIGHT",
            "parent_count": 12,
            "task_count": 72,
            "raw_design_target": 2592,
            "exact_unique_target": 1440,
            "resource_policy": self.config["resource_policy"],
            "capacity": capacity,
            "label_path_access": self.config["label_path_access"],
            "claim_boundary": CLAIM,
        }

    def _capacity_gate(self) -> dict[str, Any]:
        policy = self.config["resource_policy"]
        gpu_ids = [int(value) for value in policy["gpu_ids"]]
        command = [
            "nvidia-smi", f"--id={','.join(map(str, gpu_ids))}",
            "--query-gpu=index,memory.used,utilization.gpu", "--format=csv,noheader,nounits",
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        observed = []
        for line in completed.stdout.splitlines():
            index, memory, util = [int(value.strip()) for value in line.split(",")]
            observed.append({"index": index, "memory_used_mib": memory, "utilization_percent": util})
        if {row["index"] for row in observed} != set(gpu_ids):
            raise RuntimeError("gpu_id_capacity_gate_failed")
        if any(row["memory_used_mib"] > 2048 or row["utilization_percent"] > 25 for row in observed):
            raise RuntimeError(f"selected_gpu_busy:{observed}")
        cpus = os.cpu_count() or 0
        if cpus < int(policy["minimum_node_cpu_count"]):
            raise RuntimeError(f"insufficient_node_cpu_count:{cpus}")
        free = shutil.disk_usage(self.root.parent).free
        if free < int(policy["minimum_free_disk_bytes"]):
            raise RuntimeError(f"insufficient_ssd_free_bytes:{free}")
        return {"checked": True, "gpu": observed, "node_cpu_count": cpus, "free_disk_bytes": free}

    def clean_env(self, gpu: int, cpu_threads: int = 8) -> dict[str, str]:
        allowed = {
            "HOME": os.environ.get("HOME", "/home/qlyu"),
            "USER": os.environ.get("USER", "qlyu"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PATH": "/data1/qlyu/anaconda3/envs/boltz/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "CUDA_VISIBLE_DEVICES": str(gpu),
            "OMP_NUM_THREADS": str(cpu_threads),
            "MKL_NUM_THREADS": str(cpu_threads),
            "OPENBLAS_NUM_THREADS": str(cpu_threads),
            "NUMEXPR_NUM_THREADS": str(cpu_threads),
            "PYTHONHASHSEED": "0",
            "TOKENIZERS_PARALLELISM": "false",
        }
        return allowed

    def command(self, argv: Sequence[str], log: Path, gpu: int, cpus: str, timeout_key: str) -> None:
        log.parent.mkdir(parents=True, exist_ok=True)
        cpu_threads = sum(
            (int(part.split("-", 1)[1]) - int(part.split("-", 1)[0]) + 1) if "-" in part else 1
            for part in cpus.split(",")
        )
        timeout_seconds = int(self.config["command_timeouts_seconds"][timeout_key])
        with log.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(
                ["taskset", "-c", cpus, *argv], stdout=handle, stderr=subprocess.STDOUT,
                env=self.clean_env(gpu, cpu_threads), text=True, start_new_session=True,
            )
            try:
                return_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=30)
                raise RuntimeError(f"command_timeout:{timeout_key}:{timeout_seconds}:{argv[0]}:{log}") from error
        if return_code:
            raise RuntimeError(f"command_failed:{return_code}:{argv[0]}:{log}")

    def run_parent(self, parent: Mapping[str, str], gpu: int, cpus: str) -> dict[str, Any]:
        parent_id = parent["parent_id"]
        final = self.runtime / "parents" / parent_id
        marker = final / "complete.json"
        if marker.is_file():
            payload = json.loads(marker.read_text())
            hlt = final / "frameworks" / f"{parent_id}_HLT.pdb"
            if payload.get("status") == "PASS_PARENT_STRUCTURE" and hlt.is_file() and sha256(hlt) == payload["hlt_sha256"]:
                verify_hash_map(final, payload["output_sha256"])
                return {**payload, "execution": "reused"}
            raise RuntimeError(f"invalid_existing_parent_output:{parent_id}")
        attempts = self.runtime / "attempts/parents"
        attempts.mkdir(parents=True, exist_ok=True)
        attempt = attempts / f"{parent_id}.{os.getpid()}.{gpu}"
        if attempt.exists():
            shutil.rmtree(attempt)
        for directory in ("monomer", "frameworks", "reports", "logs"):
            (attempt / directory).mkdir(parents=True, exist_ok=True)
        raw = attempt / "monomer" / f"{parent_id}_raw.pdb"
        norm = attempt / "monomer" / f"{parent_id}_chainH.pdb"
        hlt = attempt / "frameworks" / f"{parent_id}_HLT.pdb"
        nbb = self.config["tools"]["nanobodybuilder2"]["path"]
        python = self.config["tools"]["python"]["path"]
        self.command([nbb, "-H", parent["sequence"], "-o", str(raw), "-v"], attempt / "logs/nbb2.log", gpu, cpus, "nanobodybuilder2")
        helper = self.root / "scripts"
        self.command(
            [python, str(helper / "normalize_pdb_chain.py"), "--in-pdb", str(raw), "--out-pdb", str(norm),
             "--chain-id", "H", "--expected-residue-count", str(len(parent["sequence"]))],
            attempt / "logs/normalize.log", gpu, cpus, "helper",
        )
        self.command(
            [python, str(helper / "validate_pdb_sequence.py"), "--pdb", str(norm), "--chain", "H",
             "--expected-seq", parent["sequence"], "--out-json", str(attempt / "reports/sequence_validation.json")],
            attempt / "logs/sequence_validation.log", gpu, cpus, "helper",
        )
        self.command(
            [python, str(helper / "pdb_geometry_qc.py"), "--pdb", str(norm), "--chain", "H",
             "--out-json", str(attempt / "reports/geometry_qc.json")],
            attempt / "logs/geometry_qc.log", gpu, cpus, "helper",
        )
        self.command(
            [python, str(helper / "make_rfantibody_hlt_framework.py"), "--input-pdb", str(norm),
             "--output-pdb", str(hlt), "--input-chain", "H", "--expected-residues", str(len(parent["sequence"])),
             "--h1", f"{parent['h1_start_1based']}-{parent['h1_end_1based']}",
             "--h2", f"{parent['h2_start_1based']}-{parent['h2_end_1based']}",
             "--h3", f"{parent['h3_start_1based']}-{parent['h3_end_1based']}",
             "--audit", str(attempt / "reports/hlt_audit.json")],
            attempt / "logs/hlt.log", gpu, cpus, "helper",
        )
        if pdb_chain_sequence(norm) != parent["sequence"]:
            raise RuntimeError(f"parent_structure_sequence_mismatch:{parent_id}")
        if pdb_chain_sequence(hlt) != parent["sequence"]:
            raise RuntimeError(f"parent_hlt_sequence_mismatch:{parent_id}")
        payload = {
            "schema_version": "phase2_v4_h_parent_structure_v1", "status": "PASS_PARENT_STRUCTURE",
            "parent_id": parent_id, "parent_framework_cluster": parent["parent_framework_cluster"],
            "sequence_sha256": parent["sequence_sha256"], "raw_pdb_sha256": sha256(raw),
            "normalized_pdb_sha256": sha256(norm), "hlt_sha256": sha256(hlt), "gpu": gpu,
            "nanobodybuilder2_sha256": self.config["tools"]["nanobodybuilder2"]["sha256"],
            "config_sha256": sha256(self.config_path),
            "finished_at_utc": now(), "claim_boundary": CLAIM,
        }
        payload["output_sha256"] = build_hash_map(attempt)
        atomic_json(attempt / "complete.json", payload, 0o444)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(attempt, final)
        return payload

    def run_generation_task(self, task: Mapping[str, str], gpu: int, cpus: str) -> dict[str, Any]:
        task_id = task["task_id"]
        final = self.runtime / "generation_tasks" / task_id
        marker = final / "complete.json"
        if marker.is_file():
            payload = json.loads(marker.read_text())
            if payload.get("status") == "PASS_GENERATION_TASK" and int(payload.get("sequence_pdb_count", 0)) == 36:
                verify_hash_map(final, payload["output_sha256"])
                framework = self.runtime / "parents" / task["parent_id"] / "frameworks" / f"{task['parent_id']}_HLT.pdb"
                target = self.root / "inputs/pvrig_8x6b_chainT.pdb"
                if payload.get("framework_hlt_sha256") != sha256(framework) or payload.get("target_sha256") != sha256(target):
                    raise RuntimeError(f"generation_task_bound_input_changed:{task_id}")
                if payload.get("config_sha256") != sha256(self.config_path):
                    raise RuntimeError(f"generation_task_config_changed:{task_id}")
                return {**payload, "execution": "reused"}
            raise RuntimeError(f"invalid_existing_generation_task:{task_id}")
        attempt_root = self.runtime / "attempts/generation"
        attempt_root.mkdir(parents=True, exist_ok=True)
        attempt = attempt_root / f"{task_id}.{os.getpid()}.{gpu}"
        if attempt.exists():
            shutil.rmtree(attempt)
        for directory in ("backbones", "sequences", "logs", "tmp"):
            (attempt / directory).mkdir(parents=True, exist_ok=True)
        framework = self.runtime / "parents" / task["parent_id"] / "frameworks" / f"{task['parent_id']}_HLT.pdb"
        target = self.root / "inputs/pvrig_8x6b_chainT.pdb"
        rf = self.config["tools"]
        rfd_cmd = [
            rf["rfdiffusion"]["path"], "--target", str(target), "--framework", str(framework),
            "--output", str(attempt / "backbones/design"), "--num-designs", task["target_backbones"],
            "--design-loops", task["design_loops"], "--hotspots", task["hotspots_pdb"],
            "--weights", rf["rfdiffusion_weight"]["path"], "--diffuser-t", task["diffuser_t"],
            "--deterministic", "--no-trajectory",
        ]
        self.command(rfd_cmd, attempt / "logs/rfdiffusion.log", gpu, cpus, "rfdiffusion")
        backbones = sorted((attempt / "backbones").glob("design_*.pdb"))
        trbs = sorted((attempt / "backbones").glob("design_*.trb"))
        if len(backbones) != 12 or len(trbs) != 12:
            raise RuntimeError(f"backbone_count_mismatch:{task_id}:{len(backbones)}:{len(trbs)}")
        parent = next(row for row in self.parents if row["parent_id"] == task["parent_id"])
        for backbone in backbones:
            validate_candidate_sequence(pdb_chain_sequence(backbone), parent, task["design_mode"])
        mpnn_cmd = [
            rf["rfantibody_env"]["path"], rf["proteinmpnn_script"]["path"],
            "-pdbdir", str(attempt / "backbones"), "-outpdbdir", str(attempt / "sequences"),
            "-loop_string", task["mpnn_loops"], "-seqs_per_struct", task["sequences_per_backbone"],
            "-temperature", task["mpnn_temperature"], "-checkpoint_path", rf["proteinmpnn_weight"]["path"],
            "-omit_AAs", task["omit_aas"], "-augment_eps", task["augment_eps"],
            "-checkpoint_name", str(attempt / "tmp/mpnn_checkpoint.txt"), "-deterministic",
        ]
        self.command(mpnn_cmd, attempt / "logs/proteinmpnn.log", gpu, cpus, "proteinmpnn")
        sequences = sorted((attempt / "sequences").glob("design_*_dldesign_*.pdb"))
        if len(sequences) != 36:
            raise RuntimeError(f"sequence_pdb_count_mismatch:{task_id}:{len(sequences)}")
        payload = {
            "schema_version": "phase2_v4_h_generation_task_v1", "status": "PASS_GENERATION_TASK",
            "task_id": task_id, "parent_id": task["parent_id"], "patch_id": task["patch_id"],
            "design_mode": task["design_mode"], "backbone_count": 12, "trb_count": 12,
            "sequence_pdb_count": 36, "rfdiffusion_design_indices": list(range(12)),
            "rfdiffusion_randomness_contract": "--deterministic; bound inference source resets numeric seed to design index",
            "proteinmpnn_randomness_contract": "-deterministic; bound script hard-codes random,NumPy,torch,CUDA seed 42",
            "framework_hlt_sha256": sha256(framework), "target_sha256": sha256(target),
            "config_sha256": sha256(self.config_path),
            "tool_sha256": {key: spec["sha256"] for key, spec in rf.items()},
            "gpu": gpu, "finished_at_utc": now(), "claim_boundary": CLAIM,
        }
        payload["output_sha256"] = build_hash_map(attempt)
        atomic_json(attempt / "complete.json", payload, 0o444)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(attempt, final)
        return payload

    def _parallel_workers(self, rows: Sequence[Mapping[str, str]], function: Any) -> list[dict[str, Any]]:
        policy = self.config["resource_policy"]
        gpu_ids = [int(value) for value in policy["gpu_ids"]]
        cpu_sets = list(policy["cpu_sets"])
        worker_count = len(gpu_ids)
        shards = [list(rows[index::worker_count]) for index in range(worker_count)]

        def worker(worker_index: int) -> list[dict[str, Any]]:
            return [function(row, gpu_ids[worker_index], cpu_sets[worker_index]) for row in shards[worker_index]]

        output: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(worker, index) for index in range(worker_count)]
            for future in as_completed(futures):
                output.extend(future.result())
        return output

    def collect(self) -> dict[str, Any]:
        parent_by_id = {row["parent_id"]: row for row in self.parents}
        raw_rows: list[dict[str, Any]] = []
        for task in self.tasks:
            task_dir = self.runtime / "generation_tasks" / task["task_id"]
            marker = json.loads((task_dir / "complete.json").read_text())
            if marker.get("status") != "PASS_GENERATION_TASK":
                raise RuntimeError(f"task_not_complete:{task['task_id']}")
            parent = parent_by_id[task["parent_id"]]
            task_pairs: set[tuple[int, int]] = set()
            for path in sorted((task_dir / "sequences").glob("design_*_dldesign_*.pdb")):
                stem = path.stem
                parts = stem.split("_")
                if len(parts) != 4 or parts[0] != "design" or parts[2] != "dldesign":
                    raise RuntimeError(f"unparsed_sequence_pdb:{path.name}")
                backbone_index, mpnn_index = int(parts[1]), int(parts[3])
                task_pairs.add((backbone_index, mpnn_index))
                sequence = pdb_chain_sequence(path)
                cdrs = validate_candidate_sequence(sequence, parent, task["design_mode"])
                designed_edit = cdrs["cdr3"] != parent["cdr3"] or (
                    task["design_mode"] == "H1H3" and cdrs["cdr1"] != parent["cdr1"]
                )
                raw_id = f"RAWV4H__{task['parent_id']}__{task['patch_id']}__{task['design_mode']}__B{backbone_index:02d}__M{mpnn_index:02d}"
                backbone = task_dir / "backbones" / f"design_{backbone_index}.pdb"
                raw_rows.append({
                    "raw_candidate_id": raw_id, "sequence": sequence, "sequence_sha256": sha256_text(sequence),
                    "sequence_length": len(sequence), "parent_id": task["parent_id"],
                    "parent_framework_cluster": task["parent_framework_cluster"],
                    "parent_queue_rank": int(parent["queue_rank"]), "parent_sequence_sha256": parent["sequence_sha256"],
                    "target_patch_id": task["patch_id"], "design_mode": task["design_mode"],
                    "design_task_id": task["task_id"], "design_loops": task["design_loops"],
                    "designed_regions": task["mpnn_loops"], "hotspots_pdb": task["hotspots_pdb"],
                    "hotspots_uniprot": task["hotspots_uniprot"], "backbone_index": backbone_index,
                    "mpnn_index": mpnn_index, "rfdiffusion_design_index": backbone_index,
                    "proteinmpnn_deterministic_seed_contract": 42,
                    "cdr1_before": parent["cdr1"], "cdr2_before": parent["cdr2"], "cdr3_before": parent["cdr3"],
                    "cdr1_after": cdrs["cdr1"], "cdr2_after": cdrs["cdr2"], "cdr3_after": cdrs["cdr3"],
                    "designed_region_edit_present": str(designed_edit).lower(),
                    "cdr3_length": cdrs["cdr3_length"], "source_backbone_pdb_sha256": sha256(backbone),
                    "source_sequence_pdb_sha256": sha256(path), "claim_boundary": CLAIM,
                })
            expected_pairs = {(backbone, mpnn) for backbone in range(12) for mpnn in range(3)}
            if task_pairs != expected_pairs:
                raise RuntimeError(f"task_cartesian_b00_b11_m00_m02_failed:{task['task_id']}")
        if len(raw_rows) != 2592 or len({row["raw_candidate_id"] for row in raw_rows}) != 2592:
            raise RuntimeError(f"raw_2592_closure_failed:{len(raw_rows)}")
        exclusion_rows = read_tsv(self.root / "manifests/excluded_candidate_sequence_sha256.tsv")
        exclusion_hashes = {row["sequence_sha256"] for row in exclusion_rows}
        parent_hashes = {row["sequence_sha256"] for row in self.parents}
        preregistered_blocked_hashes = exclusion_hashes | parent_hashes
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in raw_rows:
            grouped[(row["parent_framework_cluster"], row["target_patch_id"], row["design_mode"])].append(row)
        if len(grouped) != 72 or set(map(len, grouped.values())) != {36}:
            raise RuntimeError("raw_stratum_72x36_closure_failed")
        selected: list[dict[str, Any]] = []
        stratum_audit: list[dict[str, Any]] = []
        parent_rank = {row["parent_framework_cluster"]: int(row["queue_rank"]) for row in self.parents}
        patch_rank = {"A_CENTER": 0, "B_LOWER": 1, "C_CROSS": 2}
        mode_rank = {"H3": 0, "H1H3": 1}
        ordered_keys = sorted(grouped, key=lambda key: (parent_rank[key[0]], patch_rank[key[1]], mode_rank[key[2]]))
        globally_used_sequence_hashes: set[str] = set()
        for priority, key in enumerate(ordered_keys, 1):
            unique_count = len({row["sequence_sha256"] for row in grouped[key]})
            excluded_old_or_parent_count = len(
                {str(row["sequence_sha256"]) for row in grouped[key]} & preregistered_blocked_hashes
            )
            chosen = select_exact_unique(
                [row for row in grouped[key] if row["designed_region_edit_present"] == "true"],
                target=20, seed=self.config["generation"]["h1_selection_seed"],
                excluded_sequence_hashes=globally_used_sequence_hashes | preregistered_blocked_hashes,
            )
            selected.extend(chosen)
            globally_used_sequence_hashes.update(str(row["sequence_sha256"]) for row in chosen)
            stratum_audit.append({
                "parent_framework_cluster": key[0], "target_patch_id": key[1], "design_mode": key[2],
                "global_dedup_priority": priority,
                "raw_count": 36, "exact_unique_count": unique_count,
                "excluded_parent_legacy7087_rfantibody1000_or_calibration_count": excluded_old_or_parent_count,
                "selected_count": 20,
                "capacity_state": "PASS_EXACT_UNIQUE_20",
            })
        selected.sort(key=lambda row: (int(row["parent_queue_rank"]), row["target_patch_id"], row["design_mode"], int(row["h1_selection_rank_in_stratum"])))
        if len(selected) != 1440 or len({row["candidate_id"] for row in selected}) != 1440 or len({row["sequence_sha256"] for row in selected}) != 1440:
            raise RuntimeError("selected_1440_exact_unique_global_closure_failed")
        selected_hashes = {str(row["sequence_sha256"]) for row in selected}
        if selected_hashes & parent_hashes:
            raise RuntimeError("selected_exact_parent_sequence_overlap")
        if selected_hashes & exclusion_hashes:
            raise RuntimeError("selected_legacy7087_or_calibration_exact_overlap")
        self.outputs.mkdir(parents=True, exist_ok=True)
        raw_path = self.outputs / "v4_h_h1_raw2592.tsv"
        selected_path = self.outputs / "v4_h_h1_candidates1440.tsv"
        strata_path = self.outputs / "v4_h_h1_stratum_capacity.tsv"
        fasta_path = self.outputs / "v4_h_h1_candidates1440.fasta"
        write_tsv(raw_path, raw_rows)
        write_tsv(selected_path, selected)
        write_tsv(strata_path, stratum_audit)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.outputs, delete=False) as handle:
            for row in selected:
                handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")
            fasta_temp = Path(handle.name)
        os.replace(fasta_temp, fasta_path)
        audit = {
            "schema_version": "phase2_v4_h_qc96_h1_generation_audit_v1",
            "status": "PASS_V4_H_H1_1440_EXACT_UNIQUE_GENERATED",
            "parent_count": 12, "stratum_count": 72, "raw_record_count": 2592,
            "selected_exact_unique_count": 1440, "selected_per_stratum": 20,
            "framework_and_fr4_byte_protection": "PASS_ALL_SELECTED",
            "cdr2_frozen": "PASS_ALL_SELECTED", "global_exact_sequence_uniqueness": "PASS_1440_OF_1440",
            "cross_stratum_dedup_priority": "parent_queue_rank_then_A_B_C_then_H3_H1H3",
            "rfdiffusion_design_indices": list(range(12)),
            "rfdiffusion_randomness_contract": "--deterministic; numeric reset seed equals design index in bound source",
            "proteinmpnn_randomness_contract": "-deterministic; hard-coded seed 42 in bound script",
            "outputs": {
                raw_path.name: sha256(raw_path), selected_path.name: sha256(selected_path),
                strata_path.name: sha256(strata_path), fasta_path.name: sha256(fasta_path),
            },
            "label_path_access": self.config["label_path_access"], "claim_boundary": CLAIM,
        }
        audit_path = self.outputs / "v4_h_h1_generation_audit.json"
        atomic_json(audit_path, audit, 0o444)
        receipt = {
            **audit, "schema_version": "phase2_v4_h_qc96_h1_generation_receipt_v1",
            "published_at_utc": now(), "audit_sha256": sha256(audit_path),
            "implementation_freeze_sha256": sha256(self.freeze_path),
            "receipt_publication_order": "LAST_AFTER_12x6x20_SEQUENCE_AND_PROVENANCE_CLOSURE",
        }
        atomic_json(self.outputs / "v4_h_h1_generation_receipt.json", receipt, 0o444)
        return receipt

    def run(self) -> dict[str, Any]:
        self.status.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        lock = (self.status / "generation.lock").open("w")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("generation_runner_already_active") from error
        self.verify_package(verify_tools=True, verify_capacity=True, require_zero_work=False)
        atomic_json(self.status / "generation.running.json", {
            "status": "RUNNING_V4_H_H1_REAL_RFANTIBODY", "pid": os.getpid(), "started_at_utc": now(),
            "resource_policy": self.config["resource_policy"], "label_path_access": self.config["label_path_access"],
            "claim_boundary": CLAIM,
        })
        parent_results = self._parallel_workers(self.parents, self.run_parent)
        atomic_json(self.status / "parent_structures.complete.json", {
            "status": "PASS_12_PARENT_STRUCTURES", "records": len(parent_results), "finished_at_utc": now(),
            "label_path_access": self.config["label_path_access"], "claim_boundary": CLAIM,
        }, 0o444)
        task_results = self._parallel_workers(self.tasks, self.run_generation_task)
        if len(task_results) != 72:
            raise RuntimeError("generation_task_result_count_not_72")
        receipt = self.collect()
        atomic_json(self.status / "generation.complete.json", {
            "status": receipt["status"], "pid": os.getpid(), "finished_at_utc": now(),
            "generation_receipt_sha256": sha256(self.outputs / "v4_h_h1_generation_receipt.json"),
            "label_path_access": self.config["label_path_access"], "claim_boundary": CLAIM,
        }, 0o444)
        (self.status / "generation.running.json").unlink(missing_ok=True)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.smoke_test:
        print(json.dumps({"status": "PASS_V4_H_GENERATION_RUNNER_SMOKE", "root": str(root)}, sort_keys=True))
        return 0
    try:
        runtime = Runtime(root)
        result = runtime.verify_package(require_zero_work=True) if args.preflight else runtime.run()
        if args.preflight:
            atomic_json(runtime.status / "zero_work_preflight.json", result, 0o444)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except BaseException as error:
        failure = {
            "status": "FAIL_V4_H_H0_OR_H1", "failed_at_utc": now(), "pid": os.getpid(),
            "error": f"{type(error).__name__}:{error}", "claim_boundary": CLAIM,
        }
        try:
            atomic_json(root / "status/generation.failed.json", failure, 0o444)
        except Exception:
            pass
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
