#!/usr/bin/env python3
"""Build the development-only V1.3 dual47/completion15 HADDOCK3 package."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_TEACHER_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_v1_manifest.csv"
DEFAULT_PILOT_MANIFEST = EXP_DIR / "data_splits/pvrig_v3_p2/dual_docking_pilot64_manifest.csv"
DEFAULT_OLD_PACKAGE = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_package_v2"
DEFAULT_OLD_SELECTED_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_v2_node1_selected"
DEFAULT_8X6B_RECEPTOR = WORKSPACE_ROOT / "docking/candidates/v2_5_pose_batch/inputs/pvrig_8x6b_chainB.pdb"
DEFAULT_9E6Y_STRUCTURE = DATA_ROOT / "structures/9E6Y.pdb"
DEFAULT_HOTSPOT_MANIFEST = DATA_ROOT / "structures/PVRIG_hotspot_set_v1.csv"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_completion15_package"

PROTOCOL_ID = "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15"
OLD_PROTOCOL_ID = "DG_A_PILOT64_V1_1"
HADDOCK3_VERSION_CONTRACT = "2025.11.0"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_v3_p2_docking_gold_v1_3_dual47_completion15_20260714"
EXPECTED_CASES = 47
EXPECTED_REUSE_CASES = 32
EXPECTED_NEW_CASES = 15
EXPECTED_RUNS = 94
EXPECTED_REUSE_RUNS = 64
EXPECTED_NEW_RUNS = 30
EXPECTED_HOTSPOTS = 23
NCORES = 4
TOPOAA_INISEED = 917
RIGIDBODY_SAMPLING = 40
RIGIDBODY_TOLERANCE = 5
FLEXREF_TOLERANCE = 20
EMREF_TOLERANCE = 20
SEED_BY_RECEPTOR = {"8X6B": 917, "9E6Y": 20917}
STAGE_OUTPUT_REQUIREMENTS = {
    "topoaa": {"operator": "eq", "value": 2},
    "rigidbody": {"operator": "ge", "value": 38},
    "seletop": {"operator": "eq", "value": 10},
    "flexref": {"operator": "ge", "value": 8},
    "emref": {"operator": "ge", "value": 8},
}
CORE_DIRECT_BLOCKERS = {
    "case02_pos_01_PVRIG-151_HR151", "case02_pos_02_PVRIG-20",
    "case02_pos_03_PVRIG-30", "case02_pos_04_PVRIG-38", "case02_pos_05_PVRIG-39",
}
SAME_FAMILY_SUPPORTS = {
    "case02_pos_06_20H5", "case02_pos_07_30H2", "case02_pos_08_39H2",
    "case02_pos_09_39H4", "case02_pos_10_151H7", "case02_pos_11_151H8",
}
CLAIM_BOUNDARY = (
    "development_only_independent_dual_receptor_computational_docking_inputs; "
    "not training Gold, formal validation, experimental binding, affinity, or blocking truth"
)
RECEPTOR_SPECS = {
    "8X6B": {"hotspot_column": "pdb_8x6b_ref", "source_chain": "B"},
    "9E6Y": {"hotspot_column": "pdb_9e6y_ref", "source_chain": "A"},
}
AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}

CASE_FIELDS = [
    "schema_version", "case_rank", "case_id", "candidate_id", "family", "anchor_class",
    "calibration_role", "sequence", "sequence_sha256", "teacher_manifest_relpath",
    "teacher_manifest_sha256", "teacher_manifest_row_sha256", "source_workdir",
    "execution_mode", "old_pilot_id", "formal_eligible", "training_label_release_eligible",
    "docking_gold_release_eligible", "claim_boundary", "case_manifest_row_sha256",
]
RUN_FIELDS = [
    "schema_version", "protocol_id", "run_id", "case_rank", "case_id", "candidate_id",
    "family", "anchor_class", "calibration_role", "sequence_sha256",
    "teacher_manifest_relpath", "teacher_manifest_sha256", "teacher_manifest_row_sha256",
    "execution_mode", "receptor_id", "seed_role", "topoaa_iniseed", "rigidbody_iniseed",
    "rigidbody_seed_start", "rigidbody_seed_end", "ncores", "rigidbody_sampling",
    "rigidbody_tolerance", "seletop_select", "flexref_tolerance", "emref_tolerance",
    "cdr1_range", "cdr2_range", "cdr3_range", "config_relpath", "config_sha256",
    "run_workspace_relpath", "run_dir_relpath", "completion_relpath", "log_relpath",
    "monomer_relpath", "monomer_sha256", "receptor_relpath", "receptor_sha256",
    "restraint_relpath", "restraint_sha256", "hotspot_relpath", "hotspot_sha256",
    "source_run_id", "fixed_top8_policy", "formal_eligible",
    "training_label_release_eligible", "docking_gold_release_eligible", "claim_boundary",
    "run_manifest_row_sha256",
]
REUSE_EXTRA_FIELDS = [
    "source_protocol_id", "source_old_remote_root", "source_old_package_relpath",
    "source_old_package_audit_sha256", "source_old_controller_relpath",
    "source_old_controller_sha256", "source_old_run_manifest_relpath",
    "source_old_run_manifest_sha256", "source_old_run_manifest_row_sha256",
    "source_config_relpath", "source_config_sha256", "source_completion_relpath",
    "source_completion_sha256", "source_completion_status", "source_completion_exit_code",
    "source_stage_output_counts_json", "source_emref_io_relpath", "source_emref_io_sha256",
    "source_emref_output_count", "source_emref_params_relpath", "source_emref_params_sha256",
    "v1_3_emref_gate_status", "source_final_stage_ignored", "exact_reuse_hash_closed",
    "reuse_manifest_row_sha256",
]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Missing or empty required file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_sha256(row: Mapping[str, Any], hash_field: str) -> str:
    return sha256_bytes(canonical_json({k: v for k, v in row.items() if k != hash_field}).encode("utf-8"))


def workspace_relative(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE_ROOT.resolve()).as_posix()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[dict[str, str]], fields: Sequence[str]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pdb_residues(path: Path, chain: str) -> list[tuple[tuple[int, str], str]]:
    residues: list[tuple[tuple[int, str], str]] = []
    seen: dict[tuple[int, str], str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27 or line[21] != chain:
            continue
        key = (int(line[22:26]), line[26])
        name = line[17:20].strip()
        if key not in seen:
            seen[key] = name
            residues.append((key, name))
        elif seen[key] != name:
            raise ValueError(f"Conflicting residue names in {path}: {key}")
    if not residues:
        raise ValueError(f"No ATOM residues for chain {chain}: {path}")
    return residues


def verify_monomer(path: Path, sequence: str) -> str:
    residues = pdb_residues(path, "A")
    if [key for key, _ in residues] != [(i, " ") for i in range(1, len(sequence) + 1)]:
        raise ValueError(f"Monomer is not numbered consecutively 1..N: {path}")
    observed = "".join(AA3_TO_1[name] for _, name in residues)
    if observed != sequence:
        raise ValueError(f"Monomer sequence mismatch: {path}")
    return sha256_file(path)


def consecutive_groups(values: Iterable[int]) -> list[tuple[int, int]]:
    numbers = list(values)
    if not numbers or numbers != sorted(set(numbers)):
        raise ValueError("CDR residues must be non-empty, sorted, and unique")
    groups: list[list[int]] = []
    for number in numbers:
        if not groups or number != groups[-1][-1] + 1:
            groups.append([number])
        else:
            groups[-1].append(number)
    return [(group[0], group[-1]) for group in groups]


def cdr_ranges(workdir: Path, candidate_id: str, sequence: str) -> dict[str, tuple[int, int]]:
    source = workdir / "haddock3/data" / f"{candidate_id}_cdr_residues_seq_numbering.txt"
    groups = consecutive_groups(int(value) for value in source.read_text(encoding="utf-8").split())
    if len(groups) != 3 or groups[-1][1] > len(sequence):
        raise ValueError(f"Expected three valid CDR groups in {source}: {groups}")
    return dict(zip(("cdr1", "cdr2", "cdr3"), groups, strict=True))


def format_range(value: tuple[int, int]) -> str:
    return f"{value[0]}-{value[1]}"


def classify_anchor(candidate_id: str) -> str:
    if candidate_id in CORE_DIRECT_BLOCKERS:
        return "core_direct_blocker"
    if candidate_id in SAME_FAMILY_SUPPORTS:
        return "same_family_support"
    return "control"


def extract_relabelled_chain(source: Path, source_chain: str, destination: Path) -> None:
    lines = [line[:21] + "B" + line[22:] for line in source.read_text(encoding="ascii").splitlines()
             if line.startswith("ATOM  ") and len(line) > 21 and line[21] == source_chain]
    if not lines:
        raise ValueError(f"No ATOM records for chain {source_chain}: {source}")
    destination.write_text("\n".join(lines) + "\nTER\nEND\n", encoding="ascii")


def derive_hotspots(path: Path, receptor_id: str) -> list[dict[str, Any]]:
    spec = RECEPTOR_SPECS[receptor_id]
    pattern = re.compile(r"^([A-Za-z0-9]):(-?\d+)([A-Z])$")
    rows: list[dict[str, Any]] = []
    for row in read_csv(path):
        if row["hotspot_class"] not in {"core_hotspot", "secondary_hotspot"}:
            continue
        match = pattern.fullmatch(row[spec["hotspot_column"]])
        if not match or match.group(1) != spec["source_chain"]:
            raise ValueError(f"Malformed {receptor_id} hotspot: {row[spec['hotspot_column']]}")
        rows.append({"resseq": int(match.group(2)), "aa": match.group(3)})
    if len(rows) != EXPECTED_HOTSPOTS or len({row["resseq"] for row in rows}) != EXPECTED_HOTSPOTS:
        raise ValueError(f"Expected {EXPECTED_HOTSPOTS} unique {receptor_id} hotspots")
    return rows


def verify_hotspots(receptor: Path, hotspots: Sequence[dict[str, Any]]) -> None:
    residues = {key[0]: AA3_TO_1[name] for key, name in pdb_residues(receptor, "B") if key[1] == " "}
    for hotspot in hotspots:
        if residues.get(hotspot["resseq"]) != hotspot["aa"]:
            raise ValueError(f"Hotspot mismatch in {receptor}: {hotspot}")


def restraint_text(ranges: Mapping[str, tuple[int, int]], hotspots: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    residues = [i for name in ("cdr1", "cdr2", "cdr3") for i in range(ranges[name][0], ranges[name][1] + 1)]
    for residue in residues:
        lines.extend([f"assign (resi {residue} and segid A)", "("])
        for index, hotspot in enumerate(hotspots):
            prefix = "       " if index == 0 else "        or\n       "
            lines.append(f"{prefix}(resi {hotspot['resseq']} and segid B)")
        lines.append(") 2.0 2.0 0.0\n")
    return "\n".join(lines) + "\n"


def config_text(run_id: str, monomer: str, receptor: str, restraint: str, seed: int) -> str:
    return f'''# V1.3 completion15 {run_id}; development-only, stop after 4_emref.
# Protocol: {PROTOCOL_ID}
run_dir = "run_{run_id}"
mode = "local"
ncores = {NCORES}

molecules = ["../../{monomer}", "../../{receptor}"]

[topoaa]
iniseed = {TOPOAA_INISEED}

[rigidbody]
ambig_fname = "../../{restraint}"
iniseed = {seed}
tolerance = {RIGIDBODY_TOLERANCE}
sampling = {RIGIDBODY_SAMPLING}

[seletop]
select = 10

[flexref]
tolerance = {FLEXREF_TOLERANCE}
ambig_fname = "../../{restraint}"

[emref]
tolerance = {EMREF_TOLERANCE}
ambig_fname = "../../{restraint}"
'''


def stage_counts_pass(counts: Mapping[str, int]) -> bool:
    for stage, requirement in STAGE_OUTPUT_REQUIREMENTS.items():
        observed = counts.get(stage, 0)
        if requirement["operator"] == "eq" and observed != requirement["value"]:
            return False
        if requirement["operator"] == "ge" and observed < requirement["value"]:
            return False
    return True


def controller_source() -> str:
    return f'''#!/usr/bin/env python3
"""Run only the 30 preregistered V1.3 completion jobs through 4_emref."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, shutil, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_VERSION = {HADDOCK3_VERSION_CONTRACT!r}
PROTOCOL_ID = {PROTOCOL_ID!r}
MAX_CONCURRENT_JOBS = 5
PASS_STATUS = "PASS_4_EMREF_TOP8_READY"
STAGE_IO_RELPATHS = {{
    "topoaa": "0_topoaa/io.json", "rigidbody": "1_rigidbody/io.json",
    "seletop": "2_seletop/io.json", "flexref": "3_flexref/io.json",
    "emref": "4_emref/io.json",
}}
STAGE_OUTPUT_REQUIREMENTS = {STAGE_OUTPUT_REQUIREMENTS!r}

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{{path.name}}.{{os.getpid()}}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    temporary.replace(path)

