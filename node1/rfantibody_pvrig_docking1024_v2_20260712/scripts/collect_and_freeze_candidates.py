#!/usr/bin/env python3
"""Collect all V2 MPNN outputs and freeze an exact-unique 1,024-candidate cohort."""

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
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path


AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}
VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")
TAG_RE = re.compile(r"design_(\d+)_dldesign_(\d+)\.pdb$")
BACKBONE_RE = re.compile(r"design_(\d+)\.pdb$")
RFANTIBODY_PYTHON = Path("/data/qlyu/anaconda3/envs/rfdiffusion2/bin/python")


def ensure_runtime() -> None:
    if Path("/data/qlyu/software/RFantibody").exists() and Path(sys.executable).resolve() != RFANTIBODY_PYTHON.resolve():
        if not RFANTIBODY_PYTHON.is_file():
            raise RuntimeError(f"RFantibody Python is missing: {RFANTIBODY_PYTHON}")
        os.execv(str(RFANTIBODY_PYTHON), [str(RFANTIBODY_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_fasta(path: Path) -> dict[str, list[str]]:
    by_sequence: dict[str, list[str]] = defaultdict(list)
    name: str | None = None
    chunks: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                by_sequence["".join(chunks).upper()].append(name)
            name, chunks = line[1:], []
        else:
            chunks.append(line.replace(" ", ""))
    if name is not None:
        by_sequence["".join(chunks).upper()].append(name)
    return by_sequence


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pdb(path: Path) -> tuple[str, dict[str, str], list[str]]:
    residues: dict[int, str] = {}
    labels: defaultdict[str, list[int]] = defaultdict(list)
    errors: list[str] = []
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if line.startswith("ATOM") and len(line) >= 27 and line[21] == "H" and line[12:16].strip() == "CA":
            if line[16] not in (" ", "A"):
                continue
            try:
                residue_id = int(line[22:26])
            except ValueError:
                errors.append("malformed_residue_number")
                continue
            aa = AA3_TO_1.get(line[17:20].strip())
            if aa is None:
                errors.append(f"unsupported_residue:{line[17:20].strip()}")
            elif residue_id in residues and residues[residue_id] != aa:
                errors.append("duplicate_residue_number")
            else:
                residues.setdefault(residue_id, aa)
        elif line.startswith("REMARK PDBinfo-LABEL:"):
            parts = line.split()
            if len(parts) >= 4 and parts[-1] in {"H1", "H2", "H3"}:
                try:
                    labels[parts[-1]].append(int(parts[-2]))
                except ValueError:
                    errors.append("malformed_cdr_label")

    sequence = "".join(residues[index] for index in sorted(residues))
    cdrs = {
        label: "".join(residues[index] for index in sorted(set(labels[label])) if index in residues)
        for label in ("H1", "H2", "H3")
    }
    if not sequence:
        errors.append("empty_H_chain")
    if set(sequence) - VALID_AA:
        errors.append("noncanonical_amino_acid")
    if not 105 <= len(sequence) <= 145:
        errors.append("unexpected_sequence_length")
    if len(cdrs["H1"]) != 7:
        errors.append("unexpected_H1_length")
    if len(cdrs["H2"]) != 6:
        errors.append("unexpected_H2_length")
    if not 5 <= len(cdrs["H3"]) <= 15:
        errors.append("unexpected_H3_length")
    return sequence, cdrs, sorted(set(errors))


def load_trb(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        data = pickle.load(handle)
    required = {"plddt", "mindist", "averagemin", "H1_len", "H2_len", "H3_len"}
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"{path} missing TRB fields: {missing}")
    return {
        "rfd_mindist": float(data["mindist"]),
        "rfd_averagemin": float(data["averagemin"]),
        "rfd_final_plddt_mean": float(data["plddt"][-1].mean()),
        "trb_h1_length": int(data["H1_len"]),
        "trb_h2_length": int(data["H2_len"]),
        "trb_h3_length": int(data["H3_len"]),
    }


def collect(run_root: Path, arms: list[dict[str, str]], references: dict[str, list[str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for arm in arms:
        arm_id = arm["arm_id"]
        arm_root = run_root / "generation" / "arms" / arm_id
        if not (arm_root / "complete.json").is_file():
            raise ValueError(f"arm is not complete: {arm_id}")
        expected_backbones = int(arm["target_backbones"])
        expected_sequences = int(arm["seqs_per_backbone"])
        backbone_indices = {
            int(match.group(1))
            for path in (arm_root / "backbones").glob("design_*.pdb")
            if (match := BACKBONE_RE.fullmatch(path.name))
        }
        if len(backbone_indices) != expected_backbones:
            raise ValueError(f"{arm_id}: expected {expected_backbones} backbones, found {len(backbone_indices)}")
        for pdb_path in sorted((arm_root / "sequences").glob("design_*_dldesign_*.pdb")):
            match = TAG_RE.fullmatch(pdb_path.name)
            if match is None:
                continue
            backbone_index, mpnn_index = map(int, match.groups())
            sequence, cdrs, errors = parse_pdb(pdb_path)
            backbone_pdb = arm_root / "backbones" / f"design_{backbone_index}.pdb"
            backbone_trb = arm_root / "backbones" / f"design_{backbone_index}.trb"
            trb = load_trb(backbone_trb)
            if len(cdrs["H1"]) != trb["trb_h1_length"]:
                errors.append("H1_length_disagrees_with_trb")
            if len(cdrs["H2"]) != trb["trb_h2_length"]:
                errors.append("H2_length_disagrees_with_trb")
            if len(cdrs["H3"]) != trb["trb_h3_length"]:
                errors.append("H3_length_disagrees_with_trb")
            digest = hashlib.sha256(sequence.encode()).hexdigest()
            exact_ids = references.get(sequence, [])
            candidate_id = f"PVRIG_RFAb_v2_{arm_id}_bb{backbone_index:03d}_mpn{mpnn_index:02d}"
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "source_run_id": run_root.name,
                    **arm,
                    "backbone_index": backbone_index,
                    "mpnn_index": mpnn_index,
                    "backbone_group_id": f"{arm_id}_bb{backbone_index:03d}",
                    "sequence": sequence,
                    "sequence_length": len(sequence),
                    "cdr1": cdrs["H1"],
                    "cdr2": cdrs["H2"],
                    "cdr3": cdrs["H3"],
                    "cdr1_length": len(cdrs["H1"]),
                    "cdr2_length": len(cdrs["H2"]),
                    "cdr3_length": len(cdrs["H3"]),
                    "sequence_sha256": digest,
                    "sequence_group_id": digest,
                    "valid_sequence": not errors,
                    "validation_errors": ";".join(sorted(set(errors))),
                    "exact_known_positive_match": bool(exact_ids),
                    "exact_known_positive_ids": ";".join(exact_ids),
                    "backbone_pdb": str(backbone_pdb),
                    "backbone_pdb_sha256": sha256_file(backbone_pdb),
                    "backbone_trb": str(backbone_trb),
                    "mpnn_pdb": str(pdb_path),
                    "mpnn_pdb_sha256": sha256_file(pdb_path),
                    "mpnn_nll_score": "",
                    "mpnn_score_missing_reason": "not_emitted_in_rfantibody_pdb",
                    **trb,
                }
            )
        found = sum(1 for row in rows if row["arm_id"] == arm_id)
        expected = expected_backbones * expected_sequences
        if found != expected:
            raise ValueError(f"{arm_id}: expected {expected} sequence PDBs, found {found}")
    return rows


def select_balanced(rows: list[dict[str, object]], target: int) -> list[dict[str, object]]:
    eligible = [
        row
        for row in rows
        if row["valid_sequence"]
        and not row["exact_known_positive_match"]
        and row["scaffold_lane"] == "primary_vhhified"
    ]
    by_arm: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in eligible:
        by_arm[str(row["arm_id"])].append(row)
    arm_ids = sorted(by_arm)
    if len(arm_ids) != 36:
        raise ValueError(f"expected 36 primary VHHified arms, found {len(arm_ids)}")

    ideal_base, _ = divmod(target, len(arm_ids))

    def priority(row: dict[str, object]) -> tuple[object, ...]:
        return (
            float(row["rfd_mindist"]) > 8.0,
            float(row["rfd_averagemin"]) > 8.5,
            float(row["rfd_mindist"]),
            float(row["rfd_averagemin"]),
            int(row["mpnn_index"]),
            str(row["candidate_id"]),
        )

    # Build a deterministic one-per-backbone round-robin order for every arm.
    ordered_digests: dict[str, list[str]] = {}
    row_by_arm_digest: dict[tuple[str, str], dict[str, object]] = {}
    for arm_id in arm_ids:
        candidates = sorted(by_arm[arm_id], key=priority)
        by_backbone: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        for row in candidates:
            by_backbone[str(row["backbone_group_id"])].append(row)
        order: list[str] = []
        seen: set[str] = set()
        max_depth = max((len(value) for value in by_backbone.values()), default=0)
        for depth in range(max_depth):
            for backbone_id in sorted(by_backbone):
                siblings = by_backbone[backbone_id]
                if depth >= len(siblings):
                    continue
                row = siblings[depth]
                digest = str(row["sequence_sha256"])
                if digest in seen:
                    continue
                seen.add(digest)
                order.append(digest)
                row_by_arm_digest[(arm_id, digest)] = row
        ordered_digests[arm_id] = order

    class Dinic:
        def __init__(self, node_count: int) -> None:
            self.graph: list[list[list[int]]] = [[] for _ in range(node_count)]

        def add_edge(self, source: int, target_node: int, capacity: int) -> list[int]:
            forward = [target_node, len(self.graph[target_node]), capacity]
            reverse = [source, len(self.graph[source]), 0]
            self.graph[source].append(forward)
            self.graph[target_node].append(reverse)
            return forward

        def max_flow(self, source: int, sink: int, limit: int) -> int:
            total = 0
            while total < limit:
                level = [-1] * len(self.graph)
                level[source] = 0
                queue = deque([source])
                while queue:
                    node = queue.popleft()
                    for edge in self.graph[node]:
                        if edge[2] and level[edge[0]] < 0:
                            level[edge[0]] = level[node] + 1
                            queue.append(edge[0])
                if level[sink] < 0:
                    break
                cursor = [0] * len(self.graph)

                def send(node: int, amount: int) -> int:
                    if node == sink:
                        return amount
                    while cursor[node] < len(self.graph[node]):
                        edge = self.graph[node][cursor[node]]
                        if edge[2] and level[edge[0]] == level[node] + 1:
                            pushed = send(edge[0], min(amount, edge[2]))
                            if pushed:
                                edge[2] -= pushed
                                self.graph[edge[0]][edge[1]][2] += pushed
                                return pushed
                        cursor[node] += 1
                    return 0

                while total < limit:
                    pushed = send(source, limit - total)
                    if not pushed:
                        break
                    total += pushed
            return total

    all_digests = sorted({digest for digests in ordered_digests.values() for digest in digests})
    source = 0
    arm_node = {arm_id: index + 1 for index, arm_id in enumerate(arm_ids)}
    digest_offset = 1 + len(arm_ids)
    digest_node = {digest: digest_offset + index for index, digest in enumerate(all_digests)}
    sink = digest_offset + len(all_digests)
    def build_network(base_capacity: int) -> tuple[Dinic, dict[str, list[tuple[str, list[int]]]]]:
        network = Dinic(sink + 1)
        edge_map: dict[str, list[tuple[str, list[int]]]] = defaultdict(list)
        for arm_id in arm_ids:
            network.add_edge(source, arm_node[arm_id], base_capacity)
            for digest in ordered_digests[arm_id]:
                edge = network.add_edge(arm_node[arm_id], digest_node[digest], 1)
                edge_map[arm_id].append((digest, edge))
        for digest in all_digests:
            network.add_edge(digest_node[digest], sink, 1)
        return network, edge_map

    base_capacity = ideal_base
    while base_capacity >= 0:
        flow, arm_digest_edges = build_network(base_capacity)
        base_target = base_capacity * len(arm_ids)
        if flow.max_flow(source, sink, base_target) == base_target:
            break
        base_capacity -= 1
    if base_capacity < 0:
        raise ValueError("could not construct a balanced exact-unique base cohort")

    remaining = target - base_capacity * len(arm_ids)
    extra_rounds = 0
    while remaining > 0:
        for arm_id in arm_ids:
            flow.add_edge(source, arm_node[arm_id], 1)
        gained = flow.max_flow(source, sink, min(remaining, len(arm_ids)))
        extra_rounds += 1
        remaining -= gained
        if gained == 0:
            break
    if remaining:
        raise ValueError(
            f"could not reach exact-unique cohort target after balanced relaxation: missing={remaining} target={target}"
        )

    selected = [
        row_by_arm_digest[(arm_id, digest)]
        for arm_id in arm_ids
        for digest, edge in arm_digest_edges[arm_id]
        if edge[2] == 0
    ]
    selected_sequences = {str(row["sequence_sha256"]) for row in selected}
    selected_by_arm = Counter(str(row["arm_id"]) for row in selected)
    if (
        len(selected) != target
        or len(selected_sequences) != target
        or len(selected_by_arm) != len(arm_ids)
        or min(selected_by_arm.values()) < base_capacity
        or max(selected_by_arm.values()) > base_capacity + extra_rounds
    ):
        raise ValueError(
            f"invalid matched cohort: selected={len(selected)} unique={len(selected_sequences)} "
            f"selected_by_arm={dict(sorted(selected_by_arm.items()))}"
        )
    selected.sort(key=lambda row: str(row["candidate_id"]))
    for rank, row in enumerate(selected, start=1):
        row["docking_cohort_rank"] = rank
        row["selected_for_docking"] = True
        row["selection_policy"] = "primary_vhhified_adaptive_balanced_maxflow_exact_unique_backbone_round_robin_rfd_geometry_priority"
    return selected


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"no rows for {path}")
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def numeric_summary(values: list[float]) -> dict[str, object]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "median": statistics.median(values) if values else None,
        "max": max(values) if values else None,
    }


def main() -> int:
    ensure_runtime()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=Path("/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712"))
    parser.add_argument("--arms-path", type=Path, help="Arm table to collect; defaults to config/generation_arms.tsv")
    parser.add_argument("--target", type=int, default=1024)
    args = parser.parse_args()

    arms_path = args.arms_path or args.run_root / "config" / "generation_arms.tsv"
    execution_policy_path = args.run_root / "config" / "generation_execution_policy.json"
    leakage_path = args.run_root / "inputs" / "leakage_reference.fasta"
    arms = read_tsv(arms_path)
    references = parse_fasta(leakage_path)
    rows = collect(args.run_root, arms, references)
    selected = select_balanced(rows, args.target)

    data_root = args.run_root / "data"
    write_tsv(data_root / "candidates_raw.tsv", rows)
    write_tsv(data_root / "candidates.tsv", selected)
    write_tsv(
        data_root / "backbone_groups.tsv",
        [
            {
                "backbone_group_id": row["backbone_group_id"],
                "arm_id": row["arm_id"],
                "patch_id": row["patch_id"],
                "scaffold_id": row["scaffold_id"],
                "h3_regime": row["h3_regime"],
                "backbone_index": row["backbone_index"],
                "backbone_pdb": row["backbone_pdb"],
                "backbone_pdb_sha256": row["backbone_pdb_sha256"],
            }
            for row in {str(item["backbone_group_id"]): item for item in selected}.values()
        ],
    )
    with (data_root / "candidates.fasta").open("w", encoding="ascii") as handle:
        for row in selected:
            handle.write(
                f">{row['candidate_id']}|arm={row['arm_id']}|backbone={row['backbone_group_id']}|status=NEEDS_RF2_AND_DOCKING\n"
            )
            handle.write(str(row["sequence"]) + "\n")

    selected_backbones = Counter(str(row["backbone_group_id"]) for row in selected)
    summary = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_root": str(args.run_root),
        "arm_table_path": str(arms_path),
        "arm_table_sha256": sha256_file(arms_path),
        "generation_execution_policy_path": str(execution_policy_path),
        "generation_execution_policy_sha256": sha256_file(execution_policy_path) if execution_policy_path.is_file() else "",
        "arm_count": len(arms),
        "arm_counts_by_lane": dict(sorted(Counter(row["scaffold_lane"] for row in arms).items())),
        "expected_backbones_from_arm_table": sum(int(row["target_backbones"]) for row in arms),
        "expected_sequence_records_from_arm_table": sum(
            int(row["target_backbones"]) * int(row["seqs_per_backbone"]) for row in arms
        ),
        "raw_records": len(rows),
        "raw_valid_records": sum(bool(row["valid_sequence"]) for row in rows),
        "raw_unique_sequences": len({row["sequence_sha256"] for row in rows if row["valid_sequence"]}),
        "raw_exact_known_positive_matches": sum(bool(row["exact_known_positive_match"]) for row in rows),
        "selected_records": len(selected),
        "selected_exact_unique_sequences": len({row["sequence_sha256"] for row in selected}),
        "selected_unique_backbones": len(selected_backbones),
        "selected_max_siblings_per_backbone": max(selected_backbones.values()),
        "selected_by_arm": dict(sorted(Counter(str(row["arm_id"]) for row in selected).items())),
        "selected_by_patch": dict(sorted(Counter(str(row["patch_id"]) for row in selected).items())),
        "selected_by_scaffold": dict(sorted(Counter(str(row["scaffold_id"]) for row in selected).items())),
        "selected_by_h3_regime": dict(sorted(Counter(str(row["h3_regime"]) for row in selected).items())),
        "selected_rfd_mindist": numeric_summary([float(row["rfd_mindist"]) for row in selected]),
        "selected_rfd_averagemin": numeric_summary([float(row["rfd_averagemin"]) for row in selected]),
        "rf2_status": "not_run",
        "docking_status": "not_run",
        "claim_boundary": "generated candidates are not experimentally verified binders or blockers",
    }
    (data_root / "generation_freeze_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name in ("candidates_raw.tsv", "candidates.tsv", "backbone_groups.tsv", "candidates.fasta", "generation_freeze_summary.json"):
        path = data_root / name
        (data_root / f"{name}.sha256").write_text(f"{sha256_file(path)}  {name}\n", encoding="ascii")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
