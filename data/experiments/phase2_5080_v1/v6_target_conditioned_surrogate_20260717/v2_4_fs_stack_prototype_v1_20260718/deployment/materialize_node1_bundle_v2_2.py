#!/usr/bin/env python3
"""Stage the superseding V2.2 claim-aligned adaptive-multiseed Node1 bundle."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import node1_v2_4_outer_development_launcher_v2_2 as deployment  # noqa: E402


PENDING_STATUS = "PREFREEZE_V2_2_ADAPTIVE_MULTI_SEED_CALIBRATION_PENDING_DO_NOT_START"
MANIFEST_NAME = "V2_4_NODE1_PREFREEZE_MANIFEST_V2_2.json"


def materialize(manifest_path: pathlib.Path, readme_path: pathlib.Path, output_root: pathlib.Path) -> dict[str, Any]:
    manifest = deployment.load_manifest(manifest_path, allow_pending_calibration=True)
    deployment.require(manifest["status"] == PENDING_STATUS, "bundle_requires_v2_pending_prefreeze_manifest")
    deployment.validate_local_sources(manifest)
    deployment.validate_training_contract(manifest, use_source=True)
    deployment.require(not os.path.lexists(output_root), f"bundle_output_exists:{output_root}")
    deployment.require(readme_path.is_file() and not readme_path.is_symlink(), "bundle_readme_missing_or_symlink")
    bundle_root = pathlib.Path(manifest["bundle_root"])
    output_root.mkdir(parents=True)
    copied: dict[str, dict[str, Any]] = {}
    for label, record in sorted(manifest["artifacts"].items()):
        if record["validation_mode"] != "LOCAL_SOURCE_AND_NODE1":
            continue
        node1_path = pathlib.Path(record["node1_path"])
        try:
            relative = node1_path.relative_to(bundle_root)
        except ValueError:
            continue
        source = pathlib.Path(record["source_path"])
        destination = output_root / relative
        deployment.require(not os.path.lexists(destination), f"bundle_destination_exists:{label}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o644)
        digest = deployment.sha256_file(destination)
        deployment.require(digest == record["sha256"], f"bundle_copy_sha:{label}")
        copied[label] = {
            "relative_path": relative.as_posix(),
            "sha256": digest,
            "size_bytes": destination.stat().st_size,
        }
    required = {
        "training_tsv", "training_receipt", "trainer", "model", "calibration_trainer",
        "calibration_runner", "deployment_launcher", "postcalibration_materializer",
        "bundle_materializer", "v2_2_supersession_audit",
        "contact_formula", "adaptive_input_contract", "adaptive_marginal_tsv_gz",
        "adaptive_pair_tsv_gz",
    }
    deployment.require(required <= set(copied), "bundle_v2_core_artifact_closure")
    manifest_destination = output_root / MANIFEST_NAME
    shutil.copyfile(manifest_path, manifest_destination)
    manifest_destination.chmod(0o644)
    readme_destination = output_root / "README_ZH.md"
    shutil.copyfile(readme_path, readme_destination)
    readme_destination.chmod(0o644)
    sum_entries = [
        f"{deployment.sha256_file(path)}  {path.relative_to(output_root).as_posix()}"
        for path in sorted(value for value in output_root.rglob("*") if value.is_file())
    ]
    sums_path = output_root / "SHA256SUMS"
    sums_path.write_text("\n".join(sum_entries) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": "pvrig_v6_residue_v2_4_node1_staged_bundle_v2_2_adaptive_multiseed_multibatch_claim_aligned",
        "status": "PASS_NODE1_BUNDLE_V2_2_STAGED_CALIBRATION_PENDING_DO_NOT_EXECUTE_OUTER",
        "production_authorized": False,
        "deployed_to_node1": False,
        "calibration_started": False,
        "optimizer_constructed": False,
        "outer_metrics_access_count": 0,
        "v4_f_access_count": 0,
        "manifest_sha256": deployment.sha256_file(manifest_destination),
        "readme_sha256": deployment.sha256_file(readme_destination),
        "sha256sums_sha256": deployment.sha256_file(sums_path),
        "staged_artifact_count": len(copied),
        "staged_artifacts": copied,
        "inherited_node1_artifacts_not_copied": sorted(
            label for label, record in manifest["artifacts"].items()
            if not pathlib.Path(record["node1_path"]).is_relative_to(bundle_root)
        ),
        "adaptive_input_contract_sha256": manifest["adaptive_supervision"]["input_contract_sha256"],
        "calibration_batch_contract_sha256": manifest["calibration_contract"]["batch_selection"]["contract_sha256"],
        "next_permitted_action": (
            "Deploy to the exact V2 bundle_root, validate all Node1 artifacts, then run the "
            "open-only pre-optimizer-step calibration; do not start smoke or outer training."
        ),
    }
    receipt_path = output_root / "BUNDLE_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": receipt["status"],
        "output": str(output_root),
        "receipt_sha256": deployment.sha256_file(receipt_path),
        "staged_artifact_count": len(copied),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    parser.add_argument("--readme", type=pathlib.Path, required=True)
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    args = parser.parse_args()
    print(json.dumps(materialize(args.manifest, args.readme, args.output_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (deployment.DeploymentError, OSError, json.JSONDecodeError) as error:
        print(f"FAIL_V2_4_BUNDLE_V2_2_MATERIALIZATION:{error}", file=os.sys.stderr)
        raise SystemExit(1)
