#!/usr/bin/env python3
"""Freeze completed lab-specific assay parameters before any measurements exist."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from analyze_pvrig_v2_5_assay_results import (
    DEFAULT_PACKAGE_DIR,
    PACKAGE_VERSION,
    AssayContractError,
    clean,
    sha256_file,
)

RESULT_CALL_COLUMNS = {
    "expression_qc_results.csv": "scientist_qc_call",
    "binding_results.csv": "scientist_binding_call",
    "competition_results.csv": "scientist_blocking_call",
    "functional_results.csv": "scientist_functional_call",
}

NUMERIC_PARAMETERS = {
    "minimum_expression_yield_mg_per_l",
    "minimum_purity_fraction",
    "minimum_sec_monomer_fraction",
    "maximum_aggregation_fraction",
    "binding_max_analyte_concentration_nM",
    "competition_max_analyte_concentration_nM",
    "functional_max_analyte_concentration_nM",
    "minimum_functional_viability_fraction",
}

FRACTION_PARAMETERS = {
    "minimum_purity_fraction",
    "minimum_sec_monomer_fraction",
    "maximum_aggregation_fraction",
    "minimum_functional_viability_fraction",
}

TEXT_PARAMETERS = {
    "binding_response_detection_rule",
    "binding_fit_qc_rule",
    "competition_effect_rule",
    "functional_effect_rule",
    "functional_viability_rule",
}

REQUIRED_PARAMETERS = NUMERIC_PARAMETERS | TEXT_PARAMETERS


def validate_no_measurements(package_dir: Path, manifest: dict[str, object]) -> None:
    initial_hashes = manifest.get("mutable_templates_initial_sha256")
    if not isinstance(initial_hashes, dict):
        raise AssayContractError("Package manifest lacks initial result-template hashes")
    for filename, call_column in RESULT_CALL_COLUMNS.items():
        path = package_dir / filename
        if not path.is_file():
            raise AssayContractError(f"Missing result template: {path}")
        frame = pd.read_csv(path, keep_default_na=False, dtype=str)
        if call_column not in frame.columns:
            raise AssayContractError(f"{filename} is missing {call_column}")
        completed = frame[call_column].astype(str).str.strip().str.upper().ne("PENDING")
        if completed.any():
            raise AssayContractError("Preregistration cannot be frozen after any result call was entered")
        expected_hash = initial_hashes.get(filename)
        if not expected_hash or sha256_file(path) != expected_hash:
            raise AssayContractError(f"Result template changed before preregistration freeze: {filename}")


def validate_parameters(parameters: object) -> dict[str, object]:
    if not isinstance(parameters, dict) or not parameters:
        raise AssayContractError("Preregistration has no lab-specific parameters")
    missing_keys = sorted(REQUIRED_PARAMETERS - set(parameters))
    if missing_keys:
        raise AssayContractError(f"Lab-specific preregistration parameters are missing: {missing_keys}")
    missing = sorted(name for name in REQUIRED_PARAMETERS if parameters[name] is None or not clean(parameters[name]))
    if missing:
        raise AssayContractError(f"Lab-specific preregistration parameters are incomplete: {missing}")
    for name in NUMERIC_PARAMETERS:
        if name not in parameters:
            raise AssayContractError(f"Missing required numeric preregistration parameter: {name}")
        try:
            value = float(parameters[name])
        except (TypeError, ValueError) as exc:
            raise AssayContractError(f"Preregistration parameter {name} must be numeric") from exc
        if not math.isfinite(value) or value < 0:
            raise AssayContractError(f"Preregistration parameter {name} must be finite and non-negative")
        if name in FRACTION_PARAMETERS and not 0 <= value <= 1:
            raise AssayContractError(f"Preregistration fraction {name} must be in [0, 1]")
    if float(parameters["binding_max_analyte_concentration_nM"]) <= 0:
        raise AssayContractError("Binding maximum analyte concentration must be positive")
    if float(parameters["competition_max_analyte_concentration_nM"]) <= 0:
        raise AssayContractError("Competition maximum analyte concentration must be positive")
    if float(parameters["functional_max_analyte_concentration_nM"]) <= 0:
        raise AssayContractError("Functional maximum analyte concentration must be positive")
    return parameters


def freeze(package_dir: Path) -> dict[str, object]:
    manifest_path = package_dir / "package_manifest.json"
    prereg_path = package_dir / "assay_preregistration.json"
    if not manifest_path.is_file() or not prereg_path.is_file():
        raise AssayContractError("Package manifest and assay preregistration must both exist")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    if manifest.get("package_version") != PACKAGE_VERSION or prereg.get("package_version") != PACKAGE_VERSION:
        raise AssayContractError("Package/preregistration version mismatch")
    if manifest.get("preregistration_frozen"):
        current = sha256_file(prereg_path)
        expected = manifest.get("frozen_artifacts", {}).get(prereg_path.name)
        if current != expected:
            raise AssayContractError("Frozen preregistration changed; create a new package version")
        return manifest

    frozen = manifest.get("frozen_artifacts")
    if not isinstance(frozen, dict):
        raise AssayContractError("Package manifest does not contain frozen artifact hashes")
    for filename, expected in frozen.items():
        if filename == prereg_path.name:
            continue
        path = package_dir / filename
        if not path.is_file() or sha256_file(path) != expected:
            raise AssayContractError(f"Frozen package artifact changed before preregistration: {filename}")

    validate_no_measurements(package_dir, manifest)
    validate_parameters(prereg.get("lab_parameters_to_freeze_before_first_measurement"))
    previous_hash = clean(frozen.get(prereg_path.name))
    current_hash = sha256_file(prereg_path)
    manifest["artifacts"][prereg_path.name] = current_hash
    manifest["frozen_artifacts"][prereg_path.name] = current_hash
    manifest["preregistration_frozen"] = True
    manifest["preregistration_freeze"] = {
        "previous_template_sha256": previous_hash,
        "frozen_sha256": current_hash,
        "rule": "frozen_before_any_non_pending_result_call",
    }
    manifest["status"] = "READY_FOR_MEASUREMENT"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii")
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = freeze(args.package_dir)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
