#!/usr/bin/env python3
"""Build rigid-invariant residue graphs from label-free monomer PDB files.

The cache is deliberately independent of Docking teachers.  Candidate Docking
poses, receptor complexes, teacher labels, and ``teacher_source`` are forbidden
inputs.  Only a single-chain monomer and its expected amino-acid sequence are
accepted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pathlib
import tempfile
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SCHEMA_VERSION = "pvrig_v6_residue_graph_cache_v2"
CACHE_NAME = "graph_cache_v2.npz"
MANIFEST_NAME = "graph_manifest_v2.tsv"
RECEIPT_NAME = "graph_cache_receipt_v2.json"
REGION_NAMES = ("framework", "cdr1", "cdr2", "cdr3", "other")
AA_ORDER = "ACDEFGHIKLMNPQRSTVWYX"
AA_TO_INDEX = {aa: index for index, aa in enumerate(AA_ORDER)}
FORBIDDEN_PATH_TOKENS = (
    "docking",
    "docked",
    "haddock",
    "pose",
    "complex",
    "job_result",
)
THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


class GraphCacheError(RuntimeError):
    """Fail-closed graph materialization error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GraphCacheError(message)


@dataclass(frozen=True)
class GraphBuildConfig:
    knn: int = 16
    radius_angstrom: float = 12.0
    rbf_bins: int = 16
    rbf_max_angstrom: float = 12.0
    sequence_separation_cap: int = 32
    confidence_scale: float = 100.0

    def validate(self) -> None:
        require(self.knn > 0, "knn_invalid")
        require(self.radius_angstrom > 0.0, "radius_invalid")
        require(self.rbf_bins >= 2, "rbf_bins_invalid")
        require(self.rbf_max_angstrom > 0.0, "rbf_max_invalid")
        require(self.sequence_separation_cap > 0, "sequence_separation_cap_invalid")
        require(self.confidence_scale > 0.0, "confidence_scale_invalid")

    @property
    def edge_feature_dim(self) -> int:
        # RBF + signed/absolute sequence separation + seq/spatial flags +
        # source- and destination-frame unit directions.
        return self.rbf_bins + 4 + 6


@dataclass(frozen=True)
class BackboneResidue:
    chain: str
    residue_number: int
    insertion_code: str
    aa: str
    n: np.ndarray
    ca: np.ndarray
    c: np.ndarray
    confidence: float


@dataclass(frozen=True)
class ResidueGraph:
    entity_id: str
    sequence: str
    sequence_sha256: str
    monomer_sha256: str
    chain: str
    aa_index: np.ndarray
    region_index: np.ndarray
    confidence: np.ndarray
    atom_n: np.ndarray
    atom_ca: np.ndarray
    atom_c: np.ndarray
    local_frames: np.ndarray
    edge_index: np.ndarray
    edge_features: np.ndarray


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return sha256_bytes(sequence.encode("ascii"))


def assert_label_free_monomer_path(path: pathlib.Path) -> pathlib.Path:
    """Reject paths that could plausibly be candidate Docking outputs."""

    require(path.suffix.lower() == ".pdb", "monomer_not_pdb")
    require(path.exists() and path.is_file(), f"monomer_missing:{path}")
    require(not path.is_symlink(), f"monomer_symlink_forbidden:{path}")
    lowered_parts = [part.lower() for part in path.parts]
    for part in lowered_parts:
        require(
            not any(token in part for token in FORBIDDEN_PATH_TOKENS),
            f"candidate_docking_or_complex_path_forbidden:{path}",
        )
    return path.resolve(strict=True)


def _parse_xyz(line: str) -> np.ndarray:
    try:
        xyz = np.asarray((float(line[30:38]), float(line[38:46]), float(line[46:54])), dtype=np.float64)
    except ValueError as error:
        raise GraphCacheError("pdb_coordinate_invalid") from error
    require(bool(np.all(np.isfinite(xyz))), "pdb_coordinate_nonfinite")
    return xyz


