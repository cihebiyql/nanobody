#!/usr/bin/env python3
"""Build the cluster-safe real-binding dataset for formal V3-G development.

The original NbBench train/validation split reuses exact VHH sequences across
splits. This builder clusters development VHHs together with the sealed
external hTNFa VHHs, removes development clusters that touch that formal
block, and assigns every remaining cluster to exactly one train/dev/test split.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_BINDING = EXP_DIR / "prepared/phase2_v3_binding/binding_train_dev_v3.csv"
DEFAULT_FORMAL = EXP_DIR / "prepared/phase2_v3_binding/binding_formal_blinded_v3.csv"
DEFAULT_OUTDIR = EXP_DIR / "prepared/phase2_v3_g2"
SPLIT_FRACTIONS = {"train": 0.80, "dev": 0.10, "test": 0.10}
SEED = "phase2_v3_g2_vhh85_seed83"
CLAIM_BOUNDARY = "generic_binding_prior_not_pvrig_binding_affinity_or_blocking_truth"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_key(value: str) -> str:
    return hashlib.sha256(f"{SEED}\t{value}".encode()).hexdigest()


def write_frame_atomic(frame: pd.DataFrame, path: Path, sep: str = ",") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
    frame.to_csv(temp_path, index=False, sep=sep)
    temp_path.replace(path)


def write_json_atomic(payload: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def load_sequence_scopes(binding_path: Path, formal_path: Path) -> dict[str, dict[str, object]]:
    development = pd.read_csv(binding_path, usecols=["sequence_sha256", "vhh_sequence"])
    formal = pd.read_csv(
        formal_path,
        usecols=["formal_block", "sequence_sha256", "vhh_sequence"],
    )
    formal = formal[formal["formal_block"].astype(str) == "external_hTNFa"]
    records: dict[str, dict[str, object]] = {}
    for scope, frame in (("development", development), ("external_hTNFa", formal)):
        for digest, sequence in frame[["sequence_sha256", "vhh_sequence"]].itertuples(index=False, name=None):
            digest = str(digest)
            sequence = str(sequence)
            observed = hashlib.sha256(sequence.encode()).hexdigest()
            if observed != digest:
                raise ValueError(f"Sequence SHA256 mismatch for {digest}")
            record = records.setdefault(digest, {"sequence": sequence, "scopes": set()})
            if record["sequence"] != sequence:
                raise ValueError(f"SHA256 collision for {digest}")
            record["scopes"].add(scope)
    if not records:
        raise ValueError("No VHH sequences were loaded")
    return records


def write_unique_fasta(records: Mapping[str, Mapping[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for digest in sorted(records):
            handle.write(f">{digest}\n{records[digest]['sequence']}\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def run_mmseqs(
    fasta_path: Path,
    output_prefix: Path,
    temp_dir: Path,
    executable: str,
    threads: int,
    min_seq_id: float,
    coverage: float,
) -> Path:
    cluster_tsv = Path(f"{output_prefix}_cluster.tsv")
    command = [
        executable,
        "easy-cluster",
        str(fasta_path),
        str(output_prefix),
        str(temp_dir),
        "--min-seq-id",
        str(min_seq_id),
        "-c",
        str(coverage),
        "--cov-mode",
        "0",
        "--threads",
        str(threads),
    ]
    subprocess.run(command, check=True)
    if not cluster_tsv.is_file():
        raise FileNotFoundError(f"MMseqs cluster table was not created: {cluster_tsv}")
    return cluster_tsv


def parse_cluster_tsv(path: Path, expected_ids: Iterable[str]) -> tuple[dict[str, str], dict[str, str]]:
    expected = set(expected_ids)
    representative_by_member: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 2:
                raise ValueError(f"Malformed MMseqs row {line_number}: {line!r}")
            representative, member = fields[:2]
            if member in representative_by_member and representative_by_member[member] != representative:
                raise ValueError(f"MMseqs member {member} appears in multiple clusters")
            representative_by_member[member] = representative
    missing = expected - set(representative_by_member)
    unexpected = set(representative_by_member) - expected
    if missing or unexpected:
        raise ValueError(
            f"MMseqs membership mismatch: missing={len(missing)} unexpected={len(unexpected)}"
        )
    cluster_id_by_member = {
        member: "vhh85_" + hashlib.sha256(representative.encode()).hexdigest()[:20]
        for member, representative in representative_by_member.items()
    }
    return representative_by_member, cluster_id_by_member


def external_overlap_clusters(
    records: Mapping[str, Mapping[str, object]],
    cluster_by_sequence: Mapping[str, str],
) -> set[str]:
    return {
        cluster_by_sequence[digest]
        for digest, record in records.items()
        if "external_hTNFa" in record["scopes"]
    }


def _cluster_payloads(frame: pd.DataFrame) -> tuple[list[dict[str, object]], Counter[str]]:
    required = {"cluster_id", "sequence_sha256", "dataset_id", "target_id", "label"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Cluster assignment input is missing {sorted(missing)}")
    work = frame.copy()
    work["_stratum"] = (
        work["dataset_id"].astype(str)
        + "|"
        + work["target_id"].astype(str)
        + "|label="
        + work["label"].astype(int).astype(str)
    )
    totals = Counter(work["_stratum"].astype(str))
    payloads: list[dict[str, object]] = []
    for cluster_id, group in work.groupby("cluster_id", sort=False):
        payloads.append(
            {
                "cluster_id": str(cluster_id),
                "row_count": len(group),
                "sequence_count": group["sequence_sha256"].nunique(),
                "strata": Counter(group["_stratum"].astype(str)),
            }
        )
    payloads.sort(
        key=lambda item: (
            -max(
                (count / totals[stratum] for stratum, count in item["strata"].items()),
                default=0.0,
            ),
            -int(item["row_count"]),
            stable_key(str(item["cluster_id"])),
        )
    )
    return payloads, totals


def assign_cluster_splits(
    frame: pd.DataFrame,
    fractions: Mapping[str, float] = SPLIT_FRACTIONS,
) -> dict[str, str]:
    if abs(sum(fractions.values()) - 1.0) > 1e-9:
        raise ValueError("Split fractions must sum to one")
    payloads, stratum_totals = _cluster_payloads(frame)
    row_total = len(frame)
    sequence_total = frame["sequence_sha256"].nunique()
    cluster_total = len(payloads)
    row_counts = Counter()
    sequence_counts = Counter()
    cluster_counts = Counter()
    stratum_counts: dict[str, Counter[str]] = {
        split: Counter() for split in fractions
    }
    assignments: dict[str, str] = {}

    def objective(candidate: str, payload: Mapping[str, object]) -> float:
        fraction = fractions[candidate]
        row_load = (row_counts[candidate] + int(payload["row_count"])) / (fraction * row_total)
        sequence_load = (
            sequence_counts[candidate] + int(payload["sequence_count"])
        ) / (fraction * sequence_total)
        cluster_load = (cluster_counts[candidate] + 1) / (fraction * cluster_total)
        stratum_loads = [
            (stratum_counts[candidate][stratum] + count) / (fraction * stratum_totals[stratum])
            for stratum, count in payload["strata"].items()
        ]
        mean_stratum_load = sum(stratum_loads) / len(stratum_loads)
        robust_stratum_load = 0.70 * mean_stratum_load + 0.30 * max(stratum_loads)
        return (
            0.40 * row_load
            + 0.30 * sequence_load
            + 0.20 * cluster_load
            + 0.10 * robust_stratum_load
        )

    for payload in payloads:
        cluster_id = str(payload["cluster_id"])
        split = min(
            fractions,
            key=lambda candidate: (
                objective(candidate, payload),
                row_counts[candidate] / max(fractions[candidate], 1e-9),
                stable_key(f"{cluster_id}|{candidate}"),
            ),
        )
        assignments[cluster_id] = split
        row_counts[split] += int(payload["row_count"])
        sequence_counts[split] += int(payload["sequence_count"])
        cluster_counts[split] += 1
        stratum_counts[split].update(payload["strata"])
    return assignments


def cross_split_overlap(frame: pd.DataFrame, field: str) -> dict[str, int]:
    values = {
        split: set(frame.loc[frame["split"].astype(str) == split, field].astype(str))
        for split in SPLIT_FRACTIONS
    }
    return {
        "train_dev": len(values["train"] & values["dev"]),
        "train_test": len(values["train"] & values["test"]),
        "dev_test": len(values["dev"] & values["test"]),
    }


def build_outputs(
    binding_path: Path,
    formal_path: Path,
    outdir: Path,
    records: Mapping[str, Mapping[str, object]],
    representative_by_member: Mapping[str, str],
    cluster_by_sequence: Mapping[str, str],
    cluster_tsv: Path,
    min_seq_id: float,
    coverage: float,
) -> dict[str, object]:
    binding = pd.read_csv(binding_path)
    binding["original_split"] = binding["split"].astype(str)
    binding["cluster_id"] = binding["sequence_sha256"].astype(str).map(cluster_by_sequence)
    if binding["cluster_id"].isna().any():
        raise ValueError("Some development rows lack MMseqs cluster membership")

    external_clusters = external_overlap_clusters(records, cluster_by_sequence)
    excluded = binding[binding["cluster_id"].isin(external_clusters)].copy()
    retained = binding[~binding["cluster_id"].isin(external_clusters)].copy()
    if retained.empty:
        raise ValueError("All development rows overlap the external hTNFa cluster set")
    assignments = assign_cluster_splits(retained)
    retained["split"] = retained["cluster_id"].map(assignments)
    retained["split_policy"] = "mmseqs_vhh85_cluster_safe_80_10_10"
    retained = retained.sort_values(["split", "cluster_id", "sample_id"]).reset_index(drop=True)

    cluster_sizes = Counter(cluster_by_sequence.values())
    membership_rows = []
    for digest in sorted(records):
        scopes = sorted(records[digest]["scopes"])
        cluster_id = cluster_by_sequence[digest]
        membership_rows.append(
            {
                "sequence_sha256": digest,
                "representative_sha256": representative_by_member[digest],
                "cluster_id": cluster_id,
                "cluster_sequence_count": cluster_sizes[cluster_id],
                "scopes": ";".join(scopes),
                "touches_external_hTNFa": cluster_id in external_clusters,
                "assigned_split": assignments.get(cluster_id, "formal_external_or_excluded"),
            }
        )
    membership = pd.DataFrame(membership_rows)

    cluster_manifest = (
        retained.groupby(["cluster_id", "split"], as_index=False)
        .agg(
            row_count=("sample_id", "size"),
            unique_vhh=("sequence_sha256", "nunique"),
            source_dataset_count=("dataset_id", "nunique"),
            target_count=("target_id", "nunique"),
            positive_rows=("label", lambda values: int((values.astype(int) == 1).sum())),
            negative_rows=("label", lambda values: int((values.astype(int) == 0).sum())),
        )
        .sort_values(["split", "cluster_id"])
    )
    stratum_counts = (
        retained.groupby(["split", "dataset_id", "target_id", "label"])
        .size()
        .rename("row_count")
        .reset_index()
        .sort_values(["split", "dataset_id", "target_id", "label"])
    )

    sequence_rows: dict[str, dict[str, object]] = {}
    for row in retained.itertuples(index=False):
        for role, digest, sequence in (
            ("vhh", str(row.sequence_sha256), str(row.vhh_sequence)),
            ("antigen", str(row.target_sequence_sha256), str(row.target_sequence)),
        ):
            entry = sequence_rows.setdefault(
                digest,
                {"sequence_sha256": digest, "sequence": sequence, "sequence_length": len(sequence), "roles": set()},
            )
            if entry["sequence"] != sequence:
                raise ValueError(f"SHA256 collision in retained sequence manifest: {digest}")
            entry["roles"].add(role)
    sequence_manifest = pd.DataFrame(
        [{**entry, "roles": ";".join(sorted(entry["roles"]))} for _, entry in sorted(sequence_rows.items())]
    )

    binding_out = outdir / "binding_cluster_safe_v1.csv"
    membership_out = outdir / "vhh_cluster_membership_v1.tsv"
    cluster_out = outdir / "vhh_cluster_split_manifest_v1.csv"
    stratum_out = outdir / "split_stratum_counts_v1.csv"
    sequence_out = outdir / "sequence_manifest_v1.csv"
    excluded_out = outdir / "external_hTNFa_near_overlap_exclusions_v1.csv"
    write_frame_atomic(retained, binding_out)
    write_frame_atomic(membership, membership_out, sep="\t")
    write_frame_atomic(cluster_manifest, cluster_out)
    write_frame_atomic(stratum_counts, stratum_out)
    write_frame_atomic(sequence_manifest, sequence_out)
    write_frame_atomic(
        excluded[["sample_id", "sequence_sha256", "cluster_id", "dataset_id", "target_id", "label"]],
        excluded_out,
    )

    split_rows = Counter(retained["split"].astype(str))
    split_sequences = {
        split: retained.loc[retained["split"] == split, "sequence_sha256"].nunique()
        for split in SPLIT_FRACTIONS
    }
    split_clusters = Counter(cluster_manifest["split"].astype(str))
    missing_strata = [
        {"dataset_id": dataset, "target_id": target, "label": int(label), "missing_split": split}
        for (dataset, target, label), group in retained.groupby(["dataset_id", "target_id", "label"])
        for split in SPLIT_FRACTIONS
        if split not in set(group["split"].astype(str))
    ]
    pair_overlap = cross_split_overlap(retained, "sample_id")
    vhh_overlap = cross_split_overlap(retained, "sequence_sha256")
    cluster_overlap = cross_split_overlap(retained, "cluster_id")
    retained_external_overlap = len(set(retained["cluster_id"].astype(str)) & external_clusters)
    row_fraction_delta = {
        split: split_rows[split] / len(retained) - fraction
        for split, fraction in SPLIT_FRACTIONS.items()
    }
    sequence_fraction_delta = {
        split: split_sequences[split] / retained["sequence_sha256"].nunique() - fraction
        for split, fraction in SPLIT_FRACTIONS.items()
    }
    cluster_fraction_delta = {
        split: split_clusters[split] / retained["cluster_id"].nunique() - fraction
        for split, fraction in SPLIT_FRACTIONS.items()
    }
    status = "PASS_CLUSTER_SAFE_BINDING_DATA_READY"
    failure_reasons = []
    if any(pair_overlap.values()) or any(vhh_overlap.values()) or any(cluster_overlap.values()):
        failure_reasons.append("cross_split_leakage")
    if retained_external_overlap:
        failure_reasons.append("external_hTNFa_cluster_overlap")
    if missing_strata:
        failure_reasons.append("missing_target_label_strata")
    if max(abs(value) for value in row_fraction_delta.values()) > 0.03:
        failure_reasons.append("split_ratio_outside_3_percent_tolerance")
    if max(abs(value) for value in sequence_fraction_delta.values()) > 0.03:
        failure_reasons.append("sequence_ratio_outside_3_percent_tolerance")
    if max(abs(value) for value in cluster_fraction_delta.values()) > 0.03:
        failure_reasons.append("cluster_ratio_outside_3_percent_tolerance")
    if failure_reasons:
        status = "FAIL_" + "_AND_".join(failure_reasons).upper()

    output_paths = {
        "binding": binding_out,
        "membership": membership_out,
        "cluster_manifest": cluster_out,
        "stratum_counts": stratum_out,
        "sequence_manifest": sequence_out,
        "external_exclusions": excluded_out,
    }
    audit: dict[str, object] = {
        "status": status,
        "failure_reasons": failure_reasons,
        "schema_version": "phase2_v3_g2_cluster_safe_prepare_audit_v1",
        "seed": SEED,
        "mmseqs": {
            "min_sequence_identity": min_seq_id,
            "coverage": coverage,
            "coverage_mode": 0,
            "cluster_tsv": str(cluster_tsv),
            "cluster_tsv_sha256": sha256_file(cluster_tsv),
        },
        "source_counts": {
            "development_rows": len(binding),
            "development_unique_vhh": binding["sequence_sha256"].nunique(),
            "external_hTNFa_unique_vhh": sum(
                "external_hTNFa" in record["scopes"] for record in records.values()
            ),
            "all_clustered_unique_vhh": len(records),
            "mmseqs_cluster_count": len(set(cluster_by_sequence.values())),
        },
        "external_hTNFa_protection": {
            "touching_cluster_count": len(external_clusters),
            "excluded_development_rows": len(excluded),
            "excluded_development_unique_vhh": excluded["sequence_sha256"].nunique(),
            "retained_external_cluster_overlap": retained_external_overlap,
        },
        "retained_counts": {
            "rows": len(retained),
            "unique_vhh": retained["sequence_sha256"].nunique(),
            "clusters": retained["cluster_id"].nunique(),
            "rows_by_split": dict(split_rows),
            "unique_vhh_by_split": split_sequences,
            "clusters_by_split": dict(split_clusters),
            "row_fraction_delta": row_fraction_delta,
            "sequence_fraction_delta": sequence_fraction_delta,
            "cluster_fraction_delta": cluster_fraction_delta,
        },
        "overlap_audit": {
            "sample_id": pair_overlap,
            "exact_vhh": vhh_overlap,
            "mmseqs_cluster": cluster_overlap,
        },
        "missing_target_label_strata": missing_strata,
        "input_sha256": {
            str(binding_path): sha256_file(binding_path),
            str(formal_path): sha256_file(formal_path),
        },
        "output_paths": {key: str(value) for key, value in output_paths.items()},
        "output_sha256": {key: sha256_file(value) for key, value in output_paths.items()},
        "formal_evaluation_policy": (
            "Use the new cluster-safe test split for internal model selection claims. Keep external_hTNFa sealed "
            "as the primary external block. Existing hIL6/SARS transfer blocks remain diagnostic because their "
            "VHH parents overlap development data."
        ),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path = outdir / "prepare_audit_v1.json"
    write_json_atomic(audit, audit_path)
    if not status.startswith("PASS"):
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def prepare(
    binding_path: Path,
    formal_path: Path,
    outdir: Path,
    executable: str,
    threads: int,
    min_seq_id: float,
    coverage: float,
    reuse_clusters: bool,
) -> dict[str, object]:
    outdir.mkdir(parents=True, exist_ok=True)
    records = load_sequence_scopes(binding_path, formal_path)
    fasta_path = outdir / "unique_vhh_development_plus_external_hTNFa_v1.fasta"
    write_unique_fasta(records, fasta_path)
    output_prefix = outdir / "mmseqs_vhh85_v1"
    cluster_tsv = Path(f"{output_prefix}_cluster.tsv")
    if not (reuse_clusters and cluster_tsv.is_file()):
        cluster_tsv = run_mmseqs(
            fasta_path,
            output_prefix,
            outdir / "mmseqs_tmp",
            executable,
            threads,
            min_seq_id,
            coverage,
        )
    representative_by_member, cluster_by_sequence = parse_cluster_tsv(cluster_tsv, records)
    return build_outputs(
        binding_path,
        formal_path,
        outdir,
        records,
        representative_by_member,
        cluster_by_sequence,
        cluster_tsv,
        min_seq_id,
        coverage,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    parser.add_argument("--formal", type=Path, default=DEFAULT_FORMAL)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--mmseqs", default="mmseqs")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--min-seq-id", type=float, default=0.85)
    parser.add_argument("--coverage", type=float, default=0.80)
    parser.add_argument("--reuse-clusters", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    audit = prepare(
        args.binding,
        args.formal,
        args.outdir,
        args.mmseqs,
        args.threads,
        args.min_seq_id,
        args.coverage,
        args.reuse_clusters,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
