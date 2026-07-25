#!/usr/bin/env python3
"""Build a portable Top7500 PVRIG dual-receptor, multi-seed Docking handoff.

The recommended schedule follows the frozen V3 evaluator:

* all 7,500 candidates: 8X6B + 9E6Y at seed 917;
* deterministic stratified sentinel: both receptors at seed 1931;
* nested stratified sentinel: both receptors at seed 3253.

An optional exhaustive manifest contains all candidates, both receptors and all
three seeds.  The package is geometry-teacher infrastructure, not biological
binding, affinity, expression, purity or experimental blocking evidence.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import shutil
import tarfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable


RECEPTORS = ("8x6b", "9e6y")
SEEDS = (917, 1931, 3253)
JOB_FIELDS = [
    "job_id", "priority", "entity_type", "entity_id", "control_class",
    "expected_behavior", "conformation", "seed", "sequence_sha256",
    "cdr1_range", "cdr2_range", "cdr3_range", "cdr_residues",
    "monomer_source", "monomer_source_kind", "monomer_source_chain",
    "monomer_sha256", "receptor_pdb", "receptor_chain", "ligand_chain",
    "vhh_chain", "numbering", "cfg_hash", "restraint_hash",
    "protocol_core_sha256", "protocol_hash", "job_hash", "job_hash_basis",
    "candidate_priority_rank", "docking_stage", "repeat_selection_rank",
]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rt", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in value).strip("_")


def unique_range(sequence: str, cdr: str, label: str, candidate_id: str) -> str:
    start = sequence.find(cdr)
    if not cdr or start < 0 or sequence.find(cdr, start + 1) >= 0:
        raise ValueError(f"{candidate_id}: {label} absent, blank, or non-unique")
    return f"{start + 1}-{start + len(cdr)}"


def parse_range(spec: str) -> list[int]:
    start, end = (int(value) for value in spec.split("-", 1))
    return list(range(start, end + 1))


def pdb_residue_order(path: Path, chain: str = "H") -> list[tuple[int, str]]:
    residues: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 27 or line[21] != chain:
            continue
        key = (int(line[22:26]), line[26])
        if key not in seen:
            residues.append(key)
            seen.add(key)
    if not residues:
        raise ValueError(f"no chain {chain} ATOM residues in {path}")
    return residues


def map_sequence_range_to_pdb_residues(
    sequence_range: str, residue_order: list[tuple[int, str]], candidate_id: str,
) -> list[int]:
    sequence_positions = parse_range(sequence_range)
    if sequence_positions[-1] > len(residue_order):
        raise ValueError(f"{candidate_id}: sequence range exceeds PDB residue order")
    return sorted({residue_order[position - 1][0] for position in sequence_positions})


def stream_selected(path: Path, wanted: set[str], fields: set[str] | None = None) -> dict[str, dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    rows: dict[str, dict[str, str]] = {}
    with opener(path, "rt", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            candidate_id = row.get("candidate_id", "")
            if candidate_id in wanted:
                if candidate_id in rows:
                    raise ValueError(f"duplicate selected candidate in {path}: {candidate_id}")
                rows[candidate_id] = row if fields is None else {key: row.get(key, "") for key in fields}
    missing = wanted - set(rows)
    if missing:
        raise ValueError(f"{path}: missing {len(missing)} selected candidates; first={sorted(missing)[:3]}")
    return rows


def repeat_stratum(row: dict[str, str], total: int) -> str:
    rank = int(row["docking_priority_rank"])
    decile = min(9, (rank - 1) * 10 // total)
    return "|".join(
        (
            row.get("parent_framework_cluster", "UNKNOWN"),
            row.get("confidence_tier", "UNKNOWN"),
            row.get("docking_wave", "UNKNOWN"),
            f"priority_decile_{decile}",
        )
    )


def stratified_repeat_order(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return deterministic round-robin order across parent/confidence/wave/rank strata."""
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        row = dict(row)
        row["repeat_stratum"] = repeat_stratum(row, len(rows))
        groups[row["repeat_stratum"]].append(row)
    for stratum, members in groups.items():
        members.sort(
            key=lambda row: hashlib.sha256(
                f"pvrig_top7500_repeat_v1|{stratum}|{row['candidate_id']}".encode()
            ).hexdigest()
        )
    ordered: list[dict[str, str]] = []
    strata_order = sorted(
        groups,
        key=lambda value: hashlib.sha256(f"pvrig_top7500_stratum_order_v1|{value}".encode()).hexdigest(),
    )
    level = 0
    while len(ordered) < len(rows):
        added = 0
        for stratum in strata_order:
            members = groups[stratum]
            if level < len(members):
                ordered.append(members[level])
                added += 1
        if not added:
            break
        level += 1
    if len(ordered) != len(rows) or len({row["candidate_id"] for row in ordered}) != len(rows):
        raise AssertionError("stratified repeat ordering lost or duplicated candidates")
    return ordered


