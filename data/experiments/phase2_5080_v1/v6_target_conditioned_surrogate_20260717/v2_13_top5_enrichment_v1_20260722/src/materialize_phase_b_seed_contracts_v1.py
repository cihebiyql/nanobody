#!/usr/bin/env python3
"""Materialize immutable seed917/1931 fold contracts after blind Phase-A selection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "pvrig_v2_13_phase_b_seed_contract_materialization_v1"
SEEDS = (917, 1931)
FOLDS = tuple(range(5))


class MaterializationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializationError(message)


def sha256_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"regular_file_required:{path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(promotion_contract: Path, selection_path: Path, source_contracts: Path, output_dir: Path) -> dict[str, Any]:
    require(not output_dir.exists(), "output_exists")
    promotion = json.loads(promotion_contract.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    require(promotion.get("schema_version") == "pvrig_v2_13_phase_b_promotion_contract_v1", "promotion_schema")
    require(promotion.get("status") == "FROZEN_RESULT_BLIND_DURING_PHASE_A_TRAINING", "promotion_status")
    require(selection.get("status") == "PASS_PHASE_A_VARIANT_PROMOTED", "selection_not_promoted")
    require(selection.get("selected_variant") in {"L1", "L2", "L3"}, "selection_variant")
    require(selection.get("input_access") == {"open_development_rows": 0, "frozen_test_rows": 0}, "selection_access")
    output_dir.mkdir(parents=True)
    outputs: dict[str, Any] = {}
    for seed in SEEDS:
        for fold in FOLDS:
            source_path = source_contracts / f"fold_{fold}_contract.json"
            source = json.loads(source_path.read_text(encoding="utf-8"))
            require(source.get("schema_version") == "pvrig_v2_12_clean_attention_inner_oof_fold_contract_v1", f"source_schema:{fold}")
            require(source.get("status") == "FROZEN_INNER_OOF_PRE_LAUNCH", f"source_status:{fold}")
            require(source.get("task") == {"fold_id": fold, "seed": 43}, f"source_task:{fold}")
            payload = json.loads(json.dumps(source))
            payload["task"] = {"fold_id": fold, "seed": seed}
            payload["phase_b_provenance"] = {
                "selected_variant": selection["selected_variant"],
                "source_contract_sha256": sha256_file(source_path),
                "selection_sha256": sha256_file(selection_path),
                "promotion_contract_sha256": sha256_file(promotion_contract),
                "seed43_reused_not_retrained": True,
            }
            name = f"seed_{seed}_fold_{fold}_contract.json"
            path = output_dir / name
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            outputs[name] = sha256_file(path)
    receipt = {
        "schema_version": SCHEMA,
        "status": "PASS_PHASE_B_SEED_CONTRACTS_MATERIALIZED",
        "selected_variant": selection["selected_variant"],
        "counts": {"seeds": len(SEEDS), "folds_per_seed": len(FOLDS), "contracts": len(SEEDS) * len(FOLDS)},
        "seeds": list(SEEDS),
        "outputs": outputs,
        "inputs": {"promotion_contract_sha256": sha256_file(promotion_contract), "selection_sha256": sha256_file(selection_path)},
        "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
    }
    receipt_path = output_dir / "MATERIALIZATION_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promotion-contract", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--source-contracts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = materialize(args.promotion_contract, args.selection, args.source_contracts, args.output_dir)
    print(json.dumps({"status": result["status"], "selected_variant": result["selected_variant"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
