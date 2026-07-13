#!/usr/bin/env python3
"""Build the frozen Pilot64 independent 8X6B/9E6Y HADDOCK3 package."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_PILOT_MANIFEST = EXP_DIR / "data_splits/pvrig_v3_p2/dual_docking_pilot64_manifest.csv"
DEFAULT_CALIBRATION_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_v1_manifest.csv"
DEFAULT_TEACHER500_MANIFEST = (
    EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"
)
DEFAULT_TEACHER500_SELECTED_ROOT = (
    EXP_DIR / "runs/pvrig_teacher_formal_v1/teacher500_node1_selected"
)
DEFAULT_8X6B_RECEPTOR = (
    WORKSPACE_ROOT / "docking/candidates/v2_5_pose_batch/inputs/pvrig_8x6b_chainB.pdb"
)
DEFAULT_9E6Y_STRUCTURE = DATA_ROOT / "structures/9E6Y.pdb"
DEFAULT_HOTSPOT_MANIFEST = DATA_ROOT / "structures/PVRIG_hotspot_set_v1.csv"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_package_v2"

REMOTE_ROOT = "/data/qlyu/projects/pvrig_v3_p2_dual_docking_pilot64_v2_20260714"
PROTOCOL_ID = "DG_A_PILOT64_V1_1"
HADDOCK3_VERSION_CONTRACT = "2025.11.0"
EXPECTED_PILOTS = 64
EXPECTED_REPLICATE_PILOTS = 16
EXPECTED_RUNS = 160
EXPECTED_HOTSPOTS = 23
EXPECTED_SELECTED_POSES = 8
EXPECTED_CLUSTERS = 2
NCORES = 4
TOPOAA_INISEED = 917
RIGIDBODY_SAMPLING = 40
RIGIDBODY_TOLERANCE = 5
FLEXREF_TOLERANCE = 20
EMREF_TOLERANCE = 20
STAGE_OUTPUT_REQUIREMENTS = {
    "topoaa": {"operator": "eq", "value": 2},
    "rigidbody": {"operator": "ge", "value": 38},
    "seletop": {"operator": "eq", "value": 10},
    "flexref": {"operator": "ge", "value": 8},
    "emref": {"operator": "ge", "value": 8},
    "final": {"operator": "ge", "value": 8},
}
SEED_BY_PROTOCOL = {
    ("8X6B", "main"): 917,
    ("8X6B", "replicate"): 10917,
    ("9E6Y", "main"): 20917,
    ("9E6Y", "replicate"): 30917,
}
RECEPTOR_SPECS = {
    "8X6B": {"hotspot_column": "pdb_8x6b_ref", "source_chain": "B"},
    "9E6Y": {"hotspot_column": "pdb_9e6y_ref", "source_chain": "A"},
}
CLAIM_BOUNDARY = (
    "independent_dual_conformer_computational_docking_gold_not_experimental_binding_or_blocking_truth"
)

AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}

RUN_FIELDS = [
    "schema_version", "protocol_id", "run_id", "pilot_rank", "pilot_id", "source_cohort",
    "source_candidate_id", "receptor_id", "seed_role", "iniseed",
    "topoaa_iniseed", "rigidbody_iniseed", "rigidbody_seed_start",
    "rigidbody_seed_end", "replicate_seed_required", "config_relpath",
    "config_sha256", "run_workspace_relpath", "run_dir_relpath",
    "completion_relpath", "log_relpath", "monomer_relpath", "monomer_sha256",
    "receptor_relpath", "receptor_sha256", "restraint_relpath",
    "restraint_sha256", "hotspot_relpath", "hotspot_sha256", "cdr1_range",
    "cdr2_range", "cdr3_range", "expected_min_poses", "expected_min_clusters",
    "ncores", "rigidbody_tolerance", "rigidbody_sampling", "seletop_select",
    "flexref_tolerance", "emref_tolerance", "clustfcc_min_population",
    "seletopclusts_top_models", "per_candidate_failure_tolerance_override",
    "tolerance_relaxed",
    "haddock3_version_contract", "claim_boundary",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[dict[str, str]], fields: Sequence[str] | None = None) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(fields or rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def require_file(path: Path, label: str) -> Path:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Missing or empty {label}: {path}")
    return path


def require_sha256(value: str, payload: str, label: str) -> None:
    actual = hashlib.sha256(payload.encode("ascii")).hexdigest()
    if actual != value:
        raise ValueError(f"{label} SHA256 mismatch: expected {value}, found {actual}")


def bool_text(value: str) -> str:
    lowered = value.strip().lower()
    if lowered not in {"true", "false"}:
        raise ValueError(f"Expected true/false, found {value!r}")
    return lowered


def pdb_residues(path: Path, chain: str) -> list[tuple[tuple[int, str], str]]:
    residues: list[tuple[tuple[int, str], str]] = []
    seen: dict[tuple[int, str], str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27 or line[21] != chain:
            continue
        key = (int(line[22:26]), line[26])
        resname = line[17:20].strip()
        if key in seen:
            if seen[key] != resname:
                raise ValueError(f"Conflicting residue names in {path}: {key}")
            continue
        seen[key] = resname
        residues.append((key, resname))
    if not residues:
        raise ValueError(f"No ATOM residues for chain {chain} in {path}")
    return residues


def pdb_sequence(path: Path, chain: str) -> str:
    try:
        return "".join(AA3_TO_1[name] for _, name in pdb_residues(path, chain))
    except KeyError as error:
        raise ValueError(f"Unsupported PDB residue {error.args[0]} in {path}") from error


def verify_monomer(path: Path, sequence: str) -> str:
    require_file(path, "frozen monomer")
    residues = pdb_residues(path, "A")
    identifiers = [key for key, _ in residues]
    expected = [(index, " ") for index in range(1, len(sequence) + 1)]
    if identifiers != expected:
        raise ValueError(f"Monomer is not consecutively sequence-numbered 1..N: {path}")
    observed = pdb_sequence(path, "A")
    if observed != sequence:
        raise ValueError(f"Frozen monomer sequence mismatch: {path}")
    return sha256_file(path)


def consecutive_groups(values: Iterable[int]) -> list[tuple[int, int]]:
    numbers = list(values)
    if not numbers or numbers != sorted(set(numbers)):
        raise ValueError("CDR residue list must be non-empty, sorted, and unique")
    groups: list[list[int]] = []
    for number in numbers:
        if not groups or number != groups[-1][-1] + 1:
            groups.append([number])
        else:
            groups[-1].append(number)
    return [(group[0], group[-1]) for group in groups]


def calibration_cdr_ranges(workdir: Path, candidate_id: str, sequence: str) -> tuple[dict[str, tuple[int, int]], Path]:
    source = require_file(
        workdir / "haddock3/data" / f"{candidate_id}_cdr_residues_seq_numbering.txt",
        "calibration CDR residue list",
    )
    try:
        values = [int(value) for value in source.read_text(encoding="utf-8").split()]
    except ValueError as error:
        raise ValueError(f"Non-integer CDR residue in {source}") from error
    groups = consecutive_groups(values)
    if len(groups) != 3:
        raise ValueError(f"Expected exactly three consecutive CDR groups in {source}, found {groups}")
    if groups[-1][1] > len(sequence):
        raise ValueError(f"CDR range exceeds sequence length in {source}")
    return dict(zip(("cdr1", "cdr2", "cdr3"), groups, strict=True)), source


def verified_teacher_range(row: dict[str, str], name: str) -> tuple[int, int]:
    sequence = row["vhh_sequence"]
    start, end = int(row[f"{name}_start_1based"]), int(row[f"{name}_end_1based"])
    cdr = row[f"{name}_after"]
    if not (1 <= start <= end <= len(sequence)) or sequence[start - 1:end] != cdr:
        raise ValueError(f"Frozen Teacher500 {name} range does not match {row['candidate_id']}")
    return start, end


def derive_hotspots(path: Path, receptor_id: str) -> list[dict[str, Any]]:
    spec = RECEPTOR_SPECS[receptor_id]
    pattern = re.compile(r"^([A-Za-z0-9]):(-?\d+)([A-Z])$")
    hotspots: list[dict[str, Any]] = []
    for row in read_csv(path):
        if row["hotspot_class"] not in {"core_hotspot", "secondary_hotspot"}:
            continue
        match = pattern.fullmatch(row[spec["hotspot_column"]])
        if not match:
            raise ValueError(f"Malformed {receptor_id} hotspot reference: {row[spec['hotspot_column']]}")
        chain, resseq, aa = match.groups()
        if chain != spec["source_chain"]:
            raise ValueError(f"Unexpected source chain for {receptor_id}: {chain}")
        hotspots.append(
            {
                "hotspot_id": row["hotspot_id"],
                "hotspot_class": row["hotspot_class"],
                "resseq": int(resseq),
                "aa": aa,
            }
        )
    if len(hotspots) != EXPECTED_HOTSPOTS or len({row["resseq"] for row in hotspots}) != EXPECTED_HOTSPOTS:
        raise ValueError(f"Expected {EXPECTED_HOTSPOTS} unique {receptor_id} hotspots")
    return hotspots


def extract_relabelled_chain(source: Path, source_chain: str, target_chain: str, destination: Path) -> None:
    output: list[str] = []
    for line in source.read_text(encoding="ascii").splitlines():
        if line.startswith("ATOM  ") and len(line) > 21 and line[21] == source_chain:
            output.append(line[:21] + target_chain + line[22:])
    if not output:
        raise ValueError(f"No ATOM records for chain {source_chain} in {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(output) + "\nTER\nEND\n", encoding="ascii")


def verify_hotspot_residues(receptor_path: Path, hotspots: Sequence[dict[str, Any]]) -> None:
    residues = {key[0]: AA3_TO_1[name] for key, name in pdb_residues(receptor_path, "B") if key[1] == " "}
    for hotspot in hotspots:
        observed = residues.get(hotspot["resseq"])
        if observed != hotspot["aa"]:
            raise ValueError(
                f"Hotspot {hotspot['resseq']}{hotspot['aa']} does not match receptor {receptor_path}: {observed}"
            )


def format_range(value: tuple[int, int]) -> str:
    return f"{value[0]}-{value[1]}"


def range_residues(ranges: dict[str, tuple[int, int]]) -> list[int]:
    residues: list[int] = []
    for name in ("cdr1", "cdr2", "cdr3"):
        start, end = ranges[name]
        residues.extend(range(start, end + 1))
    return residues


def restraint_text(cdr_residues: Sequence[int], hotspots: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    for residue in cdr_residues:
        lines.append(f"assign (resi {residue} and segid A)")
        lines.append("(")
        for index, hotspot in enumerate(hotspots):
            prefix = "       " if index == 0 else "        or\n       "
            lines.append(f"{prefix}(resi {hotspot['resseq']} and segid B)")
        lines.append(") 2.0 2.0 0.0\n")
    return "\n".join(lines) + "\n"


def config_text(
    run_id: str,
    monomer_relpath: str,
    receptor_relpath: str,
    restraint_relpath: str,
    rigidbody_iniseed: int,
) -> str:
    return f'''# Pilot64 {run_id}: frozen independent dual-conformer docking.
# Protocol: {PROTOCOL_ID}
# Evidence boundary: {CLAIM_BOUNDARY}
# HADDOCK3 version contract: {HADDOCK3_VERSION_CONTRACT}
run_dir = "run_{run_id}"
mode = "local"
ncores = {NCORES}

molecules = [
    "../../{monomer_relpath}",
    "../../{receptor_relpath}",
]

[topoaa]
iniseed = {TOPOAA_INISEED}

[rigidbody]
ambig_fname = "../../{restraint_relpath}"
iniseed = {rigidbody_iniseed}
tolerance = {RIGIDBODY_TOLERANCE}
sampling = {RIGIDBODY_SAMPLING}

[seletop]
select = 10

[flexref]
tolerance = {FLEXREF_TOLERANCE}
ambig_fname = "../../{restraint_relpath}"

[emref]
tolerance = {EMREF_TOLERANCE}
ambig_fname = "../../{restraint_relpath}"

[clustfcc]
min_population = 1

[seletopclusts]
top_models = 4
'''


def controller_source() -> str:
    return f'''#!/usr/bin/env python3
"""Run frozen Pilot64 HADDOCK jobs with resumability and docking-output gates."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_VERSION = "{HADDOCK3_VERSION_CONTRACT}"
PROTOCOL_ID = "{PROTOCOL_ID}"
MAX_CONCURRENT_JOBS = 5
POSE_PATTERN = re.compile(r"^cluster_(\\d+)_model_(\\d+)\\.pdb(?:\\.gz)?$")
STAGE_IO_RELPATHS = {{
    "topoaa": "0_topoaa/io.json",
    "rigidbody": "1_rigidbody/io.json",
    "seletop": "2_seletop/io.json",
    "flexref": "3_flexref/io.json",
    "emref": "4_emref/io.json",
    "final": "6_seletopclusts/io.json",
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


def output_counts(run_dir: Path) -> tuple[int, int]:
    selected = run_dir / "6_seletopclusts"
    pairs: set[tuple[int, int]] = set()
    if selected.is_dir():
        for path in selected.iterdir():
            match = POSE_PATTERN.fullmatch(path.name)
            if match and path.is_file() and path.stat().st_size:
                pairs.add((int(match.group(1)), int(match.group(2))))
    return len(pairs), len({{cluster for cluster, _ in pairs}})


def stage_output_counts(run_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {{}}
    for stage, relative in STAGE_IO_RELPATHS.items():
        path = run_dir / relative
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            outputs = payload.get("output")
            if not isinstance(outputs, list):
                raise ValueError("io.json output is not a list")
            counts[stage] = len(outputs)
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


def reusable_exit_zero(completion: Path) -> bool:
    try:
        payload = json.loads(completion.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return (
        payload.get("exit_code") == 0
        and payload.get("protocol_id") == PROTOCOL_ID
        and payload.get("per_candidate_failure_tolerance_override") is False
    )


def archive_partial(root: Path, row: dict[str, str], run_dir: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = root / "partial_runs" / row["run_id"] / f"{{run_dir.name}}.{{stamp}}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(run_dir), str(destination))
    return str(destination.relative_to(root))


def verify_inputs(root: Path, row: dict[str, str]) -> None:
    for path_field, hash_field in (
        ("config_relpath", "config_sha256"),
        ("monomer_relpath", "monomer_sha256"),
        ("receptor_relpath", "receptor_sha256"),
        ("restraint_relpath", "restraint_sha256"),
        ("hotspot_relpath", "hotspot_sha256"),
    ):
        path = root / row[path_field]
        if not path.is_file() or sha256_file(path) != row[hash_field]:
            raise RuntimeError(f"Hash closure failed for {{row['run_id']}}: {{path_field}}")


def completion_payload(
    row: dict[str, str],
    status: str,
    poses: int,
    clusters: int,
    stage_counts: dict[str, int],
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {{
        "schema_version": "phase2_v3_p2_pilot64_run_completion_v1_1",
        "protocol_id": PROTOCOL_ID,
        "run_id": row["run_id"],
        "pilot_id": row["pilot_id"],
        "source_candidate_id": row["source_candidate_id"],
        "receptor_id": row["receptor_id"],
        "seed_role": row["seed_role"],
        "iniseed": int(row["iniseed"]),
        "status": status,
        "pose_count": poses,
        "cluster_count": clusters,
        "expected_min_poses": int(row["expected_min_poses"]),
        "expected_min_clusters": int(row["expected_min_clusters"]),
        "stage_output_counts": stage_counts,
        "stage_output_requirements": STAGE_OUTPUT_REQUIREMENTS,
        "run_dir_relpath": row["run_dir_relpath"],
        "config_sha256": row["config_sha256"],
        "monomer_sha256": row["monomer_sha256"],
        "receptor_sha256": row["receptor_sha256"],
        "per_candidate_failure_tolerance_override": False,
        "tolerance_relaxed": False,
        "haddock3_version_contract": EXPECTED_VERSION,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }}
    payload.update(extra)
    return payload


def wait_for_load(max_load1: float, poll_seconds: float) -> None:
    while True:
        load1 = float(Path("/proc/loadavg").read_text(encoding="ascii").split()[0])
        if load1 <= max_load1:
            return
        time.sleep(poll_seconds)


def run_one(
    root: Path,
    haddock_bin: Path,
    row: dict[str, str],
    max_load1: float,
    load_poll_seconds: float,
) -> dict[str, object]:
    completion = root / row["completion_relpath"]
    run_dir = root / row["run_dir_relpath"]
    try:
        verify_inputs(root, row)
        poses, clusters = output_counts(run_dir)
        stage_counts = stage_output_counts(run_dir)
        if (
            reusable_exit_zero(completion)
            and stage_counts_pass(stage_counts)
            and poses >= int(row["expected_min_poses"])
            and clusters >= int(row["expected_min_clusters"])
        ):
            payload = completion_payload(
                row, "PASS_DOCKING_OUTPUT_COMPLETE", poses, clusters, stage_counts,
                exit_code=0, reused=True,
                dg_a_status="PENDING_GEOMETRY_AND_CONTACT_POSTPROCESS",
            )
            atomic_json(completion, payload)
            return payload

        archived = ""
        if run_dir.exists():
            archived = archive_partial(root, row, run_dir)

        workspace = root / row["run_workspace_relpath"]
        log_path = root / row["log_relpath"]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        wait_for_load(max_load1, load_poll_seconds)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\\nRUN_START {{datetime.now(timezone.utc).isoformat()}} run_id={{row['run_id']}}\\n")
            result = subprocess.run(
                [str(haddock_bin), Path(row["config_relpath"]).name],
                cwd=workspace,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        poses, clusters = output_counts(run_dir)
        stage_counts = stage_output_counts(run_dir)
        passed = (
            result.returncode == 0
            and stage_counts_pass(stage_counts)
            and poses >= int(row["expected_min_poses"])
            and clusters >= int(row["expected_min_clusters"])
        )
        status = "PASS_DOCKING_OUTPUT_COMPLETE" if passed else "FAIL_DOCKING_OUTPUT_INCOMPLETE"
        payload = completion_payload(
            row, status, poses, clusters, stage_counts, exit_code=result.returncode,
            reused=False, archived_partial_relpath=archived,
            dg_a_status="PENDING_GEOMETRY_AND_CONTACT_POSTPROCESS",
        )
        atomic_json(completion, payload)
        return payload
    except Exception as error:
        poses, clusters = output_counts(run_dir)
        stage_counts = stage_output_counts(run_dir)
        payload = completion_payload(
            row, "FAIL_CONTROLLER_EXCEPTION", poses, clusters, stage_counts, exit_code=None,
            dg_a_status="FAIL_CONTROLLER_EXCEPTION", error=str(error),
        )
        atomic_json(completion, payload)
        return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--haddock-bin", type=Path,
        default=Path(os.environ.get("HADDOCK3_BIN", "/data/qlyu/anaconda3/envs/haddock3/bin/haddock3")),
    )
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument(
        "--max-load1", type=float,
        default=float(os.environ.get("PVRIG_DOCKING_MAX_LOAD1", "55")),
    )
    parser.add_argument("--load-poll-seconds", type=float, default=60.0)
    parser.add_argument("--pilot-id", action="append")
    parser.add_argument("--receptor", choices=("8X6B", "9E6Y"), action="append")
    parser.add_argument("--seed-role", choices=("main", "replicate"), action="append")
    parser.add_argument("--list-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.max_workers <= MAX_CONCURRENT_JOBS:
        raise SystemExit(f"--max-workers must be between 1 and {{MAX_CONCURRENT_JOBS}}")
    if args.max_load1 <= 0 or args.load_poll_seconds <= 0:
        raise SystemExit("--max-load1 and --load-poll-seconds must be positive")
    manifest = args.root / "manifests/run_manifest.csv"
    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows = [
        row for row in rows
        if (not args.pilot_id or row["pilot_id"] in args.pilot_id)
        and (not args.receptor or row["receptor_id"] in args.receptor)
        and (not args.seed_role or row["seed_role"] in args.seed_role)
    ]
    if not rows:
        raise SystemExit("No runs match the requested filters")
    if args.list_only:
        print(json.dumps([{{key: row[key] for key in ("run_id", "pilot_id", "receptor_id", "seed_role", "iniseed")}} for row in rows], indent=2))
        return

    version = subprocess.run(
        [str(args.haddock_bin), "--version"], capture_output=True, text=True, check=False,
    )
    version_text = (version.stdout + "\\n" + version.stderr).strip()
    if version.returncode != 0 or EXPECTED_VERSION not in version_text:
        raise SystemExit(f"HADDOCK3 version contract failed: expected {{EXPECTED_VERSION}}, got {{version_text!r}}")

    failures = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {{
            executor.submit(
                run_one, args.root, args.haddock_bin, row,
                args.max_load1, args.load_poll_seconds,
            ): row
            for row in rows
        }}
        for future in as_completed(futures):
            payload = future.result()
            print(json.dumps(payload, sort_keys=True), flush=True)
            if payload["status"] != "PASS_DOCKING_OUTPUT_COMPLETE":
                failures += 1
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
'''


def _index_unique(rows: Sequence[dict[str, str]], key: str, label: str) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row[key]
        if value in index:
            raise ValueError(f"Duplicate {label} {key}: {value}")
        index[value] = row
    return index


def validate_pilot_rows(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    if len(rows) != EXPECTED_PILOTS:
        raise ValueError(f"Expected {EXPECTED_PILOTS} Pilot64 rows, found {len(rows)}")
    ordered = sorted(rows, key=lambda row: int(row["pilot_rank"]))
    if [int(row["pilot_rank"]) for row in ordered] != list(range(1, EXPECTED_PILOTS + 1)):
        raise ValueError("Pilot ranks must be exactly 1..64")
    if len({row["pilot_id"] for row in ordered}) != EXPECTED_PILOTS:
        raise ValueError("Pilot IDs are not unique")
    if len({row["source_candidate_id"] for row in ordered}) != EXPECTED_PILOTS:
        raise ValueError("Pilot source candidate IDs are not unique")
    replicate_count = 0
    for row in ordered:
        require_sha256(row["sequence_sha256"], row["sequence"], row["pilot_id"])
        replicate_count += bool_text(row["replicate_seed_required"]) == "true"
        if row["required_docking_protocol"] != "DG_A_INDEPENDENT_8X6B_AND_9E6Y":
            raise ValueError(f"Unexpected protocol for {row['pilot_id']}")
    if replicate_count != EXPECTED_REPLICATE_PILOTS:
        raise ValueError(f"Expected {EXPECTED_REPLICATE_PILOTS} replicate pilots, found {replicate_count}")
    return ordered


def resolve_monomers(
    pilot_rows: Sequence[dict[str, str]],
    calibration_manifest: Path,
    teacher500_manifest: Path,
    teacher500_selected_root: Path,
    outdir: Path,
) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    calibration = _index_unique(read_csv(calibration_manifest), "candidate_id", "calibration")
    teacher500 = _index_unique(read_csv(teacher500_manifest), "candidate_id", "Teacher500")
    manifest_rows: list[dict[str, str]] = []
    resolved: dict[str, dict[str, Any]] = {}
    for pilot_row in pilot_rows:
        pilot_id = pilot_row["pilot_id"]
        candidate_id = pilot_row["source_candidate_id"]
        sequence = pilot_row["sequence"]
        if pilot_row["source_cohort"] == "teacher500_stratified":
            source_row = teacher500.get(candidate_id)
            if source_row is None:
                raise KeyError(f"Teacher500 candidate missing: {candidate_id}")
            if source_row["vhh_sequence"] != sequence or source_row["sequence_sha256"] != pilot_row["sequence_sha256"]:
                raise ValueError(f"Teacher500 manifest mismatch for {candidate_id}")
            matches = list(
                teacher500_selected_root.glob(
                    f"shard_*/monomer/{candidate_id}/{candidate_id}_nanobodybuilder2_chainA.pdb"
                )
            )
            if len(matches) != 1:
                raise ValueError(f"Expected one selected Teacher500 monomer for {candidate_id}, found {len(matches)}")
            source_monomer = matches[0]
            ranges = {name: verified_teacher_range(source_row, name) for name in ("cdr1", "cdr2", "cdr3")}
            cdr_source = teacher500_manifest
            cdr_source_type = "frozen_teacher500_manifest_coordinates"
        elif pilot_row["source_cohort"] in {"known_positive", "matched_control"}:
            source_row = calibration.get(candidate_id)
            if source_row is None:
                raise KeyError(f"Calibration candidate missing: {candidate_id}")
            if source_row["sequence"] != sequence or source_row["sequence_sha256"] != pilot_row["sequence_sha256"]:
                raise ValueError(f"Calibration manifest mismatch for {candidate_id}")
            workdir = Path(source_row["workdir"])
            source_monomer = workdir / "haddock3/data" / f"{candidate_id}_vhh_chainA.pdb"
            ranges, cdr_source = calibration_cdr_ranges(workdir, candidate_id, sequence)
            cdr_source_type = "existing_three_consecutive_cdr_residue_groups"
        else:
            raise ValueError(f"Unknown source cohort: {pilot_row['source_cohort']}")

        source_sha = verify_monomer(source_monomer, sequence)
        packaged_relpath = f"monomers/{pilot_id}_vhh_chainA.pdb"
        packaged_path = outdir / packaged_relpath
        packaged_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_monomer, packaged_path)
        packaged_sha = sha256_file(packaged_path)
        if packaged_sha != source_sha:
            raise ValueError(f"Monomer copy changed bytes for {pilot_id}")
        range_strings = {name: format_range(ranges[name]) for name in ranges}
        manifest_rows.append(
            {
                "schema_version": "phase2_v3_p2_pilot64_monomer_manifest_v1",
                "pilot_rank": pilot_row["pilot_rank"],
                "pilot_id": pilot_id,
                "source_cohort": pilot_row["source_cohort"],
                "source_candidate_id": candidate_id,
                "sequence": sequence,
                "sequence_sha256": pilot_row["sequence_sha256"],
                "source_monomer_path": str(source_monomer),
                "source_monomer_sha256": source_sha,
                "monomer_relpath": packaged_relpath,
                "monomer_sha256": packaged_sha,
                "pdb_sequence_validated": "true",
                "cdr_source_type": cdr_source_type,
                "cdr_source_path": str(cdr_source),
                "cdr1_range": range_strings["cdr1"],
                "cdr2_range": range_strings["cdr2"],
                "cdr3_range": range_strings["cdr3"],
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
        resolved[pilot_id] = {
            "relpath": packaged_relpath,
            "sha256": packaged_sha,
            "ranges": ranges,
            "range_strings": range_strings,
        }
    if len(manifest_rows) != EXPECTED_PILOTS:
        raise AssertionError("Monomer closure is not 64/64")
    return manifest_rows, resolved


def build_receptors_and_protocols(
    outdir: Path,
    receptor_8x6b: Path,
    structure_9e6y: Path,
    hotspot_manifest: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    receptors_dir = outdir / "receptors"
    receptors_dir.mkdir(parents=True, exist_ok=True)
    receptor_paths = {
        "8X6B": receptors_dir / "pvrig_8x6b_chainB.pdb",
        "9E6Y": receptors_dir / "pvrig_9e6y_chainB.pdb",
    }
    shutil.copyfile(require_file(receptor_8x6b, "frozen 8X6B receptor"), receptor_paths["8X6B"])
    extract_relabelled_chain(
        require_file(structure_9e6y, "9E6Y structure"), "A", "B", receptor_paths["9E6Y"]
    )
    sources = {"8X6B": receptor_8x6b, "9E6Y": structure_9e6y}
    receptor_info: dict[str, dict[str, Any]] = {}
    for receptor_id in ("8X6B", "9E6Y"):
        hotspots = derive_hotspots(hotspot_manifest, receptor_id)
        verify_hotspot_residues(receptor_paths[receptor_id], hotspots)
        hotspot_relpath = f"hotspots/hotspot_residues_{receptor_id.lower()}.txt"
        hotspot_path = outdir / hotspot_relpath
        hotspot_path.parent.mkdir(parents=True, exist_ok=True)
        hotspot_path.write_text("\n".join(str(row["resseq"]) for row in hotspots) + "\n", encoding="ascii")
        receptor_info[receptor_id] = {
            "relpath": str(receptor_paths[receptor_id].relative_to(outdir)),
            "sha256": sha256_file(receptor_paths[receptor_id]),
            "source": sources[receptor_id],
            "source_sha256": sha256_file(sources[receptor_id]),
            "hotspots": hotspots,
            "hotspot_relpath": hotspot_relpath,
            "hotspot_sha256": sha256_file(hotspot_path),
        }

    protocol_rows: list[dict[str, str]] = []
    for receptor_id in ("8X6B", "9E6Y"):
        info = receptor_info[receptor_id]
        for seed_role in ("main", "replicate"):
            seed = SEED_BY_PROTOCOL[(receptor_id, seed_role)]
            protocol_rows.append(
                {
                    "schema_version": "phase2_v3_p2_pilot64_protocol_manifest_v1_1",
                    "protocol_id": PROTOCOL_ID,
                    "receptor_id": receptor_id,
                    "seed_role": seed_role,
                    "topoaa_iniseed": str(TOPOAA_INISEED),
                    "rigidbody_iniseed": str(seed),
                    "rigidbody_seed_start": str(seed + 1),
                    "rigidbody_seed_end": str(seed + RIGIDBODY_SAMPLING),
                    "flexref_iniseed": "INHERIT_RIGIDBODY_POSE_SEEDS",
                    "emref_iniseed": "INHERIT_RIGIDBODY_POSE_SEEDS",
                    "rigidbody_sampling": str(RIGIDBODY_SAMPLING),
                    "rigidbody_tolerance": str(RIGIDBODY_TOLERANCE),
                    "seletop_select": "10",
                    "flexref_tolerance": str(FLEXREF_TOLERANCE),
                    "emref_tolerance": str(EMREF_TOLERANCE),
                    "clustfcc_min_population": "1",
                    "seletopclusts_top_models": "4",
                    "ncores": str(NCORES),
                    "per_candidate_failure_tolerance_override": "false",
                    "tolerance_relaxed": "false",
                    "haddock3_version_contract": HADDOCK3_VERSION_CONTRACT,
                    "receptor_source_path": str(info["source"]),
                    "receptor_source_sha256": info["source_sha256"],
                    "receptor_relpath": info["relpath"],
                    "receptor_sha256": info["sha256"],
                    "hotspot_source_path": str(hotspot_manifest),
                    "hotspot_source_sha256": sha256_file(hotspot_manifest),
                    "hotspot_relpath": info["hotspot_relpath"],
                    "hotspot_sha256": info["hotspot_sha256"],
                    "hotspot_count": str(len(info["hotspots"])),
                    "hotspot_residues": ";".join(str(row["resseq"]) for row in info["hotspots"]),
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )
    seed_ranges = [
        set(range(int(row["rigidbody_seed_start"]), int(row["rigidbody_seed_end"]) + 1))
        for row in protocol_rows
    ]
    if any(left & right for index, left in enumerate(seed_ranges) for right in seed_ranges[index + 1:]):
        raise AssertionError("Rigid-body seed ranges overlap")
    return receptor_info, protocol_rows


def build_run_rows(
    outdir: Path,
    pilot_rows: Sequence[dict[str, str]],
    monomers: dict[str, dict[str, Any]],
    receptors: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for pilot in pilot_rows:
        pilot_id = pilot["pilot_id"]
        monomer = monomers[pilot_id]
        replicate_required = bool_text(pilot["replicate_seed_required"])
        for receptor_id in ("8X6B", "9E6Y"):
            receptor = receptors[receptor_id]
            restraint_relpath = f"restraints/{pilot_id}__{receptor_id}.tbl"
            restraint_path = outdir / restraint_relpath
            restraint_path.parent.mkdir(parents=True, exist_ok=True)
            restraint_path.write_text(
                restraint_text(range_residues(monomer["ranges"]), receptor["hotspots"]),
                encoding="ascii",
            )
            restraint_sha = sha256_file(restraint_path)
            roles = ["main"] + (["replicate"] if replicate_required == "true" else [])
            for seed_role in roles:
                run_id = f"{pilot_id}__{receptor_id}__{seed_role}"
                workspace_relpath = f"runs/{run_id}"
                workspace = outdir / workspace_relpath
                workspace.mkdir(parents=True, exist_ok=True)
                config_relpath = f"{workspace_relpath}/{run_id}.cfg"
                config_path = outdir / config_relpath
                seed = SEED_BY_PROTOCOL[(receptor_id, seed_role)]
                config_path.write_text(
                    config_text(
                        run_id, monomer["relpath"], receptor["relpath"],
                        restraint_relpath, seed,
                    ),
                    encoding="utf-8",
                )
                rows.append(
                    {
                        "schema_version": "phase2_v3_p2_pilot64_run_manifest_v1_1",
                        "protocol_id": PROTOCOL_ID,
                        "run_id": run_id,
                        "pilot_rank": pilot["pilot_rank"],
                        "pilot_id": pilot_id,
                        "source_cohort": pilot["source_cohort"],
                        "source_candidate_id": pilot["source_candidate_id"],
                        "receptor_id": receptor_id,
                        "seed_role": seed_role,
                        "iniseed": str(seed),
                        "topoaa_iniseed": str(TOPOAA_INISEED),
                        "rigidbody_iniseed": str(seed),
                        "rigidbody_seed_start": str(seed + 1),
                        "rigidbody_seed_end": str(seed + RIGIDBODY_SAMPLING),
                        "replicate_seed_required": replicate_required,
                        "config_relpath": config_relpath,
                        "config_sha256": sha256_file(config_path),
                        "run_workspace_relpath": workspace_relpath,
                        "run_dir_relpath": f"{workspace_relpath}/run_{run_id}",
                        "completion_relpath": f"{workspace_relpath}/{run_id}.complete.json",
                        "log_relpath": f"{workspace_relpath}/{run_id}.log",
                        "monomer_relpath": monomer["relpath"],
                        "monomer_sha256": monomer["sha256"],
                        "receptor_relpath": receptor["relpath"],
                        "receptor_sha256": receptor["sha256"],
                        "restraint_relpath": restraint_relpath,
                        "restraint_sha256": restraint_sha,
                        "hotspot_relpath": receptor["hotspot_relpath"],
                        "hotspot_sha256": receptor["hotspot_sha256"],
                        "cdr1_range": monomer["range_strings"]["cdr1"],
                        "cdr2_range": monomer["range_strings"]["cdr2"],
                        "cdr3_range": monomer["range_strings"]["cdr3"],
                        "expected_min_poses": str(EXPECTED_SELECTED_POSES),
                        "expected_min_clusters": str(EXPECTED_CLUSTERS),
                        "ncores": str(NCORES),
                        "rigidbody_tolerance": str(RIGIDBODY_TOLERANCE),
                        "rigidbody_sampling": str(RIGIDBODY_SAMPLING),
                        "seletop_select": "10",
                        "flexref_tolerance": str(FLEXREF_TOLERANCE),
                        "emref_tolerance": str(EMREF_TOLERANCE),
                        "clustfcc_min_population": "1",
                        "seletopclusts_top_models": "4",
                        "per_candidate_failure_tolerance_override": "false",
                        "tolerance_relaxed": "false",
                        "haddock3_version_contract": HADDOCK3_VERSION_CONTRACT,
                        "claim_boundary": CLAIM_BOUNDARY,
                    }
                )
    if len(rows) != EXPECTED_RUNS or len({row["run_id"] for row in rows}) != EXPECTED_RUNS:
        raise AssertionError(f"Expected {EXPECTED_RUNS} unique runs, found {len(rows)}")
    return rows


def write_content_hashes(outdir: Path) -> Path:
    destination = outdir / "manifests/package_content_sha256.tsv"
    files = sorted(
        path for path in outdir.rglob("*")
        if path.is_file() and path not in {destination, outdir / "package_audit.json"}
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        handle.write("sha256\tpath\n")
        for path in files:
            handle.write(f"{sha256_file(path)}\t{path.relative_to(outdir).as_posix()}\n")
    return destination


def build_package(
    pilot_manifest: Path = DEFAULT_PILOT_MANIFEST,
    calibration_manifest: Path = DEFAULT_CALIBRATION_MANIFEST,
    teacher500_manifest: Path = DEFAULT_TEACHER500_MANIFEST,
    teacher500_selected_root: Path = DEFAULT_TEACHER500_SELECTED_ROOT,
    receptor_8x6b: Path = DEFAULT_8X6B_RECEPTOR,
    structure_9e6y: Path = DEFAULT_9E6Y_STRUCTURE,
    hotspot_manifest: Path = DEFAULT_HOTSPOT_MANIFEST,
    outdir: Path = DEFAULT_OUTDIR,
    force: bool = False,
) -> dict[str, Any]:
    for path, label in (
        (pilot_manifest, "Pilot64 manifest"),
        (calibration_manifest, "calibration manifest"),
        (teacher500_manifest, "Teacher500 manifest"),
        (hotspot_manifest, "hotspot manifest"),
    ):
        require_file(path, label)
    if outdir.exists():
        if not force:
            raise FileExistsError(f"Output already exists: {outdir}")
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)

    pilot_rows = validate_pilot_rows(read_csv(pilot_manifest))
    monomer_rows, monomers = resolve_monomers(
        pilot_rows, calibration_manifest, teacher500_manifest, teacher500_selected_root, outdir
    )
    receptors, protocol_rows = build_receptors_and_protocols(
        outdir, receptor_8x6b, structure_9e6y, hotspot_manifest
    )
    run_rows = build_run_rows(outdir, pilot_rows, monomers, receptors)

    manifests_dir = outdir / "manifests"
    run_manifest = manifests_dir / "run_manifest.csv"
    monomer_manifest = manifests_dir / "monomer_manifest.csv"
    protocol_manifest = manifests_dir / "protocol_manifest.csv"
    write_csv(run_manifest, run_rows, RUN_FIELDS)
    write_csv(monomer_manifest, monomer_rows)
    write_csv(protocol_manifest, protocol_rows)

    controller = outdir / "scripts/run_dual_docking_pilot64.py"
    controller.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text(controller_source(), encoding="utf-8")
    controller.chmod(0o755)
    compile(controller.read_text(encoding="utf-8"), str(controller), "exec")

    content_hashes = write_content_hashes(outdir)
    run_counts = Counter((row["receptor_id"], row["seed_role"]) for row in run_rows)
    audit: dict[str, Any] = {
        "status": "PASS_PILOT64_DUAL_DOCKING_PACKAGE_READY",
        "schema_version": "phase2_v3_p2_pilot64_package_audit_v1_1",
        "protocol_id": PROTOCOL_ID,
        "remote_root": REMOTE_ROOT,
        "haddock3_version_contract": HADDOCK3_VERSION_CONTRACT,
        "pilot_manifest": str(pilot_manifest),
        "pilot_manifest_sha256": sha256_file(pilot_manifest),
        "candidate_count": len(pilot_rows),
        "monomer_count": len(monomer_rows),
        "monomer_sequence_validation_count": sum(row["pdb_sequence_validated"] == "true" for row in monomer_rows),
        "run_count": len(run_rows),
        "main_run_count": sum(row["seed_role"] == "main" for row in run_rows),
        "replicate_run_count": sum(row["seed_role"] == "replicate" for row in run_rows),
        "run_counts_by_receptor_and_seed_role": {
            f"{receptor_id}:{seed_role}": count
            for (receptor_id, seed_role), count in sorted(run_counts.items())
        },
        "replicate_candidate_count": sum(row["replicate_seed_required"] == "true" for row in pilot_rows),
        "hotspot_counts": {receptor_id: len(info["hotspots"]) for receptor_id, info in receptors.items()},
        "seed_contract": {
            f"{receptor_id}:{seed_role}": {
                "topoaa_iniseed": TOPOAA_INISEED,
                "rigidbody_seed_start": seed + 1,
                "rigidbody_seed_end": seed + RIGIDBODY_SAMPLING,
            }
            for (receptor_id, seed_role), seed in SEED_BY_PROTOCOL.items()
        },
        "seed_ranges_non_overlapping": True,
        "flexref_emref_iniseed_policy": "inherit_rigidbody_pose_seeds_no_explicit_iniseed",
        "module_failure_tolerances": {
            "rigidbody": RIGIDBODY_TOLERANCE,
            "flexref": FLEXREF_TOLERANCE,
            "emref": EMREF_TOLERANCE,
        },
        "stage_output_requirements": STAGE_OUTPUT_REQUIREMENTS,
        "per_candidate_failure_tolerance_override": False,
        "tolerance_relaxed": False,
        "max_concurrent_haddock_jobs": 5,
        "expected_min_selected_poses_per_run": EXPECTED_SELECTED_POSES,
        "expected_min_clusters_per_run": EXPECTED_CLUSTERS,
        "run_manifest": str(run_manifest.relative_to(outdir)),
        "run_manifest_sha256": sha256_file(run_manifest),
        "monomer_manifest": str(monomer_manifest.relative_to(outdir)),
        "monomer_manifest_sha256": sha256_file(monomer_manifest),
        "protocol_manifest": str(protocol_manifest.relative_to(outdir)),
        "protocol_manifest_sha256": sha256_file(protocol_manifest),
        "controller": str(controller.relative_to(outdir)),
        "controller_sha256": sha256_file(controller),
        "package_content_hash_manifest": str(content_hashes.relative_to(outdir)),
        "package_content_hash_manifest_sha256": sha256_file(content_hashes),
        "package_content_hash_scope_exclusions": ["package_audit.json", "manifests/package_content_sha256.tsv"],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (outdir / "package_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-manifest", type=Path, default=DEFAULT_PILOT_MANIFEST)
    parser.add_argument("--calibration-manifest", type=Path, default=DEFAULT_CALIBRATION_MANIFEST)
    parser.add_argument("--teacher500-manifest", type=Path, default=DEFAULT_TEACHER500_MANIFEST)
    parser.add_argument("--teacher500-selected-root", type=Path, default=DEFAULT_TEACHER500_SELECTED_ROOT)
    parser.add_argument("--receptor-8x6b", type=Path, default=DEFAULT_8X6B_RECEPTOR)
    parser.add_argument("--structure-9e6y", type=Path, default=DEFAULT_9E6Y_STRUCTURE)
    parser.add_argument("--hotspot-manifest", type=Path, default=DEFAULT_HOTSPOT_MANIFEST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    audit = build_package(
        pilot_manifest=args.pilot_manifest,
        calibration_manifest=args.calibration_manifest,
        teacher500_manifest=args.teacher500_manifest,
        teacher500_selected_root=args.teacher500_selected_root,
        receptor_8x6b=args.receptor_8x6b,
        structure_9e6y=args.structure_9e6y,
        hotspot_manifest=args.hotspot_manifest,
        outdir=args.outdir,
        force=args.force,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
