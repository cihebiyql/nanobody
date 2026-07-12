#!/usr/bin/env python3
"""Freeze V3-G1 multitask sources and build a real-binding smoke dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_BINDING = EXP_DIR / "prepared/phase2_v3_binding/binding_train_dev_v3.csv"
DEFAULT_BINDING_AUDIT = EXP_DIR / "prepared/phase2_v3_binding/binding_prepare_audit_v3.json"
DEFAULT_CONTACT = EXP_DIR / "prepared/structure_contact_maps_v3_clustered.jsonl"
DEFAULT_SITE = EXP_DIR / "data_splits/zym_site_split_manifest_v2_clustered.csv"
DEFAULT_CLUSTER_AUDIT = EXP_DIR / "audits/clustered_split_build_summary_v2.json"
DEFAULT_OUTDIR = EXP_DIR / "prepared/phase2_v3_g1"
CLAIM_BOUNDARY = "generic_multitask_smoke_not_pvrig_binding_affinity_or_blocking_truth"
SMOKE_PER_TARGET_SPLIT = 512
SEED = "phase2_v3_g1_smoke_seed73"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_key(sample_id: str) -> str:
    return hashlib.sha256(f"{SEED}\t{sample_id}".encode()).hexdigest()


def select_smoke(frame: pd.DataFrame, per_target_split: int = SMOKE_PER_TARGET_SPLIT) -> pd.DataFrame:
    required = {"sample_id", "dataset_id", "split", "target_id", "vhh_sequence", "target_sequence", "label"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Binding data missing columns: {sorted(missing)}")
    selected: list[pd.DataFrame] = []
    for (split, dataset_id, target_id), group in frame.groupby(["split", "dataset_id", "target_id"], sort=True):
        if split not in {"train", "dev"}:
            continue
        positives = group[group["label"].astype(int) == 1].copy()
        negatives = group[group["label"].astype(int) == 0].copy()
        if positives.empty or negatives.empty:
            raise ValueError(f"Target group lacks both labels: {(split, dataset_id, target_id)}")
        positive_target = min(per_target_split // 2, len(positives))
        negative_target = min(per_target_split - positive_target, len(negatives))
        remaining = per_target_split - positive_target - negative_target
        if remaining:
            extra_pos = min(remaining, len(positives) - positive_target)
            positive_target += extra_pos
            remaining -= extra_pos
        if remaining:
            extra_neg = min(remaining, len(negatives) - negative_target)
            negative_target += extra_neg
            remaining -= extra_neg
        if remaining:
            raise ValueError(f"Target group is too small for requested smoke quota: {(split, dataset_id, target_id)}")
        positives["_stable_key"] = positives["sample_id"].astype(str).map(stable_key)
        negatives["_stable_key"] = negatives["sample_id"].astype(str).map(stable_key)
        selected.append(positives.sort_values("_stable_key").head(positive_target))
        selected.append(negatives.sort_values("_stable_key").head(negative_target))
    output = pd.concat(selected, ignore_index=True).drop(columns=["_stable_key"])
    return output.sort_values(["split", "dataset_id", "target_id", "sample_id"]).reset_index(drop=True)


def sequence_manifest(frame: pd.DataFrame) -> pd.DataFrame:
    rows: dict[str, dict[str, object]] = {}
    for row in frame.itertuples(index=False):
        for role, sequence in (("vhh", str(row.vhh_sequence)), ("antigen", str(row.target_sequence))):
            digest = hashlib.sha256(sequence.encode()).hexdigest()
            existing = rows.setdefault(
                digest,
                {"sequence_sha256": digest, "sequence": sequence, "sequence_length": len(sequence), "roles": set()},
            )
            if existing["sequence"] != sequence:
                raise ValueError(f"SHA256 collision: {digest}")
            existing["roles"].add(role)
    return pd.DataFrame(
        [
            {**row, "roles": ";".join(sorted(row["roles"]))}
            for _, row in sorted(rows.items())
        ]
    )


def overlap_audit(frame: pd.DataFrame) -> dict[str, object]:
    train = frame[frame["split"].astype(str) == "train"]
    dev = frame[frame["split"].astype(str) == "dev"]
    train_pairs = set(train["sample_id"].astype(str))
    dev_pairs = set(dev["sample_id"].astype(str))
    train_vhh = set(train["sequence_sha256"].astype(str))
    dev_vhh = set(dev["sequence_sha256"].astype(str))
    train_target = set(train["target_sequence_sha256"].astype(str))
    dev_target = set(dev["target_sequence_sha256"].astype(str))
    return {
        "exact_pair_overlap": len(train_pairs & dev_pairs),
        "exact_vhh_overlap": len(train_vhh & dev_vhh),
        "exact_target_overlap": len(train_target & dev_target),
        "interpretation": (
            "Exact VHH overlap is expected in mutation-transfer source splits and makes this smoke set unsuitable "
            "for unseen-parent formal claims."
        ),
    }


def run(
    binding_path: Path,
    binding_audit_path: Path,
    contact_path: Path,
    site_path: Path,
    cluster_audit_path: Path,
    outdir: Path,
    per_target_split: int,
) -> dict[str, object]:
    frame = pd.read_csv(binding_path)
    if set(frame["split"].astype(str)) != {"train", "dev"}:
        raise ValueError("Binding source must contain exactly train/dev rows")
    smoke = select_smoke(frame, per_target_split)
    outdir.mkdir(parents=True, exist_ok=True)
    smoke_path = outdir / "binding_smoke_train_dev_v1.csv"
    sequence_path = outdir / "sequence_manifest_smoke_v1.csv"
    registry_path = outdir / "multitask_source_registry_v1.json"
    audit_path = outdir / "prepare_audit_v1.json"
    smoke.to_csv(smoke_path, index=False)
    sequence_manifest(smoke).to_csv(sequence_path, index=False)

    binding_audit = json.loads(binding_audit_path.read_text(encoding="utf-8"))
    cluster_audit = json.loads(cluster_audit_path.read_text(encoding="utf-8"))
    registry = {
        "schema_version": "phase2_v3_g1_multitask_source_registry_v1",
        "tasks": {
            "contact": {
                "path": str(contact_path),
                "rows": sum(1 for line in contact_path.open(encoding="utf-8") if line.strip()),
                "supervision": "real_structure_residue_contact",
            },
            "site": {
                "path": str(site_path),
                "rows": len(pd.read_csv(site_path)),
                "supervision": "paratope_epitope",
            },
            "real_binding_smoke": {
                "path": str(smoke_path),
                "rows": len(smoke),
                "supervision": "real_binary_binding_assay",
            },
        },
        "source_split_policy": {
            "contact_site": "existing global clustered split with zero audited exact/cluster overlap",
            "binding_smoke": "preserved NbBench target/mutation split; not parent-cluster formal safe",
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    group_counts = (
        smoke.groupby(["split", "dataset_id", "target_id", "label"]).size().rename("count").reset_index().to_dict("records")
    )
    audit: dict[str, object] = {
        "status": "PASS_SMOKE_DATA_READY",
        "schema_version": "phase2_v3_g1_prepare_audit_v1",
        "seed": SEED,
        "binding_source_rows": len(frame),
        "binding_source_counts": dict(Counter(frame["split"].astype(str))),
        "binding_source_audit_sha256": sha256_file(binding_audit_path),
        "binding_source_reported_counts": binding_audit.get("row_counts", {}),
        "smoke_rows": len(smoke),
        "smoke_counts": dict(Counter(smoke["split"].astype(str))),
        "smoke_group_label_counts": group_counts,
        "smoke_overlap_audit": overlap_audit(smoke),
        "contact_cluster_audit_status": cluster_audit.get("status"),
        "contact_global_overlap": cluster_audit.get("global_overlap"),
        "formal_readiness": "NOT_READY_REQUIRES_VHH_PARENT_CLUSTER_SPLIT_FOR_REAL_BINDING_ROWS",
        "input_sha256": {
            str(binding_path): sha256_file(binding_path),
            str(contact_path): sha256_file(contact_path),
            str(site_path): sha256_file(site_path),
            str(cluster_audit_path): sha256_file(cluster_audit_path),
        },
        "output_sha256": {
            str(smoke_path): sha256_file(smoke_path),
            str(sequence_path): sha256_file(sequence_path),
            str(registry_path): sha256_file(registry_path),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if audit["smoke_overlap_audit"]["exact_pair_overlap"] != 0:
        audit["status"] = "FAIL_EXACT_PAIR_LEAKAGE"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not str(audit["status"]).startswith("PASS"):
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    parser.add_argument("--binding-audit", type=Path, default=DEFAULT_BINDING_AUDIT)
    parser.add_argument("--contact", type=Path, default=DEFAULT_CONTACT)
    parser.add_argument("--site", type=Path, default=DEFAULT_SITE)
    parser.add_argument("--cluster-audit", type=Path, default=DEFAULT_CLUSTER_AUDIT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--per-target-split", type=int, default=SMOKE_PER_TARGET_SPLIT)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(
        json.dumps(
            run(
                args.binding,
                args.binding_audit,
                args.contact,
                args.site,
                args.cluster_audit,
                args.outdir,
                args.per_target_split,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
