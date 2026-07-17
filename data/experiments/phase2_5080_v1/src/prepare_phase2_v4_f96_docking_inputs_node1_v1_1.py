#!/usr/bin/env python3
"""Freeze Full-QC eligibility and NanoBodyBuilder2 monomers for V4-F96 Docking.

This program runs on Node1 only after the frozen V4-F96 Full-QC recovery is
terminal.  It never reads surrogate predictions or any Docking/experimental
label.  Every Full-QC hard-pass row is attempted exactly once (with one
explicit unrefined fallback); failures are retained without replacement.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FULLQC_ROOT = Path("/data1/qlyu/projects/pvrig_v4_f_holdout96_full_qc_recovery_v2_20260717")
OUTPUT_ROOT = Path("/data1/qlyu/projects/pvrig_v4_f96_docking_input_release_v1_1_20260717")
MANIFEST = FULLQC_ROOT / "inputs/prospective_holdout96_manifest.tsv"
FULL_MERGED = FULLQC_ROOT / "cascade/full_merged.tsv"
FAST_MERGED = FULLQC_ROOT / "cascade/fast_merged.tsv"
TERMINAL = FULLQC_ROOT / "outputs/full_qc_terminal_summary.json"
COMPLETE = FULLQC_ROOT / "status/runner.complete.json"
NBB2 = Path("/data/qlyu/anaconda3/envs/boltz/bin/NanoBodyBuilder2")
EXPECTED = {
    "manifest": "3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334",
    "fullqc_freeze": "062f83b290166471fee54231470967425b5de786d0f61f9597b02f5bcc190805",
    "fullqc_package": "c89ba6591c10acb4007a182ec21880b17ec92f661530df8701f6c66677ae1af0",
    "fullqc_runner": "b36e2fc2908eee2cf573db065a1acb16e4b6a17f53dad85c27183ededb444d09",
    "fullqc_prereg": "b9d539f8936992df330e7ad844604d7d81114547e99de82b1a1fcbcbeecbebcb",
    "nbb2": "db5113f9c15b699e8c5ec4bd6857f37c7cff41ae474ecf9ffb463fbd606935ab",
}
STATIC_PATHS = {
    "fullqc_freeze": FULLQC_ROOT / "IMPLEMENTATION_FREEZE.json",
    "fullqc_package": FULLQC_ROOT / "PACKAGE_RECEIPT.json",
    "fullqc_runner": FULLQC_ROOT / "run_phase2_v4_f_holdout96_full_qc_recovery_v2_node1.py",
    "fullqc_prereg": FULLQC_ROOT / "phase2_v4_f_holdout96_full_qc_recovery_v2_preregistration.json",
    "nbb2": NBB2,
}
AA3 = {
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E",
    "GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K","MET":"M","PHE":"F",
    "PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V",
}
ELIGIBILITY_FIELDS = [
    "candidate_id", "sequence_sha256", "parent_framework_cluster", "model_split",
    "full_qc_hard_pass", "full_qc_status", "replacement_used",
]
CLAIM = (
    "Computational sequence/developability eligibility and monomer provenance only; "
    "not binding, affinity, competition, experimental blocking, blocker probability, or Docking Gold."
)


class InputReleaseError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InputReleaseError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True); handle.write("\n")
            handle.flush(); os.fsync(handle.fileno())
        os.chmod(name, mode); os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0, f"missing_or_invalid_tsv:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        require(None not in reader.fieldnames and all(None not in row for row in rows), f"ragged_tsv:{path}")
        return list(reader.fieldnames or []), rows


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(rows); handle.flush(); os.fsync(handle.fileno())
        os.chmod(name, 0o444); os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def parse_bool(value: str, field: str) -> bool:
    normalized = str(value).strip().lower()
    require(normalized in {"true", "false"}, f"invalid_bool:{field}:{value!r}")
    return normalized == "true"


def pdb_sequence(path: Path) -> tuple[str, str]:
    by_chain: dict[str, list[str]] = {}
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 54 or line[12:16].strip() != "CA":
            continue
        chain, resseq, icode, resname = line[21], line[22:26], line[26], line[17:20].strip()
        token = (chain, resseq, icode)
        if token not in seen:
            seen.add(token); by_chain.setdefault(chain, []).append(AA3.get(resname, "X"))
    matches = [(chain, "".join(sequence)) for chain, sequence in by_chain.items()]
    require(bool(matches), f"pdb_has_no_atom_ca:{path}")
    return max(matches, key=lambda item: len(item[1]))


def normalize_chain(source: Path, destination: Path, sequence: str) -> str:
    chain_sequences: dict[str, str] = {}
    for chain in {line[21] for line in source.read_text(errors="strict").splitlines() if line.startswith("ATOM  ") and len(line) >= 54}:
        rows: list[str] = []; seen: set[tuple[str, str]] = set()
        for line in source.read_text(errors="strict").splitlines():
            if not line.startswith("ATOM  ") or len(line) < 54 or line[21] != chain or line[12:16].strip() != "CA": continue
            key = (line[22:26], line[26])
            if key not in seen: seen.add(key); rows.append(AA3.get(line[17:20].strip(), "X"))
        chain_sequences[chain] = "".join(rows)
    matches = [chain for chain, observed in chain_sequences.items() if observed == sequence]
    require(len(matches) == 1, f"monomer_exact_sequence_chain_count:{len(matches)}")
    chain = matches[0]; residue_map: dict[tuple[str, str], int] = {}; output: list[str] = []
    for raw in source.read_text(errors="strict").splitlines():
        if not raw.startswith("ATOM  ") or len(raw) < 54 or raw[21] != chain: continue
        line = raw.ljust(80); key = (line[22:26], line[26]); residue_map.setdefault(key, len(residue_map) + 1)
        output.append(f"{line[:21]}A{residue_map[key]:4d} {line[27:]}".rstrip())
    require(len(residue_map) == len(sequence), "normalized_residue_count_mismatch")
    destination.write_text("\n".join(output) + "\nTER\nEND\n", encoding="utf-8")
    chain_name, observed = pdb_sequence(destination)
    require(chain_name == "A" and observed == sequence and not any(line.startswith("HETATM") for line in destination.read_text().splitlines()), "normalized_sequence_or_hetatm_gate_failed")
    return chain


def validate_upstream() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    require(os.environ.get("PYTHONOPTIMIZE", "") in {"", "0"}, "PYTHONOPTIMIZE_forbidden")
    require(not os.environ.get("BASH_ENV") and not os.environ.get("PYTHONPATH"), "poison_environment_forbidden")
    require(sha256(MANIFEST) == EXPECTED["manifest"], "manifest_hash_mismatch")
    for name, path in STATIC_PATHS.items():
        require(path.is_file() and not path.is_symlink() and sha256(path) == EXPECTED[name], f"static_hash_mismatch:{name}")
    manifest_fields, manifest_rows = read_tsv(MANIFEST)
    require(len(manifest_rows) == 96 and len({row["candidate_id"] for row in manifest_rows}) == 96, "manifest_96_identity_closure_failed")
    require(all(hashlib.sha256(row["sequence"].encode()).hexdigest() == row["sequence_sha256"] for row in manifest_rows), "manifest_sequence_hash_mismatch")
    terminal = json.loads(TERMINAL.read_text()); complete = json.loads(COMPLETE.read_text())
    require(terminal.get("status") == "PASS_V4_F96_SEQUENCE_DEVELOPABILITY_FULL_QC_RECOVERY_V2_COMPLETE", "fullqc_terminal_status_invalid")
    require(complete.get("status") == terminal.get("status") and complete.get("terminal_summary_sha256") == sha256(TERMINAL), "fullqc_complete_binding_invalid")
    require(terminal.get("input_manifest_sha256") == EXPECTED["manifest"] and terminal.get("no_replacement") is True and terminal.get("model_based_selection") is False, "fullqc_policy_binding_invalid")
    require(terminal.get("cascade_output_sha256", {}).get("full_merged.tsv") == sha256(FULL_MERGED), "full_merged_binding_invalid")
    _, fast_rows = read_tsv(FAST_MERGED); _, full_rows = read_tsv(FULL_MERGED)
    require(len(fast_rows) == 96 and len({row["candidate_id"] for row in fast_rows}) == 96, "fast96_closure_failed")
    require(len({row["candidate_id"] for row in full_rows}) == len(full_rows), "full_duplicate_candidate")
    manifest_ids = {row["candidate_id"] for row in manifest_rows}; require({row["candidate_id"] for row in full_rows} <= manifest_ids, "full_unknown_candidate")
    return manifest_rows, full_rows, terminal


def build_eligibility(manifest_rows: list[dict[str, str]], full_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_id = {row["candidate_id"]: row for row in full_rows}; output: list[dict[str, str]] = []
    for source in manifest_rows:
        qc = by_id.get(source["candidate_id"])
        hard_pass = qc is not None and not parse_bool(qc.get("hard_fail", ""), "hard_fail")
        output.append({
            "candidate_id": source["candidate_id"], "sequence_sha256": source["sequence_sha256"],
            "parent_framework_cluster": source["parent_framework_cluster"], "model_split": source["model_split"],
            "full_qc_hard_pass": str(hard_pass).lower(),
            "full_qc_status": "PASS_FULL_QC_HARD_GATE" if hard_pass else ("FAIL_FULL_QC_HARD_GATE" if qc is not None else "FAIL_FAST_QC_HARD_GATE"),
            "replacement_used": "false",
        })
    return output


def run_one(root: Path, source: dict[str, str], gpu: int) -> dict[str, Any]:
    cid, sequence = source["candidate_id"], source["sequence"]
    outdir = root / "monomers" / cid; outdir.mkdir(parents=True, exist_ok=True)
    raw, normalized = outdir / "nbb2.raw.pdb", outdir / "nbb2.chainA.pdb"
    env = dict(os.environ); env.update({"CUDA_VISIBLE_DEVICES": str(gpu), "OMP_NUM_THREADS":"4", "MKL_NUM_THREADS":"4", "OPENBLAS_NUM_THREADS":"4"})
    attempts: list[dict[str, Any]] = []
    for mode, extra in (("REFINED", []), ("UNREFINED_FALLBACK", ["-u"])):
        command = [str(NBB2), "-H", sequence, "-o", str(raw), "--n_threads", "4", *extra, "-v"]
        completed = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log = outdir / f"{mode.lower()}.log"; log.write_text(f"$ {shlex.join(command)}\n{completed.stdout}\n[exit_code] {completed.returncode}\n")
        attempts.append({"mode":mode, "exit_code":completed.returncode, "log_sha256":sha256(log)})
        if completed.returncode == 0:
            try:
                source_chain = normalize_chain(raw, normalized, sequence)
                return {"candidate_id":cid, "sequence_sha256":source["sequence_sha256"], "monomer_status":"SUCCESS", "source_chain":source_chain, "frozen_chain":"A", "pdb_path":str(normalized), "pdb_sha256":sha256(normalized), "attempts_json":json.dumps(attempts,separators=(",",":")), "technical_failure_reason":""}
            except Exception as error:
                attempts[-1]["normalization_error"] = f"{type(error).__name__}:{error}"
    return {"candidate_id":cid, "sequence_sha256":source["sequence_sha256"], "monomer_status":"TECHNICAL_FAILURE", "source_chain":"", "frozen_chain":"", "pdb_path":"", "pdb_sha256":"", "attempts_json":json.dumps(attempts,separators=(",",":")), "technical_failure_reason":"NANOBODYBUILDER2_REFINED_AND_UNREFINED_FAILED_OR_INVALID"}


def run() -> dict[str, Any]:
    manifest_rows, full_rows, terminal = validate_upstream(); eligibility = build_eligibility(manifest_rows, full_rows)
    hard_ids = {row["candidate_id"] for row in eligibility if row["full_qc_hard_pass"] == "true"}
    hard_sources = [row for row in manifest_rows if row["candidate_id"] in hard_ids]
    staging = OUTPUT_ROOT / f".staging.{os.getpid()}"; require(not staging.exists(), "staging_exists"); staging.mkdir(parents=True)
    try:
        eligibility_path = staging / "full_qc_eligibility.tsv"; write_tsv(eligibility_path, eligibility, ELIGIBILITY_FIELDS)
        records: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(run_one, staging, row, index % 4): row for index, row in enumerate(hard_sources)}
            for future in as_completed(futures): records.append(future.result())
        records.sort(key=lambda row: next(i for i, source in enumerate(hard_sources) if source["candidate_id"] == row["candidate_id"]))
        fields = ["candidate_id","sequence_sha256","monomer_status","source_chain","frozen_chain","pdb_path","pdb_sha256","attempts_json","technical_failure_reason"]
        monomer_manifest = staging / "monomer_manifest.tsv"; write_tsv(monomer_manifest, records, fields)
        successful = sum(row["monomer_status"] == "SUCCESS" for row in records)
        closure = hashlib.sha256((sha256(eligibility_path)+sha256(monomer_manifest)+"".join(row["pdb_sha256"] for row in records)).encode()).hexdigest()
        release = OUTPUT_ROOT / "releases" / closure; release.parent.mkdir(parents=True, exist_ok=True)
        require(not release.exists(), "content_addressed_release_collision"); os.replace(staging, release)
        eligibility_path, monomer_manifest = release / eligibility_path.name, release / monomer_manifest.name
        receipt = {
            "schema_version":"phase2_v4_f96_full_qc_eligibility_receipt_v1", "status":"PASS_V4_F96_FULL_QC_ELIGIBILITY_FROZEN_NO_REPLACEMENT", "execution_mode":"production",
            "manifest_sha256":EXPECTED["manifest"], "eligibility":{"path":str(eligibility_path),"sha256":sha256(eligibility_path)},
            "row_count":96, "hard_pass_count":len(hard_sources), "replacement_count":0,
            "node1_input_release":{"release_path":str(release),"release_id":closure,"monomer_manifest_sha256":sha256(monomer_manifest),"monomer_success_count":successful,"monomer_failure_count":len(records)-successful},
            "full_qc_terminal_sha256":sha256(TERMINAL), "full_qc_complete_sha256":sha256(COMPLETE), "full_qc_full_merged_sha256":sha256(FULL_MERGED),
            "all_hard_pass_monomers_attempted":True, "no_replacement":True, "no_imputation":True, "surrogate_prediction_paths_read":0, "docking_label_paths_read":0, "claim_boundary":CLAIM,
        }
        atomic_json(release / "full_qc_eligibility.receipt.json", receipt)
        pointer = {"schema_version":"phase2_v4_f96_node1_docking_input_release_pointer_v1_1", "status":"PASS_NODE1_V4_F96_DOCKING_INPUT_RELEASE_READY", "release_id":closure,"release_path":str(release),"eligibility_receipt_sha256":sha256(release / "full_qc_eligibility.receipt.json"),"hard_pass_count":len(hard_sources),"monomer_attempt_count":len(records),"no_eligible_docking":len(hard_sources)==0,"published_at_utc":now(),"claim_boundary":CLAIM}
        atomic_json(OUTPUT_ROOT / "CURRENT_RELEASE.json", pointer)
        return pointer
    except BaseException:
        if staging.exists():
            import shutil; shutil.rmtree(staging)
        raise


def main() -> int:
    if "--smoke-test" in sys.argv:
        print(json.dumps({"status":"PASS_NODE1_V4_F96_DOCKING_INPUT_RUNNER_SMOKE","canonical_fullqc_root":str(FULLQC_ROOT),"canonical_output_root":str(OUTPUT_ROOT),"candidate_count":96,"gpu_ids":[0,1,2,3],"label_paths_read":0},sort_keys=True)); return 0
    try:
        print(json.dumps(run(), indent=2, sort_keys=True)); return 0
    except BaseException as error:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        atomic_json(OUTPUT_ROOT / "FAILED.json", {"status":"FAIL_NODE1_V4_F96_DOCKING_INPUT_RELEASE","error":f"{type(error).__name__}:{error}","failed_at_utc":now(),"claim_boundary":CLAIM})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
