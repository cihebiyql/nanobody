#!/usr/bin/env python3
"""QC fixed-pose CPU proposals and freeze an exact one-million sequence pool."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import tarfile
from collections import Counter, defaultdict, deque
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("cpu_generator", HERE / "generate_local_cpu_routes.py")
GEN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GEN)

UNIFIED_FIELDS = [
    "candidate_id", "sequence", "sequence_sha256", "route_id", "generator",
    "generation_batch", "parent_id", "parent_cluster", "source_candidate_id",
    "target_patch", "design_mode", "designed_regions", "fast_qc_status",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_positive_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}; name = ""; chunks: list[str] = []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            if name: records[name] = "".join(chunks)
            name = line[1:].split()[0]; chunks = []
        else:
            chunks.append(line.strip())
    if name: records[name] = "".join(chunks)
    return records


def tsv_rows(path: Path):
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle, delimiter="\t")


def archive_rows(sync_root: Path):
    archives = sorted(sync_root.glob("node_*/node_*_sequence_outputs.tar.gz"))
    if len(archives) != 8:
        raise ValueError(f"expected 8 node archives, found {len(archives)}")
    for archive in archives:
        with tarfile.open(archive, "r:gz") as tar:
            members = sorted(
                (member for member in tar.getmembers() if member.name.endswith(".tsv.gz")),
                key=lambda member: member.name,
            )
            if len(members) != 64:
                raise ValueError(f"{archive}: expected 64 worker outputs, found {len(members)}")
            for member in members:
                raw = tar.extractfile(member)
                if raw is None: raise ValueError(f"cannot extract {member.name}")
                with gzip.GzipFile(fileobj=raw) as compressed:
                    with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                        yield from csv.DictReader(text, delimiter="\t")


def write_row(writer: csv.DictWriter, row: dict[str, str], fixed: bool = False) -> None:
    if fixed:
        writer.writerow({
            "candidate_id": row["candidate_id"], "sequence": row["sequence"],
            "sequence_sha256": row["sequence_sha256"], "route_id": "fixed_pose_proteinmpnn_cpu",
            "generator": row["design_method"], "generation_batch": "pvrig_1m_cpu_fixed_pose500k_raw_v4_20260722",
            "parent_id": row["source_candidate_id"], "parent_cluster": "",
            "source_candidate_id": row["source_candidate_id"], "target_patch": row["target_patch"],
            "design_mode": row["design_mode"], "designed_regions": row["designed_regions"],
            "fast_qc_status": "PASS",
        })
    else:
        writer.writerow({
            "candidate_id": row["candidate_id"], "sequence": row["sequence"],
            "sequence_sha256": row["sequence_sha256"], "route_id": row.get("route_id", ""),
            "generator": row.get("generator", ""), "generation_batch": row.get("generation_batch", ""),
            "parent_id": row.get("parent_id", ""), "parent_cluster": row.get("parent_cluster", ""),
            "source_candidate_id": "", "target_patch": row.get("target_patch_assignment", ""),
            "design_mode": row.get("design_mode", ""), "designed_regions": row.get("designed_regions", ""),
            "fast_qc_status": row.get("fast_qc_status", "PASS"),
        })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync-root", type=Path, required=True)
    parser.add_argument("--existing", type=Path, action="append", required=True)
    parser.add_argument("--positive-cdr", type=Path, required=True)
    parser.add_argument("--positive-fasta", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-new", type=int, default=300_000)
    args = parser.parse_args()
    if args.output_dir.exists(): raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)

    positive_rows = list(csv.DictReader(args.positive_cdr.open(), delimiter="\t"))
    positives = {row["record_id"]: {k: row[k] for k in ("cdr1", "cdr2", "cdr3")} for row in positive_rows}
    parent_sequences = read_positive_fasta(args.positive_fasta)
    existing_sequences: set[str] = set(); existing_ids: set[str] = set(); existing_count = 0
    for path in args.existing:
        for row in tsv_rows(path):
            if row["sequence"] in existing_sequences: raise ValueError(f"duplicate existing sequence: {path}")
            if row["candidate_id"] in existing_ids: raise ValueError(f"duplicate existing ID: {path}")
            existing_sequences.add(row["sequence"]); existing_ids.add(row["candidate_id"]); existing_count += 1
    if existing_count != 700_000: raise ValueError(f"expected 700000 existing records, found {existing_count}")

    raw_path = args.output_dir / "fixed_pose_cpu_raw_qc.tsv.gz"
    raw_fields = None; raw_count = 0; pass_count = 0; overlap_count = 0
    reasons: Counter[str] = Counter(); buckets: dict[tuple[str, str], deque[dict[str, str]]] = defaultdict(deque)
    seen_new: set[str] = set()
    with gzip.open(raw_path, "wt", newline="", encoding="utf-8", compresslevel=1) as out:
        writer = None
        for row in archive_rows(args.sync_root):
            raw_count += 1
            qc = GEN.fast_qc(
                row["sequence"], {k: row[k] for k in ("cdr1", "cdr2", "cdr3")},
                parent_sequences[row["source_candidate_id"]], positives,
            )
            row.update(qc)
            row["overlap_existing_cpu700k"] = "true" if row["sequence"] in existing_sequences else "false"
            row["exact_duplicate_new"] = "true" if row["sequence"] in seen_new else "false"
            if writer is None:
                raw_fields = list(row); writer = csv.DictWriter(out, fieldnames=raw_fields, delimiter="\t", lineterminator="\n"); writer.writeheader()
            writer.writerow(row)
            for reason in qc["fast_qc_reasons"].split("|"):
                if reason: reasons[reason] += 1
            if row["overlap_existing_cpu700k"] == "true": overlap_count += 1
            if qc["fast_qc_status"] == "PASS" and row["sequence"] not in existing_sequences and row["sequence"] not in seen_new:
                buckets[(row["source_candidate_id"], row["temperature"])].append(dict(row)); pass_count += 1
                seen_new.add(row["sequence"])
    if raw_count != 480_000: raise ValueError(f"expected 480000 raw records, found {raw_count}")

    selected: list[dict[str, str]] = []
    keys = sorted(buckets)
    while len(selected) < args.target_new:
        gained = 0
        for key in keys:
            if buckets[key]:
                selected.append(buckets[key].popleft()); gained += 1
                if len(selected) == args.target_new: break
        if gained == 0: break
    if len(selected) != args.target_new:
        raise ValueError(f"only {len(selected)} exact-unique fast-QC new records available")

    selected_path = args.output_dir / "fixed_pose_cpu_selected300k.tsv.gz"
    with gzip.open(selected_path, "wt", newline="", encoding="utf-8", compresslevel=1) as handle:
        writer = csv.DictWriter(handle, fieldnames=raw_fields or [], delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(selected)
    fasta_path = args.output_dir / "screening_pool_exact1m.fasta.gz"
    unified_path = args.output_dir / "screening_pool_exact1m.tsv.gz"
    final_sequences: set[str] = set(); final_ids: set[str] = set(); final_count = 0
    with gzip.open(unified_path, "wt", newline="", encoding="utf-8", compresslevel=1) as table, gzip.open(fasta_path, "wt", encoding="utf-8", compresslevel=1) as fasta:
        writer = csv.DictWriter(table, fieldnames=UNIFIED_FIELDS, delimiter="\t", lineterminator="\n"); writer.writeheader()
        for path in args.existing:
            for row in tsv_rows(path):
                write_row(writer, row); fasta.write(f">{row['candidate_id']}\n{row['sequence']}\n")
                final_sequences.add(row["sequence"]); final_ids.add(row["candidate_id"]); final_count += 1
        for row in selected:
            if row["sequence"] in final_sequences or row["candidate_id"] in final_ids: raise ValueError("final merge duplicate")
            write_row(writer, row, fixed=True); fasta.write(f">{row['candidate_id']}\n{row['sequence']}\n")
            final_sequences.add(row["sequence"]); final_ids.add(row["candidate_id"]); final_count += 1
    if final_count != 1_000_000 or len(final_sequences) != final_count or len(final_ids) != final_count:
        raise ValueError("final one-million closure failed")
    outputs = [raw_path, selected_path, unified_path, fasta_path]
    receipt = {
        "status": "EXACT_1M_SEQUENCE_SCREENING_POOL_READY", "existing_cpu_records": existing_count,
        "fixed_pose_raw_records": raw_count, "fixed_pose_exact_unique_fast_qc_nonoverlap": pass_count,
        "fixed_pose_selected_records": len(selected), "overlap_existing_cpu700k": overlap_count,
        "final_records": final_count, "final_exact_unique_sequences": len(final_sequences),
        "final_exact_unique_candidate_ids": len(final_ids), "top_failure_reasons": reasons.most_common(20),
        "outputs": {p.name: sha256_file(p) for p in outputs},
        "scientific_boundary": "one-million sequence proposal pool for downstream screening; not structure-complete, binding, affinity, docking, or blocking evidence",
    }
    (args.output_dir / "READY.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
