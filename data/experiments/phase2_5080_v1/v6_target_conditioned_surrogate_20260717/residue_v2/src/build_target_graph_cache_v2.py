#!/usr/bin/env python3
"""Build fixed label-free PVRIG graphs from public 8X6B and 9E6Y structures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import pathlib
import re
import shutil
import tempfile
from dataclasses import asdict
from typing import Any, Mapping, Sequence

import numpy as np

from build_residue_graph_cache_v2 import (
    GraphBuildConfig,
    ResidueGraph,
    build_graph_from_pdb,
    parse_monomer_backbone,
    sha256_file,
)


SCHEMA_VERSION = "pvrig_v6_residue_v2_fixed_target_graphs"
CACHE_NAME = "target_graph_cache_v2.npz"
TORCH_NAME = "target_graphs_v2.pt"
MANIFEST_NAME = "target_graph_manifest_v2.tsv"
RECEIPT_NAME = "target_graph_receipt_v2.json"
SHA256SUMS_NAME = "SHA256SUMS"
TARGET_ROOT_NAME = "label_free_targets"
TARGET_SPECS = {
    "8x6b": {
        "pdb_id": "8X6B", "chain": "B",
        "source_sha256": "b9a930e44f61ee2ba35b4f8f739bc9431eb1944dad2e2344bd9c9a7ad13bb868",
        "interface_filename": "PVRIG_interface_residues_8X6B.csv",
    },
    "9e6y": {
        "pdb_id": "9E6Y", "chain": "A",
        "source_sha256": "fb05ec77e439b8e1f43bfa12d7eb60f05f2c53e2099f06442f6c9ced32d98316",
        "interface_filename": "PVRIG_interface_residues_9E6Y.csv",
    },
}
AA_ORDER = "ACDEFGHIKLMNPQRSTVWYX"
MAX_ASA = {
    "A": 121.0, "R": 265.0, "N": 187.0, "D": 187.0, "C": 148.0,
    "Q": 214.0, "E": 214.0, "G": 97.0, "H": 216.0, "I": 195.0,
    "L": 191.0, "K": 230.0, "M": 203.0, "F": 228.0, "P": 154.0,
    "S": 143.0, "T": 163.0, "W": 264.0, "Y": 255.0, "V": 165.0,
}
VDW_RADII = {"C": 1.70, "N": 1.55, "O": 1.52, "S": 1.80, "P": 1.80}
NODE_FEATURE_NAMES = (
    tuple(f"aa_{aa}" for aa in AA_ORDER)
    + ("interface_mask", "hotspot_weight", "relative_sasa", "secondary_helix", "secondary_sheet", "secondary_coil", "ca_neighbor_density_8a", "ca_curvature", "normalized_sequence_position")
)


class TargetGraphError(RuntimeError):
    """Fail-closed fixed-target graph error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TargetGraphError(message)


def _read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    require(path.exists() and path.is_file() and not path.is_symlink(), f"csv_invalid:{path}")
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames is not None, f"csv_header_missing:{path}")
        return list(reader)


def extract_public_pvrig_chain(source_pdb: pathlib.Path, chain: str) -> bytes:
    """Extract one PVRIG ATOM chain; ligand chains and HETATM are discarded."""

    require(source_pdb.exists() and source_pdb.is_file() and not source_pdb.is_symlink(), "public_structure_invalid")
    lines: list[str] = []
    model_count = 0
    active_model = True
    with source_pdb.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = line[:6].strip().upper()
            if record == "MODEL":
                model_count += 1
                require(model_count == 1, "public_structure_multiple_models")
                active_model = True
                continue
            if record == "ENDMDL":
                active_model = False
                continue
            if record != "ATOM" or not active_model or line[21:22] != chain:
                continue
            if line[16:17] not in {" ", "A"}:
                continue
            lines.append(line.rstrip("\n") + "\n")
    require(lines, f"pvrig_chain_has_no_atoms:{chain}")
    observed_chains = {line[21:22] for line in lines}
    require(observed_chains == {chain}, f"target_chain_extraction_failed:{observed_chains}")
    return ("".join(lines) + "END\n").encode("ascii")