def copy_protocol_runtime(source: Path, output: Path) -> dict[str, object]:
    copies = [
        "config/blocker_judgment_rules_v2.json",
        "inputs/source/8X6B.pdb",
        "inputs/source/9E6Y.pdb",
        "inputs/source/PVRIG_hotspot_set_v1.csv",
        "inputs/normalized/8x6b_pvrig_receptor.pdb",
        "inputs/normalized/9e6y_pvrig_receptor.pdb",
        "inputs/normalized/8x6b_TL_reference.pdb",
        "inputs/normalized/9e6y_TL_reference.pdb",
        "inputs/normalized/interface_hotspots_uniprot.tsv",
        "reports/reference_normalization_summary.json",
        "scripts/common.py",
        "scripts/build_docking_jobs.py",
        "scripts/run_job.py",
        "scripts/score_pose.py",
        "scripts/status.py",
        "scripts/run_controller.py",
        "scripts/aggregate_results.py",
        "scripts/analyze_p2_p3_p4_enrichment.py",
        "scripts/validate_protocol.py",
    ]
    copied = []
    for relative in copies:
        src = source / relative
        if not src.is_file():
            raise FileNotFoundError(src)
        dst = output / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append({"path": relative, "sha256": sha256_file(dst), "bytes": dst.stat().st_size})
    base_spec = json.loads((source / "config/protocol_spec.json").read_text())
    return {"files": copied, "base_spec": base_spec}


def make_protocol_spec(
    base: dict[str, object], candidate_count: int, repeat_second: int, repeat_third: int,
) -> dict[str, object]:
    recommended_jobs = 2 * (candidate_count + repeat_second + repeat_third)
    exhaustive_jobs = 2 * candidate_count * len(SEEDS)
    references = base["references"]
    interface = base["interface"]
    scoring = base["scoring"]
    docking = dict(base["docking"])
    docking.update(
        {
            "seeds": list(SEEDS),
            "expected_candidate_jobs_recommended": recommended_jobs,
            "expected_candidate_jobs_exhaustive": exhaustive_jobs,
            "recommended_schedule": {
                "seed_917_all_candidates": candidate_count,
                "seed_1931_stratified_sentinel": repeat_second,
                "seed_3253_nested_stratified_sentinel": repeat_third,
            },
        }
    )
    for key in list(docking):
        if key.startswith("expected_") and key not in {
            "expected_candidate_jobs_recommended", "expected_candidate_jobs_exhaustive"
        }:
            docking.pop(key)
    docking.pop("smoke_control_id", None)
    docking["smoke_candidate_id"] = "set_by_handoff_manifest"
    docking["expected_smoke_jobs"] = 2
    return {
        "schema_version": 1,
        "protocol_id": "pvrig_top7500_dualreceptor_multiseed_handoff_v3_20260722",
        "status": "HANDOFF_LOCKED",
        "base_protocol_id": base.get("protocol_id", ""),
        "evidence_boundary": base.get("evidence_boundary", ""),
        "candidate_panel": {
            "panel_id": "priority_s0_stage0_top7500_v1",
            "expected_count": candidate_count,
            "selection_source": "TOP7500_DOCKING_PRIORITY_ORDER.tsv",
            "monomer_source": "NanoBodyBuilder2/ImmuneBuilder-1.2 independently predicted VHH monomers",
        },
        "controls": {
            "included": False,
            "note": "This handoff is candidate-only; do not claim the 47-control evaluator gate from this package.",
        },
        "references": references,
        "interface": interface,
        "docking": docking,
        "scoring": scoring,
        "stability_gate": {
            "minimum_successful_seeds_for_repeated_candidates": 2,
            "independent_runs_for_both_conformations": True,
            "technical_failure_semantics": "NA_not_negative",
            "calibration_controls_applied": False,
        },
    }


