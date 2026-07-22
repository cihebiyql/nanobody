#!/usr/bin/env python3
"""Prepare and materialize label-free VHH residue graphs for canonical10644.

The adapter joins a frozen canonical candidate table to an independently
hash-pinned monomer-structure manifest.  It deliberately reads no contact
teacher, candidate Docking pose, Docking result, or pose-derived feature.
Actual graph construction is delegated to the frozen residue-v2 builder.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "pvrig_v2_11_canonical10644_label_free_graph_adapter_v1"
CONTRACT_SCHEMA = "pvrig_v2_11_canonical10644_label_free_graph_input_contract_v1"
PREPARED_MANIFEST = "canonical10644_label_free_graph_input_manifest_v1.tsv"
PREPARE_RECEIPT = "PREPARE_RECEIPT.json"
MATERIALIZATION_RECEIPT = "MATERIALIZATION_RECEIPT.json"
GRAPH_CACHE_DIR = "graph_cache"
EXPECTED_TARGET_STATUS = "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED"
EXPECTED_GRAPH_STATUS = "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE"
MATERIALIZATION_ENV = "PVRIG_ALLOW_CANONICAL10644_GRAPH_MATERIALIZATION"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")

CLAIM_BOUNDARY = (
    "Label-free single-chain VHH monomer residue graphs joined to the frozen "
    "canonical10644 candidate set and fixed public 8X6B/9E6Y target graphs; "
    "no contact teacher, candidate Docking pose, Docking result, pose-derived "
    "feature, binding, affinity, experimental blocking, or Docking Gold truth."
)

TEACHER_REQUIRED_FIELDS = {
    "candidate_id", "sequence_sha256", "sequence", "cdr1", "cdr2", "cdr3",
}
STRUCTURE_REQUIRED_FIELDS = {"candidate_id", "sequence_sha256"}
STRUCTURE_ALLOWED_FIELDS = {
    "schema_version",
    "candidate_id",
    "sequence_sha256",
    "monomer_relative_path",
    "frozen_monomer_path",
    "pdb_relative_path",
    "monomer_path",
    "monomer_sha256",
    "sha256",
    "source_chain",
    "chain",
    "size_bytes",
    "claim_boundary",
}
PATH_FIELDS = (
    "monomer_relative_path", "frozen_monomer_path", "pdb_relative_path", "monomer_path",
)
HASH_FIELDS = ("monomer_sha256", "sha256")
CHAIN_FIELDS = ("source_chain", "chain")
FORBIDDEN_STRUCTURE_FIELD_TOKENS = (
    "contact", "pose", "docking", "teacher", "target", "score", "result", "complex",
)
FORBIDDEN_PATH_TOKENS = (
    "contact", "pose", "docking", "docked", "haddock", "teacher", "complex", "job_result",
)
OUTPUT_FIELDS = (
    "schema_version",
    "candidate_id",
    "sequence",
    "sequence_sha256",
    "monomer_relative_path",
    "monomer_sha256",
    "source_chain",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "claim_boundary",
)


class CanonicalGraphError(RuntimeError):
    """Fail-closed canonical graph preparation error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CanonicalGraphError(message)


