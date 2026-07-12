#!/usr/bin/env python3
"""Collect RFantibody ProteinMPNN outputs into a balanced 1,000-sequence pool."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import pickle
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")
SETS = ("A", "B", "C", "D")
HOTSPOTS = {
    "A": "T57,T101,T106",
    "B": "T62,T101,T106",
    "C": "T97,T101,T105,T106",
    "D": "T33,T36,T105,T106",
}
UNIPROT = {
    "A": "R95,F139,W144",
    "B": "W100,F139,W144",
    "C": "K135,F139,S143,W144",
    "D": "S71,T74,S143,W144",
}
TAG_RE = re.compile(r"design_(\d+)_dldesign_(\d+)\.pdb$")
BACKBONE_PDB_RE = re.compile(r"design_(\d+)\.pdb$")
BACKBONE_TRB_RE = re.compile(r"design_(\d+)\.trb$")

RFANTIBODY_PYTHON = Path("/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python")
if __name__ == "__main__" and Path(sys.executable).resolve() != RFANTIBODY_PYTHON.resolve():
    if RFANTIBODY_PYTHON.is_file():
        os.execv(
            str(RFANTIBODY_PYTHON),
            [str(RFANTIBODY_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
        )
    if Path("/data/qlyu/software/RFantibody").exists():
        raise RuntimeError(f"RFantibody Python is missing: {RFANTIBODY_PYTHON}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("/data/qlyu/projects/pvrig_rfantibody_1000_20260712"),
    )
    parser.add_argument("--target-count", type=int, default=1000)
    parser.add_argument("--per-set", type=int, default=250)
    parser.add_argument("--initial-sibling-cap", type=int, default=5)
    parser.add_argument("--leakage-reference", type=Path, default=None)
    parser.add_argument("--expected-backbones-per-set", type=int, default=50)
    parser.add_argument("--expected-sequences-per-backbone", type=int, default=8)
    return parser.parse_args()


def parse_fasta(path: Path) -> dict[str, list[str]]:
    by_sequence: dict[str, list[str]] = defaultdict(list)
    name: str | None = None
    chunks: list[str] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                by_sequence["".join(chunks).upper()].append(name)
            name = line[1:]
            chunks = []
        else:
            chunks.append(line.replace(" ", ""))
    if name is not None:
        by_sequence["".join(chunks).upper()].append(name)
    return by_sequence


def parse_pdb(path: Path) -> tuple[str, dict[str, str], list[str]]:
    residues: dict[tuple[str, int, str], str] = {}
    labels: dict[str, list[int]] = defaultdict(list)
    errors: list[str] = []

    for line in path.read_text().splitlines():
        if line.startswith("ATOM  ") and len(line) >= 27:
            if line[21] != "H" or line[12:16].strip() != "CA":
                continue
            altloc = line[16]
            if altloc not in (" ", "A"):
                continue
            try:
                residue_id = int(line[22:26])
            except ValueError:
                errors.append("malformed_atom_residue_number")
                continue
            insertion_code = line[26]
            if insertion_code != " ":
                errors.append("unsupported_insertion_code")
            key = (line[21], residue_id, insertion_code)
            aa = AA3_TO_1.get(line[17:20].strip())
            if aa is None:
                errors.append(f"unknown_residue:{line[17:20].strip()}")
                continue
            residues.setdefault(key, aa)
        elif line.startswith("REMARK PDBinfo-LABEL:"):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    labels[parts[-1]].append(int(parts[-2]))
                except ValueError:
                    errors.append("malformed_cdr_label")
            else:
                errors.append("malformed_cdr_label")

    ordered = sorted(residues.items(), key=lambda item: (item[0][1], item[0][2]))
    sequence = "".join(aa for _, aa in ordered)
    residue_number_counts = Counter(key[1] for key, _ in ordered)
    if any(count > 1 for count in residue_number_counts.values()):
        errors.append("duplicate_H_chain_residue_number")
    by_resid = {key[1]: aa for key, aa in ordered}
    cdrs = {
        cdr: "".join(by_resid[n] for n in sorted(set(labels.get(cdr, []))) if n in by_resid)
        for cdr in ("H1", "H2", "H3")
    }

    if not sequence:
        errors.append("empty_H_chain")
    if set(sequence) - VALID_AA:
        errors.append("noncanonical_amino_acid")
    if not 105 <= len(sequence) <= 140:
        errors.append("unexpected_length")
    for cdr in ("H1", "H2", "H3"):
        if not cdrs[cdr]:
            errors.append(f"missing_{cdr}")
    if len(cdrs["H1"]) != 7:
        errors.append("unexpected_H1_length")
    if len(cdrs["H2"]) != 6:
        errors.append("unexpected_H2_length")
    if not 5 <= len(cdrs["H3"]) <= 13:
        errors.append("unexpected_H3_length")

    return sequence, cdrs, errors


def load_trb(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        data = pickle.load(handle)
    required = {"plddt", "mindist", "averagemin", "H1_len", "H2_len", "H3_len"}
    missing = sorted(required - set(data))
    if missing:
        raise RuntimeError(f"{path} is missing TRB keys: {','.join(missing)}")
    try:
        final_plddt_mean = float(data["plddt"][-1].mean())
    except (IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError(f"Cannot decode final pLDDT from {path}: {exc}") from exc
    mindist = float(data["mindist"])
    if mindist <= 8.0:
        distance_bin = "le_8A"
    elif mindist <= 10.0:
        distance_bin = "8_to_10A"
    else:
        distance_bin = "gt_10A"
    return {
        "rfd_mindist": mindist,
        "rfd_averagemin": float(data["averagemin"]),
        "rfd_hotspot_distance_bin": distance_bin,
        "rfd_final_plddt_mean": final_plddt_mean,
        "h1_len": int(data["H1_len"]),
        "h2_len": int(data["H2_len"]),
        "h3_len": int(data["H3_len"]),
    }


def validate_generation_shape(
    run_root: Path,
    expected_backbones: int,
    expected_sequences: int,
) -> None:
    errors: list[str] = []
    expected_backbone_indices = set(range(expected_backbones))
    expected_pairs = {
        (backbone_index, mpnn_index)
        for backbone_index in range(expected_backbones)
        for mpnn_index in range(expected_sequences)
    }

    for set_id in SETS:
        set_dir = run_root / "sets" / f"set_{set_id}"
        backbone_dir = set_dir / "backbones"
        sequence_dir = set_dir / "sequences"
        if not (set_dir / "complete.json").is_file():
            errors.append(f"set_{set_id}:missing_complete_marker")

        pdb_indices: set[int] = set()
        for path in backbone_dir.glob("design_*.pdb"):
            match = BACKBONE_PDB_RE.fullmatch(path.name)
            if match is None:
                errors.append(f"set_{set_id}:malformed_backbone_pdb:{path.name}")
            else:
                pdb_indices.add(int(match.group(1)))

        trb_indices: set[int] = set()
        for path in backbone_dir.glob("design_*.trb"):
            match = BACKBONE_TRB_RE.fullmatch(path.name)
            if match is None:
                errors.append(f"set_{set_id}:malformed_backbone_trb:{path.name}")
            else:
                trb_indices.add(int(match.group(1)))

        sequence_pairs: set[tuple[int, int]] = set()
        for path in sequence_dir.glob("design_*_dldesign_*.pdb"):
            match = TAG_RE.fullmatch(path.name)
            if match is None:
                errors.append(f"set_{set_id}:malformed_sequence_pdb:{path.name}")
            else:
                sequence_pairs.add((int(match.group(1)), int(match.group(2))))

        if pdb_indices != expected_backbone_indices:
            errors.append(
                f"set_{set_id}:backbone_pdb_indices="
                f"missing{sorted(expected_backbone_indices - pdb_indices)}:"
                f"extra{sorted(pdb_indices - expected_backbone_indices)}"
            )
        if trb_indices != expected_backbone_indices:
            errors.append(
                f"set_{set_id}:backbone_trb_indices="
                f"missing{sorted(expected_backbone_indices - trb_indices)}:"
                f"extra{sorted(trb_indices - expected_backbone_indices)}"
            )
        if sequence_pairs != expected_pairs:
            errors.append(
                f"set_{set_id}:sequence_indices="
                f"missing{sorted(expected_pairs - sequence_pairs)}:"
                f"extra{sorted(sequence_pairs - expected_pairs)}"
            )

        for index in sorted(trb_indices & expected_backbone_indices):
            try:
                load_trb(backbone_dir / f"design_{index}.trb")
            except Exception as exc:
                errors.append(f"set_{set_id}:invalid_trb_{index}:{exc}")

    if errors:
        preview = "\n".join(errors[:40])
        suffix = "" if len(errors) <= 40 else f"\n... {len(errors) - 40} more errors"
        raise RuntimeError(f"Generation preflight failed:\n{preview}{suffix}")


def collect(run_root: Path, leakage_reference: dict[str, list[str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for set_id in SETS:
        sequence_dir = run_root / "sets" / f"set_{set_id}" / "sequences"
        backbone_dir = run_root / "sets" / f"set_{set_id}" / "backbones"
        for pdb_path in sorted(sequence_dir.glob("design_*_dldesign_*.pdb")):
            match = TAG_RE.search(pdb_path.name)
            if not match:
                continue
            backbone_index, mpnn_index = map(int, match.groups())
            sequence, cdrs, errors = parse_pdb(pdb_path)
            leakage_ids = leakage_reference.get(sequence, [])
            backbone_path = backbone_dir / f"design_{backbone_index}.pdb"
            trb_path = backbone_dir / f"design_{backbone_index}.trb"
            trb = load_trb(trb_path)
            expected_cdr_lengths = {
                "H1": int(trb["h1_len"]),
                "H2": int(trb["h2_len"]),
                "H3": int(trb["h3_len"]),
            }
            for cdr, expected_length in expected_cdr_lengths.items():
                if len(cdrs[cdr]) != expected_length:
                    errors.append(f"{cdr}_length_disagrees_with_trb")
            rows.append({
                "candidate_id": f"PVRIG_RFAb_v0_{set_id}_bb{backbone_index:03d}_mpn{mpnn_index:02d}",
                "hotspot_set": set_id,
                "hotspots_pdb": HOTSPOTS[set_id],
                "hotspots_uniprot": UNIPROT[set_id],
                "framework_id": "h-NbBCII10",
                "backbone_index": backbone_index,
                "mpnn_index": mpnn_index,
                "sequence": sequence,
                "sequence_length": len(sequence),
                "cdr1": cdrs["H1"],
                "cdr2": cdrs["H2"],
                "cdr3": cdrs["H3"],
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "valid_sequence": not errors,
                "validation_errors": ";".join(sorted(set(errors))),
                "exact_known_positive_match": bool(leakage_ids),
                "exact_known_positive_ids": ";".join(leakage_ids),
                "backbone_pdb": str(backbone_path),
                "backbone_trb": str(trb_path),
                "mpnn_pdb": str(pdb_path),
                "rf2_status": "not_run_by_generation_plan",
                "final_label": (
                    "FAIL_SEQUENCE_FORMAT" if errors
                    else "EXCLUDE_EXACT_KNOWN_POSITIVE_CONTROL" if leakage_ids
                    else "PASS_SEQUENCE_GENERATION_NEEDS_RF2_DOCKING"
                ),
                **trb,
            })
    return rows


@dataclass
class FlowEdge:
    to: int
    reverse: int
    capacity: int
    original_capacity: int


class Dinic:
    def __init__(self) -> None:
        self.graph: list[list[FlowEdge]] = []

    def node(self) -> int:
        self.graph.append([])
        return len(self.graph) - 1

    def add_edge(self, source: int, target: int, capacity: int) -> FlowEdge:
        forward = FlowEdge(target, len(self.graph[target]), capacity, capacity)
        reverse = FlowEdge(source, len(self.graph[source]), 0, 0)
        self.graph[source].append(forward)
        self.graph[target].append(reverse)
        return forward

    def max_flow(self, source: int, target: int) -> int:
        flow = 0
        while True:
            level = [-1] * len(self.graph)
            level[source] = 0
            queue = [source]
            for node in queue:
                for edge in self.graph[node]:
                    if edge.capacity > 0 and level[edge.to] < 0:
                        level[edge.to] = level[node] + 1
                        queue.append(edge.to)
            if level[target] < 0:
                return flow

            cursor = [0] * len(self.graph)

            def send(node: int, amount: int) -> int:
                if node == target:
                    return amount
                while cursor[node] < len(self.graph[node]):
                    edge = self.graph[node][cursor[node]]
                    if edge.capacity > 0 and level[node] + 1 == level[edge.to]:
                        pushed = send(edge.to, min(amount, edge.capacity))
                        if pushed:
                            edge.capacity -= pushed
                            self.graph[edge.to][edge.reverse].capacity += pushed
                            return pushed
                    cursor[node] += 1
                return 0

            while True:
                pushed = send(source, 10**9)
                if not pushed:
                    break
                flow += pushed


def select_balanced(
    rows: list[dict[str, object]], per_set: int, initial_sibling_cap: int
) -> list[dict[str, object]]:
    candidates = [
        row for row in rows
        if row["valid_sequence"] and not row["exact_known_positive_match"]
    ]
    candidates.sort(
        key=lambda row: (
            str(row["hotspot_set"]),
            int(row["mpnn_index"]),
            int(row["backbone_index"]),
        )
    )
    row_by_edge_key: dict[tuple[str, int, str], dict[str, object]] = {}
    for row in candidates:
        key = (
            str(row["hotspot_set"]),
            int(row["backbone_index"]),
            str(row["sequence_sha256"]),
        )
        row_by_edge_key.setdefault(key, row)

    target_total = per_set * len(SETS)
    for sibling_cap in range(initial_sibling_cap, 9):
        flow = Dinic()
        source = flow.node()
        sink = flow.node()
        set_nodes = {set_id: flow.node() for set_id in SETS}
        backbone_nodes = {
            (set_id, backbone_index): flow.node()
            for set_id, backbone_index, _ in row_by_edge_key
        }
        digest_nodes = {
            digest: flow.node() for _, _, digest in row_by_edge_key
        }

        for set_id in SETS:
            flow.add_edge(source, set_nodes[set_id], per_set)
        for set_id, backbone_index in backbone_nodes:
            flow.add_edge(
                set_nodes[set_id], backbone_nodes[(set_id, backbone_index)], sibling_cap
            )
        for digest, node in digest_nodes.items():
            flow.add_edge(node, sink, 1)

        candidate_edges: list[tuple[FlowEdge, dict[str, object]]] = []
        for key, row in row_by_edge_key.items():
            set_id, backbone_index, digest = key
            edge = flow.add_edge(
                backbone_nodes[(set_id, backbone_index)], digest_nodes[digest], 1
            )
            candidate_edges.append((edge, row))

        achieved = flow.max_flow(source, sink)
        if achieved == target_total:
            selected = [
                row for edge, row in candidate_edges
                if edge.original_capacity == 1 and edge.capacity == 0
            ]
            selected.sort(
                key=lambda row: (
                    str(row["hotspot_set"]),
                    int(row["backbone_index"]),
                    int(row["mpnn_index"]),
                )
            )
            return selected

    available = Counter(str(row["hotspot_set"]) for row in candidates)
    raise RuntimeError(
        f"Could not assign {per_set} globally unique sequences to every hotspot set; "
        f"maximum flow remained below {target_total}; available={dict(available)}. "
        "Run a top-up before finalizing."
    )


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"No rows available for {path}")
    fields = list(rows[0].keys())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def summarize_numeric(values: list[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {
        "count": len(clean),
        "min": min(clean),
        "median": statistics.median(clean),
        "max": max(clean),
    }


def main() -> None:
    args = parse_args()
    if args.target_count != args.per_set * len(SETS):
        raise SystemExit("target-count must equal per-set multiplied by four hotspot sets")

    final_dir = args.run_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    leakage_path = args.leakage_reference or args.run_root / "inputs" / "leakage_reference.fasta"
    if not leakage_path.is_file():
        raise RuntimeError(f"Required leakage reference is missing: {leakage_path}")
    leakage_reference = parse_fasta(leakage_path)
    if not leakage_reference:
        raise RuntimeError(f"Leakage reference contains no sequences: {leakage_path}")

    validate_generation_shape(
        args.run_root,
        args.expected_backbones_per_set,
        args.expected_sequences_per_backbone,
    )

    staging_dir = final_dir / f".staging-{os.getpid()}"
    staging_dir.mkdir(parents=False, exist_ok=False)
    rows = collect(args.run_root, leakage_reference)
    write_tsv(staging_dir / "raw_candidates.tsv", rows)

    selected = select_balanced(rows, args.per_set, args.initial_sibling_cap)
    if len(selected) != args.target_count:
        raise RuntimeError(f"selected {len(selected)} rows, expected {args.target_count}")

    write_tsv(staging_dir / "pvrig_rfantibody_1000.tsv", selected)
    with (staging_dir / "pvrig_rfantibody_1000.fasta").open("w") as handle:
        for row in selected:
            handle.write(
                f">{row['candidate_id']}|hotspot_set={row['hotspot_set']}|"
                f"backbone={row['backbone_index']}|mpnn={row['mpnn_index']}|"
                "status=NEEDS_RF2_DOCKING\n"
            )
            handle.write(str(row["sequence"]) + "\n")

    raw_hash_counts = Counter(str(row["sequence_sha256"]) for row in rows if row["valid_sequence"])
    selected_by_set = Counter(str(row["hotspot_set"]) for row in selected)
    selected_by_backbone = Counter(
        (str(row["hotspot_set"]), int(row["backbone_index"])) for row in selected
    )
    raw_valid_by_set = Counter(
        str(row["hotspot_set"]) for row in rows if row["valid_sequence"]
    )
    raw_unique_by_set = {
        set_id: len({
            str(row["sequence_sha256"])
            for row in rows
            if row["hotspot_set"] == set_id and row["valid_sequence"]
        })
        for set_id in SETS
    }
    pose_distance_summary = {
        set_id: {
            "mindist": summarize_numeric([
                row["rfd_mindist"] for row in rows
                if row["hotspot_set"] == set_id
            ]),
            "averagemin": summarize_numeric([
                row["rfd_averagemin"] for row in rows
                if row["hotspot_set"] == set_id
            ]),
            "backbones_mindist_le_8A": len({
                int(row["backbone_index"])
                for row in rows
                if row["hotspot_set"] == set_id
                and row["rfd_mindist"] is not None
                and float(row["rfd_mindist"]) <= 8.0
            }),
            "backbones_mindist_le_10A": len({
                int(row["backbone_index"])
                for row in rows
                if row["hotspot_set"] == set_id
                and row["rfd_mindist"] is not None
                and float(row["rfd_mindist"]) <= 10.0
            }),
        }
        for set_id in SETS
    }
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_root": str(args.run_root),
        "generation_shape_validated": True,
        "expected_backbones_per_hotspot_set": args.expected_backbones_per_set,
        "expected_sequences_per_backbone": args.expected_sequences_per_backbone,
        "raw_pdb_records": len(rows),
        "raw_valid_records": sum(bool(row["valid_sequence"]) for row in rows),
        "raw_unique_sequences": len(raw_hash_counts),
        "raw_duplicate_records": sum(count - 1 for count in raw_hash_counts.values()),
        "exact_known_positive_reference_sequences": len(leakage_reference),
        "exact_known_positive_matches": sum(
            bool(row["exact_known_positive_match"]) for row in rows
        ),
        "raw_valid_by_hotspot_set": dict(sorted(raw_valid_by_set.items())),
        "raw_unique_by_hotspot_set": raw_unique_by_set,
        "raw_sequence_length_distribution": dict(sorted(Counter(
            int(row["sequence_length"]) for row in rows if row["valid_sequence"]
        ).items())),
        "raw_cdr3_length_distribution": dict(sorted(Counter(
            len(str(row["cdr3"])) for row in rows if row["valid_sequence"]
        ).items())),
        "rf_diffusion_hotspot_distance_summary": pose_distance_summary,
        "selected_records": len(selected),
        "selected_unique_sequences": len({row["sequence_sha256"] for row in selected}),
        "selected_by_hotspot_set": dict(sorted(selected_by_set.items())),
        "selected_unique_backbones": len(selected_by_backbone),
        "selected_max_siblings_per_backbone": max(selected_by_backbone.values()),
        "rf2_status": "not_run_by_generation_plan",
        "scientific_boundary": "Generated hotspot-conditioned candidates are not validated binders or blockers.",
    }
    (staging_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    deliverables = [
        "raw_candidates.tsv",
        "pvrig_rfantibody_1000.tsv",
        "pvrig_rfantibody_1000.fasta",
        "summary.json",
    ]
    manifest = [
        f"{hashlib.sha256((staging_dir / name).read_bytes()).hexdigest()}  {name}"
        for name in deliverables
    ]
    (staging_dir / "sha256sums.txt").write_text("\n".join(manifest) + "\n")

    for name in [*deliverables, "sha256sums.txt"]:
        (staging_dir / name).replace(final_dir / name)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
