#!/usr/bin/env python3
"""Stage hash-closed, label-free NBB2 monomers from batched tar archives.

The input is a gzip TSV containing candidate/sequence/CDR metadata and durable
NBB2 archive/member provenance.  Only an explicit label-free allowlist is read.
Each archive is hashed once per materialization attempt; each selected member is
required to be a regular tar member whose byte count and SHA256 match the input.

The delivery contains two manifests:

* an M2-compatible label-free structure manifest; and
* a relative-path graph-builder manifest containing sequence/CDR annotations.

Candidate Docking poses, Docking scores, geometry labels, binding labels and
experimental outcomes are neither requested nor read.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import stat
import tarfile
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "pvrig_v2_19_top150k_nbb2_archive_staging_v1"
M2_SCHEMA_VERSION = "pvrig_v2_11_canonical10644_label_free_structure_manifest_v1"
READY_STATUS = "PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING"
M2_MANIFEST_NAME = "top150k_m2_structure_manifest_v1.tsv"
GRAPH_MANIFEST_NAME = "top150k_graph_structure_manifest_v1.tsv"
ARCHIVE_AUDIT_NAME = "top150k_archive_audit_v1.tsv"
RECEIPT_NAME = "top150k_nbb2_staging_receipt_v1.json"
CLAIM_BOUNDARY = (
    "Label-free VHH NBB2 monomer structures and sequence/CDR metadata only; no "
    "candidate Docking pose, Docking Gold, scalar geometry label, binding, "
    "affinity, or experimental blocking truth."
)
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
CANDIDATE_RE = re.compile(r"[A-Za-z0-9_.=+@~-]{1,220}")
STANDARD_AA_RE = re.compile(r"[ACDEFGHIKLMNPQRSTVWY]+")


class StagingError(RuntimeError):
    """Fail-closed staging error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StagingError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("ascii"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise StagingError(f"missing_file:{label}:{path}") from error
    require(stat.S_ISREG(metadata.st_mode), f"not_regular_file:{label}:{path}")


def require_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise StagingError(f"missing_directory:{label}:{path}") from error
    require(stat.S_ISDIR(metadata.st_mode), f"not_directory:{label}:{path}")


def require_digest(value: str, label: str) -> str:
    value = value.strip().lower()
    require(DIGEST_RE.fullmatch(value) is not None, f"invalid_sha256:{label}")
    return value


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), f"output_exists:{path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_or_verify(path: Path, payload: bytes) -> str:
    """Publish once, or accept an identical partial-delivery file on resume."""

    if path.exists() or path.is_symlink():
        require_regular_file(path, f"partial_output:{path.name}")
        require(path.read_bytes() == payload, f"partial_output_content_mismatch:{path.name}")
        return "VERIFIED_EXISTING"
    atomic_write(path, payload)
    return "WRITTEN"


