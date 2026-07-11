#!/usr/bin/env python3
"""Build leakage-resistant Phase 2 site, pair, and contact splits.

The V1 manifests preserve upstream row/PDB splits. This builder instead keeps
connected VHH, CDR3-proxy, antigen, and structure groups in one split. It also
separates observed positives from constructed contrastive pairs so unobserved
pairs are not presented as experimentally verified non-binders.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_phase2_manifests import build_pair_negatives, read_zym  # noqa: E402


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.weight = [1] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left = self.find(left)
        right = self.find(right)
        if left == right:
            return
        if self.weight[left] < self.weight[right]:
            left, right = right, left
        self.parent[right] = left
        self.weight[left] += self.weight[right]


def clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "na", "n/a"} else text


def sequence_identity(left: str, right: str) -> float:
    left = clean(left).upper()
    right = clean(right).upper()
    if not left or not right:
        return 0.0
    matched = sum(a == b for a, b in zip(left, right))
    return matched / max(len(left), len(right), 1)


def cdr3_proxy(sequence: str) -> str:
    """Return a conservative C-terminal VHH window, not an ANARCI CDR3 call."""
    sequence = clean(sequence).upper()
    return sequence[-35:-10] if len(sequence) >= 50 else sequence


def cluster_sequences(
    sequences: list[str],
    threshold: float,
    transform: Callable[[str], str] | None = None,
) -> dict[str, str]:
    unique = list(dict.fromkeys(clean(seq).upper() for seq in sequences if clean(seq)))
    uf = UnionFind(len(unique))
    transformed = [(transform(seq) if transform else seq) for seq in unique]
    for idx, left in enumerate(transformed):
        for other_idx in range(idx):
            right = transformed[other_idx]
            if min(len(left), len(right)) / max(len(left), len(right), 1) < threshold:
                continue
            if sequence_identity(left, right) >= threshold:
                uf.union(idx, other_idx)

    roots = sorted({uf.find(idx) for idx in range(len(unique))}, key=lambda root: unique[root])
    root_id = {root: f"cluster_{rank:06d}" for rank, root in enumerate(roots)}
    return {seq: root_id[uf.find(idx)] for idx, seq in enumerate(unique)}


def assign_connected_splits(
    rows: list[dict[str, Any]],
    vhh_threshold: float,
    antigen_threshold: float,
    cdr3_proxy_threshold: float,
    seed: int,
    structure_key: str | None = None,
    balance_key: str | None = None,
) -> tuple[list[str], list[str], dict[str, str], dict[str, str], dict[str, str], dict[str, Any]]:
    vhh_map = cluster_sequences([clean(row.get("vhh_seq")) for row in rows], vhh_threshold)
    antigen_map = cluster_sequences([clean(row.get("antigen_seq")) for row in rows], antigen_threshold)
    cdr3_map = cluster_sequences(
        [clean(row.get("vhh_seq")) for row in rows],
        cdr3_proxy_threshold,
        transform=cdr3_proxy,
    )

    uf = UnionFind(len(rows))
    owners: dict[tuple[str, str], int] = {}
    for idx, row in enumerate(rows):
        vhh = clean(row.get("vhh_seq")).upper()
        antigen = clean(row.get("antigen_seq")).upper()
        keys = [
            ("vhh", vhh_map[vhh]),
            ("cdr3_proxy", cdr3_map[vhh]),
            ("antigen", antigen_map[antigen]),
        ]
        if structure_key and clean(row.get(structure_key)):
            keys.append(("structure", clean(row.get(structure_key))))
        for key in keys:
            if key in owners:
                uf.union(idx, owners[key])
            else:
                owners[key] = idx

    components: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(rows)):
        components[uf.find(idx)].append(idx)

    rng = random.Random(seed)
    component_items = list(components.values())
    rng.shuffle(component_items)
    component_items.sort(key=len, reverse=True)
    targets = {"train": 0.70 * len(rows), "val": 0.15 * len(rows), "test": 0.15 * len(rows)}
    counts = {split: 0 for split in targets}
    balance_totals = Counter(clean(row.get(balance_key)) or "all" for row in rows) if balance_key else Counter()
    balance_counts = {key: Counter() for key in balance_totals}
    row_split = [""] * len(rows)
    row_group = [""] * len(rows)
    for group_rank, members in enumerate(component_items):
        if balance_key:
            component_balance = Counter(clean(rows[idx].get(balance_key)) or "all" for idx in members)
            candidates: list[tuple[float, int, int, str]] = []
            for split_rank, split_name in enumerate(targets):
                projected = {key: balance_counts[key].copy() for key in balance_totals}
                for key, value in component_balance.items():
                    projected[key][split_name] += value
                projected_counts = counts.copy()
                projected_counts[split_name] += len(members)
                task_error = sum(
                    (
                        projected[key][candidate_split] / balance_totals[key]
                        - targets[candidate_split] / len(rows)
                    )
                    ** 2
                    for key in balance_totals
                    for candidate_split in targets
                )
                overall_error = sum(
                    (
                        projected_counts[candidate_split] / len(rows)
                        - targets[candidate_split] / len(rows)
                    )
                    ** 2
                    for candidate_split in targets
                )
                candidates.append((task_error + 0.25 * overall_error, counts[split_name], split_rank, split_name))
            split = min(candidates)[-1]
            for key, value in component_balance.items():
                balance_counts[key][split] += value
        else:
            remaining = {split: targets[split] - counts[split] for split in targets}
            split = max(remaining, key=lambda name: (remaining[name], -counts[name]))
        group_id = f"connected_group_{group_rank:06d}"
        for idx in members:
            row_split[idx] = split
            row_group[idx] = group_id
        counts[split] += len(members)

    component_sizes = sorted((len(members) for members in component_items), reverse=True)
    stats = {
        "rows": len(rows),
        "components": len(component_items),
        "largest_component": component_sizes[0] if component_sizes else 0,
        "split_counts": Counter(row_split),
        "vhh_clusters": len(set(vhh_map.values())),
        "cdr3_proxy_clusters": len(set(cdr3_map.values())),
        "antigen_clusters": len(set(antigen_map.values())),
    }
    if balance_key:
        stats["balance_key"] = balance_key
        stats["task_split_counts"] = {key: dict(value) for key, value in balance_counts.items()}
    return row_split, row_group, vhh_map, cdr3_map, antigen_map, stats


def overlap_report(rows: list[dict[str, Any]], split_key: str = "split") -> dict[str, Any]:
    report: dict[str, Any] = {}
    for field in ["vhh_seq", "antigen_seq", "vhh_cluster_id", "cdr3_proxy_cluster_id", "antigen_cluster_id"]:
        by_split = {
            split: {clean(row.get(field)) for row in rows if row.get(split_key) == split and clean(row.get(field))}
            for split in ["train", "val", "test"]
        }
        report[field] = {
            "train_val": len(by_split["train"] & by_split["val"]),
            "train_test": len(by_split["train"] & by_split["test"]),
            "val_test": len(by_split["val"] & by_split["test"]),
        }
    return report


def write_site_and_pair_outputs(
    out_root: Path,
    site: pd.DataFrame,
    assignments: dict[str, Any],
) -> dict[str, Any]:
    splits = assignments["splits"]
    groups = assignments["groups"]
    vhh_map = assignments["vhh_map"]
    cdr3_map = assignments["cdr3_map"]
    antigen_map = assignments["antigen_map"]
    site["split"] = splits
    site["split_group_id"] = groups
    site["vhh_cluster_id"] = [vhh_map[clean(seq).upper()] for seq in site["vhh_seq"]]
    site["cdr3_proxy_cluster_id"] = [cdr3_map[clean(seq).upper()] for seq in site["vhh_seq"]]
    site["antigen_cluster_id"] = [antigen_map[clean(seq).upper()] for seq in site["antigen_seq"]]
    site_path = out_root / "data_splits/zym_site_split_manifest_v2_clustered.csv"
    site.to_csv(site_path, index=False, quoting=csv.QUOTE_MINIMAL)

    negatives = build_pair_negatives(site, assignments["seed"])
    site_by_id = {row["sample_id"]: row for _, row in site.iterrows()}
    pair_rows: list[dict[str, Any]] = []
    for _, row in site.iterrows():
        pair_rows.append(
            {
                "pair_id": row["sample_id"],
                "split": row["split"],
                "split_group_id": row["split_group_id"],
                "ranking_group_id": row["sample_id"],
                "pdb_id": row["pdb_id"],
                "vhh_seq": row["vhh_seq"],
                "antigen_seq": row["antigen_seq"],
                "vhh_cluster_id": row["vhh_cluster_id"],
                "cdr3_proxy_cluster_id": row["cdr3_proxy_cluster_id"],
                "antigen_cluster_id": row["antigen_cluster_id"],
                "binding_label": 1,
                "contrastive_target": 1,
                "label_state": "observed_positive",
                "label_source": "cognate_structure_pair",
                "negative_type": "positive_cognate_pair",
                "construction_rule": "observed_cognate_pair",
                "ordinary_bce_eligible": "yes",
                "ranking_eligible": "yes",
                "supervision_weight": 1.0,
            }
        )

    triplets: list[dict[str, Any]] = []
    for _, row in negatives.iterrows():
        source = site_by_id[clean(row["source_positive_id"])]
        vhh = clean(row["vhh_seq"]).upper()
        antigen = clean(row["antigen_seq"]).upper()
        pair_rows.append(
            {
                "pair_id": row["negative_id"],
                "split": source["split"],
                "split_group_id": source["split_group_id"],
                "ranking_group_id": source["sample_id"],
                "pdb_id": "",
                "vhh_seq": vhh,
                "antigen_seq": antigen,
                "vhh_cluster_id": vhh_map[vhh],
                "cdr3_proxy_cluster_id": cdr3_map[vhh],
                "antigen_cluster_id": antigen_map[antigen],
                "binding_label": pd.NA,
                "contrastive_target": 0,
                "label_state": "unlabeled_contrastive",
                "label_source": "constructed_unobserved_pair",
                "negative_type": row["negative_type"],
                "construction_rule": row["construction_rule"],
                "ordinary_bce_eligible": "no",
                "ranking_eligible": "yes",
                "supervision_weight": 0.0,
            }
        )
        triplets.append(
            {
                "ranking_group_id": source["sample_id"],
                "split": source["split"],
                "positive_pair_id": source["sample_id"],
                "negative_pair_id": row["negative_id"],
                "negative_type": row["negative_type"],
                "positive_vhh_seq": source["vhh_seq"],
                "positive_antigen_seq": source["antigen_seq"],
                "negative_vhh_seq": vhh,
                "negative_antigen_seq": antigen,
                "preference_label": 1,
                "label_source": "constructed_contrastive_preference",
            }
        )

    pair_path = out_root / "data_splits/pair_binding_split_v2_clustered.csv"
    triplet_path = out_root / "data_splits/pair_ranking_triplets_v2_clustered.csv"
    pd.DataFrame(pair_rows).to_csv(pair_path, index=False, quoting=csv.QUOTE_MINIMAL)
    pd.DataFrame(triplets).to_csv(triplet_path, index=False, quoting=csv.QUOTE_MINIMAL)
    site_records = site.to_dict("records")
    return {
        "site_path": str(site_path),
        "pair_path": str(pair_path),
        "triplet_path": str(triplet_path),
        "site_overlap": overlap_report(site_records),
        "pair_rows": len(pair_rows),
        "triplets": len(triplets),
        "pair_label_states": Counter(clean(row["label_state"]) for row in pair_rows),
    }


def write_contact_outputs(
    out_root: Path,
    records: list[dict[str, Any]],
    assignments: dict[str, Any],
) -> dict[str, Any]:
    splits = assignments["splits"]
    groups = assignments["groups"]
    vhh_map = assignments["vhh_map"]
    cdr3_map = assignments["cdr3_map"]
    antigen_map = assignments["antigen_map"]
    for idx, record in enumerate(records):
        vhh = clean(record["vhh_seq"]).upper()
        antigen = clean(record["antigen_seq"]).upper()
        record["original_split"] = record.get("split", "")
        record["split"] = splits[idx]
        record["split_group_id"] = groups[idx]
        record["vhh_cluster_id"] = vhh_map[vhh]
        record["cdr3_proxy_cluster_id"] = cdr3_map[vhh]
        record["antigen_cluster_id"] = antigen_map[antigen]

    contact_path = out_root / "prepared/structure_contact_maps_v3_clustered.jsonl"
    with contact_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary_rows = [
        {
            "complex_id": record["complex_id"],
            "pdb": record.get("pdb", ""),
            "structure_member": record.get("structure_member", ""),
            "split": record["split"],
            "split_group_id": record["split_group_id"],
            "vhh_cluster_id": record["vhh_cluster_id"],
            "cdr3_proxy_cluster_id": record["cdr3_proxy_cluster_id"],
            "antigen_cluster_id": record["antigen_cluster_id"],
            "vhh_len": len(record["vhh_seq"]),
            "antigen_len": len(record["antigen_seq"]),
            "positive_pairs": len(record["positive_pairs"]),
            "negative_pairs": len(record["negative_pairs"]),
        }
        for record in records
    ]
    manifest_path = out_root / "data_splits/structure_contact_split_manifest_v3_clustered.csv"
    pd.DataFrame(summary_rows).to_csv(manifest_path, index=False, quoting=csv.QUOTE_MINIMAL)
    return {
        "contact_path": str(contact_path),
        "manifest_path": str(manifest_path),
        "contact_overlap": overlap_report(records),
        "positive_pairs": sum(len(record["positive_pairs"]) for record in records),
        "negative_pairs": sum(len(record["negative_pairs"]) for record in records),
    }


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(clean(sequence).upper().encode("ascii")).hexdigest()


def build_global_assignments(
    root: Path,
    out_root: Path,
    args: argparse.Namespace,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    site = read_zym(root).copy().rename(columns={"split": "original_split"})
    contact_source = out_root / "prepared/structure_contact_maps_v2_full2277.jsonl"
    contacts = [json.loads(line) for line in contact_source.open("r", encoding="utf-8") if line.strip()]

    site_rows = site.to_dict("records")
    for row in site_rows:
        row["dataset_role"] = "site"
        row["structure_group"] = f"pdb:{clean(row.get('pdb_id')).lower()}"
    for row in contacts:
        row["dataset_role"] = "contact"
        row["structure_group"] = f"pdb:{clean(row.get('pdb')).lower()}"

    combined = site_rows + contacts
    splits, groups, vhh_map, cdr3_map, antigen_map, stats = assign_connected_splits(
        combined,
        args.vhh_identity,
        args.antigen_identity,
        args.cdr3_proxy_identity,
        args.seed,
        structure_key="structure_group",
        balance_key="dataset_role",
    )
    site_count = len(site_rows)
    common = {
        "vhh_map": vhh_map,
        "cdr3_map": cdr3_map,
        "antigen_map": antigen_map,
        "seed": args.seed,
    }
    site_assignments = {**common, "splits": splits[:site_count], "groups": groups[:site_count]}
    contact_assignments = {**common, "splits": splits[site_count:], "groups": groups[site_count:]}

    manifest_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(combined):
        vhh = clean(row.get("vhh_seq")).upper()
        antigen = clean(row.get("antigen_seq")).upper()
        manifest_rows.append(
            {
                "dataset_role": row["dataset_role"],
                "record_id": clean(row.get("sample_id") or row.get("complex_id")),
                "split": splits[idx],
                "split_group_id": groups[idx],
                "pdb_id": clean(row.get("pdb_id") or row.get("pdb")),
                "structure_member": clean(row.get("structure_member")),
                "vhh_sha256": sequence_sha256(vhh),
                "antigen_sha256": sequence_sha256(antigen),
                "vhh_cluster_id": vhh_map[vhh],
                "cdr3_proxy_cluster_id": cdr3_map[vhh],
                "antigen_cluster_id": antigen_map[antigen],
            }
        )
    manifest_path = out_root / "data_splits/phase2_global_split_manifest_v2_clustered.csv"
    pd.DataFrame(manifest_rows).to_csv(manifest_path, index=False, quoting=csv.QUOTE_MINIMAL)
    stats["manifest_path"] = str(manifest_path)
    return site, contacts, site_assignments, contact_assignments, stats


def controls_overlap(root: Path, site_path: str, contact_path: str) -> dict[str, int]:
    controls = pd.read_csv(root / "experiments/phase2_5080_v1/data_splits/pvrig_external_calibration_manifest_v1.csv")
    control_sequences = {
        clean(seq).upper()
        for seq in controls[controls["role"].isin(["known_positive_calibration_only", "mutant_or_leakage_control"])]["sequence"]
        if clean(seq)
    }
    site = pd.read_csv(site_path)
    site_sequences = set(site["vhh_seq"].dropna().astype(str).str.upper())
    contact_sequences = {
        clean(json.loads(line)["vhh_seq"]).upper()
        for line in Path(contact_path).open("r", encoding="utf-8")
        if line.strip()
    }
    return {
        "site_exact_control_overlap": len(site_sequences & control_sequences),
        "contact_exact_control_overlap": len(contact_sequences & control_sequences),
    }


def all_zero(overlap: dict[str, Any]) -> bool:
    return all(value == 0 for field in overlap.values() for value in field.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--seed", type=int, default=73)
    parser.add_argument("--vhh-identity", type=float, default=0.80)
    parser.add_argument("--antigen-identity", type=float, default=0.70)
    parser.add_argument("--cdr3-proxy-identity", type=float, default=0.90)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_root = root / "experiments/phase2_5080_v1"
    for directory in [out_root / "data_splits", out_root / "prepared", out_root / "audits"]:
        directory.mkdir(parents=True, exist_ok=True)

    site, contact_records, site_assignments, contact_assignments, global_stats = build_global_assignments(
        root, out_root, args
    )
    site_pair = write_site_and_pair_outputs(out_root, site, site_assignments)
    contact = write_contact_outputs(out_root, contact_records, contact_assignments)
    site_pair["site_stats"] = {
        "split_counts": global_stats["task_split_counts"]["site"],
        "components": global_stats["components"],
        "largest_component": global_stats["largest_component"],
    }
    contact["contact_stats"] = {
        "split_counts": global_stats["task_split_counts"]["contact"],
        "components": global_stats["components"],
        "largest_component": global_stats["largest_component"],
    }
    global_overlap = overlap_report(site.to_dict("records") + contact_records)
    controls = controls_overlap(root, site_pair["site_path"], contact["contact_path"])
    status = (
        "PASS"
        if all_zero(site_pair["site_overlap"])
        and all_zero(contact["contact_overlap"])
        and all_zero(global_overlap)
        and not any(controls.values())
        else "FAIL"
    )
    result = {
        "status": status,
        "seed": args.seed,
        "thresholds": {
            "vhh_ungapped_identity": args.vhh_identity,
            "antigen_ungapped_identity": args.antigen_identity,
            "cdr3_proxy_window_identity": args.cdr3_proxy_identity,
        },
        "site_pair": site_pair,
        "contact": contact,
        "global_assignment": global_stats,
        "global_overlap": global_overlap,
        "pvrig_control_overlap": controls,
        "limitations": [
            "cdr3_proxy_cluster_id uses a C-terminal proxy window and is not an ANARCI/IMGT CDR3 assignment",
            "sequence clustering uses deterministic ungapped positional identity and can miss indel-shifted homologs",
            "constructed pairs are contrastive candidates, not experimentally verified non-binders",
        ],
    }
    json_path = out_root / "audits/clustered_split_build_summary_v2.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=dict) + "\n", encoding="utf-8")

    lines = [
        "# Clustered Split Build Audit V2",
        "",
        f"Verdict: {status}",
        "",
        "## Thresholds",
        "",
        f"- VHH ungapped identity: {args.vhh_identity}",
        f"- Antigen ungapped identity: {args.antigen_identity}",
        f"- CDR3 proxy-window identity: {args.cdr3_proxy_identity}",
        "",
        "## Global Assignment",
        "",
        f"- Global manifest: `{global_stats['manifest_path']}`",
        f"- Connected components: {global_stats['components']}",
        f"- Largest connected component: {global_stats['largest_component']}",
        f"- Combined split counts: {dict(global_stats['split_counts'])}",
        f"- Task-balanced split counts: {global_stats['task_split_counts']}",
        f"- Cross-task overlap: `{json.dumps(global_overlap, ensure_ascii=False)}`",
        "",
        "## Site / Pair",
        "",
        f"- Site split counts: {dict(site_pair['site_stats']['split_counts'])}",
        f"- Pair rows: {site_pair['pair_rows']}",
        f"- Ranking triplets: {site_pair['triplets']}",
        f"- Pair label states: {dict(site_pair['pair_label_states'])}",
        f"- Cross-split overlap: `{json.dumps(site_pair['site_overlap'], ensure_ascii=False)}`",
        "",
        "## Contact",
        "",
        f"- Contact split counts: {dict(contact['contact_stats']['split_counts'])}",
        f"- Positive pairs: {contact['positive_pairs']}",
        f"- Negative pairs: {contact['negative_pairs']}",
        f"- Cross-split overlap: `{json.dumps(contact['contact_overlap'], ensure_ascii=False)}`",
        "",
        "## PVRIG Calibration Boundary",
        "",
        f"- Exact control overlap: `{json.dumps(controls, ensure_ascii=False)}`",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in result["limitations"])
    lines.append("")
    audit_path = out_root / "audits/CLUSTERED_SPLIT_BUILD_AUDIT_V2.md"
    audit_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "summary": str(json_path), "audit": str(audit_path)}, ensure_ascii=False, indent=2))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
