#!/usr/bin/env python3
"""Generate additional ProteinMPNN sequences for 114 docking-enriched VHH backbones."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/data1/qlyu/projects/pvrig_v4_i_top114_mpnn_v1_20260718")
PLAN = ROOT / "inputs/top114_backbones.tsv"
OLD_RAW = Path("/data1/qlyu/projects/pvrig_v4_h_qc96_h0_h3_v1_20260717/outputs/v4_h_h1_raw2592.tsv")
OLD_SELECTED = Path("/data1/qlyu/projects/pvrig_v4_h_qc96_h0_h3_v1_20260717/outputs/v4_h_h1_candidates1440.tsv")
WRAPPER = Path("/data/qlyu/software/RFantibody/bin/rfantibody-env")
SCRIPT = Path("/data/qlyu/software/RFantibody/scripts/proteinmpnn_interface_design.py")
WEIGHT = Path("/data/qlyu/software/RFantibody/weights/ProteinMPNN_v48_noise_0.2.pt")
GPU_IDS = (6, 7)
CLAIM_BOUNDARY = (
    "ProteinMPNN sequence expansion around computational docking-enriched backbones; "
    "not binding, affinity, competition, or experimental blocking."
)
AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V", "MSE": "M",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode()).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def pdb_sequence(path: Path, chain: str = "H") -> str:
    residues: list[str] = []
    seen: set[tuple[str, str]] = set()
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("ATOM") or len(line) < 27 or line[21:22] != chain:
            continue
        key = (line[22:26], line[26:27])
        if key in seen:
            continue
        seen.add(key)
        residues.append(AA3_TO_1[line[17:20].strip().upper()])
    if not residues:
        raise RuntimeError(f"pdb_chain_missing:{path}:{chain}")
    return "".join(residues)


def validate() -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    for path in (PLAN, OLD_RAW, OLD_SELECTED, WRAPPER, SCRIPT, WEIGHT):
        if not path.is_file():
            raise RuntimeError(f"required_file_missing:{path}")
    plan = read_tsv(PLAN)
    if len(plan) != 114:
        raise RuntimeError(f"plan_count:{len(plan)}")
    if len({(row["design_task_id"], row["backbone_index"]) for row in plan}) != 114:
        raise RuntimeError("plan_backbone_not_unique")
    for row in plan:
        backbone = Path(row["source_backbone_path"])
        if not backbone.is_file() or sha256(backbone) != row["source_backbone_sha256"]:
            raise RuntimeError(f"source_backbone_hash_mismatch:{backbone}")
    selected = read_tsv(OLD_SELECTED)
    source_by_task: dict[str, dict[str, str]] = {}
    for row in selected:
        source_by_task.setdefault(row["design_task_id"], row)
    missing = {row["design_task_id"] for row in plan} - set(source_by_task)
    if missing:
        raise RuntimeError(f"task_metadata_missing:{sorted(missing)}")
    return plan, source_by_task


def run_task(task_id: str, rows: list[dict[str, str]], gpu: int) -> dict[str, Any]:
    task_root = ROOT / "runtime/tasks" / task_id
    marker = task_root / "complete.json"
    if marker.is_file():
        payload = json.loads(marker.read_text())
        if payload.get("status") != "PASS_MPNN_TASK" or int(payload.get("backbone_count", 0)) != len(rows):
            raise RuntimeError(f"invalid_existing_task:{task_id}")
        return payload
    attempt = ROOT / "runtime/attempts" / f"{task_id}.{os.getpid()}.{gpu}"
    if attempt.exists():
        shutil.rmtree(attempt)
    input_dir = attempt / "backbones"
    output_dir = attempt / "sequences"
    input_dir.mkdir(parents=True)
    output_dir.mkdir()
    for row in rows:
        index = int(row["backbone_index"])
        destination = input_dir / f"design_{index}.pdb"
        shutil.copy2(row["source_backbone_path"], destination)
        if sha256(destination) != row["source_backbone_sha256"]:
            raise RuntimeError(f"staged_backbone_hash_mismatch:{task_id}:{index}")
    command = [
        str(WRAPPER), str(SCRIPT), "-pdbdir", str(input_dir), "-outpdbdir", str(output_dir),
        "-loop_string", rows[0]["mpnn_loop_string"], "-seqs_per_struct", "12",
        "-temperature", "0.2", "-checkpoint_path", str(WEIGHT), "-omit_AAs", "CX",
        "-augment_eps", "0", "-checkpoint_name", str(attempt / "checkpoint.txt"), "-deterministic",
    ]
    env = dict(os.environ)
    env.update({"CUDA_VISIBLE_DEVICES": str(gpu), "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"})
    with (attempt / "proteinmpnn.log").open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    expected = len(rows) * 12
    outputs = sorted(output_dir.glob("design_*_dldesign_*.pdb"))
    if completed.returncode or len(outputs) != expected:
        raise RuntimeError(f"proteinmpnn_task_failed:{task_id}:rc={completed.returncode}:outputs={len(outputs)}:{expected}")
    payload = {
        "schema_version": "pvrig_v4_i_top114_mpnn_task_v1", "status": "PASS_MPNN_TASK",
        "task_id": task_id, "gpu": gpu, "backbone_count": len(rows), "generated_sequence_pdb_count": len(outputs),
        "new_index_range": "3-11", "finished_at_utc": now(), "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(attempt / "complete.json", payload)
    task_root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(attempt, task_root)
    return payload


def collect(plan: list[dict[str, str]], source_by_task: dict[str, dict[str, str]]) -> dict[str, Any]:
    old_hashes = {row["sequence_sha256"] for row in read_tsv(OLD_RAW)}
    by_key = {(row["design_task_id"], int(row["backbone_index"])): row for row in plan}
    representatives: dict[str, dict[str, Any]] = {}
    old_overlap = 0
    within_new_duplicates = 0
    raw_new = 0
    for path in sorted((ROOT / "runtime/tasks").glob("*/sequences/design_*_dldesign_*.pdb")):
        parts = path.stem.split("_")
        backbone_index = int(parts[1])
        mpnn_index = int(parts[-1])
        if mpnn_index < 3 or mpnn_index > 11:
            continue
        task_id = path.parents[1].name
        plan_row = by_key[(task_id, backbone_index)]
        metadata = source_by_task[task_id]
        sequence = pdb_sequence(path)
        digest = sequence_hash(sequence)
        raw_new += 1
        if digest in old_hashes:
            old_overlap += 1
            continue
        if digest in representatives:
            within_new_duplicates += 1
            continue
        candidate_id = f"V4I_MPNN__{metadata['parent_id']}__{metadata['target_patch_id']}__{metadata['design_mode']}__B{backbone_index:02d}__M{mpnn_index:02d}"
        representatives[digest] = {
            "candidate_id": candidate_id, "sequence": sequence, "sequence_sha256": digest,
            "parent_id": metadata["parent_id"], "parent_framework_cluster": metadata["parent_framework_cluster"],
            "target_patch_id": metadata["target_patch_id"], "design_mode": metadata["design_mode"],
            "design_task_id": task_id, "backbone_index": str(backbone_index), "mpnn_index": str(mpnn_index),
            "source_backbone_sha256": plan_row["source_backbone_sha256"],
            "source_rank": plan_row["source_rank"], "source_R_dual_min": plan_row["source_R_dual_min"],
            "research_pool_state": "MPNN_EXPANSION_PENDING_FULL_QC", "claim_boundary": CLAIM_BOUNDARY,
        }
    rows = sorted(representatives.values(), key=lambda row: (int(row["source_rank"]), int(row["mpnn_index"]), row["candidate_id"]))
    output = ROOT / "outputs"
    write_tsv(output / "mpnn_expansion_candidates.tsv", rows, list(rows[0]))
    (output / "mpnn_expansion_candidates.fasta").write_text(
        "".join(f">{row['candidate_id']}\n{row['sequence']}\n" for row in rows)
    )
    summary = {
        "schema_version": "pvrig_v4_i_top114_mpnn_terminal_v1", "status": "PASS_TOP114_MPNN_EXPANSION_COMPLETE",
        "backbone_count": 114, "raw_new_index_sequences": raw_new, "old_sequence_overlap_excluded": old_overlap,
        "within_new_duplicates_collapsed": within_new_duplicates, "unique_new_candidate_count": len(rows),
        "parent_counts": dict(Counter(row["parent_framework_cluster"] for row in rows)),
        "output_hashes": {
            "mpnn_expansion_candidates.tsv": sha256(output / "mpnn_expansion_candidates.tsv"),
            "mpnn_expansion_candidates.fasta": sha256(output / "mpnn_expansion_candidates.fasta"),
        },
        "finished_at_utc": now(), "claim_boundary": CLAIM_BOUNDARY,
    }
    atomic_json(output / "MPNN_EXPANSION_RECEIPT.json", summary)
    return summary


def run() -> dict[str, Any]:
    plan, source_by_task = validate()
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in plan:
        groups[row["design_task_id"]].append(row)
    tasks = sorted(groups.items(), key=lambda item: min(int(row["source_rank"]) for row in item[1]))
    atomic_json(ROOT / "status/runner.running.json", {
        "status": "RUNNING", "pid": os.getpid(), "started_at_utc": now(),
        "task_count": len(tasks), "backbone_count": len(plan), "gpus": list(GPU_IDS),
    })
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(GPU_IDS)) as executor:
        futures = {
            executor.submit(run_task, task_id, rows, GPU_IDS[index % len(GPU_IDS)]): task_id
            for index, (task_id, rows) in enumerate(tasks)
        }
        for future in as_completed(futures):
            results.append(future.result())
            atomic_json(ROOT / "status/progress.json", {
                "status": "RUNNING", "completed_tasks": len(results), "total_tasks": len(tasks),
                "completed_backbones": sum(int(row["backbone_count"]) for row in results), "updated_at_utc": now(),
            })
    summary = collect(plan, source_by_task)
    atomic_json(ROOT / "status/runner.complete.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    try:
        if args.preflight:
            plan, _ = validate()
            print(json.dumps({"status": "PASS_ZERO_WORK_PREFLIGHT", "backbone_count": len(plan), "gpus": list(GPU_IDS)}, indent=2))
            return 0
        print(json.dumps(run(), indent=2, sort_keys=True))
        return 0
    except BaseException as error:
        atomic_json(ROOT / "status/runner.failed.json", {
            "status": "FAILED", "error": f"{type(error).__name__}:{error}",
            "failed_at_utc": now(), "pid": os.getpid(), "claim_boundary": CLAIM_BOUNDARY,
        })
        raise


if __name__ == "__main__":
    raise SystemExit(main())
