#!/usr/bin/env python3
"""Split terminal MPNN Full-QC passes into exact, disjoint Node1/Node23 lanes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


CLAIM = (
    "Deterministic compute-lane split for monomer generation only; not binding, "
    "affinity, competition, experimental blocking, or Docking Gold."
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def run(qc_root: Path, output_root: Path) -> dict[str, object]:
    complete_path = qc_root / "status/runner.complete.json"
    manifest_path = qc_root / "outputs/research_ready_candidates.tsv"
    if not complete_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("qc_terminal_artifacts_missing")
    complete = json.loads(complete_path.read_text())
    if complete.get("status") != "PASS_MPNN1008_FULL_QC_COMPLETE":
        raise RuntimeError(f"unexpected_qc_status:{complete.get('status')}")
    expected = int(complete["full_hard_pass"])
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    required = {"candidate_id", "sequence", "sequence_sha256", "research_pool_state"}
    if not required <= set(fields):
        raise RuntimeError(f"manifest_fields_missing:{sorted(required - set(fields))}")
    if len(rows) != expected or len({row["candidate_id"] for row in rows}) != expected:
        raise RuntimeError("manifest_count_or_id_closure_failed")
    if len({row["sequence_sha256"] for row in rows}) != expected:
        raise RuntimeError("sequence_hash_not_unique")
    for row in rows:
        if row["research_pool_state"] != "RESEARCH_READY":
            raise RuntimeError(f"candidate_not_research_ready:{row['candidate_id']}")
        if hashlib.sha256(row["sequence"].encode()).hexdigest() != row["sequence_sha256"]:
            raise RuntimeError(f"sequence_hash_mismatch:{row['candidate_id']}")
    rows.sort(key=lambda row: (row["sequence_sha256"], row["candidate_id"]))
    lanes = {"node1": [], "node23": []}
    for index, row in enumerate(rows):
        lane = "node1" if index % 2 == 0 else "node23"
        selected = dict(row)
        selected["compute_lane"] = lane.upper()
        lanes[lane].append(selected)
    output_fields = fields + (["compute_lane"] if "compute_lane" not in fields else [])
    outputs: dict[str, dict[str, object]] = {}
    for lane, lane_rows in lanes.items():
        path = output_root / f"{lane}_candidates.tsv"
        write_tsv(path, lane_rows, output_fields)
        outputs[lane] = {"count": len(lane_rows), "sha256": sha256(path), "path": str(path)}
    if sum(int(item["count"]) for item in outputs.values()) != expected:
        raise RuntimeError("split_count_closure_failed")
    if {row["sequence_sha256"] for row in lanes["node1"]} & {row["sequence_sha256"] for row in lanes["node23"]}:
        raise RuntimeError("split_overlap")
    receipt = {
        "schema_version": "pvrig_v4_i_mpnn1008_monomer_split_v1",
        "status": "PASS_DISJOINT_MONOMER_SPLIT",
        "input_count": expected,
        "input_manifest_sha256": sha256(manifest_path),
        "lanes": outputs,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": CLAIM,
    }
    atomic_json(output_root / "SPLIT_RECEIPT.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qc-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.qc_root, args.output_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