def tsv_bytes(rows: Sequence[Mapping[str, str]], fields: Sequence[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def first_present(fieldnames: Sequence[str], aliases: Sequence[str], label: str, *, required: bool = True) -> str | None:
    matches = [field for field in aliases if field in fieldnames]
    if required:
        require(bool(matches), f"input_column_missing:{label}:{','.join(aliases)}")
    require(len(matches) <= 1, f"input_column_ambiguous:{label}:{','.join(matches)}")
    return matches[0] if matches else None


@dataclass(frozen=True)
class InputColumns:
    candidate_id: str
    sequence: str
    sequence_sha256: str
    parent_cluster: str
    cdr1: str
    cdr2: str
    cdr3: str
    archive_path: str
    archive_member: str
    pdb_sha256: str
    pdb_bytes: str
    archive_sha256: str | None

    @classmethod
    def resolve(cls, fieldnames: Sequence[str]) -> "InputColumns":
        return cls(
            candidate_id=first_present(fieldnames, ("candidate_id",), "candidate_id"),
            sequence=first_present(fieldnames, ("sequence",), "sequence"),
            sequence_sha256=first_present(fieldnames, ("sequence_sha256",), "sequence_sha256"),
            parent_cluster=first_present(
                fieldnames, ("parent_framework_cluster", "parent_cluster"), "parent_cluster"
            ),
            cdr1=first_present(fieldnames, ("cdr1_after", "cdr1"), "cdr1"),
            cdr2=first_present(fieldnames, ("cdr2_after", "cdr2"), "cdr2"),
            cdr3=first_present(fieldnames, ("cdr3_after", "cdr3"), "cdr3"),
            archive_path=first_present(
                fieldnames,
                ("nbb2_nbb2_archive_path", "nbb2_archive_path", "archive_path"),
                "archive_path",
            ),
            archive_member=first_present(
                fieldnames,
                ("nbb2_nbb2_archive_member", "nbb2_archive_member", "archive_member"),
                "archive_member",
            ),
            pdb_sha256=first_present(
                fieldnames, ("nbb2_pdb_sha256", "nbb2_nbb2_pdb_sha256", "pdb_sha256"), "pdb_sha256"
            ),
            pdb_bytes=first_present(
                fieldnames, ("nbb2_pdb_bytes", "nbb2_nbb2_pdb_bytes", "pdb_bytes"), "pdb_bytes"
            ),
            archive_sha256=first_present(
                fieldnames,
                ("nbb2_nbb2_archive_sha256", "nbb2_archive_sha256", "archive_sha256"),
                "archive_sha256",
                required=False,
            ),
        )

    @property
    def selected(self) -> tuple[str, ...]:
        values = [
            self.candidate_id, self.sequence, self.sequence_sha256, self.parent_cluster,
            self.cdr1, self.cdr2, self.cdr3, self.archive_path, self.archive_member,
            self.pdb_sha256, self.pdb_bytes,
        ]
        if self.archive_sha256 is not None:
            values.append(self.archive_sha256)
        return tuple(values)


@dataclass(frozen=True)
class CandidateAsset:
    ordinal: int
    candidate_id: str
    sequence: str
    sequence_sha256: str
    parent_cluster: str
    cdr1_range: str
    cdr2_range: str
    cdr3_range: str
    archive_path: str
    archive_member: str
    archive_sha256: str | None
    pdb_sha256: str
    pdb_bytes: int
    monomer_relative_path: str


@dataclass(frozen=True)
class ArchiveJob:
    archive_path: str
    expected_sha256: str | None
    pdb_root: str
    assets: tuple[CandidateAsset, ...]


@dataclass(frozen=True)
class ArchiveResult:
    archive_path: str
    observed_sha256: str
    expected_sha256: str
    expected_sha256_status: str
    members: int
    payload_bytes: int
    extracted: int
    resumed: int


def unique_cdr_ranges(sequence: str, cdrs: Mapping[str, str], candidate_id: str) -> dict[str, str]:
    spans: dict[str, tuple[int, int]] = {}
    for name in ("cdr1", "cdr2", "cdr3"):
        cdr = cdrs[name].strip().upper()
        require(STANDARD_AA_RE.fullmatch(cdr) is not None, f"invalid_{name}:{candidate_id}")
        starts = [index for index in range(len(sequence)) if sequence.startswith(cdr, index)]
        require(len(starts) == 1, f"nonunique_{name}_mapping:{candidate_id}:{len(starts)}")
        spans[name] = (starts[0], starts[0] + len(cdr))
    require(
        spans["cdr1"][1] <= spans["cdr2"][0] and spans["cdr2"][1] <= spans["cdr3"][0],
        f"cdr_order_or_overlap_invalid:{candidate_id}",
    )
    return {name: f"{start + 1}-{stop}" for name, (start, stop) in spans.items()}


def safe_member_name(value: str, candidate_id: str) -> str:
    require("\\" not in value and "\x00" not in value, f"archive_member_unsafe:{candidate_id}")
    member = PurePosixPath(value)
    require(value and not member.is_absolute(), f"archive_member_unsafe:{candidate_id}")
    require(all(part not in {"", ".", ".."} for part in member.parts), f"archive_member_unsafe:{candidate_id}")
    require(member.as_posix() == value, f"archive_member_not_canonical:{candidate_id}")
    return value


def load_archive_digest_table(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    require_regular_file(path, "archive_digest_tsv")
    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = reader.fieldnames or []
        path_field = first_present(fields, ("archive_path", "nbb2_archive_path"), "digest_archive_path")
        sha_field = first_present(fields, ("archive_sha256", "nbb2_archive_sha256"), "digest_archive_sha256")
        for row_number, row in enumerate(reader, start=2):
            archive = str(Path(row[path_field]).resolve())
            digest = require_digest(row[sha_field], f"digest_table_row_{row_number}")
            require(archive not in mapping, f"duplicate_archive_digest:{archive}")
            mapping[archive] = digest
    require(mapping, "archive_digest_tsv_empty")
    return mapping


def projected_input_rows(path: Path) -> tuple[InputColumns, list[dict[str, str]]]:
    require_regular_file(path, "source_tsv_gz")
    require(path.suffix == ".gz", "source_tsv_must_be_gzip")
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            fieldnames = next(reader)
        except StopIteration as error:
            raise StagingError("source_tsv_empty") from error
        require(len(fieldnames) == len(set(fieldnames)), "source_tsv_duplicate_header")
        columns = InputColumns.resolve(fieldnames)
        selected = columns.selected
        indices = {field: fieldnames.index(field) for field in selected}
        rows: list[dict[str, str]] = []
        for line_number, values in enumerate(reader, start=2):
            require(len(values) == len(fieldnames), f"source_tsv_field_count_mismatch:{line_number}")
            rows.append({field: values[index] for field, index in indices.items()})
    require(rows, "source_tsv_no_rows")
    return columns, rows


def load_assets(
    source_tsv: Path,
    *,
    digest_table: Mapping[str, str],
    expected_rows: int,
    require_expected_archive_sha256: bool,
) -> tuple[list[CandidateAsset], dict[str, str | None], InputColumns]:
    columns, rows = projected_input_rows(source_tsv)
    require(len(rows) == expected_rows, f"source_row_count_mismatch:{len(rows)}!={expected_rows}")
    assets: list[CandidateAsset] = []
    candidate_ids: set[str] = set()
    sequence_hashes: set[str] = set()
    archive_members: set[tuple[str, str]] = set()
    archive_expected: dict[str, str | None] = {}
    for ordinal, row in enumerate(rows):
        candidate_id = row[columns.candidate_id].strip()
        require(CANDIDATE_RE.fullmatch(candidate_id) is not None, f"candidate_id_unsafe:{candidate_id}")
        require(candidate_id not in {".", ".."}, f"candidate_id_unsafe:{candidate_id}")
        require(candidate_id not in candidate_ids, f"duplicate_candidate_id:{candidate_id}")
        candidate_ids.add(candidate_id)
        sequence = row[columns.sequence].strip().upper()
        require(STANDARD_AA_RE.fullmatch(sequence) is not None, f"sequence_invalid:{candidate_id}")
        sequence_digest = require_digest(row[columns.sequence_sha256], f"sequence:{candidate_id}")
        require(sha256_text(sequence) == sequence_digest, f"sequence_sha256_mismatch:{candidate_id}")
        require(sequence_digest not in sequence_hashes, f"duplicate_sequence_sha256:{candidate_id}")
        sequence_hashes.add(sequence_digest)
        ranges = unique_cdr_ranges(
            sequence,
            {"cdr1": row[columns.cdr1], "cdr2": row[columns.cdr2], "cdr3": row[columns.cdr3]},
            candidate_id,
        )
        parent = row[columns.parent_cluster].strip()
        require(bool(parent), f"parent_cluster_missing:{candidate_id}")
        archive_path = Path(row[columns.archive_path]).expanduser()
        require(archive_path.is_absolute(), f"archive_path_not_absolute:{candidate_id}")
        require_regular_file(archive_path, f"archive:{candidate_id}")
        resolved_archive = str(archive_path.resolve(strict=True))
        inline_sha = None
        if columns.archive_sha256 is not None and row[columns.archive_sha256].strip():
            inline_sha = require_digest(row[columns.archive_sha256], f"archive:{candidate_id}")
        table_sha = digest_table.get(resolved_archive)
        if inline_sha is not None and table_sha is not None:
            require(inline_sha == table_sha, f"archive_digest_sources_disagree:{resolved_archive}")
        expected_archive_sha = inline_sha or table_sha
        if require_expected_archive_sha256:
            require(expected_archive_sha is not None, f"archive_expected_sha256_missing:{resolved_archive}")
        if resolved_archive in archive_expected:
            require(
                archive_expected[resolved_archive] == expected_archive_sha,
                f"archive_expected_sha256_inconsistent:{resolved_archive}",
            )
        else:
            archive_expected[resolved_archive] = expected_archive_sha
        try:
            pdb_bytes = int(row[columns.pdb_bytes])
        except ValueError as error:
            raise StagingError(f"pdb_bytes_invalid:{candidate_id}") from error
        require(pdb_bytes > 0, f"pdb_bytes_invalid:{candidate_id}")
        member = safe_member_name(row[columns.archive_member].strip(), candidate_id)
        archive_member_key = (resolved_archive, member)
        require(archive_member_key not in archive_members, f"duplicate_archive_member:{resolved_archive}:{member}")
        archive_members.add(archive_member_key)
        relative = Path(sequence_digest[:2]) / f"{candidate_id}.pdb"
        assets.append(CandidateAsset(
            ordinal=ordinal,
            candidate_id=candidate_id,
            sequence=sequence,
            sequence_sha256=sequence_digest,
            parent_cluster=parent,
            cdr1_range=ranges["cdr1"],
            cdr2_range=ranges["cdr2"],
            cdr3_range=ranges["cdr3"],
            archive_path=resolved_archive,
            archive_member=member,
            archive_sha256=expected_archive_sha,
            pdb_sha256=require_digest(row[columns.pdb_sha256], f"pdb:{candidate_id}"),
            pdb_bytes=pdb_bytes,
            monomer_relative_path=relative.as_posix(),
        ))
    return assets, archive_expected, columns


def validate_label_free_pdb(payload: bytes, candidate_id: str) -> str:
    require(b"\x00" not in payload, f"pdb_nul_byte:{candidate_id}")
    try:
        text = payload.decode("ascii", errors="strict")
    except UnicodeDecodeError as error:
        raise StagingError(f"pdb_not_ascii:{candidate_id}") from error
    atom_chains: set[str] = set()
    atom_count = 0
    for line in text.splitlines():
        record = line[:6].strip().upper()
        require(record != "HETATM", f"pdb_hetatm_forbidden:{candidate_id}")
        if record == "ATOM":
            require(len(line) >= 54, f"pdb_atom_line_short:{candidate_id}")
            atom_count += 1
            atom_chains.add(line[21:22].strip() or "_")
    require(atom_count > 0, f"pdb_no_atom_records:{candidate_id}")
    require(len(atom_chains) == 1 and "_" not in atom_chains,
            f"pdb_not_single_named_chain:{candidate_id}:{sorted(atom_chains)}")
    return next(iter(atom_chains))


def validate_existing_pdb(path: Path, asset: CandidateAsset) -> None:
    require_regular_file(path, f"staged_pdb:{asset.candidate_id}")
    payload = path.read_bytes()
    require(len(payload) == asset.pdb_bytes, f"staged_pdb_bytes_mismatch:{asset.candidate_id}")
    require(sha256_bytes(payload) == asset.pdb_sha256, f"staged_pdb_sha256_mismatch:{asset.candidate_id}")
    validate_label_free_pdb(payload, asset.candidate_id)


def safe_tar_member(archive: tarfile.TarFile, asset: CandidateAsset) -> tarfile.TarInfo:
    try:
        member = archive.getmember(asset.archive_member)
    except KeyError as error:
        raise StagingError(f"archive_member_missing:{asset.candidate_id}:{asset.archive_member}") from error
    require(member.isfile(), f"archive_member_not_regular:{asset.candidate_id}")
    require(not member.issym() and not member.islnk(), f"archive_member_link_forbidden:{asset.candidate_id}")
    require(member.name == safe_member_name(member.name, asset.candidate_id), f"archive_member_name_changed:{asset.candidate_id}")
    require(member.size == asset.pdb_bytes, f"archive_member_bytes_mismatch:{asset.candidate_id}")
    return member


def stage_archive(job: ArchiveJob) -> ArchiveResult:
    archive_path = Path(job.archive_path)
    require_regular_file(archive_path, "archive_worker")
    observed_sha = sha256_file(archive_path)
    if job.expected_sha256 is not None:
        require(observed_sha == job.expected_sha256, f"archive_sha256_mismatch:{archive_path}")
        expected_status = "MATCHED_EXPECTED"
        expected_sha = job.expected_sha256
    else:
        expected_status = "OBSERVED_AND_BOUND_NO_UPSTREAM_EXPECTED"
        expected_sha = ""
    pdb_root = Path(job.pdb_root)
    require_directory(pdb_root, "pdb_root_worker")
    extracted = 0
    resumed = 0
    payload_bytes = 0
    with tarfile.open(archive_path, mode="r:*") as archive:
        for asset in job.assets:
            destination = pdb_root / asset.monomer_relative_path
            require(destination.resolve(strict=False).is_relative_to(pdb_root.resolve(strict=True)),
                    f"staging_path_escape:{asset.candidate_id}")
            member = safe_tar_member(archive, asset)
            if destination.exists() or destination.is_symlink():
                validate_existing_pdb(destination, asset)
                resumed += 1
                payload_bytes += asset.pdb_bytes
                continue
            handle = archive.extractfile(member)
            require(handle is not None, f"archive_member_unreadable:{asset.candidate_id}")
            payload = handle.read(asset.pdb_bytes + 1)
            require(len(payload) == asset.pdb_bytes, f"archive_member_read_bytes_mismatch:{asset.candidate_id}")
            require(sha256_bytes(payload) == asset.pdb_sha256, f"archive_member_sha256_mismatch:{asset.candidate_id}")
            validate_label_free_pdb(payload, asset.candidate_id)
            shard = destination.parent
            if shard.exists() or shard.is_symlink():
                require_directory(shard, f"pdb_shard:{asset.candidate_id}")
            else:
                shard.mkdir(parents=True, exist_ok=True)
                require_directory(shard, f"pdb_shard:{asset.candidate_id}")
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
            validate_existing_pdb(destination, asset)
            extracted += 1
            payload_bytes += asset.pdb_bytes
    return ArchiveResult(
        archive_path=str(archive_path),
        observed_sha256=observed_sha,
        expected_sha256=expected_sha,
        expected_sha256_status=expected_status,
        members=len(job.assets),
        payload_bytes=payload_bytes,
        extracted=extracted,
        resumed=resumed,
    )


def output_rows(assets: Sequence[CandidateAsset], pdb_root: Path, source_sha256: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    m2_rows: list[dict[str, str]] = []
    graph_rows: list[dict[str, str]] = []
    for asset in sorted(assets, key=lambda item: item.ordinal):
        monomer = (pdb_root / asset.monomer_relative_path).resolve(strict=True)
        validate_existing_pdb(monomer, asset)
        monomer_chain = validate_label_free_pdb(monomer.read_bytes(), asset.candidate_id)
        m2_rows.append({
            "schema_version": M2_SCHEMA_VERSION,
            "candidate_id": asset.candidate_id,
            "sequence_sha256": asset.sequence_sha256,
            "parent_framework_cluster": asset.parent_cluster,
            "model_split": "production",
            "asset_lane": "TOP150K_NBB2_ARCHIVE_V1",
            "monomer_path": str(monomer),
            "monomer_sha256": asset.pdb_sha256,
            "monomer_chain": monomer_chain,
            "cdr1_range": asset.cdr1_range,
            "cdr2_range": asset.cdr2_range,
            "cdr3_range": asset.cdr3_range,
            "source_manifest_sha256": source_sha256,
            "claim_boundary": CLAIM_BOUNDARY,
        })
        graph_rows.append({
            "candidate_id": asset.candidate_id,
            "sequence": asset.sequence,
            "sequence_sha256": asset.sequence_sha256,
            "parent_framework_cluster": asset.parent_cluster,
            "monomer_relative_path": asset.monomer_relative_path,
            "monomer_sha256": asset.pdb_sha256,
            "source_chain": monomer_chain,
            "cdr1_range": asset.cdr1_range,
            "cdr2_range": asset.cdr2_range,
            "cdr3_range": asset.cdr3_range,
            "claim_boundary": CLAIM_BOUNDARY,
        })
    return m2_rows, graph_rows


def validate_existing_delivery(
    output_dir: Path, source_sha256: str, expected_rows: int, pdb_root: Path
) -> dict[str, Any] | None:
    receipt_path = output_dir / RECEIPT_NAME
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return None
    require_regular_file(receipt_path, "existing_receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("schema_version") == SCHEMA_VERSION, "existing_receipt_schema_invalid")
    require(receipt.get("status") == READY_STATUS, "existing_receipt_status_invalid")
    require(receipt.get("inputs", {}).get("source_tsv_gz_sha256") == source_sha256,
            "existing_receipt_source_sha256_mismatch")
    require(receipt.get("counts", {}).get("candidates") == expected_rows,
            "existing_receipt_candidate_count_mismatch")
    require(receipt.get("pdb_root") == str(pdb_root.resolve(strict=True)), "existing_receipt_pdb_root_mismatch")
    outputs = receipt.get("outputs", {})
    require(set(outputs) == {M2_MANIFEST_NAME, GRAPH_MANIFEST_NAME, ARCHIVE_AUDIT_NAME},
            "existing_receipt_output_set_invalid")
    for name, expected_sha in outputs.items():
        path = output_dir / name
        require_regular_file(path, f"existing_output:{name}")
        require(sha256_file(path) == expected_sha, f"existing_output_sha256_mismatch:{name}")
    return {
        "status": "PASS_EXISTING_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING",
        "rows": expected_rows,
        "receipt_sha256": sha256_file(receipt_path),
    }


def materialize(
    source_tsv: Path,
    pdb_root: Path,
    output_dir: Path,
    *,
    expected_rows: int,
    workers: int,
    archive_digest_tsv: Path | None = None,
    require_expected_archive_sha256: bool = False,
) -> dict[str, Any]:
    require(workers >= 1, "workers_must_be_positive")
    require(expected_rows >= 1, "expected_rows_must_be_positive")
    require_regular_file(source_tsv, "source_tsv_gz")
    source_sha = sha256_file(source_tsv)
    pdb_root.mkdir(parents=True, exist_ok=True)
    require_directory(pdb_root, "pdb_root")
    pdb_root = pdb_root.resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    require_directory(output_dir, "output_dir")
    existing = validate_existing_delivery(output_dir, source_sha, expected_rows, pdb_root)
    if existing is not None:
        return existing

    digest_table = load_archive_digest_table(archive_digest_tsv)
    assets, archive_expected, columns = load_assets(
        source_tsv,
        digest_table=digest_table,
        expected_rows=expected_rows,
        require_expected_archive_sha256=require_expected_archive_sha256,
    )
    grouped: dict[str, list[CandidateAsset]] = defaultdict(list)
    for asset in assets:
        grouped[asset.archive_path].append(asset)
    jobs = [
        ArchiveJob(
            archive_path=archive_path,
            expected_sha256=archive_expected[archive_path],
            pdb_root=str(pdb_root),
            assets=tuple(grouped[archive_path]),
        )
        for archive_path in sorted(grouped)
    ]
    if workers == 1 or len(jobs) == 1:
        results = [stage_archive(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            results = list(pool.map(stage_archive, jobs, chunksize=1))

    m2_rows, graph_rows = output_rows(assets, pdb_root, source_sha)
    m2_fields = tuple(m2_rows[0])
    graph_fields = tuple(graph_rows[0])
    archive_rows = [{
        "archive_path": result.archive_path,
        "observed_sha256": result.observed_sha256,
        "expected_sha256": result.expected_sha256,
        "expected_sha256_status": result.expected_sha256_status,
        "member_count": str(result.members),
        "payload_bytes": str(result.payload_bytes),
    } for result in sorted(results, key=lambda item: item.archive_path)]
    archive_fields = tuple(archive_rows[0])
    publication_states = {
        M2_MANIFEST_NAME: write_or_verify(output_dir / M2_MANIFEST_NAME, tsv_bytes(m2_rows, m2_fields)),
        GRAPH_MANIFEST_NAME: write_or_verify(output_dir / GRAPH_MANIFEST_NAME, tsv_bytes(graph_rows, graph_fields)),
        ARCHIVE_AUDIT_NAME: write_or_verify(output_dir / ARCHIVE_AUDIT_NAME, tsv_bytes(archive_rows, archive_fields)),
    }

    inventory_digest = hashlib.sha256()
    for asset in sorted(assets, key=lambda item: item.candidate_id):
        inventory_digest.update(
            f"{asset.candidate_id}\t{asset.pdb_sha256}\t{asset.pdb_bytes}\t{asset.monomer_relative_path}\n".encode("utf-8")
        )
    outputs = {
        name: sha256_file(output_dir / name)
        for name in (M2_MANIFEST_NAME, GRAPH_MANIFEST_NAME, ARCHIVE_AUDIT_NAME)
    }
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
        "implementation_sha256": sha256_file(Path(__file__)),
        "pdb_root": str(pdb_root),
        "inputs": {
            "source_tsv_gz_path": str(source_tsv.resolve(strict=True)),
            "source_tsv_gz_sha256": source_sha,
            "archive_digest_tsv_sha256": sha256_file(archive_digest_tsv) if archive_digest_tsv else None,
            "projected_columns": list(columns.selected),
        },
        "counts": {
            "candidates": len(assets),
            "unique_candidate_ids": len({asset.candidate_id for asset in assets}),
            "unique_sequence_sha256": len({asset.sequence_sha256 for asset in assets}),
            "parent_clusters": len({asset.parent_cluster for asset in assets}),
            "archives": len(results),
            "archive_hash_computations": len(results),
            "archives_matched_expected_sha256": sum(
                result.expected_sha256_status == "MATCHED_EXPECTED" for result in results
            ),
            "archives_observed_without_upstream_expected": sum(
                result.expected_sha256_status != "MATCHED_EXPECTED" for result in results
            ),
            "pdbs_extracted_this_attempt": sum(result.extracted for result in results),
            "pdbs_resumed_this_attempt": sum(result.resumed for result in results),
            "pdb_bytes": sum(asset.pdb_bytes for asset in assets),
            "parent_cluster_rows": dict(sorted(Counter(asset.parent_cluster for asset in assets).items())),
        },
        "outputs": outputs,
        "publication_states": publication_states,
        "pdb_inventory_sha256": inventory_digest.hexdigest(),
        "invariants": {
            "gzip_input_projected_to_label_free_allowlist": True,
            "archive_sha256_computed_once_per_archive_this_attempt": True,
            "archive_expected_sha256_required": require_expected_archive_sha256,
            "tar_extractall_used": False,
            "tar_regular_member_only": True,
            "tar_member_path_escape_rejected": True,
            "tar_links_rejected": True,
            "pdb_bytes_recomputed": True,
            "pdb_sha256_recomputed": True,
            "existing_pdb_resume_requires_exact_bytes_and_sha256": True,
            "single_named_chain_atom_records_required": True,
            "candidate_docking_pose_files_opened": 0,
            "geometry_label_columns_read": 0,
        },
    }
    atomic_write(output_dir / RECEIPT_NAME, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return {
        "status": READY_STATUS,
        "rows": len(assets),
        "archives": len(results),
        "extracted": sum(result.extracted for result in results),
        "resumed": sum(result.resumed for result in results),
        "m2_manifest_sha256": outputs[M2_MANIFEST_NAME],
        "graph_manifest_sha256": outputs[GRAPH_MANIFEST_NAME],
        "receipt_sha256": sha256_file(output_dir / RECEIPT_NAME),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tsv-gz", type=Path, required=True)
    parser.add_argument("--pdb-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, default=150000)
    parser.add_argument("--workers", type=int, default=max(1, min(32, os.cpu_count() or 1)))
    parser.add_argument("--archive-digest-tsv", type=Path)
    parser.add_argument("--require-expected-archive-sha256", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = materialize(
        args.source_tsv_gz,
        args.pdb_root,
        args.output_dir,
        expected_rows=args.expected_rows,
        workers=args.workers,
        archive_digest_tsv=args.archive_digest_tsv,
        require_expected_archive_sha256=args.require_expected_archive_sha256,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
