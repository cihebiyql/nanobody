#!/usr/bin/env python3
"""Validate the frozen V1.3 terminal-OXT identity normalization amendment."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_AMENDMENT = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_atom_identity_normalization_amendment.json"
)
FROZEN_AMENDMENT_SHA256 = "daf5c628e424c185c9d33c13b90bdf8d875261a990cbbd04a07b48e272d5df23"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_artifact(raw: str, data_root: Path = DATA_ROOT) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe amendment artifact path: {raw!r}")
    return (data_root / path).resolve()


def validate_payload(payload: dict[str, Any], data_root: Path = DATA_ROOT) -> list[str]:
    errors: list[str] = []
    expected = {
        "schema_version": "phase2_v3_p2_v1_3_atom_identity_normalization_amendment_v1",
        "protocol_id": "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15",
        "status": "FROZEN_V1_3_TERMINAL_OXT_NORMALIZATION_AMENDMENT",
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            errors.append(f"{field}_mismatch")

    scope = payload.get("evidence_scope", {})
    scope_expected = {
        "exact_reuse_run_count": 64,
        "exact_reuse_pose_count": 512,
        "boundary_run_count": 4,
        "boundary_pose_count": 32,
        "total_run_count": 68,
        "total_pose_count": 544,
        "vhh_chain_a_residue_exact_count": 544,
        "vhh_chain_a_raw_atom_exact_count": 0,
        "vhh_chain_a_terminal_oxt_normalized_exact_count": 544,
        "vhh_chain_a_non_oxt_difference_count": 0,
        "pvrig_chain_b_residue_exact_count": 544,
        "pvrig_chain_b_raw_atom_exact_count": 544,
        "pvrig_chain_b_difference_count": 0,
    }
    for field, value in scope_expected.items():
        if scope.get(field) != value:
            errors.append(f"evidence_scope_{field}_mismatch")
    if scope.get("receptor_pose_counts") != {"8X6B": 272, "9E6Y": 272}:
        errors.append("evidence_scope_receptor_pose_counts_mismatch")

    rule = payload.get("normalization_rule", {})
    rule_expected = {
        "rule_id": "VHH_CHAIN_A_TERMINAL_OXT_PRESENCE_ONLY_V1",
        "applicable_chain": "A",
        "record_scope": "ATOM_heavy_atoms_only",
        "terminal_residue_definition": "last_ATOM_heavy_residue_in_file_order",
        "terminal_residue_identity_must_match": True,
        "residue_identity_normalization": "none",
        "allowed_atom_name": "OXT",
        "allowed_difference": "presence_or_absence_only_on_the_identical_terminal_residue",
        "symmetric_difference_maximum_atom_identities": 1,
        "non_terminal_oxt_allowed": False,
        "all_non_oxt_atoms_must_match": True,
        "all_other_atom_or_residue_differences": "fail_closed",
    }
    for field, value in rule_expected.items():
        if rule.get(field) != value:
            errors.append(f"normalization_rule_{field}_mismatch")
    if rule.get("residue_identity_key") != ["resseq", "icode", "resname"]:
        errors.append("normalization_rule_residue_key_mismatch")
    if rule.get("atom_identity_key") != [
        "resseq", "icode", "resname", "atom_name", "altloc", "element"
    ]:
        errors.append("normalization_rule_atom_key_mismatch")

    receptor = payload.get("receptor_rule", {})
    receptor_expected = {
        "applicable_chain": "B",
        "residue_identity_normalization": "none",
        "atom_identity_normalization": "none",
        "raw_residue_identity_must_match": True,
        "raw_atom_identity_must_match": True,
        "all_differences": "fail_closed",
    }
    for field, value in receptor_expected.items():
        if receptor.get(field) != value:
            errors.append(f"receptor_rule_{field}_mismatch")

    effects = payload.get("side_effect_contract", {})
    for field in (
        "coordinate_bytes_modified", "source_pose_hash_modified",
        "decompressed_coordinate_hash_modified", "haddock_score_modified",
        "native_rank_modified", "pose_selection_modified", "geometry_metric_modified",
    ):
        if effects.get(field) is not False:
            errors.append(f"side_effect_{field}_mismatch")
    if effects.get("normalization_used_only_for_identity_gate") is not True:
        errors.append("side_effect_identity_gate_only_mismatch")

    eligibility = payload.get("eligibility", {})
    if eligibility.get("development_identity_gate_use_permitted") is not True:
        errors.append("eligibility_development_gate_mismatch")
    for field in (
        "formal_eligible", "training_label_release_eligible",
        "docking_gold_release_eligible", "p2_training_ready",
    ):
        if eligibility.get(field) is not False:
            errors.append(f"eligibility_{field}_mismatch")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 4:
        return errors + ["artifacts_count_mismatch"]
    seen: set[str] = set()
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            errors.append(f"artifact_{index}_not_object")
            continue
        raw_path = str(item.get("path", ""))
        expected_hash = str(item.get("sha256", ""))
        expected_bytes = item.get("bytes")
        if not raw_path or raw_path in seen:
            errors.append(f"artifact_{index}_path_missing_or_duplicate")
            continue
        seen.add(raw_path)
        try:
            path = resolve_artifact(raw_path, data_root)
        except ValueError:
            errors.append(f"artifact_unsafe_path:{raw_path}")
            continue
        if not path.is_file():
            errors.append(f"artifact_missing:{raw_path}")
            continue
        if not HASH_RE.fullmatch(expected_hash) or sha256_file(path) != expected_hash:
            errors.append(f"artifact_hash_mismatch:{raw_path}")
        if not isinstance(expected_bytes, int) or path.stat().st_size != expected_bytes:
            errors.append(f"artifact_size_mismatch:{raw_path}")

    audit_items = [
        item for item in artifacts
        if str(item.get("role")) == "544_pose_machine_readable_identity_evidence"
    ]
    if len(audit_items) != 1:
        return errors + ["audit_artifact_binding_mismatch"]
    try:
        audit = json.loads(
            resolve_artifact(str(audit_items[0]["path"]), data_root).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return errors + [f"audit_unreadable:{error}"]
    if audit.get("status") != "PASS_V1_3_ATOM_IDENTITY_TERMINAL_OXT_ONLY_SUPPORTED":
        errors.append("audit_status_mismatch")
    if audit.get("summary", {}).get("pose_count") != 544:
        errors.append("audit_pose_count_mismatch")
    acceptance = audit.get("acceptance", {})
    for field in (
        "all_512_targeted_exact_reuse_poses_covered",
        "all_non_terminal_oxt_atom_identities_exact",
        "all_residue_identities_exact",
        "boundary4_complete_and_hash_closed",
        "total_544_pose_closure",
    ):
        if acceptance.get(field) is not True:
            errors.append(f"audit_acceptance_{field}_mismatch")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amendment", type=Path, default=DEFAULT_AMENDMENT)
    args = parser.parse_args()
    observed_hash = sha256_file(args.amendment)
    payload = json.loads(args.amendment.read_text(encoding="utf-8"))
    errors = validate_payload(payload)
    if observed_hash != FROZEN_AMENDMENT_SHA256:
        errors.insert(0, "amendment_sha256_mismatch")
    result = {
        "status": (
            "PASS_V1_3_ATOM_IDENTITY_NORMALIZATION_AMENDMENT_VALIDATED"
            if not errors
            else "FAIL_V1_3_ATOM_IDENTITY_NORMALIZATION_AMENDMENT_INVALID"
        ),
        "valid": not errors,
        "amendment": str(args.amendment.resolve()),
        "amendment_sha256": observed_hash,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