def _residue_key(number: int, insertion_code: str) -> tuple[int, str]:
    return number, insertion_code.strip()


def _interface_map(path: pathlib.Path, pdb_id: str, chain: str) -> dict[tuple[int, str], str]:
    result: dict[tuple[int, str], str] = {}
    for row in _read_csv(path):
        require(row["pdb_id"] == pdb_id and row["pvrig_chain"] == chain, "interface_csv_target_mismatch")
        key = _residue_key(int(row["pvrig_resseq"]), row["pvrig_icode"])
        require(key not in result, f"duplicate_interface_residue:{key}")
        result[key] = row["pvrig_aa"]
    require(result, "interface_map_empty")
    return result


def _numbering_map(path: pathlib.Path, pdb_id: str, chain: str) -> dict[tuple[int, str], tuple[str, int]]:
    result: dict[tuple[int, str], tuple[str, int]] = {}
    for row in _read_csv(path):
        if row["pdb_id"] != pdb_id or row["pvrig_chain"] != chain:
            continue
        key = _residue_key(int(row["pdb_resseq"]), row["pdb_icode"])
        require(key not in result, f"duplicate_numbering_residue:{pdb_id}:{key}")
        result[key] = (row["pdb_aa"], int(row["uniprot_position"]))
    require(result, f"numbering_map_empty:{pdb_id}")
    return result


def _hotspot_map(path: pathlib.Path, receptor: str, chain: str) -> dict[tuple[int, str], tuple[str, float]]:
    field = "pdb_8x6b_ref" if receptor == "8x6b" else "pdb_9e6y_ref"
    pattern = re.compile(r"^([A-Za-z0-9]):(-?\d+)([A-Z])")
    result: dict[tuple[int, str], tuple[str, float]] = {}
    for row in _read_csv(path):
        match = pattern.match(row[field])
        require(match is not None, f"hotspot_reference_invalid:{row.get('hotspot_id')}:{field}")
        require(match.group(1) == chain, f"hotspot_chain_mismatch:{row.get('hotspot_id')}:{field}")
        key = _residue_key(int(match.group(2)), "")
        aa = match.group(3)
        weight = float(row["priority_weight"])
        require(math.isfinite(weight) and 0.0 <= weight <= 1.0, "hotspot_weight_invalid")
        if key in result:
            # Core interface evidence takes priority over a lower-weight soft hint.
            previous_aa, previous_weight = result[key]
            require(previous_aa == aa, f"hotspot_aa_conflict:{key}")
            result[key] = (aa, max(previous_weight, weight))
        else:
            result[key] = (aa, weight)
    require(result, f"hotspot_map_empty:{receptor}")
    return result


def _atom_records(payload: bytes) -> list[tuple[tuple[int, str], str, str, np.ndarray]]:
    records: list[tuple[tuple[int, str], str, str, np.ndarray]] = []
    for line in payload.decode("ascii").splitlines():
        if not line.startswith("ATOM"):
            continue
        atom_name = line[12:16].strip().upper()
        if atom_name.startswith("H"):
            continue
        element = line[76:78].strip().upper() or re.sub("[^A-Z]", "", atom_name)[:1]
        if element == "H":
            continue
        key = _residue_key(int(line[22:26]), line[26:27])
        aa3 = line[17:20].strip().upper()
        xyz = np.asarray((float(line[30:38]), float(line[38:46]), float(line[46:54])), dtype=np.float64)
        require(bool(np.all(np.isfinite(xyz))), "target_atom_coordinate_nonfinite")
        records.append((key, aa3, element, xyz))
    require(records, "target_heavy_atom_records_empty")
    return records


def _sphere_points(count: int = 64) -> np.ndarray:
    indices = np.arange(count, dtype=np.float64) + 0.5
    z = 1.0 - 2.0 * indices / count
    radius = np.sqrt(np.maximum(0.0, 1.0 - z * z))
    theta = math.pi * (1.0 + math.sqrt(5.0)) * indices
    return np.stack((radius * np.cos(theta), radius * np.sin(theta), z), axis=1)


