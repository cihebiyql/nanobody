#!/usr/bin/env python3
"""Bind formal V3-P checkpoints, predictions, controls, and governance files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Sequence


EXPECTED_SEEDS = (83, 89, 97)
FULL_CONTROLS = {"vhh_only", "hotspot_shuffle", "antigen_ablation", "target_permutation"}
LABEL_CONTROL = {"label_shuffle"}
SCHEMA_VERSION = "phase2_v3_p1_formal_artifact_bundle_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def verify_file(path: Path, expected: str, label: str) -> None:
    observed = sha256_file(path)
    if observed != expected:
        raise ValueError(f"Artifact hash mismatch for {label}: {observed} != {expected}")


def seed_summaries(path: Path, expected_control: str) -> dict[int, dict[str, Any]]:
    summary = load_json(path)
    if summary.get("status") != "PASS_FORMAL_MULTISEED_COMPLETE" or summary.get("control_type") != expected_control:
        raise ValueError(f"Training summary is not a complete {expected_control} run: {path}")
    rows = summary.get("seed_summaries")
    if not isinstance(rows, list) or {int(row["seed"]) for row in rows} != set(EXPECTED_SEEDS):
        raise ValueError(f"Training summary seeds must be exactly {EXPECTED_SEEDS}")
    output = {int(row["seed"]): row for row in rows}
    for seed, row in output.items():
        if row.get("status") != "PASS_FORMAL_TRAINING_COMPLETE" or row.get("control_type") != expected_control:
            raise ValueError(f"Seed {seed} is not a complete {expected_control} run")
        if row.get("formal_governance_preflight", {}).get("status") != "PASS_FORMAL_GOVERNANCE_PREFLIGHT":
            raise ValueError(f"Seed {seed} lacks a passing governance preflight")
        for path_key, hash_key in (
            ("best_checkpoint", "best_checkpoint_sha256"),
            ("test_predictions_path", "test_predictions_sha256"),
            ("dev_predictions_path", "dev_predictions_sha256"),
            ("control_predictions_path", "control_predictions_sha256"),
            ("baseline_registry_path", "baseline_registry_sha256"),
            ("generic_replay_retention_path", "generic_replay_retention_sha256"),
        ):
            verify_file(Path(row[path_key]), str(row[hash_key]), f"{expected_control}:seed{seed}:{path_key}")
    return output


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty bundle CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def build(args: argparse.Namespace) -> dict[str, Any]:
    full = seed_summaries(args.full_training_summary, "full")
    shuffled = seed_summaries(args.label_shuffle_training_summary, "label_shuffle")
    prereg_sha = sha256_file(args.preregistration)
    spec_sha = sha256_file(args.test_spec)
    fingerprints = {row["config_fingerprint"] for row in full.values()}
    shuffled_fingerprints = {row["config_fingerprint"] for row in shuffled.values()}
    if len(fingerprints) != 1 or len(shuffled_fingerprints) != 1:
        raise ValueError("Config fingerprints differ within a multiseed run")
    for row in [*full.values(), *shuffled.values()]:
        if row["preregistration_sha256"] != prereg_sha or row["test_spec_sha256"] != spec_sha:
            raise ValueError("Seed summary governance hashes differ from supplied preregistration/test spec")

    baseline_hashes = {row["baseline_registry_sha256"] for row in full.values()}
    if len(baseline_hashes) != 1:
        raise ValueError("Full-run baseline registries differ across seeds")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline_out = args.output_dir / "baseline_predictions.csv"
    shutil.copyfile(Path(full[83]["baseline_registry_path"]), baseline_out)

    controls: list[dict[str, str]] = []
    for seed, row in full.items():
        source = read_csv(Path(row["control_predictions_path"]))
        if {item["control_type"] for item in source} != FULL_CONTROLS:
            raise ValueError(f"Full seed {seed} has the wrong control types")
        controls.extend(source)
    for seed, row in shuffled.items():
        source = read_csv(Path(row["control_predictions_path"]))
        if {item["control_type"] for item in source} != LABEL_CONTROL:
            raise ValueError(f"Label-shuffle seed {seed} has the wrong control types")
        controls.extend(source)
    control_out = args.output_dir / "control_predictions.csv"
    write_csv(control_out, controls)

    replay_payload = {
        "schema_version": "phase2_v3_p1_generic_replay_retention_v1",
        "per_seed": {str(seed): full[seed]["generic_replay_retention"] for seed in EXPECTED_SEEDS},
    }
    replay_out = args.output_dir / "generic_replay_retention.json"
    atomic_json(replay_out, replay_payload)

    bound_paths = {
        "preregistration": args.preregistration,
        "test_spec": args.test_spec,
        "config": args.config,
        "teacher_open": args.teacher_open,
        "teacher_test_sealed": args.teacher_test_sealed,
        "formal_data_audit": args.formal_data_audit,
        "model_input_validation": args.model_input_validation,
        "full_training_summary": args.full_training_summary,
        "label_shuffle_training_summary": args.label_shuffle_training_summary,
        "trainer_source": args.trainer_source,
        "model_source": args.model_source,
        "evaluator_source": args.evaluator_source,
    }
    bound_files = {name: {"path": str(path), "sha256": sha256_file(path)} for name, path in bound_paths.items()}
    seed_predictions = {
        str(seed): {"path": full[seed]["test_predictions_path"], "sha256": full[seed]["test_predictions_sha256"]}
        for seed in EXPECTED_SEEDS
    }
    checkpoints = {
        str(seed): {"path": full[seed]["best_checkpoint"], "sha256": full[seed]["best_checkpoint_sha256"]}
        for seed in EXPECTED_SEEDS
    }
    label_shuffle_checkpoints = {
        str(seed): {"path": shuffled[seed]["best_checkpoint"], "sha256": shuffled[seed]["best_checkpoint_sha256"]}
        for seed in EXPECTED_SEEDS
    }
    manifest: dict[str, Any] = {
        "status": "PASS_V3_P1_FORMAL_ARTIFACT_BUNDLE_READY",
        "schema_version": SCHEMA_VERSION,
        "expected_seeds": list(EXPECTED_SEEDS),
        "full_config_fingerprint": next(iter(fingerprints)),
        "label_shuffle_config_fingerprint": next(iter(shuffled_fingerprints)),
        "seed_predictions": seed_predictions,
        "checkpoints": checkpoints,
        "label_shuffle_checkpoints": label_shuffle_checkpoints,
        "bound_files": bound_files,
        "bundle_outputs": {
            "baseline_predictions": {"path": str(baseline_out), "sha256": sha256_file(baseline_out)},
            "control_predictions": {"path": str(control_out), "sha256": sha256_file(control_out)},
            "generic_replay_retention": {"path": str(replay_out), "sha256": sha256_file(replay_out)},
        },
        "claim_boundary": "docking_geometry_surrogate_not_binding_or_experimental_blocking_truth",
    }
    manifest_path = args.output_dir / "formal_artifact_manifest.json"
    atomic_json(manifest_path, manifest)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-training-summary", type=Path, required=True)
    parser.add_argument("--label-shuffle-training-summary", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--test-spec", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--teacher-open", type=Path, required=True)
    parser.add_argument("--teacher-test-sealed", type=Path, required=True)
    parser.add_argument("--formal-data-audit", type=Path, required=True)
    parser.add_argument("--model-input-validation", type=Path, required=True)
    parser.add_argument("--trainer-source", type=Path, required=True)
    parser.add_argument("--model-source", type=Path, required=True)
    parser.add_argument("--evaluator-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    print(json.dumps(build(parse_args(argv)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
