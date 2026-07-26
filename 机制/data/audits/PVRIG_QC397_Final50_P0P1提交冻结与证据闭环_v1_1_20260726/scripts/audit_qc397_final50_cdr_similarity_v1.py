#!/usr/bin/env python3
"""Build submission-grade Final50 CDR identity evidence.

The identity calculation intentionally reuses the official validator semantics:
pairwise MUSCLE alignment followed by matches / non-double-gap columns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ab_data_validator.muscle import align_pair
from ab_data_validator.similarity import calculate_identity


CDRS = ("cdr1", "cdr2", "cdr3")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-tsv", required=True, type=Path)
    parser.add_argument("--vhh-eval-tsv", required=True, type=Path)
    parser.add_argument("--official-positive-csv", required=True, type=Path)
    parser.add_argument("--local-positive-csv", required=True, type=Path)
    parser.add_argument("--muscle-bin", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=16)
    return parser.parse_args()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidates(
    freeze_path: Path, vhh_eval_path: Path
) -> list[dict[str, str]]:
    frozen = read_tsv(freeze_path)
    vhh = {row["id"]: row for row in read_tsv(vhh_eval_path)}
    assert len(frozen) == 50, f"expected 50 frozen candidates, got {len(frozen)}"
    assert len(vhh) == 50, f"expected 50 VHH-QC rows, got {len(vhh)}"
    candidates: list[dict[str, str]] = []
    for row in frozen:
        sid = row["submission_id"]
        assert sid in vhh, f"missing VHH-QC row for {sid}"
        qc = vhh[sid]
        item = dict(row)
        for cdr in CDRS:
            numbered = qc[f"imgt_{cdr}"].strip()
            assert numbered, f"empty IMGT {cdr} for {sid}"
            assert numbered == row[cdr], (
                f"freeze/QC {cdr} mismatch for {sid}: {row[cdr]} != {numbered}"
            )
            item[cdr] = numbered
        candidates.append(item)
    ranks = [int(row["competition_rank_1_50"]) for row in candidates]
    assert ranks == list(range(1, 51)), "freeze rows must be in exact competition-rank order"
    return candidates


def load_references(
    official_path: Path, local_path: Path
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    with official_path.open(newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=1):
            references.append(
                {
                    "reference_uid": f"official_{index:03d}",
                    "reference_set": row.get("reference_set", "official_ab_data_validator"),
                    "reference_name": row["positive_name"],
                    "reference_type": row.get("positive_type", ""),
                    "reference_source": row.get("positive_source", ""),
                    "cdr1": row["positive_cdr1"].strip(),
                    "cdr2": row["positive_cdr2"].strip(),
                    "cdr3": row["positive_cdr3"].strip(),
                }
            )
    with local_path.open(newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=1):
            references.append(
                {
                    "reference_uid": f"local_pvrig_{index:03d}",
                    "reference_set": "local_pvrig_positive_vhh",
                    "reference_name": row["molecule_name"],
                    "reference_type": row.get("sequence_type", ""),
                    "reference_source": f"WO2021180205A1_SEQ_ID_{row.get('seq_id_no', '')}",
                    "cdr1": row["raw_anarci_imgt_cdr1_exact"].strip(),
                    "cdr2": row["raw_anarci_imgt_cdr2_exact"].strip(),
                    "cdr3": row["raw_anarci_imgt_cdr3_exact"].strip(),
                }
            )
    assert len(references) == 78, f"expected 78 positive rows, got {len(references)}"
    for reference in references:
        for cdr in CDRS:
            assert reference[cdr], f"empty {cdr} in {reference['reference_uid']}"
    return references


def identity_cache(
    pairs: set[tuple[str, str]], muscle_bin: str, workers: int
) -> dict[tuple[str, str], tuple[float, str, str]]:
    ordered = sorted(pairs)

    def one(pair: tuple[str, str]) -> tuple[tuple[str, str], tuple[float, str, str]]:
        aligned_a, aligned_b = align_pair(pair[0], pair[1], muscle_bin=muscle_bin)
        return pair, (calculate_identity(aligned_a, aligned_b), aligned_a, aligned_b)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        forward = dict(pool.map(one, ordered))
    cache = dict(forward)
    for (left, right), (identity, aligned_left, aligned_right) in forward.items():
        cache.setdefault(
            (right, left), (identity, aligned_right, aligned_left)
        )
    return cache


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates = load_candidates(args.freeze_tsv, args.vhh_eval_tsv)
    references = load_references(args.official_positive_csv, args.local_positive_csv)

    pairs: set[tuple[str, str]] = set()
    for candidate in candidates:
        for reference in references:
            for cdr in CDRS:
                pairs.add((candidate[cdr], reference[cdr]))
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index:]:
            for cdr in CDRS:
                pairs.add((left[cdr], right[cdr]))
    cache = identity_cache(pairs, args.muscle_bin, args.workers)

    positive_rows: list[dict[str, object]] = []
    positive_summary: list[dict[str, object]] = []
    for candidate in candidates:
        candidate_rows: list[dict[str, object]] = []
        for reference in references:
            row: dict[str, object] = {
                "submission_id": candidate["submission_id"],
                "competition_rank_1_50": candidate["competition_rank_1_50"],
                "mechanism_rank_immutable": candidate["mechanism_rank_immutable"],
                "candidate_id": candidate["candidate_id"],
                "reference_uid": reference["reference_uid"],
                "reference_set": reference["reference_set"],
                "reference_name": reference["reference_name"],
                "reference_type": reference["reference_type"],
                "reference_source": reference["reference_source"],
            }
            for cdr in CDRS:
                identity, aligned_candidate, aligned_reference = cache[
                    (candidate[cdr], reference[cdr])
                ]
                row[f"candidate_{cdr}"] = candidate[cdr]
                row[f"reference_{cdr}"] = reference[cdr]
                row[f"{cdr}_identity"] = f"{identity:.6f}"
                row[f"{cdr}_aligned_candidate"] = aligned_candidate
                row[f"{cdr}_aligned_reference"] = aligned_reference
            row["max_corresponding_cdr_identity"] = f"{max(float(row[f'{c}_identity']) for c in CDRS):.6f}"
            row["all_three_below_0p80"] = str(
                all(float(row[f"{c}_identity"]) < 0.80 for c in CDRS)
            ).lower()
            candidate_rows.append(row)
        positive_rows.extend(candidate_rows)
        summary: dict[str, object] = {
            "submission_id": candidate["submission_id"],
            "competition_rank_1_50": candidate["competition_rank_1_50"],
            "mechanism_rank_immutable": candidate["mechanism_rank_immutable"],
            "candidate_id": candidate["candidate_id"],
        }
        for cdr in CDRS:
            best = max(candidate_rows, key=lambda row: float(row[f"{cdr}_identity"]))
            summary[f"max_positive_{cdr}_identity"] = best[f"{cdr}_identity"]
            summary[f"max_positive_{cdr}_reference_uid"] = best["reference_uid"]
            summary[f"max_positive_{cdr}_reference_name"] = best["reference_name"]
            summary[f"max_positive_{cdr}_reference_set"] = best["reference_set"]
        summary["max_positive_any_cdr_identity"] = f"{max(float(summary[f'max_positive_{c}_identity']) for c in CDRS):.6f}"
        summary["all_positive_corresponding_cdrs_below_0p80"] = str(
            float(summary["max_positive_any_cdr_identity"]) < 0.80
        ).lower()
        positive_summary.append(summary)

    positive_fields = [
        "submission_id",
        "competition_rank_1_50",
        "mechanism_rank_immutable",
        "candidate_id",
        "reference_uid",
        "reference_set",
        "reference_name",
        "reference_type",
        "reference_source",
    ]
    for cdr in CDRS:
        positive_fields.extend(
            [
                f"candidate_{cdr}",
                f"reference_{cdr}",
                f"{cdr}_identity",
                f"{cdr}_aligned_candidate",
                f"{cdr}_aligned_reference",
            ]
        )
    positive_fields.extend(["max_corresponding_cdr_identity", "all_three_below_0p80"])
    positive_path = args.output_dir / "Final50_vs_all_positive_corresponding_CDR_identity.tsv"
    write_tsv(positive_path, positive_rows, positive_fields)

    summary_fields = [
        "submission_id",
        "competition_rank_1_50",
        "mechanism_rank_immutable",
        "candidate_id",
    ]
    for cdr in CDRS:
        summary_fields.extend(
            [
                f"max_positive_{cdr}_identity",
                f"max_positive_{cdr}_reference_uid",
                f"max_positive_{cdr}_reference_name",
                f"max_positive_{cdr}_reference_set",
            ]
        )
    summary_fields.extend(
        ["max_positive_any_cdr_identity", "all_positive_corresponding_cdrs_below_0p80"]
    )
    summary_path = args.output_dir / "Final50_vs_all_positive_CDR_identity_summary.tsv"
    write_tsv(summary_path, positive_summary, summary_fields)

    pair_rows: list[dict[str, object]] = []
    matrix_paths: list[Path] = []
    for cdr in CDRS:
        matrix_path = args.output_dir / f"Final50_team_{cdr.upper()}_identity_matrix.tsv"
        matrix_paths.append(matrix_path)
        fields = ["submission_id"] + [row["submission_id"] for row in candidates]
        matrix_rows: list[dict[str, object]] = []
        for left in candidates:
            matrix_row: dict[str, object] = {"submission_id": left["submission_id"]}
            for right in candidates:
                identity = cache[(left[cdr], right[cdr])][0]
                matrix_row[right["submission_id"]] = f"{identity:.6f}"
            matrix_rows.append(matrix_row)
        write_tsv(matrix_path, matrix_rows, fields)

    nearest: dict[str, dict[str, object]] = {
        candidate["submission_id"]: {
            "submission_id": candidate["submission_id"],
            "competition_rank_1_50": candidate["competition_rank_1_50"],
            "mechanism_rank_immutable": candidate["mechanism_rank_immutable"],
            "candidate_id": candidate["candidate_id"],
            **{f"max_team_{cdr}_identity": -1.0 for cdr in CDRS},
            **{f"max_team_{cdr}_peer_submission_id": "" for cdr in CDRS},
            "max_team_any_cdr_identity": -1.0,
            "max_team_any_cdr_peer_submission_id": "",
            "max_team_any_cdr_name": "",
        }
        for candidate in candidates
    }
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            row: dict[str, object] = {
                "left_submission_id": left["submission_id"],
                "left_competition_rank": left["competition_rank_1_50"],
                "left_candidate_id": left["candidate_id"],
                "right_submission_id": right["submission_id"],
                "right_competition_rank": right["competition_rank_1_50"],
                "right_candidate_id": right["candidate_id"],
            }
            identities: dict[str, float] = {}
            for cdr in CDRS:
                identity = cache[(left[cdr], right[cdr])][0]
                identities[cdr] = identity
                row[f"{cdr}_identity"] = f"{identity:.6f}"
                for subject, peer in ((left, right), (right, left)):
                    current = nearest[subject["submission_id"]]
                    if identity > float(current[f"max_team_{cdr}_identity"]):
                        current[f"max_team_{cdr}_identity"] = identity
                        current[f"max_team_{cdr}_peer_submission_id"] = peer["submission_id"]
                    if identity > float(current["max_team_any_cdr_identity"]):
                        current["max_team_any_cdr_identity"] = identity
                        current["max_team_any_cdr_peer_submission_id"] = peer["submission_id"]
                        current["max_team_any_cdr_name"] = cdr
            row["max_any_cdr_identity"] = f"{max(identities.values()):.6f}"
            row["all_three_below_0p80"] = str(
                all(value < 0.80 for value in identities.values())
            ).lower()
            pair_rows.append(row)
    pair_path = args.output_dir / "Final50_team_CDR_identity_pairs.tsv"
    write_tsv(
        pair_path,
        pair_rows,
        [
            "left_submission_id",
            "left_competition_rank",
            "left_candidate_id",
            "right_submission_id",
            "right_competition_rank",
            "right_candidate_id",
            "cdr1_identity",
            "cdr2_identity",
            "cdr3_identity",
            "max_any_cdr_identity",
            "all_three_below_0p80",
        ],
    )

    nearest_rows: list[dict[str, object]] = []
    for candidate in candidates:
        row = nearest[candidate["submission_id"]]
        for key, value in list(row.items()):
            if isinstance(value, float):
                row[key] = f"{value:.6f}"
        nearest_rows.append(row)
    nearest_path = args.output_dir / "Final50_team_CDR_nearest_neighbor_summary.tsv"
    write_tsv(
        nearest_path,
        nearest_rows,
        [
            "submission_id",
            "competition_rank_1_50",
            "mechanism_rank_immutable",
            "candidate_id",
            "max_team_cdr1_identity",
            "max_team_cdr1_peer_submission_id",
            "max_team_cdr2_identity",
            "max_team_cdr2_peer_submission_id",
            "max_team_cdr3_identity",
            "max_team_cdr3_peer_submission_id",
            "max_team_any_cdr_identity",
            "max_team_any_cdr_peer_submission_id",
            "max_team_any_cdr_name",
        ],
    )

    assert len(positive_rows) == 3900
    assert len(pair_rows) == 1225
    for matrix_path in matrix_paths:
        matrix = read_tsv(matrix_path)
        assert len(matrix) == 50
        for index, row in enumerate(matrix):
            sid = candidates[index]["submission_id"]
            assert float(row[sid]) == 1.0
            for other in candidates:
                other_sid = other["submission_id"]
                reverse = matrix[int(other["competition_rank_1_50"]) - 1][sid]
                assert row[other_sid] == reverse

    outputs = [
        positive_path,
        summary_path,
        pair_path,
        nearest_path,
        *matrix_paths,
    ]
    receipt = {
        "schema_version": "qc397_final50_cdr_similarity_v1",
        "state": "COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity_method": (
            "official ab-data-validator semantics: MUSCLE pair alignment; "
            "matches divided by non-double-gap alignment columns"
        ),
        "candidate_count": len(candidates),
        "positive_reference_rows": len(references),
        "candidate_positive_rows": len(positive_rows),
        "team_pair_rows": len(pair_rows),
        "matrix_shape": [50, 50],
        "assertions": {
            "freeze_vs_uniform_imgt_cdr_exact": True,
            "matrix_symmetric": True,
            "matrix_diagonal_one": True,
            "competition_ranks_exact_1_to_50": True,
        },
        "inputs": {
            str(path): sha256(path)
            for path in (
                args.freeze_tsv,
                args.vhh_eval_tsv,
                args.official_positive_csv,
                args.local_positive_csv,
            )
        },
        "outputs": {path.name: sha256(path) for path in outputs},
    }
    receipt_path = args.output_dir / "CDR_SIMILARITY_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