def sha256_file(path: Path) -> str:
    require(path.exists() and path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _read_tsv(path: Path, label: str) -> tuple[list[str], list[dict[str, str]]]:
    require(path.exists() and path.is_file() and not path.is_symlink(), f"{label}_invalid")
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    require(fields, f"{label}_header_missing")
    require(rows, f"{label}_empty")
    return fields, rows


def _resolve_contract_path(contract_path: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    workspace_root = Path(__file__).resolve().parents[5]
    return workspace_root / path


def load_contract(contract_path: Path) -> dict[str, Any]:
    require(contract_path.exists() and contract_path.is_file() and not contract_path.is_symlink(), "contract_invalid")
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    require(payload.get("schema_version") == CONTRACT_SCHEMA, "contract_schema_invalid")
    require(payload.get("status") == "FROZEN_PRE_MATERIALIZATION", "contract_status_invalid")
    require(payload.get("implicit_materialization_authorized") is False, "implicit_materialization_must_be_false")
    require(int(payload.get("expected_rows", 0)) > 0, "contract_expected_rows_invalid")
    return payload


def _require_digest(value: str, label: str) -> str:
    digest = value.strip().lower()
    require(bool(SHA256_RE.fullmatch(digest)), f"{label}_sha256_invalid")
    return digest


def _one_alias(row: Mapping[str, str], fields: Sequence[str], label: str) -> str:
    values = [row.get(field, "").strip() for field in fields if row.get(field, "").strip()]
    require(values, f"{label}_missing")
    require(len(set(values)) == 1, f"{label}_alias_conflict")
    return values[0]


def _validate_relative_monomer_path(value: str, candidate_id: str) -> str:
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts, f"monomer_path_unsafe:{candidate_id}")
    require(path.suffix.lower() == ".pdb", f"monomer_path_not_pdb:{candidate_id}")
    lowered_parts = [part.lower() for part in path.parts]
    require(
        not any(token in part for part in lowered_parts for token in FORBIDDEN_PATH_TOKENS),
        f"monomer_path_forbidden_token:{candidate_id}",
    )
    return path.as_posix()


def _cdr_range(sequence: str, cdr: str, name: str, candidate_id: str) -> tuple[int, int]:
    require(bool(cdr) and bool(AA_RE.fullmatch(cdr)), f"{name}_invalid:{candidate_id}")
    require(sequence.count(cdr) == 1, f"{name}_not_unique_exact_substring:{candidate_id}")
    start = sequence.index(cdr) + 1
    return start, start + len(cdr) - 1


def load_canonical_candidates(path: Path, expected_rows: int) -> dict[str, dict[str, str]]:
    fields, rows = _read_tsv(path, "canonical_candidates")
    require(TEACHER_REQUIRED_FIELDS <= set(fields), "canonical_candidate_fields_missing")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = row["candidate_id"].strip()
        sequence = row["sequence"].strip().upper()
        digest = _require_digest(row["sequence_sha256"], f"candidate_sequence:{candidate_id}")
        require(candidate_id and candidate_id not in result, f"candidate_id_duplicate:{candidate_id}")
        require(bool(AA_RE.fullmatch(sequence)), f"candidate_sequence_invalid:{candidate_id}")
        require(sequence_sha256(sequence) == digest, f"candidate_sequence_sha256_mismatch:{candidate_id}")
        ranges = [_cdr_range(sequence, row[name].strip().upper(), name, candidate_id) for name in ("cdr1", "cdr2", "cdr3")]
        require(ranges[0][1] < ranges[1][0] and ranges[1][1] < ranges[2][0], f"candidate_cdr_order_invalid:{candidate_id}")
        result[candidate_id] = {
            "sequence": sequence,
            "sequence_sha256": digest,
            "cdr1_range": f"{ranges[0][0]}-{ranges[0][1]}",
            "cdr2_range": f"{ranges[1][0]}-{ranges[1][1]}",
            "cdr3_range": f"{ranges[2][0]}-{ranges[2][1]}",
        }
    require(len(result) == expected_rows, f"canonical_candidate_count_mismatch:{len(result)}!={expected_rows}")
    return result


def load_structure_manifest(path: Path, expected_rows: int) -> dict[str, dict[str, str]]:
    fields, rows = _read_tsv(path, "structure_manifest")
    field_set = set(fields)
    require(STRUCTURE_REQUIRED_FIELDS <= field_set, "structure_manifest_fields_missing")
    require(field_set <= STRUCTURE_ALLOWED_FIELDS, f"structure_manifest_unapproved_fields:{sorted(field_set - STRUCTURE_ALLOWED_FIELDS)}")
    require(
        not any(token in field.lower() for field in fields for token in FORBIDDEN_STRUCTURE_FIELD_TOKENS),
        "structure_manifest_forbidden_field",
    )
    require(any(field in field_set for field in PATH_FIELDS), "structure_manifest_path_field_missing")
    require(any(field in field_set for field in HASH_FIELDS), "structure_manifest_hash_field_missing")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = row["candidate_id"].strip()
        require(candidate_id and candidate_id not in result, f"structure_candidate_duplicate:{candidate_id}")
        digest = _require_digest(row["sequence_sha256"], f"structure_sequence:{candidate_id}")
        monomer_digest = _require_digest(_one_alias(row, HASH_FIELDS, f"monomer_sha256:{candidate_id}"), f"monomer:{candidate_id}")
        relative = _validate_relative_monomer_path(_one_alias(row, PATH_FIELDS, f"monomer_path:{candidate_id}"), candidate_id)
        chain_values = [row.get(field, "").strip() for field in CHAIN_FIELDS if row.get(field, "").strip()]
        require(chain_values and len(set(chain_values)) == 1, f"source_chain_missing_or_conflict:{candidate_id}")
        chain = chain_values[0]
        require(len(chain) == 1 and chain.isalnum(), f"source_chain_invalid:{candidate_id}")
        if row.get("claim_boundary", "").strip():
            claim = row["claim_boundary"].lower()
            require("label-free" in claim and "docking gold" in claim, f"structure_claim_boundary_invalid:{candidate_id}")
        result[candidate_id] = {
            "sequence_sha256": digest,
            "monomer_relative_path": relative,
            "monomer_sha256": monomer_digest,
            "source_chain": chain,
        }
    require(len(result) == expected_rows, f"structure_manifest_count_mismatch:{len(result)}!={expected_rows}")
    return result


def join_candidates_and_structures(
    candidates: Mapping[str, Mapping[str, str]],
    structures: Mapping[str, Mapping[str, str]],
) -> list[dict[str, str]]:
    candidate_ids = set(candidates)
    structure_ids = set(structures)
    require(candidate_ids == structure_ids, f"candidate_structure_id_set_mismatch:missing={len(candidate_ids-structure_ids)}:extra={len(structure_ids-candidate_ids)}")
    output: list[dict[str, str]] = []
    for candidate_id in sorted(candidate_ids):
        candidate = candidates[candidate_id]
        structure = structures[candidate_id]
        require(candidate["sequence_sha256"] == structure["sequence_sha256"], f"candidate_structure_sequence_mismatch:{candidate_id}")
        output.append({
            "schema_version": SCHEMA_VERSION,
            "candidate_id": candidate_id,
            "sequence": candidate["sequence"],
            "sequence_sha256": candidate["sequence_sha256"],
            "monomer_relative_path": structure["monomer_relative_path"],
            "monomer_sha256": structure["monomer_sha256"],
            "source_chain": structure["source_chain"],
            "cdr1_range": candidate["cdr1_range"],
            "cdr2_range": candidate["cdr2_range"],
            "cdr3_range": candidate["cdr3_range"],
            "claim_boundary": CLAIM_BOUNDARY,
        })
    require(len({(row["candidate_id"], row["sequence_sha256"], row["monomer_sha256"]) for row in output}) == len(output), "candidate_sequence_monomer_triplet_duplicate")
    return output


def _write_manifest(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    require(bool(rows), "prepared_manifest_empty")
    from io import StringIO
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(OUTPUT_FIELDS), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_text(path, buffer.getvalue())


def verify_target_graph_binding(contract_path: Path, contract: Mapping[str, Any]) -> dict[str, str]:
    binding = dict(contract.get("fixed_target_graph") or {})
    receipt_path = _resolve_contract_path(contract_path, str(binding.get("receipt_path", "")))
    expected_receipt = _require_digest(str(binding.get("receipt_sha256", "")), "target_receipt")
    require(sha256_file(receipt_path) == expected_receipt, "target_receipt_sha256_mismatch")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("status") == EXPECTED_TARGET_STATUS, "target_receipt_status_invalid")
    sealed = dict(receipt.get("sealed_boundary") or {})
    require(sealed.get("candidate_docking_pose_files_opened") == 0, "target_receipt_candidate_pose_access_nonzero")
    require(sealed.get("teacher_source_is_model_feature") is False, "target_receipt_teacher_source_feature")
    require(sealed.get("absolute_coordinates_are_node_features") is False, "target_receipt_absolute_coordinate_feature")
    observed = {"target_graph_receipt_v2.json": expected_receipt}
    for name, item in dict(binding.get("artifacts") or {}).items():
        artifact_path = _resolve_contract_path(contract_path, str(item.get("path", "")))
        expected = _require_digest(str(item.get("sha256", "")), f"target_artifact:{name}")
        require(sha256_file(artifact_path) == expected, f"target_artifact_sha256_mismatch:{name}")
        require((receipt.get("outputs") or {}).get(name) == expected, f"target_receipt_output_binding_mismatch:{name}")
        observed[name] = expected
    require({"target_graph_cache_v2.npz", "target_graph_manifest_v2.tsv", "target_graphs_v2.pt"} <= set(observed), "target_artifact_set_incomplete")
    return observed


def verify_graph_builder_binding(contract_path: Path, contract: Mapping[str, Any]) -> Path:
    binding = dict(contract.get("graph_builder") or {})
    path = _resolve_contract_path(contract_path, str(binding.get("path", "")))
    expected = _require_digest(str(binding.get("sha256", "")), "graph_builder")
    require(sha256_file(path) == expected, "graph_builder_sha256_mismatch")
    return path


def _load_graph_builder(path: Path) -> Any:
    name = f"pvrig_residue_graph_builder_{sha256_file(path)[:12]}"
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None, "graph_builder_import_spec_invalid")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def prepare_bundle(
    *,
    contract_path: Path,
    structure_manifest_path: Path,
    expected_structure_manifest_sha256: str,
    output_dir: Path,
) -> dict[str, Any]:
    require(not output_dir.exists(), f"prepare_output_exists:{output_dir}")
    contract = load_contract(contract_path)
    expected_rows = int(contract["expected_rows"])
    candidate_binding = dict(contract.get("canonical_candidates") or {})
    candidate_path = _resolve_contract_path(contract_path, str(candidate_binding.get("path", "")))
    expected_candidate_sha = _require_digest(str(candidate_binding.get("sha256", "")), "canonical_candidates")
    require(sha256_file(candidate_path) == expected_candidate_sha, "canonical_candidates_sha256_mismatch")
    expected_structure_sha = _require_digest(expected_structure_manifest_sha256, "structure_manifest")
    require(sha256_file(structure_manifest_path) == expected_structure_sha, "structure_manifest_sha256_mismatch")
    target_hashes = verify_target_graph_binding(contract_path, contract)
    builder_path = verify_graph_builder_binding(contract_path, contract)
    candidates = load_canonical_candidates(candidate_path, expected_rows)
    structures = load_structure_manifest(structure_manifest_path, expected_rows)
    joined = join_candidates_and_structures(candidates, structures)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        manifest_path = staging / PREPARED_MANIFEST
        _write_manifest(manifest_path, joined)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_CANONICAL10644_LABEL_FREE_GRAPH_INPUT_PREPARED",
            "claim_boundary": CLAIM_BOUNDARY,
            "counts": {
                "canonical_candidates": len(candidates),
                "structure_manifest_rows": len(structures),
                "exact_candidate_sequence_monomer_triplets": len(joined),
            },
            "inputs": {
                "canonical_candidates_sha256": expected_candidate_sha,
                "structure_manifest_sha256": expected_structure_sha,
                "contract_sha256": sha256_file(contract_path),
                "graph_builder_sha256": sha256_file(builder_path),
                "fixed_target_graph_hashes": target_hashes,
            },
            "outputs": {PREPARED_MANIFEST: sha256_file(manifest_path)},
            "access_audit": {
                "contact_teacher_files_opened": 0,
                "candidate_docking_pose_files_opened": 0,
                "docking_result_files_opened": 0,
                "pose_derived_feature_files_opened": 0,
                "fixed_target_graphs_reused_not_rebuilt": True,
            },
            "materialization": {
                "performed": False,
                "requires_explicit_cli_flag": True,
                "requires_environment": f"{MATERIALIZATION_ENV}=1",
            },
        }
        _atomic_json(staging / PREPARE_RECEIPT, receipt)
        os.replace(staging, output_dir)
        return receipt
    finally:
        if staging.exists():
            import shutil
            shutil.rmtree(staging)


