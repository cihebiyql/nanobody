#!/usr/bin/env python3
"""Materialize trainer-ready adaptive dual-source tables and frozen input contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import build_adaptive_dual_contact_targets_v3 as marginal
import build_adaptive_dual_pair_contact_targets_v3 as pair


CONTRACT_SCHEMA = "pvrig_v2_4_adaptive_multiseed_dual_source_input_contract_v1"
CONTRACT_STATUS = "FROZEN_V2_4_ADAPTIVE_MULTI_SEED_DUAL_SOURCE_INPUTS"
TEACHER_GENERATION = "V4D_MULTI_SEED_PLUS_V4H_ADAPTIVE_MULTI_SEED_V2"
EXPECTED_COUNTS = {
    "training_candidates": 1507,
    "v4d_candidates": 226,
    "v4h_valid_candidates": 1281,
    "v4h_technical_incomplete_excluded": 39,
    "v4h_source_candidates": 1320,
    "v4h_selected_paired_jobs": 3536,
}
EXPECTED_PARENT_COUNTS = {"V4D_OPEN_MULTI_SEED": 20, "V4H_ADAPTIVE_SEED_RANKING": 11}
TRAINING_TSV_SHA256 = "47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1"
CONTRACT_NAME = "ADAPTIVE_DUAL_SOURCE_INPUT_CONTRACT_V1.json"
RECEIPT_NAME = "MATERIALIZATION_RECEIPT.json"


class MaterializeError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise MaterializeError(f"{label}_missing:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"{label}_not_regular_or_symlink:{path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    regular(path, label)
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), f"{label}_not_object")
    return payload


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def artifact(path: Path) -> dict[str, Any]:
    regular(path, "artifact")
    return {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def materialize(
    *,
    training_tsv: Path,
    v4d_pair_tsv: Path,
    v4d_marginal_tsv: Path,
    v4d_receipt: Path,
    v4h_pair_tsv: Path,
    v4h_residue_tsv: Path,
    v4h_candidate_tsv: Path,
    v4h_receipt: Path,
    target_cache_npz: Path,
    target_manifest_tsv: Path,
    target_receipt: Path,
    output_root: Path,
) -> dict[str, Any]:
    require(not output_root.exists() and not output_root.is_symlink(), "output_root_must_not_exist")
    regular(training_tsv, "training_tsv")
    require(sha256_file(training_tsv) == TRAINING_TSV_SHA256, "training_tsv_frozen_sha")
    source = load_json(v4h_receipt, "v4h_receipt")
    require(source.get("schema_version") == "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2_receipt", "v4h_receipt_schema")
    require(source.get("status") == "PASS_V4H_ADAPTIVE_MULTI_SEED_CONTACT_EXTRACTION", "v4h_receipt_status")
    require(source.get("candidate_rows") == EXPECTED_COUNTS["v4h_source_candidates"], "v4h_source_candidate_count")
    require(source.get("valid_candidate_rows") == EXPECTED_COUNTS["v4h_valid_candidates"], "v4h_valid_candidate_count")
    require(source.get("technical_incomplete_candidate_rows") == EXPECTED_COUNTS["v4h_technical_incomplete_excluded"], "v4h_na_count")
    require(source.get("selected_paired_job_rows") == EXPECTED_COUNTS["v4h_selected_paired_jobs"], "v4h_selected_jobs")
    require(source.get("source_mutation_operations") == 0, "v4h_source_mutation")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent))
    try:
        marginal_dir = staging / "marginal"
        pair_dir = staging / "pair"
        marginal_receipt = marginal.build_targets(
            training_tsv, v4d_marginal_tsv, v4d_receipt,
            v4h_residue_tsv, v4h_candidate_tsv, v4h_receipt, marginal_dir,
            expected_source_counts={
                marginal.V4D: EXPECTED_COUNTS["v4d_candidates"],
                marginal.V4H: EXPECTED_COUNTS["v4h_valid_candidates"],
            },
        )
        pair_receipt = pair.build_targets(
            training_tsv=training_tsv, v4d_pair_tsv_gz=v4d_pair_tsv, v4d_receipt=v4d_receipt,
            v4h_pair_tsv_gz=v4h_pair_tsv, v4h_candidate_tsv_gz=v4h_candidate_tsv,
            v4h_receipt=v4h_receipt, target_cache_npz=target_cache_npz,
            target_manifest_tsv=target_manifest_tsv, target_receipt=target_receipt,
            output_dir=pair_dir,
            expected_source_counts={
                pair.V4D: EXPECTED_COUNTS["v4d_candidates"],
                pair.V4H: EXPECTED_COUNTS["v4h_valid_candidates"],
            },
            expected_parent_counts=EXPECTED_PARENT_COUNTS,
        )
        marginal_table = marginal_dir / marginal.OUTPUT_NAME
        marginal_receipt_path = marginal_dir / marginal.RECEIPT_NAME
        pair_table = pair_dir / pair.OUTPUT_NAME
        pair_receipt_path = pair_dir / pair.RECEIPT_NAME
        artifacts = {
            "v4h_adaptive_source_receipt": artifact(v4h_receipt),
            "v4d_source_receipt": artifact(v4d_receipt),
            "adaptive_marginal_tsv_gz": artifact(marginal_table),
            "adaptive_marginal_receipt": artifact(marginal_receipt_path),
            "adaptive_pair_tsv_gz": artifact(pair_table),
            "adaptive_pair_receipt": artifact(pair_receipt_path),
        }
        source_provenance = {
            field: source[field]
            for field in ("contract_sha256", "reconciliation_receipt_sha256", "implementation_sha256")
        }
        contract = {
            "schema_version": CONTRACT_SCHEMA,
            "status": CONTRACT_STATUS,
            "teacher_generation": TEACHER_GENERATION,
            "legacy_stage1_inputs_forbidden": True,
            "training_tsv_sha256": sha256_file(training_tsv),
            "expected_counts": EXPECTED_COUNTS,
            "v4h_source_provenance": source_provenance,
            "artifacts": artifacts,
            "claim_boundary": marginal.CLAIM_BOUNDARY,
        }
        atomic_json(staging / CONTRACT_NAME, contract)
        receipt = {
            "schema_version": "pvrig_v2_4_adaptive_dual_source_materialization_receipt_v1",
            "status": "PASS_V2_4_ADAPTIVE_DUAL_SOURCE_TABLES_AND_CONTRACT_MATERIALIZED",
            "contract_sha256": sha256_file(staging / CONTRACT_NAME),
            "marginal_receipt_status": marginal_receipt["status"],
            "pair_receipt_status": pair_receipt["status"],
            "artifacts": artifacts,
            "technical_na_rows_imputed": 0,
            "legacy_stage1_rows": 0,
            "claim_boundary": marginal.CLAIM_BOUNDARY,
        }
        atomic_json(staging / RECEIPT_NAME, receipt)
        os.replace(staging, output_root)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    for name in (
        "training-tsv", "v4d-pair-tsv", "v4d-marginal-tsv", "v4d-receipt",
        "v4h-pair-tsv", "v4h-residue-tsv", "v4h-candidate-tsv", "v4h-receipt",
        "target-cache-npz", "target-manifest-tsv", "target-receipt", "output-root",
    ):
        value.add_argument(f"--{name}", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    receipt = materialize(**{key: value for key, value in vars(args).items()})
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