def approximate_residue_sasa(payload: bytes, residue_keys: Sequence[tuple[int, str]], aas: Sequence[str]) -> np.ndarray:
    """Deterministic 64-point Shrake-Rupley relative SASA on isolated PVRIG."""

    records = _atom_records(payload)
    atom_keys = [record[0] for record in records]
    elements = [record[2] for record in records]
    coordinates = np.stack([record[3] for record in records])
    radii = np.asarray([VDW_RADII.get(element, 1.70) + 1.40 for element in elements], dtype=np.float64)
    sphere = _sphere_points(64)
    residue_area: dict[tuple[int, str], float] = {key: 0.0 for key in residue_keys}
    for atom_index, (key, radius) in enumerate(zip(atom_keys, radii)):
        points = coordinates[atom_index] + sphere * radius
        differences = points[:, None, :] - coordinates[None, :, :]
        squared = np.einsum("paj,paj->pa", differences, differences)
        blocked = squared < (radii[None, :] ** 2)
        blocked[:, atom_index] = False
        accessible_fraction = float((~blocked.any(axis=1)).mean())
        residue_area[key] = residue_area.get(key, 0.0) + 4.0 * math.pi * radius * radius * accessible_fraction
    require(set(residue_keys) <= set(residue_area), "sasa_residue_closure_failed")
    relative = np.asarray([
        min(max(residue_area[key] / MAX_ASA[aa], 0.0), 1.5) / 1.5
        for key, aa in zip(residue_keys, aas)
    ], dtype=np.float32)
    require(bool(np.all(np.isfinite(relative))), "relative_sasa_nonfinite")
    return relative