def lock_protocol(output: Path, base_protocol_root: Path) -> str:
    lock_paths = [
        "config/protocol_spec.json",
        "config/blocker_judgment_rules_v2.json",
        "inputs/normalized/8x6b_pvrig_receptor.pdb",
        "inputs/normalized/9e6y_pvrig_receptor.pdb",
        "inputs/normalized/8x6b_TL_reference.pdb",
        "inputs/normalized/9e6y_TL_reference.pdb",
        "inputs/normalized/interface_hotspots_uniprot.tsv",
        "reports/reference_normalization_summary.json",
        "scripts/common.py",
        "scripts/build_docking_jobs.py",
        "scripts/run_job.py",
        "scripts/score_pose.py",
    ]
    files = [
        {"path": relative, "sha256": sha256_file(output / relative), "bytes": (output / relative).stat().st_size}
        for relative in lock_paths
    ]
    protocol_hash = sha256_bytes(canonical_json(files).encode())
    base_lock = json.loads((base_protocol_root / "PROTOCOL_CORE_LOCK.json").read_text())
    write_json(
        output / "PROTOCOL_CORE_LOCK.json",
        {
            "schema_version": 1,
            "status": "CORE_LOCKED",
            "protocol_id": "pvrig_top7500_dualreceptor_multiseed_handoff_v3_20260722",
            "base_protocol_id": base_lock.get("protocol_id", ""),
            "base_protocol_core_sha256": base_lock.get("protocol_core_sha256", ""),
            "protocol_core_sha256": protocol_hash,
            "files": files,
        },
    )
    return protocol_hash


def render_cfg(spec: dict[str, object], conformation: str, seed: int, core_hash: str) -> str:
    docking = spec["docking"]
    randremoval = "true" if docking["randremoval"] else "false"
    return f'''# Frozen PVRIG V3 {conformation} independent docking config
# protocol_core_sha256={core_hash}
run_dir = "haddock_run"
mode = "local"
ncores = {int(docking["ncores"])}

molecules = [
    "data/vhh_chainA.pdb",
    "data/pvrig_chainT.pdb",
]

[topoaa]
iniseed = {seed}

[rigidbody]
ambig_fname = "data/air.tbl"
iniseed = {seed}
tolerance = {int(docking["rigidbody_tolerance"])}
sampling = {int(docking["sampling"])}
randremoval = {randremoval}
npart = {int(docking["npart"])}

[seletop]
select = {int(docking["seletop_select"])}

[flexref]
ambig_fname = "data/air.tbl"
iniseed = {seed}
tolerance = {int(docking["flexref_tolerance"])}
randremoval = {randremoval}
npart = {int(docking["npart"])}

[emref]
ambig_fname = "data/air.tbl"
iniseed = {seed}
randremoval = {randremoval}
npart = {int(docking["npart"])}

[clustfcc]
min_population = 1

[seletopclusts]
top_models = {int(docking["seletopclusts_top_models"])}
'''


def air_anchors(output: Path) -> list[int]:
    rows = read_tsv(output / "inputs/normalized/interface_hotspots_uniprot.tsv")
    values = [int(row["uniprot_position"]) for row in rows if row["restraint_role"] == "AIR_ANCHOR"]
    if len(values) != 12 or len(set(values)) != 12:
        raise ValueError(f"expected 12 unique AIR anchors, found {values}")
    return values


def render_restraints(cdr_residues: list[int], anchors: list[int], core_hash: str) -> str:
    lines = [
        f"! protocol_core_sha256={core_hash}",
        "! VHH CDR residues (chain A) to 12 UniProt-numbered PVRIG AIR anchors (chain T)",
        "! 11 holdout interface residues are deliberately absent",
    ]
    for residue in cdr_residues:
        lines.append(f"assign (resi {residue} and segid A)")
        lines.append("(")
        for index, anchor in enumerate(anchors):
            prefix = "       " if index == 0 else "        or\n       "
            lines.append(f"{prefix}(resi {anchor} and segid T)")
        lines.append(") 2.0 2.0 0.0\n")
    return "\n".join(lines) + "\n"


