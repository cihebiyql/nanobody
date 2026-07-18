#!/usr/bin/env python3
"""Materialize the exact supervised1507 label-free VHH monomer graph cache."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import pathlib
import shutil
import tarfile
import tempfile
from collections import Counter
from typing import Any, Mapping, Sequence

from build_residue_graph_cache_v2 import (
    CACHE_NAME,
    MANIFEST_NAME,
    RECEIPT_NAME,
    GraphBuildConfig,
    GraphCacheError,
    ResidueGraph,
    build_graph_from_pdb,
    materialize_graph_cache,
    sha256_file,
)


SCHEMA_VERSION = "pvrig_v6_residue_v2_supervised1507_graph_inputs"
CLOSURE_NAME = "graph_input_closure_v2.tsv"
MATERIALIZATION_RECEIPT = "materialization_receipt_v2.json"
SHA256SUMS_NAME = "SHA256SUMS"
SOURCE_V4D = "V4D_OPEN_MULTI_SEED"
SOURCE_V4H = "V4H_STAGE1_SEED917"
EXPECTED_SOURCE_COUNTS = {SOURCE_V4D: 226, SOURCE_V4H: 1281}
EXPECTED_PARENT_COUNTS = {SOURCE_V4D: 20, SOURCE_V4H: 11}
V4D_MANIFEST_MEMBER = "outputs/open258_structure_manifest_v1.tsv"


class GraphInputMaterializationError(RuntimeError):
    """Fail-closed supervised graph-input error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GraphInputMaterializationError(message)


def _read_tsv(path: pathlib.Path) -> list[dict[str, str]]:
    require(path.exists() and path.is_file() and not path.is_symlink(), f"tsv_invalid:{path}")
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, f"tsv_header_missing:{path}")
        return list(reader)


def derive_cdr_region_indices(sequence: str, cdr1: str, cdr2: str, cdr3: str) -> tuple[list[int], dict[str, str]]:
    """Map each CDR only when its sequence is a unique ordered substring."""

    sequence = sequence.strip().upper()
    cdrs = (("cdr1", cdr1.strip().upper(), 1), ("cdr2", cdr2.strip().upper(), 2), ("cdr3", cdr3.strip().upper(), 3))
    regions = [0] * len(sequence)
    ranges: dict[str, str] = {}
    previous_end = -1
    for name, cdr, region in cdrs:
        require(cdr, f"{name}_empty")
        require(sequence.count(cdr) == 1, f"{name}_not_unique_substring")
        start = sequence.index(cdr)
        end = start + len(cdr)
        require(start >= previous_end, f"cdr_order_or_overlap_invalid:{name}")
        for index in range(start, end):
            require(regions[index] == 0, f"cdr_overlap:{name}:{index + 1}")
            regions[index] = region
        ranges[f"{name}_range"] = f"{start + 1}-{end}"
        previous_end = end
    return regions, ranges


def _validate_training_rows(
    rows: Sequence[Mapping[str, str]],
    expected_source_counts: Mapping[str, int],
    expected_parent_counts: Mapping[str, int],
) -> dict[str, dict[str, str]]:
    required = {
        "candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster",
        "teacher_source", "monomer_sha256", "cdr1", "cdr2", "cdr3",
    }
    require(rows, "training_table_empty")
    require(required <= set(rows[0]), f"training_fields_missing:{sorted(required - set(rows[0]))}")
    candidates: dict[str, dict[str, str]] = {}
    source_counts: Counter[str] = Counter()
    source_parents: dict[str, set[str]] = {source: set() for source in expected_source_counts}
    for raw in rows:
        row = dict(raw)
        candidate = row["candidate_id"]
        require(candidate and candidate not in candidates, f"duplicate_training_candidate:{candidate}")
        source = row["teacher_source"]
        require(source in expected_source_counts, f"forbidden_training_source:{source}")
        sequence = row["sequence"].strip().upper()
        require(hashlib.sha256(sequence.encode("ascii")).hexdigest() == row["sequence_sha256"], f"training_sequence_hash_mismatch:{candidate}")
        require(len(row["monomer_sha256"]) == 64, f"training_monomer_hash_invalid:{candidate}")
        derive_cdr_region_indices(sequence, row["cdr1"], row["cdr2"], row["cdr3"])
        candidates[candidate] = row
        source_counts[source] += 1
        source_parents[source].add(row["parent_framework_cluster"])
    require(dict(source_counts) == dict(expected_source_counts), f"training_source_counts_invalid:{dict(source_counts)}")
    observed_parent_counts = {source: len(parents) for source, parents in source_parents.items()}
    require(observed_parent_counts == dict(expected_parent_counts), f"training_parent_counts_invalid:{observed_parent_counts}")
    require(source_parents[SOURCE_V4D].isdisjoint(source_parents[SOURCE_V4H]), "parent_cluster_cross_source_overlap")
    return candidates


