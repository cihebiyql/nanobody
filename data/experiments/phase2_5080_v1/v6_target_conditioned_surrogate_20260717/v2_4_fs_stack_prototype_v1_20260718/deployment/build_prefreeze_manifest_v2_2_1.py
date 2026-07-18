#!/usr/bin/env python3
"""Build the V2.4 V2.2.1 status-constant technical-supersession manifest.

V2.2 technically supersedes V2.1 after an exact observation/manifest claim-boundary mismatch. It preserves all numeric calibration inputs, gates, batches, and observed weights while using new immutable roots.  It never accepts the
historical V4-H Stage-1 contact tables.  Its formal
trainer inputs must be dual-source, trainer-ready adaptive marginal/pair
tables closed by a separately frozen input contract whose SHA256 is supplied
explicitly on the command line.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import pathlib
import random
import stat
from collections import Counter
from typing import Any, Mapping


BUNDLE = "/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v2_2_1_20260718"
RUNTIME = "/data1/qlyu/projects/pvrig_v6_residue_v2_4_four_lane_oof_v2_2_1_20260718"
CALIBRATION_RUNTIME = "/data1/qlyu/projects/pvrig_v6_residue_v2_4_calibration_v2_2_1_20260718"
V23_BUNDLE = "/data1/qlyu/projects/pvrig_v6_residue_v2_3_deployment_bundle_v1_20260718"
HF_SNAPSHOT = "/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c"
ESM_SHA = "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"
MANIFEST_SCHEMA = "pvrig_v6_residue_v2_4_node1_deployment_manifest_v2_2_1_status_constant_corrected"
MANIFEST_STATUS = "PREFREEZE_V2_2_1_ADAPTIVE_MULTI_SEED_CALIBRATION_PENDING_DO_NOT_START"
ADAPTIVE_CONTRACT_SCHEMA = "pvrig_v2_4_adaptive_multiseed_dual_source_input_contract_v1"
ADAPTIVE_CONTRACT_STATUS = "FROZEN_V2_4_ADAPTIVE_MULTI_SEED_DUAL_SOURCE_INPUTS"
ADAPTIVE_TEACHER_GENERATION = "V4D_MULTI_SEED_PLUS_V4H_ADAPTIVE_MULTI_SEED_V2"
SOURCE_RECEIPT_SCHEMA = "pvrig_v6_v4h_adaptive_multiseed_contact_teacher_v2_receipt"
SOURCE_RECEIPT_STATUS = "PASS_V4H_ADAPTIVE_MULTI_SEED_CONTACT_EXTRACTION"
MARGINAL_RECEIPT_SCHEMA = "pvrig_v2_4_adaptive_multiseed_dual_source_marginal_receipt_v1"
MARGINAL_RECEIPT_STATUS = "PASS_V2_4_ADAPTIVE_MULTI_SEED_DUAL_SOURCE_MARGINAL_MATERIALIZED"
PAIR_RECEIPT_SCHEMA = "pvrig_v2_4_adaptive_multiseed_dual_source_pair_receipt_v1"
PAIR_RECEIPT_STATUS = "PASS_V2_4_ADAPTIVE_MULTI_SEED_DUAL_SOURCE_PAIR_MATERIALIZED"
V4D_RECEIPT_SCHEMA = "pvrig_v6_v4d_open226_multi_seed_contact_teacher_v2_receipt"
V4D_RECEIPT_STATUS = "COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2"
TRAINING_TSV_SHA = "47c2c98fc282058e470ab0978b58daaf896262d593f017216cbc02cd5e6335e1"
POSTCAL_V1_HISTORICAL_SHA = "56f040f2814dbdb9e27a4484b4ef0fec7320f9e7581e24776b0a99a56aa0e662"
POSTCAL_TEST_V1_HISTORICAL_SHA = "75044eadf059fd19459f6b4fe9a9c4f7951c9c10201aa1eab23bbaa40a49f3fd"
FORBIDDEN_INPUT_TOKENS = ("v4h_stage1", "stage1_contact", "stage1_residue", "stage1_pair")
EXPECTED_COUNTS = {
    "training_candidates": 1507,
    "v4d_candidates": 226,
    "v4h_valid_candidates": 1281,
    "v4h_technical_incomplete_excluded": 39,
    "v4h_source_candidates": 1320,
    "v4h_selected_paired_jobs": 3536,
}
CALIBRATION_BATCH_COUNT = 8
CALIBRATION_MEDIAN_BAND = [0.05, 0.15]
CALIBRATION_MAXIMUM_FRACTION = 0.30
SUPERSESSION_VERSION = "V2.2_CLAIM_BOUNDARY_ALIGNMENT_ONLY"
BUNDLE_REVISION = "V2.2.1_STATUS_CONSTANT_ONLY"
TRAINER_RESULT_CLAIM_BOUNDARY = (
    "Open-only computational surrogate of independent 8X6B/9E6Y Docking "
    "geometry; not binding probability, affinity, experimental blocking, "
    "Docking Gold, or submission evidence."
)
EXPECTED_CONTACT_WEIGHTS = {
    "C_SPLIT_MARGINAL": {"marginal": 1.5, "pair": 0.0},
    "D_SPLIT_PAIR": {"marginal": 1.0, "pair": 0.5},
}
CALIBRATION_SELECTION_RULE = (
    "per_lane_smallest_grid_value_with_median_in_band_and_per_batch_max_at_or_below_"
    "ceiling_before_optimizer_step"
)
EXPECTED_V2_IMPLEMENTATION_SHA256 = {
    "calibration_trainer": "6947f912e85f4096ad660d7dc3a47d023a44e2bae8c63e619eab9707c80bcbc1",
    "calibration_trainer_test": "80da8ff20e3b349c25570aeb6caa81858ebedc82664eb1aca044195447533d2e",
    "deployment_launcher": "f5f9884f097bec8107d2a25973e23db4dc4884d2f1e9a3849b98f4b0f9d954fe",
    "deployment_launcher_test": "156ebe8216270ecfa13c56ba6d7b024314aa419124267928349f30d4005acc2d",
    "calibration_runner": "a380100bf58c4149c1f83bfb0b1490a88bdd5f80e5e123816fb1287352a481b5",
    "calibration_runner_test": "5f0b101e2ae518366d5240a51566a6c84e863541fe4970aeb72964302761d84f",
    "postcalibration_materializer": "a683a94e82d13439436d4dc2f768e13409a52e390cc979c11605407b27908d9a",
    "postcalibration_materializer_test": "f6b91ca43534c9eed2c7c971f6e8994b5e4b9a6b8f19e391bfd073ba2a4f2397",
    "v2_migration_test": "ff72c786585f83fcc51d735ec348e0f99e19ba71439c4ec46b6c9007e56dd742",
    "bundle_materializer": "43a001b5556f11dff95e8a90c4d5a8d04208911f5a719eb2116d998f0df56449",
}


class ManifestV2Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestV2Error(message)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha(value: Any, label: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value), f"{label}_invalid_sha256")
    return value


def regular(path: pathlib.Path, label: str) -> pathlib.Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ManifestV2Error(f"{label}_missing:{path}") from exc
    require(stat.S_ISREG(metadata.st_mode), f"{label}_not_regular_or_symlink:{path}")
    return path


def load_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    regular(path, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestV2Error(f"{label}_invalid_json:{path}") from exc
    require(isinstance(payload, dict), f"{label}_not_object")
    return payload


def reject_legacy_stage1_path(path: pathlib.Path, label: str) -> None:
    lowered = str(path).lower()
    require(not any(token in lowered for token in FORBIDDEN_INPUT_TOKENS), f"legacy_stage1_input_forbidden:{label}:{path}")
    require("adaptive" in path.name.lower(), f"adaptive_input_filename_required:{label}:{path.name}")


def artifact_record(path: pathlib.Path, node1_path: str) -> dict[str, Any]:
    regular(path, "artifact_source")
    return {
        "source_path": str(path.resolve()),
        "node1_path": node1_path,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "validation_mode": "LOCAL_SOURCE_AND_NODE1",
    }


def _contract_record(contract: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    records = contract.get("artifacts")
    require(isinstance(records, dict) and isinstance(records.get(label), dict), f"adaptive_contract_artifact_missing:{label}")
    record = records[label]
    require_sha(record.get("sha256"), f"adaptive_contract:{label}")
    require(isinstance(record.get("size_bytes"), int) and record["size_bytes"] >= 0, f"adaptive_contract_size:{label}")
    return record


def _validate_bound_file(path: pathlib.Path, contract: Mapping[str, Any], label: str, *, reject_stage1: bool) -> None:
    regular(path, label)
    if reject_stage1:
        reject_legacy_stage1_path(path, label)
    record = _contract_record(contract, label)
    require(path.stat().st_size == record["size_bytes"], f"adaptive_input_size:{label}")
    require(sha256_file(path) == record["sha256"], f"adaptive_input_sha256:{label}")


def _receipt_output_sha(receipt: Mapping[str, Any]) -> str | None:
    if isinstance(receipt.get("output"), dict):
        return receipt["output"].get("sha256")
    return receipt.get("output_sha256")


def _trainer_table_candidate_ids(path: pathlib.Path, required_fields: set[str], label: str) -> set[str]:
    try:
        handle = gzip.open(path, "rt", encoding="utf-8-sig", newline="")
        with handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = set(reader.fieldnames or [])
            require(required_fields <= fields, f"adaptive_{label}_table_header")
            candidate_ids: set[str] = set()
            teacher_sources: set[str] = set()
            source_by_candidate: dict[str, str] = {}
            for row in reader:
                candidate_id = row.get("candidate_id", "")
                require(bool(candidate_id), f"adaptive_{label}_candidate_id_empty")
                candidate_ids.add(candidate_id)
                source = row.get("teacher_source", "")
                teacher_sources.add(source)
                require(source_by_candidate.setdefault(candidate_id, source) == source, f"adaptive_{label}_candidate_source_conflict")
                require("adaptive" in row.get("schema_version", "").lower(), f"adaptive_{label}_schema_value")
            require(
                teacher_sources == {"V4D_OPEN_MULTI_SEED", "V4H_ADAPTIVE_SEED_RANKING"},
                f"adaptive_{label}_teacher_sources",
            )
            require(
                Counter(source_by_candidate.values())
                == Counter({"V4D_OPEN_MULTI_SEED": 226, "V4H_ADAPTIVE_SEED_RANKING": 1281}),
                f"adaptive_{label}_teacher_source_candidate_counts",
            )
            return candidate_ids
    except (gzip.BadGzipFile, EOFError, UnicodeDecodeError, csv.Error) as exc:
        raise ManifestV2Error(f"adaptive_{label}_table_invalid_gzip_tsv:{path}") from exc


def validate_trainer_ready_tables(marginal_path: pathlib.Path, pair_path: pathlib.Path) -> None:
    marginal_required = {
        "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
        "teacher_source", "vhh_sequence_index", "vhh_aa", "contact_target_8x6b",
        "contact_target_9e6y", "contact_variance_8x6b", "contact_variance_9e6y",
        "contact_uncertainty_weight_8x6b", "contact_uncertainty_weight_9e6y",
        "target_mask_8x6b", "target_mask_9e6y",
    }
    pair_required = {
        "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
        "teacher_source", "receptor", "vhh_sequence_index", "vhh_aa", "pvrig_node_index",
        "pvrig_uniprot_position", "pvrig_aa", "contact_target", "contact_variance",
        "contact_uncertainty_weight", "target_mask",
    }
    marginal_ids = _trainer_table_candidate_ids(marginal_path, marginal_required, "marginal")
    pair_ids = _trainer_table_candidate_ids(pair_path, pair_required, "pair")
    require(len(marginal_ids) == EXPECTED_COUNTS["training_candidates"], "adaptive_marginal_candidate_closure")
    require(len(pair_ids) == EXPECTED_COUNTS["training_candidates"], "adaptive_pair_candidate_closure")
    require(marginal_ids == pair_ids, "adaptive_marginal_pair_candidate_mismatch")


def validate_adaptive_inputs(
    *,
    input_contract_path: pathlib.Path,
    expected_input_contract_sha256: str,
    source_receipt_path: pathlib.Path,
    v4d_source_receipt_path: pathlib.Path,
    marginal_table_path: pathlib.Path,
    marginal_receipt_path: pathlib.Path,
    pair_table_path: pathlib.Path,
    pair_receipt_path: pathlib.Path,
) -> dict[str, Any]:
    expected = require_sha(expected_input_contract_sha256, "expected_adaptive_input_contract")
    contract = load_json(input_contract_path, "adaptive_input_contract")
    require(sha256_file(input_contract_path) == expected, "adaptive_input_contract_expected_sha256_mismatch")
    require(contract.get("schema_version") == ADAPTIVE_CONTRACT_SCHEMA, "adaptive_input_contract_schema")
    require(contract.get("status") == ADAPTIVE_CONTRACT_STATUS, "adaptive_input_contract_status")
    require(contract.get("teacher_generation") == ADAPTIVE_TEACHER_GENERATION, "adaptive_teacher_generation")
    require(contract.get("legacy_stage1_inputs_forbidden") is True, "adaptive_contract_legacy_gate")
    require(contract.get("training_tsv_sha256") == TRAINING_TSV_SHA, "adaptive_contract_training_sha")
    require(contract.get("expected_counts") == EXPECTED_COUNTS, "adaptive_contract_expected_counts")
    source_provenance = contract.get("v4h_source_provenance")
    require(isinstance(source_provenance, dict), "adaptive_contract_source_provenance")
    for field in ("contract_sha256", "reconciliation_receipt_sha256", "implementation_sha256"):
        require_sha(source_provenance.get(field), f"adaptive_contract_source_provenance:{field}")

    paths = {
        "v4h_adaptive_source_receipt": source_receipt_path,
        "v4d_source_receipt": v4d_source_receipt_path,
        "adaptive_marginal_tsv_gz": marginal_table_path,
        "adaptive_marginal_receipt": marginal_receipt_path,
        "adaptive_pair_tsv_gz": pair_table_path,
        "adaptive_pair_receipt": pair_receipt_path,
    }
    for label, path in paths.items():
        _validate_bound_file(path, contract, label, reject_stage1=label in {"adaptive_marginal_tsv_gz", "adaptive_pair_tsv_gz"})
    validate_trainer_ready_tables(marginal_table_path, pair_table_path)

    source = load_json(source_receipt_path, "v4h_adaptive_source_receipt")
    require(source.get("schema_version") == SOURCE_RECEIPT_SCHEMA, "adaptive_source_receipt_schema")
    require(source.get("status") == SOURCE_RECEIPT_STATUS, "adaptive_source_receipt_status")
    require(source.get("candidate_rows") == EXPECTED_COUNTS["v4h_source_candidates"], "adaptive_source_candidate_rows")
    require(source.get("valid_candidate_rows") == EXPECTED_COUNTS["v4h_valid_candidates"], "adaptive_source_valid_rows")
    require(source.get("technical_incomplete_candidate_rows") == EXPECTED_COUNTS["v4h_technical_incomplete_excluded"], "adaptive_source_incomplete_rows")
    require(source.get("selected_paired_job_rows") == EXPECTED_COUNTS["v4h_selected_paired_jobs"], "adaptive_source_paired_jobs")
    require(source.get("source_mutation_operations") == 0, "adaptive_source_mutation_operations")
    for field in ("contract_sha256", "reconciliation_receipt_sha256", "implementation_sha256"):
        require(source.get(field) == source_provenance[field], f"adaptive_source_{field}")
    require(isinstance(source.get("pair_rows"), int) and source["pair_rows"] > 0, "adaptive_source_pair_rows")
    require(isinstance(source.get("residue_rows"), int) and source["residue_rows"] > 0, "adaptive_source_residue_rows")
    output_hashes = source.get("output_hashes")
    require(isinstance(output_hashes, dict), "adaptive_source_output_hashes")
    require(require_sha(output_hashes.get("v4h_adaptive_residue_pair_contact_teacher.tsv.gz"), "adaptive_source_raw_pair") != "", "adaptive_source_raw_pair")
    require(require_sha(output_hashes.get("v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz"), "adaptive_source_raw_marginal") != "", "adaptive_source_raw_marginal")
    source_sha = sha256_file(source_receipt_path)
    v4d = load_json(v4d_source_receipt_path, "v4d_source_receipt")
    require(v4d.get("schema_version") == V4D_RECEIPT_SCHEMA, "v4d_source_receipt_schema")
    require(v4d.get("status") == V4D_RECEIPT_STATUS, "v4d_source_receipt_status")
    require((v4d.get("counts") or {}).get("teacher_candidates") == EXPECTED_COUNTS["v4d_candidates"], "v4d_source_candidate_rows")
    require((v4d.get("counts") or {}).get("zero_imputed_failed_seeds") == 0, "v4d_source_zero_imputation")
    require((v4d.get("source") or {}).get("source_mutation_operations") == 0, "v4d_source_mutation_operations")
    v4d_sha = sha256_file(v4d_source_receipt_path)

    for lane, path, expected_schema, expected_status, table_path in (
        ("marginal", marginal_receipt_path, MARGINAL_RECEIPT_SCHEMA, MARGINAL_RECEIPT_STATUS, marginal_table_path),
        ("pair", pair_receipt_path, PAIR_RECEIPT_SCHEMA, PAIR_RECEIPT_STATUS, pair_table_path),
    ):
        receipt = load_json(path, f"adaptive_{lane}_receipt")
        require(receipt.get("schema_version") == expected_schema, f"adaptive_{lane}_receipt_schema")
        require(receipt.get("status") == expected_status, f"adaptive_{lane}_receipt_status")
        require(receipt.get("teacher_generation") == ADAPTIVE_TEACHER_GENERATION, f"adaptive_{lane}_generation")
        require(receipt.get("training_tsv_sha256") == TRAINING_TSV_SHA, f"adaptive_{lane}_training_sha")
        require(receipt.get("v4h_adaptive_source_receipt_sha256") == source_sha, f"adaptive_{lane}_source_receipt_sha")
        require(receipt.get("v4d_source_receipt_sha256") == v4d_sha, f"adaptive_{lane}_v4d_source_receipt_sha")
        require(
            receipt.get("v4h_adaptive_raw_pair_teacher_sha256")
            == output_hashes["v4h_adaptive_residue_pair_contact_teacher.tsv.gz"],
            f"adaptive_{lane}_raw_pair_sha",
        )
        require(
            receipt.get("v4h_adaptive_raw_marginal_teacher_sha256")
            == output_hashes["v4h_adaptive_vhh_residue_marginal_teacher.tsv.gz"],
            f"adaptive_{lane}_raw_marginal_sha",
        )
        require(_receipt_output_sha(receipt) == sha256_file(table_path), f"adaptive_{lane}_output_sha")
        require(receipt.get("candidate_rows") == EXPECTED_COUNTS["training_candidates"], f"adaptive_{lane}_candidate_rows")
        require(receipt.get("v4d_candidate_rows") == EXPECTED_COUNTS["v4d_candidates"], f"adaptive_{lane}_v4d_rows")
        require(receipt.get("v4h_valid_candidate_rows") == EXPECTED_COUNTS["v4h_valid_candidates"], f"adaptive_{lane}_v4h_rows")
        require(receipt.get("v4h_technical_incomplete_excluded") == EXPECTED_COUNTS["v4h_technical_incomplete_excluded"], f"adaptive_{lane}_excluded_rows")
        require(receipt.get("legacy_stage1_rows") == 0, f"adaptive_{lane}_legacy_stage1_rows")

    return {
        "status": ADAPTIVE_CONTRACT_STATUS,
        "teacher_generation": ADAPTIVE_TEACHER_GENERATION,
        "legacy_stage1_inputs_forbidden": True,
        "input_contract_sha256": expected,
        "source_receipt_sha256": source_sha,
        "v4d_source_receipt_sha256": v4d_sha,
        "input_contract_artifact_label": "adaptive_input_contract",
        "source_receipt_artifact_label": "v4h_adaptive_source_receipt",
        "trainer_input_artifact_labels": {
            "marginal": "adaptive_marginal_tsv_gz",
            "pair": "adaptive_pair_tsv_gz",
        },
        "expected_counts": EXPECTED_COUNTS,
    }


def local_record(repo: pathlib.Path, relative: str, node1_path: str) -> dict[str, Any]:
    return artifact_record((repo / relative).resolve(), node1_path)


def canonical_candidate_ids_sha256(candidate_ids: list[str]) -> str:
    require(candidate_ids and len(candidate_ids) == len(set(candidate_ids)), "calibration_batch_candidate_ids")
    return hashlib.sha256("".join(f"{value}\n" for value in candidate_ids).encode("utf-8")).hexdigest()


def calibration_batch_selection_contract(
    training_tsv: pathlib.Path, split_json: pathlib.Path, *, seed: int, batch_size: int,
) -> dict[str, Any]:
    regular(training_tsv, "calibration_training_tsv")
    split = load_json(split_json, "calibration_split_json")
    train_parents = split.get("train_parents")
    require(isinstance(train_parents, list) and train_parents, "calibration_train_parents")
    with training_tsv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {
        "candidate_id", "parent_framework_cluster", "teacher_source",
        "development_reliability_tier",
    }
    require(rows and required <= set(rows[0]), "calibration_training_header")
    selected = [row for row in rows if row["parent_framework_cluster"] in set(train_parents)]
    require(selected, "calibration_training_rows_empty")
    random.Random(seed).shuffle(selected)
    complete_batches = len(selected) // batch_size
    require(complete_batches >= CALIBRATION_BATCH_COUNT, "calibration_complete_batches_insufficient")
    offsets = [
        index * (complete_batches - 1) // (CALIBRATION_BATCH_COUNT - 1)
        for index in range(CALIBRATION_BATCH_COUNT)
    ]
    require(len(offsets) == len(set(offsets)) == CALIBRATION_BATCH_COUNT, "calibration_batch_offsets")
    seen: set[str] = set()
    records = []
    for batch_number, offset in enumerate(offsets):
        batch = selected[offset * batch_size:(offset + 1) * batch_size]
        require(len(batch) == batch_size, f"calibration_batch_incomplete:{offset}")
        candidate_ids = [row["candidate_id"] for row in batch]
        require(seen.isdisjoint(candidate_ids), f"calibration_batch_candidate_reuse:{offset}")
        seen.update(candidate_ids)
        records.append({
            "batch_id": f"B{batch_number:02d}_OFFSET_{offset:04d}",
            "batch_offset": offset,
            "forward_seed": seed + 1_000_003 + offset,
            "candidate_ids": candidate_ids,
            "candidate_ids_sha256": canonical_candidate_ids_sha256(candidate_ids),
            "candidate_count": len(candidate_ids),
            "teacher_source_counts": dict(Counter(row["teacher_source"] for row in batch)),
            "contact_tier_counts": dict(Counter(row["development_reliability_tier"] for row in batch)),
            "parent_framework_clusters": sorted({row["parent_framework_cluster"] for row in batch}),
        })
    digest_payload = {
        "selection_algorithm": "evenly_spaced_complete_batches_after_python_random_seed_shuffle_v1",
        "seed": seed,
        "batch_size": batch_size,
        "training_candidate_count": len(selected),
        "complete_batch_count": complete_batches,
        "batch_records": records,
    }
    digest = hashlib.sha256(
        (json.dumps(digest_payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    return {**digest_payload, "contract_sha256": digest}


def compose_payload(
    artifacts: dict[str, dict[str, Any]], adaptive: Mapping[str, Any],
    calibration_batches: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    require(not os.path.lexists(RUNTIME), f"runtime_must_be_absent:{RUNTIME}")
    require(not os.path.lexists(CALIBRATION_RUNTIME), f"calibration_runtime_must_be_absent:{CALIBRATION_RUNTIME}")
    require(isinstance(calibration_batches, dict), "calibration_batch_contract_missing")
    prefixes = [
        "ALL__", "CDR1_CDR2__", "CDR1_CDR3__", "CDR1_FRAMEWORK__", "CDR1__",
        "CDR2_CDR3__", "CDR2_FRAMEWORK__", "CDR2__", "CDR3_FRAMEWORK__", "CDR3__",
        "CDR_ALL__", "FRAMEWORK__",
    ]
    template = [
        "{python}", "{trainer}", "--lane", "{lane}", "--output-dir", "{output_dir}",
        "--split-manifest", "{split_manifest}", "--v2-3-bundle-root", V23_BUNDLE,
        "--training-tsv", "{training_tsv}", "--contact-tsv-gz", "{adaptive_marginal_tsv_gz}",
        "--graph-cache-dir", "{vhh_graph_dir}", "--target-graph-pt", "{base_target_pt}",
        "--pair-contact-tsv-gz", "{adaptive_pair_tsv_gz}", "--structure-dim", "126",
        "--contact-formula-json", "{contact_formula}",
        "--model-path", HF_SNAPSHOT, "--model-identity-file", "{esm2_650m_identity}",
        "--expected-model-sha256", ESM_SHA, "--learning-rate", "0.0001", "--weight-decay", "0.02",
        "--gradient-clip", "1.0", "--gradient-accumulation", "2", "--huber-delta", "0.03",
        "--receptor-weight", "1.0", "--dual-weight", "0.5", "--ridge-alpha", "10.0", "--seed", "43",
    ]
    for prefix in prefixes:
        template.extend(("--structure-prefix", prefix))
    return {
        "schema_version": MANIFEST_SCHEMA,
        "manifest_generation": "V2_2_1_STATUS_CONSTANT_CORRECTED",
        "status": MANIFEST_STATUS,
        "production_authorized": False,
        "claim_boundary": "Open-only adaptive-multiseed independent 8X6B/9E6Y computational Docking geometry surrogate; not binding, affinity, experimental blocking, Docking Gold, or submission evidence.",
        "trainer_result_claim_boundary": TRAINER_RESULT_CLAIM_BOUNDARY,
        "bundle_root": BUNDLE,
        "runtime_root": RUNTIME,
        "python": "/data1/qlyu/software/envs/pvrig-v6-tc/bin/python",
        "resources": {
            "lane_gpu_map": {"A_VHH_ONLY": 1, "B_TARGET_NO_CONTACT": 2, "C_SPLIT_MARGINAL": 4, "D_SPLIT_PAIR": 5},
            "cpu_threads_per_process": 8,
            "thread_environment": {"OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "8", "NUMEXPR_NUM_THREADS": "8", "TOKENIZERS_PARALLELISM": "false"},
        },
        "execution": {
            "phase_order": ["OPEN_ONLY_CONTACT_GRADIENT_CALIBRATION", "IMPLEMENTATION_FREEZE", "TINY_SMOKE", "FOUR_LANE_OUTER_DEVELOPMENT"],
            "outer_folds": [0, 1, 2, 3, 4], "lanes_concurrent": 4,
            "folds_sequential_within_lane": True, "tiny_smoke_must_pass_all_lanes": True,
            "automatic_smoke_to_outer_transition": False,
        },
        "expected_training_counts": {
            "rows": 1507, "unique_candidates": 1507, "unique_parent_framework_clusters": 31,
            "teacher_sources": {"V4D_OPEN_MULTI_SEED": 226, "V4H_ADAPTIVE_SEED_RANKING": 1281},
            "reliability_tiers": {"A": 349, "B": 241, "C": 917},
        },
        "adaptive_supervision": dict(adaptive),
        "technical_supersession": {
            "version": SUPERSESSION_VERSION,
            "scope": (
                "V2.2.1 nonnumeric execution-contract closure: pending-status correction; "
                "campaign/base-trainer claim separation; freeze and receipt schema/claim/revision "
                "validation; frozen lane-weight propagation into ready tiny-smoke commands; and "
                "hash-bound builder/launcher/postcalibration/bundle/test closure"
            ),
            "numeric_method_changes": 0,
            "grid_changes": 0,
            "gate_changes": 0,
            "batch_changes": 0,
            "model_changes": 0,
            "v2_1_selected_contact_weights": EXPECTED_CONTACT_WEIGHTS,
            "audit_artifact_label": "v2_2_supersession_audit",
            "audit_sha256": artifacts["v2_2_supersession_audit"]["sha256"],
            "bundle_revision": BUNDLE_REVISION,
            "bundle_revision_scope": (
                "status-triggered technical closure across builder, runner, launcher, "
                "postcalibration materializer, bundle materializer, receipts, and tests"
            ),
            "bundle_revision_numeric_method_changes": 0,
            "bundle_revision_audit_artifact_label": "v2_2_1_status_supersession_audit",
            "bundle_revision_audit_sha256": artifacts["v2_2_1_status_supersession_audit"]["sha256"],
        },
        "artifacts": artifacts,
        "trainer": {
            "artifact_label": "trainer", "argv_template": template,
            "calibration_artifact_label": "calibration_trainer",
            "tiny_smoke_extra_argv": ["--backbone-kind", "tiny", "--tiny-e2e", "--fixed-epochs", "1", "--graph-hidden-dim", "32", "--dropout", "0", "--batch-size", "4", "--device", "cpu", "--precision", "fp32"],
            "outer_development_extra_argv": None, "lane_outer_extra_argv": None,
            "required_result_file": "RESULT.json",
            "frozen_noncalibration_parameters": {"structure_dim": 126, "graph_hidden_dim": 128, "dropout": 0.25, "fixed_epochs": 8, "batch_size": 8, "learning_rate": 0.0001, "weight_decay": 0.02, "gradient_clip": 1.0, "gradient_accumulation": 2, "precision": "bf16", "huber_delta": 0.03, "receptor_weight": 1.0, "dual_weight": 0.5, "ridge_alpha": 10.0, "seed": 43},
        },
        "calibration_contract": {
            "binding_status": "PENDING_V2_2_1_ADAPTIVE_OPEN_ONLY_PRESTEP_CALIBRATION",
            "receipt_artifact_label": None,
            "calibration_runtime_root": CALIBRATION_RUNTIME,
            "calibration_receipt_node1_path": f"{BUNDLE}/CALIBRATION_RECEIPT.json",
            "open_only": True, "optimizer_steps_before_observation": 0,
            "outer_metrics_access_count": 0, "prediction_metrics_access_count": 0,
            "fixed_grid": [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0],
            "pair_to_marginal_ratio": 0.5,
            "target_median_gradient_fraction_band": CALIBRATION_MEDIAN_BAND,
            "maximum_per_batch_gradient_fraction": CALIBRATION_MAXIMUM_FRACTION,
            "selection_rule": CALIBRATION_SELECTION_RULE,
            "batch_selection": dict(calibration_batches),
            "frozen_lane_contact_weights": None,
            "attention_temperatures": {"8x6b": 1.0, "9e6y": 1.0},
        },
        "runtime_must_remain_absent_until_implementation_freeze": True,
        "pending": ["CALIBRATION_RECEIPT.json", "frozen_lane_contact_weights", "IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_1.json"],
        "sealed_evaluation_access_count": 0,
        "prediction_metrics_access_count": 0,
        "historical_v1_non_input_provenance": {
            "postcalibration_materializer_v1_sha256": POSTCAL_V1_HISTORICAL_SHA,
            "postcalibration_materializer_test_v1_sha256": POSTCAL_TEST_V1_HISTORICAL_SHA,
            "production_input": False,
        },
    }


def run(
    *, repo: pathlib.Path, output: pathlib.Path, input_contract: pathlib.Path,
    expected_input_contract_sha256: str, source_receipt: pathlib.Path,
    marginal_table: pathlib.Path, marginal_receipt: pathlib.Path,
    pair_table: pathlib.Path, pair_receipt: pathlib.Path,
    v4d_source_receipt: pathlib.Path,
) -> dict[str, Any]:
    adaptive = validate_adaptive_inputs(
        input_contract_path=input_contract,
        expected_input_contract_sha256=expected_input_contract_sha256,
        source_receipt_path=source_receipt,
        v4d_source_receipt_path=v4d_source_receipt,
        marginal_table_path=marginal_table,
        marginal_receipt_path=marginal_receipt,
        pair_table_path=pair_table,
        pair_receipt_path=pair_receipt,
    )
    p = "experiments/phase2_5080_v1/v6_target_conditioned_surrogate_20260717/v2_4_fs_stack_prototype_v1_20260718"
    r = "experiments/phase2_5080_v1"
    artifacts: dict[str, dict[str, Any]] = {}
    specs = {
        "prefreeze_builder": (f"{p}/deployment/build_prefreeze_manifest_v2_2_1.py", f"{BUNDLE}/src/build_prefreeze_manifest_v2_2_1.py"),
        "training_tsv": (f"{p}/data_contract/materialized_v1/v6_supervised1507_v2_4.tsv", f"{BUNDLE}/inputs/v6_supervised1507_v2_4.tsv"),
        "training_receipt": (f"{p}/data_contract/materialized_v1/v6_supervised1507_v2_4.receipt.json", f"{BUNDLE}/inputs/v6_supervised1507_v2_4.receipt.json"),
        "trainer": (f"{p}/trainer/train_v2_4_base_split.py", f"{BUNDLE}/src/train_v2_4_base_split.py"),
        "trainer_test": (f"{p}/trainer/test_train_v2_4_base_split.py", f"{BUNDLE}/tests/test_train_v2_4_base_split.py"),
        "calibration_trainer": (f"{p}/trainer/observe_v2_4_multibatch_calibration_v2_2.py", f"{BUNDLE}/src/observe_v2_4_multibatch_calibration_v2_2.py"),
        "calibration_trainer_test": (f"{p}/trainer/test_observe_v2_4_multibatch_calibration_v2_2.py", f"{BUNDLE}/tests/test_observe_v2_4_multibatch_calibration_v2_2.py"),
        "model": (f"{p}/model/residue_model_v2_4.py", f"{BUNDLE}/src/residue_model_v2_4.py"),
        "model_test": (f"{p}/model/test_residue_model_v2_4.py", f"{BUNDLE}/tests/test_residue_model_v2_4.py"),
        "calibration_runner": (f"{p}/deployment/run_open_only_prestep_calibration_v2_2_1.py", f"{BUNDLE}/src/run_open_only_prestep_calibration_v2_2_1.py"),
        "calibration_runner_test": (f"{p}/deployment/test_run_open_only_prestep_calibration_v2_2_1.py", f"{BUNDLE}/tests/test_run_open_only_prestep_calibration_v2_2_1.py"),
        "deployment_launcher": (f"{p}/deployment/node1_v2_4_outer_development_launcher_v2_2_1.py", f"{BUNDLE}/src/node1_v2_4_outer_development_launcher_v2_2_1.py"),
        "deployment_launcher_test": (f"{p}/deployment/test_node1_v2_4_outer_development_launcher_v2_2_1.py", f"{BUNDLE}/tests/test_node1_v2_4_outer_development_launcher_v2_2_1.py"),
        "postcalibration_materializer": (f"{p}/deployment/materialize_postcalibration_freeze_v2_2_1.py", f"{BUNDLE}/src/materialize_postcalibration_freeze_v2_2_1.py"),
        "postcalibration_materializer_test": (f"{p}/deployment/test_materialize_postcalibration_freeze_v2_2_1.py", f"{BUNDLE}/tests/test_materialize_postcalibration_freeze_v2_2_1.py"),
        "v2_migration_test": (f"{p}/deployment/test_v2_2_claim_supersession.py", f"{BUNDLE}/tests/test_v2_2_claim_supersession.py"),
        "bundle_materializer": (f"{p}/deployment/materialize_node1_bundle_v2_2_1.py", f"{BUNDLE}/src/materialize_node1_bundle_v2_2_1.py"),
        "v2_2_supersession_audit": (f"{p}/deployment/V2_CALIBRATION_CLAIM_BOUNDARY_SUPERSESSION_V2_2.json", f"{BUNDLE}/audits/V2_CALIBRATION_CLAIM_BOUNDARY_SUPERSESSION_V2_2.json"),
        "v2_2_1_status_supersession_audit": (f"{p}/deployment/V2_2_1_STATUS_CONSTANT_SUPERSESSION.json", f"{BUNDLE}/audits/V2_2_1_STATUS_CONSTANT_SUPERSESSION.json"),
        "contact_formula": (f"{p}/contact_contract/contact_score_formula_v1.json", f"{BUNDLE}/inputs/contact_contract/contact_score_formula_v1.json"),
        "outer_split_source": (f"{p}/split_contract/prepared/whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4/outer_development_manifest.tsv", f"{BUNDLE}/inputs/splits/source_outer_development_manifest.tsv"),
        "outer_split_materialization_receipt": (f"{p}/deployment/prepared/outer_split_json_v1/receipt.json", f"{BUNDLE}/inputs/splits/receipt.json"),
        "vhh_graph_cache_npz": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/graph_cache_v2.npz", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/graph_cache_v2.npz"),
        "vhh_graph_manifest": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/graph_manifest_v2.tsv", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/graph_manifest_v2.tsv"),
        "vhh_graph_receipt": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/graph_cache_receipt_v2.json", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/graph_cache_receipt_v2.json"),
        "vhh_graph_closure": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/graph_input_closure_v2.tsv", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/graph_input_closure_v2.tsv"),
        "vhh_graph_materialization_receipt": (f"{r}/prepared/pvrig_v6_residue_v2_supervised1507_graph_inputs_v1_20260718/materialization_receipt_v2.json", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/vhh_graphs/materialization_receipt_v2.json"),
        "base_target_pt": (f"{r}/prepared/pvrig_v6_residue_v2_fixed_target_graphs_v1_20260718/target_graphs_v2.pt", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graphs_v2.pt"),
        "base_target_receipt": (f"{r}/prepared/pvrig_v6_residue_v2_fixed_target_graphs_v1_20260718/target_graph_receipt_v2.json", "/data1/qlyu/projects/pvrig_v6_residue_v2_deployment_bundle_v1_20260718/inputs/base_target_graphs/target_graph_receipt_v2.json"),
        "v23_trainer": (f"{r}/v6_target_conditioned_surrogate_20260717/residue_v2/src/train_nested_residue_surrogate_v2.py", f"{V23_BUNDLE}/residue_v2/src/train_nested_residue_surrogate_v2.py"),
        "v1_trainer": (f"{r}/v6_target_conditioned_surrogate_20260717/residue_v1/src/train_nested_residue_surrogate.py", f"{V23_BUNDLE}/residue_v1/src/train_nested_residue_surrogate.py"),
        "v1_5_trainer": (f"{r}/v6_target_conditioned_surrogate_20260717/residue_v1/src/train_nested_residue_surrogate_v1_5.py", f"{V23_BUNDLE}/residue_v1/src/train_nested_residue_surrogate_v1_5.py"),
        "v1_model": (f"{r}/v6_target_conditioned_surrogate_20260717/residue_v1/src/residue_model.py", f"{V23_BUNDLE}/residue_v1/src/residue_model.py"),
        "v23_freeze": (f"{r}/prepared/pvrig_v6_residue_v2_3_numerical_soak_launcher_v1_20260718/IMPLEMENTATION_FREEZE_V2_3.json", f"{V23_BUNDLE}/residue_v2/IMPLEMENTATION_FREEZE_V2.json"),
    }
    for label, (source, node1) in specs.items():
        artifacts[label] = local_record(repo, source, node1)
    for label, expected_sha256 in EXPECTED_V2_IMPLEMENTATION_SHA256.items():
        require(
            artifacts[label]["sha256"] == expected_sha256,
            f"v2_implementation_sha256_mismatch:{label}:{artifacts[label]['sha256']}:{expected_sha256}",
        )
    supersession_audit = json.loads(
        pathlib.Path(artifacts["v2_2_1_status_supersession_audit"]["source_path"]).read_text(encoding="utf-8")
    )
    audit_label_map = {
        "prefreeze_builder": "prefreeze_builder",
        "runner": "calibration_runner",
        "runner_test": "calibration_runner_test",
        "launcher": "deployment_launcher",
        "launcher_test": "deployment_launcher_test",
        "postcalibration_materializer": "postcalibration_materializer",
        "postcalibration_materializer_test": "postcalibration_materializer_test",
        "bundle_materializer": "bundle_materializer",
    }
    corrected = supersession_audit.get("corrected_artifacts") or {}
    require(set(corrected) == set(audit_label_map), "v2_2_1_audit_corrected_artifact_labels")
    for audit_label, artifact_label in audit_label_map.items():
        require(
            corrected[audit_label].get("sha256") == artifacts[artifact_label]["sha256"],
            f"v2_2_1_audit_artifact_sha256:{audit_label}",
        )
    for fold in range(5):
        artifacts[f"outer_split_{fold}"] = local_record(repo, f"{p}/deployment/prepared/outer_split_json_v1/outer_fold_{fold}.json", f"{BUNDLE}/inputs/splits/outer_fold_{fold}.json")
    for label, path, node1_name in (
        ("adaptive_input_contract", input_contract, "adaptive_input_contract_v1.json"),
        ("v4h_adaptive_source_receipt", source_receipt, "v4h_adaptive_source_RUN_RECEIPT.json"),
        ("v4d_source_receipt", v4d_source_receipt, "v4d_open226_source_RUN_RECEIPT.json"),
        ("adaptive_marginal_tsv_gz", marginal_table, "v6_dual_source_adaptive_multiseed_marginal_targets_v2.tsv.gz"),
        ("adaptive_marginal_receipt", marginal_receipt, "adaptive_marginal_RUN_RECEIPT.json"),
        ("adaptive_pair_tsv_gz", pair_table, "v6_dual_source_adaptive_multiseed_pair_targets_v2.tsv.gz"),
        ("adaptive_pair_receipt", pair_receipt, "adaptive_pair_RUN_RECEIPT.json"),
    ):
        artifacts[label] = artifact_record(path, f"{BUNDLE}/inputs/adaptive_contacts/{node1_name}")
    artifacts["esm2_650m_identity"] = {
        "node1_path": f"{HF_SNAPSHOT}/model.safetensors", "sha256": ESM_SHA,
        "size_bytes": 2609506392, "validation_mode": "INHERITED_NODE1_IMMUTABLE",
        "inherited_freeze_sha256": artifacts["v23_freeze"]["sha256"],
    }
    calibration_batches = calibration_batch_selection_contract(
        pathlib.Path(artifacts["training_tsv"]["source_path"]),
        pathlib.Path(artifacts["outer_split_0"]["source_path"]),
        seed=43, batch_size=8,
    )
    payload = compose_payload(artifacts, adaptive, calibration_batches)
    resolved_output = output.resolve()
    require(
        resolved_output == pathlib.Path(BUNDLE) / "V2_4_NODE1_PREFREEZE_MANIFEST_V2_2_1.json"
        or resolved_output.is_relative_to(repo.resolve()),
        "output_path_not_local_or_canonical_node1",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    require(not output.exists(), f"output_exists:{output}")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "PASS_V2_2_1_ADAPTIVE_PREFREEZE_MANIFEST_MATERIALIZED_CALIBRATION_PENDING", "output": str(output), "sha256": sha256_file(output), "artifact_count": len(artifacts)}


def input_preflight(paths: Mapping[str, pathlib.Path]) -> dict[str, Any]:
    missing = sorted(label for label, path in paths.items() if not path.exists())
    return {
        "schema_version": "pvrig_v2_4_adaptive_prefreeze_input_preflight_v2_2_1",
        "status": "BLOCKED_INPUT_ADAPTIVE_ARTIFACTS_NOT_MATERIALIZED" if missing else "READY_FOR_V2_2_1_MANIFEST_MATERIALIZATION",
        "missing": missing,
        "production_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--adaptive-input-contract", type=pathlib.Path, required=True)
    parser.add_argument("--expected-adaptive-input-contract-sha256", required=True)
    parser.add_argument("--v4h-adaptive-source-receipt", type=pathlib.Path, required=True)
    parser.add_argument("--v4d-source-receipt", type=pathlib.Path, required=True)
    parser.add_argument("--adaptive-marginal-table", type=pathlib.Path, required=True)
    parser.add_argument("--adaptive-marginal-receipt", type=pathlib.Path, required=True)
    parser.add_argument("--adaptive-pair-table", type=pathlib.Path, required=True)
    parser.add_argument("--adaptive-pair-receipt", type=pathlib.Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    paths = {
        "adaptive_input_contract": args.adaptive_input_contract,
        "v4h_adaptive_source_receipt": args.v4h_adaptive_source_receipt,
        "v4d_source_receipt": args.v4d_source_receipt,
        "adaptive_marginal_table": args.adaptive_marginal_table,
        "adaptive_marginal_receipt": args.adaptive_marginal_receipt,
        "adaptive_pair_table": args.adaptive_pair_table,
        "adaptive_pair_receipt": args.adaptive_pair_receipt,
    }
    preflight = input_preflight(paths)
    if args.preflight_only or preflight["missing"]:
        print(json.dumps(preflight, indent=2, sort_keys=True))
        return 0 if not preflight["missing"] else 2
    result = run(
        repo=args.repo_root, output=args.output,
        input_contract=args.adaptive_input_contract,
        expected_input_contract_sha256=args.expected_adaptive_input_contract_sha256,
        source_receipt=args.v4h_adaptive_source_receipt,
        v4d_source_receipt=args.v4d_source_receipt,
        marginal_table=args.adaptive_marginal_table,
        marginal_receipt=args.adaptive_marginal_receipt,
        pair_table=args.adaptive_pair_table,
        pair_receipt=args.adaptive_pair_receipt,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ManifestV2Error, OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"FAIL_V2_2_1_ADAPTIVE_PREFREEZE_MANIFEST:{error}", file=os.sys.stderr)
        raise SystemExit(1)
