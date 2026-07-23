#!/usr/bin/env python3
"""Validate causal pairing of the five V2.20 C0/C1 outer-fold runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "pvrig.v220.paired_folds_validation.v1"
FOLDS = tuple(range(5))
OUTPUT_NAMES = (
    "fold_predictions.tsv",
    "fold_checkpoint.pt",
    "epoch_history.json",
    "CONTACT_WEIGHT_CALIBRATION.json",
)


class PairValidationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PairValidationError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"file_invalid:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_result(root: Path, arm: str, fold_id: int) -> tuple[dict[str, Any], str]:
    path = root / f"fold_{fold_id}" / "RESULT.json"
    require(path.is_file() and not path.is_symlink(), f"result_invalid:{arm}:{fold_id}")
    raw = path.read_bytes()
    try:
        result = json.loads(raw)
    except Exception as error:
        raise PairValidationError(f"result_json:{arm}:{fold_id}") from error
    require(result.get("status") == f"PASS_V220_{arm}_CONTACT_SHARED_FOLD", f"status:{arm}:{fold_id}")
    require(result.get("arm") == arm and int(result.get("fold_id", -1)) == fold_id, f"identity:{arm}:{fold_id}")
    require(int(result.get("seed", -1)) == 43, f"seed:{arm}:{fold_id}")
    outputs = result.get("outputs") or {}
    for name in OUTPUT_NAMES:
        output_path = root / f"fold_{fold_id}" / name
        require(outputs.get(name) == sha256_file(output_path), f"output_hash:{arm}:{fold_id}:{name}")
    return result, hashlib.sha256(raw).hexdigest()


def validate_pair(c0_root: Path, c1_root: Path) -> dict[str, Any]:
    fold_receipts: list[dict[str, Any]] = []
    initial_serialized: set[str] = set()
    for fold_id in FOLDS:
        c0, c0_hash = read_result(c0_root, "C0", fold_id)
        c1, c1_hash = read_result(c1_root, "C1", fold_id)
        for arm, result in (("C0", c0), ("C1", c1)):
            require(int((result.get("split") or {}).get("whole_parent_overlap", -1)) == 0, f"parent_overlap:{arm}:{fold_id}")
            firewall = result.get("neural_input_firewall") or {}
            require(int(firewall.get("outer_score_contact_numeric_reads", -1)) == 0, f"score_contact_access:{arm}:{fold_id}")
            require(firewall.get("contact_labels_forwarded") is False, f"contact_forward:{arm}:{fold_id}")
            require(result.get("exact_min_inference") is True, f"exact_min:{arm}:{fold_id}")

        pair0, pair1 = c0.get("pairing") or {}, c1.get("pairing") or {}
        required_pair_fields = (
            "initial_state_hashes",
            "serialized_initial_state_sha256",
            "optimizer_group_sha256",
            "epoch_batch_order_sha256",
            "serialized_initial_state_scope",
            "backbone_binding",
        )
        for field in required_pair_fields:
            require(pair0.get(field) == pair1.get(field), f"pairing_mismatch:{fold_id}:{field}")
        require(pair0.get("serialized_initial_state_scope") == "model.head", f"state_scope:{fold_id}")
        backbone = pair0.get("backbone_binding") or {}
        require(backbone.get("serialized_in_checkpoint") is False, f"backbone_serialized:{fold_id}")
        require(
            len(str(backbone.get("artifact_identity_sha256", ""))) == 64,
            f"backbone_identity:{fold_id}",
        )
        require(
            len(str(backbone.get("runtime_state_sha256", ""))) == 64,
            f"backbone_runtime_state:{fold_id}",
        )
        require(
            len(str(backbone.get("state_contract_sha256", ""))) == 64,
            f"backbone_state_contract:{fold_id}",
        )
        initial_serialized.add(str(pair0["serialized_initial_state_sha256"]))

        weights0, weights1 = c0.get("contact_weights") or {}, c1.get("contact_weights") or {}
        require(
            (c0.get("outputs") or {}).get("CONTACT_WEIGHT_CALIBRATION.json")
            == (c1.get("outputs") or {}).get("CONTACT_WEIGHT_CALIBRATION.json"),
            f"calibration_receipt_hash_mismatch:{fold_id}",
        )
        selected0 = float(weights0.get("selected_marginal_weight", -1.0))
        selected1 = float(weights1.get("selected_marginal_weight", -2.0))
        require(selected0 == selected1 and selected0 > 0.0, f"calibration_selected_mismatch:{fold_id}")
        require(float(weights0.get("selected_pair_weight", -1.0)) == 0.5 * selected0, f"c0_selected_pair:{fold_id}")
        require(float(weights1.get("selected_pair_weight", -1.0)) == 0.5 * selected1, f"c1_selected_pair:{fold_id}")
        require(float(weights0.get("applied_marginal_weight", -1.0)) == 0.0, f"c0_applied_marginal:{fold_id}")
        require(float(weights0.get("applied_pair_weight", -1.0)) == 0.0, f"c0_applied_pair:{fold_id}")
        require(float(weights1.get("applied_marginal_weight", -1.0)) == selected1, f"c1_applied_marginal:{fold_id}")
        require(float(weights1.get("applied_pair_weight", -1.0)) == 0.5 * selected1, f"c1_applied_pair:{fold_id}")
        require(c0.get("split") == c1.get("split"), f"split_mismatch:{fold_id}")
        require(c0.get("input_bindings") == c1.get("input_bindings"), f"input_binding_mismatch:{fold_id}")
        fold_receipts.append(
            {
                "fold_id": fold_id,
                "C0_result_sha256": c0_hash,
                "C1_result_sha256": c1_hash,
                "selected_marginal_weight": selected0,
                "initial_state_sha256": pair0["serialized_initial_state_sha256"],
                "optimizer_group_sha256": pair0["optimizer_group_sha256"],
                "epoch_batch_order_sha256": pair0["epoch_batch_order_sha256"],
            }
        )
    require(len(initial_serialized) == 1, "initial_state_not_identical_across_all_folds")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_V220_C0_C1_FIVE_FOLD_CAUSAL_PAIRING",
        "folds": fold_receipts,
        "serialized_initial_state_sha256": next(iter(initial_serialized)),
    }


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c0-root", type=Path, required=True)
    parser.add_argument("--c1-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate_pair(args.c0_root, args.c1_root)
    atomic_json(args.output_json, result)
    print(json.dumps({"status": result["status"], "folds": len(result["folds"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