def parse_monomer_backbone(
    path: pathlib.Path,
    *,
    expected_sequence: str,
    expected_chain: str | None = None,
) -> list[BackboneResidue]:
    """Read one standard-amino-acid chain with complete N/CA/C atoms."""

    resolved = assert_label_free_monomer_path(path)
    expected_sequence = expected_sequence.strip().upper()
    require(expected_sequence and all(aa in AA_TO_INDEX and aa != "X" for aa in expected_sequence), "expected_sequence_invalid")
    residue_order: list[tuple[str, int, str]] = []
    residue_data: dict[tuple[str, int, str], dict[str, Any]] = {}
    model_count = 0
    active_model = True
    with resolved.open("r", encoding="utf-8", errors="strict") as handle:
        for line in handle:
            record = line[:6].strip().upper()
            if record == "MODEL":
                model_count += 1
                require(model_count == 1, "multiple_pdb_models_forbidden")
                active_model = True
                continue
            if record == "ENDMDL":
                active_model = False
                continue
            if record != "ATOM" or not active_model:
                continue
            atom_name = line[12:16].strip().upper()
            if atom_name not in {"N", "CA", "C"}:
                continue
            altloc = line[16:17]
            if altloc not in {" ", "A"}:
                continue
            residue_name = line[17:20].strip().upper()
            require(residue_name in THREE_TO_ONE, f"nonstandard_residue_forbidden:{residue_name}")
            chain = line[21:22].strip() or "_"
            try:
                residue_number = int(line[22:26])
            except ValueError as error:
                raise GraphCacheError("pdb_residue_number_invalid") from error
            insertion_code = line[26:27].strip()
            key = (chain, residue_number, insertion_code)
            if key not in residue_data:
                residue_order.append(key)
                residue_data[key] = {"aa": THREE_TO_ONE[residue_name], "atoms": {}, "confidence": None}
            require(residue_data[key]["aa"] == THREE_TO_ONE[residue_name], "pdb_residue_name_conflict")
            atoms = residue_data[key]["atoms"]
            require(atom_name not in atoms, f"duplicate_backbone_atom:{key}:{atom_name}")
            atoms[atom_name] = _parse_xyz(line)
            if atom_name == "CA":
                try:
                    confidence = float(line[60:66])
                except ValueError as error:
                    raise GraphCacheError("pdb_confidence_invalid") from error
                require(math.isfinite(confidence), "pdb_confidence_nonfinite")
                residue_data[key]["confidence"] = confidence

    require(residue_order, "pdb_has_no_backbone_atoms")
    chains = {key[0] for key in residue_order}
    require(len(chains) == 1, f"monomer_multiple_chains_forbidden:{sorted(chains)}")
    chain = next(iter(chains))
    if expected_chain is not None:
        require(chain == expected_chain, f"monomer_chain_mismatch:{chain}!={expected_chain}")
    residues: list[BackboneResidue] = []
    for key in residue_order:
        item = residue_data[key]
        missing = {"N", "CA", "C"} - set(item["atoms"])
        require(not missing, f"backbone_atoms_missing:{key}:{sorted(missing)}")
        require(item["confidence"] is not None, f"ca_confidence_missing:{key}")
        residues.append(
            BackboneResidue(
                chain=key[0], residue_number=key[1], insertion_code=key[2], aa=item["aa"],
                n=item["atoms"]["N"], ca=item["atoms"]["CA"], c=item["atoms"]["C"],
                confidence=float(item["confidence"]),
            )
        )
    observed_sequence = "".join(residue.aa for residue in residues)
    require(observed_sequence == expected_sequence, "monomer_sequence_mismatch")
    return residues


def _normalize(vectors: np.ndarray, *, message: str) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    require(bool(np.all(norms > 1e-7)), message)
    return vectors / norms


def local_frames(atom_n: np.ndarray, atom_ca: np.ndarray, atom_c: np.ndarray) -> np.ndarray:
    """Return right-handed N/CA/C local frames as column vectors."""

    require(atom_n.shape == atom_ca.shape == atom_c.shape and atom_ca.ndim == 2 and atom_ca.shape[1] == 3, "backbone_array_shape_invalid")
    x_axis = _normalize(atom_c - atom_ca, message="degenerate_ca_c_vector")
    ca_to_n = _normalize(atom_n - atom_ca, message="degenerate_ca_n_vector")
    z_axis = _normalize(np.cross(x_axis, ca_to_n), message="degenerate_backbone_plane")
    y_axis = _normalize(np.cross(z_axis, x_axis), message="degenerate_local_frame")
    frames = np.stack((x_axis, y_axis, z_axis), axis=-1)
    require(bool(np.all(np.isfinite(frames))), "local_frame_nonfinite")
    return frames


