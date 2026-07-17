#!/usr/bin/env python3
"""Freeze and run the V4-G C0154 hard-pass-12 monomer acquisition package.

This utility deliberately reads only sequence/developability Full-QC fields.  It
does not consume model scores, docking poses, geometry scores, or labels.
NanoBodyBuilder2 is the docking-primary monomer source because that is the
frozen V4-D physical protocol; IgFold is generated only as an audit crosscheck.
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
from typing import Any, Iterable


RECOVERY_ROOT = Path("/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716")
RECOVERY_RECEIPT = RECOVERY_ROOT / "status/recovery.complete.json"
EXPECTED_RECOVERY_RECEIPT_SHA256 = "7b2786274045a45d7b487fa7b9cc4e14d7a2e6215e2cb6286d950e2b9632f356"
EXPECTED_FULL_MERGED_SHA256 = "f6b0ca1d3de522f6cc3269d498bcd89cd40e73576b81d16291bd81f49b7d6962"
EXPECTED_ACQUISITION_MANIFEST_SHA256 = "e814103ee90831e33b3f04a7e8a477e68695d61401d96732b7e95829b1bd306f"
EXPECTED_PARENT = "PLDNANO_VHH_00220"
EXPECTED_CLUSTER = "C0154"
EXPECTED_COUNT = 12
EXPECTED_POLICY = "run_full_qc_on_all_96;dock_every_full_qc_hard_pass;record_attrition;no_replacement"
CLAIM_BOUNDARY = (
    "acquisition_only_computational_monomer_and_independent_dual_receptor_docking_evidence;"
    "not_binding_affinity_competition_experimental_blocking_or_docking_gold"
)
NBB2 = Path("/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2")
IGFOLD_PYTHON = Path("/data1/qlyu/software/envs/vhh-igfold/bin/python")
IGFOLD_SCRIPT = Path("/data1/qlyu/software/vhh_eval_tools/igfold_predict.py")
V4D_PHYSICAL = {
    "source_protocol_id": "pvrig_v4_d_fullqc290_dual_redocking_20260715",
    "source_protocol_lock_file_sha256": "56ef539cb54a1aba8e665ec5d62b3653088e2289e371d8fa5bbadbc725c1d574",
    "source_protocol_core_lock_file_sha256": "767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24",
    "source_protocol_core_sha256": "91d75291ff832c1e94cbc0bf6f1cdd75de6a8bb74611230cdcd1716466f37cb7",
    "source_protocol_lock_sha256": "a24eaf37730bc569067d64cdc1a43a763b70878d13d50e804bf3000ce43f5e84",
    "seeds": [917, 1931, 3253],
    "receptors": ["8x6b", "9e6y"],
    "sampling": 40,
    "ncores_per_job": 4,
    "seletop_select": 10,
    "seletopclusts_top_models": 4,
    "rigidbody_tolerance": 5,
    "flexref_tolerance": 10,
    "randremoval": True,
    "npart": 2,
}
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
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def bool_text(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise RuntimeError(f"invalid boolean text: {value!r}")
    return normalized == "true"


def unique_range(sequence: str, cdr: str, label: str, candidate_id: str) -> str:
    start = sequence.find(cdr)
    if not cdr or start < 0 or sequence.find(cdr, start + 1) >= 0:
        raise RuntimeError(f"{candidate_id}: {label} absent or non-unique")
    return f"{start + 1}-{start + len(cdr)}"


def freeze_selection(output_root: Path, acquisition_manifest: Path) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"refusing to prepare non-empty output root: {output_root}")
    for path, expected in (
        (RECOVERY_RECEIPT, EXPECTED_RECOVERY_RECEIPT_SHA256),
        (RECOVERY_ROOT / "outputs/full_merged.tsv", EXPECTED_FULL_MERGED_SHA256),
        (acquisition_manifest, EXPECTED_ACQUISITION_MANIFEST_SHA256),
    ):
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"frozen input hash mismatch: {path}")
    receipt = json.loads(RECOVERY_RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS_V4_G_UNSEEN96_FULL_QC_RECOVERY_VALIDATED":
        raise RuntimeError("recovery receipt is not PASS")
    if receipt.get("full_rows") != 24 or receipt.get("full_hard_pass") != 12 or receipt.get("full_hard_fail") != 12:
        raise RuntimeError("recovery receipt count drift")
    if receipt.get("outputs", {}).get("full_merged.tsv") != EXPECTED_FULL_MERGED_SHA256:
        raise RuntimeError("receipt does not bind expected full_merged.tsv")

    # Only these three Full-QC columns are consumed.  All model/docking/geometry
    # columns are intentionally ignored even if present as empty schema fields.
    full_rows = read_tsv(RECOVERY_ROOT / "outputs/full_merged.tsv")
    reduced = [
        {"candidate_id": row["candidate_id"], "sequence": row["sequence"], "hard_fail": row["hard_fail"]}
        for row in full_rows
    ]
    selected = [row for row in reduced if not bool_text(row["hard_fail"])]
    failed = [row for row in reduced if bool_text(row["hard_fail"])]
    if len(selected) != EXPECTED_COUNT or len(failed) != EXPECTED_COUNT:
        raise RuntimeError("hard-pass selection is not exactly 12/24")
    if len({row["candidate_id"] for row in selected}) != EXPECTED_COUNT:
        raise RuntimeError("duplicate selected candidate IDs")

    acquisition_rows = read_tsv(acquisition_manifest)
    acquisition = {row["candidate_id"]: row for row in acquisition_rows}
    if len(acquisition) != 96:
        raise RuntimeError("frozen unseen96 acquisition manifest count drift")
    manifest_rows: list[dict[str, str]] = []
    for row in sorted(selected, key=lambda item: item["candidate_id"]):
        cid, sequence = row["candidate_id"], row["sequence"]
        if cid not in acquisition:
            raise RuntimeError(f"selected ID absent from acquisition manifest: {cid}")
        source = acquisition[cid]
        if source["sequence"] != sequence or source["sequence_sha256"] != sha256_text(sequence):
            raise RuntimeError(f"sequence closure failed: {cid}")
        if source["parent_id"] != EXPECTED_PARENT or source["parent_framework_cluster"] != EXPECTED_CLUSTER:
            raise RuntimeError(f"unexpected hard-pass parent/cluster: {cid}")
        if source["full_qc_and_docking_policy"] != EXPECTED_POLICY:
            raise RuntimeError(f"frozen no-replacement policy drift: {cid}")
        manifest_rows.append({
            "candidate_id": cid,
            "sequence": sequence,
            "sequence_sha256": source["sequence_sha256"],
            "parent_id": source["parent_id"],
            "parent_framework_cluster": source["parent_framework_cluster"],
            "design_method": source["design_method"],
            "design_mode": source["design_mode"],
            "target_patch_id": source["target_patch_id"],
            "cdr1": source["cdr1"],
            "cdr2": source["cdr2"],
            "cdr3": source["cdr3"],
            "cdr1_range": unique_range(sequence, source["cdr1"], "cdr1", cid),
            "cdr2_range": unique_range(sequence, source["cdr2"], "cdr2", cid),
            "cdr3_range": unique_range(sequence, source["cdr3"], "cdr3", cid),
            "selection_rule": "exact_full_qc_hard_fail_false_from_bound_recovery",
            "full_qc_and_docking_policy": source["full_qc_and_docking_policy"],
            "claim_boundary": CLAIM_BOUNDARY,
        })

    output_root.mkdir(parents=True)
    for name in ("inputs", "logs", "outputs/nbb2", "outputs/igfold", "status"):
        (output_root / name).mkdir(parents=True, exist_ok=True)
    manifest = output_root / "inputs/hardpass12.tsv"
    write_tsv(manifest, manifest_rows)
    fasta = output_root / "inputs/hardpass12.fasta"
    fasta.write_text("".join(f">{row['candidate_id']}\n{row['sequence']}\n" for row in manifest_rows), encoding="utf-8")
    script_path = Path(__file__).resolve()
    prereg = {
        "schema_version": "pvrig_v4_g_c0154_hardpass12_acquisition_preregistration_v1",
        "status": "FROZEN_BEFORE_STRUCTURE_OR_DOCKING_ACQUISITION",
        "frozen_at_utc": utc_now(),
        "selection": {
            "rule": "select every and only full_merged.tsv row where hard_fail is False",
            "candidate_count": EXPECTED_COUNT,
            "candidate_ids": [row["candidate_id"] for row in manifest_rows],
            "parent_id": EXPECTED_PARENT,
            "parent_framework_cluster": EXPECTED_CLUSTER,
            "replacement_policy": "NO_REPLACEMENT",
            "model_score_access": "PROHIBITED_AND_NOT_USED",
            "docking_or_geometry_access_at_selection": "PROHIBITED_AND_NOT_USED",
        },
        "frozen_inputs": {
            "recovery_receipt_path": str(RECOVERY_RECEIPT),
            "recovery_receipt_sha256": EXPECTED_RECOVERY_RECEIPT_SHA256,
            "full_merged_path": str(RECOVERY_ROOT / "outputs/full_merged.tsv"),
            "full_merged_sha256": EXPECTED_FULL_MERGED_SHA256,
            "unseen96_acquisition_manifest_sha256": EXPECTED_ACQUISITION_MANIFEST_SHA256,
            "hardpass12_manifest_sha256": sha256_file(manifest),
            "hardpass12_fasta_sha256": sha256_file(fasta),
            "preparation_script_sha256": sha256_file(script_path),
        },
        "structure_acquisition": {
            "primary": "NanoBodyBuilder2 normalized to chain A; used for docking",
            "crosscheck_only": "IgFold one model; cannot replace candidates or select docking inputs",
            "node1_ssd_only": True,
            "max_parallel": 4,
            "gpu_ids": [0, 1, 2, 3],
            "threads_per_nbb2": 8,
        },
        "docking_acquisition": {
            **V4D_PHYSICAL,
            "candidate_count": EXPECTED_COUNT,
            "expected_jobs": 72,
            "launch_gate": "only after source V4-D controller is terminal and node23 load1 allows",
            "post_docking_use": "labels remain sealed from acquisition selector; downstream evaluator is separate",
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    prereg_path = output_root / "PREREGISTRATION.json"
    write_json(prereg_path, prereg)
    write_json(output_root / "status/prepared.json", {
        "status": "PASS_V4_G_HARDPASS12_STRUCTURE_PACKAGE_PREPARED",
        "candidate_count": EXPECTED_COUNT,
        "preregistration_sha256": sha256_file(prereg_path),
        "manifest_sha256": sha256_file(manifest),
        "prepared_at_utc": utc_now(),
    })
    return prereg


def candidate_manifest(root: Path) -> list[dict[str, str]]:
    prereg_path = root / "PREREGISTRATION.json"
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    script_hash = sha256_file(Path(__file__).resolve())
    if prereg["frozen_inputs"]["preparation_script_sha256"] != script_hash:
        raise RuntimeError("running script differs from preregistered preparation script")
    manifest = root / "inputs/hardpass12.tsv"
    if sha256_file(manifest) != prereg["frozen_inputs"]["hardpass12_manifest_sha256"]:
        raise RuntimeError("hardpass12 manifest differs from preregistration")
    rows = read_tsv(manifest)
    if len(rows) != EXPECTED_COUNT or [r["candidate_id"] for r in rows] != prereg["selection"]["candidate_ids"]:
        raise RuntimeError("candidate set differs from preregistration")
    return rows


def pdb_chains(path: Path) -> dict[str, list[tuple[tuple[str, str], str, str]]]:
    result: dict[str, list[tuple[tuple[str, str], str, str]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54 or line[12:16].strip() != "CA":
            continue
        chain, key, aa3 = line[21], (line[22:26], line[26]), line[17:20].strip()
        token = (chain, *key)
        if token in seen:
            continue
        seen.add(token)
        result.setdefault(chain, []).append((key, aa3, line))
    return result


def normalize_matching_chain(source: Path, destination: Path, sequence: str) -> str:
    chains = pdb_chains(source)
    matching = [chain for chain, residues in chains.items() if "".join(AA3.get(item[1], "X") for item in residues) == sequence]
    if len(matching) != 1:
        observed = {chain: "".join(AA3.get(item[1], "X") for item in residues) for chain, residues in chains.items()}
        raise RuntimeError(f"expected exactly one chain matching sequence in {source}; observed lengths={dict((k,len(v)) for k,v in observed.items())}")
    source_chain = matching[0]
    residue_map: dict[tuple[str, str], int] = {}
    lines: list[str] = []
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54 or line[21] != source_chain:
            continue
        padded = line.ljust(80)
        key = (padded[22:26], padded[26])
        residue_map.setdefault(key, len(residue_map) + 1)
        lines.append(f"{padded[:21]}A{residue_map[key]:4d} {padded[27:]}".rstrip())
    if len(residue_map) != len(sequence):
        raise RuntimeError(f"normalized residue count mismatch for {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\nTER\nEND\n", encoding="utf-8")
    observed = "".join(AA3.get(item[1], "X") for item in pdb_chains(destination).get("A", []))
    if observed != sequence:
        raise RuntimeError(f"normalized sequence mismatch for {destination}")
    return source_chain


def ca_geometry(path: Path, chain: str = "A") -> dict[str, Any]:
    coords: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("ATOM  ") and len(line) >= 54 and line[21] == chain and line[12:16].strip() == "CA":
            coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    distances = [math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3))) for a, b in zip(coords, coords[1:])]
    return {
        "ca_count": len(coords),
        "adjacent_ca_min": min(distances) if distances else None,
        "adjacent_ca_max": max(distances) if distances else None,
        "adjacent_ca_gt_6A": sum(value > 6.0 for value in distances),
        "likely_sane_backbone": bool(distances) and sum(2.5 <= value <= 4.5 for value in distances) >= 0.8 * len(distances),
    }


def run_logged(command: list[str], log: Path, env: dict[str, str]) -> int:
    started = utc_now()
    process = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        f"$ {shlex.join(command)}\n[started_at] {started}\n{process.stdout}\n"
        f"[finished_at] {utc_now()}\n[exit_code] {process.returncode}\n",
        encoding="utf-8",
    )
    return int(process.returncode)


def run_one(root: Path, row: dict[str, str], gpu: int, threads: int) -> dict[str, Any]:
    cid, sequence = row["candidate_id"], row["sequence"]
    nbb_dir, ig_dir = root / "outputs/nbb2" / cid, root / "outputs/igfold" / cid
    nbb_dir.mkdir(parents=True, exist_ok=True)
    ig_dir.mkdir(parents=True, exist_ok=True)
    fasta = ig_dir / f"{cid}.fasta"
    fasta.write_text(f">{cid}\n{sequence}\n", encoding="utf-8")
    for cache_dir in (
        Path("/data1/qlyu/pvrig_v4g12_cache/home"),
        Path("/data1/qlyu/pvrig_v4g12_cache/torch"),
        Path("/data1/qlyu/pvrig_v4g12_cache/huggingface"),
    ):
        cache_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "CUDA_VISIBLE_DEVICES": str(gpu),
        "PATH": f"/data1/qlyu/anaconda3/envs/boltz/bin:{NBB2.parent}:{env.get('PATH', '')}",
        "HOME": "/data1/qlyu/pvrig_v4g12_cache/home",
        "TORCH_HOME": "/data1/qlyu/pvrig_v4g12_cache/torch",
        "HF_HOME": "/data1/qlyu/pvrig_v4g12_cache/huggingface",
        "OMP_NUM_THREADS": str(threads), "MKL_NUM_THREADS": str(threads), "OPENBLAS_NUM_THREADS": str(threads),
    })
    raw = nbb_dir / f"{cid}_nanobodybuilder2_raw.pdb"
    primary = nbb_dir / f"{cid}_nanobodybuilder2_chainA.pdb"
    refinement = "refined"
    if not raw.is_file():
        rc = run_logged([str(NBB2), "-H", sequence, "-o", str(raw), "--n_threads", str(threads), "-v"], root / "logs" / f"{cid}.nbb2.log", env)
        if rc != 0:
            refinement = "unrefined_fallback"
            rc = run_logged([str(NBB2), "-H", sequence, "-o", str(raw), "--n_threads", str(threads), "-u", "-v"], root / "logs" / f"{cid}.nbb2_unrefined.log", env)
        if rc != 0:
            raise RuntimeError(f"NanoBodyBuilder2 failed for {cid}")
    source_chain = normalize_matching_chain(raw, primary, sequence)
    nbb_geometry = ca_geometry(primary)
    if nbb_geometry["ca_count"] != len(sequence):
        raise RuntimeError(f"NBB2 CA closure failed for {cid}")

    ig_raw = ig_dir / "igfold.raw.pdb"
    ig_norm = ig_dir / "igfold.chainA.pdb"
    ig_env = dict(env)
    ig_env.update({"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
    if not ig_raw.is_file():
        command = [str(IGFOLD_PYTHON), str(IGFOLD_SCRIPT), str(fasta), "-o", str(ig_raw), "--models", "1"]
        if run_logged(command, root / "logs" / f"{cid}.igfold.log", ig_env) != 0:
            raise RuntimeError(f"IgFold failed for {cid}")
    ig_source_chain = normalize_matching_chain(ig_raw, ig_norm, sequence)
    ig_geometry = ca_geometry(ig_norm)
    if ig_geometry["ca_count"] != len(sequence):
        raise RuntimeError(f"IgFold CA closure failed for {cid}")
    record = {
        "candidate_id": cid,
        "sequence_sha256": row["sequence_sha256"],
        "gpu": gpu,
        "nbb2_refinement": refinement,
        "nbb2_source_chain": source_chain,
        "nbb2_primary_pdb": str(primary),
        "nbb2_primary_pdb_sha256": sha256_file(primary),
        "nbb2_geometry": nbb_geometry,
        "igfold_role": "CROSSCHECK_ONLY_NO_SELECTION_OR_REPLACEMENT",
        "igfold_source_chain": ig_source_chain,
        "igfold_pdb": str(ig_norm),
        "igfold_pdb_sha256": sha256_file(ig_norm),
        "igfold_geometry": ig_geometry,
        "completed_at_utc": utc_now(),
    }
    write_json(root / "status/candidates" / f"{cid}.complete.json", record)
    return record


def run_structures(root: Path, max_parallel: int, threads: int) -> dict[str, Any]:
    rows = candidate_manifest(root)
    for tool in (NBB2, IGFOLD_PYTHON, IGFOLD_SCRIPT):
        if not tool.is_file():
            raise RuntimeError(f"required structure tool missing: {tool}")
    if max_parallel < 1 or max_parallel > 4 or threads * max_parallel > 32:
        raise RuntimeError("resource policy violation: at most 4 GPUs and 32 CPU threads")
    slots: queue.Queue[int] = queue.Queue()
    for gpu in range(max_parallel):
        slots.put(gpu)

    def worker(row: dict[str, str]) -> dict[str, Any]:
        gpu = slots.get()
        try:
            return run_one(root, row, gpu, threads)
        finally:
            slots.put(gpu)

    records: list[dict[str, Any]] = []
    write_json(root / "status/structures.running.json", {
        "status": "RUNNING", "pid": os.getpid(), "started_at_utc": utc_now(),
        "max_parallel": max_parallel, "threads_per_worker": threads,
    })
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = [pool.submit(worker, row) for row in rows]
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda item: item["candidate_id"])
    if len(records) != EXPECTED_COUNT or {r["candidate_id"] for r in records} != {r["candidate_id"] for r in rows}:
        raise RuntimeError("structure result closure failed")
    manifest_rows = [{
        "candidate_id": item["candidate_id"],
        "sequence_sha256": item["sequence_sha256"],
        "primary_method": "NanoBodyBuilder2",
        "primary_pdb": item["nbb2_primary_pdb"],
        "primary_pdb_sha256": item["nbb2_primary_pdb_sha256"],
        "primary_chain": "A",
        "igfold_crosscheck_pdb": item["igfold_pdb"],
        "igfold_crosscheck_pdb_sha256": item["igfold_pdb_sha256"],
        "replacement_policy": "NO_REPLACEMENT",
        "claim_boundary": CLAIM_BOUNDARY,
    } for item in records]
    manifest = root / "outputs/monomer_manifest.tsv"
    write_tsv(manifest, manifest_rows)
    complete = {
        "status": "PASS_V4_G_HARDPASS12_NBB2_IGFOLD_STRUCTURE_ACQUISITION",
        "candidate_count": EXPECTED_COUNT,
        "primary_nbb2_count": EXPECTED_COUNT,
        "igfold_crosscheck_count": EXPECTED_COUNT,
        "manifest_sha256": sha256_file(manifest),
        "preregistration_sha256": sha256_file(root / "PREREGISTRATION.json"),
        "records": records,
        "completed_at_utc": utc_now(),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(root / "status/structures.complete.json", complete)
    return complete


def validate(root: Path) -> dict[str, Any]:
    rows = candidate_manifest(root)
    complete_path = root / "status/structures.complete.json"
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    manifest = root / "outputs/monomer_manifest.tsv"
    monomers = read_tsv(manifest)
    if complete.get("status") != "PASS_V4_G_HARDPASS12_NBB2_IGFOLD_STRUCTURE_ACQUISITION":
        raise RuntimeError("structure receipt is not PASS")
    if sha256_file(manifest) != complete.get("manifest_sha256") or len(monomers) != EXPECTED_COUNT:
        raise RuntimeError("monomer manifest closure failed")
    by_id = {row["candidate_id"]: row for row in rows}
    for item in monomers:
        cid = item["candidate_id"]
        if cid not in by_id or item["sequence_sha256"] != by_id[cid]["sequence_sha256"]:
            raise RuntimeError(f"monomer sequence binding failed: {cid}")
        for field in ("primary_pdb", "igfold_crosscheck_pdb"):
            path = Path(item[field])
            expected = item[f"{field}_sha256"]
            if not path.is_file() or sha256_file(path) != expected:
                raise RuntimeError(f"structure artifact hash mismatch: {path}")
    return {
        "status": "PASS_V4_G_HARDPASS12_STRUCTURE_DELIVERY_VALIDATED",
        "candidate_count": EXPECTED_COUNT,
        "manifest_sha256": sha256_file(manifest),
        "complete_receipt_sha256": sha256_file(complete_path),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "validate"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--acquisition-manifest", type=Path)
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--threads", type=int, default=8)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.action == "prepare":
            if args.acquisition_manifest is None:
                raise RuntimeError("--acquisition-manifest is required for prepare")
            payload = freeze_selection(args.output_root, args.acquisition_manifest)
        elif args.action == "run":
            payload = run_structures(args.output_root, args.max_parallel, args.threads)
        else:
            payload = validate(args.output_root)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.output_root.exists():
            write_json(args.output_root / "status/structures.failed.json", {
                "status": "FAILED_CLOSED", "error": str(exc), "failed_at_utc": utc_now(),
            })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
