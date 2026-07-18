#!/usr/bin/env python3
"""Validate receptor-specific compact inner-OOF evidence for the V2.4 stack.

This is a data-contract validator only.  It does not train a base model, fit a
scaler, fit the meta stack, or infer missing receptor-specific features.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


ROW_SCHEMA_VERSION = "pvrig_v2_4_receptor_compact_inner_oof_row_v1"
PROVENANCE_SCHEMA_VERSION = "pvrig_v2_4_receptor_compact_inner_oof_provenance_v1"
REPORT_SCHEMA_VERSION = "pvrig_v2_4_receptor_compact_inner_oof_validation_report_v1"
EVIDENCE_ROLE = "INNER_OOF"

COMPACT_FEATURE_COLUMNS = (
    "M2_R8",
    "neural_R8",
    "contact_score_R8",
    "M2_R9",
    "neural_R9",
    "contact_score_R9",
)

EXACT_COLUMNS = (
    "schema_version",
    "evidence_role",
    "candidate_id",
    "teacher_source",
    "parent_framework_cluster",
    "outer_fold",
    "inner_fold",
    "R_8X6B",
    "R_9E6Y",
    "R_dual_min",
    *COMPACT_FEATURE_COLUMNS,
    "base_training_parent_set_sha256",
    "base_model_receipt_sha256",
    "base_model_artifact_path",
    "scaler_fit_parent_set_sha256",
    "scaler_receipt_sha256",
    "scaler_artifact_path",
    "meta_fit_parent_set_sha256",
    "meta_fit_receipt_sha256",
    "meta_fit_artifact_path",
)

NUMERIC_COLUMNS = (
    "R_8X6B",
    "R_9E6Y",
    "R_dual_min",
    *COMPACT_FEATURE_COLUMNS,
)

SHA_COLUMNS = (
    "base_training_parent_set_sha256",
    "base_model_receipt_sha256",
    "scaler_fit_parent_set_sha256",
    "scaler_receipt_sha256",
    "meta_fit_parent_set_sha256",
    "meta_fit_receipt_sha256",
)

PATH_COLUMNS = (
    "base_model_artifact_path",
    "scaler_artifact_path",
    "meta_fit_artifact_path",
)

_V4F_TOKEN = re.compile(r"(^|[/\\._-])v4[/\\._-]?f($|[/\\._-])", re.IGNORECASE)


class ContractValidationError(ValueError):
    """Raised when the evidence contract is incomplete or leakage-prone."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_parent_set_sha256(parents: Iterable[str]) -> str:
    values = sorted(set(parents))
    payload = "".join(f"{value}\n" for value in values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _contains_v4f_token(value: str) -> bool:
    return _V4F_TOKEN.search(value) is not None


def _validate_artifact_path(value: str, context: str) -> None:
    if _contains_v4f_token(value):
        raise ContractValidationError(f"forbidden_v4f_path:{context}:{value}")
    if not Path(value).is_absolute():
        raise ContractValidationError(f"artifact_path_not_absolute:{context}:{value}")


def read_evidence_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ContractValidationError(f"missing_header:{path}")
        rows = list(reader)
    validate_row_schema(rows, reader.fieldnames)
    return rows


def validate_row_schema(
    rows: Sequence[Mapping[str, str]], fieldnames: Sequence[str]
) -> None:
    observed = tuple(fieldnames)
    if observed != EXACT_COLUMNS:
        missing = [column for column in EXACT_COLUMNS if column not in observed]
        extra = [column for column in observed if column not in EXACT_COLUMNS]
        raise ContractValidationError(
            "exact_header_mismatch:"
            f"missing={','.join(missing) or '-'}:extra={','.join(extra) or '-'}:"
            f"order_match={set(observed) == set(EXACT_COLUMNS)}"
        )
    if not rows:
        raise ContractValidationError("empty_evidence")

    candidate_ids: set[str] = set()
    parent_sources: dict[str, str] = {}
    for row_number, row in enumerate(rows, start=2):
        for column in EXACT_COLUMNS:
            if column not in row or str(row[column]).strip() == "":
                raise ContractValidationError(
                    f"blank_required_value:row={row_number}:column={column}"
                )
        if row["schema_version"] != ROW_SCHEMA_VERSION:
            raise ContractValidationError(
                f"row_schema_version_mismatch:row={row_number}:{row['schema_version']}"
            )
        if row["evidence_role"] != EVIDENCE_ROLE:
            raise ContractValidationError(
                f"evidence_role_mismatch:row={row_number}:{row['evidence_role']}"
            )

        candidate_id = row["candidate_id"]
        if candidate_id in candidate_ids:
            raise ContractValidationError(f"duplicate_candidate_id:{candidate_id}")
        candidate_ids.add(candidate_id)

        source = row["teacher_source"]
        parent = row["parent_framework_cluster"]
        previous_source = parent_sources.setdefault(parent, source)
        if previous_source != source:
            raise ContractValidationError(
                f"parent_in_multiple_sources:{parent}:{previous_source}:{source}"
            )
        if re.sub(r"[^a-z0-9]", "", source.lower()) == "v4f":
            raise ContractValidationError(f"forbidden_v4f_source:{candidate_id}:{source}")

        for column in NUMERIC_COLUMNS:
            try:
                value = float(row[column])
            except (TypeError, ValueError) as exc:
                raise ContractValidationError(
                    f"non_numeric_value:row={row_number}:column={column}"
                ) from exc
            if not math.isfinite(value):
                raise ContractValidationError(
                    f"non_finite_value:row={row_number}:column={column}"
                )

        r8 = np.float64(row["R_8X6B"])
        r9 = np.float64(row["R_9E6Y"])
        dual = np.float64(row["R_dual_min"])
        expected_dual = np.minimum(r8, r9)
        if dual.tobytes() != expected_dual.tobytes():
            raise ContractValidationError(
                f"truth_dual_not_exact_min:row={row_number}:candidate={candidate_id}:"
                f"observed={dual!r}:expected={expected_dual!r}"
            )

        for column in SHA_COLUMNS:
            if not _is_sha256(row[column]):
                raise ContractValidationError(
                    f"invalid_sha256:row={row_number}:column={column}"
                )
        for column in PATH_COLUMNS:
            _validate_artifact_path(row[column], f"row={row_number}:column={column}")


def load_provenance(path: Path) -> dict[str, Any]:
    provenance = json.loads(path.read_text(encoding="utf-8"))
    if provenance.get("schema_version") != PROVENANCE_SCHEMA_VERSION:
        raise ContractValidationError("provenance_schema_version_mismatch")
    for key in ("base_models", "scalers", "meta_fits"):
        if not isinstance(provenance.get(key), dict):
            raise ContractValidationError(f"missing_provenance_section:{key}")
    validate_provenance_manifest(provenance)
    return provenance


def _validate_parent_block(
    block: Mapping[str, Any],
    *,
    list_key: str,
    digest_key: str,
    context: str,
) -> set[str]:
    raw_parents = block.get(list_key)
    if not isinstance(raw_parents, list) or not raw_parents:
        raise ContractValidationError(f"missing_or_empty_parent_list:{context}:{list_key}")
    parents = [str(value) for value in raw_parents]
    if len(set(parents)) != len(parents):
        raise ContractValidationError(f"duplicate_parent_in_manifest:{context}")
    observed_digest = str(block.get(digest_key, ""))
    expected_digest = canonical_parent_set_sha256(parents)
    if observed_digest != expected_digest:
        raise ContractValidationError(
            f"manifest_parent_digest_mismatch:{context}:"
            f"observed={observed_digest}:expected={expected_digest}"
        )
    return set(parents)


def validate_provenance_manifest(provenance: Mapping[str, Any]) -> None:
    section_contracts = {
        "base_models": (
            "training_parent_framework_clusters",
            "training_parent_set_sha256",
        ),
        "scalers": ("fit_parent_framework_clusters", "fit_parent_set_sha256"),
        "meta_fits": ("fit_parent_framework_clusters", "fit_parent_set_sha256"),
    }
    for section_name, (parent_key, digest_key) in section_contracts.items():
        section = provenance.get(section_name)
        if not isinstance(section, dict):
            raise ContractValidationError(f"missing_provenance_section:{section_name}")
        for receipt_sha, block in section.items():
            if not _is_sha256(str(receipt_sha)):
                raise ContractValidationError(
                    f"invalid_manifest_receipt_sha256:{section_name}:{receipt_sha}"
                )
            if not isinstance(block, dict):
                raise ContractValidationError(
                    f"invalid_manifest_receipt_block:{section_name}:{receipt_sha}"
                )
            for fold_key in ("outer_fold", "inner_fold"):
                if str(block.get(fold_key, "")).strip() == "":
                    raise ContractValidationError(
                        f"blank_manifest_fold:{section_name}:{receipt_sha}:{fold_key}"
                    )
            _validate_artifact_path(
                str(block.get("artifact_path", "")),
                f"manifest:{section_name}:{receipt_sha}",
            )
            _validate_parent_block(
                block,
                list_key=parent_key,
                digest_key=digest_key,
                context=f"{section_name}:{receipt_sha}",
            )


def _validate_receipt_reference(
    *,
    row: Mapping[str, str],
    provenance_section: Mapping[str, Any],
    receipt_column: str,
    row_digest_column: str,
    row_path_column: str,
    manifest_parent_list_key: str,
    manifest_digest_key: str,
    kind: str,
) -> set[str]:
    receipt_sha = row[receipt_column]
    block = provenance_section.get(receipt_sha)
    if not isinstance(block, dict):
        raise ContractValidationError(
            f"unknown_{kind}_receipt:{row['candidate_id']}:{receipt_sha}"
        )
    if str(block.get("outer_fold")) != str(row["outer_fold"]):
        raise ContractValidationError(
            f"{kind}_outer_fold_mismatch:{row['candidate_id']}"
        )
    if str(block.get("inner_fold")) != str(row["inner_fold"]):
        raise ContractValidationError(
            f"{kind}_inner_fold_mismatch:{row['candidate_id']}"
        )
    artifact_path = str(block.get("artifact_path", ""))
    _validate_artifact_path(artifact_path, f"manifest:{kind}:{receipt_sha}")
    if artifact_path != row[row_path_column]:
        raise ContractValidationError(
            f"{kind}_artifact_path_mismatch:{row['candidate_id']}"
        )

    parents = _validate_parent_block(
        block,
        list_key=manifest_parent_list_key,
        digest_key=manifest_digest_key,
        context=f"{kind}:{receipt_sha}",
    )
    if row[row_digest_column] != block[manifest_digest_key]:
        raise ContractValidationError(
            f"{kind}_row_parent_digest_mismatch:{row['candidate_id']}"
        )
    if row["parent_framework_cluster"] in parents:
        raise ContractValidationError(
            f"in_sample_parent:{kind}:{row['candidate_id']}:"
            f"{row['parent_framework_cluster']}"
        )
    return parents


def validate_provenance(
    rows: Sequence[Mapping[str, str]], provenance: Mapping[str, Any]
) -> dict[str, Any]:
    validate_provenance_manifest(provenance)
    base_parent_sets: set[str] = set()
    scaler_parent_sets: set[str] = set()
    meta_parent_sets: set[str] = set()
    for row in rows:
        _validate_receipt_reference(
            row=row,
            provenance_section=provenance["base_models"],
            receipt_column="base_model_receipt_sha256",
            row_digest_column="base_training_parent_set_sha256",
            row_path_column="base_model_artifact_path",
            manifest_parent_list_key="training_parent_framework_clusters",
            manifest_digest_key="training_parent_set_sha256",
            kind="base_model",
        )
        base_parent_sets.add(row["base_training_parent_set_sha256"])

        _validate_receipt_reference(
            row=row,
            provenance_section=provenance["scalers"],
            receipt_column="scaler_receipt_sha256",
            row_digest_column="scaler_fit_parent_set_sha256",
            row_path_column="scaler_artifact_path",
            manifest_parent_list_key="fit_parent_framework_clusters",
            manifest_digest_key="fit_parent_set_sha256",
            kind="scaler",
        )
        scaler_parent_sets.add(row["scaler_fit_parent_set_sha256"])

        _validate_receipt_reference(
            row=row,
            provenance_section=provenance["meta_fits"],
            receipt_column="meta_fit_receipt_sha256",
            row_digest_column="meta_fit_parent_set_sha256",
            row_path_column="meta_fit_artifact_path",
            manifest_parent_list_key="fit_parent_framework_clusters",
            manifest_digest_key="fit_parent_set_sha256",
            kind="meta_fit",
        )
        meta_parent_sets.add(row["meta_fit_parent_set_sha256"])

    return {
        "status": "PASS_RECEPTOR_COMPACT_INNER_OOF_CONTRACT",
        "candidate_count": len(rows),
        "parent_count": len({row["parent_framework_cluster"] for row in rows}),
        "source_count": len({row["teacher_source"] for row in rows}),
        "outer_fold_count": len({row["outer_fold"] for row in rows}),
        "inner_fold_count": len(
            {(row["outer_fold"], row["inner_fold"]) for row in rows}
        ),
        "base_parent_set_digest_count": len(base_parent_sets),
        "scaler_parent_set_digest_count": len(scaler_parent_sets),
        "meta_parent_set_digest_count": len(meta_parent_sets),
        "compact_feature_columns": list(COMPACT_FEATURE_COLUMNS),
        "compact_feature_count": len(COMPACT_FEATURE_COLUMNS),
        "truth_contract": "R_dual_min is bit-exact numpy.minimum(R_8X6B, R_9E6Y)",
        "leakage_contract": (
            "candidate parent absent from base-training, scaler-fit, and meta-fit parent sets"
        ),
    }


def validate_contract(evidence_path: Path, provenance_path: Path) -> dict[str, Any]:
    rows = read_evidence_tsv(evidence_path)
    provenance = load_provenance(provenance_path)
    report = validate_provenance(rows, provenance)
    report.update(
        {
            "schema_version": REPORT_SCHEMA_VERSION,
            "evidence_tsv": {
                "path": str(evidence_path.resolve()),
                "sha256": sha256_file(evidence_path),
            },
            "provenance_json": {
                "path": str(provenance_path.resolve()),
                "sha256": sha256_file(provenance_path),
            },
            "exact_columns": list(EXACT_COLUMNS),
        }
    )
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    evidence_path = Path(args.evidence_tsv)
    provenance_path = Path(args.provenance_json)
    report_path = Path(args.report_json)
    if report_path.exists():
        raise ContractValidationError(f"report_already_exists:{report_path}")
    report = validate_contract(evidence_path, provenance_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-tsv", required=True)
    parser.add_argument("--provenance-json", required=True)
    parser.add_argument("--report-json", required=True)
    return parser


def main() -> int:
    report = run(build_parser().parse_args())
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