def build_edge_index(atom_ca: np.ndarray, config: GraphBuildConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Union directed sequence edges with CA kNN16 edges inside radius12A."""

    config.validate()
    require(atom_ca.ndim == 2 and atom_ca.shape[1] == 3 and len(atom_ca) > 0, "ca_array_shape_invalid")
    distances = np.linalg.norm(atom_ca[:, None, :] - atom_ca[None, :, :], axis=-1)
    edges: dict[tuple[int, int], list[bool]] = {}
    count = len(atom_ca)
    for source in range(count):
        for destination in (source - 1, source + 1):
            if 0 <= destination < count:
                edges.setdefault((source, destination), [False, False])[0] = True
        candidates = [
            destination for destination in range(count)
            if destination != source and distances[source, destination] <= config.radius_angstrom
        ]
        candidates.sort(key=lambda destination: (float(distances[source, destination]), destination))
        for destination in candidates[: config.knn]:
            edges.setdefault((source, destination), [False, False])[1] = True
    ordered = sorted(edges)
    require(ordered, "graph_has_no_edges")
    edge_index = np.asarray(ordered, dtype=np.int64).T
    sequence_flags = np.asarray([edges[edge][0] for edge in ordered], dtype=np.float32)
    spatial_flags = np.asarray([edges[edge][1] for edge in ordered], dtype=np.float32)
    return edge_index, sequence_flags, spatial_flags


def build_edge_features(
    atom_ca: np.ndarray,
    frames: np.ndarray,
    edge_index: np.ndarray,
    sequence_flags: np.ndarray,
    spatial_flags: np.ndarray,
    config: GraphBuildConfig,
) -> np.ndarray:
    """Compute rigid-invariant RBF, separation, flags, and local directions."""

    require(edge_index.ndim == 2 and edge_index.shape[0] == 2, "edge_index_shape_invalid")
    source, destination = edge_index
    require(len(source) == len(sequence_flags) == len(spatial_flags), "edge_metadata_length_mismatch")
    relative = atom_ca[destination] - atom_ca[source]
    distance = np.linalg.norm(relative, axis=-1)
    require(bool(np.all(distance > 1e-7)), "zero_length_edge")
    unit = relative / distance[:, None]
    source_direction = np.einsum("eji,ej->ei", frames[source], unit)
    destination_direction = np.einsum("eji,ej->ei", frames[destination], -unit)
    centers = np.linspace(0.0, config.rbf_max_angstrom, config.rbf_bins, dtype=np.float64)
    spacing = float(centers[1] - centers[0])
    rbf = np.exp(-0.5 * ((distance[:, None] - centers[None, :]) / spacing) ** 2)
    separation = destination.astype(np.float64) - source.astype(np.float64)
    signed_separation = np.clip(separation / config.sequence_separation_cap, -1.0, 1.0)
    absolute_separation = np.log1p(np.abs(separation)) / math.log1p(config.sequence_separation_cap)
    features = np.concatenate(
        (
            rbf,
            signed_separation[:, None], absolute_separation[:, None],
            sequence_flags[:, None], spatial_flags[:, None],
            source_direction, destination_direction,
        ),
        axis=1,
    ).astype(np.float32)
    require(features.shape == (edge_index.shape[1], config.edge_feature_dim), "edge_feature_shape_invalid")
    require(bool(np.all(np.isfinite(features))), "edge_feature_nonfinite")
    return features


def graph_from_backbone(
    *,
    entity_id: str,
    sequence: str,
    sequence_digest: str,
    monomer_digest: str,
    residues: Sequence[BackboneResidue],
    region_index: Sequence[int],
    config: GraphBuildConfig,
) -> ResidueGraph:
    require(entity_id.strip() == entity_id and entity_id, "entity_id_invalid")
    require(sequence_sha256(sequence) == sequence_digest, "sequence_sha256_mismatch")
    require(len(residues) == len(sequence) == len(region_index), "graph_residue_length_mismatch")
    require("".join(residue.aa for residue in residues) == sequence, "graph_backbone_sequence_mismatch")
    require(all(0 <= int(region) < len(REGION_NAMES) for region in region_index), "region_index_invalid")
    atom_n = np.stack([residue.n for residue in residues]).astype(np.float32)
    atom_ca = np.stack([residue.ca for residue in residues]).astype(np.float32)
    atom_c = np.stack([residue.c for residue in residues]).astype(np.float32)
    frames = local_frames(atom_n.astype(np.float64), atom_ca.astype(np.float64), atom_c.astype(np.float64)).astype(np.float32)
    edge_index, sequence_flags, spatial_flags = build_edge_index(atom_ca.astype(np.float64), config)
    edge_features = build_edge_features(atom_ca.astype(np.float64), frames.astype(np.float64), edge_index, sequence_flags, spatial_flags, config)
    confidence = np.asarray([residue.confidence for residue in residues], dtype=np.float32) / config.confidence_scale
    require(bool(np.all(np.isfinite(confidence))), "confidence_nonfinite")
    return ResidueGraph(
        entity_id=entity_id,
        sequence=sequence,
        sequence_sha256=sequence_digest,
        monomer_sha256=monomer_digest,
        chain=residues[0].chain,
        aa_index=np.asarray([AA_TO_INDEX[residue.aa] for residue in residues], dtype=np.int64),
        region_index=np.asarray(region_index, dtype=np.int64),
        confidence=confidence,
        atom_n=atom_n, atom_ca=atom_ca, atom_c=atom_c,
        local_frames=frames,
        edge_index=edge_index,
        edge_features=edge_features,
    )


def build_graph_from_pdb(
    *,
    entity_id: str,
    sequence: str,
    sequence_digest: str,
    monomer_path: pathlib.Path,
    region_index: Sequence[int],
    config: GraphBuildConfig = GraphBuildConfig(),
    expected_chain: str | None = None,
    expected_monomer_sha256: str | None = None,
) -> ResidueGraph:
    resolved = assert_label_free_monomer_path(monomer_path)
    monomer_digest = sha256_file(resolved)
    if expected_monomer_sha256:
        require(monomer_digest == expected_monomer_sha256, "monomer_sha256_mismatch")
    residues = parse_monomer_backbone(resolved, expected_sequence=sequence, expected_chain=expected_chain)
    return graph_from_backbone(
        entity_id=entity_id, sequence=sequence, sequence_digest=sequence_digest,
        monomer_digest=monomer_digest, residues=residues, region_index=region_index, config=config,
    )


def _atomic_write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_save_npz(path: pathlib.Path, arrays: Mapping[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".npz", dir=path.parent)
    os.close(descriptor)
    try:
        np.savez_compressed(temporary, **arrays)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def materialize_graph_cache(
    graphs: Sequence[ResidueGraph],
    output_dir: pathlib.Path,
    *,
    config: GraphBuildConfig = GraphBuildConfig(),
) -> dict[str, Any]:
    """Write content-addressed ragged graph arrays and auditable manifest."""

    config.validate()
    require(graphs, "no_graphs_to_materialize")
    ordered = sorted(graphs, key=lambda graph: graph.entity_id)
    require(len({graph.entity_id for graph in ordered}) == len(ordered), "duplicate_entity_id")
    node_offsets = [0]
    edge_offsets = [0]
    manifest_rows: list[dict[str, str]] = []
    global_edges: list[np.ndarray] = []
    for graph in ordered:
        require(graph.edge_features.shape[1] == config.edge_feature_dim, "graph_edge_feature_dim_mismatch")
        node_start = node_offsets[-1]
        edge_start = edge_offsets[-1]
        node_offsets.append(node_start + len(graph.sequence))
        edge_offsets.append(edge_start + graph.edge_index.shape[1])
        global_edges.append(graph.edge_index + node_start)
        manifest_rows.append({
            "schema_version": SCHEMA_VERSION,
            "entity_id": graph.entity_id,
            "sequence_sha256": graph.sequence_sha256,
            "monomer_sha256": graph.monomer_sha256,
            "chain": graph.chain,
            "node_start": str(node_start), "node_end": str(node_offsets[-1]),
            "edge_start": str(edge_start), "edge_end": str(edge_offsets[-1]),
        })
    arrays = {
        "node_offsets": np.asarray(node_offsets, dtype=np.int64),
        "edge_offsets": np.asarray(edge_offsets, dtype=np.int64),
        "aa_index": np.concatenate([graph.aa_index for graph in ordered]),
        "region_index": np.concatenate([graph.region_index for graph in ordered]),
        "confidence": np.concatenate([graph.confidence for graph in ordered]),
        "atom_n": np.concatenate([graph.atom_n for graph in ordered]),
        "atom_ca": np.concatenate([graph.atom_ca for graph in ordered]),
        "atom_c": np.concatenate([graph.atom_c for graph in ordered]),
        "local_frames": np.concatenate([graph.local_frames for graph in ordered]),
        "edge_index": np.concatenate(global_edges, axis=1),
        "edge_features": np.concatenate([graph.edge_features for graph in ordered]),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / CACHE_NAME
    manifest_path = output_dir / MANIFEST_NAME
    _atomic_save_npz(cache_path, arrays)
    fields = list(manifest_rows[0])
    lines: list[str] = []
    from io import StringIO
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(manifest_rows)
    _atomic_write_text(manifest_path, buffer.getvalue())
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE",
        "claim_boundary": "Label-free monomer residue graphs only; no Docking pose, complex, teacher label, binding, affinity, or experimental blocking truth.",
        "config": asdict(config),
        "counts": {
            "entities": len(ordered),
            "nodes": int(node_offsets[-1]),
            "edges": int(edge_offsets[-1]),
            "edge_feature_dim": config.edge_feature_dim,
        },
        "outputs": {
            CACHE_NAME: sha256_file(cache_path),
            MANIFEST_NAME: sha256_file(manifest_path),
        },
        "forbidden_model_features": ["teacher_source", "candidate_docking_pose", "absolute_coordinate_mlp_input"],
    }
    receipt_path = output_dir / RECEIPT_NAME
    _atomic_write_text(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def load_graph_cache(output_dir: pathlib.Path) -> tuple[dict[str, np.ndarray], list[dict[str, str]], dict[str, Any]]:
    cache_path = output_dir / CACHE_NAME
    manifest_path = output_dir / MANIFEST_NAME
    receipt_path = output_dir / RECEIPT_NAME
    require(all(path.exists() and path.is_file() and not path.is_symlink() for path in (cache_path, manifest_path, receipt_path)), "graph_cache_delivery_incomplete")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE", "graph_cache_receipt_status_invalid")
    require(receipt["outputs"][CACHE_NAME] == sha256_file(cache_path), "graph_cache_hash_mismatch")
    require(receipt["outputs"][MANIFEST_NAME] == sha256_file(manifest_path), "graph_manifest_hash_mismatch")
    with np.load(cache_path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    with manifest_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(len(rows) == receipt["counts"]["entities"], "graph_manifest_entity_count_mismatch")
    require("teacher_source" not in arrays and (not rows or "teacher_source" not in rows[0]), "teacher_source_feature_forbidden")
    return arrays, rows, receipt


def _region_indices_from_manifest(row: Mapping[str, str], length: int) -> list[int]:
    encoded = row.get("region_indices", "").strip()
    if encoded:
        try:
            regions = [int(value) for value in encoded.split(",")]
        except ValueError as error:
            raise GraphCacheError("manifest_region_indices_invalid") from error
        require(len(regions) == length, "manifest_region_indices_length_mismatch")
        require(all(0 <= region < len(REGION_NAMES) for region in regions), "manifest_region_indices_invalid")
        return regions
    regions = [0] * length
    found = False
    for region, field in ((1, "cdr1_range"), (2, "cdr2_range"), (3, "cdr3_range")):
        value = row.get(field, "").strip()
        if not value:
            continue
        found = True
        try:
            start_text, end_text = value.split("-", 1)
            start, end = int(start_text), int(end_text)
        except (ValueError, TypeError) as error:
            raise GraphCacheError(f"manifest_cdr_range_invalid:{field}") from error
        require(1 <= start <= end <= length, f"manifest_cdr_range_out_of_bounds:{field}")
        for index in range(start - 1, end):
            require(regions[index] == 0, f"manifest_cdr_ranges_overlap:{index + 1}")
            regions[index] = region
    require(found, "manifest_region_annotation_missing")
    return regions


def build_cache_from_manifest(
    manifest_path: pathlib.Path,
    pdb_root: pathlib.Path,
    output_dir: pathlib.Path,
    *,
    expected_entities: int | None = None,
    config: GraphBuildConfig = GraphBuildConfig(),
) -> dict[str, Any]:
    """Materialize a cache from a pre-joined, label-free monomer manifest."""

    require(manifest_path.exists() and manifest_path.is_file() and not manifest_path.is_symlink(), "input_manifest_invalid")
    root = pdb_root.resolve(strict=True)
    require(root.is_dir(), "pdb_root_not_directory")
    with manifest_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None, "input_manifest_header_missing")
        required = {"sequence", "sequence_sha256", "claim_boundary"}
        require(required <= set(reader.fieldnames), f"input_manifest_fields_missing:{sorted(required - set(reader.fieldnames))}")
        rows = list(reader)
    if expected_entities is not None:
        require(len(rows) == expected_entities, f"input_manifest_entity_count_mismatch:{len(rows)}!={expected_entities}")
    require(rows, "input_manifest_empty")
    graphs: list[ResidueGraph] = []
    for row in rows:
        entity_id = (row.get("entity_id") or row.get("candidate_id") or "").strip()
        require(entity_id, "manifest_entity_id_missing")
        claim_boundary = row["claim_boundary"].lower()
        require("label-free" in claim_boundary and "docking gold" in claim_boundary, "manifest_claim_boundary_not_label_free")
        relative_text = next(
            (row.get(field, "").strip() for field in ("monomer_relative_path", "bundle_relative_path", "pdb_relative_path", "monomer_path") if row.get(field, "").strip()),
            "",
        )
        require(relative_text, f"manifest_monomer_path_missing:{entity_id}")
        relative = pathlib.Path(relative_text)
        require(not relative.is_absolute() and ".." not in relative.parts, f"manifest_monomer_path_unsafe:{entity_id}")
        monomer_path = (root / relative).resolve(strict=True)
        require(monomer_path.is_relative_to(root), f"manifest_monomer_path_escape:{entity_id}")
        sequence = row["sequence"].strip().upper()
        regions = _region_indices_from_manifest(row, len(sequence))
        expected_chain = (row.get("source_chain") or row.get("monomer_source_chain") or row.get("chain") or "").strip() or None
        graphs.append(
            build_graph_from_pdb(
                entity_id=entity_id,
                sequence=sequence,
                sequence_digest=row["sequence_sha256"].strip(),
                monomer_path=monomer_path,
                region_index=regions,
                config=config,
                expected_chain=expected_chain,
                expected_monomer_sha256=(row.get("monomer_sha256") or "").strip() or None,
            )
        )
    receipt = materialize_graph_cache(graphs, output_dir, config=config)
    receipt["input_manifest_sha256"] = sha256_file(manifest_path)
    # Re-write the receipt so the input manifest is part of the delivery hash
    # closure rather than an unbound caller-side assertion.
    _atomic_write_text(output_dir / RECEIPT_NAME, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--pdb-root", type=pathlib.Path)
    parser.add_argument("--output-dir", type=pathlib.Path)
    parser.add_argument("--expected-entities", type=int)
    parser.add_argument("--self-test-contract", action="store_true", help="Validate the frozen default graph configuration and exit.")
    args = parser.parse_args()
    config = GraphBuildConfig()
    config.validate()
    if args.self_test_contract:
        require(args.manifest is None and args.pdb_root is None and args.output_dir is None, "self_test_cannot_materialize")
        print(json.dumps({"schema_version": SCHEMA_VERSION, "config": asdict(config), "edge_feature_dim": config.edge_feature_dim}, sort_keys=True))
        return
    require(args.manifest is not None and args.pdb_root is not None and args.output_dir is not None, "manifest_pdb_root_output_required")
    receipt = build_cache_from_manifest(
        args.manifest, args.pdb_root, args.output_dir,
        expected_entities=args.expected_entities, config=config,
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