def stage_output_counts(run_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {{}}
    for stage, relative in STAGE_IO_RELPATHS.items():
        try:
            payload = json.loads((run_dir / relative).read_text(encoding="utf-8"))
            output = payload.get("output")
            if not isinstance(output, list):
                raise ValueError("output is not a list")
            counts[stage] = len(output)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            counts[stage] = 0
    return counts

def stage_counts_pass(counts: dict[str, int]) -> bool:
    for stage, requirement in STAGE_OUTPUT_REQUIREMENTS.items():
        observed = counts.get(stage, 0)
        expected = int(requirement["value"])
        if requirement["operator"] == "eq" and observed != expected:
            return False
        if requirement["operator"] == "ge" and observed < expected:
            return False
    return True

def verify_inputs(root: Path, row: dict[str, str]) -> None:
    for path_field, hash_field in (("config_relpath", "config_sha256"),
        ("monomer_relpath", "monomer_sha256"), ("receptor_relpath", "receptor_sha256"),
        ("restraint_relpath", "restraint_sha256"), ("hotspot_relpath", "hotspot_sha256")):
        path = root / row[path_field]
        if not path.is_file() or sha256_file(path) != row[hash_field]:
            raise RuntimeError(f"Hash closure failed for {{row['run_id']}}: {{path_field}}")

def reusable(completion: Path, row: dict[str, str], counts: dict[str, int]) -> bool:
    try:
        payload = json.loads(completion.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return (payload.get("status") == PASS_STATUS and payload.get("exit_code") == 0
            and payload.get("protocol_id") == PROTOCOL_ID
            and payload.get("config_sha256") == row["config_sha256"]
            and stage_counts_pass(counts))

def archive_partial(root: Path, row: dict[str, str], run_dir: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = root / "partial_runs" / row["run_id"] / f"{{run_dir.name}}.{{stamp}}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(run_dir), str(destination))
    return destination.relative_to(root).as_posix()

def wait_for_load(max_load1: float, poll_seconds: float) -> None:
    while float(Path("/proc/loadavg").read_text(encoding="ascii").split()[0]) > max_load1:
        time.sleep(poll_seconds)

def payload(row: dict[str, str], status: str, counts: dict[str, int], **extra: object) -> dict[str, object]:
    result: dict[str, object] = {{
        "schema_version": "phase2_v3_p2_v1_3_completion15_run_completion_v1",
        "protocol_id": PROTOCOL_ID, "run_id": row["run_id"], "case_id": row["case_id"],
        "candidate_id": row["candidate_id"], "receptor_id": row["receptor_id"],
        "status": status, "stage_output_counts": counts,
        "stage_output_requirements": STAGE_OUTPUT_REQUIREMENTS,
        "config_sha256": row["config_sha256"], "monomer_sha256": row["monomer_sha256"],
        "receptor_sha256": row["receptor_sha256"], "fixed_top8_selection_performed": False,
        "fixed_top8_policy": "deferred_4_emref_score_order_no_backfill",
        "formal_eligible": False, "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }}
    result.update(extra)
    return result

def run_one(root: Path, haddock_bin: Path, row: dict[str, str], max_load1: float, poll: float) -> dict[str, object]:
    completion, run_dir = root / row["completion_relpath"], root / row["run_dir_relpath"]
    try:
        verify_inputs(root, row)
        counts = stage_output_counts(run_dir)
        if reusable(completion, row, counts):
            result = payload(row, PASS_STATUS, counts, exit_code=0, reused=True)
            atomic_json(completion, result)
            return result
        archived = archive_partial(root, row, run_dir) if run_dir.exists() else ""
        wait_for_load(max_load1, poll)
        log_path = root / row["log_relpath"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            completed = subprocess.run([str(haddock_bin), Path(row["config_relpath"]).name],
                cwd=root / row["run_workspace_relpath"], stdout=log, stderr=subprocess.STDOUT,
                text=True, check=False)
        counts = stage_output_counts(run_dir)
        status = PASS_STATUS if completed.returncode == 0 and stage_counts_pass(counts) else "FAIL_4_EMREF_GATE"
        result = payload(row, status, counts, exit_code=completed.returncode, reused=False,
                         archived_partial_relpath=archived)
    except Exception as error:
        counts = stage_output_counts(run_dir)
        result = payload(row, "FAIL_CONTROLLER_EXCEPTION", counts, exit_code=None, error=str(error))
    atomic_json(completion, result)
    return result

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--haddock-bin", type=Path,
        default=Path(os.environ.get("HADDOCK3_BIN", "/data/qlyu/anaconda3/envs/haddock3/bin/haddock3")))
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--max-load1", type=float, default=float(os.environ.get("PVRIG_DOCKING_MAX_LOAD1", "55")))
    parser.add_argument("--load-poll-seconds", type=float, default=60.0)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--run-id", action="append")
    parser.add_argument("--receptor", choices=("8X6B", "9E6Y"), action="append")
    parser.add_argument("--list-only", action="store_true")
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    if not 1 <= args.max_workers <= MAX_CONCURRENT_JOBS:
        raise SystemExit(f"--max-workers must be between 1 and {{MAX_CONCURRENT_JOBS}}")
    if args.max_load1 <= 0 or args.load_poll_seconds <= 0:
        raise SystemExit("load limits must be positive")
    with (args.root / "manifests/new_run_manifest.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows = [row for row in rows if (not args.case_id or row["case_id"] in args.case_id)
            and (not args.run_id or row["run_id"] in args.run_id)
            and (not args.receptor or row["receptor_id"] in args.receptor)]
    if not rows:
        raise SystemExit("No new completion runs match the requested filters")
    if args.list_only:
        print(json.dumps([{{key: row[key] for key in ("run_id", "case_id", "receptor_id", "rigidbody_iniseed")}}
                          for row in rows], indent=2))
        return
    version = subprocess.run([str(args.haddock_bin), "--version"], capture_output=True, text=True, check=False)
    version_text = (version.stdout + "\\n" + version.stderr).strip()
    if version.returncode or EXPECTED_VERSION not in version_text:
        raise SystemExit(f"HADDOCK3 version contract failed: {{version_text!r}}")
    failures = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {{executor.submit(run_one, args.root, args.haddock_bin, row,
                    args.max_load1, args.load_poll_seconds): row for row in rows}}
        for future in as_completed(futures):
            result = future.result()
            print(json.dumps(result, sort_keys=True), flush=True)
            failures += result["status"] != PASS_STATUS
    raise SystemExit(1 if failures else 0)

if __name__ == "__main__":
    main()
'''


def load_case_records(teacher_manifest: Path, pilot_manifest: Path) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    teacher_rows = read_csv(teacher_manifest)
    pilot_rows = read_csv(pilot_manifest)
    if len(teacher_rows) != EXPECTED_CASES or len({r["candidate_id"] for r in teacher_rows}) != EXPECTED_CASES:
        raise ValueError("Teacher manifest must contain exactly 47 unique cases")
    pilot_by_source = {row["source_candidate_id"]: row for row in pilot_rows}
    if len(pilot_by_source) != len(pilot_rows):
        raise ValueError("Pilot64 source candidates are not unique")
    teacher_sha = sha256_file(teacher_manifest)
    output: list[dict[str, str]] = []
    matched: dict[str, dict[str, str]] = {}
    for rank, raw in enumerate(teacher_rows, 1):
        candidate = raw["candidate_id"]
        if sha256_bytes(raw["sequence"].encode("ascii")) != raw["sequence_sha256"]:
            raise ValueError(f"Sequence hash mismatch: {candidate}")
        pilot = pilot_by_source.get(candidate)
        if pilot:
            if pilot["sequence_sha256"] != raw["sequence_sha256"] or pilot["sequence"] != raw["sequence"]:
                raise ValueError(f"Pilot/teacher sequence mismatch: {candidate}")
            matched[candidate] = pilot
        row = {
            "schema_version": "phase2_v3_p2_v1_3_dual47_case_manifest_v1",
            "case_rank": str(rank), "case_id": candidate, "candidate_id": candidate,
            "family": raw["family"], "anchor_class": classify_anchor(candidate),
            "calibration_role": raw["calibration_role"], "sequence": raw["sequence"],
            "sequence_sha256": raw["sequence_sha256"],
            "teacher_manifest_relpath": workspace_relative(teacher_manifest),
            "teacher_manifest_sha256": teacher_sha,
            "teacher_manifest_row_sha256": sha256_bytes(canonical_json(raw).encode("utf-8")),
            "source_workdir": workspace_relative(Path(raw["workdir"])),
            "execution_mode": "REUSE_OLD_PILOT64_MAIN" if pilot else "NEW_DUAL_DOCKING_COMPLETION",
            "old_pilot_id": pilot["pilot_id"] if pilot else "", "formal_eligible": "false",
            "training_label_release_eligible": "false", "docking_gold_release_eligible": "false",
            "claim_boundary": CLAIM_BOUNDARY, "case_manifest_row_sha256": "",
        }
        row["case_manifest_row_sha256"] = row_sha256(row, "case_manifest_row_sha256")
        output.append(row)
    counts = Counter(row["anchor_class"] for row in output)
    if counts != Counter({"core_direct_blocker": 5, "same_family_support": 6, "control": 36}):
        raise AssertionError(f"Unexpected anchor composition: {counts}")
    if len(matched) != EXPECTED_REUSE_CASES:
        raise AssertionError(f"Expected 32 exact Pilot64 overlaps, found {len(matched)}")
    return output, matched


def build_receptors(outdir: Path, receptor_8x6b: Path, structure_9e6y: Path, hotspot_manifest: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    receptor_dir = outdir / "receptors"
    receptor_dir.mkdir(parents=True)
    paths = {"8X6B": receptor_dir / "pvrig_8x6b_chainB.pdb", "9E6Y": receptor_dir / "pvrig_9e6y_chainB.pdb"}
    shutil.copyfile(receptor_8x6b, paths["8X6B"])
    extract_relabelled_chain(structure_9e6y, "A", paths["9E6Y"])
    info: dict[str, dict[str, Any]] = {}
    protocols: list[dict[str, str]] = []
    for receptor_id in ("8X6B", "9E6Y"):
        hotspots = derive_hotspots(hotspot_manifest, receptor_id)
        verify_hotspots(paths[receptor_id], hotspots)
        hotspot_rel = f"hotspots/hotspot_residues_{receptor_id.lower()}.txt"
        hotspot_path = outdir / hotspot_rel
        hotspot_path.parent.mkdir(parents=True, exist_ok=True)
        hotspot_path.write_text("\n".join(str(x["resseq"]) for x in hotspots) + "\n", encoding="ascii")
        seed = SEED_BY_RECEPTOR[receptor_id]
        info[receptor_id] = {"relpath": paths[receptor_id].relative_to(outdir).as_posix(),
            "sha256": sha256_file(paths[receptor_id]), "hotspots": hotspots,
            "hotspot_relpath": hotspot_rel, "hotspot_sha256": sha256_file(hotspot_path)}
        protocols.append({
            "schema_version": "phase2_v3_p2_v1_3_completion15_protocol_manifest_v1",
            "protocol_id": PROTOCOL_ID, "receptor_id": receptor_id, "source_chain": RECEPTOR_SPECS[receptor_id]["source_chain"],
            "packaged_chain": "B", "vhh_chain": "A", "hotspot_count": str(len(hotspots)),
            "topoaa_iniseed": str(TOPOAA_INISEED), "rigidbody_iniseed": str(seed),
            "rigidbody_seed_start": str(seed + 1), "rigidbody_seed_end": str(seed + RIGIDBODY_SAMPLING),
            "rigidbody_sampling": str(RIGIDBODY_SAMPLING), "rigidbody_tolerance": str(RIGIDBODY_TOLERANCE),
            "seletop_select": "10", "flexref_tolerance": str(FLEXREF_TOLERANCE),
            "emref_tolerance": str(EMREF_TOLERANCE), "ncores": str(NCORES),
            "last_module": "4_emref", "haddock3_version_contract": HADDOCK3_VERSION_CONTRACT,
            "receptor_relpath": info[receptor_id]["relpath"], "receptor_sha256": info[receptor_id]["sha256"],
            "hotspot_relpath": hotspot_rel, "hotspot_sha256": info[receptor_id]["hotspot_sha256"],
            "claim_boundary": CLAIM_BOUNDARY,
        })
    return info, protocols


def old_reuse_context(old_package: Path, old_selected_root: Path) -> dict[str, Any]:
    audit_path = old_package / "package_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    run_manifest = old_package / audit["run_manifest"]
    controller = old_package / audit["controller"]
    if audit["protocol_id"] != OLD_PROTOCOL_ID or audit["haddock3_version_contract"] != HADDOCK3_VERSION_CONTRACT:
        raise ValueError("Old Pilot64 protocol is incompatible")
    if sha256_file(run_manifest) != audit["run_manifest_sha256"] or sha256_file(controller) != audit["controller_sha256"]:
        raise ValueError("Old Pilot64 package hash closure failed")
    if (old_selected_root / "package_audit.json").read_bytes() != audit_path.read_bytes():
        raise ValueError("Selected old output root is not bound to the exact old package")
    rows = read_csv(run_manifest)
    index = {(r["pilot_id"], r["receptor_id"]): r for r in rows if r["seed_role"] == "main"}
    return {"audit": audit, "audit_path": audit_path, "run_manifest": run_manifest,
        "controller": controller, "run_index": index, "selected_root": old_selected_root}


def common_run_row(case: dict[str, str], receptor_id: str, execution_mode: str, ranges: Mapping[str, str]) -> dict[str, str]:
    rank = int(case["case_rank"])
    run_id = f"V13CAL_{rank:03d}__{receptor_id}__main"
    seed = SEED_BY_RECEPTOR[receptor_id]
    return {
        "schema_version": "phase2_v3_p2_v1_3_dual47_run_manifest_v1", "protocol_id": PROTOCOL_ID,
        "run_id": run_id, "case_rank": case["case_rank"], "case_id": case["case_id"],
        "candidate_id": case["candidate_id"], "family": case["family"], "anchor_class": case["anchor_class"],
        "calibration_role": case["calibration_role"], "sequence_sha256": case["sequence_sha256"],
        "teacher_manifest_relpath": case["teacher_manifest_relpath"],
        "teacher_manifest_sha256": case["teacher_manifest_sha256"],
        "teacher_manifest_row_sha256": case["teacher_manifest_row_sha256"], "execution_mode": execution_mode,
        "receptor_id": receptor_id, "seed_role": "main", "topoaa_iniseed": str(TOPOAA_INISEED),
        "rigidbody_iniseed": str(seed), "rigidbody_seed_start": str(seed + 1),
        "rigidbody_seed_end": str(seed + RIGIDBODY_SAMPLING), "ncores": str(NCORES),
        "rigidbody_sampling": str(RIGIDBODY_SAMPLING), "rigidbody_tolerance": str(RIGIDBODY_TOLERANCE),
        "seletop_select": "10", "flexref_tolerance": str(FLEXREF_TOLERANCE),
        "emref_tolerance": str(EMREF_TOLERANCE), "cdr1_range": ranges["cdr1"],
        "cdr2_range": ranges["cdr2"], "cdr3_range": ranges["cdr3"], "config_relpath": "",
        "config_sha256": "", "run_workspace_relpath": "", "run_dir_relpath": "",
        "completion_relpath": "", "log_relpath": "", "monomer_relpath": "", "monomer_sha256": "",
        "receptor_relpath": "", "receptor_sha256": "", "restraint_relpath": "",
        "restraint_sha256": "", "hotspot_relpath": "", "hotspot_sha256": "", "source_run_id": "",
        "fixed_top8_policy": "deferred_4_emref_score_order_no_backfill", "formal_eligible": "false",
        "training_label_release_eligible": "false", "docking_gold_release_eligible": "false",
        "claim_boundary": CLAIM_BOUNDARY, "run_manifest_row_sha256": "",
    }


def build_runs(outdir: Path, cases: Sequence[dict[str, str]], matched: Mapping[str, dict[str, str]], receptors: Mapping[str, dict[str, Any]], old: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    all_rows: list[dict[str, str]] = []
    reuse_rows: list[dict[str, str]] = []
    new_rows: list[dict[str, str]] = []
    monomer_rows: list[dict[str, str]] = []
    for case in cases:
        pilot = matched.get(case["candidate_id"])
        if pilot:
            old_8x = old["run_index"][(pilot["pilot_id"], "8X6B")]
            ranges = {name: old_8x[f"{name}_range"] for name in ("cdr1", "cdr2", "cdr3")}
            for receptor_id in ("8X6B", "9E6Y"):
                source = old["run_index"][(pilot["pilot_id"], receptor_id)]
                for key, expected in (("ncores", "4"), ("rigidbody_sampling", "40"),
                    ("rigidbody_tolerance", "5"), ("seletop_select", "10"),
                    ("flexref_tolerance", "20"), ("emref_tolerance", "20")):
                    if source[key] != expected:
                        raise ValueError(f"Old run protocol mismatch {source['run_id']}: {key}")
                completion_path = old["selected_root"] / source["completion_relpath"]
                completion = json.loads(completion_path.read_text(encoding="utf-8"))
                counts = {k: int(v) for k, v in completion["stage_output_counts"].items() if k in STAGE_OUTPUT_REQUIREMENTS}
                if not stage_counts_pass(counts):
                    raise ValueError(f"Old run does not pass V1.3 4_emref gate: {source['run_id']}")
                emref_dir = old["selected_root"] / source["run_dir_relpath"] / "4_emref"
                io_path, params_path = emref_dir / "io.json", emref_dir / "params.cfg"
                io_payload = json.loads(io_path.read_text(encoding="utf-8"))
                output_count = len(io_payload.get("output", []))
                if output_count < 8:
                    raise ValueError(f"Old run has fewer than 8 emref outputs: {source['run_id']}")
                row = common_run_row(case, receptor_id, "REUSE_OLD_PILOT64_MAIN", ranges)
                row["source_run_id"] = source["run_id"]
                row["run_manifest_row_sha256"] = row_sha256(row, "run_manifest_row_sha256")
                all_rows.append(row)
                extra = {
                    "source_protocol_id": OLD_PROTOCOL_ID, "source_old_remote_root": old["audit"]["remote_root"],
                    "source_old_package_relpath": workspace_relative(Path(old["audit_path"]).parent),
                    "source_old_package_audit_sha256": sha256_file(old["audit_path"]),
                    "source_old_controller_relpath": workspace_relative(old["controller"]),
                    "source_old_controller_sha256": sha256_file(old["controller"]),
                    "source_old_run_manifest_relpath": workspace_relative(old["run_manifest"]),
                    "source_old_run_manifest_sha256": sha256_file(old["run_manifest"]),
                    "source_old_run_manifest_row_sha256": sha256_bytes(canonical_json(source).encode("utf-8")),
                    "source_config_relpath": f"{old['audit']['remote_root']}/{source['config_relpath']}",
                    "source_config_sha256": source["config_sha256"],
                    "source_completion_relpath": workspace_relative(completion_path),
                    "source_completion_sha256": sha256_file(completion_path),
                    "source_completion_status": str(completion.get("status", "")),
                    "source_completion_exit_code": str(completion.get("exit_code", "")),
                    "source_stage_output_counts_json": canonical_json(counts),
                    "source_emref_io_relpath": workspace_relative(io_path), "source_emref_io_sha256": sha256_file(io_path),
                    "source_emref_output_count": str(output_count),
                    "source_emref_params_relpath": workspace_relative(params_path),
                    "source_emref_params_sha256": sha256_file(params_path),
                    "v1_3_emref_gate_status": "PASS_4_EMREF_TOP8_READY",
                    "source_final_stage_ignored": "true", "exact_reuse_hash_closed": "true",
                    "reuse_manifest_row_sha256": "",
                }
                reuse = {**row, **extra}
                reuse["reuse_manifest_row_sha256"] = row_sha256(reuse, "reuse_manifest_row_sha256")
                reuse_rows.append(reuse)
            continue

        workdir = WORKSPACE_ROOT / case["source_workdir"]
        source_monomer = workdir / "haddock3/data" / f"{case['candidate_id']}_vhh_chainA.pdb"
        ranges_raw = cdr_ranges(workdir, case["candidate_id"], case["sequence"])
        source_sha = verify_monomer(source_monomer, case["sequence"])
        monomer_rel = f"monomers/{case['candidate_id']}_vhh_chainA.pdb"
        packaged_monomer = outdir / monomer_rel
        packaged_monomer.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_monomer, packaged_monomer)
        ranges = {name: format_range(ranges_raw[name]) for name in ranges_raw}
        monomer_rows.append({
            "schema_version": "phase2_v3_p2_v1_3_completion15_monomer_manifest_v1",
            "case_rank": case["case_rank"], "case_id": case["case_id"], "candidate_id": case["candidate_id"],
            "family": case["family"], "calibration_role": case["calibration_role"],
            "sequence_sha256": case["sequence_sha256"], "teacher_manifest_row_sha256": case["teacher_manifest_row_sha256"],
            "source_monomer_relpath": workspace_relative(source_monomer), "source_monomer_sha256": source_sha,
            "monomer_relpath": monomer_rel, "monomer_sha256": sha256_file(packaged_monomer),
            "cdr1_range": ranges["cdr1"], "cdr2_range": ranges["cdr2"], "cdr3_range": ranges["cdr3"],
            "pdb_sequence_validated": "true", "claim_boundary": CLAIM_BOUNDARY,
        })
        for receptor_id in ("8X6B", "9E6Y"):
            receptor = receptors[receptor_id]
            row = common_run_row(case, receptor_id, "NEW_DUAL_DOCKING_COMPLETION", ranges)
            restraint_rel = f"restraints/{case['candidate_id']}__{receptor_id}.tbl"
            restraint_path = outdir / restraint_rel
            restraint_path.parent.mkdir(parents=True, exist_ok=True)
            restraint_path.write_text(restraint_text(ranges_raw, receptor["hotspots"]), encoding="ascii")
            workspace_rel = f"runs/{row['run_id']}"
            workspace = outdir / workspace_rel
            workspace.mkdir(parents=True, exist_ok=True)
            config_rel = f"{workspace_rel}/{row['run_id']}.cfg"
            config_path = outdir / config_rel
            config_path.write_text(config_text(row["run_id"], monomer_rel, receptor["relpath"], restraint_rel,
                SEED_BY_RECEPTOR[receptor_id]), encoding="utf-8")
            row.update({
                "config_relpath": config_rel, "config_sha256": sha256_file(config_path),
                "run_workspace_relpath": workspace_rel, "run_dir_relpath": f"{workspace_rel}/run_{row['run_id']}",
                "completion_relpath": f"{workspace_rel}/{row['run_id']}.complete.json",
                "log_relpath": f"{workspace_rel}/{row['run_id']}.log", "monomer_relpath": monomer_rel,
                "monomer_sha256": sha256_file(packaged_monomer), "receptor_relpath": receptor["relpath"],
                "receptor_sha256": receptor["sha256"], "restraint_relpath": restraint_rel,
                "restraint_sha256": sha256_file(restraint_path), "hotspot_relpath": receptor["hotspot_relpath"],
                "hotspot_sha256": receptor["hotspot_sha256"],
            })
            row["run_manifest_row_sha256"] = row_sha256(row, "run_manifest_row_sha256")
            all_rows.append(row)
            new_rows.append(dict(row))
    if (len(all_rows), len(reuse_rows), len(new_rows), len(monomer_rows)) != (94, 64, 30, 15):
        raise AssertionError("V1.3 94/64/30/15 closure failed")
    return all_rows, reuse_rows, new_rows, monomer_rows


def write_content_hashes(outdir: Path) -> Path:
    destination = outdir / "manifests/package_content_sha256.tsv"
    files = sorted(path for path in outdir.rglob("*") if path.is_file()
                   and path not in {destination, outdir / "package_audit.json"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        handle.write("sha256  path\n")
        for path in files:
            handle.write(f"{sha256_file(path)}  {path.relative_to(outdir).as_posix()}\n")
    return destination


def _build_into(outdir: Path, teacher_manifest: Path, pilot_manifest: Path, old_package: Path,
                old_selected_root: Path, receptor_8x6b: Path, structure_9e6y: Path,
                hotspot_manifest: Path) -> dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    cases, matched = load_case_records(teacher_manifest, pilot_manifest)
    receptors, protocols = build_receptors(outdir, receptor_8x6b, structure_9e6y, hotspot_manifest)
    old = old_reuse_context(old_package, old_selected_root)
    all_rows, reuse_rows, new_rows, monomers = build_runs(outdir, cases, matched, receptors, old)
    manifests = outdir / "manifests"
    paths = {
        "case": manifests / "case_manifest.csv", "run": manifests / "run_manifest.csv",
        "reuse": manifests / "exact_reuse_manifest.csv", "new": manifests / "new_run_manifest.csv",
        "monomer": manifests / "new_monomer_manifest.csv", "protocol": manifests / "protocol_manifest.csv",
    }
    write_csv(paths["case"], cases, CASE_FIELDS)
    write_csv(paths["run"], all_rows, RUN_FIELDS)
    write_csv(paths["reuse"], reuse_rows, RUN_FIELDS + REUSE_EXTRA_FIELDS)
    write_csv(paths["new"], new_rows, RUN_FIELDS)
    write_csv(paths["monomer"], monomers, list(monomers[0]))
    write_csv(paths["protocol"], protocols, list(protocols[0]))
    controller = outdir / "scripts/run_v1_3_completion15.py"
    controller.parent.mkdir(parents=True)
    controller.write_text(controller_source(), encoding="utf-8")
    controller.chmod(0o755)
    compile(controller.read_text(encoding="utf-8"), str(controller), "exec")
    content = write_content_hashes(outdir)
    anchor_counts = Counter(case["anchor_class"] for case in cases)
    core_families = {case["family"] for case in cases if case["anchor_class"] == "core_direct_blocker"}
    support_families = {case["family"] for case in cases if case["anchor_class"] == "same_family_support"}
    audit: dict[str, Any] = {
        "status": "PASS_V1_3_DUAL47_COMPLETION15_PACKAGE_READY",
        "schema_version": "phase2_v3_p2_v1_3_dual47_completion15_package_audit_v1",
        "protocol_id": PROTOCOL_ID, "remote_root": REMOTE_ROOT,
        "haddock3_version_contract": HADDOCK3_VERSION_CONTRACT, "candidate_count": len(cases),
        "run_count": len(all_rows), "reuse_case_count": len(matched), "reuse_run_count": len(reuse_rows),
        "new_case_count": len(monomers), "new_run_count": len(new_rows),
        "run_counts_by_execution_mode": dict(sorted(Counter(row["execution_mode"] for row in all_rows).items())),
        "run_counts_by_receptor": dict(sorted(Counter(row["receptor_id"] for row in all_rows).items())),
        "anchor_composition": {"core_direct_blockers": anchor_counts["core_direct_blocker"],
            "same_family_supports": anchor_counts["same_family_support"], "controls": anchor_counts["control"],
            "new_family_count": len(support_families - core_families), "new_family_claimed": False},
        "old_reuse_binding": {"protocol_id": OLD_PROTOCOL_ID, "remote_root": old["audit"]["remote_root"],
            "package_audit_relpath": workspace_relative(old["audit_path"]),
            "package_audit_sha256": sha256_file(old["audit_path"]),
            "run_manifest_relpath": workspace_relative(old["run_manifest"]),
            "run_manifest_sha256": sha256_file(old["run_manifest"]),
            "controller_relpath": workspace_relative(old["controller"]),
            "controller_sha256": sha256_file(old["controller"])},
        "protocol_contract": {"vhh_chain": "A", "receptor_chain": "B", "hotspots_per_receptor": 23,
            "ncores": 4, "topoaa_iniseed": 917, "rigidbody_iniseed": SEED_BY_RECEPTOR,
            "rigidbody_sampling": 40, "module_failure_tolerances": {"rigidbody": 5, "flexref": 20, "emref": 20},
            "seletop_select": 10, "last_module": "4_emref", "stage_output_requirements": STAGE_OUTPUT_REQUIREMENTS,
            "fixed_top8_policy": "deferred_4_emref_score_order_no_backfill", "final_stage_gate": False,
            "backfill_allowed": False},
        "teacher_manifest_relpath": workspace_relative(teacher_manifest),
        "teacher_manifest_sha256": sha256_file(teacher_manifest), "controller": controller.relative_to(outdir).as_posix(),
        "controller_sha256": sha256_file(controller),
        "manifests": {name: {"path": path.relative_to(outdir).as_posix(), "sha256": sha256_file(path)}
                      for name, path in paths.items()},
        "package_content_hash_manifest": content.relative_to(outdir).as_posix(),
        "package_content_hash_manifest_sha256": sha256_file(content),
        "package_content_hash_check_command": "tail -n +2 manifests/package_content_sha256.tsv | sha256sum -c -",
        "formal_eligible": False, "training_label_release_eligible": False,
        "docking_gold_release_eligible": False, "p2_training_ready": False,
        "remote_jobs_launched": False, "scoring_or_calibration_performed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (outdir / "package_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def build_package(teacher_manifest: Path = DEFAULT_TEACHER_MANIFEST,
                  pilot_manifest: Path = DEFAULT_PILOT_MANIFEST,
                  old_package: Path = DEFAULT_OLD_PACKAGE,
                  old_selected_root: Path = DEFAULT_OLD_SELECTED_ROOT,
                  receptor_8x6b: Path = DEFAULT_8X6B_RECEPTOR,
                  structure_9e6y: Path = DEFAULT_9E6Y_STRUCTURE,
                  hotspot_manifest: Path = DEFAULT_HOTSPOT_MANIFEST,
                  outdir: Path = DEFAULT_OUTDIR, force: bool = False) -> dict[str, Any]:
    outdir.parent.mkdir(parents=True, exist_ok=True)
    if outdir.exists() and not force:
        raise FileExistsError(f"Output already exists: {outdir}")
    staging = Path(tempfile.mkdtemp(prefix=f".{outdir.name}.build-", dir=outdir.parent))
    try:
        audit = _build_into(staging, teacher_manifest, pilot_manifest, old_package,
                            old_selected_root, receptor_8x6b, structure_9e6y, hotspot_manifest)
        backup = outdir.with_name(f".{outdir.name}.old-{os.getpid()}")
        if backup.exists():
            shutil.rmtree(backup)
        if outdir.exists():
            outdir.replace(backup)
        try:
            staging.replace(outdir)
        except Exception:
            if backup.exists() and not outdir.exists():
                backup.replace(outdir)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return audit
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-manifest", type=Path, default=DEFAULT_TEACHER_MANIFEST)
    parser.add_argument("--pilot-manifest", type=Path, default=DEFAULT_PILOT_MANIFEST)
    parser.add_argument("--old-package", type=Path, default=DEFAULT_OLD_PACKAGE)
    parser.add_argument("--old-selected-root", type=Path, default=DEFAULT_OLD_SELECTED_ROOT)
    parser.add_argument("--receptor-8x6b", type=Path, default=DEFAULT_8X6B_RECEPTOR)
    parser.add_argument("--structure-9e6y", type=Path, default=DEFAULT_9E6Y_STRUCTURE)
    parser.add_argument("--hotspot-manifest", type=Path, default=DEFAULT_HOTSPOT_MANIFEST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    audit = build_package(args.teacher_manifest, args.pilot_manifest, args.old_package,
        args.old_selected_root, args.receptor_8x6b, args.structure_9e6y,
        args.hotspot_manifest, args.outdir, args.force)
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
