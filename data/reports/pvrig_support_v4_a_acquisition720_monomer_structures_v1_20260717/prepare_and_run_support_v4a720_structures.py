#!/usr/bin/env python3
"""Prepare, run, and audit the label-free Support V4-A 720 monomer package.

All 720 frozen Full-QC hard-pass sequences are attempted with NanoBodyBuilder2
as the primary monomer method and IgFold as an independent crosscheck.  The
candidate set is never selected or replaced using structure results.  This
program never reads docking, geometry, model-score, affinity, or experimental
label files.

The frozen policy is no replacement and no imputation, including when either
structure method fails for an individual candidate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import queue
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UPSTREAM_ROOT = Path("/data1/qlyu/projects/pvrig_support_v4_a_acquisition720_full_qc_v1_20260717")
UPSTREAM = {
    "acquisition_manifest": (
        UPSTREAM_ROOT / "inputs/support_v4_a_future_teacher_acquisition_pool_v1.tsv",
        "73454cbf8194d3faa5cad354a5b2f31f433e317d5222a6cd59906775fb56bfca",
    ),
    "full_merged": (
        UPSTREAM_ROOT / "cascade/full_merged.tsv",
        "c35ffb8848172c2aa86885360dc963498f241023259271ec5c6638fa1200fa90",
    ),
    "terminal_summary": (
        UPSTREAM_ROOT / "outputs/full_qc_terminal_summary.json",
        "4b2cdd48b2b459b19bc3514e5ebad11be6e43045d30d502b7e76773905c7792d",
    ),
    "runner_complete": (
        UPSTREAM_ROOT / "status/runner.complete.json",
        "b8a15ee86fb20975979f274d836e22b3d345e75f08019a170cea83e0cf2a302c",
    ),
    "terminal_process_closure": (
        UPSTREAM_ROOT / "status/terminal_process_closure_v1.json",
        "8c5cee5c427322e1c4e6c6ddca1e3ae768907715fca79fb783ee0ce4affa53f8",
    ),
    "acquisition_readiness_receipt": (
        UPSTREAM_ROOT / "inputs/support_v4_a_acquisition_readiness_receipt_v1.json",
        "440e675b1a6e39771a830d282e7e575dfe7ce24f7cb91c2966f71f577c655181",
    ),
}

EXPECTED_COUNT = 720
EXPECTED_PARENT_COUNT = 20
EXPECTED_GPUS = (0, 1, 2, 3)
MAX_PARALLEL = 4
THREADS_PER_WORKER = 8
MAX_CPU_THREADS = 32
NBB2 = Path("/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2")
IGFOLD_PYTHON = Path("/data1/qlyu/software/envs/vhh-igfold/bin/python")
IGFOLD_SCRIPT = Path("/data1/qlyu/software/vhh_eval_tools/igfold_predict.py")
CACHE_ROOT = Path("/data1/qlyu/pvrig_support_v4a720_structure_cache_v1")
CLAIM_BOUNDARY = (
    "label_free_computational_monomer_structure_and_cross_method_uncertainty_only;"
    "not_docking_geometry_binding_affinity_competition_experimental_blocking_"
    "blocker_probability_or_docking_gold"
)

AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty TSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise RuntimeError(f"invalid boolean text: {value!r}")
    return normalized == "true"


def validate_upstream() -> dict[str, Any]:
    observed: dict[str, str] = {}
    for name, (path, expected) in UPSTREAM.items():
        if not path.is_file():
            raise RuntimeError(f"missing frozen upstream file: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"frozen upstream hash mismatch for {name}: {actual}")
        observed[name] = actual

    terminal = json.loads(UPSTREAM["terminal_summary"][0].read_text(encoding="utf-8"))
    complete = json.loads(UPSTREAM["runner_complete"][0].read_text(encoding="utf-8"))
    closure = json.loads(UPSTREAM["terminal_process_closure"][0].read_text(encoding="utf-8"))
    if terminal.get("status") != "PASS_SUPPORT_V4_A_ACQUISITION720_SEQUENCE_DEVELOPABILITY_FULL_QC_COMPLETE":
        raise RuntimeError("upstream terminal summary is not authoritative PASS")
    if complete.get("status") != terminal.get("status"):
        raise RuntimeError("upstream runner complete status differs from terminal summary")
    for key in ("input_rows", "fast_rows", "fast_hard_pass", "full_rows", "full_hard_pass"):
        if terminal.get(key) != EXPECTED_COUNT:
            raise RuntimeError(f"upstream count drift: {key}={terminal.get(key)!r}")
    if terminal.get("fast_hard_fail") != 0 or terminal.get("full_hard_fail") != 0:
        raise RuntimeError("upstream contains a hard-fail candidate")
    if terminal.get("input_manifest_sha256") != UPSTREAM["acquisition_manifest"][1]:
        raise RuntimeError("terminal summary does not bind acquisition manifest")
    if terminal.get("cascade_output_sha256", {}).get("full_merged.tsv") != UPSTREAM["full_merged"][1]:
        raise RuntimeError("terminal summary does not bind full_merged.tsv")
    if closure.get("status") != "PASS_TERMINAL_PROCESS_CLOSED" or closure.get("runner_pid_alive") is not False:
        raise RuntimeError("upstream process lifecycle is not authoritatively closed")
    if closure.get("runner_complete", {}).get("sha256") != UPSTREAM["runner_complete"][1]:
        raise RuntimeError("terminal process closure does not bind runner.complete.json")
    if closure.get("terminal_summary", {}).get("sha256") != UPSTREAM["terminal_summary"][1]:
        raise RuntimeError("terminal process closure does not bind terminal summary")
    if terminal.get("label_path_access") != {"docking": 0, "experimental": 0, "geometry": 0, "model": 0}:
        raise RuntimeError("upstream label-path access is not zero")
    return {"observed_sha256": observed, "terminal": terminal, "closure": closure}


def build_manifest() -> list[dict[str, str]]:
    validate_upstream()
    acquisition_rows = read_tsv(UPSTREAM["acquisition_manifest"][0])
    full_rows = read_tsv(UPSTREAM["full_merged"][0])
    if len(acquisition_rows) != EXPECTED_COUNT or len(full_rows) != EXPECTED_COUNT:
        raise RuntimeError("upstream TSV row count drift")
    acquisition = {row["candidate_id"]: row for row in acquisition_rows}
    full = {row["candidate_id"]: row for row in full_rows}
    if len(acquisition) != EXPECTED_COUNT or len(full) != EXPECTED_COUNT or set(acquisition) != set(full):
        raise RuntimeError("upstream candidate identity set mismatch or duplicate")

    rows: list[dict[str, str]] = []
    for cid in sorted(acquisition):
        source, qc = acquisition[cid], full[cid]
        sequence = source["sequence"]
        if source["sequence_sha256"] != sha256_text(sequence):
            raise RuntimeError(f"input manifest sequence hash mismatch: {cid}")
        if qc["sequence"] != sequence:
            raise RuntimeError(f"Full-QC sequence differs from acquisition manifest: {cid}")
        if parse_bool(qc["hard_fail"]):
            raise RuntimeError(f"unexpected Full-QC hard fail: {cid}")
        if qc["official_validator_pass"] != "PASS" or not parse_bool(qc["ANARCI_status"]):
            raise RuntimeError(f"Full-QC validator/numbering closure failed: {cid}")
        rows.append({
            "candidate_id": cid,
            "sequence": sequence,
            "sequence_sha256": source["sequence_sha256"],
            "parent_id": source["parent_id"],
            "parent_framework_cluster": source["parent_framework_cluster"],
            "parent_role": source["parent_role"],
            "target_patch_id": source["target_patch_id"],
            "design_mode": source["design_mode"],
            "acquisition_role": source["acquisition_role"],
            "full_qc_hard_fail": "False",
            "official_validator_pass": qc["official_validator_pass"],
            "ANARCI_status": qc["ANARCI_status"],
            "structure_selection_rule": "ALL_720_FROZEN_FULL_QC_HARD_PASS_NO_REPLACEMENT",
            "claim_boundary": CLAIM_BOUNDARY,
        })
    if len({row["parent_id"] for row in rows}) != EXPECTED_PARENT_COUNT:
        raise RuntimeError("parent count drift")
    return rows


def tool_hashes() -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, path in (("nanobodybuilder2", NBB2), ("igfold_python", IGFOLD_PYTHON), ("igfold_script", IGFOLD_SCRIPT)):
        if not path.is_file():
            raise RuntimeError(f"required tool missing: {path}")
        observed[name] = sha256_file(path)
    return observed


def prepare(root: Path) -> dict[str, Any]:
    if root.exists() and any(root.iterdir()):
        allowed = {"scripts", "tests"}
        extras = {path.name for path in root.iterdir()} - allowed
        if extras:
            raise RuntimeError(f"refusing non-empty structure root; unexpected entries={sorted(extras)}")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("inputs", "outputs/nbb2", "outputs/igfold", "logs", "status/candidates", "status/failures", "audit"):
        (root / name).mkdir(parents=True, exist_ok=True)
    rows = build_manifest()
    manifest = root / "inputs/support_v4a720_structure_manifest.tsv"
    fasta = root / "inputs/support_v4a720_structure_manifest.fasta"
    write_tsv(manifest, rows)
    fasta.write_text("".join(f">{row['candidate_id']}\n{row['sequence']}\n" for row in rows), encoding="utf-8")
    script_path = Path(__file__).resolve()
    prereg = {
        "schema_version": "pvrig_support_v4_a_acquisition720_monomer_structures_preregistration_v1",
        "status": "FROZEN_BEFORE_FIRST_MONOMER_COMPUTE",
        "frozen_at_utc": utc_now(),
        "candidate_policy": {
            "candidate_count": EXPECTED_COUNT,
            "parent_count": EXPECTED_PARENT_COUNT,
            "selection": "all and only exact frozen upstream Full-QC hard-pass candidates",
            "replacement": "NO_REPLACEMENT",
            "label_or_score_access": {"docking": 0, "geometry": 0, "model": 0, "experimental": 0},
            "candidate_ids_sha256": sha256_text("\n".join(row["candidate_id"] for row in rows) + "\n"),
            "candidate_id_sequence_sha256_pairs_sha256": sha256_text(
                "".join(f"{row['candidate_id']}\t{row['sequence_sha256']}\n" for row in rows)
            ),
        },
        "upstream": {
            name: {"path": str(path), "sha256": expected} for name, (path, expected) in UPSTREAM.items()
        },
        "derived_inputs": {
            "manifest_path": str(manifest),
            "manifest_sha256": sha256_file(manifest),
            "fasta_path": str(fasta),
            "fasta_sha256": sha256_file(fasta),
            "runner_path": str(script_path),
            "runner_sha256": sha256_file(script_path),
        },
        "tools": {"paths": {"nanobodybuilder2": str(NBB2), "igfold_python": str(IGFOLD_PYTHON), "igfold_script": str(IGFOLD_SCRIPT)}, "sha256": tool_hashes()},
        "protocol": {
            "primary": "NanoBodyBuilder2 refined; on nonzero exit one explicit unrefined fallback attempt; state recorded per candidate",
            "crosscheck": "IgFold one model for every one of the same frozen 720 candidates; no result-conditioned subset",
            "failed_candidate_policy": "record terminal failure; continue all attempts; no replacement; no imputation",
            "resume_policy": "only per-candidate hash-validated terminal records are skipped",
            "crosscheck_use": "monomer uncertainty and backbone sanity only; no binding/blocking interpretation",
        },
        "resources": {
            "node": "node1", "ssd_only": True, "gpu_ids": list(EXPECTED_GPUS),
            "max_gpu_workers": MAX_PARALLEL, "threads_per_worker": THREADS_PER_WORKER,
            "maximum_cpu_threads": MAX_CPU_THREADS,
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    prereg_path = root / "PREREGISTRATION.json"
    write_json(prereg_path, prereg)
    write_json(root / "status/prepared.json", {
        "status": "PASS_SUPPORT_V4A720_MONOMER_PACKAGE_PREPARED",
        "candidate_count": EXPECTED_COUNT,
        "manifest_sha256": sha256_file(manifest),
        "preregistration_sha256": sha256_file(prereg_path),
        "prepared_at_utc": utc_now(),
        "claim_boundary": CLAIM_BOUNDARY,
    })
    return prereg


def load_frozen_manifest(root: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    prereg_path = root / "PREREGISTRATION.json"
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    if prereg.get("status") != "FROZEN_BEFORE_FIRST_MONOMER_COMPUTE":
        raise RuntimeError("preregistration is not frozen")
    if prereg["derived_inputs"]["runner_sha256"] != sha256_file(Path(__file__).resolve()):
        raise RuntimeError("runner differs from frozen preregistration")
    validate_upstream()
    manifest = Path(prereg["derived_inputs"]["manifest_path"])
    if manifest != root / "inputs/support_v4a720_structure_manifest.tsv":
        raise RuntimeError("manifest path is not canonical under output root")
    if sha256_file(manifest) != prereg["derived_inputs"]["manifest_sha256"]:
        raise RuntimeError("derived manifest hash drift")
    rows = read_tsv(manifest)
    if len(rows) != EXPECTED_COUNT or len({row["candidate_id"] for row in rows}) != EXPECTED_COUNT:
        raise RuntimeError("derived manifest identity closure failed")
    pairs = sha256_text("".join(f"{row['candidate_id']}\t{row['sequence_sha256']}\n" for row in rows))
    if pairs != prereg["candidate_policy"]["candidate_id_sequence_sha256_pairs_sha256"]:
        raise RuntimeError("candidate ID/sequence hash-pair closure failed")
    if tool_hashes() != prereg["tools"]["sha256"]:
        raise RuntimeError("tool hash drift")
    return prereg, rows


def preflight(root: Path) -> dict[str, Any]:
    prereg, rows = load_frozen_manifest(root)
    gpu_query = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
    )
    observed_gpu_ids = {int(line.split(",", 1)[0].strip()) for line in gpu_query.stdout.splitlines() if line.strip()}
    if not set(EXPECTED_GPUS).issubset(observed_gpu_ids):
        raise RuntimeError(f"required GPU IDs absent: observed={sorted(observed_gpu_ids)}")
    if os.cpu_count() is None or os.cpu_count() < MAX_CPU_THREADS:
        raise RuntimeError("node exposes fewer than 32 CPUs")
    candidate_artifacts = list((root / "status/candidates").glob("*.terminal.json"))
    if candidate_artifacts or list((root / "outputs/nbb2").glob("*/*")) or list((root / "outputs/igfold").glob("*/*")):
        raise RuntimeError("zero-work preflight found candidate structure artifacts")
    payload = {
        "schema_version": "pvrig_support_v4a720_monomer_zero_work_preflight_v1",
        "status": "PASS_ZERO_WORK_PREFLIGHT",
        "candidate_count": len(rows),
        "preregistration_sha256": sha256_file(root / "PREREGISTRATION.json"),
        "runner_sha256": prereg["derived_inputs"]["runner_sha256"],
        "gpu_inventory": gpu_query.stdout.splitlines(),
        "resource_policy": prereg["resources"],
        "candidate_structure_artifacts_before_launch": 0,
        "checked_at_utc": utc_now(),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(root / "status/zero_work_preflight.json", payload)
    return payload


def pdb_chains(path: Path) -> dict[str, list[tuple[tuple[str, str], str]]]:
    result: dict[str, list[tuple[tuple[str, str], str]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54 or line[12:16].strip() != "CA":
            continue
        chain, key, aa3 = line[21], (line[22:26], line[26]), line[17:20].strip()
        token = (chain, *key)
        if token in seen:
            continue
        seen.add(token)
        result.setdefault(chain, []).append((key, aa3))
    return result


def normalize_matching_chain(source: Path, destination: Path, sequence: str) -> str:
    chains = pdb_chains(source)
    matching = [chain for chain, residues in chains.items() if "".join(AA3.get(aa3, "X") for _, aa3 in residues) == sequence]
    if len(matching) != 1:
        lengths = {chain: len(residues) for chain, residues in chains.items()}
        raise RuntimeError(f"expected exactly one exact sequence chain in {source}; observed={lengths}")
    source_chain = matching[0]
    residue_map: dict[tuple[str, str], int] = {}
    output: list[str] = []
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54 or line[21] != source_chain:
            continue
        padded = line.ljust(80)
        key = (padded[22:26], padded[26])
        residue_map.setdefault(key, len(residue_map) + 1)
        output.append(f"{padded[:21]}A{residue_map[key]:4d} {padded[27:]}".rstrip())
    if len(residue_map) != len(sequence):
        raise RuntimeError(f"normalized residue count mismatch: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(output) + "\nTER\nEND\n", encoding="utf-8")
    normalized = "".join(AA3.get(aa3, "X") for _, aa3 in pdb_chains(destination).get("A", []))
    if normalized != sequence:
        raise RuntimeError(f"normalized sequence mismatch: {destination}")
    return source_chain


def ca_geometry(path: Path) -> dict[str, Any]:
    coords: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("ATOM  ") and len(line) >= 54 and line[21] == "A" and line[12:16].strip() == "CA":
            coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    distances = [math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3))) for a, b in zip(coords, coords[1:])]
    return {
        "ca_count": len(coords),
        "adjacent_ca_min": min(distances) if distances else None,
        "adjacent_ca_max": max(distances) if distances else None,
        "adjacent_ca_gt_6A": sum(value > 6.0 for value in distances),
        "likely_sane_backbone": bool(distances) and sum(2.5 <= value <= 4.5 for value in distances) >= 0.8 * len(distances),
    }


def run_logged(command: list[str], log: Path, env: dict[str, str]) -> tuple[int, str]:
    started = utc_now()
    process = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        f"$ {shlex.join(command)}\n[started_at] {started}\n{process.stdout}\n"
        f"[finished_at] {utc_now()}\n[exit_code] {process.returncode}\n",
        encoding="utf-8",
    )
    return int(process.returncode), sha256_file(log)


def validate_existing_terminal(root: Path, row: dict[str, str]) -> dict[str, Any] | None:
    path = root / "status/candidates" / f"{row['candidate_id']}.terminal.json"
    if not path.is_file():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("candidate_id") != row["candidate_id"] or record.get("sequence_sha256") != row["sequence_sha256"]:
        raise RuntimeError(f"existing candidate terminal binding drift: {row['candidate_id']}")
    for method in ("nbb2", "igfold"):
        method_record = record.get(method, {})
        if method_record.get("status") == "SUCCESS":
            artifact = Path(method_record["pdb"])
            if not artifact.is_file() or sha256_file(artifact) != method_record["pdb_sha256"]:
                raise RuntimeError(f"existing {method} artifact hash drift: {row['candidate_id']}")
    return record


def base_env(gpu: int, threads: int) -> dict[str, str]:
    env = os.environ.copy()
    for path in (CACHE_ROOT / "home", CACHE_ROOT / "torch", CACHE_ROOT / "huggingface"):
        path.mkdir(parents=True, exist_ok=True)
    env.update({
        "CUDA_VISIBLE_DEVICES": str(gpu),
        "PATH": f"/data1/qlyu/anaconda3/envs/boltz/bin:{NBB2.parent}:{env.get('PATH', '')}",
        "HOME": str(CACHE_ROOT / "home"),
        "TORCH_HOME": str(CACHE_ROOT / "torch"),
        "HF_HOME": str(CACHE_ROOT / "huggingface"),
        "OMP_NUM_THREADS": str(threads),
        "MKL_NUM_THREADS": str(threads),
        "OPENBLAS_NUM_THREADS": str(threads),
    })
    return env


def run_nbb2(root: Path, row: dict[str, str], gpu: int, threads: int) -> dict[str, Any]:
    cid, sequence = row["candidate_id"], row["sequence"]
    outdir = root / "outputs/nbb2" / cid
    outdir.mkdir(parents=True, exist_ok=True)
    raw, normalized = outdir / "nbb2.raw.pdb", outdir / "nbb2.chainA.pdb"
    env = base_env(gpu, threads)
    refined_rc, refined_log_sha = run_logged(
        [str(NBB2), "-H", sequence, "-o", str(raw), "--n_threads", str(threads), "-v"],
        root / "logs" / f"{cid}.nbb2_refined.log", env,
    )
    refinement_state = "REFINED_SUCCESS"
    unrefined_rc: int | None = None
    unrefined_log_sha: str | None = None
    if refined_rc != 0:
        refinement_state = "REFINED_FAILED_UNREFINED_ATTEMPTED"
        unrefined_rc, unrefined_log_sha = run_logged(
            [str(NBB2), "-H", sequence, "-o", str(raw), "--n_threads", str(threads), "-u", "-v"],
            root / "logs" / f"{cid}.nbb2_unrefined.log", env,
        )
        if unrefined_rc != 0:
            return {
                "status": "FAILED", "refinement_state": "REFINED_AND_UNREFINED_FAILED",
                "refined_exit_code": refined_rc, "refined_log_sha256": refined_log_sha,
                "unrefined_exit_code": unrefined_rc, "unrefined_log_sha256": unrefined_log_sha,
                "error": "NanoBodyBuilder2 refined and unrefined invocations failed",
            }
        refinement_state = "UNREFINED_FALLBACK_SUCCESS_EXPLICIT"
    try:
        source_chain = normalize_matching_chain(raw, normalized, sequence)
        geometry = ca_geometry(normalized)
        if geometry["ca_count"] != len(sequence):
            raise RuntimeError("NBB2 CA count differs from input sequence length")
        return {
            "status": "SUCCESS", "refinement_state": refinement_state,
            "refined_exit_code": refined_rc, "refined_log_sha256": refined_log_sha,
            "unrefined_exit_code": unrefined_rc, "unrefined_log_sha256": unrefined_log_sha,
            "source_chain": source_chain, "pdb": str(normalized), "pdb_sha256": sha256_file(normalized),
            "geometry": geometry,
        }
    except Exception as exc:
        return {
            "status": "FAILED", "refinement_state": refinement_state,
            "refined_exit_code": refined_rc, "refined_log_sha256": refined_log_sha,
            "unrefined_exit_code": unrefined_rc, "unrefined_log_sha256": unrefined_log_sha,
            "error": f"NBB2 normalization/QC failed: {exc}",
        }


def run_igfold(root: Path, row: dict[str, str], gpu: int) -> dict[str, Any]:
    cid, sequence = row["candidate_id"], row["sequence"]
    outdir = root / "outputs/igfold" / cid
    outdir.mkdir(parents=True, exist_ok=True)
    fasta, raw, normalized = outdir / "input.fasta", outdir / "igfold.raw.pdb", outdir / "igfold.chainA.pdb"
    fasta.write_text(f">{cid}\n{sequence}\n", encoding="utf-8")
    env = base_env(gpu, 1)
    rc, log_sha = run_logged(
        [str(IGFOLD_PYTHON), str(IGFOLD_SCRIPT), str(fasta), "-o", str(raw), "--models", "1"],
        root / "logs" / f"{cid}.igfold.log", env,
    )
    if rc != 0:
        return {"status": "FAILED", "exit_code": rc, "log_sha256": log_sha, "error": "IgFold invocation failed"}
    try:
        source_chain = normalize_matching_chain(raw, normalized, sequence)
        geometry = ca_geometry(normalized)
        if geometry["ca_count"] != len(sequence):
            raise RuntimeError("IgFold CA count differs from input sequence length")
        return {
            "status": "SUCCESS", "exit_code": rc, "log_sha256": log_sha,
            "source_chain": source_chain, "pdb": str(normalized), "pdb_sha256": sha256_file(normalized),
            "geometry": geometry,
            "role": "CROSSCHECK_ONLY_ALL_720_NO_SELECTION_OR_REPLACEMENT",
        }
    except Exception as exc:
        return {"status": "FAILED", "exit_code": rc, "log_sha256": log_sha, "error": f"IgFold normalization/QC failed: {exc}"}


def run_one(root: Path, row: dict[str, str], gpu: int, threads: int) -> dict[str, Any]:
    existing = validate_existing_terminal(root, row)
    if existing is not None:
        return existing
    cid = row["candidate_id"]
    started = utc_now()
    try:
        nbb2 = run_nbb2(root, row, gpu, threads)
    except Exception as exc:
        nbb2 = {"status": "FAILED", "error": f"unexpected NBB2 exception: {exc}"}
    try:
        igfold = run_igfold(root, row, gpu)
    except Exception as exc:
        igfold = {"status": "FAILED", "error": f"unexpected IgFold exception: {exc}"}
    record = {
        "schema_version": "pvrig_support_v4a720_candidate_monomer_terminal_v1",
        "candidate_id": cid, "sequence_sha256": row["sequence_sha256"], "gpu_physical_id": gpu,
        "nbb2": nbb2, "igfold": igfold,
        "overall_status": "SUCCESS_BOTH_METHODS" if nbb2.get("status") == igfold.get("status") == "SUCCESS" else "PARTIAL_OR_FAILED_NO_REPLACEMENT",
        "started_at_utc": started, "completed_at_utc": utc_now(),
        "replacement": "NO_REPLACEMENT", "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(root / "status/candidates" / f"{cid}.terminal.json", record)
    if record["overall_status"] != "SUCCESS_BOTH_METHODS":
        write_json(root / "status/failures" / f"{cid}.json", record)
    return record


def summarize(root: Path, prereg: dict[str, Any], rows: list[dict[str, str]], records: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {record["candidate_id"]: record for record in records}
    if set(by_id) != {row["candidate_id"] for row in rows} or len(by_id) != EXPECTED_COUNT:
        raise RuntimeError("terminal candidate record set is not exactly the frozen 720")
    manifest_rows: list[dict[str, Any]] = []
    for row in rows:
        record = by_id[row["candidate_id"]]
        nbb2, igfold = record["nbb2"], record["igfold"]
        manifest_rows.append({
            "candidate_id": row["candidate_id"], "sequence_sha256": row["sequence_sha256"],
            "nbb2_status": nbb2.get("status", ""), "nbb2_refinement_state": nbb2.get("refinement_state", ""),
            "nbb2_pdb": nbb2.get("pdb", ""), "nbb2_pdb_sha256": nbb2.get("pdb_sha256", ""),
            "nbb2_backbone_sane": nbb2.get("geometry", {}).get("likely_sane_backbone", ""),
            "igfold_status": igfold.get("status", ""), "igfold_pdb": igfold.get("pdb", ""),
            "igfold_pdb_sha256": igfold.get("pdb_sha256", ""),
            "igfold_backbone_sane": igfold.get("geometry", {}).get("likely_sane_backbone", ""),
            "replacement": "NO_REPLACEMENT", "claim_boundary": CLAIM_BOUNDARY,
        })
    manifest = root / "outputs/monomer_manifest.tsv"
    write_tsv(manifest, manifest_rows)
    nbb_success = sum(row["nbb2_status"] == "SUCCESS" for row in manifest_rows)
    ig_success = sum(row["igfold_status"] == "SUCCESS" for row in manifest_rows)
    fallback = sum(row["nbb2_refinement_state"] == "UNREFINED_FALLBACK_SUCCESS_EXPLICIT" for row in manifest_rows)
    complete_both = sum(row["nbb2_status"] == row["igfold_status"] == "SUCCESS" for row in manifest_rows)
    status = "PASS_ALL_720_NBB2_AND_IGFOLD_MONOMERS_COMPLETE" if complete_both == EXPECTED_COUNT else "PARTIAL_FAILED_CLOSED_ALL_720_ATTEMPTED_NO_REPLACEMENT"
    summary = {
        "schema_version": "pvrig_support_v4_a_acquisition720_monomer_terminal_summary_v1",
        "status": status, "candidate_count": EXPECTED_COUNT, "attempted_count": EXPECTED_COUNT,
        "nbb2_success_count": nbb_success, "nbb2_failed_count": EXPECTED_COUNT - nbb_success,
        "nbb2_explicit_unrefined_fallback_success_count": fallback,
        "igfold_success_count": ig_success, "igfold_failed_count": EXPECTED_COUNT - ig_success,
        "both_methods_success_count": complete_both,
        "no_replacement": True, "no_imputation": True,
        "manifest_sha256": sha256_file(manifest),
        "preregistration_sha256": sha256_file(root / "PREREGISTRATION.json"),
        "runner_sha256": prereg["derived_inputs"]["runner_sha256"],
        "completed_at_utc": utc_now(), "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(root / "status/structures.complete.json", summary)
    return summary


def run(root: Path, max_parallel: int, threads: int, gpu_ids: tuple[int, ...]) -> dict[str, Any]:
    if max_parallel != MAX_PARALLEL or threads != THREADS_PER_WORKER or gpu_ids != EXPECTED_GPUS:
        raise RuntimeError("runtime resources differ from frozen exact 4-GPU/32-thread policy")
    if max_parallel * threads > MAX_CPU_THREADS:
        raise RuntimeError("resource policy exceeds 32 CPU threads")
    prereg, rows = load_frozen_manifest(root)
    preflight_payload = json.loads((root / "status/zero_work_preflight.json").read_text(encoding="utf-8"))
    if preflight_payload.get("status") != "PASS_ZERO_WORK_PREFLIGHT":
        raise RuntimeError("zero-work preflight did not PASS")
    write_json(root / "status/structures.running.json", {
        "status": "RUNNING", "pid": os.getpid(), "candidate_count": len(rows),
        "gpu_ids": list(gpu_ids), "max_parallel": max_parallel, "threads_per_worker": threads,
        "started_at_utc": utc_now(), "claim_boundary": CLAIM_BOUNDARY,
    })
    slots: queue.Queue[int] = queue.Queue()
    for gpu in gpu_ids:
        slots.put(gpu)

    def worker(row: dict[str, str]) -> dict[str, Any]:
        gpu = slots.get()
        try:
            return run_one(root, row, gpu, threads)
        finally:
            slots.put(gpu)

    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = [pool.submit(worker, row) for row in rows]
        for future in as_completed(futures):
            records.append(future.result())
            if len(records) % 10 == 0 or len(records) == EXPECTED_COUNT:
                write_json(root / "status/progress.json", {
                    "status": "RUNNING", "completed_terminal_records": len(records),
                    "expected": EXPECTED_COUNT, "updated_at_utc": utc_now(),
                })
    return summarize(root, prereg, rows, records)


def audit(root: Path) -> dict[str, Any]:
    prereg, rows = load_frozen_manifest(root)
    terminal_paths = sorted((root / "status/candidates").glob("*.terminal.json"))
    records = [json.loads(path.read_text(encoding="utf-8")) for path in terminal_paths]
    expected_ids = {row["candidate_id"] for row in rows}
    observed_ids = {record.get("candidate_id") for record in records}
    payload = {
        "status": "RUNNING" if observed_ids != expected_ids else "TERMINAL_RECORD_SET_COMPLETE",
        "expected": EXPECTED_COUNT, "terminal_records": len(records),
        "missing_ids": sorted(expected_ids - observed_ids), "unexpected_ids": sorted(observed_ids - expected_ids),
        "nbb2_success": sum(record.get("nbb2", {}).get("status") == "SUCCESS" for record in records),
        "igfold_success": sum(record.get("igfold", {}).get("status") == "SUCCESS" for record in records),
        "nbb2_unrefined_fallback_success": sum(record.get("nbb2", {}).get("refinement_state") == "UNREFINED_FALLBACK_SUCCESS_EXPLICIT" for record in records),
        "preregistration_sha256": sha256_file(root / "PREREGISTRATION.json"),
        "runner_sha256": prereg["derived_inputs"]["runner_sha256"],
        "audited_at_utc": utc_now(), "claim_boundary": CLAIM_BOUNDARY,
    }
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "preflight", "run", "audit"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-parallel", type=int, default=MAX_PARALLEL)
    parser.add_argument("--threads", type=int, default=THREADS_PER_WORKER)
    parser.add_argument("--gpu-ids", default=",".join(map(str, EXPECTED_GPUS)))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        gpu_ids = tuple(int(value) for value in args.gpu_ids.split(",") if value != "")
        if args.action == "prepare":
            payload = prepare(args.output_root)
        elif args.action == "preflight":
            payload = preflight(args.output_root)
        elif args.action == "run":
            payload = run(args.output_root, args.max_parallel, args.threads, gpu_ids)
        else:
            payload = audit(args.output_root)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.output_root.exists():
            write_json(args.output_root / "status/runner.failed.json", {
                "status": "FAILED_CLOSED", "action": args.action, "error": str(exc),
                "failed_at_utc": utc_now(), "claim_boundary": CLAIM_BOUNDARY,
            })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