def _read_v4d_archive_manifest(archive: tarfile.TarFile) -> list[dict[str, str]]:
    try:
        member = archive.getmember(V4D_MANIFEST_MEMBER)
    except KeyError as error:
        raise GraphInputMaterializationError("v4d_archive_manifest_missing") from error
    require(member.isfile() and not member.issym() and not member.islnk(), "v4d_archive_manifest_not_regular")
    extracted = archive.extractfile(member)
    require(extracted is not None, "v4d_archive_manifest_unreadable")
    with io.TextIOWrapper(extracted, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, "v4d_archive_manifest_header_missing")
        return list(reader)


def _safe_v4d_pdb_bytes(archive: tarfile.TarFile, member_name: str) -> bytes:
    relative = pathlib.PurePosixPath(member_name)
    require(not relative.is_absolute() and ".." not in relative.parts, f"v4d_member_path_unsafe:{member_name}")
    require(relative.suffix.lower() == ".pdb", f"v4d_member_not_pdb:{member_name}")
    require(not any(token in part.lower() for part in relative.parts for token in ("docking", "haddock", "pose", "complex")), f"v4d_member_forbidden_path:{member_name}")
    try:
        member = archive.getmember(member_name)
    except KeyError as error:
        raise GraphInputMaterializationError(f"v4d_member_missing:{member_name}") from error
    require(member.isfile() and not member.issym() and not member.islnk(), f"v4d_member_not_regular:{member_name}")
    handle = archive.extractfile(member)
    require(handle is not None, f"v4d_member_unreadable:{member_name}")
    return handle.read()


def _v4h_graphs(
    training: Mapping[str, Mapping[str, str]],
    manifest_path: pathlib.Path,
    structure_root: pathlib.Path,
    config: GraphBuildConfig,
) -> tuple[list[ResidueGraph], list[dict[str, str]]]:
    rows = _read_tsv(manifest_path)
    by_candidate: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate = row.get("candidate_id", "")
        require(candidate and candidate not in by_candidate, f"duplicate_v4h_manifest_candidate:{candidate}")
        by_candidate[candidate] = row
    expected = {candidate for candidate, row in training.items() if row["teacher_source"] == SOURCE_V4H}
    require(expected <= set(by_candidate), f"v4h_manifest_missing_candidates:{len(expected - set(by_candidate))}")
    root = structure_root.resolve(strict=True)
    graphs: list[ResidueGraph] = []
    closure: list[dict[str, str]] = []
    for candidate in sorted(expected):
        train = training[candidate]
        source = by_candidate[candidate]
        require(source["sequence"] == train["sequence"], f"v4h_sequence_mismatch:{candidate}")
        require(source["sequence_sha256"] == train["sequence_sha256"], f"v4h_sequence_hash_mismatch:{candidate}")
        require(source["parent_framework_cluster"] == train["parent_framework_cluster"], f"v4h_parent_mismatch:{candidate}")
        require(source["monomer_sha256"] == train["monomer_sha256"], f"v4h_monomer_hash_mismatch:{candidate}")
        require("label-free" in source["claim_boundary"].lower(), f"v4h_not_label_free:{candidate}")
        relative = pathlib.Path(source["monomer_relative_path"])
        require(not relative.is_absolute() and ".." not in relative.parts, f"v4h_path_unsafe:{candidate}")
        pdb = (root / relative).resolve(strict=True)
        require(pdb.is_relative_to(root), f"v4h_path_escape:{candidate}")
        regions, ranges = derive_cdr_region_indices(train["sequence"], train["cdr1"], train["cdr2"], train["cdr3"])
        graph = build_graph_from_pdb(
            entity_id=candidate, sequence=train["sequence"], sequence_digest=train["sequence_sha256"],
            monomer_path=pdb, region_index=regions, config=config,
            expected_chain=source["source_chain"], expected_monomer_sha256=train["monomer_sha256"],
        )
        graphs.append(graph)
        closure.append(_closure_row(train, graph, ranges, "V4H_DIRECT_LABEL_FREE_BUNDLE"))
    return graphs, closure


