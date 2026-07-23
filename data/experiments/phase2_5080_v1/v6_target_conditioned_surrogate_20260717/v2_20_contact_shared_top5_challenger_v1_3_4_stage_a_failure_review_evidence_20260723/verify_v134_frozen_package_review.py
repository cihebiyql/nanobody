#!/usr/bin/env python3
"""Independent, read-only verification of the frozen V2.20 V1.3.4 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


CORE = (
    "launchers/run_shared_fold_materialization_once_v1_3_1.sh",
    "src/materialize_v220_shared_fold_calibration_v1_3_1.py",
    "src/run_v220_contact_shared_fold_v1_3_1.py",
    "src/v220_shared_calibration_artifact_v1.py",
    "src/validate_v220_shared_fold_calibration_load_only_v1_3_1.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular_files(root: Path) -> set[str]:
    observed: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise AssertionError(f"symlink_in_frozen_package:{path.relative_to(root)}")
        if path.is_file():
            observed.add(path.relative_to(root).as_posix())
    return observed


def normalize_version(text: str) -> str:
    return (
        text.replace("V1_3_3", "V1_3_4")
        .replace("v1_3_3", "v1_3_4")
        .replace("V1.3.3", "V1.3.4")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1-3-1", type=Path, required=True)
    parser.add_argument("--v1-3-3", type=Path, required=True)
    parser.add_argument("--v1-3-4", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    p31, p33, p34 = (p.resolve(strict=True) for p in (args.v1_3_1, args.v1_3_3, args.v1_3_4))
    freeze_path = p34 / "IMPLEMENTATION_FREEZE_PHASE1_TECHNICAL_RECOVERY_V1_3_4.json"
    sidecar_path = freeze_path.with_suffix(freeze_path.suffix + ".sha256")
    freeze_sha = sha(freeze_path)
    freeze = json.loads(freeze_path.read_text())
    expected_sidecar = f"{freeze_sha}  {freeze_path.name}\n"
    assert sidecar_path.read_text() == expected_sidecar
    observed = regular_files(p34)
    expected = set(freeze["package_file_allowlist"])
    assert observed == expected, (sorted(observed - expected), sorted(expected - observed))
    assert set(freeze["implementation_hashes"]) == expected - {
        freeze_path.name,
        sidecar_path.name,
    }
    for relative, expected_sha in freeze["implementation_hashes"].items():
        assert sha(p34 / relative) == expected_sha, relative

    core: dict[str, object] = {}
    for relative in CORE:
        digests = {
            "v1_3_1": sha(p31 / relative),
            "v1_3_3": sha(p33 / relative),
            "v1_3_4": sha(p34 / relative),
        }
        assert len(set(digests.values())) == 1, relative
        core[relative] = {"byte_identical": True, "sha256": digests["v1_3_4"]}

    old_template = (p33 / "launchers/run_phase1_core_fold_pair_node1_v1_3_3.template.sh").read_text()
    new_template = (p34 / "launchers/run_phase1_core_fold_pair_node1_v1_3_4.template.sh").read_text()
    template_scientific_semantics_unchanged = normalize_version(old_template) == new_template
    assert template_scientific_semantics_unchanged

    preflight = p34 / "launchers/run_phase1_preflight_node1_v1_3_4.sh"
    preflight_text = preflight.read_text()
    legacy_launcher = p34 / "launchers/run_legacy_102_tests_python311_v1_3_4.sh"
    match = re.search(r'^EXPECTED_LEGACY_TEST_LAUNCHER_SHA="([0-9a-f]{64})"$', preflight_text, re.M)
    assert match
    bound_legacy_sha = match.group(1)
    actual_legacy_sha = sha(legacy_launcher)

    builder = p34 / "src/build_v220_v1_3_4_preflight_receipt.py"
    builder_text = builder.read_text()
    parser_flag = "--v1-3-3-test-log"
    build_attribute = "args.v1_3_4_test_log"
    parser_destination = "v1_3_3_test_log"
    assert parser_flag in builder_text
    assert build_attribute in builder_text
    assert parser_destination not in builder_text

    payload = {
        "schema_version": "pvrig.v220.v1_3_4.independent_static_review.v1",
        "status": "FAIL_V1_3_4_STAGE_A_DEPLOYMENT_NOT_AUTHORIZED",
        "freeze": {
            "path": str(freeze_path),
            "sha256": freeze_sha,
            "sidecar_exact": True,
            "package_allowlist_exact": True,
            "all_implementation_hashes_exact": True,
        },
        "scientific_semantics": {
            "five_core_files": core,
            "training_template_equal_after_version_only_normalization": True,
            "data_model_split_loss_optimizer_threshold_hyperparameters_changed": False,
        },
        "blocking_findings": [
            {
                "id": "V134_PREFLIGHT_LEGACY_LAUNCHER_HASH_STALE",
                "path": str(preflight),
                "bound_sha256": bound_legacy_sha,
                "actual_sha256": actual_legacy_sha,
                "deterministic_effect": "sha256sum gate fails before Stage-A materialization",
            },
            {
                "id": "V134_PREFLIGHT_RECEIPT_ARGPARSE_DEST_MISMATCH",
                "path": str(builder),
                "parser_flag": parser_flag,
                "parser_destination": parser_destination,
                "build_reads": build_attribute,
                "deterministic_effect": "AttributeError if the receipt builder CLI is reached",
            },
        ],
        "test_coverage_gap": {
            "frozen_new44_did_not_assert_bound_legacy_launcher_hash_equals_file": True,
            "frozen_new44_constructed_argparse_namespace_directly_and_did_not_test_cli_destination": True,
        },
        "authorization": {
            "stage_a_approved": False,
            "deployment_authorized": False,
            "training_authorized": False,
            "training_started": False,
            "same_version_repair_or_retry_allowed": False,
            "required_action": "supersede with a new version; do not edit, deploy, or train V1.3.4",
        },
    }
    assert bound_legacy_sha != actual_legacy_sha
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": payload["status"], "output_sha256": sha(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
