#!/usr/bin/env python3
"""Create a train9849-only manifest view over the immutable full10644 graph arrays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Sequence


class GraphViewError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GraphViewError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    require(path.is_file() and not path.is_symlink(), f"tsv_invalid:{path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields, rows = list(reader.fieldnames or ()), [dict(row) for row in reader]
    require(fields and rows, f"tsv_empty:{path}")
    return fields, rows


def write_tsv(path: Path, fields: Sequence[str], rows: Sequence[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def materialize(teacher: Path, source_graph_dir: Path, output_root: Path) -> dict:
    require(not output_root.exists(), f"output_exists:{output_root}")
    teacher_fields, teacher_rows = read_tsv(teacher)
    require({"candidate_id", "sequence_sha256"} <= set(teacher_fields), "teacher_fields")
    require(len(teacher_rows) == 9849, f"teacher_rows:{len(teacher_rows)}")
    teacher_ids = [row["candidate_id"] for row in teacher_rows]
    require(len(set(teacher_ids)) == len(teacher_ids), "teacher_duplicate")

    source_cache = source_graph_dir / "graph_cache_v2.npz"
    source_manifest = source_graph_dir / "graph_manifest_v2.tsv"
    source_receipt = source_graph_dir / "graph_cache_receipt_v2.json"
    source_wrapper_root = source_graph_dir.parent
    source_prepared = source_wrapper_root / "canonical10644_label_free_graph_input_manifest_v1.tsv"
    for path in (source_cache, source_manifest, source_receipt, source_prepared):
        require(path.is_file() and not path.is_symlink(), f"source_invalid:{path}")

    manifest_fields, manifest_rows = read_tsv(source_manifest)
    prepared_fields, prepared_rows = read_tsv(source_prepared)
    manifest_by_id = {row["entity_id"]: row for row in manifest_rows}
    prepared_by_id = {row["candidate_id"]: row for row in prepared_rows}
    require(len(manifest_by_id) == len(manifest_rows) == 10644, "source_manifest_closure")
    require(len(prepared_by_id) == len(prepared_rows) == 10644, "source_prepared_closure")
    require(set(teacher_ids) <= set(manifest_by_id) and set(teacher_ids) <= set(prepared_by_id), "teacher_graph_missing")
    for row in teacher_rows:
        candidate, sequence_sha = row["candidate_id"], row["sequence_sha256"]
        require(manifest_by_id[candidate]["sequence_sha256"] == sequence_sha, f"manifest_sequence:{candidate}")
        require(prepared_by_id[candidate]["sequence_sha256"] == sequence_sha, f"prepared_sequence:{candidate}")

    graph_dir = output_root / "graph_cache"
    graph_dir.mkdir(parents=True)
    cache_view = graph_dir / source_cache.name
    require(source_cache.stat().st_dev == graph_dir.stat().st_dev, "hardlink_cross_device")
    os.link(source_cache, cache_view)
    require(cache_view.stat().st_ino == source_cache.stat().st_ino, "hardlink_inode_mismatch")
    manifest_view = graph_dir / source_manifest.name
    write_tsv(manifest_view, manifest_fields, [manifest_by_id[candidate] for candidate in teacher_ids])
    prepared_view = output_root / source_prepared.name
    write_tsv(prepared_view, prepared_fields, [prepared_by_id[candidate] for candidate in teacher_ids])

    source_receipt_payload = json.loads(source_receipt.read_text(encoding="utf-8"))
    edge_dim = int((source_receipt_payload.get("counts") or {})["edge_feature_dim"])
    receipt = {
        "schema_version": "pvrig_v2_12_train9849_graph_manifest_view_v1",
        "status": "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE",
        "counts": {"entities": 9849, "backing_entities": 10644, "unused_backing_entities": 795, "edge_feature_dim": edge_dim},
        "outputs": {cache_view.name: sha256_file(cache_view), manifest_view.name: sha256_file(manifest_view)},
        "storage": "HARDLINK_IMMUTABLE_FULL10644_ARRAYS_WITH_TRAIN9849_ONLY_MANIFEST",
        "label_access": {"open_development_labels": 0, "frozen_test_labels": 0},
    }
    receipt_path = graph_dir / source_receipt.name
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    prepare_receipt = {"schema_version": "pvrig_v2_12_train9849_graph_prepare_receipt_v1", "outputs": {prepared_view.name: sha256_file(prepared_view)}}
    (output_root / "PREPARE_RECEIPT.json").write_text(json.dumps(prepare_receipt, indent=2, sort_keys=True) + "\n")
    wrapper = {
        "schema_version": "pvrig_v2_12_train9849_graph_wrapper_v1",
        "status": "PASS_CANONICAL10644_LABEL_FREE_GRAPH_MATERIALIZED",
        "outputs": {
            cache_view.name: sha256_file(cache_view),
            manifest_view.name: sha256_file(manifest_view),
            receipt_path.name: sha256_file(receipt_path),
        },
        "view_rows": 9849,
        "unused_backing_entities": 795,
    }
    (output_root / "MATERIALIZATION_RECEIPT.json").write_text(json.dumps(wrapper, indent=2, sort_keys=True) + "\n")
    terminal = {
        "schema_version": "pvrig_v2_12_train9849_graph_view_terminal_v1",
        "status": "PASS_TRAIN9849_LABEL_FREE_GRAPH_VIEW",
        "teacher_sha256": sha256_file(teacher),
        "source_graph_cache_sha256": sha256_file(source_cache),
        "source_graph_manifest_sha256": sha256_file(source_manifest),
        "outputs": {
            str(path.relative_to(output_root)): sha256_file(path)
            for path in (cache_view, manifest_view, receipt_path, prepared_view, output_root / "PREPARE_RECEIPT.json", output_root / "MATERIALIZATION_RECEIPT.json")
        },
        "inode_audit": {"source": source_cache.stat().st_ino, "view": cache_view.stat().st_ino, "same_inode": True},
        "input_access": {"open_development_labels": 0, "frozen_test_labels": 0},
    }
    (output_root / "GRAPH_VIEW_TERMINAL.json").write_text(json.dumps(terminal, indent=2, sort_keys=True) + "\n")
    return terminal


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--source-graph-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = materialize(args.teacher, args.source_graph_dir, args.output_root)
    print(json.dumps({"status": result["status"], "outputs": len(result["outputs"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