def _v4d_graphs(
    training: Mapping[str, Mapping[str, str]],
    archive_path: pathlib.Path,
    config: GraphBuildConfig,
) -> tuple[list[ResidueGraph], list[dict[str, str]]]:
    require(archive_path.exists() and archive_path.is_file() and not archive_path.is_symlink(), "v4d_archive_invalid")
    expected = {candidate for candidate, row in training.items() if row["teacher_source"] == SOURCE_V4D}
    graphs: list[ResidueGraph] = []
    closure: list[dict[str, str]] = []
    with tarfile.open(archive_path, "r:gz") as archive, tempfile.TemporaryDirectory(prefix="v4d_label_free_") as temporary:
        rows = _read_v4d_archive_manifest(archive)
        open_train_rows = [row for row in rows if row.get("model_split") == "OPEN_TRAIN"]
        require(len(open_train_rows) == len(expected), f"v4d_open_train_count_mismatch:{len(open_train_rows)}")
        by_candidate: dict[str, dict[str, str]] = {}
        for row in open_train_rows:
            candidate = row["candidate_id"]
            require(candidate not in by_candidate, f"duplicate_v4d_manifest_candidate:{candidate}")
            by_candidate[candidate] = row
        require(set(by_candidate) == expected, f"v4d_open_train_candidate_set_mismatch:{len(set(by_candidate) ^ expected)}")
        temp_root = pathlib.Path(temporary)
        for candidate in sorted(expected):
            train = training[candidate]
            source = by_candidate[candidate]
            require(source["sequence_sha256"] == train["sequence_sha256"], f"v4d_sequence_hash_mismatch:{candidate}")
            require(source["parent_framework_cluster"] == train["parent_framework_cluster"], f"v4d_parent_mismatch:{candidate}")
            require(source["monomer_sha256"] == train["monomer_sha256"], f"v4d_monomer_hash_mismatch:{candidate}")
            require("label-free" in source["claim_boundary"].lower(), f"v4d_not_label_free:{candidate}")
            payload = _safe_v4d_pdb_bytes(archive, source["bundle_relative_path"])
            require(hashlib.sha256(payload).hexdigest() == train["monomer_sha256"], f"v4d_archive_pdb_hash_mismatch:{candidate}")
            pdb = temp_root / f"{candidate}.pdb"
            pdb.write_bytes(payload)
            regions, ranges = derive_cdr_region_indices(train["sequence"], train["cdr1"], train["cdr2"], train["cdr3"])
            graph = build_graph_from_pdb(
                entity_id=candidate, sequence=train["sequence"], sequence_digest=train["sequence_sha256"],
                monomer_path=pdb, region_index=regions, config=config,
                expected_chain=source["monomer_source_chain"], expected_monomer_sha256=train["monomer_sha256"],
            )
            graphs.append(graph)
            closure.append(_closure_row(train, graph, ranges, "V4D_ARCHIVE_OPEN_TRAIN_LABEL_FREE"))
    return graphs, closure


def _closure_row(train: Mapping[str, str], graph: ResidueGraph, ranges: Mapping[str, str], structure_source: str) -> dict[str, str]:
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": train["candidate_id"],
        "sequence_sha256": train["sequence_sha256"],
        "parent_framework_cluster": train["parent_framework_cluster"],
        "teacher_source_audit_only": train["teacher_source"],
        "monomer_sha256": graph.monomer_sha256,
        "structure_source": structure_source,
        "chain": graph.chain,
        "cdr1_range": ranges["cdr1_range"],
        "cdr2_range": ranges["cdr2_range"],
        "cdr3_range": ranges["cdr3_range"],
        "node_count": str(len(graph.sequence)),
        "edge_count": str(graph.edge_index.shape[1]),
    }


