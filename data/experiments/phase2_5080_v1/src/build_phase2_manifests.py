#!/usr/bin/env python3
"""Build Phase 2 train/val/test split and negative-sample manifests.

This script is intentionally dependency-light (pandas/numpy only) and uses the
existing MVP contact extractor for mmCIF parsing. It creates auditable inputs for
Phase 2 GPU training without touching Phase 1/MVP outputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
from extract_sabdab2_single_domain_contacts_mvp import (  # noqa: E402
    extract_contacts_for_structure,
    parse_atom_site,
    split_chains,
)

AA = set("ACDEFGHIKLMNPQRSTVWY")


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


def seq_identity(a: str, b: str) -> float:
    a = clean(a)
    b = clean(b)
    if not a or not b:
        return 0.0
    if len(a) == len(b):
        return sum(x == y for x, y in zip(a, b)) / max(len(a), 1)
    # Fast ungapped identity over the shorter sequence; enough for sampling heuristics.
    n = min(len(a), len(b))
    return sum(a[i] == b[i] for i in range(n)) / max(max(len(a), len(b)), 1)


def mask_count(mask: str) -> int:
    return sum(1 for ch in clean(mask) if ch == "1")


def read_zym(root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for split in ["train", "val", "test"]:
        df = pd.read_csv(root / f"datasets/49_hf_broad_antibody/ZYMScott_Paratope/{split}.csv")
        for idx, r in df.iterrows():
            vhh = clean(r.get("seq_nanobody"))
            antigen = clean(r.get("seq_antigen"))
            sample_id = f"zympara_{split}_{idx:06d}"
            rows.append(
                {
                    "sample_id": sample_id,
                    "source_dataset": "ZYMScott_Paratope",
                    "source_file": f"datasets/49_hf_broad_antibody/ZYMScott_Paratope/{split}.csv",
                    "source_row": idx,
                    "split": split,
                    "group_key": f"{clean(r.get('pdb'))}|{clean(r.get('nanobody_chain'))}|{clean(r.get('antigen_chain'))}",
                    "pdb_id": clean(r.get("pdb")),
                    "vhh_chain": clean(r.get("nanobody_chain")),
                    "antigen_chain": clean(r.get("antigen_chain")),
                    "vhh_seq": vhh,
                    "antigen_seq": antigen,
                    "vhh_len": len(vhh),
                    "antigen_len": len(antigen),
                    "vhh_paratope_mask": clean(r.get("paratope")),
                    "antigen_epitope_mask": clean(r.get("epitope")),
                    "paratope_positive_count": mask_count(r.get("paratope")),
                    "epitope_positive_count": mask_count(r.get("epitope")),
                    "binding_label": 1,
                    "label_source": "cognate_structure_pair",
                    "quality_flag": "ok" if vhh and antigen else "missing_sequence",
                }
            )
    return pd.DataFrame(rows)


def choose_easy_antigen(row: pd.Series, candidates: pd.DataFrame, positive_pairs: set[tuple[str, str]], rng: random.Random) -> tuple[pd.Series | None, str]:
    pool = candidates[candidates["antigen_seq"] != row["antigen_seq"]].copy()
    pool["_id"] = pool["antigen_seq"].apply(lambda s: seq_identity(row["antigen_seq"], s))
    pool = pool[pool["_id"] < 0.30]
    if pool.empty:
        pool = candidates[candidates["antigen_seq"] != row["antigen_seq"]].copy()
        reason = "fallback_different_antigen_identity_not_below_0p30"
    else:
        reason = "different_antigen_identity_below_0p30"
    if pool.empty:
        return None, "no_candidate_antigen"
    order = list(pool.index)
    rng.shuffle(order)
    for idx in order:
        cand = pool.loc[idx]
        if (row["vhh_seq"], cand["antigen_seq"]) not in positive_pairs:
            return cand, reason
    return None, "all_easy_candidates_known_positive_pairs"


def choose_same_family_antigen(row: pd.Series, candidates: pd.DataFrame, positive_pairs: set[tuple[str, str]], rng: random.Random) -> tuple[pd.Series | None, str]:
    pool = candidates[candidates["antigen_seq"] != row["antigen_seq"]].copy()
    pool["_id"] = pool["antigen_seq"].apply(lambda s: seq_identity(row["antigen_seq"], s))
    pool["_len_ratio"] = pool["antigen_len"].apply(lambda n: min(n, row["antigen_len"]) / max(n, row["antigen_len"], 1))
    hard = pool[(pool["_id"] >= 0.30) & (pool["_id"] < 0.90) & (pool["_len_ratio"] >= 0.70)].copy()
    if hard.empty:
        hard = pool.sort_values(["_id", "_len_ratio"], ascending=[False, False]).head(20)
        reason = "fallback_most_similar_available_antigen"
    else:
        reason = "same_family_proxy_antigen_identity_0p30_to_0p90"
    if hard.empty:
        return None, "no_candidate_antigen"
    order = list(hard.index)
    rng.shuffle(order)
    for idx in order:
        cand = hard.loc[idx]
        if (row["vhh_seq"], cand["antigen_seq"]) not in positive_pairs:
            return cand, reason
    return None, "all_same_family_candidates_known_positive_pairs"


def choose_framework_vhh(row: pd.Series, candidates: pd.DataFrame, positive_pairs: set[tuple[str, str]], rng: random.Random) -> tuple[pd.Series | None, str]:
    pool = candidates[candidates["vhh_seq"] != row["vhh_seq"]].copy()
    pool["_id"] = pool["vhh_seq"].apply(lambda s: seq_identity(row["vhh_seq"], s))
    pool["_len_ratio"] = pool["vhh_len"].apply(lambda n: min(n, row["vhh_len"]) / max(n, row["vhh_len"], 1))
    hard = pool[(pool["_id"] >= 0.55) & (pool["_id"] < 0.95) & (pool["_len_ratio"] >= 0.80)].copy()
    if hard.empty:
        hard = pool.sort_values(["_id", "_len_ratio"], ascending=[False, False]).head(20)
        reason = "fallback_most_similar_available_vhh_no_cdr_annotation"
    else:
        reason = "framework_proxy_vhh_identity_0p55_to_0p95_cdr_unavailable"
    if hard.empty:
        return None, "no_candidate_vhh"
    order = list(hard.index)
    rng.shuffle(order)
    for idx in order:
        cand = hard.loc[idx]
        if (cand["vhh_seq"], row["antigen_seq"]) not in positive_pairs:
            return cand, reason
    return None, "all_framework_candidates_known_positive_pairs"


def build_pair_negatives(zym: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = random.Random(seed)
    positives = {(r["vhh_seq"], r["antigen_seq"]) for _, r in zym.iterrows()}
    rows: list[dict[str, Any]] = []
    for split, split_df in zym.groupby("split", sort=False):
        split_df = split_df.reset_index(drop=True)
        for _, row in split_df.iterrows():
            tasks = [
                ("N1_easy_cross_antigen", choose_easy_antigen),
                ("N2_same_family_hard_antigen", choose_same_family_antigen),
                ("N3_framework_similar_hard_vhh", choose_framework_vhh),
            ]
            for neg_type, chooser in tasks:
                cand, reason = chooser(row, split_df, positives, rng)
                if cand is None:
                    continue
                if neg_type == "N3_framework_similar_hard_vhh":
                    vhh_seq = cand["vhh_seq"]
                    antigen_seq = row["antigen_seq"]
                    vhh_source = cand["sample_id"]
                    antigen_source = row["sample_id"]
                    sim = seq_identity(row["vhh_seq"], cand["vhh_seq"])
                else:
                    vhh_seq = row["vhh_seq"]
                    antigen_seq = cand["antigen_seq"]
                    vhh_source = row["sample_id"]
                    antigen_source = cand["sample_id"]
                    sim = seq_identity(row["antigen_seq"], cand["antigen_seq"])
                if (vhh_seq, antigen_seq) in positives:
                    continue
                rows.append(
                    {
                        "negative_id": f"{row['sample_id']}_{neg_type}",
                        "negative_type": neg_type,
                        "source_positive_id": row["sample_id"],
                        "split": split,
                        "group_key": f"neg|{row['sample_id']}|{neg_type}",
                        "vhh_source_sample_id": vhh_source,
                        "antigen_source_sample_id": antigen_source,
                        "vhh_seq": vhh_seq,
                        "antigen_seq": antigen_seq,
                        "binding_label": 0,
                        "construction_rule": reason,
                        "similarity_proxy": round(float(sim), 4),
                        "reason_not_positive": "not_observed_as_cognate_pair_in_ZYMScott_Paratope_current_manifest",
                        "excluded_known_positive_hit": "no_exact_vhh_antigen_pair_in_positive_manifest",
                        "seed": seed,
                    }
                )
    return pd.DataFrame(rows)


def build_pair_split(zym: pd.DataFrame, negatives: pd.DataFrame) -> pd.DataFrame:
    pos = zym[["sample_id", "split", "group_key", "pdb_id", "vhh_seq", "antigen_seq", "binding_label", "label_source"]].copy()
    pos = pos.rename(columns={"sample_id": "pair_id"})
    pos["negative_type"] = "positive_cognate_pair"
    pos["construction_rule"] = "observed_cognate_pair"
    neg = negatives[["negative_id", "split", "group_key", "vhh_seq", "antigen_seq", "binding_label", "negative_type", "construction_rule"]].copy()
    neg = neg.rename(columns={"negative_id": "pair_id"})
    neg["pdb_id"] = ""
    neg["label_source"] = "constructed_negative"
    return pd.concat([pos, neg[pos.columns]], ignore_index=True)


def assign_group_splits(groups: list[str], seed: int) -> dict[str, str]:
    rng = random.Random(seed)
    groups = sorted(set(groups))
    rng.shuffle(groups)
    n = len(groups)
    n_train = max(1, int(round(0.70 * n))) if n else 0
    n_val = max(1, int(round(0.15 * n))) if n >= 3 else max(0, n - n_train)
    if n_train + n_val >= n and n > 1:
        n_train = max(1, n - 2)
        n_val = 1
    out = {}
    for i, g in enumerate(groups):
        if i < n_train:
            out[g] = "train"
        elif i < n_train + n_val:
            out[g] = "val"
        else:
            out[g] = "test"
    return out


def residue_atoms(atoms: list[dict[str, object]], chains: set[str]) -> dict[tuple[str, str, str], list[dict[str, object]]]:
    out: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for atom in atoms:
        if str(atom["chain"]) in chains:
            key = (str(atom["chain"]), str(atom["resseq"]), str(atom["resname"]),)
            out[key].append(atom)
    return out


def min_distance(res_a: list[dict[str, object]], res_b: list[dict[str, object]]) -> float:
    best = 999.0
    for a in res_a:
        for b in res_b:
            d = math.sqrt((float(a["x"]) - float(b["x"])) ** 2 + (float(a["y"]) - float(b["y"])) ** 2 + (float(a["z"]) - float(b["z"])) ** 2)
            if d < best:
                best = d
    return best


def build_structure_contacts(root: Path, seed: int, max_structures: int, neg_ratio: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = random.Random(seed)
    manifest = pd.read_csv(root / "model_data/sabdab2_single_domain_structure_manifest_v0.csv")
    eligible = manifest[manifest["has_antigen_chain_summary"].astype(str).str.lower().eq("yes")].copy()
    eligible = eligible[eligible["h_chains"].apply(lambda x: len(split_chains(x)) > 0)]
    eligible = eligible[eligible["antigen_chains"].apply(lambda x: len(split_chains(x)) > 0)]
    eligible = eligible.head(max_structures).copy()
    split_by_pdb = assign_group_splits(eligible["pdb"].astype(str).tolist(), seed)
    group_rows = []
    pair_rows: list[dict[str, Any]] = []
    neg_rows: list[dict[str, Any]] = []
    archive = root / "datasets/13_sabdab_structures/sabdab_all_single_domain_structures.tgz"
    wanted = set(eligible["structure_member"].astype(str))
    meta_by_member = {str(r["structure_member"]): r for _, r in eligible.iterrows()}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if member.name not in wanted:
                continue
            meta = meta_by_member[member.name]
            pdb = str(meta["pdb"])
            split = split_by_pdb[pdb]
            vhh_chains = set(split_chains(meta["h_chains"]))
            antigen_chains = set(split_chains(meta["antigen_chains"]))
            fh = tar.extractfile(member)
            if fh is None:
                continue
            text = fh.read().decode("utf-8", errors="replace")
            atoms = parse_atom_site(text)
            contacts, stats = extract_contacts_for_structure(text, vhh_chains, antigen_chains, cutoff=4.5)
            vhh_res = residue_atoms(atoms, vhh_chains)
            ag_res = residue_atoms(atoms, antigen_chains)
            positive_keys = {(str(c["vhh_chain"]), str(c["vhh_resseq"]), str(c["antigen_chain"]), str(c["antigen_resseq"])) for c in contacts}
            group_rows.append(
                {
                    "pdb": pdb,
                    "structure_member": member.name,
                    "split": split,
                    "group_key": f"{pdb}|{'|'.join(sorted(vhh_chains))}|{'|'.join(sorted(antigen_chains))}",
                    "vhh_chains": "|".join(sorted(vhh_chains)),
                    "antigen_chains": "|".join(sorted(antigen_chains)),
                    "contact_positive_rows": len(contacts),
                    "vhh_residue_count": len(vhh_res),
                    "antigen_residue_count": len(ag_res),
                    **stats,
                }
            )
            for cidx, c in enumerate(contacts):
                pair_rows.append(
                    {
                        "contact_pair_id": f"{pdb}_pos_{cidx:06d}",
                        "pdb": pdb,
                        "structure_member": member.name,
                        "split": split,
                        "label": 1,
                        "negative_type": "positive_heavy_atom_contact_le_4p5A",
                        "vhh_chain": c["vhh_chain"],
                        "vhh_resseq": c["vhh_resseq"],
                        "vhh_resname": c["vhh_resname"],
                        "antigen_chain": c["antigen_chain"],
                        "antigen_resseq": c["antigen_resseq"],
                        "antigen_resname": c["antigen_resname"],
                        "min_distance_angstrom": c["min_distance_angstrom"],
                        "construction_rule": "observed_residue_pair_contact_cutoff_4p5A",
                    }
                )
            all_pairs = [(vk, ak) for vk in vhh_res for ak in ag_res if (vk[0], vk[1], ak[0], ak[1]) not in positive_keys]
            rng.shuffle(all_pairs)
            need = min(len(all_pairs), max(1, len(contacts) * neg_ratio))
            kept = 0
            scanned = 0
            for vk, ak in all_pairs:
                if kept >= need or scanned >= need * 80:
                    break
                scanned += 1
                d = min_distance(vhh_res[vk], ag_res[ak])
                if d < 8.0:
                    continue
                row = {
                    "contact_pair_id": f"{pdb}_neg_{kept:06d}",
                    "pdb": pdb,
                    "structure_member": member.name,
                    "split": split,
                    "label": 0,
                    "negative_type": "N0_same_complex_noncontact_ge_8A",
                    "vhh_chain": vk[0],
                    "vhh_resseq": vk[1],
                    "vhh_resname": vk[2],
                    "antigen_chain": ak[0],
                    "antigen_resseq": ak[1],
                    "antigen_resname": ak[2],
                    "min_distance_angstrom": round(d, 3),
                    "construction_rule": "same_complex_residue_pair_min_heavy_atom_distance_ge_8A",
                }
                pair_rows.append(row)
                neg_rows.append(row)
                kept += 1
    return pd.DataFrame(group_rows), pd.DataFrame(pair_rows), pd.DataFrame(neg_rows)


def build_pvrig_external(root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    pos = pd.read_csv(root / "model_data/pvrig_blocker_positive_calibration_v0.csv")
    mut = pd.read_csv(root / "model_data/pvrig_blocker_mutant_control_calibration_v0.csv")
    cand = pd.read_csv(root / "reports/mvp_pvrig_top_candidates_v0.csv") if (root / "reports/mvp_pvrig_top_candidates_v0.csv").exists() else pd.DataFrame()
    for _, r in pos.iterrows():
        rows.append({"sample_id": clean(r.get("calibration_id")), "split": "pvrig_external", "role": "known_positive_calibration_only", "sequence": clean(r.get("sequence")), "label_hint": "positive_blocking_control", "leakage_policy": "exclude_from_training_and_new_candidate_ranking"})
    for _, r in mut.iterrows():
        rows.append({"sample_id": clean(r.get("control_id")), "split": "pvrig_external", "role": "mutant_or_leakage_control", "sequence": clean(r.get("sequence")), "label_hint": clean(r.get("leakage_label")), "leakage_policy": "exclude_or_hold_for_manual_review"})
    for _, r in cand.iterrows():
        rows.append({"sample_id": clean(r.get("candidate_id")), "split": "pvrig_inference_only", "role": "mvp_top_candidate", "sequence": clean(r.get("vhh_seq")), "label_hint": clean(r.get("final_blocker_like_calibrated_label")), "leakage_policy": clean(r.get("leakage_label"))})
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row.get(c, "")).replace("\n", " ") for c in cols) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-structures", type=int, default=24)
    parser.add_argument("--contact-negative-ratio", type=int, default=4)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_root = root / "experiments/phase2_5080_v1"
    for sub in ["data_splits", "negative_sets", "prepared", "audits"]:
        (out_root / sub).mkdir(parents=True, exist_ok=True)

    zym = read_zym(root)
    zym.to_csv(out_root / "data_splits/zym_site_split_manifest_v1.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    pair_negs = build_pair_negatives(zym, args.seed)
    pair_negs.to_csv(out_root / "negative_sets/pair_negatives_v1.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    pair_split = build_pair_split(zym, pair_negs)
    pair_split.to_csv(out_root / "data_splits/pair_binding_split_v1.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    groups, contact_pairs, contact_negs = build_structure_contacts(root, args.seed, args.max_structures, args.contact_negative_ratio)
    groups.to_csv(out_root / "data_splits/sabdab2_structure_group_split_v1.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    contact_pairs.to_csv(out_root / "prepared/structure_contact_pairs_mvp_v1.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    contact_negs.to_csv(out_root / "negative_sets/contact_negatives_v1.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    pvrig_external = build_pvrig_external(root)
    pvrig_external.to_csv(out_root / "data_splits/pvrig_external_calibration_manifest_v1.csv", index=False, quoting=csv.QUOTE_MINIMAL)

    summary = {
        "zym_site_rows": int(len(zym)),
        "zym_split_counts": zym["split"].value_counts().to_dict(),
        "pair_negative_rows": int(len(pair_negs)),
        "pair_negative_type_counts": pair_negs["negative_type"].value_counts().to_dict() if not pair_negs.empty else {},
        "pair_binding_rows": int(len(pair_split)),
        "pair_binding_split_counts": pair_split["split"].value_counts().to_dict(),
        "structure_groups": int(len(groups)),
        "structure_split_counts": groups["split"].value_counts().to_dict() if not groups.empty else {},
        "contact_pair_rows": int(len(contact_pairs)),
        "contact_label_counts": contact_pairs["label"].value_counts().to_dict() if not contact_pairs.empty else {},
        "contact_negative_rows": int(len(contact_negs)),
        "pvrig_external_rows": int(len(pvrig_external)),
        "seed": args.seed,
    }
    (out_root / "audits/phase2_manifest_build_summary_v1.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    report_lines = [
        "# Phase 2 Manifest Build Audit",
        "",
        "Updated: 2026-07-09",
        "",
        "## Verdict",
        "",
        "PASS: split manifests, pair negatives, contact negatives, and PVRIG external calibration manifest were generated.",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Pair negative type counts",
        "",
        markdown_table(pd.DataFrame([{"negative_type": k, "rows": v} for k, v in summary["pair_negative_type_counts"].items()])),
        "",
        "## Contact label counts",
        "",
        markdown_table(pd.DataFrame([{"label": k, "rows": v} for k, v in summary["contact_label_counts"].items()])),
        "",
        "## Boundary",
        "",
        "Pair negatives are constructed negatives, not experimentally confirmed non-binders. N2/N3 are hard-negative heuristics and must be reported separately during evaluation.",
        "PVRIG known positives and mutant controls are held out for calibration/inference only and are not training positives.",
        "",
    ]
    (out_root / "audits/phase2_manifest_build_audit.md").write_text("\n".join(report_lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