def make_job(
    entity: dict[str, str], conformation: str, seed: int, priority: int,
    stage: str, repeat_rank: int | None, spec: dict[str, object], anchors: list[int], core_hash: str,
) -> dict[str, str]:
    cdr_residues = [int(value) for value in entity["cdr_residues"].split(",") if value]
    cfg_hash = sha256_bytes(render_cfg(spec, conformation, seed, core_hash).encode())
    restraint_hash = sha256_bytes(render_restraints(cdr_residues, anchors, core_hash).encode())
    basis = {
        "entity_type": "candidate",
        "entity_id": entity["entity_id"],
        "sequence_sha256": entity["sequence_sha256"],
        "monomer_sha256": entity["monomer_sha256"],
        "conformation": conformation,
        "seed": seed,
        "cfg_hash": cfg_hash,
        "restraint_hash": restraint_hash,
        "protocol_core_sha256": core_hash,
    }
    basis_text = canonical_json(basis)
    job_hash = sha256_bytes(basis_text.encode())
    receptor = spec["references"]["conformations"][conformation]["normalized_receptor_pdb"]
    return {
        "job_id": f"CANDIDATE_{safe_id(entity['entity_id'])}_{conformation}_s{seed}_{job_hash[:12]}",
        "priority": str(priority),
        "entity_type": "candidate",
        "entity_id": entity["entity_id"],
        "control_class": "",
        "expected_behavior": "CANDIDATE_UNKNOWN",
        "conformation": conformation,
        "seed": str(seed),
        "sequence_sha256": entity["sequence_sha256"],
        "cdr1_range": entity["cdr1_range"],
        "cdr2_range": entity["cdr2_range"],
        "cdr3_range": entity["cdr3_range"],
        "cdr_residues": ",".join(map(str, cdr_residues)),
        "monomer_source": entity["monomer_source"],
        "monomer_source_kind": "frozen_nbb2_archive_extract",
        "monomer_source_chain": "H",
        "monomer_sha256": entity["monomer_sha256"],
        "receptor_pdb": receptor,
        "receptor_chain": spec["references"]["receptor_chain"],
        "ligand_chain": spec["references"]["ligand_chain"],
        "vhh_chain": "A",
        "numbering": spec["references"]["numbering"],
        "cfg_hash": cfg_hash,
        "restraint_hash": restraint_hash,
        "protocol_core_sha256": core_hash,
        "protocol_hash": core_hash,
        "job_hash": job_hash,
        "job_hash_basis": basis_text,
        "candidate_priority_rank": entity["candidate_priority_rank"],
        "docking_stage": stage,
        "repeat_selection_rank": "" if repeat_rank is None else str(repeat_rank),
    }


def extract_archive_group(archive: str, rows: list[dict[str, str]], output: Path) -> tuple[str, int]:
    archive_path = Path(archive)
    expected_archive_hashes = {row["nbb2_archive_sha256"] for row in rows}
    if len(expected_archive_hashes) != 1 or sha256_file(archive_path) != next(iter(expected_archive_hashes)):
        raise ValueError(f"archive SHA256 mismatch: {archive_path}")
    # gzip tar members are not cheaply seekable.  Iterating once in archive order
    # avoids re-decompressing the archive for every selected PDB.
    wanted = {row["nbb2_archive_member"]: row for row in rows}
    found: set[str] = set()
    with tarfile.open(archive_path, "r|gz") as tar:
        for member in tar:
            row = wanted.get(member.name)
            if row is None:
                continue
            source = tar.extractfile(member)
            if source is None:
                raise FileNotFoundError(f"{archive_path}:{member.name}")
            data = source.read()
            if sha256_bytes(data) != row["pdb_sha256"]:
                raise ValueError(f"PDB SHA256 mismatch: {row['candidate_id']}")
            destination = output / "inputs/candidate_monomers" / f"{row['candidate_id']}.pdb"
            destination.write_bytes(data)
            found.add(member.name)
    missing = set(wanted) - found
    if missing:
        raise FileNotFoundError(f"{archive_path}: missing {len(missing)} selected members")
    return archive, len(rows)


def shard_by_candidate_seed(jobs: list[dict[str, str]], count: int) -> list[list[dict[str, str]]]:
    units: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for job in jobs:
        units[(job["entity_id"], job["seed"])].append(job)
    ordered = sorted(units.items(), key=lambda item: min(int(row["priority"]) for row in item[1]))
    shards: list[list[dict[str, str]]] = [[] for _ in range(count)]
    for index, (_, pair) in enumerate(ordered):
        if {row["conformation"] for row in pair} != set(RECEPTORS) or len(pair) != 2:
            raise ValueError("a candidate/seed execution unit must contain exactly both receptors")
        shards[index % count].extend(sorted(pair, key=lambda row: row["conformation"]))
    return shards


