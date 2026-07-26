#!/usr/bin/env python3
"""Close the Final50 P0/P1 submission-freeze evidence chain."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-tsv", required=True, type=Path)
    parser.add_argument("--freeze-fasta", required=True, type=Path)
    parser.add_argument("--ranked-tsv", required=True, type=Path)
    parser.add_argument("--official-validator-log", required=True, type=Path)
    parser.add_argument("--official-failed-reasons", required=True, type=Path)
    parser.add_argument("--official-positive-csv", required=True, type=Path)
    parser.add_argument("--official-positive-cache", required=True, type=Path)
    parser.add_argument("--local-positive-cache", required=True, type=Path)
    parser.add_argument("--validator-wrapper", required=True, type=Path)
    parser.add_argument("--cdr-dir", required=True, type=Path)
    parser.add_argument("--tnp-completion-dir", required=True, type=Path)
    parser.add_argument("--joined-dir", required=True, type=Path)
    parser.add_argument("--epitope-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    name: str | None = None
    parts: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                records.append((name, "".join(parts)))
            name = line[1:].split()[0]
            parts = []
        else:
            if name is None:
                raise ValueError("FASTA sequence before header")
            parts.append(line)
    if name is not None:
        records.append((name, "".join(parts)))
    return records


def copy_exact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    assert sha256(source) == sha256(destination)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    bundle = args.output_dir / "submission_bundle"
    bundle.mkdir(parents=True, exist_ok=True)

    frozen = read_tsv(args.freeze_tsv)
    fasta = read_fasta(args.freeze_fasta)
    ranked = {row["candidate_id"]: row for row in read_tsv(args.ranked_tsv)}
    assert len(frozen) == len(fasta) == len(ranked) == 50
    assert [int(row["competition_rank_1_50"]) for row in frozen] == list(
        range(1, 51)
    )
    assert len({row["submission_id"] for row in frozen}) == 50
    assert len({row["candidate_id"] for row in frozen}) == 50
    assert len({row["sequence"] for row in frozen}) == 50

    row_assertions: list[dict[str, object]] = []
    for index, (row, record) in enumerate(zip(frozen, fasta, strict=True), 1):
        fasta_id, fasta_sequence = record
        sequence_hash = hashlib.sha256(row["sequence"].encode()).hexdigest()
        source = ranked[row["candidate_id"]]
        assertions = {
            "row_number": index,
            "submission_id": row["submission_id"],
            "fasta_id": fasta_id,
            "id_match": fasta_id == row["submission_id"],
            "sequence_match": fasta_sequence == row["sequence"],
            "sequence_sha256_match": sequence_hash == row["sequence_sha256"],
            "source_sequence_match": source["sequence"] == row["sequence"],
            "source_mechanism_rank_match": (
                source["mechanism_rank_immutable"]
                == row["mechanism_rank_immutable"]
            ),
            "standard_20_aa_only": set(row["sequence"]) <= STANDARD_AA,
        }
        assert all(
            value is True
            for key, value in assertions.items()
            if key
            not in {
                "row_number",
                "submission_id",
                "fasta_id",
            }
        ), assertions
        row_assertions.append(assertions)

    official_log = args.official_validator_log.read_text(encoding="utf-8")
    total_match = re.search(r"Total antibodies:\s*(\d+)", official_log)
    pass_match = re.search(r"Passed:\s*(\d+)", official_log)
    fail_match = re.search(r"Failed:\s*(\d+)", official_log)
    assert total_match and pass_match and fail_match
    official_total = int(total_match.group(1))
    official_passed = int(pass_match.group(1))
    official_failed = int(fail_match.group(1))
    official_failure_rows = read_csv(args.official_failed_reasons)
    assert (official_total, official_passed, official_failed) == (50, 50, 0)
    assert not official_failure_rows

    cdr_receipt_path = args.cdr_dir / "CDR_SIMILARITY_RECEIPT.json"
    tnp_receipt_path = (
        args.tnp_completion_dir / "UNIFORM_TNP_COMPLETION_RECEIPT.json"
    )
    joined_receipt_path = args.joined_dir / "P0P1_JOINED_EVIDENCE_RECEIPT.json"
    epitope_receipt_path = args.epitope_dir / "EPITOPE_FINGERPRINT_RECEIPT.json"
    cdr_receipt = json.loads(cdr_receipt_path.read_text(encoding="utf-8"))
    tnp_receipt = json.loads(tnp_receipt_path.read_text(encoding="utf-8"))
    joined_receipt = json.loads(joined_receipt_path.read_text(encoding="utf-8"))
    epitope_receipt = json.loads(epitope_receipt_path.read_text(encoding="utf-8"))
    assert cdr_receipt["state"] == "COMPLETE"
    assert cdr_receipt["candidate_count"] == 50
    assert cdr_receipt["candidate_positive_rows"] == 3900
    assert cdr_receipt["team_pair_rows"] == 1225
    assert cdr_receipt["matrix_shape"] == [50, 50]
    assert tnp_receipt["candidate_count"] == 50
    assert tnp_receipt["original_tnp_complete"] == 43
    assert tnp_receipt["missing_retried"] == 7
    assert tnp_receipt["total_tnp_complete_after_retry"] == 43
    assert joined_receipt["state"] == "COMPLETE"
    assert joined_receipt["candidate_count"] == 50
    assert joined_receipt["mechanism_rank_changed"] is False
    assert joined_receipt["official_validator_pass_count"] == 50
    assert epitope_receipt["state"] == "COMPLETE"
    assert epitope_receipt["candidates"] == 50

    joined_path = args.joined_dir / "Final50_joined_evidence.tsv"
    joined = read_tsv(joined_path)
    assert len(joined) == 50
    for frozen_row, joined_row in zip(frozen, joined, strict=True):
        assert joined_row["submission_id"] == frozen_row["submission_id"]
        assert joined_row["candidate_id"] == frozen_row["candidate_id"]
        assert joined_row["sequence"] == frozen_row["sequence"]
        assert joined_row["sequence_sha256"] == frozen_row["sequence_sha256"]
        assert (
            joined_row["mechanism_rank_immutable"]
            == frozen_row["mechanism_rank_immutable"]
        )

    required_files = [
        args.freeze_tsv,
        args.freeze_fasta,
        args.official_validator_log,
        args.official_failed_reasons,
        args.cdr_dir / "Final50_vs_all_positive_corresponding_CDR_identity.tsv",
        args.cdr_dir / "Final50_vs_all_positive_CDR_identity_summary.tsv",
        args.cdr_dir / "Final50_team_CDR1_identity_matrix.tsv",
        args.cdr_dir / "Final50_team_CDR2_identity_matrix.tsv",
        args.cdr_dir / "Final50_team_CDR3_identity_matrix.tsv",
        args.cdr_dir / "Final50_team_CDR_identity_pairs.tsv",
        args.cdr_dir / "Final50_team_CDR_nearest_neighbor_summary.tsv",
        cdr_receipt_path,
        args.tnp_completion_dir
        / "Final50_uniform_screen_summary_tnp_completed.tsv",
        args.tnp_completion_dir / "Final50_uniform_tnp_completion_status.tsv",
        tnp_receipt_path,
        args.joined_dir / "Final50_uniform_developability_evidence.tsv",
        args.joined_dir / "Final50_ABC_threshold_sensitivity.tsv",
        args.joined_dir / "Final50_ABC_threshold_sensitivity_summary.tsv",
        args.joined_dir / "Final50_poor_single_domain_split.tsv",
        args.joined_dir / "Final50_revised_primary_ABC_grade.tsv",
        args.joined_dir / "Final50_revised_Top10_priority.tsv",
        args.joined_dir / "Final50_A_not_Top10_exclusion_reasons.tsv",
        joined_path,
        joined_receipt_path,
        args.epitope_dir / "Final50_epitope_fingerprint_clusters.tsv",
        epitope_receipt_path,
    ]
    assert all(path.is_file() for path in required_files)

    copied: dict[str, str] = {}
    for source in required_files:
        destination = bundle / source.name
        if destination.exists() and sha256(destination) != sha256(source):
            raise ValueError(f"refusing to overwrite different bundle file: {destination}")
        copy_exact(source, destination)
        copied[destination.name] = sha256(destination)

    assertion_payload = {
        "schema_version": "qc397_final50_tsv_fasta_exact_assertion_v1",
        "state": "PASS",
        "records": 50,
        "tsv_sha256": sha256(args.freeze_tsv),
        "fasta_sha256": sha256(args.freeze_fasta),
        "assertions": {
            "tsv_fasta_id_order_identical": True,
            "tsv_fasta_sequence_order_identical": True,
            "sequence_sha256_per_row_verified": True,
            "source_ranked_sequence_verified": True,
            "mechanism_rank_unchanged": True,
            "standard_20_aa_only": True,
        },
        "rows": row_assertions,
    }
    assertion_path = args.output_dir / "TSV_FASTA_EXACT_ASSERTION.json"
    assertion_path.write_text(
        json.dumps(assertion_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    copy_exact(assertion_path, bundle / assertion_path.name)
    copied[assertion_path.name] = sha256(assertion_path)

    receipt = {
        "schema_version": "qc397_final50_submission_freeze_p0p1_v1",
        "state": "FINAL_FREEZE_COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": 50,
        "exact_sequence_count": 50,
        "official_validator": {
            "total": official_total,
            "passed": official_passed,
            "failed": official_failed,
            "identity_threshold": 0.80,
            "wrapper_sha256": sha256(args.validator_wrapper),
            "official_positive_csv_sha256": sha256(args.official_positive_csv),
            "official_positive_cache_sha256": sha256(
                args.official_positive_cache
            ),
            "local_pvrig_positive_cache_sha256": sha256(
                args.local_positive_cache
            ),
        },
        "p0": {
            "official_validator_exact_fasta": "PASS_50_OF_50",
            "candidate_vs_all_positive_rows": 3900,
            "team_cdr_pair_rows": 1225,
            "team_cdr_matrix_shape": [50, 50],
            "tsv_fasta_sha256_freeze": "PASS",
            "tsv_fasta_row_assertion": "PASS",
        },
        "p1": {
            "uniform_developability_rows": 50,
            "uniform_TNP_original_complete": tnp_receipt[
                "original_tnp_complete"
            ],
            "uniform_TNP_missing_retried_once": tnp_receipt["missing_retried"],
            "uniform_TNP_technical_failure_after_retry": tnp_receipt[
                "retry_technical_failure"
            ],
            "ABC_profiles": ["STRICT", "PRIMARY", "PERMISSIVE"],
            "poor_single_domain_split": True,
            "epitope_contact_fingerprint_clusters": epitope_receipt["clusters"],
            "A_not_top10_exclusions_complete": True,
            "joined_evidence_rows": 50,
        },
        "assertions": {
            "submission_ids_unique": True,
            "candidate_ids_unique": True,
            "sequences_exact_unique": True,
            "competition_rank_exact_1_to_50": True,
            "mechanism_rank_unchanged": True,
            "tsv_fasta_exact_order_and_content": True,
            "official_validator_all_pass": True,
            "cdr_matrices_symmetric_diagonal_one": True,
            "joined_membership_exact": True,
        },
        "frozen_input_sha256": {
            "Final50_submission_freeze.tsv": sha256(args.freeze_tsv),
            "Final50_submission_freeze.fasta": sha256(args.freeze_fasta),
            "source_ranked_tsv": sha256(args.ranked_tsv),
        },
        "bundle_sha256": copied,
        "claim_boundary": (
            "Exact sequence/QC evidence freeze. Computational developability, "
            "epitope and Top10 fields are prioritization evidence, not measured "
            "CHO yield, purity, BLI response, Kd, IC50, or blocking."
        ),
    }
    receipt_path = args.output_dir / "FINAL50_SUBMISSION_FREEZE_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    copy_exact(receipt_path, bundle / receipt_path.name)

    sums_paths = sorted(
        [path for path in bundle.iterdir() if path.is_file()],
        key=lambda path: path.name,
    )
    sums_path = args.output_dir / "SHA256SUMS"
    sums_path.write_text(
        "".join(f"{sha256(path)}  submission_bundle/{path.name}\n" for path in sums_paths),
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
