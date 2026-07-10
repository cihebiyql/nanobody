#!/usr/bin/env python3
"""Extract a small, dependency-free sdAb-antigen contact set from SAbDab2 mmCIF archives.

This is intentionally an MVP extractor: it samples a bounded number of single-domain
structures with antigen chains and writes residue-pair contacts at a heavy-atom cutoff.
It avoids BioPython/gemmi so the pipeline remains runnable in the current environment.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import shlex
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd

HEAVY_ATOM_SKIP = {"H", "D"}


def markdown_table(df: pd.DataFrame) -> str:
    """Render a compact markdown table without requiring pandas[tabulate]."""
    if df.empty:
        return "(no rows)"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = [str(row.get(c, "")).replace("\n", " ") for c in df.columns]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def split_chains(value: object) -> list[str]:
    text = "" if pd.isna(value) else str(value).strip()
    if not text or text.lower() in {"nan", "none", "?", "."}:
        return []
    return [x.strip() for x in text.replace(",", "|").split("|") if x.strip()]


def parse_atom_site(cif_text: str) -> list[dict[str, object]]:
    """Parse _atom_site loop rows needed for coarse contact extraction."""
    lines = cif_text.splitlines()
    atoms: list[dict[str, object]] = []
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
        field_index = {name: idx for idx, name in enumerate(headers)}
        required = [
            "_atom_site.group_PDB",
            "_atom_site.type_symbol",
            "_atom_site.Cartn_x",
            "_atom_site.Cartn_y",
            "_atom_site.Cartn_z",
        ]
        if not all(name in field_index for name in required):
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
            except ValueError:
                j += 1
                continue
            if len(parts) < len(headers):
                j += 1
                continue
            try:
                group = parts[field_index["_atom_site.group_PDB"]]
                element = parts[field_index["_atom_site.type_symbol"]].upper()
                if group != "ATOM" or element in HEAVY_ATOM_SKIP:
                    j += 1
                    continue
                model = parts[field_index.get("_atom_site.pdbx_PDB_model_num", -1)] if "_atom_site.pdbx_PDB_model_num" in field_index else "1"
                if model not in {"1", "1.0", ".", "?"}:
                    j += 1
                    continue
                chain = parts[field_index.get("_atom_site.auth_asym_id", field_index.get("_atom_site.label_asym_id"))]
                resseq = parts[field_index.get("_atom_site.auth_seq_id", field_index.get("_atom_site.label_seq_id"))]
                resname = parts[field_index.get("_atom_site.auth_comp_id", field_index.get("_atom_site.label_comp_id"))]
                atom_name = parts[field_index.get("_atom_site.auth_atom_id", field_index.get("_atom_site.label_atom_id"))]
                alt_id = parts[field_index.get("_atom_site.label_alt_id", -1)] if "_atom_site.label_alt_id" in field_index else "."
                if alt_id not in {".", "?", "A", "1"}:
                    j += 1
                    continue
                x = float(parts[field_index["_atom_site.Cartn_x"]])
                y = float(parts[field_index["_atom_site.Cartn_y"]])
                z = float(parts[field_index["_atom_site.Cartn_z"]])
            except Exception:
                j += 1
                continue
            atoms.append(
                {
                    "chain": chain,
                    "resseq": resseq,
                    "resname": resname,
                    "atom": atom_name,
                    "element": element,
                    "x": x,
                    "y": y,
                    "z": z,
                }
            )
            j += 1
        i = j
    return atoms


def grid_key(atom: dict[str, object], cell: float) -> tuple[int, int, int]:
    return (
        math.floor(float(atom["x"]) / cell),
        math.floor(float(atom["y"]) / cell),
        math.floor(float(atom["z"]) / cell),
    )


def neighbor_keys(key: tuple[int, int, int]) -> Iterable[tuple[int, int, int]]:
    x, y, z = key
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield (x + dx, y + dy, z + dz)


def dist2(a: dict[str, object], b: dict[str, object]) -> float:
    return (float(a["x"]) - float(b["x"])) ** 2 + (float(a["y"]) - float(b["y"])) ** 2 + (float(a["z"]) - float(b["z"])) ** 2


def extract_contacts_for_structure(
    cif_text: str,
    vhh_chains: set[str],
    antigen_chains: set[str],
    cutoff: float,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    atoms = parse_atom_site(cif_text)
    vhh_atoms = [a for a in atoms if str(a["chain"]) in vhh_chains]
    ag_atoms = [a for a in atoms if str(a["chain"]) in antigen_chains]
    ag_grid: dict[tuple[int, int, int], list[dict[str, object]]] = defaultdict(list)
    for atom in ag_atoms:
        ag_grid[grid_key(atom, cutoff)].append(atom)

    cutoff2 = cutoff * cutoff
    pairs: dict[tuple[str, str, str, str, str, str], dict[str, object]] = {}
    for va in vhh_atoms:
        for nk in neighbor_keys(grid_key(va, cutoff)):
            for aa in ag_grid.get(nk, []):
                d2 = dist2(va, aa)
                if d2 > cutoff2:
                    continue
                key = (
                    str(va["chain"]),
                    str(va["resseq"]),
                    str(va["resname"]),
                    str(aa["chain"]),
                    str(aa["resseq"]),
                    str(aa["resname"]),
                )
                rec = pairs.setdefault(
                    key,
                    {
                        "vhh_chain": key[0],
                        "vhh_resseq": key[1],
                        "vhh_resname": key[2],
                        "antigen_chain": key[3],
                        "antigen_resseq": key[4],
                        "antigen_resname": key[5],
                        "min_distance_angstrom": 999.0,
                        "contact_atom_pairs": 0,
                        "example_atom_pair": "",
                    },
                )
                d = math.sqrt(d2)
                rec["contact_atom_pairs"] = int(rec["contact_atom_pairs"]) + 1
                if d < float(rec["min_distance_angstrom"]):
                    rec["min_distance_angstrom"] = round(d, 3)
                    rec["example_atom_pair"] = f'{va["atom"]}-{aa["atom"]}'
    stats = {"atoms_total": len(atoms), "vhh_atoms": len(vhh_atoms), "antigen_atoms": len(ag_atoms)}
    return list(pairs.values()), stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="model_data/sabdab2_single_domain_structure_manifest_v0.csv")
    parser.add_argument("--archive", default="datasets/13_sabdab_structures/sabdab_all_single_domain_structures.tgz")
    parser.add_argument("--out", default="model_data/sabdab2_single_domain_contacts_mvp.csv")
    parser.add_argument("--report", default="reports/sabdab2_contact_extraction_mvp.md")
    parser.add_argument("--max-structures", type=int, default=20)
    parser.add_argument("--cutoff", type=float, default=4.5)
    args = parser.parse_args()

    manifest = pd.read_csv(args.manifest)
    eligible = manifest[manifest["has_antigen_chain_summary"].astype(str).str.lower().eq("yes")].copy()
    eligible = eligible[eligible["h_chains"].apply(lambda x: len(split_chains(x)) > 0)]
    eligible = eligible[eligible["antigen_chains"].apply(lambda x: len(split_chains(x)) > 0)]
    eligible = eligible.head(args.max_structures)
    wanted = set(eligible["structure_member"].astype(str))
    meta_by_member = {str(r["structure_member"]): r for _, r in eligible.iterrows()}

    rows: list[dict[str, object]] = []
    structure_summaries: list[dict[str, object]] = []
    processed = 0
    with tarfile.open(args.archive, "r:gz") as tar:
        for member in tar:
            if member.name not in wanted:
                continue
            meta = meta_by_member[member.name]
            fh = tar.extractfile(member)
            if fh is None:
                continue
            text = fh.read().decode("utf-8", errors="replace")
            vhh_chains = set(split_chains(meta["h_chains"]))
            antigen_chains = set(split_chains(meta["antigen_chains"]))
            contacts, stats = extract_contacts_for_structure(text, vhh_chains, antigen_chains, args.cutoff)
            processed += 1
            for rec in contacts:
                rec.update(
                    {
                        "pdb": meta["pdb"],
                        "structure_member": member.name,
                        "cutoff_angstrom": args.cutoff,
                        "antigen_name": meta.get("antigen_name", ""),
                        "resolution": meta.get("resolution", ""),
                        "method": meta.get("method", ""),
                    }
                )
                rows.append(rec)
            structure_summaries.append(
                {
                    "pdb": meta["pdb"],
                    "structure_member": member.name,
                    "vhh_chains": "|".join(sorted(vhh_chains)),
                    "antigen_chains": "|".join(sorted(antigen_chains)),
                    "contact_residue_pairs": len(contacts),
                    **stats,
                }
            )
            if processed >= len(wanted):
                break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "pdb",
        "structure_member",
        "vhh_chain",
        "vhh_resseq",
        "vhh_resname",
        "antigen_chain",
        "antigen_resseq",
        "antigen_resname",
        "min_distance_angstrom",
        "contact_atom_pairs",
        "example_atom_pair",
        "cutoff_angstrom",
        "antigen_name",
        "resolution",
        "method",
    ]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for rec in rows:
            writer.writerow({k: rec.get(k, "") for k in fieldnames})

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    nonzero = sum(1 for s in structure_summaries if int(s["contact_residue_pairs"]) > 0)
    summary = {
        "manifest_rows": int(len(manifest)),
        "eligible_sampled_structures": int(len(eligible)),
        "processed_structures": int(processed),
        "structures_with_contacts": int(nonzero),
        "contact_rows": int(len(rows)),
        "cutoff_angstrom": args.cutoff,
        "output": str(out),
    }
    report_path.write_text(
        "# SAbDab2 single-domain structure contact MVP\n\n"
        f"Updated: 2026-07-09\n\n"
        "## Summary\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n\n"
        "## Boundary\n\n"
        "这是一个无外部依赖的 MVP 级 contact extractor，仅用于证明结构接触数据通路可跑通；"
        "它不是最终全量、高精度结构标注器。后续全量训练建议改用 gemmi/Bio.PDB 并加入 CDR 编号映射。\n\n"
        "## Structure summaries\n\n"
        + markdown_table(pd.DataFrame(structure_summaries)),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