def _verify_prepared_bundle(prepared_dir: Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = prepared_dir / PREPARED_MANIFEST
    receipt_path = prepared_dir / PREPARE_RECEIPT
    require(manifest_path.is_file() and not manifest_path.is_symlink(), "prepared_manifest_invalid")
    require(receipt_path.is_file() and not receipt_path.is_symlink(), "prepare_receipt_invalid")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS_CANONICAL10644_LABEL_FREE_GRAPH_INPUT_PREPARED", "prepare_receipt_status_invalid")
    require((receipt.get("outputs") or {}).get(PREPARED_MANIFEST) == sha256_file(manifest_path), "prepared_manifest_sha256_mismatch")
    return manifest_path, receipt


def materialize_prepared_bundle(
    *,
    contract_path: Path,
    prepared_dir: Path,
    pdb_root: Path,
    explicit_authorization: bool,
) -> dict[str, Any]:
    require(explicit_authorization, "materialization_explicit_authorization_required")
    contract = load_contract(contract_path)
    expected_rows = int(contract["expected_rows"])
    manifest_path, prepare_receipt = _verify_prepared_bundle(prepared_dir)
    require((prepare_receipt.get("inputs") or {}).get("contract_sha256") == sha256_file(contract_path), "prepare_contract_binding_mismatch")
    target_hashes = verify_target_graph_binding(contract_path, contract)
    require((prepare_receipt.get("inputs") or {}).get("fixed_target_graph_hashes") == target_hashes, "prepare_target_graph_binding_mismatch")
    builder_path = verify_graph_builder_binding(contract_path, contract)
    require((prepare_receipt.get("inputs") or {}).get("graph_builder_sha256") == sha256_file(builder_path), "prepare_graph_builder_binding_mismatch")
    cache_dir = prepared_dir / GRAPH_CACHE_DIR
    require(not cache_dir.exists(), "graph_cache_output_exists")
    graph_builder = _load_graph_builder(builder_path)
    staging_cache = Path(tempfile.mkdtemp(prefix=f".{GRAPH_CACHE_DIR}.", dir=prepared_dir))
    try:
        graph_receipt = graph_builder.build_cache_from_manifest(
            manifest_path,
            pdb_root,
            staging_cache,
            expected_entities=expected_rows,
            config=graph_builder.GraphBuildConfig(),
        )
        require(graph_receipt.get("status") == EXPECTED_GRAPH_STATUS, "graph_receipt_status_invalid")
        require(graph_receipt.get("input_manifest_sha256") == sha256_file(manifest_path), "graph_input_manifest_binding_mismatch")
        require(int((graph_receipt.get("counts") or {}).get("entities", 0)) == expected_rows, "graph_entity_count_mismatch")
        os.replace(staging_cache, cache_dir)
    finally:
        if staging_cache.exists():
            import shutil
            shutil.rmtree(staging_cache)
    wrapper = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_CANONICAL10644_LABEL_FREE_GRAPH_MATERIALIZED",
        "claim_boundary": CLAIM_BOUNDARY,
        "counts": {
            "canonical_candidates": expected_rows,
            "graph_entities": int(graph_receipt["counts"]["entities"]),
            "graph_nodes": int(graph_receipt["counts"]["nodes"]),
            "graph_edges": int(graph_receipt["counts"]["edges"]),
        },
        "inputs": {
            "contract_sha256": sha256_file(contract_path),
            "prepared_manifest_sha256": sha256_file(manifest_path),
            "prepare_receipt_sha256": sha256_file(prepared_dir / PREPARE_RECEIPT),
            "graph_builder_sha256": sha256_file(builder_path),
            "fixed_target_graph_hashes": target_hashes,
        },
        "outputs": {
            "graph_cache_receipt_v2.json": sha256_file(cache_dir / "graph_cache_receipt_v2.json"),
            "graph_cache_v2.npz": sha256_file(cache_dir / "graph_cache_v2.npz"),
            "graph_manifest_v2.tsv": sha256_file(cache_dir / "graph_manifest_v2.tsv"),
        },
        "access_audit": {
            "contact_teacher_files_opened": 0,
            "candidate_docking_pose_files_opened": 0,
            "docking_result_files_opened": 0,
            "pose_derived_feature_files_opened": 0,
            "fixed_target_graphs_reused_not_rebuilt": True,
        },
    }
    _atomic_json(prepared_dir / MATERIALIZATION_RECEIPT, wrapper)
    return wrapper


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--mode", choices=("prepare", "materialize"), required=True)
    value.add_argument("--contract", type=Path, required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--structure-manifest", type=Path)
    value.add_argument("--expected-structure-manifest-sha256")
    value.add_argument("--pdb-root", type=Path)
    value.add_argument("--allow-high-load-materialization", action="store_true")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.mode == "prepare":
        require(args.structure_manifest is not None, "prepare_structure_manifest_required")
        require(args.expected_structure_manifest_sha256 is not None, "prepare_structure_manifest_sha256_required")
        require(args.pdb_root is None and not args.allow_high_load_materialization, "prepare_must_not_materialize")
        receipt = prepare_bundle(
            contract_path=args.contract,
            structure_manifest_path=args.structure_manifest,
            expected_structure_manifest_sha256=args.expected_structure_manifest_sha256,
            output_dir=args.output_dir,
        )
    else:
        require(args.structure_manifest is None and args.expected_structure_manifest_sha256 is None, "materialize_uses_prepared_manifest_only")
        require(args.pdb_root is not None, "materialize_pdb_root_required")
        require(args.allow_high_load_materialization, "materialization_cli_flag_required")
        require(os.environ.get(MATERIALIZATION_ENV) == "1", "materialization_environment_gate_required")
        receipt = materialize_prepared_bundle(
            contract_path=args.contract,
            prepared_dir=args.output_dir,
            pdb_root=args.pdb_root,
            explicit_authorization=True,
        )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
