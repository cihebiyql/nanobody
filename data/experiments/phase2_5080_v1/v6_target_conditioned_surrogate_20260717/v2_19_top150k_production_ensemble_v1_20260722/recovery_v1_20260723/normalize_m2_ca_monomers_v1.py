#!/usr/bin/env python3
"""Normalize label-free monomer CA records to contiguous sequence numbering for M2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

AA3 = {
    "ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q","GLU":"E","GLY":"G","HIS":"H","ILE":"I",
    "LEU":"L","LYS":"K","MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W","TYR":"Y","VAL":"V",
}


class NormalizeError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise NormalizeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


@dataclass(frozen=True)
class Job:
    candidate_id: str
    source_path: str
    source_sha256: str
    expected_chain: str
    expected_sequence: str
    relative_path: str
    partial_root: str


def normalize_job(job: Job) -> tuple[str, str, int, str]:
    source = Path(job.source_path)
    require(source.is_file() and not source.is_symlink(), f"source_invalid:{job.candidate_id}")
    require(sha256_file(source) == job.source_sha256, f"source_sha_mismatch:{job.candidate_id}")
    records: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    sequence: list[str] = []
    with source.open("r", encoding="ascii", errors="strict") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
                continue
            require(len(line) >= 66, f"short_ca:{job.candidate_id}:{line_number}")
            chain = line[21:22]
            require(chain == job.expected_chain, f"chain_mismatch:{job.candidate_id}:{line_number}")
            key = (chain, line[22:26], line[26:27])
            require(key not in seen, f"duplicate_ca_residue:{job.candidate_id}:{key}")
            seen.add(key)
            aa = AA3.get(line[17:20].strip().upper())
            require(aa is not None, f"noncanonical_residue:{job.candidate_id}:{line_number}")
            sequence.append(aa)
            index = len(sequence)
            require(index <= 9999, f"residue_index_overflow:{job.candidate_id}")
            normalized = f"{line[:6]}{index:5d}{line[11:21]}{job.expected_chain}{index:4d} {line[27:]}"
            require(normalized[12:16].strip() == "CA" and normalized[26:27] == " ", "normalization_layout_invalid")
            records.append(normalized.rstrip("\r\n") + "\n")
    observed_sequence = "".join(sequence)
    require(observed_sequence == job.expected_sequence, f"sequence_mismatch:{job.candidate_id}")
    require(80 <= len(records) == len(job.expected_sequence), f"residue_count_invalid:{job.candidate_id}")
    payload = ("".join(records) + "TER\nEND\n").encode("ascii")
    destination = Path(job.partial_root) / job.relative_path
    atomic_bytes(destination, payload)
    return job.candidate_id, sha256_bytes(payload), len(records), job.relative_path


def load_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"table_invalid:{path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return fields, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m2-manifest", type=Path, required=True)
    parser.add_argument("--sequence-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    parser.add_argument("--workers", type=int, default=32)
    args = parser.parse_args()
    require(args.workers >= 1 and not args.output_dir.exists() and not args.output_dir.is_symlink(), "output_or_workers_invalid")
    m2_fields, m2_rows = load_table(args.m2_manifest)
    seq_fields, seq_rows = load_table(args.sequence_manifest)
    require(len(m2_rows) == len(seq_rows) == args.expected_rows, "row_count_invalid")
    require({"candidate_id","sequence","sequence_sha256"} <= set(seq_fields), "sequence_columns_missing")
    sequences = {row["candidate_id"]: row for row in seq_rows}
    require(len(sequences) == args.expected_rows, "sequence_candidate_duplicate")
    partial = args.output_dir.with_name(f".{args.output_dir.name}.partial.{os.getpid()}.{uuid.uuid4().hex}")
    partial.mkdir(parents=True)
    try:
        jobs=[]
        for row in m2_rows:
            candidate=row["candidate_id"]; require(candidate in sequences, f"sequence_missing:{candidate}")
            seq=sequences[candidate]["sequence"].strip(); require(sha256_bytes(seq.encode("ascii")) == row["sequence_sha256"] == sequences[candidate]["sequence_sha256"], f"sequence_sha_mismatch:{candidate}")
            relative=f"ca_monomers/{row['sequence_sha256'][:2]}/{candidate}.pdb"
            jobs.append(Job(candidate,row["monomer_path"],row["monomer_sha256"],row["monomer_chain"],seq,relative,str(partial)))
        if args.workers == 1:
            results=[normalize_job(job) for job in jobs]
        else:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                results=list(pool.map(normalize_job,jobs,chunksize=8))
        result_map={candidate:(digest,count,relative) for candidate,digest,count,relative in results}
        require(len(result_map)==args.expected_rows,"result_count_invalid")
        output_rows=[]; inventory=hashlib.sha256()
        for row in m2_rows:
            candidate=row["candidate_id"]; digest,count,relative=result_map[candidate]
            updated=dict(row); updated["monomer_path"]=str(args.output_dir/relative); updated["monomer_sha256"]=digest; updated["monomer_chain"]=row["monomer_chain"]; updated["asset_lane"]=row["asset_lane"]+"_CA_SEQUENCE_RENUMBERED_V1"
            output_rows.append(updated); inventory.update(f"{candidate}\t{relative}\t{digest}\t{count}\n".encode())
        manifest_bytes=io.StringIO(newline=""); writer=csv.DictWriter(manifest_bytes,fieldnames=m2_fields,delimiter="\t",lineterminator="\n"); writer.writeheader(); writer.writerows(output_rows)
        atomic_bytes(partial/"normalized_m2_structure_manifest_v1.tsv",manifest_bytes.getvalue().encode())
        receipt={"schema_version":"pvrig_top150k_m2_ca_sequence_normalization_v1","status":"PASS_M2_CA_SEQUENCE_NORMALIZATION","created_at_utc":datetime.now(timezone.utc).isoformat(),"rows":args.expected_rows,"features_preserved":"CA coordinates, B-factor confidence, residue order, chain, CDR sequence-position ranges","inputs":{"m2_manifest_sha256":sha256_file(args.m2_manifest),"sequence_manifest_sha256":sha256_file(args.sequence_manifest)},"outputs":{"normalized_m2_structure_manifest_v1.tsv":sha256_file(partial/"normalized_m2_structure_manifest_v1.tsv")},"inventory_sha256":inventory.hexdigest(),"invariants":{"sequence_matches_pdb_ca_residues_all_rows":True,"contiguous_residue_numbering_all_rows":True,"blank_insertion_code_all_rows":True,"only_ca_records_emitted":True,"candidate_docking_pose_files_opened":0,"teacher_labels_opened":0}}
        atomic_bytes(partial/"NORMALIZATION_RECEIPT.json",(json.dumps(receipt,indent=2,sort_keys=True)+"\n").encode())
        os.replace(partial,args.output_dir)
    finally:
        if partial.exists(): shutil.rmtree(partial)
    print(json.dumps(receipt,sort_keys=True))


if __name__ == "__main__":
    main()