def build(args: argparse.Namespace) -> dict[str, object]:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    staging = output.with_name(f".{output.name}.building.{os.getpid()}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        selection = read_tsv(args.selection)
        if len(selection) != args.expected or len({row["candidate_id"] for row in selection}) != args.expected:
            raise ValueError("selection must contain exactly 7,500 unique candidates")
        selection.sort(key=lambda row: int(row["docking_priority_rank"]))
        if [int(row["docking_priority_rank"]) for row in selection] != list(range(1, args.expected + 1)):
            raise ValueError("docking_priority_rank must be the exact range 1..7500")
        wanted = {row["candidate_id"] for row in selection}
        metric_fields = {
            "candidate_id", "sequence_sha256", "anarci_qc_status",
            "anarci_cdr1", "anarci_cdr2", "anarci_cdr3",
        }
        metrics = stream_selected(args.multimetric, wanted, metric_fields)
        structures = stream_selected(args.structure_manifest, wanted)

        runtime = copy_protocol_runtime(args.protocol_root, staging)
        if not 0 < args.repeat_third <= args.repeat_second <= args.expected:
            raise ValueError("repeat counts must satisfy 0 < third <= second <= candidates")
        spec = make_protocol_spec(
            runtime["base_spec"], args.expected, args.repeat_second, args.repeat_third
        )
        write_json(staging / "config/protocol_spec.json", spec)
        core_hash = lock_protocol(staging, args.protocol_root)

        archive_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        for candidate_id in sorted(wanted):
            row = structures[candidate_id]
            if row["status"] != "SUCCESS" or row["pdb_sequence_match"].lower() != "true":
                raise ValueError(f"invalid structure record: {candidate_id}")
            archive_groups[row["nbb2_archive_path"]].append(row)
        (staging / "inputs/candidate_monomers").mkdir(parents=True)
        with ThreadPoolExecutor(max_workers=args.extract_workers) as pool:
            futures = [pool.submit(extract_archive_group, archive, rows, staging) for archive, rows in archive_groups.items()]
            extracted = sum(future.result()[1] for future in as_completed(futures))
        if extracted != args.expected:
            raise ValueError(f"expected {args.expected} extracted monomers, found {extracted}")

        entities: list[dict[str, str]] = []
        candidate_manifest: list[dict[str, str]] = []
        for selected in selection:
            candidate_id = selected["candidate_id"]
            metric = metrics[candidate_id]
            structure = structures[candidate_id]
            if metric["anarci_qc_status"] != "PASS":
                raise ValueError(f"ANARCI not PASS: {candidate_id}")
            if not (selected["sequence_sha256"] == metric["sequence_sha256"] == structure["sequence_sha256"]):
                raise ValueError(f"sequence SHA mismatch: {candidate_id}")
            if selected["cdr3"] != metric["anarci_cdr3"]:
                raise ValueError(f"CDR3 mismatch: {candidate_id}")
            monomer_rel = f"inputs/candidate_monomers/{candidate_id}.pdb"
            monomer = staging / monomer_rel
            if sha256_file(monomer) != structure["pdb_sha256"]:
                raise ValueError(f"post-extraction monomer mismatch: {candidate_id}")
            cdr_ranges = {
                label: unique_range(selected["sequence"], metric[f"anarci_{label}"], label, candidate_id)
                for label in ("cdr1", "cdr2", "cdr3")
            }
            residue_order = pdb_residue_order(monomer, "H")
            if len(residue_order) != len(selected["sequence"]):
                raise ValueError(
                    f"PDB/sequence residue count mismatch: {candidate_id}: "
                    f"{len(residue_order)} != {len(selected['sequence'])}"
                )
            cdr_pdb_residues = {
                label: map_sequence_range_to_pdb_residues(cdr_ranges[label], residue_order, candidate_id)
                for label in ("cdr1", "cdr2", "cdr3")
            }
            all_cdr_pdb_residues = sorted(
                set().union(*(set(values) for values in cdr_pdb_residues.values()))
            )
            entity = {
                "entity_id": candidate_id,
                "sequence_sha256": selected["sequence_sha256"],
                "monomer_sha256": structure["pdb_sha256"],
                "monomer_source": monomer_rel,
                "candidate_priority_rank": selected["docking_priority_rank"],
                "cdr_residues": ",".join(map(str, all_cdr_pdb_residues)),
                **{f"{label}_range": value for label, value in cdr_ranges.items()},
            }
            entities.append(entity)
            candidate_manifest.append(
                {
                    **selected,
                    "anarci_cdr1": metric["anarci_cdr1"],
                    "anarci_cdr2": metric["anarci_cdr2"],
                    "anarci_cdr3": metric["anarci_cdr3"],
                    **cdr_ranges,
                    **{
                        f"{label}_pdb_residues": ",".join(map(str, cdr_pdb_residues[label]))
                        for label in ("cdr1", "cdr2", "cdr3")
                    },
                    "cdr_pdb_residues": ",".join(map(str, all_cdr_pdb_residues)),
                    "monomer_source": monomer_rel,
                    "monomer_source_chain": "H",
                    "monomer_sha256": structure["pdb_sha256"],
                    "monomer_bytes": structure["pdb_bytes"],
                    "structure_model": structure["structure_model"],
                    "structure_model_version": structure["structure_model_version"],
                    "source_archive": structure["nbb2_archive_path"],
                    "source_archive_sha256": structure["nbb2_archive_sha256"],
                    "source_archive_member": structure["nbb2_archive_member"],
                }
            )

        input_fields = list(selection[0]) + [
            "anarci_cdr1", "anarci_cdr2", "anarci_cdr3", "cdr1_range", "cdr2_range", "cdr3_range",
            "cdr1_pdb_residues", "cdr2_pdb_residues", "cdr3_pdb_residues", "cdr_pdb_residues",
            "monomer_source", "monomer_source_chain", "monomer_sha256", "monomer_bytes",
            "structure_model", "structure_model_version", "source_archive", "source_archive_sha256",
            "source_archive_member",
        ]
        write_tsv(staging / "inputs/TOP7500_DOCKING_CANDIDATES.tsv", candidate_manifest, input_fields)
        with (staging / "inputs/TOP7500_DOCKING_CANDIDATES.fasta").open("w") as handle:
            for row in selection:
                handle.write(f">{row['candidate_id']} docking_priority_rank={row['docking_priority_rank']}\n{row['sequence']}\n")

        repeat_order = stratified_repeat_order(selection)
        repeat_second = repeat_order[: args.repeat_second]
        repeat_third = repeat_order[: args.repeat_third]
        repeat_fields = [
            "repeat_selection_rank", "candidate_id", "docking_priority_rank", "repeat_stratum",
            "parent_framework_cluster", "confidence_tier", "docking_wave", "sequence_sha256",
        ]
        for count, rows in ((args.repeat_second, repeat_second), (args.repeat_third, repeat_third)):
            payload = []
            for index, row in enumerate(rows, 1):
                payload.append({"repeat_selection_rank": index, **row})
            write_tsv(staging / f"manifests/repeat_sentinel_{count}.tsv", payload, repeat_fields)

        entity_by_id = {row["entity_id"]: row for row in entities}
        anchors = air_anchors(staging)
        stage_specs = [
            ("STAGE1_ALL7500_SEED917", 917, selection, None),
            (f"STAGE2_SENTINEL{args.repeat_second}_SEED1931", 1931, repeat_second, {r["candidate_id"]: i for i, r in enumerate(repeat_second, 1)}),
            (f"STAGE3_NESTED{args.repeat_third}_SEED3253", 3253, repeat_third, {r["candidate_id"]: i for i, r in enumerate(repeat_third, 1)}),
        ]
        recommended: list[dict[str, str]] = []
        stage_rows: dict[str, list[dict[str, str]]] = {}
        priority = 0
        for stage, seed, members, repeat_ranks in stage_specs:
            jobs = []
            for selected in members:
                entity = entity_by_id[selected["candidate_id"]]
                for conformation in RECEPTORS:
                    priority += 1
                    jobs.append(
                        make_job(
                            entity, conformation, seed, priority, stage,
                            None if repeat_ranks is None else repeat_ranks[entity["entity_id"]],
                            spec, anchors, core_hash,
                        )
                    )
            stage_rows[stage] = jobs
            recommended.extend(jobs)

        exhaustive: list[dict[str, str]] = []
        ex_priority = 0
        for selected in selection:
            entity = entity_by_id[selected["candidate_id"]]
            for seed in SEEDS:
                for conformation in RECEPTORS:
                    ex_priority += 1
                    exhaustive.append(
                        make_job(entity, conformation, seed, ex_priority, "EXHAUSTIVE_ALL7500_3SEED", None, spec, anchors, core_hash)
                    )

        expected_stage_counts = {
            "STAGE1_ALL7500_SEED917": 15000,
            f"STAGE2_SENTINEL{args.repeat_second}_SEED1931": 2 * args.repeat_second,
            f"STAGE3_NESTED{args.repeat_third}_SEED3253": 2 * args.repeat_third,
        }
        if {name: len(rows) for name, rows in stage_rows.items()} != expected_stage_counts:
            raise AssertionError("recommended stage job counts are wrong")
        expected_recommended = 2 * (args.expected + args.repeat_second + args.repeat_third)
        expected_exhaustive = 2 * args.expected * len(SEEDS)
        if len(recommended) != expected_recommended or len(exhaustive) != expected_exhaustive:
            raise AssertionError("recommended/exhaustive job count mismatch")
        for rows in (recommended, exhaustive):
            if len({row["job_id"] for row in rows}) != len(rows) or len({row["job_hash"] for row in rows}) != len(rows):
                raise ValueError("job IDs/hashes must be unique")

        names = {
            "STAGE1_ALL7500_SEED917": "docking_jobs_stage1_all7500_seed917.tsv",
            f"STAGE2_SENTINEL{args.repeat_second}_SEED1931": f"docking_jobs_stage2_sentinel{args.repeat_second}_seed1931.tsv",
            f"STAGE3_NESTED{args.repeat_third}_SEED3253": f"docking_jobs_stage3_nested{args.repeat_third}_seed3253.tsv",
        }
        for stage, jobs in stage_rows.items():
            write_tsv(staging / "manifests" / names[stage], jobs, JOB_FIELDS)
        write_tsv(staging / f"manifests/docking_jobs_recommended_{expected_recommended}.tsv", recommended, JOB_FIELDS)
        write_tsv(staging / "manifests/docking_jobs.tsv", recommended, JOB_FIELDS)
        write_tsv(staging / "manifests/docking_jobs_exhaustive_45000.tsv", exhaustive, JOB_FIELDS)

        shard_summary = {}
        for label, jobs in (("recommended", recommended), ("exhaustive", exhaustive)):
            shards = shard_by_candidate_seed(jobs, 8)
            shard_summary[label] = [len(shard) for shard in shards]
            for index, shard in enumerate(shards):
                write_tsv(staging / f"manifests/shards_{label}_8/shard_{index:02d}.tsv", shard, JOB_FIELDS)

        smoke_jobs = [row for row in stage_rows["STAGE1_ALL7500_SEED917"] if row["entity_id"] == selection[0]["candidate_id"]]
        write_tsv(staging / "manifests/smoke_jobs.tsv", smoke_jobs, JOB_FIELDS)

        plan = {
            "schema_version": "pvrig_top7500_dual_multiseed_plan_v3",
            "status": "READY",
            "candidate_count": 7500,
            "receptors": list(RECEPTORS),
            "seeds": list(SEEDS),
            "recommended": {
                "job_count": expected_recommended,
                "stages": expected_stage_counts,
                "policy": f"all seed917; stratified {args.repeat_second} seed1931; nested {args.repeat_third} seed3253",
            },
            "optional_exhaustive": {"job_count": 45000, "policy": "all candidates x both receptors x all seeds"},
            "eight_shard_job_counts": shard_summary,
            "protocol_core_sha256": core_hash,
            "technical_failure_semantics": "NA_not_negative",
            "claim_boundary": "Computational Docking geometry only; not binding, Kd, IC50, expression, purity, or experimental blocking.",
        }
        write_json(staging / "DOCKING_PLAN.json", plan)

        readme = f"""# PVRIG Top7500 双受体多 seed Docking 交接包

## 冻结口径

- 候选：7,500 条，按 `docking_priority_rank=1..7500` 冻结。
- 受体构象：`8x6b` 和 `9e6y`，必须独立对接。
- HADDOCK3：冻结 V3 参数，4 CPU/job，sampling=40。
- seeds：917、1931、3253。
- 失败语义：技术失败是 NA，不是生物学阴性。

## 推荐运行顺序

1. `manifests/docking_jobs_stage1_all7500_seed917.tsv`：15,000 jobs。
2. `manifests/docking_jobs_stage2_sentinel{args.repeat_second}_seed1931.tsv`：{2 * args.repeat_second:,} jobs。
3. `manifests/docking_jobs_stage3_nested{args.repeat_third}_seed3253.tsv`：{2 * args.repeat_third:,} jobs。

合计 {expected_recommended:,} jobs。`manifests/docking_jobs.tsv` 与
`docking_jobs_recommended_{expected_recommended}.tsv` 均是该默认计划。第二/第三阶段为分层技术重复，
覆盖 parent、surrogate confidence、原 docking wave 和优先级十分位；{args.repeat_third:,} 条是
{args.repeat_second:,} 条的子集。

如计算资源充足，可改用 `manifests/docking_jobs_exhaustive_45000.tsv`，即所有
7,500 条都运行两受体×三 seed。不要同时运行推荐和 exhaustive 清单，
因为它们存在重叠 jobs。

## 8 节点分片

- 推荐计划：`manifests/shards_recommended_8/`
- 全量三 seed：`manifests/shards_exhaustive_8/`

同一 candidate/seed 的 8X6B 和 9E6Y 被放在同一分片，不会跨节点拆分。

## 运行

将本目录设为根目录：

```bash
export PVRIG_PROJECT_ROOT="$PWD"
export HADDOCK3=/path/to/haddock3
python3 scripts/run_job.py --job-id '<job_id>'
```

节点应在本地 scratch 中运行，并回传 `status/jobs/`、`results/`和 `runs/`。
合并时使用 `job_id + job_hash + protocol_core_sha256`。

## 重要边界

本包不包含 47 个校准对照，因此不能单独宣称完整评价器稳定门禁通过。
Docking 输出是双受体阻断样几何证据，不是 Kd、IC50 或实验阻断结果。

Protocol core SHA256: `{core_hash}`
"""
        (staging / "README_ZH.md").write_text(readme)
        for directory in ("status/jobs", "results", "runs", "failed_attempts", "reports/runtime"):
            (staging / directory).mkdir(parents=True, exist_ok=True)

        manifest_hashes = {
            "selection": sha256_file(args.selection),
            "multimetric": sha256_file(args.multimetric),
            "structure_manifest": sha256_file(args.structure_manifest),
        }
        validation = {
            "status": "PASS",
            "candidate_count": len(candidate_manifest),
            "candidate_id_unique": len({row["candidate_id"] for row in candidate_manifest}) == 7500,
            "candidate_monomer_count": len(list((staging / "inputs/candidate_monomers").glob("*.pdb"))),
            "source_archive_count": len(archive_groups),
            "recommended_job_count": len(recommended),
            "exhaustive_job_count": len(exhaustive),
            "job_shape_recommended": {
                "conformations": dict(Counter(row["conformation"] for row in recommended)),
                "seeds": dict(Counter(row["seed"] for row in recommended)),
            },
            "repeat_second_unique": len({row["candidate_id"] for row in repeat_second}) == args.repeat_second,
            "repeat_third_unique_nested": (
                len({row["candidate_id"] for row in repeat_third}) == args.repeat_third
                and {row["candidate_id"] for row in repeat_third}.issubset({row["candidate_id"] for row in repeat_second})
            ),
            "protocol_core_sha256": core_hash,
            "source_sha256": manifest_hashes,
            "claim_boundary": plan["claim_boundary"],
        }
        write_json(staging / "status/PACKAGE_VALIDATION.json", validation)
        ready = {
            "schema_version": "pvrig_top7500_dual_multiseed_handoff_v3",
            "status": "READY",
            "created_epoch": time.time(),
            "candidate_count": 7500,
            "recommended_job_count": expected_recommended,
            "optional_exhaustive_job_count": 45000,
            "receptors": list(RECEPTORS),
            "seeds": list(SEEDS),
            "protocol_core_sha256": core_hash,
            "validation": "status/PACKAGE_VALIDATION.json",
            "source_sha256": manifest_hashes,
            "claim_boundary": plan["claim_boundary"],
        }
        write_json(staging / "status/READY.json", ready)

        checksums = []
        for path in sorted(staging.rglob("*")):
            if path.is_file() and path.name != "SHA256SUMS":
                checksums.append(f"{sha256_file(path)}  {path.relative_to(staging).as_posix()}")
        (staging / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
        staging.replace(output)
        return {**ready, "output": str(output), "sha256_entries": len(checksums)}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--multimetric", type=Path, required=True)
    parser.add_argument("--structure-manifest", type=Path, required=True)
    parser.add_argument("--protocol-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=7500)
    parser.add_argument("--repeat-second", type=int, default=4000)
    parser.add_argument("--repeat-third", type=int, default=1000)
    parser.add_argument("--extract-workers", type=int, default=8)
    args = parser.parse_args()
    receipt = build(args)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