def _tsv_text(rows: Sequence[Mapping[str, str]]) -> str:
    require(rows, "cannot_write_empty_tsv")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _write_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def materialize_supervised_graph_inputs(
    *,
    training_table: pathlib.Path,
    v4d_archive: pathlib.Path,
    v4h_manifest: pathlib.Path,
    v4h_structure_root: pathlib.Path,
    output_dir: pathlib.Path | None,
    dry_run: bool,
    expected_source_counts: Mapping[str, int] = EXPECTED_SOURCE_COUNTS,
    expected_parent_counts: Mapping[str, int] = EXPECTED_PARENT_COUNTS,
    config: GraphBuildConfig = GraphBuildConfig(),
) -> dict[str, Any]:
    training_rows = _read_tsv(training_table)
    training = _validate_training_rows(training_rows, expected_source_counts, expected_parent_counts)
    v4d_graphs, v4d_closure = _v4d_graphs(training, v4d_archive, config)
    v4h_graphs, v4h_closure = _v4h_graphs(training, v4h_manifest, v4h_structure_root, config)
    graphs = v4d_graphs + v4h_graphs
    closure = sorted(v4d_closure + v4h_closure, key=lambda row: row["candidate_id"])
    require(len(graphs) == len(training) == sum(expected_source_counts.values()), "final_graph_count_mismatch")
    require({graph.entity_id for graph in graphs} == set(training), "final_graph_candidate_set_mismatch")
    audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_DRY_RUN_SUPERVISED_GRAPH_INPUTS" if dry_run else "PASS_SUPERVISED_GRAPH_INPUTS_MATERIALIZED",
        "claim_boundary": "Exact supervised candidate closure over label-free VHH monomer structures only; teacher source is audit-only and no candidate Docking pose is a model input.",
        "counts": {
            "candidates": len(graphs),
            "parents": len({row["parent_framework_cluster"] for row in training.values()}),
            "source_candidates": dict(Counter(row["teacher_source"] for row in training.values())),
            "source_parents": {
                source: len({row["parent_framework_cluster"] for row in training.values() if row["teacher_source"] == source})
                for source in expected_source_counts
            },
            "nodes": sum(len(graph.sequence) for graph in graphs),
            "edges": sum(graph.edge_index.shape[1] for graph in graphs),
        },
        "inputs": {
            "training_table_sha256": sha256_file(training_table),
            "v4d_archive_sha256": sha256_file(v4d_archive),
            "v4h_manifest_sha256": sha256_file(v4h_manifest),
        },
        "config": {
            "knn": config.knn,
            "radius_angstrom": config.radius_angstrom,
            "rbf_bins": config.rbf_bins,
            "edge_feature_dim": config.edge_feature_dim,
            "cdr_mapping": "unique_exact_sequence_substring_then_ordered_nonoverlap",
        },
        "sealed_boundary": {
            "allowed_sources": sorted(expected_source_counts),
            "v4d_allowed_split": "OPEN_TRAIN",
            "open_development_candidates_emitted": 0,
            "candidate_docking_pose_files_opened": 0,
            "teacher_source_is_model_feature": False,
        },
    }
    if dry_run:
        require(output_dir is None or not output_dir.exists(), "dry_run_must_not_write_output")
        return audit
    require(output_dir is not None, "output_dir_required")
    require(not output_dir.exists(), f"output_dir_already_exists:{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        graph_receipt = materialize_graph_cache(graphs, staging, config=config)
        closure_path = staging / CLOSURE_NAME
        closure_path.write_text(_tsv_text(closure), encoding="utf-8")
        audit["graph_cache"] = graph_receipt
        audit["outputs"] = {
            CACHE_NAME: sha256_file(staging / CACHE_NAME),
            MANIFEST_NAME: sha256_file(staging / MANIFEST_NAME),
            RECEIPT_NAME: sha256_file(staging / RECEIPT_NAME),
            CLOSURE_NAME: sha256_file(closure_path),
        }
        _write_json(staging / MATERIALIZATION_RECEIPT, audit)
        sum_files = [CACHE_NAME, MANIFEST_NAME, RECEIPT_NAME, CLOSURE_NAME, MATERIALIZATION_RECEIPT]
        sums = "".join(f"{sha256_file(staging / name)}  {name}\n" for name in sum_files)
        (staging / SHA256SUMS_NAME).write_text(sums, encoding="utf-8")
        os.replace(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-table", required=True, type=pathlib.Path)
    parser.add_argument("--v4d-archive", required=True, type=pathlib.Path)
    parser.add_argument("--v4h-manifest", required=True, type=pathlib.Path)
    parser.add_argument("--v4h-structure-root", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        require(args.output_dir is not None, "output_dir_required_without_dry_run")
    receipt = materialize_supervised_graph_inputs(
        training_table=args.training_table,
        v4d_archive=args.v4d_archive,
        v4h_manifest=args.v4h_manifest,
        v4h_structure_root=args.v4h_structure_root,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
