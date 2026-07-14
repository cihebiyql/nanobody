#!/usr/bin/env python3
"""Validate the immutable V1.2 failed-RC evidence freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "phase2_v3_p2_v1_2_failed_rc_freeze_manifest_v1"
FREEZE_STATUS = "FROZEN_FAILED_RC_V1_2"
VALIDATION_OUTCOME = "FAIL_DOCKING_GOLD_NOT_VALIDATED"
TRAINING_STATE = "P2_TRAINING_BLOCKED"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def json_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer!r}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        else:
            current = current[token]
    return current


def parse_sha256_listing(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            digest, relative = raw_line.split(None, 1)
        except ValueError as exc:
            raise ValueError(f"Malformed hash listing line {line_number}: {raw_line!r}") from exc
        relative = relative.strip()
        if relative.startswith("*"):
            relative = relative[1:]
        if relative.startswith("./"):
            relative = relative[2:]
        if not SHA256_RE.fullmatch(digest):
            raise ValueError(f"Invalid SHA256 on listing line {line_number}: {digest!r}")
        if not relative or relative in entries:
            raise ValueError(f"Invalid or duplicate listing path on line {line_number}: {relative!r}")
        entries[relative] = digest
    return entries


def _add_equal(errors: list[str], label: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        errors.append(f"{label}: {observed!r} != {expected!r}")


def validate_payload(payload: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    errors: list[str] = []

    _add_equal(errors, "schema_version", payload.get("schema_version"), SCHEMA_VERSION)
    _add_equal(errors, "status", payload.get("status"), FREEZE_STATUS)
    _add_equal(
        errors,
        "validation_outcome",
        payload.get("validation_outcome"),
        VALIDATION_OUTCOME,
    )
    _add_equal(errors, "training_state", payload.get("training_state"), TRAINING_STATE)

    release = payload.get("release_eligibility", {})
    for key in (
        "threshold_freeze_eligible",
        "pose_rule_threshold_freeze_eligible",
        "single_8x6b_dock_run_method_freeze_eligible",
        "dual_receptor_r_gold_freeze_eligible",
        "training_label_release_eligible",
        "formal_eligible",
        "p2_training_ready",
    ):
        _add_equal(errors, f"release_eligibility.{key}", release.get(key), False)
    _add_equal(
        errors,
        "release_eligibility.continuous_input_provenance_reuse_only",
        release.get("continuous_input_provenance_reuse_only"),
        True,
    )

    gate = payload.get("failed_acceptance_gate", {})
    _add_equal(errors, "failed_acceptance_gate.name", gate.get("name"), "bootstrap")
    _add_equal(errors, "failed_acceptance_gate.required_anchor_count", gate.get("required_anchor_count"), 9)
    _add_equal(errors, "failed_acceptance_gate.observed_anchor_count", gate.get("observed_anchor_count"), 7)
    _add_equal(errors, "failed_acceptance_gate.total_anchor_count", gate.get("total_anchor_count"), 11)
    _add_equal(errors, "failed_acceptance_gate.minimum_modal_probability", gate.get("minimum_modal_probability"), 0.70)

    policy = payload.get("reuse_policy", {})
    _add_equal(errors, "reuse_policy.mode", policy.get("mode"), "CONTINUOUS_INPUT_AND_PROVENANCE_ONLY")
    prohibited = set(policy.get("prohibited_uses", []))
    required_prohibitions = {
        "CURRENT_ABC_E_OR_G1_G5_AS_GOLD_LABELS",
        "CURRENT_R_CALIBRATION_RUN_8X6B_DOCK_AS_GOLD",
        "P2_MODEL_TRAINING_OR_LABEL_RELEASE",
        "SMOKE8_OR_FAILED52_SCORING_WITH_V1_2_RULES",
        "DUAL_RECEPTOR_R_GOLD_CLAIM",
        "FORMAL_HOLDOUT_OR_EXPERIMENTAL_TRUTH_CLAIM",
        "RETROACTIVE_V1_2_GATE_OR_THRESHOLD_CHANGE",
    }
    missing_prohibitions = sorted(required_prohibitions - prohibited)
    if missing_prohibitions:
        errors.append(f"reuse_policy.prohibited_uses missing: {missing_prohibitions}")

    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifacts: expected a non-empty list")
        artifacts = []
    _add_equal(errors, "artifact_count", payload.get("artifact_count"), len(artifacts))
    paths = [item.get("path") for item in artifacts if isinstance(item, dict)]
    if len(paths) != len(set(paths)):
        errors.append("artifacts: duplicate paths")
    if paths != sorted(paths):
        errors.append("artifacts: paths are not lexicographically sorted")
    expected_inventory_digest = payload.get("artifact_inventory_sha256")
    observed_inventory_digest = canonical_sha256(artifacts)
    _add_equal(
        errors,
        "artifact_inventory_sha256",
        observed_inventory_digest,
        expected_inventory_digest,
    )

    artifact_paths: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            errors.append(f"artifact record is not an object: {item!r}")
            continue
        relative = item.get("path")
        expected_sha = item.get("sha256")
        expected_bytes = item.get("bytes")
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
            errors.append(f"artifact path is not repository-relative: {relative!r}")
            continue
        artifact_paths.add(relative)
        if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
            errors.append(f"artifact has invalid SHA256: {relative}: {expected_sha!r}")
            continue
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            errors.append(f"artifact has invalid byte size: {relative}: {expected_bytes!r}")
            continue
        if item.get("frozen") is not True:
            errors.append(f"artifact not marked frozen: {relative}")
        if item.get("reuse_class") not in {"PROVENANCE_ONLY", "CONTINUOUS_INPUT", "VALIDATOR"}:
            errors.append(f"invalid reuse_class for {relative}: {item.get('reuse_class')!r}")
        path = repo_root / relative
        if not path.is_file():
            errors.append(f"artifact missing: {relative}")
            continue
        observed_sha = sha256_file(path)
        if observed_sha != expected_sha:
            errors.append(f"artifact SHA256 mismatch: {relative}: {observed_sha} != {expected_sha}")
        if path.stat().st_size != expected_bytes:
            errors.append(f"artifact byte-size mismatch: {relative}: {path.stat().st_size} != {expected_bytes}")

    listing_entry_total = 0
    for contract in payload.get("hash_listing_contracts", []):
        listing_rel = contract["listing_path"]
        root_rel = contract["root"]
        listing_path = repo_root / listing_rel
        package_root = repo_root / root_rel
        try:
            listing = parse_sha256_listing(listing_path)
        except (OSError, ValueError) as exc:
            errors.append(f"hash listing invalid: {listing_rel}: {exc}")
            continue
        listing_entry_total += len(listing)
        _add_equal(errors, f"{listing_rel}.entry_count", len(listing), contract["entry_count"])
        observed_files = {
            str(path.relative_to(package_root))
            for path in package_root.rglob("*")
            if path.is_file()
        }
        listed_files = set(listing)
        if contract.get("require_exact_file_set") and observed_files != listed_files:
            errors.append(
                f"hash listing file-set mismatch: {listing_rel}: "
                f"missing={sorted(listed_files - observed_files)}; extra={sorted(observed_files - listed_files)}"
            )
        for relative, expected_sha in listing.items():
            path = package_root / relative
            if path.is_file():
                observed_sha = sha256_file(path)
                if observed_sha != expected_sha:
                    errors.append(
                        f"listed artifact SHA256 mismatch: {root_rel}/{relative}: "
                        f"{observed_sha} != {expected_sha}"
                    )

    for contract in payload.get("exact_directory_contracts", []):
        root_rel = contract["root"]
        directory = repo_root / root_rel
        observed = sorted(
            str(path.relative_to(directory))
            for path in directory.rglob("*")
            if path.is_file()
        )
        expected = sorted(contract["expected_files"])
        _add_equal(errors, f"exact directory {root_rel}", observed, expected)
        for relative in expected:
            full_relative = str(Path(root_rel) / relative)
            if full_relative not in artifact_paths:
                errors.append(f"exact directory artifact not hash-bound: {full_relative}")

    semantic_document_cache: dict[str, Any] = {}
    semantic_assertions = payload.get("semantic_assertions", [])
    _add_equal(
        errors,
        "semantic_assertion_count",
        payload.get("semantic_assertion_count"),
        len(semantic_assertions),
    )
    for assertion in semantic_assertions:
        relative = assertion["path"]
        if relative not in semantic_document_cache:
            try:
                semantic_document_cache[relative] = json.loads((repo_root / relative).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"semantic source invalid: {relative}: {exc}")
                continue
        try:
            observed = json_pointer(semantic_document_cache[relative], assertion["pointer"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            errors.append(f"semantic assertion pointer failed: {relative}{assertion['pointer']}: {exc}")
            continue
        _add_equal(
            errors,
            f"semantic assertion {relative}{assertion['pointer']}",
            observed,
            assertion["expected"],
        )

    return {
        "status": "PASS_V1_2_FAILED_RC_FREEZE_VALIDATED" if not errors else "FAIL_V1_2_FAILED_RC_FREEZE_INVALID",
        "valid": not errors,
        "artifact_count": len(artifacts),
        "hash_listing_entry_count": listing_entry_total,
        "semantic_assertion_count": len(payload.get("semantic_assertions", [])),
        "artifact_inventory_sha256": observed_inventory_digest,
        "errors": errors,
    }


def validate_manifest(manifest_path: Path, repo_root: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = validate_payload(payload, repo_root)
    result["manifest_path"] = str(manifest_path)
    result["manifest_sha256"] = sha256_file(manifest_path)
    return result


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[4]
    default_manifest = repo_root / "data/experiments/phase2_5080_v1/audits/phase2_v3_p2_v1_2_failed_rc_freeze_manifest.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate_manifest(args.manifest.resolve(), args.repo_root.resolve())
    except (OSError, json.JSONDecodeError) as exc:
        result = {
            "status": "FAIL_V1_2_FAILED_RC_FREEZE_INVALID",
            "valid": False,
            "errors": [str(exc)],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
