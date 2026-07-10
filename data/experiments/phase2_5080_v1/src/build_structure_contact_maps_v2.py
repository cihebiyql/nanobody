#!/usr/bin/env python3
"""Build real sequence-indexed heavy-atom contact-map records for Phase 2 V2.

Outputs JSONL records with VHH sequence, antigen sequence, true positive residue
pairs at <=4.5 A, and sampled non-contact pairs at >=8.0 A. Residue indices are
0-based sequence indices reconstructed per chain from mmCIF atom_site label/auth
sequence ids.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shlex
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

AA3 = {
    "ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F", "GLY": "G", "HIS": "H", "ILE": "I", "LYS": "K", "LEU": "L",
    "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R", "SER": "S", "THR": "T", "VAL": "V", "TRP": "W", "TYR": "Y",
    "SEC": "C", "PYL": "K", "MSE": "M",
}
HEAVY_SKIP = {"H", "D"}


def clean(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    text = str(v).strip()
    if text.lower() in {"nan", "none", "na", "n/a", "?", "."}:
        return ""
    return text


def split_chains(value: Any) -> list[str]:
    text = clean(value)
    if not text:
        return []
    return [x.strip() for x in text.replace(",", "|").split("|") if x.strip()]


def parse_atom_site_rich(cif_text: str) -> list[dict[str, Any]]:
    lines = cif_text.splitlines()
    atoms: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != "loop_":
            i += 1
            continue
        j = i + 1
        headers: list[str] = []
        while j < len(lines) and lines[j].strip().startswith("_atom_site."):
            headers.append(lines[j].strip())
            j += 1
        if not headers:
            i += 1
            continue
        idx = {h: k for k, h in enumerate(headers)}
        required = ["_atom_site.group_PDB", "_atom_site.type_symbol", "_atom_site.Cartn_x", "_atom_site.Cartn_y", "_atom_site.Cartn_z"]
        if not all(r in idx for r in required):
            i = j
            continue
        while j < len(lines):
            raw = lines[j].strip()
            if not raw or raw == "#":
                j += 1
                break
            if raw.startswith("loop_") or raw.startswith("_") or raw.startswith("data_"):
                break
            try:
                parts = shlex.split(raw, posix=True)
            except Exception:
                j += 1
                continue
            if len(parts) < len(headers):
                j += 1
                continue
            try:
                group = parts[idx["_atom_site.group_PDB"]]
                element = parts[idx["_atom_site.type_symbol"]].upper()
                if group != "ATOM" or element in HEAVY_SKIP:
                    j += 1
                    continue
                model = parts[idx.get("_atom_site.pdbx_PDB_model_num", -1)] if "_atom_site.pdbx_PDB_model_num" in idx else "1"
                if model not in {"1", "1.0", ".", "?"}:
                    j += 1
                    continue
                alt = parts[idx.get("_atom_site.label_alt_id", -1)] if "_atom_site.label_alt_id" in idx else "."
                if alt not in {".", "?", "A", "1"}:
                    j += 1
                    continue
                auth_chain = parts[idx.get("_atom_site.auth_asym_id", idx.get("_atom_site.label_asym_id"))]
                label_chain = parts[idx.get("_atom_site.label_asym_id", idx.get("_atom_site.auth_asym_id"))]
                auth_seq = parts[idx.get("_atom_site.auth_seq_id", idx.get("_atom_site.label_seq_id"))]
                label_seq = parts[idx.get("_atom_site.label_seq_id", idx.get("_atom_site.auth_seq_id"))]
                auth_comp = parts[idx.get("_atom_site.auth_comp_id", idx.get("_atom_site.label_comp_id"))].upper()
                label_comp = parts[idx.get("_atom_site.label_comp_id", idx.get("_atom_site.auth_comp_id"))].upper()
                atom = parts[idx.get("_atom_site.auth_atom_id", idx.get("_atom_site.label_atom_id"))]
                x = float(parts[idx["_atom_site.Cartn_x"]])
                y = float(parts[idx["_atom_site.Cartn_y"]])
                z = float(parts[idx["_atom_site.Cartn_z"]])
            except Exception:
                j += 1
                continue
            atoms.append({
                "chain": auth_chain,
                "label_chain": label_chain,
                "auth_seq": auth_seq,
                "label_seq": label_seq,
                "resname": auth_comp if auth_comp in AA3 else label_comp,
                "atom": atom,
                "element": element,
                "x": x,
                "y": y,
                "z": z,
            })
            j += 1
        i = j
    return atoms


def seq_sort_key(label_seq: str, auth_seq: str) -> tuple[int, float, str]:
    for v in [label_seq, auth_seq]:
        try:
            return (0, float(v), clean(v))
        except Exception:
            pass
    return (1, 0.0, clean(auth_seq) or clean(label_seq))


def residues_for_chain(atoms: list[dict[str, Any]], chain: str) -> tuple[str, dict[tuple[str, str, str], int], dict[int, list[dict[str, Any]]]]:
    residues: dict[tuple[str, str, str], dict[str, Any]] = {}
    for a in atoms:
        if a["chain"] != chain:
            continue
        key = (clean(a["label_seq"]), clean(a["auth_seq"]), clean(a["resname"]))
        residues.setdefault(key, {"atoms": [], "sort": seq_sort_key(key[0], key[1]), "resname": key[2]})["atoms"].append(a)
    ordered = sorted(residues.items(), key=lambda kv: kv[1]["sort"])
    seq = "".join(AA3.get(meta["resname"], "X") for _, meta in ordered)
    key_to_idx = {key: i for i, (key, _) in enumerate(ordered)}
    idx_atoms = {i: meta["atoms"] for i, (_, meta) in enumerate(ordered)}
    return seq, key_to_idx, idx_atoms


def grid_key(atom: dict[str, Any], cell: float) -> tuple[int, int, int]:
    return (math.floor(atom["x"] / cell), math.floor(atom["y"] / cell), math.floor(atom["z"] / cell))


def neighbor_keys(key: tuple[int, int, int]) -> Iterable[tuple[int, int, int]]:
    x, y, z = key
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield (x + dx, y + dy, z + dz)


def dist2(a: dict[str, Any], b: dict[str, Any]) -> float:
    return (a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2


def min_residue_distance(a_atoms: list[dict[str, Any]], b_atoms: list[dict[str, Any]]) -> float:
    best = 999.0
    for a in a_atoms:
        for b in b_atoms:
            d = math.sqrt(dist2(a, b))
            if d < best:
                best = d
    return best


def contact_pairs_for_chain_pair(
    atoms: list[dict[str, Any]],
    v_chain: str,
    a_chain: str,
    cutoff: float,
) -> tuple[str, str, list[list[int]], dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]], dict[str, Any]]:
    v_seq, v_key_idx, v_idx_atoms = residues_for_chain(atoms, v_chain)
    a_seq, a_key_idx, a_idx_atoms = residues_for_chain(atoms, a_chain)
    v_atoms = [atom for atoms_ in v_idx_atoms.values() for atom in atoms_]
    a_atoms = [atom for atoms_ in a_idx_atoms.values() for atom in atoms_]
    a_grid: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for atom in a_atoms:
        a_grid[grid_key(atom, cutoff)].append(atom)
    cutoff2 = cutoff * cutoff
    pos: set[tuple[int, int]] = set()
    for va in v_atoms:
        v_key = (clean(va["label_seq"]), clean(va["auth_seq"]), clean(va["resname"]))
        vi = v_key_idx.get(v_key)
        if vi is None:
            continue
        for nk in neighbor_keys(grid_key(va, cutoff)):
            for aa in a_grid.get(nk, []):
                if dist2(va, aa) > cutoff2:
                    continue
                a_key = (clean(aa["label_seq"]), clean(aa["auth_seq"]), clean(aa["resname"]))
                ai = a_key_idx.get(a_key)
                if ai is not None:
                    pos.add((vi, ai))
    stats = {"vhh_residues": len(v_seq), "antigen_residues": len(a_seq), "vhh_atoms": len(v_atoms), "antigen_atoms": len(a_atoms)}
    return v_seq, a_seq, [list(x) for x in sorted(pos)], v_idx_atoms, a_idx_atoms, stats


def sample_negative_pairs(
    v_atoms: dict[int, list[dict[str, Any]]],
    a_atoms: dict[int, list[dict[str, Any]]],
    positives: set[tuple[int, int]],
    ratio_count: int,
    rng: random.Random,
    min_dist: float,
) -> list[list[int]]:
    all_candidates = [(i, j) for i in v_atoms for j in a_atoms if (i, j) not in positives]
    rng.shuffle(all_candidates)
    out: list[list[int]] = []
    max_scan = min(len(all_candidates), max(ratio_count * 80, ratio_count + 200))
    for i, j in all_candidates[:max_scan]:
        if len(out) >= ratio_count:
            break
        d = min_residue_distance(v_atoms[i], a_atoms[j])
        if d >= min_dist:
            out.append([i, j])
    return out


def chain_pairs(v_chains: list[str], a_chains: list[str]) -> list[tuple[str, str]]:
    if not v_chains or not a_chains:
        return []
    if len(v_chains) == len(a_chains):
        return list(zip(v_chains, a_chains))
    return [(v, a) for v in v_chains for a in a_chains]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--max-structures", type=int, default=160)
    parser.add_argument("--neg-ratio", type=int, default=4)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--positive-cutoff", type=float, default=4.5)
    parser.add_argument("--negative-min-distance", type=float, default=8.0)
    parser.add_argument("--output-stem", default="structure_contact_maps_v2")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_root = root / "experiments/phase2_5080_v1"
    prepared = out_root / "prepared"
    audits = out_root / "audits"
    prepared.mkdir(parents=True, exist_ok=True)
    audits.mkdir(parents=True, exist_ok=True)
    out_jsonl = prepared / f"{args.output_stem}.jsonl"
    out_summary_csv = prepared / f"{args.output_stem}_summary.csv"

    manifest = pd.read_csv(root / "model_data/sabdab2_single_domain_structure_manifest_v0.csv")
    eligible = manifest[manifest["has_antigen_chain_summary"].astype(str).str.lower().eq("yes")].copy()
    eligible = eligible[eligible["h_chains"].apply(lambda x: len(split_chains(x)) > 0)]
    eligible = eligible[eligible["antigen_chains"].apply(lambda x: len(split_chains(x)) > 0)]
    eligible = eligible.head(args.max_structures).copy()
    archive_path = root / "datasets/13_sabdab_structures/sabdab_all_single_domain_structures.tgz"
    wanted = set(eligible["structure_member"].astype(str))
    meta = {str(r["structure_member"]): r for _, r in eligible.iterrows()}
    rng = random.Random(args.seed)

    records = 0
    summary_rows: list[dict[str, Any]] = []
    split_cycle = ["train"] * 7 + ["val"] * 2 + ["test"] * 1
    eligible_members = list(eligible["structure_member"].astype(str))
    split_by_member = {m: split_cycle[i % len(split_cycle)] for i, m in enumerate(eligible_members)}

    with tarfile.open(archive_path, "r:gz") as tar, out_jsonl.open("w", encoding="utf-8") as out:
        for member in tar:
            if member.name not in wanted:
                continue
            row = meta[member.name]
            fh = tar.extractfile(member)
            if fh is None:
                continue
            text = fh.read().decode("utf-8", errors="replace")
            atoms = parse_atom_site_rich(text)
            v_chains = split_chains(row["h_chains"])
            a_chains = split_chains(row["antigen_chains"])
            for v_chain, a_chain in chain_pairs(v_chains, a_chains):
                v_seq, a_seq, positives, v_idx_atoms, a_idx_atoms, stats = contact_pairs_for_chain_pair(atoms, v_chain, a_chain, args.positive_cutoff)
                if not v_seq or not a_seq or len(positives) < 3:
                    continue
                pos_set = {tuple(x) for x in positives}
                negatives = sample_negative_pairs(v_idx_atoms, a_idx_atoms, pos_set, max(len(positives) * args.neg_ratio, 1), rng, args.negative_min_distance)
                if len(negatives) < max(3, len(positives)):
                    continue
                rec = {
                    "complex_id": f"{row['pdb']}|{v_chain}|{a_chain}",
                    "pdb": str(row["pdb"]),
                    "structure_member": member.name,
                    "split": split_by_member[member.name],
                    "vhh_chain": v_chain,
                    "antigen_chain": a_chain,
                    "vhh_seq": v_seq,
                    "antigen_seq": a_seq,
                    "positive_pairs": positives,
                    "negative_pairs": negatives,
                    "positive_cutoff_angstrom": args.positive_cutoff,
                    "negative_min_distance_angstrom": args.negative_min_distance,
                    "antigen_name": clean(row.get("antigen_name")),
                    "resolution": clean(row.get("resolution")),
                    "method": clean(row.get("method")),
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                records += 1
                summary_rows.append({
                    "complex_id": rec["complex_id"],
                    "pdb": rec["pdb"],
                    "split": rec["split"],
                    "vhh_chain": v_chain,
                    "antigen_chain": a_chain,
                    "vhh_len": len(v_seq),
                    "antigen_len": len(a_seq),
                    "positive_pairs": len(positives),
                    "negative_pairs": len(negatives),
                    **stats,
                })
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(out_summary_csv, index=False, quoting=csv.QUOTE_MINIMAL)
    summary = {
        "records": records,
        "input_structures_sampled": int(len(eligible)),
        "split_counts": summary_df["split"].value_counts().to_dict() if not summary_df.empty else {},
        "positive_pairs": int(summary_df["positive_pairs"].sum()) if not summary_df.empty else 0,
        "negative_pairs": int(summary_df["negative_pairs"].sum()) if not summary_df.empty else 0,
        "output_jsonl": str(out_jsonl),
        "output_summary_csv": str(out_summary_csv),
        "seed": args.seed,
        "positive_cutoff_angstrom": args.positive_cutoff,
        "negative_min_distance_angstrom": args.negative_min_distance,
    }
    (audits / f"{args.output_stem}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Structure Contact Maps V2 Audit",
        "",
        "Updated: 2026-07-09",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Boundary",
        "",
        "Positive labels are true same-complex residue pairs with heavy-atom distance <= 4.5 A. Negative labels are sampled same-complex residue pairs with min heavy-atom distance >= 8.0 A. Residue indices are 0-based reconstructed sequence indices per chain from mmCIF atom_site records.",
        "",
    ]
    (audits / f"{args.output_stem}_audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
