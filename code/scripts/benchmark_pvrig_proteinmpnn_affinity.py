#!/usr/bin/env python3
"""Prepare and aggregate a PVRIG ProteinMPNN complex-likelihood benchmark."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(args.mpnn_root))
    from protein_mpnn_utils import parse_PDB  # type: ignore

    args.output.mkdir(parents=True, exist_ok=True)
    poses = sorted(args.pose_dir.glob("*.pdb"))
    if len(poses) != args.expected_poses:
        raise SystemExit(f"expected {args.expected_poses} poses, found {len(poses)}")

    parsed_path = args.output / "pvrig_positive11_poses.jsonl"
    chain_path = args.output / "designed_vhh_chain.jsonl"
    manifest_path = args.output / "pose_manifest.tsv"
    chain_map: dict[str, list[list[str]]] = {}
    known = pd.read_csv(args.known, sep="\t")
    known_sequences = {}
    for row in known.itertuples(index=False):
        fasta = Path(row.source_fasta)
        sequence = "".join(line.strip() for line in fasta.read_text().splitlines() if not line.startswith(">"))
        known_sequences[row.candidate_id] = sequence

    with parsed_path.open("w") as parsed_handle, manifest_path.open("w", newline="") as manifest_handle:
        fields = ["candidate_id", "pose_name", "pdb_path", "pdb_sha256", "antigen_chain", "vhh_chain"]
        writer = csv.DictWriter(manifest_handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for pose in poses:
            records = parse_PDB(str(pose), input_chain_list=["A", "B"])
            if len(records) != 1:
                raise SystemExit(f"could not parse exactly one complex: {pose}")
            record = records[0]
            if not record.get("seq_chain_A") or not record.get("seq_chain_B"):
                raise SystemExit(f"missing A/B chains: {pose}")
            candidate_id = record["name"].split("__pose", 1)[0]
            expected_vhh = known_sequences[candidate_id]
            matches = [chain for chain in ("A", "B") if record[f"seq_chain_{chain}"] == expected_vhh]
            if len(matches) != 1:
                raise SystemExit(f"could not identify VHH chain by exact sequence: {pose} matches={matches}")
            vhh_chain = matches[0]
            antigen_chain = "B" if vhh_chain == "A" else "A"
            if "X" in record[f"seq_chain_{vhh_chain}"] or "-" in record[f"seq_chain_{vhh_chain}"]:
                raise SystemExit(f"non-canonical VHH chain sequence: {pose}")
            parsed_handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            chain_map[record["name"]] = [[vhh_chain], [antigen_chain]]
            writer.writerow(
                {
                    "candidate_id": candidate_id,
                    "pose_name": record["name"],
                    "pdb_path": str(pose.resolve()),
                    "pdb_sha256": sha256(pose),
                    "antigen_chain": antigen_chain,
                    "vhh_chain": vhh_chain,
                }
            )

    chain_path.write_text(json.dumps(chain_map, sort_keys=True) + "\n")
    receipt = {
        "status": "READY",
        "poses": len(poses),
        "candidates": len({path.name.split("__pose", 1)[0] for path in poses}),
        "chain_identification": "exact match to hash-bound positive VHH FASTA",
        "vhh_chain_counts": {
            str(chain): int(count)
            for chain, count in pd.read_csv(manifest_path, sep="\t")["vhh_chain"].value_counts().items()
        },
        "parsed_jsonl_sha256": sha256(parsed_path),
        "chain_jsonl_sha256": sha256(chain_path),
        "manifest_sha256": sha256(manifest_path),
        "scientific_boundary": "complex-conditioned sequence likelihood; not predicted Kd",
    }
    (args.output / "PREPARED.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


def direction_metrics(frame: pd.DataFrame, feature: str) -> dict[str, object]:
    details = []
    correct = wrong = ties = 0
    for family, group in frame.dropna(subset=["known_pkd", feature]).groupby("family"):
        rows = list(group.itertuples(index=False))
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                exp = math.copysign(1.0, a.known_pkd - b.known_pkd) if a.known_pkd != b.known_pkd else 0.0
                pred_a, pred_b = getattr(a, feature), getattr(b, feature)
                pred = math.copysign(1.0, pred_a - pred_b) if pred_a != pred_b else 0.0
                if pred == 0:
                    ties += 1
                    verdict = "tie"
                elif pred == exp:
                    correct += 1
                    verdict = "correct"
                else:
                    wrong += 1
                    verdict = "wrong"
                details.append({"family": family, "a": a.molecule_name, "b": b.molecule_name, "verdict": verdict})
    return {"correct": correct, "wrong": wrong, "ties": ties, "total": len(details), "details": details}


def aggregate(args: argparse.Namespace) -> int:
    args.output.mkdir(parents=True, exist_ok=True)
    suffix = "vhh" if args.scope == "full_vhh" else args.scope
    prefix = f"proteinmpnn_loglik_{suffix}"
    nll_prefix = f"proteinmpnn_nll_{suffix}"
    manifest = pd.read_csv(args.prepared / "pose_manifest.tsv", sep="\t")
    rows = []
    for row in manifest.itertuples(index=False):
        result = args.score_dir / f"{row.pose_name}_pdb.npz"
        if not result.is_file():
            raise SystemExit(f"missing ProteinMPNN score: {result}")
        data = np.load(result)
        score = float(np.asarray(data["score"]).reshape(-1)[0])
        global_score = float(np.asarray(data["global_score"]).reshape(-1)[0])
        rows.append(
            {
                "candidate_id": row.candidate_id,
                "pose_name": row.pose_name,
                "pdb_sha256": row.pdb_sha256,
                nll_prefix: score,
                prefix: -score,
                "proteinmpnn_global_nll": global_score,
                "score_npz_sha256": sha256(result),
            }
        )
    pose_frame = pd.DataFrame(rows)
    pose_frame.to_csv(args.output / "proteinmpnn_pose_scores.tsv", sep="\t", index=False)

    candidate = (
        pose_frame.groupby("candidate_id", as_index=False)
        .agg(
            pose_count=("pose_name", "count"),
            **{
                f"{prefix}_median": (prefix, "median"),
                f"{prefix}_mean": (prefix, "mean"),
                f"{prefix}_stdev": (prefix, "std"),
                f"{prefix}_min": (prefix, "min"),
                f"{prefix}_max": (prefix, "max"),
            },
        )
    )
    known = pd.read_csv(args.known, sep="\t")
    keep = ["candidate_id", "molecule_name", "family", "known_kd_m", "known_pkd", "deepnano_binding_prior"]
    candidate = known[keep].merge(candidate, on="candidate_id", how="left", validate="one_to_one")
    if len(candidate) != 11 or not (candidate["pose_count"] == 9).all():
        raise SystemExit("candidate/pose cardinality mismatch")
    candidate.to_csv(args.output / "proteinmpnn_candidate_summary.tsv", sep="\t", index=False)

    feature = f"{prefix}_median"
    eval_frame = candidate.dropna(subset=["known_pkd", feature]).copy()
    metrics = {
        "status": "PASS",
        "n_known_kd": len(eval_frame),
        "pearson_vs_pKd": float(eval_frame[[feature, "known_pkd"]].corr(method="pearson").iloc[0, 1]),
        "spearman_vs_pKd": float(eval_frame[[feature, "known_pkd"]].corr(method="spearman").iloc[0, 1]),
        "within_family_direction": direction_metrics(eval_frame, feature),
        "pose_count": len(pose_frame),
        "candidate_count": len(candidate),
        "model": "ProteinMPNN v_48_020",
        "feature": feature,
        "scope": args.scope,
        "aggregation": f"median {args.scope} log-likelihood across 9 frozen HADDOCK poses",
        "scientific_boundary": "weak complex-conditioned affinity evidence; not predicted Kd",
    }
    (args.output / "evaluation_metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    sums = []
    for path in sorted(args.output.glob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            sums.append(f"{sha256(path)}  {path.name}")
    (args.output / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print(json.dumps(metrics, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--pose-dir", type=Path, required=True)
    prep.add_argument("--mpnn-root", type=Path, required=True)
    prep.add_argument("--known", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--expected-poses", type=int, default=99)
    prep.set_defaults(func=prepare)
    agg = sub.add_parser("aggregate")
    agg.add_argument("--prepared", type=Path, required=True)
    agg.add_argument("--score-dir", type=Path, required=True)
    agg.add_argument("--known", type=Path, required=True)
    agg.add_argument("--output", type=Path, required=True)
    agg.add_argument("--scope", choices=("full_vhh", "cdr123", "cdr13", "cdr3"), default="full_vhh")
    agg.set_defaults(func=aggregate)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
