#!/usr/bin/env python3
"""Validate the frozen V1.3 ATOM/OXT plus zero-heavy-HETATM amendment v2."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

try:
    from experiments.phase2_5080_v1.src import (
        validate_phase2_v3_p2_v1_3_atom_identity_normalization_amendment as v1_validator,
    )
except ModuleNotFoundError:  # pragma: no cover - direct execution from src/
    import validate_phase2_v3_p2_v1_3_atom_identity_normalization_amendment as v1_validator


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
DEFAULT_AMENDMENT = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_atom_identity_normalization_amendment_v2.json"
)
FROZEN_AMENDMENT_SHA256 = "4a59c7dde89a63f717a79208b71ced8753aa50c4da7551f7abc70ba66e179c00"
FROZEN_V1_AMENDMENT_SHA256 = "daf5c628e424c185c9d33c13b90bdf8d875261a990cbbd04a07b48e272d5df23"
FROZEN_V1_RELPATH = (
    "experiments/phase2_5080_v1/audits/"
    "phase2_v3_p2_v1_3_atom_identity_normalization_amendment.json"
)
HETATM_AUDIT_ROLE = "544_pose_machine_readable_atom_hetatm_addendum_evidence"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_artifact(raw: str, data_root: Path = DATA_ROOT) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe amendment artifact path: {raw!r}")
    root = data_root.resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Amendment artifact escapes data root: {raw!r}") from error
    return resolved


def validate_audit_payload(audit: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {
        "schema_version": "phase2_v3_p2_v1_3_atom_hetatm_identity_addendum_audit_v1",
        "status": "PASS_V1_3_ATOM_OXT_AND_HETATM_ZERO_EVIDENCE",
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "selector_or_scoring_performed": False,
        "normalization_activated": False,
    }
    for field, value in expected.items():
        if audit.get(field) != value:
            errors.append(f"audit_{field}_mismatch")

    acceptance = audit.get("acceptance", {})
    for field in (
        "all_512_targeted_exact_reuse_poses_covered",
        "all_heavy_hetatm_counts_zero",
        "all_heavy_hetatm_raw_identities_exact",
        "all_non_terminal_oxt_atom_identities_exact",
        "all_residue_identities_exact",
        "boundary4_complete_and_hash_closed",
        "total_544_pose_closure",
    ):
        if acceptance.get(field) is not True:
            errors.append(f"audit_acceptance_{field}_mismatch")

    summary = audit.get("summary", {})
    if summary.get("run_count") != 68:
        errors.append("audit_run_count_mismatch")
    if summary.get("pose_count") != 544:
        errors.append("audit_pose_count_mismatch")
    if summary.get("pose_counts_by_receptor") != {"8X6B": 272, "9E6Y": 272}:
        errors.append("audit_receptor_pose_counts_mismatch")

    chains = summary.get("chains", {})
    for chain, raw_atom_exact in (("A", 0), ("B", 544)):
        chain_summary = chains.get(chain, {})
        expected_chain = {
            "comparison_count": 544,
            "residue_identity_exact_count": 544,
            "atom_identity_exact_count": raw_atom_exact,
            "terminal_oxt_normalized_atom_identity_exact_count": 544,
            "non_oxt_difference_count": 0,
            "residue_difference_count": 0,
        }
        for field, value in expected_chain.items():
            if chain_summary.get(field) != value:
                errors.append(f"audit_chain_{chain}_{field}_mismatch")
        hetatm = chain_summary.get("heavy_hetatm", {})
        expected_hetatm = {
            "reference_identity_count_total": 0,
            "pose_identity_count_total": 0,
            "reference_nonzero_comparison_count": 0,
            "pose_nonzero_comparison_count": 0,
            "raw_identity_exact_count": 544,
            "missing_identity_count": 0,
            "extra_identity_count": 0,
        }
        for field, value in expected_hetatm.items():
            if hetatm.get(field) != value:
                errors.append(f"audit_chain_{chain}_heavy_hetatm_{field}_mismatch")

    by_receptor = summary.get("chains_by_receptor", {})
    for receptor in ("8X6B", "9E6Y"):
        for chain in ("A", "B"):
            row = by_receptor.get(receptor, {}).get(chain, {})
            expected_row = {
                "comparison_count": 272,
                "heavy_hetatm_reference_identity_count_total": 0,
                "heavy_hetatm_pose_identity_count_total": 0,
                "heavy_hetatm_reference_nonzero_comparison_count": 0,
                "heavy_hetatm_pose_nonzero_comparison_count": 0,
                "heavy_hetatm_raw_identity_exact_count": 272,
                "heavy_hetatm_missing_identity_count": 0,
                "heavy_hetatm_extra_identity_count": 0,
            }
            for field, value in expected_row.items():
                if row.get(field) != value:
                    errors.append(
                        f"audit_receptor_{receptor}_chain_{chain}_{field}_mismatch"
                    )

    proposed = audit.get("proposed_rule", {})
    if proposed.get("oxt_normalization_record_scope") != "ATOM_only_never_HETATM":
        errors.append("audit_oxt_record_scope_mismatch")
    if (
        proposed.get("heavy_hetatm_policy")
        != "require_zero_on_reference_and_pose_chains_A_and_B"
    ):
        errors.append("audit_heavy_hetatm_policy_mismatch")
    return errors


def validate_artifacts(
    payload: Mapping[str, Any], data_root: Path
) -> tuple[list[str], dict[str, Mapping[str, Any]]]:
    errors: list[str] = []
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 5:
        return ["artifacts_count_mismatch"], {}

    expected_roles = {
        "superseded_frozen_v1_amendment",
        HETATM_AUDIT_ROLE,
        "chinese_atom_hetatm_addendum_report",
        "atom_hetatm_addendum_audit_implementation",
        "atom_hetatm_addendum_adversarial_unit_evidence",
    }
    by_role: dict[str, Mapping[str, Any]] = {}
    seen_paths: set[str] = set()
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            errors.append(f"artifact_{index}_not_object")
            continue
        raw_path = str(item.get("path", ""))
        role = str(item.get("role", ""))
        expected_hash = str(item.get("sha256", ""))
        expected_bytes = item.get("bytes")
        if not raw_path or raw_path in seen_paths:
            errors.append(f"artifact_{index}_path_missing_or_duplicate")
            continue
        seen_paths.add(raw_path)
        if not role or role in by_role:
            errors.append(f"artifact_{index}_role_missing_or_duplicate")
        else:
            by_role[role] = item
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
    if set(by_role) != expected_roles:
        errors.append("artifact_roles_mismatch")
    return errors, by_role


def validate_payload(payload: dict[str, Any], data_root: Path = DATA_ROOT) -> list[str]:
    errors: list[str] = []
    expected = {
        "schema_version": "phase2_v3_p2_v1_3_atom_identity_normalization_amendment_v2",
        "protocol_id": "DG_A_PVRIG_V1_3_DUAL47_COMPLETION15",
        "status": "FROZEN_V1_3_TERMINAL_OXT_AND_ZERO_HEAVY_HETATM_AMENDMENT_V2",
        "claim_boundary": (
            "coordinate-identity comparison gates only; no coordinate, source or "
            "decompressed coordinate hash, docking score, rank, pose selection, geometry, "
            "binding, affinity, blocking, formal Gold, P2 readiness, or training-label change"
        ),
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            errors.append(f"{field}_mismatch")

    supersedes = payload.get("supersedes", {})
    supersedes_expected = {
        "path": FROZEN_V1_RELPATH,
        "sha256": FROZEN_V1_AMENDMENT_SHA256,
        "schema_version": "phase2_v3_p2_v1_3_atom_identity_normalization_amendment_v1",
        "status": "FROZEN_V1_3_TERMINAL_OXT_NORMALIZATION_AMENDMENT",
        "history_rewritten": False,
    }
    for field, value in supersedes_expected.items():
        if supersedes.get(field) != value:
            errors.append(f"supersedes_{field}_mismatch")

    scope = payload.get("evidence_scope", {})
    scope_expected = {
        "exact_reuse_run_count": 64,
        "exact_reuse_pose_count": 512,
        "boundary_run_count": 4,
        "boundary_pose_count": 32,
        "total_run_count": 68,
        "total_pose_count": 544,
        "receptor_pose_counts": {"8X6B": 272, "9E6Y": 272},
        "vhh_chain_a_residue_exact_count": 544,
        "vhh_chain_a_raw_atom_exact_count": 0,
        "vhh_chain_a_terminal_oxt_normalized_exact_count": 544,
        "vhh_chain_a_non_oxt_difference_count": 0,
        "pvrig_chain_b_residue_exact_count": 544,
        "pvrig_chain_b_raw_atom_exact_count": 544,
        "pvrig_chain_b_difference_count": 0,
        "vhh_chain_a_reference_heavy_hetatm_identity_count_total": 0,
        "vhh_chain_a_pose_heavy_hetatm_identity_count_total": 0,
        "vhh_chain_a_heavy_hetatm_raw_exact_count": 544,
        "vhh_chain_a_heavy_hetatm_missing_identity_count": 0,
        "vhh_chain_a_heavy_hetatm_extra_identity_count": 0,
        "pvrig_chain_b_reference_heavy_hetatm_identity_count_total": 0,
        "pvrig_chain_b_pose_heavy_hetatm_identity_count_total": 0,
        "pvrig_chain_b_heavy_hetatm_raw_exact_count": 544,
        "pvrig_chain_b_heavy_hetatm_missing_identity_count": 0,
        "pvrig_chain_b_heavy_hetatm_extra_identity_count": 0,
        "exact_reuse64_remote_inventory_hash_chain": (
            "7944c79dda27401b6e637d6d9611578a3b862b693a8f76e7018f7ff8bc8cf285"
        ),
        "boundary4_remote_inventory_hash_chain": (
            "580590a1d55f6f684ecb732dcd3112250d921a016864f146040ee0334d0a1819"
        ),
    }
    for field, value in scope_expected.items():
        if scope.get(field) != value:
            errors.append(f"evidence_scope_{field}_mismatch")

    try:
        v1_path = resolve_artifact(FROZEN_V1_RELPATH, data_root)
        v1_payload = json.loads(v1_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"superseded_v1_unreadable:{error}")
        v1_payload = {}
    else:
        if sha256_file(v1_path) != FROZEN_V1_AMENDMENT_SHA256:
            errors.append("superseded_v1_hash_mismatch")
        if v1_validator.validate_payload(v1_payload, data_root):
            errors.append("superseded_v1_validator_failed")

    if payload.get("normalization_rule") != v1_payload.get("normalization_rule"):
        errors.append("normalization_rule_not_identical_to_v1")
    if payload.get("receptor_rule") != v1_payload.get("receptor_rule"):
        errors.append("receptor_rule_not_identical_to_v1")

    heavy_hetatm = payload.get("heavy_hetatm_rule", {})
    heavy_hetatm_expected = {
        "rule_id": "CHAIN_A_B_ZERO_HEAVY_HETATM_V1",
        "applicable_chains": ["A", "B"],
        "reference_roles": ["frozen_vhh_monomer", "frozen_pvrig_receptor"],
        "pose_role": "native_haddock_4_emref_pose",
        "record_scope": "HETATM_heavy_atoms_only",
        "identity_key": [
            "resseq", "icode", "resname", "atom_name", "altloc", "element"
        ],
        "identity_normalization": "none",
        "terminal_oxt_normalization_applies": False,
        "reference_heavy_hetatm_identity_count_must_equal": 0,
        "pose_heavy_hetatm_identity_count_must_equal": 0,
        "raw_reference_pose_identity_must_match": True,
        "any_heavy_hetatm_identity": "fail_closed",
    }
    for field, value in heavy_hetatm_expected.items():
        if heavy_hetatm.get(field) != value:
            errors.append(f"heavy_hetatm_rule_{field}_mismatch")

    effects = payload.get("side_effect_contract", {})
    for field in (
        "coordinate_bytes_modified",
        "atom_records_modified",
        "hetatm_records_modified",
        "source_pose_hash_modified",
        "decompressed_coordinate_hash_modified",
        "haddock_score_modified",
        "native_rank_modified",
        "pose_selection_modified",
        "geometry_metric_modified",
    ):
        if effects.get(field) is not False:
            errors.append(f"side_effect_{field}_mismatch")
    for field in (
        "normalization_used_only_for_atom_identity_gate",
        "heavy_hetatm_rule_used_only_for_identity_gate",
    ):
        if effects.get(field) is not True:
            errors.append(f"side_effect_{field}_mismatch")

    eligibility = payload.get("eligibility", {})
    if eligibility.get("development_identity_gate_use_permitted") is not True:
        errors.append("eligibility_development_identity_gate_use_permitted_mismatch")
    for field in (
        "formal_eligible",
        "training_label_release_eligible",
        "docking_gold_release_eligible",
        "p2_training_ready",
    ):
        if eligibility.get(field) is not False:
            errors.append(f"eligibility_{field}_mismatch")

    activation = payload.get("selector_activation_contract", {})
    for field in (
        "hard_bound_amendment_v2_sha256_required",
        "hard_bound_superseded_v1_sha256_required",
        "both_amendment_validators_must_pass",
        "silent_rule_expansion_forbidden",
        "future_rule_change_requires_new_amendment",
    ):
        if activation.get(field) is not True:
            errors.append(f"selector_activation_{field}_mismatch")

    artifact_errors, by_role = validate_artifacts(payload, data_root)
    errors.extend(artifact_errors)
    v1_item = by_role.get("superseded_frozen_v1_amendment", {})
    if (
        v1_item.get("path") != supersedes.get("path")
        or v1_item.get("sha256") != supersedes.get("sha256")
    ):
        errors.append("supersedes_artifact_binding_mismatch")

    audit_item = by_role.get(HETATM_AUDIT_ROLE)
    if audit_item is None:
        return errors + ["audit_artifact_binding_mismatch"]
    try:
        audit = json.loads(
            resolve_artifact(str(audit_item["path"]), data_root).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return errors + [f"audit_unreadable:{error}"]
    errors.extend(validate_audit_payload(audit))

    implementation_item = by_role.get("atom_hetatm_addendum_audit_implementation", {})
    implementation = audit.get("implementation", {})
    implementation_artifact_path = str(implementation_item.get("path", ""))
    if (
        implementation.get("relpath") != f"data/{implementation_artifact_path}"
        or implementation.get("sha256") != implementation_item.get("sha256")
    ):
        errors.append("audit_implementation_artifact_binding_mismatch")
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
            "PASS_V1_3_ATOM_HETATM_IDENTITY_AMENDMENT_V2_VALIDATED"
            if not errors
            else "FAIL_V1_3_ATOM_HETATM_IDENTITY_AMENDMENT_V2_INVALID"
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
