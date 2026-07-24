#!/usr/bin/env python3
"""Build, but never launch, the Top5000 dual-receptor four-seed handoff.

Production mode is fixed to 5,000 candidates, 40,000 Docking jobs, eight
NanoBodyBuilder2 archives, and eight exact-closure balanced shards.  The
builder validates and copies structures; it does not submit or execute HADDOCK.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import tarfile
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, TextIO


VERSION = "pvrig_top5000_dualreceptor_4seed_handoff_v1_20260724"
EXPECTED_CANDIDATES = 5000
EXPECTED_SHORTLIST_ROWS = 100000
EXPECTED_JOBS = 40000
EXPECTED_ARCHIVES = 8
EXPECTED_SHARDS = 8
SEEDS = (917, 1931, 42, 3047)
CONFORMATIONS = ("8x6b", "9e6y")

EXPECTED_PROTOCOL_CORE_SHA256 = (
    "8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3"
)
EXPECTED_TEMPLATE_LOCK_SHA256 = (
    "19f0025ac06cd4e4396b672847823746544da0fc718ecdc458d7106de4baf0e2"
)
EXPECTED_PROTOCOL_SPEC_SHA256 = (
    "6cc7f7ce876c73885a164fbc10939592ef6d42a026e1300f20dadf96a90ccae9"
)
EXPECTED_CFG_HASHES = {
    "917": {
        "8x6b": "e163c08b04a1b3315589b17ab3b439ddd791224da6419154a3697161f79d5e88",
        "9e6y": "981649a809b861fc99c1838d4ab62144e10441485ae8b665eff412435f2b577e",
    },
    "1931": {
        "8x6b": "8d155f3264b4c86acac8ae8440abe8ba0d594abd9a2426bacee386236c0f90b1",
        "9e6y": "01f3b4c1875617df9d1e097e16d943cb988d7d25af3ca57335d167dec8e42c73",
    },
    "42": {
        "8x6b": "6e3411303a8196b0e07523e8d66724b2c6a9380dca7a347caa47b5632620a2a8",
        "9e6y": "7b597e4976340689606e650f7a864d1c028938e4a1d0c4201b7092f53302813a",
    },
    "3047": {
        "8x6b": "21918201f2d7d8fd86e7fbe3003003c516ebb4de914b20d6f1f82a78554f6225",
        "9e6y": "036faa08876ef5dc8e4331507bf042bf828faae3f3cf5a5fd358a89d5fb215da",
    },
}

STANDARD_RESIDUES = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}
STANDARD_AA = frozenset(STANDARD_RESIDUES.values())

REQUIRED_TEMPLATE_PATHS = {
    "config/protocol_spec.json",
    "config/blocker_judgment_rules_v2.json",
    "inputs/normalized/8x6b_pvrig_receptor.pdb",
    "inputs/normalized/9e6y_pvrig_receptor.pdb",
    "inputs/normalized/8x6b_TL_reference.pdb",
    "inputs/normalized/9e6y_TL_reference.pdb",
    "inputs/normalized/interface_hotspots_uniprot.tsv",
    "scripts/common.py",
    "scripts/build_docking_jobs.py",
    "scripts/run_job.py",
    "scripts/score_pose.py",
}

REQUIRED_PORTABLE_SUPPORT_PATHS = (
    "scripts/validate_protocol.py",
    "scripts/aggregate_external_candidate_results.py",
)
OPTIONAL_PORTABLE_SUPPORT_PATHS = (
    "scripts/aggregate_results.py",
    "scripts/status.py",
    "inputs/source/8X6B.pdb",
    "inputs/source/9E6Y.pdb",
    "inputs/source/PVRIG_hotspot_set_v1.csv",
)

CANDIDATE_FIELDS = [
    "release_rank",
    "candidate_id",
    "sequence",
    "sequence_sha256",
    "imgt_cdr1",
    "imgt_cdr2",
    "imgt_cdr3",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "cdr1_pdb_residues",
    "cdr2_pdb_residues",
    "cdr3_pdb_residues",
    "cdr_pdb_residues",
    "monomer_source",
    "monomer_source_chain",
    "monomer_sha256",
    "nbb2_manifest_pdb_relative_path",
    "nbb2_archive",
    "nbb2_archive_sha256",
    "nbb2_archive_member",
    "nbb2_structure_model",
    "nbb2_structure_model_version",
    "release_row_sha256",
    "shortlist_row_sha256",
    "nbb2_manifest_row_sha256",
]

JOB_HASH_SCHEMA = "pvrig.docking_job.complete_binding.v1"
JOB_FIELDS = [
    "job_id",
    "priority",
    "entity_type",
    "entity_id",
    "control_class",
    "expected_behavior",
    "conformation",
    "seed",
    "sequence_sha256",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "cdr_residues",
    "monomer_source",
    "monomer_source_kind",
    "monomer_source_chain",
    "monomer_sha256",
    "receptor_pdb",
    "receptor_sha256",
    "receptor_chain",
    "ligand_chain",
    "vhh_chain",
    "numbering",
    "cfg_hash",
    "restraint_hash",
    "protocol_core_sha256",
    "protocol_hash",
    "candidate_priority_rank",
    "docking_stage",
    "repeat_selection_rank",
    "job_hash_schema",
    "job_hash",
    "job_hash_basis",
]
JOB_HASH_BOUND_FIELDS = tuple(
    field
    for field in JOB_FIELDS
    if field not in {"job_id", "job_hash", "job_hash_basis"}
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@contextmanager
def open_text(path: Path) -> Iterator[TextIO]:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            yield handle
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield handle


def write_tsv(
    path: Path, fields: list[str], rows: Iterable[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def field_name(
    fields: Iterable[str],
    aliases: Iterable[str],
    label: str,
    *,
    required: bool = True,
) -> str | None:
    by_folded: dict[str, str] = {}
    for field in fields:
        folded = field.casefold()
        if folded in by_folded:
            raise ValueError(
                f"{label} has case-insensitive duplicate fields: "
                f"{by_folded[folded]!r}, {field!r}"
            )
        by_folded[folded] = field
    for alias in aliases:
        if alias.casefold() in by_folded:
            return by_folded[alias.casefold()]
    if required:
        raise ValueError(f"{label} missing field; accepted aliases: {list(aliases)}")
    return None


def safe_id(value: str) -> str:
    if not value or re.fullmatch(r"[A-Za-z0-9_.-]+", value) is None:
        raise ValueError(f"candidate_id is not a safe frozen filename: {value!r}")
    return value


def safe_template_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe template-relative path: {value!r}")
    return path


def safe_archive_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe archive-relative path: {value!r}")
    return path


def normalize_sequence(value: str, label: str) -> str:
    sequence = "".join(value.split()).upper()
    if not sequence or any(aa not in STANDARD_AA for aa in sequence):
        raise ValueError(f"{label} is not a non-empty standard amino-acid sequence")
    return sequence


def unique_substring_range(
    sequence: str, subsequence: str, label: str
) -> tuple[int, int]:
    starts: list[int] = []
    offset = 0
    while True:
        found = sequence.find(subsequence, offset)
        if found < 0:
            break
        starts.append(found)
        offset = found + 1
    if len(starts) != 1:
        raise ValueError(
            f"{label} must occur exactly once in the full sequence; "
            f"found {len(starts)} occurrences"
        )
    start = starts[0] + 1
    return start, start + len(subsequence) - 1


def read_release(
    release_tsv: Path,
    release_fasta: Path,
    expected_candidates: int,
) -> list[dict[str, str]]:
    with open_text(release_tsv) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"release TSV has no header: {release_tsv}")
        id_field = field_name(
            reader.fieldnames, ("candidate_id", "id"), "release TSV"
        )
        sequence_field = field_name(
            reader.fieldnames, ("sequence", "full_sequence"), "release TSV"
        )
        rank_field = field_name(
            reader.fieldnames,
            ("release_rank", "top5000_rank", "final_rank", "rank"),
            "release TSV",
            required=False,
        )
        sequence_hash_field = field_name(
            reader.fieldnames,
            ("sequence_sha256",),
            "release TSV",
            required=False,
        )
        rows: list[dict[str, str]] = []
        ids: set[str] = set()
        sequences: set[str] = set()
        ranks: set[int] = set()
        for row_index, source_row in enumerate(reader, 1):
            candidate_id = safe_id(source_row[id_field].strip())
            sequence = normalize_sequence(
                source_row[sequence_field], f"release sequence {candidate_id}"
            )
            sequence_hash = sha256_text(sequence)
            if sequence_hash_field and source_row[sequence_hash_field].strip():
                if source_row[sequence_hash_field].strip() != sequence_hash:
                    raise ValueError(
                        f"release sequence_sha256 mismatch: {candidate_id}"
                    )
            if candidate_id in ids:
                raise ValueError(f"duplicate release candidate_id: {candidate_id}")
            if sequence in sequences:
                raise ValueError(
                    f"duplicate release sequence: {candidate_id} ({sequence_hash})"
                )
            rank = (
                int(source_row[rank_field])
                if rank_field and source_row[rank_field].strip()
                else row_index
            )
            if rank < 1 or rank in ranks:
                raise ValueError(f"invalid or duplicate release rank: {rank}")
            ids.add(candidate_id)
            sequences.add(sequence)
            ranks.add(rank)
            rows.append(
                {
                    "release_rank": str(rank),
                    "candidate_id": candidate_id,
                    "sequence": sequence,
                    "sequence_sha256": sequence_hash,
                    "release_row_sha256": sha256_text(canonical_json(source_row)),
                }
            )
    if len(rows) != expected_candidates:
        raise ValueError(
            f"expected {expected_candidates} release rows, found {len(rows)}"
        )
    rows.sort(key=lambda row: int(row["release_rank"]))

    fasta = read_fasta(release_fasta)
    release_by_id = {row["candidate_id"]: row for row in rows}
    if set(fasta) != set(release_by_id):
        missing = sorted(set(release_by_id) - set(fasta))
        extra = sorted(set(fasta) - set(release_by_id))
        raise ValueError(
            f"release FASTA/TSV ID closure mismatch; missing={missing[:5]}, "
            f"extra={extra[:5]}"
        )
    for candidate_id, sequence in fasta.items():
        if sequence != release_by_id[candidate_id]["sequence"]:
            raise ValueError(
                f"release FASTA/TSV sequence mismatch: {candidate_id}"
            )
    if len(set(fasta.values())) != expected_candidates:
        raise ValueError("release FASTA sequences are not unique")
    return rows


def read_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    current_id: str | None = None
    chunks: list[str] = []

    def finish_record() -> None:
        nonlocal current_id, chunks
        if current_id is None:
            return
        sequence = normalize_sequence("".join(chunks), f"FASTA sequence {current_id}")
        if current_id in records:
            raise ValueError(f"duplicate FASTA candidate_id: {current_id}")
        records[current_id] = sequence
        current_id = None
        chunks = []

    with open_text(path) as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                finish_record()
                header = line[1:].strip()
                if not header:
                    raise ValueError(f"empty FASTA header at line {line_number}")
                current_id = safe_id(header.split()[0])
            else:
                if current_id is None:
                    raise ValueError(
                        f"FASTA sequence before first header at line {line_number}"
                    )
                chunks.append(line)
    finish_record()
    if not records:
        raise ValueError(f"FASTA contains no records: {path}")
    return records


def enrich_from_shortlist(
    shortlist_tsv: Path,
    release_rows: list[dict[str, str]],
    expected_shortlist_rows: int | None,
) -> None:
    release_by_id = {row["candidate_id"]: row for row in release_rows}
    selected: set[str] = set()
    with open_text(shortlist_tsv) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"shortlist TSV has no header: {shortlist_tsv}")
        id_field = field_name(
            reader.fieldnames, ("candidate_id", "id"), "100k shortlist"
        )
        sequence_field = field_name(
            reader.fieldnames, ("sequence", "full_sequence"), "100k shortlist"
        )
        cdr_fields = {
            label: field_name(
                reader.fieldnames,
                (f"IMGT_CDR{index}", f"imgt_cdr{index}", f"anarci_cdr{index}"),
                "100k shortlist",
            )
            for index, label in enumerate(("cdr1", "cdr2", "cdr3"), 1)
        }
        total_rows = 0
        for source_row in reader:
            total_rows += 1
            candidate_id = source_row[id_field].strip()
            if candidate_id not in release_by_id:
                continue
            if candidate_id in selected:
                raise ValueError(
                    f"duplicate Top5000 candidate in shortlist: {candidate_id}"
                )
            selected.add(candidate_id)
            candidate = release_by_id[candidate_id]
            sequence = normalize_sequence(
                source_row[sequence_field], f"shortlist sequence {candidate_id}"
            )
            if sequence != candidate["sequence"]:
                raise ValueError(
                    f"release/shortlist sequence mismatch: {candidate_id}"
                )
            ranges: dict[str, tuple[int, int]] = {}
            for label, source_field in cdr_fields.items():
                cdr_sequence = normalize_sequence(
                    source_row[source_field],
                    f"{candidate_id} IMGT_{label.upper()}",
                )
                start, end = unique_substring_range(
                    sequence, cdr_sequence, f"{candidate_id} IMGT_{label.upper()}"
                )
                candidate[f"imgt_{label}"] = cdr_sequence
                candidate[f"{label}_range"] = f"{start}-{end}"
                candidate[f"_{label}_start"] = str(start)
                candidate[f"_{label}_end"] = str(end)
                ranges[label] = (start, end)
            if not (
                ranges["cdr1"][1] < ranges["cdr2"][0]
                and ranges["cdr2"][1] < ranges["cdr3"][0]
            ):
                raise ValueError(
                    f"IMGT CDR ranges overlap or are out of order: {candidate_id}"
                )
            candidate["shortlist_row_sha256"] = sha256_text(
                canonical_json(source_row)
            )
    if expected_shortlist_rows is not None and total_rows != expected_shortlist_rows:
        raise ValueError(
            f"expected {expected_shortlist_rows} shortlist rows, found {total_rows}"
        )
    missing = sorted(set(release_by_id) - selected)
    if missing:
        raise ValueError(
            f"Top5000 candidates missing from shortlist: {missing[:10]}"
        )


def read_nbb2_manifest(
    manifest_tsv: Path, release_rows: list[dict[str, str]]
) -> dict[str, dict[str, str]]:
    release_by_id = {row["candidate_id"]: row for row in release_rows}
    selected: dict[str, dict[str, str]] = {}
    with open_text(manifest_tsv) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"NBB2 manifest has no header: {manifest_tsv}")
        names = {
            key: field_name(reader.fieldnames, aliases, "NBB2 aggregate manifest")
            for key, aliases in {
                "candidate_id": ("candidate_id",),
                "sequence_sha256": ("sequence_sha256",),
                "pdb_relative_path": ("pdb_relative_path",),
                "pdb_sha256": ("pdb_sha256",),
                "status": ("status",),
            }.items()
        }
        optional_names = {
            key: field_name(
                reader.fieldnames,
                aliases,
                "NBB2 aggregate manifest",
                required=False,
            )
            for key, aliases in {
                "pdb_bytes": ("pdb_bytes",),
                "pdb_sequence_match": ("pdb_sequence_match",),
                "structure_model": ("structure_model",),
                "structure_model_version": ("structure_model_version",),
            }.items()
        }
        for source_row in reader:
            candidate_id = source_row[names["candidate_id"]].strip()
            if candidate_id not in release_by_id:
                continue
            if candidate_id in selected:
                raise ValueError(
                    f"duplicate Top5000 candidate in NBB2 manifest: {candidate_id}"
                )
            candidate = release_by_id[candidate_id]
            if source_row[names["sequence_sha256"]].strip() != candidate[
                "sequence_sha256"
            ]:
                raise ValueError(
                    f"NBB2 manifest sequence hash mismatch: {candidate_id}"
                )
            if source_row[names["status"]].strip().upper() != "SUCCESS":
                raise ValueError(f"NBB2 status is not SUCCESS: {candidate_id}")
            sequence_match_field = optional_names["pdb_sequence_match"]
            if sequence_match_field and source_row[sequence_match_field].strip():
                if source_row[sequence_match_field].strip().lower() not in {
                    "true",
                    "1",
                    "yes",
                }:
                    raise ValueError(
                        f"NBB2 manifest pdb_sequence_match is not true: "
                        f"{candidate_id}"
                    )
            pdb_relative = source_row[names["pdb_relative_path"]].strip()
            safe_archive_relative(pdb_relative)
            if not pdb_relative.endswith(".pdb"):
                raise ValueError(
                    f"NBB2 manifest PDB path has wrong suffix: {candidate_id}"
                )
            pdb_hash = source_row[names["pdb_sha256"]].strip()
            if re.fullmatch(r"[0-9a-f]{64}", pdb_hash) is None:
                raise ValueError(
                    f"invalid NBB2 manifest pdb_sha256: {candidate_id}"
                )
            row = {
                "candidate_id": candidate_id,
                "sequence_sha256": candidate["sequence_sha256"],
                "pdb_relative_path": pdb_relative,
                "pdb_sha256": pdb_hash,
                "pdb_bytes": (
                    source_row[optional_names["pdb_bytes"]].strip()
                    if optional_names["pdb_bytes"]
                    else ""
                ),
                "structure_model": (
                    source_row[optional_names["structure_model"]].strip()
                    if optional_names["structure_model"]
                    else ""
                ),
                "structure_model_version": (
                    source_row[optional_names["structure_model_version"]].strip()
                    if optional_names["structure_model_version"]
                    else ""
                ),
                "manifest_row_sha256": sha256_text(canonical_json(source_row)),
            }
            if row["pdb_bytes"] and int(row["pdb_bytes"]) <= 0:
                raise ValueError(
                    f"invalid NBB2 manifest pdb_bytes: {candidate_id}"
                )
            selected[candidate_id] = row
    missing = sorted(set(release_by_id) - set(selected))
    if missing:
        raise ValueError(
            f"Top5000 candidates missing from NBB2 manifest: {missing[:10]}"
        )
    relative_paths = [row["pdb_relative_path"] for row in selected.values()]
    if len(relative_paths) != len(set(relative_paths)):
        raise ValueError("selected NBB2 manifest PDB relative paths are not unique")
    return selected


def is_standard_atom_line(line: str) -> bool:
    return (
        line.startswith("ATOM  ")
        and len(line) >= 54
        and line[17:20].strip().upper() in STANDARD_RESIDUES
    )


def pdb_sequence_mapping(path: Path, chain: str) -> tuple[str, list[str]]:
    seen: dict[tuple[int, str], str] = {}
    order: list[tuple[int, str]] = []
    with path.open("r", encoding="ascii", errors="strict") as handle:
        for line in handle:
            if not is_standard_atom_line(line) or line[21] != chain:
                continue
            try:
                residue_number = int(line[22:26])
            except ValueError as exc:
                raise ValueError(
                    f"invalid PDB residue number in {path}:{chain}"
                ) from exc
            insertion = line[26].strip()
            key = (residue_number, insertion)
            aa = STANDARD_RESIDUES[line[17:20].strip().upper()]
            if key not in seen:
                seen[key] = aa
                order.append(key)
            elif seen[key] != aa:
                raise ValueError(
                    f"inconsistent residue name for {path}:{chain}:{key}"
                )
    if not order:
        raise ValueError(f"no standard ATOM residues for chain {chain} in {path}")
    residue_ids = [f"{number}{insertion}" for number, insertion in order]
    return "".join(seen[key] for key in order), residue_ids


def positions_to_pdb_residues(
    start: int, end: int, pdb_residue_ids: list[str]
) -> list[str]:
    if start < 1 or end < start or end > len(pdb_residue_ids):
        raise ValueError(
            f"sequence range {start}-{end} is invalid for PDB sequence length "
            f"{len(pdb_residue_ids)}"
        )
    return pdb_residue_ids[start - 1 : end]


def materialize_monomers(
    archives: list[Path],
    manifest_rows: dict[str, dict[str, str]],
    release_rows: list[dict[str, str]],
    staging_root: Path,
) -> list[dict[str, Any]]:
    if len(archives) != EXPECTED_ARCHIVES:
        raise ValueError(
            f"expected exactly {EXPECTED_ARCHIVES} NBB2 archives, found "
            f"{len(archives)}"
        )
    resolved_archives = [path.resolve() for path in archives]
    if len(set(resolved_archives)) != EXPECTED_ARCHIVES:
        raise ValueError("NBB2 archive paths are not unique")
    for path in resolved_archives:
        if not path.is_file() or path.is_symlink():
            raise ValueError(
                f"NBB2 archive is missing, non-regular, or symlinked: {path}"
            )

    release_by_id = {row["candidate_id"]: row for row in release_rows}
    expected_by_basename: dict[str, str] = {}
    for candidate_id, manifest in manifest_rows.items():
        basename = PurePosixPath(manifest["pdb_relative_path"]).name
        if basename in expected_by_basename:
            raise ValueError(
                f"selected manifest PDB basenames collide: {basename}"
            )
        expected_by_basename[basename] = candidate_id

    monomer_dir = staging_root / "inputs/candidate_monomers"
    monomer_dir.mkdir(parents=True, exist_ok=False)
    found: dict[str, dict[str, str]] = {}
    archive_records: list[dict[str, Any]] = []
    for archive_path in resolved_archives:
        archive_hash = sha256_file(archive_path)
        selected_in_archive = 0
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive:
                member_path = safe_archive_relative(member.name)
                candidate_id = expected_by_basename.get(member_path.name)
                if candidate_id is None:
                    continue
                expected_relative = manifest_rows[candidate_id]["pdb_relative_path"]
                if not (
                    member.name == expected_relative
                    or member.name.endswith("/" + expected_relative)
                ):
                    continue
                if not member.isfile() or member.issym() or member.islnk():
                    raise ValueError(
                        f"selected NBB2 member is not a regular file: "
                        f"{archive_path}:{member.name}"
                    )
                if candidate_id in found:
                    previous = found[candidate_id]
                    raise ValueError(
                        f"selected NBB2 PDB appears more than once: {candidate_id}; "
                        f"{previous['archive_member']} and {member.name}"
                    )
                manifest = manifest_rows[candidate_id]
                if manifest["pdb_bytes"] and member.size != int(
                    manifest["pdb_bytes"]
                ):
                    raise ValueError(
                        f"NBB2 archive member byte count mismatch: {candidate_id}"
                    )
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(
                        f"cannot read selected NBB2 member: {member.name}"
                    )
                destination_relative = (
                    Path("inputs/candidate_monomers")
                    / f"{safe_id(candidate_id)}.pdb"
                )
                destination = staging_root / destination_relative
                digest = hashlib.sha256()
                bytes_written = 0
                with destination.open("wb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        bytes_written += len(chunk)
                extracted_hash = digest.hexdigest()
                if bytes_written != member.size:
                    raise ValueError(
                        f"short read while extracting NBB2 PDB: {candidate_id}"
                    )
                if extracted_hash != manifest["pdb_sha256"]:
                    raise ValueError(
                        f"NBB2 archive PDB hash mismatch: {candidate_id}"
                    )
                pdb_sequence, pdb_residue_ids = pdb_sequence_mapping(
                    destination, "H"
                )
                candidate = release_by_id[candidate_id]
                if pdb_sequence != candidate["sequence"]:
                    raise ValueError(
                        f"PDB chain H sequence mismatch: {candidate_id}"
                    )
                cdr_residues: dict[str, list[str]] = {}
                for label in ("cdr1", "cdr2", "cdr3"):
                    cdr_residues[label] = positions_to_pdb_residues(
                        int(candidate[f"_{label}_start"]),
                        int(candidate[f"_{label}_end"]),
                        pdb_residue_ids,
                    )
                all_cdr_residues: list[str] = []
                for label in ("cdr1", "cdr2", "cdr3"):
                    for residue in cdr_residues[label]:
                        if residue not in all_cdr_residues:
                            all_cdr_residues.append(residue)
                found[candidate_id] = {
                    "monomer_source": destination_relative.as_posix(),
                    "monomer_source_chain": "H",
                    "monomer_sha256": extracted_hash,
                    "nbb2_archive": archive_path.name,
                    "nbb2_archive_sha256": archive_hash,
                    "archive_member": member.name,
                    "cdr1_pdb_residues": ",".join(cdr_residues["cdr1"]),
                    "cdr2_pdb_residues": ",".join(cdr_residues["cdr2"]),
                    "cdr3_pdb_residues": ",".join(cdr_residues["cdr3"]),
                    "cdr_pdb_residues": ",".join(all_cdr_residues),
                }
                selected_in_archive += 1
        archive_records.append(
            {
                "path": str(archive_path),
                "name": archive_path.name,
                "sha256": archive_hash,
                "bytes": archive_path.stat().st_size,
                "selected_pdbs": selected_in_archive,
            }
        )
    missing = sorted(set(manifest_rows) - set(found))
    if missing:
        raise ValueError(
            f"Top5000 PDBs missing from the eight NBB2 archives: {missing[:10]}"
        )
    pdb_outputs = list(monomer_dir.glob("*.pdb"))
    if len(pdb_outputs) != len(release_rows):
        raise AssertionError(
            f"expected {len(release_rows)} materialized PDBs, found "
            f"{len(pdb_outputs)}"
        )
    for candidate in release_rows:
        candidate.update(found[candidate["candidate_id"]])
    return archive_records


def validate_template(
    template_root: Path, production: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    lock_path = template_root / "PROTOCOL_CORE_LOCK.json"
    if not lock_path.is_file() or lock_path.is_symlink():
        raise ValueError("template PROTOCOL_CORE_LOCK.json missing or symlinked")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("status") != "CORE_LOCKED":
        raise ValueError("template protocol core is not CORE_LOCKED")
    if lock.get("protocol_core_sha256") != EXPECTED_PROTOCOL_CORE_SHA256:
        raise ValueError(
            "template protocol_core_sha256 is not the fixed production core"
        )
    if production and sha256_file(lock_path) != EXPECTED_TEMPLATE_LOCK_SHA256:
        raise ValueError("production template lock is not the exact frozen lock")

    lock_rows: dict[str, dict[str, Any]] = {}
    for source_row in lock.get("files", []):
        relative = str(source_row.get("path", ""))
        if relative in lock_rows:
            raise ValueError(f"duplicate template lock path: {relative}")
        safe_template_relative(relative)
        lock_rows[relative] = source_row
    missing = sorted(REQUIRED_TEMPLATE_PATHS - set(lock_rows))
    if missing:
        raise ValueError(f"template lock lacks required paths: {missing}")
    for relative, source_row in lock_rows.items():
        source = template_root / safe_template_relative(relative)
        if not source.is_file() or source.is_symlink():
            raise ValueError(
                f"locked template file missing, non-regular, or symlinked: "
                f"{relative}"
            )
        if sha256_file(source) != source_row.get("sha256"):
            raise ValueError(f"locked template hash mismatch: {relative}")
        if source.stat().st_size != int(source_row.get("bytes", -1)):
            raise ValueError(f"locked template byte count mismatch: {relative}")

    protocol_path = template_root / "config/protocol_spec.json"
    if production and sha256_file(protocol_path) != EXPECTED_PROTOCOL_SPEC_SHA256:
        raise ValueError(
            "production protocol_spec.json is not the exact frozen file"
        )
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("status") != "HANDOFF_LOCKED":
        raise ValueError("template protocol is not HANDOFF_LOCKED")
    conformations = protocol.get("references", {}).get("conformations", {})
    if set(conformations) != set(CONFORMATIONS):
        raise ValueError(
            "template does not contain exactly the two frozen receptor "
            "conformations"
        )
    cfg_hashes = calculate_cfg_hashes(protocol)
    if cfg_hashes != EXPECTED_CFG_HASHES:
        raise ValueError(f"four-seed cfg hashes changed: {cfg_hashes}")
    return protocol, lock, lock_rows


def copy_frozen_template(
    template_root: Path, staging_root: Path, lock: dict[str, Any]
) -> None:
    shutil.copyfile(
        template_root / "PROTOCOL_CORE_LOCK.json",
        staging_root / "PROTOCOL_CORE_LOCK.json",
    )
    for source_row in lock["files"]:
        relative = safe_template_relative(str(source_row["path"]))
        source = template_root / relative
        destination = staging_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if sha256_file(destination) != source_row["sha256"]:
            raise ValueError(f"copied frozen template hash mismatch: {relative}")


def collect_portable_support(
    template_root: Path, production: bool
) -> list[dict[str, Any]]:
    support: list[dict[str, Any]] = []
    required = set(REQUIRED_PORTABLE_SUPPORT_PATHS)
    for relative in (
        *REQUIRED_PORTABLE_SUPPORT_PATHS,
        *OPTIONAL_PORTABLE_SUPPORT_PATHS,
    ):
        source = template_root / safe_template_relative(relative)
        is_required = relative in required
        if source.is_symlink():
            if production and is_required:
                raise ValueError(
                    f"required portable support is symlinked: {relative}"
                )
            continue
        if not source.exists():
            if production and is_required:
                raise ValueError(
                    f"required portable support is missing: {relative}"
                )
            continue
        if not source.is_file():
            if production and is_required:
                raise ValueError(
                    f"required portable support is not a regular file: "
                    f"{relative}"
                )
            continue
        support.append(
            {
                "path": relative,
                "source": source,
                "required_in_production": is_required,
                "sha256": sha256_file(source),
                "bytes": source.stat().st_size,
            }
        )
    return support


def copy_portable_support(
    support: list[dict[str, Any]], staging_root: Path
) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for source_row in support:
        relative = safe_template_relative(str(source_row["path"]))
        source = Path(source_row["source"])
        destination = staging_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if (
                not destination.is_file()
                or destination.is_symlink()
                or sha256_file(destination) != source_row["sha256"]
            ):
                raise ValueError(
                    f"portable support collides with different frozen output: "
                    f"{relative}"
                )
        else:
            shutil.copyfile(source, destination)
        if (
            sha256_file(destination) != source_row["sha256"]
            or destination.stat().st_size != source_row["bytes"]
        ):
            raise ValueError(
                f"copied portable support hash/size mismatch: {relative}"
            )
        copied.append(
            {
                "path": relative.as_posix(),
                "sha256": source_row["sha256"],
                "bytes": source_row["bytes"],
                "required_in_production": source_row[
                    "required_in_production"
                ],
            }
        )
    return copied


def anchor_positions(template_root: Path) -> list[int]:
    path = template_root / "inputs/normalized/interface_hotspots_uniprot.tsv"
    with open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError("interface hotspot TSV has no header")
        position_field = field_name(
            reader.fieldnames, ("uniprot_position",), "interface hotspot TSV"
        )
        role_field = field_name(
            reader.fieldnames, ("restraint_role",), "interface hotspot TSV"
        )
        positions = [
            int(row[position_field])
            for row in reader
            if row[role_field] == "AIR_ANCHOR"
        ]
    if len(positions) != 12 or len(set(positions)) != 12:
        raise ValueError(f"expected 12 unique AIR anchors, found {positions}")
    return positions


def cfg_payload(
    protocol: dict[str, Any],
    conformation: str,
    seed: int,
    core_hash: str,
) -> dict[str, Any]:
    docking = protocol["docking"]
    return {
        "protocol_core_sha256": core_hash,
        "conformation": conformation,
        "seed": int(seed),
        "ncores": int(docking["ncores"]),
        "sampling": int(docking["sampling"]),
        "select": int(docking["seletop_select"]),
        "top_models": int(docking["seletopclusts_top_models"]),
        "rigidbody_tolerance": int(docking["rigidbody_tolerance"]),
        "flexref_tolerance": int(docking["flexref_tolerance"]),
        "randremoval": bool(docking["randremoval"]),
        "npart": int(docking["npart"]),
    }


def render_cfg(
    protocol: dict[str, Any],
    conformation: str,
    seed: int,
    core_hash: str,
) -> str:
    cfg = cfg_payload(protocol, conformation, seed, core_hash)
    boolean = "true" if cfg["randremoval"] else "false"
    return f'''# Frozen PVRIG V3 {conformation} independent docking config
# protocol_core_sha256={core_hash}
run_dir = "haddock_run"
mode = "local"
ncores = {cfg["ncores"]}

molecules = [
    "data/vhh_chainA.pdb",
    "data/pvrig_chainT.pdb",
]

[topoaa]
iniseed = {seed}

[rigidbody]
ambig_fname = "data/air.tbl"
iniseed = {seed}
tolerance = {cfg["rigidbody_tolerance"]}
sampling = {cfg["sampling"]}
randremoval = {boolean}
npart = {cfg["npart"]}

[seletop]
select = {cfg["select"]}

[flexref]
ambig_fname = "data/air.tbl"
iniseed = {seed}
tolerance = {cfg["flexref_tolerance"]}
randremoval = {boolean}
npart = {cfg["npart"]}

[emref]
ambig_fname = "data/air.tbl"
iniseed = {seed}
randremoval = {boolean}
npart = {cfg["npart"]}

[clustfcc]
min_population = 1

[seletopclusts]
top_models = {cfg["top_models"]}
'''


def calculate_cfg_hashes(protocol: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        str(seed): {
            conformation: sha256_text(
                render_cfg(
                    protocol,
                    conformation,
                    seed,
                    EXPECTED_PROTOCOL_CORE_SHA256,
                )
            )
            for conformation in CONFORMATIONS
        }
        for seed in SEEDS
    }


def render_restraints(
    cdr_residues: list[str], core_hash: str, anchors: list[int]
) -> str:
    lines = [
        f"! protocol_core_sha256={core_hash}",
        "! VHH CDR residues (source chain H, runtime chain A) to 12 "
        "UniProt-numbered PVRIG AIR anchors (chain T)",
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


def freeze_candidates(
    release_rows: list[dict[str, str]],
    manifest_rows: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    frozen: list[dict[str, str]] = []
    for candidate in release_rows:
        manifest = manifest_rows[candidate["candidate_id"]]
        frozen.append(
            {
                "release_rank": candidate["release_rank"],
                "candidate_id": candidate["candidate_id"],
                "sequence": candidate["sequence"],
                "sequence_sha256": candidate["sequence_sha256"],
                "imgt_cdr1": candidate["imgt_cdr1"],
                "imgt_cdr2": candidate["imgt_cdr2"],
                "imgt_cdr3": candidate["imgt_cdr3"],
                "cdr1_range": candidate["cdr1_range"],
                "cdr2_range": candidate["cdr2_range"],
                "cdr3_range": candidate["cdr3_range"],
                "cdr1_pdb_residues": candidate["cdr1_pdb_residues"],
                "cdr2_pdb_residues": candidate["cdr2_pdb_residues"],
                "cdr3_pdb_residues": candidate["cdr3_pdb_residues"],
                "cdr_pdb_residues": candidate["cdr_pdb_residues"],
                "monomer_source": candidate["monomer_source"],
                "monomer_source_chain": candidate["monomer_source_chain"],
                "monomer_sha256": candidate["monomer_sha256"],
                "nbb2_manifest_pdb_relative_path": manifest[
                    "pdb_relative_path"
                ],
                "nbb2_archive": candidate["nbb2_archive"],
                "nbb2_archive_sha256": candidate["nbb2_archive_sha256"],
                "nbb2_archive_member": candidate["archive_member"],
                "nbb2_structure_model": manifest["structure_model"],
                "nbb2_structure_model_version": manifest[
                    "structure_model_version"
                ],
                "release_row_sha256": candidate["release_row_sha256"],
                "shortlist_row_sha256": candidate["shortlist_row_sha256"],
                "nbb2_manifest_row_sha256": manifest[
                    "manifest_row_sha256"
                ],
            }
        )
    return frozen


def expected_job_id(row: dict[str, str], job_hash: str) -> str:
    return (
        f"CANDIDATE_{safe_id(row['entity_id'])}_{row['conformation']}_"
        f"s{row['seed']}_{job_hash[:12]}"
    )


def bind_job_hash(row: dict[str, str]) -> dict[str, str]:
    missing = [field for field in JOB_HASH_BOUND_FIELDS if field not in row]
    if missing:
        raise ValueError(f"job is missing hash-bound fields: {missing}")
    basis = {field: row[field] for field in JOB_HASH_BOUND_FIELDS}
    basis_text = canonical_json(basis)
    job_hash = sha256_text(basis_text)
    bound = dict(row)
    bound["job_hash_basis"] = basis_text
    bound["job_hash"] = job_hash
    bound["job_id"] = expected_job_id(bound, job_hash)
    return bound


def validate_job_hash_binding(row: dict[str, str]) -> None:
    if row.get("job_hash_schema") != JOB_HASH_SCHEMA:
        raise ValueError(f"unknown job_hash_schema: {row.get('job_hash_schema')}")
    basis = {field: row[field] for field in JOB_HASH_BOUND_FIELDS}
    basis_text = canonical_json(basis)
    if row.get("job_hash_basis") != basis_text:
        raise ValueError(f"job_hash_basis mismatch: {row.get('job_id', '')}")
    expected_hash = sha256_text(basis_text)
    if row.get("job_hash") != expected_hash:
        raise ValueError(f"job_hash mismatch: {row.get('job_id', '')}")
    if row.get("job_id") != expected_job_id(row, expected_hash):
        raise ValueError(f"job_id/hash mismatch: {row.get('job_id', '')}")


def build_jobs(
    candidates: list[dict[str, str]],
    protocol: dict[str, Any],
    lock_rows: dict[str, dict[str, Any]],
    anchors: list[int],
) -> list[dict[str, str]]:
    cfg_hashes = calculate_cfg_hashes(protocol)
    jobs: list[dict[str, str]] = []
    priority = 0
    for candidate in candidates:
        cdr_residues = [
            value
            for value in candidate["cdr_pdb_residues"].split(",")
            if value
        ]
        restraint_hash = sha256_text(
            render_restraints(
                cdr_residues, EXPECTED_PROTOCOL_CORE_SHA256, anchors
            )
        )
        for seed in SEEDS:
            for conformation in CONFORMATIONS:
                priority += 1
                receptor_path = protocol["references"]["conformations"][
                    conformation
                ]["normalized_receptor_pdb"]
                if receptor_path not in lock_rows:
                    raise ValueError(
                        f"normalized receptor is not lock-bound: {receptor_path}"
                    )
                semantic_row = {
                    "priority": str(priority),
                    "entity_type": "candidate",
                    "entity_id": candidate["candidate_id"],
                    "control_class": "",
                    "expected_behavior": "CANDIDATE_UNKNOWN",
                    "conformation": conformation,
                    "seed": str(seed),
                    "sequence_sha256": candidate["sequence_sha256"],
                    "cdr1_range": candidate["cdr1_range"],
                    "cdr2_range": candidate["cdr2_range"],
                    "cdr3_range": candidate["cdr3_range"],
                    "cdr_residues": candidate["cdr_pdb_residues"],
                    "monomer_source": candidate["monomer_source"],
                    "monomer_source_kind": (
                        "frozen_nbb2_archive_manifest_copy"
                    ),
                    "monomer_source_chain": candidate[
                        "monomer_source_chain"
                    ],
                    "monomer_sha256": candidate["monomer_sha256"],
                    "receptor_pdb": receptor_path,
                    "receptor_sha256": str(
                        lock_rows[receptor_path]["sha256"]
                    ),
                    "receptor_chain": protocol["references"][
                        "receptor_chain"
                    ],
                    "ligand_chain": protocol["references"]["ligand_chain"],
                    "vhh_chain": "A",
                    "numbering": protocol["references"]["numbering"],
                    "cfg_hash": cfg_hashes[str(seed)][conformation],
                    "restraint_hash": restraint_hash,
                    "protocol_core_sha256": EXPECTED_PROTOCOL_CORE_SHA256,
                    "protocol_hash": EXPECTED_PROTOCOL_CORE_SHA256,
                    "candidate_priority_rank": candidate["release_rank"],
                    "docking_stage": (
                        "TOP5000_DUALRECEPTOR_4SEED_EXHAUSTIVE"
                    ),
                    "repeat_selection_rank": "",
                    "job_hash_schema": JOB_HASH_SCHEMA,
                }
                jobs.append(bind_job_hash(semantic_row))
    expected_jobs = len(candidates) * len(SEEDS) * len(CONFORMATIONS)
    if len(jobs) != expected_jobs:
        raise AssertionError(
            f"expected {expected_jobs} jobs, built {len(jobs)}"
        )
    for job in jobs:
        validate_job_hash_binding(job)
    if len({job["job_id"] for job in jobs}) != expected_jobs:
        raise ValueError("job IDs are not unique")
    if len({job["job_hash"] for job in jobs}) != expected_jobs:
        raise ValueError("job hashes are not unique")
    counts = Counter((job["seed"], job["conformation"]) for job in jobs)
    for seed in SEEDS:
        for conformation in CONFORMATIONS:
            if counts[(str(seed), conformation)] != len(candidates):
                raise AssertionError(
                    f"job matrix is incomplete for seed={seed}, "
                    f"conformation={conformation}"
                )
    return jobs


def build_balanced_shards(
    jobs: list[dict[str, str]],
    candidates: list[dict[str, str]],
    shard_count: int,
) -> list[list[dict[str, str]]]:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    by_candidate: dict[str, list[dict[str, str]]] = defaultdict(list)
    for job in jobs:
        by_candidate[job["entity_id"]].append(job)
    shards: list[list[dict[str, str]]] = [[] for _ in range(shard_count)]
    expected_pairs = {
        (str(seed), conformation)
        for seed in SEEDS
        for conformation in CONFORMATIONS
    }
    for candidate_index, candidate in enumerate(candidates):
        unit = by_candidate[candidate["candidate_id"]]
        if len(unit) != len(expected_pairs) or {
            (row["seed"], row["conformation"]) for row in unit
        } != expected_pairs:
            raise ValueError(
                f"candidate does not have the exact eight-job matrix: "
                f"{candidate['candidate_id']}"
            )
        shards[candidate_index % shard_count].extend(
            sorted(unit, key=lambda row: int(row["priority"]))
        )

    all_hashes = [job["job_hash"] for job in jobs]
    sharded_hashes = [
        job["job_hash"] for shard in shards for job in shard
    ]
    if (
        len(sharded_hashes) != len(all_hashes)
        or len(set(sharded_hashes)) != len(sharded_hashes)
        or set(sharded_hashes) != set(all_hashes)
    ):
        raise AssertionError("shards do not form exact one-time job closure")
    job_counts = [len(shard) for shard in shards]
    if max(job_counts) - min(job_counts) > len(expected_pairs):
        raise AssertionError("shard job counts are not candidate-unit balanced")
    for seed, conformation in expected_pairs:
        counts = [
            sum(
                row["seed"] == seed
                and row["conformation"] == conformation
                for row in shard
            )
            for shard in shards
        ]
        if max(counts) - min(counts) > 1:
            raise AssertionError(
                f"shards are not balanced for seed={seed}, "
                f"conformation={conformation}: {counts}"
            )
    return shards


def write_shards(
    staging_root: Path,
    shards: list[list[dict[str, str]]],
    all_jobs: list[dict[str, str]],
) -> tuple[Path, dict[str, Any]]:
    shard_root = staging_root / "manifests/shards_exact_8"
    shard_root.mkdir(parents=True, exist_ok=False)
    shard_rows: list[dict[str, Any]] = []
    for index, shard in enumerate(shards):
        path = shard_root / f"shard_{index:02d}.tsv"
        write_tsv(path, JOB_FIELDS, shard)
        counts = Counter((row["seed"], row["conformation"]) for row in shard)
        shard_rows.append(
            {
                "shard": index,
                "path": path.relative_to(staging_root).as_posix(),
                "sha256": sha256_file(path),
                "jobs": len(shard),
                "candidates": len({row["entity_id"] for row in shard}),
                "jobs_by_seed_conformation": {
                    f"seed{seed}_{conformation}": counts[
                        (str(seed), conformation)
                    ]
                    for seed in SEEDS
                    for conformation in CONFORMATIONS
                },
                "ordered_job_hashes_sha256": sha256_text(
                    "".join(f"{row['job_hash']}\n" for row in shard)
                ),
            }
        )
    closure = {
        "schema_version": "pvrig.top5000.exact_closure_shards.v1",
        "status": "PASS_EXACT_CLOSURE_BALANCED",
        "shard_count": len(shards),
        "job_count": sum(len(shard) for shard in shards),
        "unique_job_hashes": len(
            {row["job_hash"] for shard in shards for row in shard}
        ),
        "authoritative_job_count": len(all_jobs),
        "authoritative_unique_job_hashes": len(
            {row["job_hash"] for row in all_jobs}
        ),
        "exact_hash_set_closure": (
            {
                row["job_hash"] for shard in shards for row in shard
            }
            == {row["job_hash"] for row in all_jobs}
        ),
        "candidate_units_split_across_shards": 0,
        "shards": shard_rows,
    }
    receipt_path = shard_root / "SHARD_RECEIPT.json"
    write_json(receipt_path, closure)
    return receipt_path, closure


def write_sha256s(root: Path) -> None:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.name != "SHA256SUMS"
    )
    with (root / "SHA256SUMS").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        for path in files:
            handle.write(
                f"{sha256_file(path)}  "
                f"{path.relative_to(root).as_posix()}\n"
            )


def build_handoff(
    release_tsv: Path,
    release_fasta: Path,
    shortlist_tsv: Path,
    nbb2_manifest_tsv: Path,
    nbb2_archives: list[Path],
    template_root: Path,
    output_root: Path,
    created_at: str,
    *,
    expected_candidates: int = EXPECTED_CANDIDATES,
    expected_shortlist_rows: int | None = EXPECTED_SHORTLIST_ROWS,
    shard_count: int = EXPECTED_SHARDS,
    production: bool = True,
) -> dict[str, Any]:
    release_tsv = release_tsv.resolve()
    release_fasta = release_fasta.resolve()
    shortlist_tsv = shortlist_tsv.resolve()
    nbb2_manifest_tsv = nbb2_manifest_tsv.resolve()
    template_root = template_root.resolve()
    output_root = output_root.resolve()
    if production:
        if expected_candidates != EXPECTED_CANDIDATES:
            raise ValueError("production candidate count must be exactly 5,000")
        if expected_shortlist_rows != EXPECTED_SHORTLIST_ROWS:
            raise ValueError(
                "production shortlist row count must be exactly 100,000"
            )
        if shard_count != EXPECTED_SHARDS:
            raise ValueError("production shard count must be exactly eight")
    for label, path in {
        "release TSV": release_tsv,
        "release FASTA": release_fasta,
        "100k shortlist": shortlist_tsv,
        "NBB2 aggregate manifest": nbb2_manifest_tsv,
    }.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"{label} is missing, non-regular, or symlinked: {path}")
    if output_root.exists():
        raise ValueError(f"output root already exists: {output_root}")

    staging_root = output_root.with_name(
        f".{output_root.name}.staging.{os.getpid()}.{uuid.uuid4().hex}"
    )
    staging_root.mkdir(parents=True)
    try:
        portable_support_sources = collect_portable_support(
            template_root, production
        )
        protocol, lock, lock_rows = validate_template(
            template_root, production
        )
        copy_frozen_template(template_root, staging_root, lock)
        portable_support = copy_portable_support(
            portable_support_sources, staging_root
        )
        release_rows = read_release(
            release_tsv, release_fasta, expected_candidates
        )
        enrich_from_shortlist(
            shortlist_tsv, release_rows, expected_shortlist_rows
        )
        manifest_rows = read_nbb2_manifest(
            nbb2_manifest_tsv, release_rows
        )
        archive_records = materialize_monomers(
            nbb2_archives, manifest_rows, release_rows, staging_root
        )
        candidates = freeze_candidates(release_rows, manifest_rows)
        candidate_manifest = staging_root / "inputs/top5000_candidates.tsv"
        write_tsv(candidate_manifest, CANDIDATE_FIELDS, candidates)

        anchors = anchor_positions(template_root)
        cfg_hashes = calculate_cfg_hashes(protocol)
        cfg_lock = {
            "schema_version": "pvrig.four_seed_cfg_lock.v1",
            "status": "LOCKED",
            "protocol_core_sha256": EXPECTED_PROTOCOL_CORE_SHA256,
            "conformations": list(CONFORMATIONS),
            "seeds": list(SEEDS),
            "cfg_hashes": cfg_hashes,
            "cfg_payloads": {
                str(seed): {
                    conformation: cfg_payload(
                        protocol,
                        conformation,
                        seed,
                        EXPECTED_PROTOCOL_CORE_SHA256,
                    )
                    for conformation in CONFORMATIONS
                }
                for seed in SEEDS
            },
        }
        cfg_lock_path = staging_root / "config/FOUR_SEED_CFG_LOCK.json"
        write_json(cfg_lock_path, cfg_lock)

        jobs = build_jobs(candidates, protocol, lock_rows, anchors)
        if production and len(jobs) != EXPECTED_JOBS:
            raise AssertionError(
                f"production job count must be {EXPECTED_JOBS}, found "
                f"{len(jobs)}"
            )
        job_manifest = staging_root / "manifests/docking_jobs.tsv"
        write_tsv(job_manifest, JOB_FIELDS, jobs)
        shards = build_balanced_shards(jobs, candidates, shard_count)
        shard_receipt_path, shard_receipt = write_shards(
            staging_root, shards, jobs
        )
        if production and [len(shard) for shard in shards] != [5000] * 8:
            raise AssertionError(
                "production shards must each contain exactly 5,000 jobs"
            )

        input_hashes = {
            "release_tsv": {
                "path": str(release_tsv),
                "sha256": sha256_file(release_tsv),
                "bytes": release_tsv.stat().st_size,
            },
            "release_fasta": {
                "path": str(release_fasta),
                "sha256": sha256_file(release_fasta),
                "bytes": release_fasta.stat().st_size,
            },
            "shortlist_tsv": {
                "path": str(shortlist_tsv),
                "sha256": sha256_file(shortlist_tsv),
                "bytes": shortlist_tsv.stat().st_size,
            },
            "nbb2_manifest_tsv": {
                "path": str(nbb2_manifest_tsv),
                "sha256": sha256_file(nbb2_manifest_tsv),
                "bytes": nbb2_manifest_tsv.stat().st_size,
            },
            "nbb2_archives": archive_records,
            "template_root": str(template_root),
            "template_lock_sha256": sha256_file(
                template_root / "PROTOCOL_CORE_LOCK.json"
            ),
        }
        matrix_counts = Counter(
            (row["seed"], row["conformation"]) for row in jobs
        )
        receipt: dict[str, Any] = {
            "schema_version": "pvrig.top5000.dualreceptor_4seed.handoff.v1",
            "package_version": VERSION,
            "created_at": created_at,
            "status": (
                "READY_FOR_EXTERNAL_DOCKING_SUBMISSION"
                if production
                else "SYNTHETIC_TEST_ONLY_PASS"
            ),
            "production": production,
            "docking_started": False,
            "launch_authority": (
                "NONE: this builder only materializes a hash-closed handoff; "
                "it never submits or runs Docking."
            ),
            "claim_boundary": (
                "Independent dual-receptor computational Docking geometry "
                "inputs only; not binding, Kd, IC50, expression, purity, or "
                "experimental blocking evidence."
            ),
            "source": input_hashes,
            "portable_support": {
                "required_in_production": list(
                    REQUIRED_PORTABLE_SUPPORT_PATHS
                ),
                "copied": portable_support,
            },
            "protocol": {
                "protocol_core_sha256": EXPECTED_PROTOCOL_CORE_SHA256,
                "conformations": list(CONFORMATIONS),
                "seeds": list(SEEDS),
                "cfg_hashes": cfg_hashes,
                "cfg_lock_sha256": sha256_file(cfg_lock_path),
                "air_anchor_count": len(anchors),
                "job_hash_schema": JOB_HASH_SCHEMA,
                "job_hash_bound_fields": list(JOB_HASH_BOUND_FIELDS),
            },
            "counts": {
                "candidates": len(candidates),
                "materialized_pdbs": len(
                    list(
                        (staging_root / "inputs/candidate_monomers").glob(
                            "*.pdb"
                        )
                    )
                ),
                "jobs": len(jobs),
                "unique_candidate_ids": len(
                    {row["candidate_id"] for row in candidates}
                ),
                "unique_sequences": len(
                    {row["sequence"] for row in candidates}
                ),
                "unique_sequence_hashes": len(
                    {row["sequence_sha256"] for row in candidates}
                ),
                "unique_monomer_hashes": len(
                    {row["monomer_sha256"] for row in candidates}
                ),
                "unique_job_ids": len({row["job_id"] for row in jobs}),
                "unique_job_hashes": len(
                    {row["job_hash"] for row in jobs}
                ),
                "jobs_by_seed_conformation": {
                    f"seed{seed}_{conformation}": matrix_counts[
                        (str(seed), conformation)
                    ]
                    for seed in SEEDS
                    for conformation in CONFORMATIONS
                },
                "shards": len(shards),
                "jobs_per_shard": [len(shard) for shard in shards],
            },
            "invariants": {
                "release_tsv_fasta_exact_id_sequence_closure": True,
                "release_ids_unique": True,
                "release_sequences_unique": True,
                "shortlist_imgt_cdrs_unique_substrings": True,
                "nbb2_archive_pdbs_match_manifest_sha256": True,
                "pdb_chain_h_sequences_match_release": True,
                "protocol_core_fixed": True,
                "four_seed_cfg_hashes_fixed": True,
                "job_hash_complete_binding_validated": True,
                "shards_exact_one_time_job_hash_closure": shard_receipt[
                    "exact_hash_set_closure"
                ],
                "candidate_job_units_not_split": True,
                "portable_support_required_present": all(
                    any(
                        row["path"] == required
                        for row in portable_support
                    )
                    for required in REQUIRED_PORTABLE_SUPPORT_PATHS
                ),
                "portable_support_files_are_regular_non_symlinks": True,
                "portable_support_sha256": {
                    row["path"]: row["sha256"]
                    for row in portable_support
                },
            },
            "outputs": {
                "candidate_manifest": {
                    "path": candidate_manifest.relative_to(
                        staging_root
                    ).as_posix(),
                    "sha256": sha256_file(candidate_manifest),
                    "rows": len(candidates),
                },
                "job_manifest": {
                    "path": job_manifest.relative_to(
                        staging_root
                    ).as_posix(),
                    "sha256": sha256_file(job_manifest),
                    "rows": len(jobs),
                },
                "shard_receipt": {
                    "path": shard_receipt_path.relative_to(
                        staging_root
                    ).as_posix(),
                    "sha256": sha256_file(shard_receipt_path),
                },
                "ordered_candidate_binding_sha256": sha256_text(
                    "".join(
                        f"{row['release_rank']}\t{row['candidate_id']}\t"
                        f"{row['sequence_sha256']}\t{row['monomer_sha256']}\n"
                        for row in candidates
                    )
                ),
                "ordered_job_hashes_sha256": sha256_text(
                    "".join(f"{row['job_hash']}\n" for row in jobs)
                ),
            },
        }
        receipt_path = staging_root / "HANDOFF_RECEIPT.json"
        write_json(receipt_path, receipt)
        ready = {
            "schema_version": "pvrig.handoff.ready.v1",
            "status": receipt["status"],
            "created_at": created_at,
            "production": production,
            "docking_started": False,
            "candidates": len(candidates),
            "jobs": len(jobs),
            "shards": len(shards),
            "handoff_receipt_sha256": sha256_file(receipt_path),
            "job_manifest_sha256": sha256_file(job_manifest),
            "shard_receipt_sha256": sha256_file(shard_receipt_path),
        }
        write_json(staging_root / "READY.json", ready)
        write_sha256s(staging_root)
        staging_root.replace(output_root)
        return receipt
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tsv", type=Path, required=True)
    parser.add_argument("--release-fasta", type=Path, required=True)
    parser.add_argument("--shortlist-tsv-gz", type=Path, required=True)
    parser.add_argument("--nbb2-manifest-tsv-gz", type=Path, required=True)
    parser.add_argument(
        "--nbb2-archive",
        type=Path,
        action="append",
        required=True,
        help="Repeat exactly eight times, once per NBB2 node tar.gz.",
    )
    parser.add_argument("--template-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--created-at", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_handoff(
        args.release_tsv,
        args.release_fasta,
        args.shortlist_tsv_gz,
        args.nbb2_manifest_tsv_gz,
        args.nbb2_archive,
        args.template_root,
        args.output_root,
        args.created_at,
        production=True,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
