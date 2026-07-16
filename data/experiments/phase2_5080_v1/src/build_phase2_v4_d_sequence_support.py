#!/usr/bin/env python3
"""Build the label-free V4-D sequence-support and OOD deployment audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCHEMA_VERSION = "phase2_v4_d_sequence_support_v1"
EXPECTED_SPLIT_SHA256 = "c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd"
EXPECTED_POOL_SHA256 = "dd97835cfa3e39229d3ebddfe37768c7a8346a6237e35d2dbe16dc3d16ab965b"
REFERENCE_SPLIT = "OPEN_TRAIN"
KMER_SIZE = 3
KMER_WIDTH = 256
SUPPORT_QUANTILE = 0.95
QUANTILE_METHOD = "linear"
NULL_SEED = 20260715
NULL_REPLICATES = 1000
CANONICAL_AA = frozenset("ACDEFGHIKLMNPQRSTVWY")


class SupportError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def read_table(path: Path, delimiter: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise SupportError("cannot_write_empty_csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def normalize_sequence(sequence: str, field: str) -> str:
    normalized = sequence.strip().upper()
    if not normalized:
        raise SupportError(f"empty_sequence:{field}")
    invalid = sorted(set(normalized) - CANONICAL_AA)
    if invalid:
        raise SupportError(f"noncanonical_sequence:{field}:{''.join(invalid)}")
    return normalized


def validate_unique_ids(rows: Iterable[dict[str, str]], label: str) -> None:
    seen: set[str] = set()
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        if not candidate_id:
            raise SupportError(f"missing_candidate_id:{label}")
        if candidate_id in seen:
            raise SupportError(f"duplicate_candidate_id:{label}:{candidate_id}")
        seen.add(candidate_id)


def canonicalize_reference_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        sequence = normalize_sequence(row.get("sequence", ""), "reference_sequence")
        cdr3 = normalize_sequence(row.get("cdr3", ""), "reference_cdr3")
        sequence_sha256 = row.get("sequence_sha256", "")
        observed_sha256 = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if sequence_sha256 != observed_sha256:
            raise SupportError(f"reference_sequence_sha256_mismatch:{row.get('candidate_id', '')}")
        cluster = row.get("parent_framework_cluster", "")
        if not cluster:
            raise SupportError(f"missing_parent_framework_cluster:{row.get('candidate_id', '')}")
        output.append(
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": sequence_sha256,
                "sequence": sequence,
                "cdr3": cdr3,
                "parent_framework_cluster": cluster,
            }
        )
    validate_unique_ids(output, "reference")
    if len({row["parent_framework_cluster"] for row in output}) < 2:
        raise SupportError("lopo_requires_at_least_two_parent_clusters")
    return output


def canonicalize_candidate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        sequence = normalize_sequence(row.get("vhh_sequence", ""), "candidate_sequence")
        cdr3 = normalize_sequence(row.get("cdr3_after", ""), "candidate_cdr3")
        sequence_sha256 = row.get("sequence_sha256", "")
        observed_sha256 = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        if sequence_sha256 != observed_sha256:
            raise SupportError(f"candidate_sequence_sha256_mismatch:{row.get('candidate_id', '')}")
        output.append(
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": sequence_sha256,
                "sequence": sequence,
                "cdr3": cdr3,
                "parent_framework_cluster": row.get("parent_framework_cluster", ""),
            }
        )
    validate_unique_ids(output, "candidate")
    return output


def kmer_vector(
    sequence: str, k: int = KMER_SIZE, width: int = KMER_WIDTH
) -> np.ndarray:
    sequence = normalize_sequence(sequence, "kmer_sequence")
    if len(sequence) < k:
        raise SupportError("sequence_shorter_than_k")
    vector = np.zeros(width, dtype=np.float64)
    for index in range(len(sequence) - k + 1):
        token = sequence[index : index + k].encode("ascii")
        bucket = int.from_bytes(hashlib.sha256(token).digest()[:8], "big") % width
        vector[bucket] += 1.0
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise SupportError("zero_kmer_vector")
    return vector / norm


def kmer_matrix(rows: list[dict[str, str]]) -> np.ndarray:
    return np.stack([kmer_vector(row["sequence"]) for row in rows])


def levenshtein(left: str, right: str) -> int:
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for right_index, right_char in enumerate(right, 1):
        current = [right_index]
        for left_index, left_char in enumerate(left, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[left_index] + 1,
                    previous[left_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def normalized_levenshtein_distance(left: str, right: str) -> float:
    return levenshtein(left, right) / max(len(left), len(right), 1)


def clamp_cosine_distance(value: float) -> float:
    return min(2.0, max(0.0, value))


def lopo_calibration(
    reference_rows: list[dict[str, str]],
    *,
    support_quantile: float = SUPPORT_QUANTILE,
) -> dict[str, Any]:
    vectors = kmer_matrix(reference_rows)
    similarities = vectors @ vectors.T
    full_distances: list[float] = []
    cdr3_distances: list[float] = []
    row_controls: list[dict[str, Any]] = []

    for index, row in enumerate(reference_rows):
        allowed = np.array(
            [
                other
                for other, candidate in enumerate(reference_rows)
                if candidate["parent_framework_cluster"]
                != row["parent_framework_cluster"]
            ],
            dtype=np.int64,
        )
        if not len(allowed):
            raise SupportError("lopo_neighbor_missing")
        local_full = 1.0 - similarities[index, allowed]
        full_local_index = int(np.argmin(local_full))
        full_index = int(allowed[full_local_index])
        full_distance = clamp_cosine_distance(float(local_full[full_local_index]))

        cdr3_pairs = [
            (
                normalized_levenshtein_distance(
                    row["cdr3"], reference_rows[int(other)]["cdr3"]
                ),
                int(other),
            )
            for other in allowed
        ]
        cdr3_distance, cdr3_index = min(cdr3_pairs, key=lambda pair: (pair[0], pair[1]))
        full_distances.append(full_distance)
        cdr3_distances.append(cdr3_distance)
        row_controls.append(
            {
                "candidate_id": row["candidate_id"],
                "parent_framework_cluster": row["parent_framework_cluster"],
                "nearest_lopo_full_candidate_id": reference_rows[full_index]["candidate_id"],
                "nearest_lopo_full_parent_cluster": reference_rows[full_index][
                    "parent_framework_cluster"
                ],
                "nearest_lopo_full_distance": full_distance,
                "nearest_lopo_cdr3_candidate_id": reference_rows[cdr3_index]["candidate_id"],
                "nearest_lopo_cdr3_parent_cluster": reference_rows[cdr3_index][
                    "parent_framework_cluster"
                ],
                "nearest_lopo_cdr3_distance": cdr3_distance,
            }
        )

    full_threshold = float(
        np.quantile(full_distances, support_quantile, method=QUANTILE_METHOD)
    )
    cdr3_threshold = float(
        np.quantile(cdr3_distances, support_quantile, method=QUANTILE_METHOD)
    )
    joint_count = 0
    for row in row_controls:
        full_pass = row["nearest_lopo_full_distance"] <= full_threshold
        cdr3_pass = row["nearest_lopo_cdr3_distance"] <= cdr3_threshold
        row["full_channel_pass"] = full_pass
        row["cdr3_channel_pass"] = cdr3_pass
        row["joint_pass"] = full_pass and cdr3_pass
        joint_count += int(row["joint_pass"])

    return {
        "full_sequence_threshold": full_threshold,
        "cdr3_threshold": cdr3_threshold,
        "joint_pass_count": joint_count,
        "joint_pass_fraction": joint_count / len(reference_rows),
        "row_controls": row_controls,
        "reference_vectors": vectors,
    }


def shuffled_copy(sequence: str, rng: np.random.Generator) -> str:
    indices = rng.permutation(len(sequence))
    return "".join(sequence[int(index)] for index in indices)


def composition_preserving_shuffle_null(
    reference_rows: list[dict[str, str]],
    reference_vectors: np.ndarray,
    *,
    full_threshold: float,
    cdr3_threshold: float,
    replicates: int = NULL_REPLICATES,
    seed: int = NULL_SEED,
) -> dict[str, Any]:
    if replicates < 1:
        raise SupportError("null_replicates_must_be_positive")
    rng = np.random.default_rng(seed)
    joint_count = 0
    full_count = 0
    cdr3_count = 0
    source_counts: dict[str, int] = {}

    for _ in range(replicates):
        source_index = int(rng.integers(0, len(reference_rows)))
        source = reference_rows[source_index]
        source_cluster = source["parent_framework_cluster"]
        source_counts[source_cluster] = source_counts.get(source_cluster, 0) + 1
        allowed = [
            index
            for index, row in enumerate(reference_rows)
            if row["parent_framework_cluster"] != source_cluster
        ]
        if not allowed:
            raise SupportError("shuffle_null_neighbor_missing")

        shuffled_sequence = shuffled_copy(source["sequence"], rng)
        shuffled_cdr3 = shuffled_copy(source["cdr3"], rng)
        vector = kmer_vector(shuffled_sequence)
        full_distance = clamp_cosine_distance(
            1.0 - float(np.max(reference_vectors[allowed] @ vector))
        )
        cdr3_distance = min(
            normalized_levenshtein_distance(
                shuffled_cdr3, reference_rows[index]["cdr3"]
            )
            for index in allowed
        )
        full_pass = full_distance <= full_threshold
        cdr3_pass = cdr3_distance <= cdr3_threshold
        full_count += int(full_pass)
        cdr3_count += int(cdr3_pass)
        joint_count += int(full_pass and cdr3_pass)

    return {
        "seed": seed,
        "replicates": replicates,
        "source_sampling": "uniform_reference_row_with_replacement",
        "reference_exclusion": "source_parent_framework_cluster",
        "shuffle_policy": "independent_full_sequence_and_imgt_cdr3_composition_preserving_permutations",
        "full_channel_pass_count": full_count,
        "full_channel_pass_fraction": full_count / replicates,
        "cdr3_channel_pass_count": cdr3_count,
        "cdr3_channel_pass_fraction": cdr3_count / replicates,
        "joint_pass_count": joint_count,
        "joint_pass_fraction": joint_count / replicates,
        "sampled_source_parent_cluster_counts": dict(sorted(source_counts.items())),
    }


def score_candidates(
    reference_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    *,
    reference_vectors: np.ndarray,
    full_threshold: float,
    cdr3_threshold: float,
) -> list[dict[str, Any]]:
    candidate_vectors = kmer_matrix(candidate_rows)
    similarities = candidate_vectors @ reference_vectors.T
    full_nearest_indices = np.argmax(similarities, axis=1)
    output: list[dict[str, Any]] = []

    for index, candidate in enumerate(candidate_rows):
        full_index = int(full_nearest_indices[index])
        full_distance = clamp_cosine_distance(
            1.0 - float(similarities[index, full_index])
        )
        cdr3_pairs = [
            (
                normalized_levenshtein_distance(candidate["cdr3"], row["cdr3"]),
                ref_index,
            )
            for ref_index, row in enumerate(reference_rows)
        ]
        cdr3_distance, cdr3_index = min(cdr3_pairs, key=lambda pair: (pair[0], pair[1]))
        full_pass = full_distance <= full_threshold
        cdr3_pass = cdr3_distance <= cdr3_threshold
        in_support = full_pass and cdr3_pass
        if in_support:
            support_domain = "IN_DOMAIN"
        elif full_pass or cdr3_pass:
            support_domain = "NEAR_DOMAIN"
        else:
            support_domain = "OOD"

        output.append(
            {
                "candidate_id": candidate["candidate_id"],
                "sequence_sha256": candidate["sequence_sha256"],
                "parent_framework_cluster": candidate["parent_framework_cluster"],
                "nearest_full_reference_candidate_id": reference_rows[full_index][
                    "candidate_id"
                ],
                "nearest_full_reference_parent_cluster": reference_rows[full_index][
                    "parent_framework_cluster"
                ],
                "nearest_full_sequence_kmer_cosine_distance": round(full_distance, 9),
                "nearest_cdr3_reference_candidate_id": reference_rows[cdr3_index][
                    "candidate_id"
                ],
                "nearest_cdr3_reference_parent_cluster": reference_rows[cdr3_index][
                    "parent_framework_cluster"
                ],
                "nearest_cdr3_normalized_levenshtein_distance": round(cdr3_distance, 9),
                "full_sequence_support_threshold": round(full_threshold, 9),
                "cdr3_support_threshold": round(cdr3_threshold, 9),
                "full_sequence_channel_supported": str(full_pass).lower(),
                "cdr3_channel_supported": str(cdr3_pass).lower(),
                "v4d_in_sequence_support": str(in_support).lower(),
                "v4d_support_domain": support_domain,
            }
        )
    return output


def build_configuration(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "reference_split": REFERENCE_SPLIT,
        "sequence_channel": {
            "representation": "sha256_hashed_amino_acid_3mer_counts_l2_normalized",
            "kmer_size": KMER_SIZE,
            "hash": "sha256_first_8_bytes_big_endian_mod_width",
            "width": KMER_WIDTH,
            "distance": "one_minus_cosine_similarity",
        },
        "cdr3_channel": {
            "region": "IMGT_CDR3",
            "distance": "levenshtein_distance_divided_by_max_length",
        },
        "calibration": {
            "policy": "leave_one_parent_framework_cluster_out_nearest_distance",
            "support_quantile": args.support_quantile,
            "quantile_method": QUANTILE_METHOD,
        },
        "domain_policy": {
            "IN_DOMAIN": "both_sequence_and_cdr3_channels_pass",
            "NEAR_DOMAIN": "exactly_one_channel_passes",
            "OOD": "neither_channel_passes",
        },
        "null_control": {
            "seed": args.null_seed,
            "replicates": args.null_replicates,
            "policy": "composition_preserving_shuffle_with_source_parent_cluster_excluded",
        },
        "expected_counts": {
            "split_manifest": args.expected_split_count,
            "open_train_reference": args.expected_reference_count,
            "candidate_pool": args.expected_candidate_count,
        },
        "gates": {
            "coverage_fraction_minimum": args.minimum_coverage,
            "in_support_count_minimum": args.minimum_in_support_count,
            "lopo_joint_fraction_minimum": args.minimum_lopo_joint,
            "shuffle_null_joint_fraction_maximum": args.maximum_null_joint,
        },
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=root / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
    )
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=root
        / "prepared/pvrig_teacher_formal_v1_candidates/scored_candidates_v1.csv",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "prepared/pvrig_v4_d/candidate7087_sequence_support.csv",
    )
    parser.add_argument("--audit-out", type=Path)
    parser.add_argument("--expected-split-sha256", default=EXPECTED_SPLIT_SHA256)
    parser.add_argument("--expected-candidate-pool-sha256", default=EXPECTED_POOL_SHA256)
    parser.add_argument("--expected-split-count", type=int, default=290)
    parser.add_argument("--expected-reference-count", type=int, default=226)
    parser.add_argument("--expected-candidate-count", type=int, default=7087)
    parser.add_argument("--support-quantile", type=float, default=SUPPORT_QUANTILE)
    parser.add_argument("--null-seed", type=int, default=NULL_SEED)
    parser.add_argument("--null-replicates", type=int, default=NULL_REPLICATES)
    parser.add_argument("--minimum-coverage", type=float, default=0.60)
    parser.add_argument("--minimum-in-support-count", type=int, default=4253)
    parser.add_argument("--minimum-lopo-joint", type=float, default=0.85)
    parser.add_argument("--maximum-null-joint", type=float, default=0.05)
    args = parser.parse_args(argv)

    if not 0.0 < args.support_quantile <= 1.0:
        raise SupportError("support_quantile_out_of_range")
    if not 0.0 <= args.minimum_coverage <= 1.0:
        raise SupportError("minimum_coverage_out_of_range")

    split_sha256 = sha256_file(args.split_manifest)
    pool_sha256 = sha256_file(args.candidate_pool)
    if split_sha256 != args.expected_split_sha256:
        raise SupportError("split_manifest_sha256_mismatch")
    if pool_sha256 != args.expected_candidate_pool_sha256:
        raise SupportError("candidate_pool_sha256_mismatch")

    split_rows = read_table(args.split_manifest, "\t")
    pool_rows = read_table(args.candidate_pool, ",")
    reference_raw = [row for row in split_rows if row.get("model_split") == REFERENCE_SPLIT]
    if len(split_rows) != args.expected_split_count:
        raise SupportError(
            f"unexpected_split_count:{len(split_rows)}:{args.expected_split_count}"
        )
    if len(reference_raw) != args.expected_reference_count:
        raise SupportError(
            f"unexpected_reference_count:{len(reference_raw)}:{args.expected_reference_count}"
        )
    if len(pool_rows) != args.expected_candidate_count:
        raise SupportError(
            f"unexpected_candidate_count:{len(pool_rows)}:{args.expected_candidate_count}"
        )

    reference_rows = canonicalize_reference_rows(reference_raw)
    candidate_rows = canonicalize_candidate_rows(pool_rows)
    calibration = lopo_calibration(
        reference_rows, support_quantile=args.support_quantile
    )
    null_control = composition_preserving_shuffle_null(
        reference_rows,
        calibration["reference_vectors"],
        full_threshold=calibration["full_sequence_threshold"],
        cdr3_threshold=calibration["cdr3_threshold"],
        replicates=args.null_replicates,
        seed=args.null_seed,
    )
    output_rows = score_candidates(
        reference_rows,
        candidate_rows,
        reference_vectors=calibration["reference_vectors"],
        full_threshold=calibration["full_sequence_threshold"],
        cdr3_threshold=calibration["cdr3_threshold"],
    )
    write_csv(args.out, output_rows)

    domain_counts = {
        domain: sum(row["v4d_support_domain"] == domain for row in output_rows)
        for domain in ("IN_DOMAIN", "NEAR_DOMAIN", "OOD")
    }
    in_support_count = domain_counts["IN_DOMAIN"]
    coverage = in_support_count / len(output_rows)
    gates = {
        "coverage_fraction": {
            "observed": coverage,
            "minimum": args.minimum_coverage,
            "passed": coverage >= args.minimum_coverage,
        },
        "in_support_count": {
            "observed": in_support_count,
            "minimum": args.minimum_in_support_count,
            "passed": in_support_count >= args.minimum_in_support_count,
        },
        "lopo_joint_fraction": {
            "observed": calibration["joint_pass_fraction"],
            "minimum": args.minimum_lopo_joint,
            "passed": calibration["joint_pass_fraction"] >= args.minimum_lopo_joint,
        },
        "shuffle_null_joint_fraction": {
            "observed": null_control["joint_pass_fraction"],
            "maximum": args.maximum_null_joint,
            "passed": null_control["joint_pass_fraction"] <= args.maximum_null_joint,
        },
    }
    all_gates_passed = all(gate["passed"] for gate in gates.values())
    configuration = build_configuration(args)
    audit: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_LABEL_FREE_SEQUENCE_SUPPORT_GATES"
            if all_gates_passed
            else "FAIL_LABEL_FREE_SEQUENCE_SUPPORT_GATES"
        ),
        "all_gates_passed": all_gates_passed,
        "inputs": {
            "split_manifest": {
                "path": str(args.split_manifest),
                "sha256": split_sha256,
                "row_count": len(split_rows),
            },
            "candidate_pool": {
                "path": str(args.candidate_pool),
                "sha256": pool_sha256,
                "row_count": len(pool_rows),
            },
        },
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "configuration": configuration,
        "configuration_sha256": sha256_json(configuration),
        "reference": {
            "split": REFERENCE_SPLIT,
            "row_count": len(reference_rows),
            "parent_framework_cluster_count": len(
                {row["parent_framework_cluster"] for row in reference_rows}
            ),
            "parent_framework_clusters": sorted(
                {row["parent_framework_cluster"] for row in reference_rows}
            ),
        },
        "thresholds": {
            "full_sequence_kmer_cosine_distance": calibration[
                "full_sequence_threshold"
            ],
            "imgt_cdr3_normalized_levenshtein_distance": calibration[
                "cdr3_threshold"
            ],
            "quantile": args.support_quantile,
            "method": QUANTILE_METHOD,
        },
        "controls": {
            "lopo_joint": {
                "policy": "leave_one_parent_framework_cluster_out",
                "row_count": len(reference_rows),
                "joint_pass_count": calibration["joint_pass_count"],
                "joint_pass_fraction": calibration["joint_pass_fraction"],
            },
            "composition_preserving_shuffle_null": null_control,
        },
        "coverage": {
            "candidate_count": len(output_rows),
            "in_support_count": in_support_count,
            "in_support_fraction": coverage,
            "domain_counts": domain_counts,
        },
        "gates": gates,
        "outputs": {
            "sequence_support_csv": {
                "path": str(args.out),
                "sha256": sha256_file(args.out),
                "row_count": len(output_rows),
            }
        },
        "claim_boundary": (
            "Label-free support/OOD diagnostic for a sequence-to-independent-dual-docking "
            "surrogate. It is not model correctness, binding, affinity, competition, Docking "
            "Gold, or experimental blocking evidence."
        ),
    }
    audit["audit_payload_sha256"] = sha256_json(audit)
    audit_path = args.audit_out or args.out.with_suffix(args.out.suffix + ".audit.json")
    write_json(audit_path, audit)
    print(
        json.dumps(
            {
                "status": audit["status"],
                "coverage": coverage,
                "in_support_count": in_support_count,
                "lopo_joint_fraction": calibration["joint_pass_fraction"],
                "shuffle_null_joint_fraction": null_control["joint_pass_fraction"],
                "out": str(args.out),
                "audit": str(audit_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
