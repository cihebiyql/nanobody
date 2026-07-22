#!/usr/bin/env python3
"""Merge the frozen 50k selection, NBB2 structure QC and TNP metrics."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
import time


def opener(path: Path, mode: str):
    return gzip.open(path, mode, newline="") if path.suffix == ".gz" else path.open(mode, newline="")


def load_by_id(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    with opener(path, "rt") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = {}
        for row in reader:
            cid = row["candidate_id"]
            if cid in rows:
                raise ValueError(f"duplicate candidate_id in {path}: {cid}")
            rows[cid] = row
    return fields, rows


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--structure", required=True, type=Path)
    parser.add_argument("--tnp", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    sf, selection = load_by_id(args.selection)
    nf, structure = load_by_id(args.structure)
    tf, tnp = load_by_id(args.tnp)
    if not (set(selection) == set(structure) == set(tnp)):
        raise SystemExit(
            f"ID mismatch selection={len(selection)} structure={len(structure)} tnp={len(tnp)}"
        )

    structure_fields = [field for field in nf if field != "candidate_id"]
    tnp_fields = [field for field in tf if field != "candidate_id"]
    extra_fields = [f"nbb2_{field}" for field in structure_fields]
    extra_fields += ["nbb2_archive", "nbb2_archive_member"]
    extra_fields += [f"tnp_{field}" for field in tnp_fields]
    output_fields = sf + extra_fields

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "prestructure50000_multimetric.tsv.gz"
    nbb2_counts: Counter[str] = Counter()
    tnp_counts: Counter[str] = Counter()
    red_counts: Counter[str] = Counter()
    with gzip.open(output, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for cid, row in selection.items():
            nrow = structure[cid]
            trow = tnp[cid]
            merged = dict(row)
            merged.update({f"nbb2_{key}": nrow[key] for key in structure_fields})
            node = nrow.get("original_node", "")
            success = nrow["status"] in {"SUCCESS", "SUCCESS_RECOVERED"}
            merged["nbb2_archive"] = f"node_{node}.tar.gz" if success else ""
            merged["nbb2_archive_member"] = (
                f"node_{node}/raw/worker_{int(nrow['worker_id']):02d}/{cid}.pdb" if success else ""
            )
            merged.update({f"tnp_{key}": trow[key] for key in tnp_fields})
            writer.writerow(merged)
            nbb2_counts[nrow["status"]] += 1
            tnp_counts[trow["status"]] += 1
            red_counts[trow.get("red_flag_count", "NA")] += 1

    payload = {
        "status": "READY_WITH_TECHNICAL_NA" if tnp_counts.get("TECHNICAL_NA", 0) else "READY",
        "records": len(selection),
        "id_set_exact_match": True,
        "nbb2_status_counts": dict(sorted(nbb2_counts.items())),
        "tnp_status_counts": dict(sorted(tnp_counts.items())),
        "tnp_red_flag_count_distribution": dict(sorted(red_counts.items())),
        "output": output.name,
        "sha256": sha256(output),
        "scientific_boundaries": {
            "nbb2": "VHH monomer geometry prediction; not binding, affinity, docking, or blocking evidence",
            "tnp": "structure developability proxy; not measured expression or purity",
            "binding_priors": "weak binding priors; not Kd, IC50, or blocking evidence",
        },
        "created_epoch": time.time(),
    }
    (args.output_dir / "READY.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "SHA256SUMS").write_text(f"{payload['sha256']}  {output.name}\n")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
