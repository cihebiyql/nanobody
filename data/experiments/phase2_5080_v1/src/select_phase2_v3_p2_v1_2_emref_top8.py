#!/usr/bin/env python3
"""Select the deterministic V1.2 development-only HADDOCK emref ensemble.

This selector deliberately uses only the ordered records in ``4_emref/io.json``.
It never reads downstream clustering, blocker geometry, or any other score when
choosing poses.  The resulting ensemble is computational development evidence,
not formal validation or experimental binding/blocking truth.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

PROTOCOL_ID = "DG_A_PVRIG_V1_2_DEV"
SOURCE_PROTOCOL = "HADDOCK3_4_EMREF_IO_SCORE_ORDER_V1"
SOURCE_STAGE = "4_emref"
REUSE_ROLE = "development_only"
FORMAL_ELIGIBLE = False
DEFAULT_K = 8
CLAIM_BOUNDARY = (
    "deterministic HADDOCK 4_emref score-selected computational poses for "
    "V1.2 development only; not formal validation and not experimental "
    "binding, affinity, or blocking truth"
)

CANDIDATE_ID_ALIASES = (
    "candidate_id",
    "calibration_name",
    "mutant_name",
    "sample_id",
    "case_id",
    "source_candidate_id",
)
WORKDIR_ALIASES = ("workdir", "case_workdir", "candidate_workdir", "run_workdir")
FAMILY_ALIASES = ("family", "base_family", "parent_family")
ROLE_ALIASES = (
    "validation_role",
    "intended_role",
    "calibration_role",
    "role",
    "control_type",
)

CSV_FIELDS = (
    "schema_version",
    "protocol_id",
    "source_protocol",
    "source_stage",
    "run_id",
    "case_id",
    "candidate_id",
    "family",
    "role",
    "canonical_rank",
    "source_output_index",
    "source_output_file",
    "source_score",
    "source_seed",
    "source_pose_relpath",
    "source_pose_format",
    "source_pose_sha256",
    "source_pose_bytes",
    "compressed_source_sha256",
    "compressed_source_bytes",
    "decompressed_coordinate_sha256",
    "decompressed_coordinate_bytes",
    "vhh_chain_id",
    "vhh_atom_count",
    "vhh_residue_count",
    "vhh_atom_heavy_atom_count",
    "vhh_atom_residue_count",
    "vhh_hetatm_heavy_atom_count",
    "vhh_hetatm_residue_count",
    "vhh_excluded_hydrogen_or_deuterium_count",
    "vhh_chain_inventory_json",
    "pvrig_chain_id",
    "pvrig_atom_count",
    "pvrig_residue_count",
    "pvrig_atom_heavy_atom_count",
    "pvrig_atom_residue_count",
    "pvrig_hetatm_heavy_atom_count",
    "pvrig_hetatm_residue_count",
    "pvrig_excluded_hydrogen_or_deuterium_count",
    "pvrig_chain_inventory_json",
    "source_io_relpath",
    "source_io_sha256",
    "source_manifest_relpath",
    "source_manifest_sha256",
    "source_manifest_row_sha256",
    "selector_implementation_relpath",
    "selector_implementation_sha256",
    "reuse_role",
    "formal_eligible",
    "claim_boundary",
    "selection_row_sha256",
)


class SelectionError(RuntimeError):
    """Raised when the canonical selection contract cannot be proven."""


@dataclass(frozen=True)
class CaseRecord:
    candidate_id: str
    family: str
    role: str
    workdir: Path
    manifest: Path
    manifest_sha256: str
    manifest_row_sha256: str


@dataclass(frozen=True)
class PoseRecord:
    source_output_index: int
    file_name: str
    score: float
    seed: int
    path: Path
    source_sha256: str
    source_bytes: int
    coordinate_sha256: str
    coordinate_bytes: int
    vhh_inventory: Mapping[str, Any]
    pvrig_inventory: Mapping[str, Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise SelectionError(f"Required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_sha256(row: Mapping[str, Any], hash_field: str) -> str:
    return sha256_bytes(
        canonical_json({key: value for key, value in row.items() if key != hash_field}).encode(
            "utf-8"
        )
    )


def workspace_relative(path: Path, workspace_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(workspace_root.resolve()).as_posix()
    except ValueError as error:
        raise SelectionError(
            f"Path is outside the workspace and cannot be emitted as relative: {resolved}"
        ) from error


def first_nonempty_alias(
    row: Mapping[str, Any],
    aliases: Sequence[str],
    field_name: str,
    require_consistent: bool = False,
) -> str:
    values = [(alias, str(row.get(alias, "")).strip()) for alias in aliases]
    populated = [(alias, value) for alias, value in values if value]
    if not populated:
        raise SelectionError(
            f"Manifest row has no {field_name}; accepted aliases: {', '.join(aliases)}"
        )
    if require_consistent and len({value for _alias, value in populated}) != 1:
        raise SelectionError(f"Conflicting {field_name} aliases: {populated}")
    return populated[0][1]


def optional_alias(row: Mapping[str, Any], aliases: Sequence[str], default: str) -> str:
    for alias in aliases:
        value = str(row.get(alias, "")).strip()
        if value:
            return value
    return default


def resolve_workdir(raw: str, manifest: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = manifest.parent / path
    resolved = path.resolve()
    if not resolved.is_dir():
        raise SelectionError(f"Case workdir is missing or not a directory: {resolved}")
    return resolved


def resolve_workdir_aliases(row: Mapping[str, Any], manifest: Path) -> Path:
    populated = [
        (alias, str(row.get(alias, "")).strip())
        for alias in WORKDIR_ALIASES
        if str(row.get(alias, "")).strip()
    ]
    if not populated:
        raise SelectionError(
            f"Manifest row has no workdir; accepted aliases: {', '.join(WORKDIR_ALIASES)}"
        )
    resolved = [(alias, resolve_workdir(raw, manifest)) for alias, raw in populated]
    if len({path for _alias, path in resolved}) != 1:
        raise SelectionError(f"Conflicting workdir aliases: {resolved}")
    return resolved[0][1]


def read_case_manifests(paths: Sequence[Path]) -> list[CaseRecord]:
    if not paths:
        raise SelectionError("At least one --case-manifest is required")
    cases: list[CaseRecord] = []
    seen_candidate_ids: set[str] = set()
    seen_workdirs: set[Path] = set()
    for manifest in sorted((path.resolve() for path in paths), key=lambda item: item.as_posix()):
        if not manifest.is_file():
            raise SelectionError(f"Case manifest is missing: {manifest}")
        manifest_sha256 = sha256_file(manifest)
        with manifest.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise SelectionError(f"Case manifest has no header: {manifest}")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise SelectionError(f"Case manifest has duplicate columns: {manifest}")
            rows = list(reader)
        if not rows:
            raise SelectionError(f"Case manifest has no cases: {manifest}")
        for row_number, row in enumerate(rows, start=2):
            candidate_id = first_nonempty_alias(
                row, CANDIDATE_ID_ALIASES, "candidate id", require_consistent=True
            )
            workdir = resolve_workdir_aliases(row, manifest)
            if workdir.name != candidate_id:
                raise SelectionError(
                    f"Candidate/workdir mismatch in {manifest}:{row_number}: "
                    f"candidate_id={candidate_id!r}, workdir basename={workdir.name!r}"
                )
            if candidate_id in seen_candidate_ids:
                raise SelectionError(f"Duplicate candidate id across manifests: {candidate_id}")
            if workdir in seen_workdirs:
                raise SelectionError(f"Duplicate case workdir across manifests: {workdir}")
            seen_candidate_ids.add(candidate_id)
            seen_workdirs.add(workdir)
            cases.append(
                CaseRecord(
                    candidate_id=candidate_id,
                    family=optional_alias(row, FAMILY_ALIASES, "unknown"),
                    role=optional_alias(row, ROLE_ALIASES, "unspecified"),
                    workdir=workdir,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    manifest_row_sha256=sha256_bytes(canonical_json(row).encode("utf-8")),
                )
            )
    return sorted(cases, key=lambda case: (case.candidate_id, case.manifest.as_posix()))


def locate_emref_io(case: CaseRecord) -> Path:
    matches = sorted(
        case.workdir.glob("haddock3/run_*/4_emref/io.json"),
        key=lambda item: item.as_posix(),
    )
    if len(matches) != 1:
        raise SelectionError(
            f"Expected exactly one haddock3/run_*/4_emref/io.json for "
            f"{case.candidate_id}, found {len(matches)}: {matches}"
        )
    return matches[0].resolve()


def parse_finite_float(value: Any, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise SelectionError(f"{field} is not numeric: {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise SelectionError(f"{field} is not numeric: {value!r}") from error
    if not math.isfinite(parsed):
        raise SelectionError(f"{field} is not finite: {value!r}")
    return parsed


def parse_seed(value: Any, field: str) -> int:
    parsed = parse_finite_float(value, field)
    if not parsed.is_integer():
        raise SelectionError(f"{field} is not an integer: {value!r}")
    return int(parsed)


def resolve_pose_path(stage_dir: Path, file_name: str) -> Path:
    candidate = Path(file_name)
    if candidate.name != file_name or candidate.is_absolute():
        raise SelectionError(f"Unsafe or non-basename emref file_name: {file_name!r}")
    if not (file_name.endswith(".pdb") or file_name.endswith(".pdb.gz")):
        raise SelectionError(f"emref file_name is not .pdb or .pdb.gz: {file_name!r}")
    options = [stage_dir / file_name]
    if file_name.endswith(".pdb"):
        options.append(stage_dir / f"{file_name}.gz")
    elif file_name.endswith(".pdb.gz"):
        options.append(stage_dir / file_name[:-3])
    matches = [path.resolve() for path in options if path.is_file() and path.stat().st_size > 0]
    if len(matches) != 1:
        raise SelectionError(
            f"Expected exactly one nonempty .pdb/.pdb.gz for {file_name!r}; found {matches}"
        )
    return matches[0]


def read_coordinate_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    if not raw:
        raise SelectionError(f"Pose source is empty: {path}")
    if path.name.endswith(".gz"):
        try:
            coordinates = gzip.decompress(raw)
        except (OSError, EOFError) as error:
            raise SelectionError(f"Pose gzip cannot be decompressed: {path}") from error
    else:
        coordinates = raw
    if not coordinates:
        raise SelectionError(f"Decompressed pose coordinates are empty: {path}")
    return coordinates


def parse_chain_inventory(coordinates: bytes, path: Path) -> dict[str, dict[str, Any]]:
    try:
        text = coordinates.decode("ascii")
    except UnicodeDecodeError as error:
        raise SelectionError(f"PDB is not ASCII text: {path}") from error
    parsed_counts = {"A": 0, "B": 0}
    heavy_counts = {"A": 0, "B": 0}
    atom_heavy_counts = {"A": 0, "B": 0}
    hetatm_heavy_counts = {"A": 0, "B": 0}
    residues: dict[str, set[tuple[str, str, str]]] = {"A": set(), "B": set()}
    atom_residues: dict[str, set[tuple[str, str, str]]] = {"A": set(), "B": set()}
    hetatm_residues: dict[str, set[tuple[str, str, str]]] = {"A": set(), "B": set()}
    altlocs: dict[str, set[str]] = {"A": set(), "B": set()}
    altloc_heavy_counts = {"A": 0, "B": 0}
    for line_number, line in enumerate(text.splitlines(), start=1):
        record = line[:6].strip()
        if record not in {"ATOM", "HETATM"}:
            continue
        if len(line) < 54:
            raise SelectionError(f"Truncated ATOM record in {path}:{line_number}")
        chain = line[21:22]
        if chain not in parsed_counts:
            continue
        try:
            serial = int(line[6:11])
            residue_number = int(line[22:26])
            coordinates_xyz = tuple(float(line[start:end]) for start, end in ((30, 38), (38, 46), (46, 54)))
        except ValueError as error:
            raise SelectionError(f"Unparseable ATOM record in {path}:{line_number}") from error
        if serial < 1 or not all(math.isfinite(value) for value in coordinates_xyz):
            raise SelectionError(f"Invalid ATOM values in {path}:{line_number}")
        resname = line[17:20].strip()
        if not resname:
            raise SelectionError(f"Missing residue name in {path}:{line_number}")
        atom_name = line[12:16].strip()
        if not atom_name:
            raise SelectionError(f"Missing atom name in {path}:{line_number}")
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        insertion_code = line[26:27].strip()
        altloc = line[16:17].strip()
        parsed_counts[chain] += 1
        is_heavy = (
            element not in {"H", "D"}
            if element
            else not atom_name.upper().startswith(("H", "D"))
        )
        if not is_heavy:
            continue
        residue_key = (resname, str(residue_number), insertion_code)
        heavy_counts[chain] += 1
        residues[chain].add(residue_key)
        if record == "ATOM":
            atom_heavy_counts[chain] += 1
            atom_residues[chain].add(residue_key)
        else:
            hetatm_heavy_counts[chain] += 1
            hetatm_residues[chain].add(residue_key)
        if altloc:
            altlocs[chain].add(altloc)
            altloc_heavy_counts[chain] += 1
    inventory = {}
    for chain in ("A", "B"):
        inventory[chain] = {
            "chain": chain,
            "selection_rule": "heavy ATOM and HETATM records retained for pose protein chains",
            "parsed_atom_and_hetatm_count": parsed_counts[chain],
            "selected_heavy_atom_count": heavy_counts[chain],
            "selected_residue_count": len(residues[chain]),
            "atom_heavy_atom_count": atom_heavy_counts[chain],
            "atom_residue_count": len(atom_residues[chain]),
            "hetatm_heavy_atom_count": hetatm_heavy_counts[chain],
            "hetatm_residue_count": len(hetatm_residues[chain]),
            "excluded_hydrogen_or_deuterium_count": parsed_counts[chain] - heavy_counts[chain],
            "altloc_heavy_atom_count": altloc_heavy_counts[chain],
            "altloc_labels": sorted(altlocs[chain]),
        }
    for chain, label in (("A", "VHH"), ("B", "PVRIG")):
        atom_count = inventory[chain]["selected_heavy_atom_count"]
        residue_count = inventory[chain]["selected_residue_count"]
        if atom_count < 1 or residue_count < 1:
            raise SelectionError(
                f"Pose {path} has no parseable heavy {label} chain {chain} "
                "ATOM/HETATM records"
            )
    return inventory


def load_pose_records(
    io_path: Path, k: int
) -> tuple[list[PoseRecord], list[PoseRecord], dict[str, Any]]:
    try:
        payload = json.loads(io_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SelectionError(f"Cannot read emref io.json: {io_path}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("output"), list):
        raise SelectionError(f"emref io.json must contain an output list: {io_path}")
    outputs = payload["output"]
    if len(outputs) < k:
        raise SelectionError(f"emref output has {len(outputs)} records, fewer than K={k}: {io_path}")
    seen_names: set[str] = set()
    records: list[PoseRecord] = []
    inventory_rows: list[dict[str, Any]] = []
    for output_index, raw_record in enumerate(outputs):
        if not isinstance(raw_record, dict):
            raise SelectionError(f"emref output[{output_index}] is not an object: {io_path}")
        file_name = str(raw_record.get("file_name", "")).strip()
        if not file_name:
            raise SelectionError(f"emref output[{output_index}] has no file_name: {io_path}")
        if file_name in seen_names:
            raise SelectionError(f"Duplicate emref file_name {file_name!r}: {io_path}")
        seen_names.add(file_name)
        score = parse_finite_float(raw_record.get("score"), f"output[{output_index}].score")
        seed = parse_seed(raw_record.get("seed"), f"output[{output_index}].seed")
        pose_path = resolve_pose_path(io_path.parent, file_name)
        source_payload = pose_path.read_bytes()
        coordinates = read_coordinate_bytes(pose_path)
        chain_inventory = parse_chain_inventory(coordinates, pose_path)
        source_hash = sha256_bytes(source_payload)
        coordinate_hash = sha256_bytes(coordinates)
        record = PoseRecord(
            source_output_index=output_index,
            file_name=file_name,
            score=score,
            seed=seed,
            path=pose_path,
            source_sha256=source_hash,
            source_bytes=len(source_payload),
            coordinate_sha256=coordinate_hash,
            coordinate_bytes=len(coordinates),
            vhh_inventory=chain_inventory["A"],
            pvrig_inventory=chain_inventory["B"],
        )
        records.append(record)
        inventory_rows.append(
            {
                "source_output_index": output_index,
                "file_name": file_name,
                "score": format(score, ".17g"),
                "seed": seed,
                "source_pose_sha256": source_hash,
                "source_pose_bytes": len(source_payload),
                "decompressed_coordinate_sha256": coordinate_hash,
                "decompressed_coordinate_bytes": len(coordinates),
                "vhh_chain_inventory": record.vhh_inventory,
                "pvrig_chain_inventory": record.pvrig_inventory,
            }
        )
    selected = sorted(
        records,
        key=lambda record: (record.score, record.source_output_index, record.file_name),
    )[:k]
    if len(selected) != k:
        raise SelectionError(f"Internal selection mismatch: selected {len(selected)} != K={k}")
    return selected, records, {"output_count": len(outputs), "outputs": inventory_rows}


def write_csv_atomic(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=list(CSV_FIELDS), extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def build(
    case_manifests: Sequence[Path],
    output_csv: Path,
    audit_json: Path,
    k: int = DEFAULT_K,
    workspace_root: Path = WORKSPACE_ROOT,
) -> dict[str, Any]:
    if k < 1:
        raise SelectionError(f"K must be positive, got {k}")
    workspace_root = workspace_root.resolve()
    output_csv = output_csv.resolve()
    audit_json = audit_json.resolve()
    output_csv_relpath = workspace_relative(output_csv, workspace_root)
    audit_json_relpath = workspace_relative(audit_json, workspace_root)
    if output_csv == audit_json:
        raise SelectionError("--output-csv and --audit-json must be distinct")
    cases = read_case_manifests(case_manifests)
    script_path = Path(__file__).resolve()
    selector_sha256 = sha256_file(script_path)
    protected_paths = {script_path, *(case.manifest for case in cases)}
    if output_csv in protected_paths or audit_json in protected_paths:
        raise SelectionError("Output path collides with a protected selector input")
    file_bindings: dict[Path, str] = {script_path: selector_sha256}
    for case in cases:
        previous = file_bindings.setdefault(case.manifest, case.manifest_sha256)
        if previous != case.manifest_sha256:
            raise SelectionError(f"Manifest hash mismatch across cases: {case.manifest}")
    rows: list[dict[str, Any]] = []
    case_audits: list[dict[str, Any]] = []
    manifest_audits = [
        {
            "relpath": workspace_relative(path.resolve(), workspace_root),
            "sha256": sha256_file(path.resolve()),
        }
        for path in sorted({case.manifest for case in cases}, key=lambda item: item.as_posix())
    ]
    for case in cases:
        io_path = locate_emref_io(case)
        run_id = io_path.parent.parent.name
        if not run_id.startswith("run_") or run_id == "run_":
            raise SelectionError(f"Invalid HADDOCK run directory name: {run_id!r}")
        io_sha256 = sha256_file(io_path)
        selected, all_records, source_inventory = load_pose_records(io_path, k)
        file_bindings[io_path] = io_sha256
        for record, inventory_row in zip(all_records, source_inventory["outputs"], strict=True):
            file_bindings[record.path] = record.source_sha256
            inventory_row["source_pose_relpath"] = workspace_relative(record.path, workspace_root)
        if output_csv in file_bindings or audit_json in file_bindings:
            raise SelectionError("Output path collides with an emref input")
        selected_indices = [record.source_output_index for record in selected]
        for rank, record in enumerate(selected, start=1):
            source_format = "pdb.gz" if record.path.name.endswith(".gz") else "pdb"
            row: dict[str, Any] = {
                    "schema_version": "phase2_v3_p2_v1_2_emref_topk_selection_v1",
                    "protocol_id": PROTOCOL_ID,
                    "source_protocol": SOURCE_PROTOCOL,
                    "source_stage": SOURCE_STAGE,
                    "run_id": run_id,
                    "case_id": case.candidate_id,
                    "candidate_id": case.candidate_id,
                    "family": case.family,
                    "role": case.role,
                    "canonical_rank": rank,
                    "source_output_index": record.source_output_index,
                    "source_output_file": record.file_name,
                    "source_score": format(record.score, ".17g"),
                    "source_seed": record.seed,
                    "source_pose_relpath": workspace_relative(record.path, workspace_root),
                    "source_pose_format": source_format,
                    "source_pose_sha256": record.source_sha256,
                    "source_pose_bytes": record.source_bytes,
                    "compressed_source_sha256": record.source_sha256,
                    "compressed_source_bytes": record.source_bytes,
                    "decompressed_coordinate_sha256": record.coordinate_sha256,
                    "decompressed_coordinate_bytes": record.coordinate_bytes,
                    "vhh_chain_id": "A",
                    "vhh_atom_count": record.vhh_inventory["selected_heavy_atom_count"],
                    "vhh_residue_count": record.vhh_inventory["selected_residue_count"],
                    "vhh_atom_heavy_atom_count": record.vhh_inventory["atom_heavy_atom_count"],
                    "vhh_atom_residue_count": record.vhh_inventory["atom_residue_count"],
                    "vhh_hetatm_heavy_atom_count": record.vhh_inventory["hetatm_heavy_atom_count"],
                    "vhh_hetatm_residue_count": record.vhh_inventory["hetatm_residue_count"],
                    "vhh_excluded_hydrogen_or_deuterium_count": record.vhh_inventory[
                        "excluded_hydrogen_or_deuterium_count"
                    ],
                    "vhh_chain_inventory_json": canonical_json(record.vhh_inventory),
                    "pvrig_chain_id": "B",
                    "pvrig_atom_count": record.pvrig_inventory["selected_heavy_atom_count"],
                    "pvrig_residue_count": record.pvrig_inventory["selected_residue_count"],
                    "pvrig_atom_heavy_atom_count": record.pvrig_inventory["atom_heavy_atom_count"],
                    "pvrig_atom_residue_count": record.pvrig_inventory["atom_residue_count"],
                    "pvrig_hetatm_heavy_atom_count": record.pvrig_inventory["hetatm_heavy_atom_count"],
                    "pvrig_hetatm_residue_count": record.pvrig_inventory["hetatm_residue_count"],
                    "pvrig_excluded_hydrogen_or_deuterium_count": record.pvrig_inventory[
                        "excluded_hydrogen_or_deuterium_count"
                    ],
                    "pvrig_chain_inventory_json": canonical_json(record.pvrig_inventory),
                    "source_io_relpath": workspace_relative(io_path, workspace_root),
                    "source_io_sha256": io_sha256,
                    "source_manifest_relpath": workspace_relative(case.manifest, workspace_root),
                    "source_manifest_sha256": case.manifest_sha256,
                    "source_manifest_row_sha256": case.manifest_row_sha256,
                    "selector_implementation_relpath": workspace_relative(
                        script_path, workspace_root
                    ),
                    "selector_implementation_sha256": selector_sha256,
                    "reuse_role": REUSE_ROLE,
                    "formal_eligible": "false",
                    "claim_boundary": CLAIM_BOUNDARY,
                    "selection_row_sha256": "",
                }
            row["selection_row_sha256"] = row_sha256(row, "selection_row_sha256")
            rows.append(row)
        case_audits.append(
            {
                "run_id": run_id,
                "case_id": case.candidate_id,
                "candidate_id": case.candidate_id,
                "family": case.family,
                "role": case.role,
                "workdir_relpath": workspace_relative(case.workdir, workspace_root),
                "source_manifest_relpath": workspace_relative(case.manifest, workspace_root),
                "source_manifest_sha256": case.manifest_sha256,
                "source_manifest_row_sha256": case.manifest_row_sha256,
                "source_io_relpath": workspace_relative(io_path, workspace_root),
                "source_io_sha256": io_sha256,
                "source_output_count": source_inventory["output_count"],
                "selected_source_output_indices": selected_indices,
                "selected_pose_count": len(selected),
                "outputs": source_inventory["outputs"],
            }
        )
    if len(rows) != len(cases) * k:
        raise SelectionError(
            f"Output cardinality mismatch: {len(rows)} != {len(cases)} cases * K={k}"
        )
    for path, expected_sha256 in file_bindings.items():
        observed_sha256 = sha256_file(path)
        if observed_sha256 != expected_sha256:
            raise SelectionError(
                f"Input changed while selecting poses: {path}: "
                f"{observed_sha256} != {expected_sha256}"
            )
    write_csv_atomic(output_csv, rows)
    audit: dict[str, Any] = {
        "schema_version": "phase2_v3_p2_v1_2_emref_topk_selection_audit_v1",
        "status": "PASS",
        "protocol_id": PROTOCOL_ID,
        "source_protocol": SOURCE_PROTOCOL,
        "source_stage": SOURCE_STAGE,
        "k": k,
        "reuse_role": REUSE_ROLE,
        "formal_eligible": FORMAL_ELIGIBLE,
        "claim_boundary": CLAIM_BOUNDARY,
        "case_count": len(cases),
        "selected_pose_count": len(rows),
        "selector": {
            "relpath": workspace_relative(script_path, workspace_root),
            "sha256": selector_sha256,
        },
        "source_manifests": manifest_audits,
        "cases": case_audits,
        "output_csv": {
            "relpath": output_csv_relpath,
            "sha256": sha256_file(output_csv),
            "rows": len(rows),
        },
    }
    audit["audit_json_relpath"] = audit_json_relpath
    write_json_atomic(audit_json, audit)
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-manifest",
        action="append",
        required=True,
        help="Case CSV manifest; repeat for multiple source manifests",
    )
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--audit-json", required=True)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    audit = build(
        [Path(path) for path in args.case_manifest],
        Path(args.output_csv),
        Path(args.audit_json),
        args.k,
    )
    print(json.dumps({
        "status": audit["status"],
        "case_count": audit["case_count"],
        "selected_pose_count": audit["selected_pose_count"],
        "output_csv": audit["output_csv"]["relpath"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