def _dihedral(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> float:
    b0 = -(b - a)
    b1 = c - b
    b2 = d - c
    norm = np.linalg.norm(b1)
    if norm <= 1e-8:
        return float("nan")
    b1 = b1 / norm
    v = b0 - np.dot(b0, b1) * b1
    w = b2 - np.dot(b2, b1) * b1
    x = np.dot(v, w)
    y = np.dot(np.cross(b1, v), w)
    return math.degrees(math.atan2(y, x))


def secondary_structure_features(residues: Sequence[Any]) -> np.ndarray:
    features = np.zeros((len(residues), 3), dtype=np.float32)
    features[:, 2] = 1.0
    for index in range(1, len(residues) - 1):
        phi = _dihedral(residues[index - 1].c, residues[index].n, residues[index].ca, residues[index].c)
        psi = _dihedral(residues[index].n, residues[index].ca, residues[index].c, residues[index + 1].n)
        if not math.isfinite(phi) or not math.isfinite(psi):
            continue
        if -160.0 <= phi <= -30.0 and -100.0 <= psi <= 50.0:
            features[index] = (1.0, 0.0, 0.0)
        elif -180.0 <= phi <= -40.0 and (psi >= 70.0 or psi <= -120.0):
            features[index] = (0.0, 1.0, 0.0)
    return features


def local_geometry_features(ca: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    distances = np.linalg.norm(ca[:, None, :] - ca[None, :, :], axis=-1)
    density = ((distances <= 8.0) & (distances > 1e-7)).sum(axis=1).astype(np.float32)
    density /= max(1, min(16, len(ca) - 1))
    density = np.clip(density, 0.0, 1.0)
    curvature = np.zeros(len(ca), dtype=np.float32)
    for index in range(1, len(ca) - 1):
        before = ca[index - 1] - ca[index]
        after = ca[index + 1] - ca[index]
        denominator = np.linalg.norm(before) * np.linalg.norm(after)
        if denominator > 1e-8:
            curvature[index] = float((np.dot(before, after) / denominator + 1.0) / 2.0)
    position = np.linspace(0.0, 1.0, len(ca), dtype=np.float32) if len(ca) > 1 else np.zeros(1, dtype=np.float32)
    return density, curvature, position


def target_node_features(
    graph: ResidueGraph,
    residues: Sequence[Any],
    payload: bytes,
    interface_map: Mapping[tuple[int, str], str],
    hotspot_map: Mapping[tuple[int, str], tuple[str, float]],
    numbering_map: Mapping[tuple[int, str], tuple[str, int]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    keys = [_residue_key(residue.residue_number, residue.insertion_code) for residue in residues]
    aas = [residue.aa for residue in residues]
    require(set(keys) == set(numbering_map), f"target_numbering_not_exact:{len(set(keys) ^ set(numbering_map))}")
    interface = np.zeros(len(keys), dtype=np.float32)
    hotspot_weight = np.zeros(len(keys), dtype=np.float32)
    uniprot_positions = np.zeros(len(keys), dtype=np.int64)
    for index, (key, aa) in enumerate(zip(keys, aas)):
        mapped_aa, uniprot = numbering_map[key]
        require(mapped_aa == aa, f"target_numbering_aa_mismatch:{key}")
        uniprot_positions[index] = uniprot
        if key in interface_map:
            require(interface_map[key] == aa, f"target_interface_aa_mismatch:{key}")
            interface[index] = 1.0
        if key in hotspot_map:
            hotspot_aa, weight = hotspot_map[key]
            require(hotspot_aa == aa, f"target_hotspot_aa_mismatch:{key}")
            hotspot_weight[index] = weight
    one_hot = np.eye(len(AA_ORDER), dtype=np.float32)[graph.aa_index]
    relative_sasa = approximate_residue_sasa(payload, keys, aas)
    secondary = secondary_structure_features(residues)
    density, curvature, position = local_geometry_features(graph.atom_ca.astype(np.float64))
    features = np.concatenate(
        (
            one_hot,
            interface[:, None], hotspot_weight[:, None], relative_sasa[:, None],
            secondary, density[:, None], curvature[:, None], position[:, None],
        ),
        axis=1,
    ).astype(np.float32)
    require(features.shape == (len(keys), len(NODE_FEATURE_NAMES)), "target_node_feature_shape_invalid")
    return features, interface.astype(bool), (hotspot_weight > 0.0), uniprot_positions


def _write_manifest(path: pathlib.Path, rows: Sequence[Mapping[str, str]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def materialize_target_graphs(
    *,
    structures_root: pathlib.Path,
    output_dir: pathlib.Path,
    dry_run: bool,
    expected_source_hashes: bool = True,
    config: GraphBuildConfig = GraphBuildConfig(),
) -> dict[str, Any]:
    require(structures_root.exists() and structures_root.is_dir(), "structures_root_invalid")
    if dry_run:
        require(not output_dir.exists(), "dry_run_must_not_write_output")
        staging_parent = pathlib.Path(tempfile.mkdtemp(prefix="target_graph_dry_run_"))
        staging = staging_parent / "delivery"
    else:
        require(not output_dir.exists(), f"output_dir_already_exists:{output_dir}")
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_parent = output_dir.parent
        staging = pathlib.Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=staging_parent))
    try:
        target_root = staging / TARGET_ROOT_NAME
        target_root.mkdir(parents=True)
        numbering_path = structures_root / "PVRIG_numbering_reconciliation.csv"
        hotspot_path = structures_root / "PVRIG_hotspot_set_v1.csv"
        arrays: dict[str, np.ndarray] = {}
        manifest_rows: list[dict[str, str]] = []
        input_hashes = {
            "numbering_reconciliation": sha256_file(numbering_path),
            "hotspot_set": sha256_file(hotspot_path),
        }
        for receptor, spec in TARGET_SPECS.items():
            source = structures_root / f"{spec['pdb_id']}.pdb"
            source_hash = sha256_file(source)
            if expected_source_hashes:
                require(source_hash == spec["source_sha256"], f"public_structure_hash_mismatch:{receptor}")
            interface_path = structures_root / spec["interface_filename"]
            input_hashes[f"{receptor}_public_structure"] = source_hash
            input_hashes[f"{receptor}_interface"] = sha256_file(interface_path)
            payload = extract_public_pvrig_chain(source, spec["chain"])
            monomer_path = target_root / f"pvrig_{receptor}_chain_{str(spec['chain']).lower()}.pdb"
            monomer_path.write_bytes(payload)
            residues = parse_monomer_backbone(
                monomer_path,
                expected_sequence="".join(
                    # Determine sequence from the extracted standard ATOM residues
                    # before reusing the strict graph builder below.
                    _sequence_from_payload(payload)
                ),
                expected_chain=spec["chain"],
            )
            sequence = "".join(residue.aa for residue in residues)
            sequence_digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            graph = build_graph_from_pdb(
                entity_id=receptor, sequence=sequence, sequence_digest=sequence_digest,
                monomer_path=monomer_path, region_index=[0] * len(sequence), config=config,
                expected_chain=spec["chain"], expected_monomer_sha256=hashlib.sha256(payload).hexdigest(),
            )
            interface = _interface_map(interface_path, spec["pdb_id"], spec["chain"])
            hotspot = _hotspot_map(hotspot_path, receptor, spec["chain"])
            numbering = _numbering_map(numbering_path, spec["pdb_id"], spec["chain"])
            node_features, interface_mask, hotspot_mask, uniprot_positions = target_node_features(
                graph, residues, payload, interface, hotspot, numbering,
            )
            prefix = receptor
            arrays[f"{prefix}_node_features"] = node_features
            arrays[f"{prefix}_edge_index"] = graph.edge_index
            arrays[f"{prefix}_edge_features"] = graph.edge_features
            arrays[f"{prefix}_interface_mask"] = interface_mask
            arrays[f"{prefix}_hotspot_mask"] = hotspot_mask
            arrays[f"{prefix}_aa_index"] = graph.aa_index
            arrays[f"{prefix}_uniprot_position"] = uniprot_positions
            arrays[f"{prefix}_residue_number"] = np.asarray([residue.residue_number for residue in residues], dtype=np.int64)
            manifest_rows.append({
                "schema_version": SCHEMA_VERSION,
                "receptor": receptor,
                "pdb_id": spec["pdb_id"],
                "pvrig_chain": spec["chain"],
                "sequence": sequence,
                "sequence_sha256": sequence_digest,
                "source_public_pdb_sha256": source_hash,
                "label_free_monomer_relative_path": str(monomer_path.relative_to(staging)),
                "label_free_monomer_sha256": hashlib.sha256(payload).hexdigest(),
                "node_count": str(len(sequence)),
                "edge_count": str(graph.edge_index.shape[1]),
                "interface_count": str(int(interface_mask.sum())),
                "hotspot_count": str(int(hotspot_mask.sum())),
            })
        cache_path = staging / CACHE_NAME
        np.savez_compressed(cache_path, **arrays)
        import torch
        torch_payload = {
            receptor: {
                "node_features": torch.from_numpy(arrays[f"{receptor}_node_features"]),
                "edge_index": torch.from_numpy(arrays[f"{receptor}_edge_index"]).long(),
                "edge_features": torch.from_numpy(arrays[f"{receptor}_edge_features"]),
                "interface_mask": torch.from_numpy(arrays[f"{receptor}_interface_mask"]).bool(),
                "hotspot_mask": torch.from_numpy(arrays[f"{receptor}_hotspot_mask"]).bool(),
            }
            for receptor in TARGET_SPECS
        }
        torch.save(torch_payload, staging / TORCH_NAME)
        manifest_path = staging / MANIFEST_NAME
        _write_manifest(manifest_path, manifest_rows)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_DRY_RUN_FIXED_TARGET_GRAPHS" if dry_run else "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED",
            "claim_boundary": "Fixed PVRIG graphs extracted from public 8X6B/9E6Y structures; no candidate Docking pose, teacher label, binding, affinity, or experimental blocking truth.",
            "config": asdict(config),
            "node_feature_names": list(NODE_FEATURE_NAMES),
            "node_feature_dim": len(NODE_FEATURE_NAMES),
            "input_hashes": input_hashes,
            "targets": {row["receptor"]: {
                "pdb_id": row["pdb_id"], "chain": row["pvrig_chain"],
                "nodes": int(row["node_count"]), "edges": int(row["edge_count"]),
                "interface_count": int(row["interface_count"]), "hotspot_count": int(row["hotspot_count"]),
                "sequence_sha256": row["sequence_sha256"],
                "label_free_monomer_sha256": row["label_free_monomer_sha256"],
            } for row in manifest_rows},
            "sealed_boundary": {
                "candidate_docking_pose_files_opened": 0,
                "ligand_chains_emitted": 0,
                "teacher_source_is_model_feature": False,
                "absolute_coordinates_are_node_features": False,
            },
        }
        if dry_run:
            return receipt
        receipt["outputs"] = {
            CACHE_NAME: sha256_file(cache_path),
            TORCH_NAME: sha256_file(staging / TORCH_NAME),
            MANIFEST_NAME: sha256_file(manifest_path),
            **{
                str(path.relative_to(staging)): sha256_file(path)
                for path in sorted(target_root.glob("*.pdb"))
            },
        }
        (staging / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        names = [CACHE_NAME, TORCH_NAME, MANIFEST_NAME, RECEIPT_NAME] + sorted(str(path.relative_to(staging)) for path in target_root.glob("*.pdb"))
        (staging / SHA256SUMS_NAME).write_text(
            "".join(f"{sha256_file(staging / name)}  {name}\n" for name in names), encoding="utf-8",
        )
        os.replace(staging, output_dir)
        return receipt
    finally:
        if dry_run:
            shutil.rmtree(staging_parent, ignore_errors=True)
        elif staging.exists():
            shutil.rmtree(staging)


def _sequence_from_payload(payload: bytes) -> list[str]:
    seen: set[tuple[int, str]] = set()
    sequence: list[str] = []
    three_to_one = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    for line in payload.decode("ascii").splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        key = _residue_key(int(line[22:26]), line[26:27])
        require(key not in seen, f"duplicate_target_ca:{key}")
        seen.add(key)
        residue = line[17:20].strip().upper()
        require(residue in three_to_one, f"nonstandard_target_residue:{residue}")
        sequence.append(three_to_one[residue])
    require(sequence, "target_sequence_empty")
    return sequence


def load_target_graph_cache(output_dir: pathlib.Path, *, device: str | None = None) -> dict[str, dict[str, Any]]:
    cache = output_dir / CACHE_NAME
    receipt_path = output_dir / RECEIPT_NAME
    require(cache.is_file() and not cache.is_symlink() and receipt_path.is_file() and not receipt_path.is_symlink(), "target_graph_delivery_incomplete")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED", "target_graph_receipt_status_invalid")
    require(receipt["outputs"][CACHE_NAME] == sha256_file(cache), "target_graph_cache_hash_mismatch")
    with np.load(cache, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    result: dict[str, dict[str, Any]] = {}
    if device is not None:
        import torch
    for receptor in TARGET_SPECS:
        graph: dict[str, Any] = {
            "node_features": arrays[f"{receptor}_node_features"],
            "edge_index": arrays[f"{receptor}_edge_index"],
            "edge_features": arrays[f"{receptor}_edge_features"],
            "interface_mask": arrays[f"{receptor}_interface_mask"],
            "hotspot_mask": arrays[f"{receptor}_hotspot_mask"],
        }
        if device is not None:
            graph = {
                key: torch.as_tensor(value, device=device, dtype=torch.long if key == "edge_index" else None)
                for key, value in graph.items()
            }
        result[receptor] = graph
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structures-root", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    receipt = materialize_target_graphs(
        structures_root=args.structures_root, output_dir=args.output_dir, dry_run=args.dry_run,
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
