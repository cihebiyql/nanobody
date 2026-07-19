#!/usr/bin/env python3
"""Build a fail-closed contract for V2.5 label-free outer contact replay."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "pvrig_v2_5_label_free_contact_export_contract_v1"
LANE = "E_DECOUPLED_CONTACT_SHARED"
SEEDS = (43, 97, 193)
PREDICTION_FIELDS = (
    "candidate_id", "neural_R8", "neural_R9", "neural_Rdual",
    "contact_score_R8", "contact_score_R9",
)


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_sealed_path(path: Path) -> None:
    normalized = str(path).lower().replace("-", "_")
    require("v4_f" not in normalized and "test32" not in normalized, f"sealed_path_forbidden:{path}")


def regular(path: Path, label: str) -> None:
    reject_sealed_path(path)
    require(path.is_file() and not path.is_symlink(), f"{label}_missing_or_symlink:{path}")


def record(path: Path) -> dict[str, Any]:
    regular(path, "contract_input")
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def parse_outer_refit(value: str) -> tuple[int, Path]:
    seed_text, separator, path_text = value.partition(":")
    require(separator == ":" and seed_text and path_text, f"outer_refit_syntax:{value}")
    return int(seed_text), Path(path_text)


def validate_prediction_table(path: Path) -> int:
    regular(path, "source_prediction")
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(tuple(reader.fieldnames or ()) == PREDICTION_FIELDS, "source_prediction_fields")
        rows = list(reader)
    require(rows and len({row["candidate_id"] for row in rows}) == len(rows), "source_prediction_rows")
    return len(rows)


def checkpoint_record(seed: int, directory: Path, outer_fold: int) -> dict[str, Any]:
    reject_sealed_path(directory)
    require(directory.is_dir() and not directory.is_symlink(), f"outer_refit_dir:{directory}")
    result_path = directory / "RESULT.json"
    regular(result_path, "outer_refit_result")
    result = json.loads(result_path.read_text())
    require(result.get("status") == "PASS_FORMAL_OUTER_REFIT", f"outer_refit_status:{seed}")
    require(result.get("phase") == "outer", f"outer_refit_phase:{seed}")
    require(result.get("lane", {}).get("variant") == LANE, f"outer_refit_lane:{seed}")
    require(int(result.get("outer_fold")) == outer_fold, f"outer_refit_fold:{seed}")
    require(int(result.get("formal_seed")) == seed, f"outer_refit_seed:{seed}")
    require(int(result.get("prediction_metrics_access_count", -1)) == 0, f"prediction_metrics_access:{seed}")
    require(int(result.get("v4_f_test32_access_count", -1)) == 0, f"sealed_access:{seed}")
    require(result.get("neural_input_firewall", {}).get("M2_126D_ID_pose_inputs") == 0, f"firewall:{seed}")
    artifacts = result.get("artifacts", {})
    head = artifacts.get("neural_head", {})
    prediction = artifacts.get("predictions_no_metrics", {})
    checkpoint_path = directory / str(head.get("path"))
    prediction_path = directory / str(prediction.get("path"))
    regular(checkpoint_path, "outer_refit_checkpoint")
    require(sha256_file(checkpoint_path) == head.get("sha256"), f"checkpoint_receipt_hash:{seed}")
    regular(prediction_path, "outer_refit_prediction")
    require(sha256_file(prediction_path) == prediction.get("sha256"), f"prediction_receipt_hash:{seed}")
    rows = validate_prediction_table(prediction_path)
    require(rows == int(prediction.get("rows")), f"prediction_receipt_rows:{seed}")
    return {
        "seed": seed,
        "result_receipt": record(result_path),
        "checkpoint": record(checkpoint_path),
        "source_predictions_no_metrics": {**record(prediction_path), "rows": rows},
        "formal_hparam_id": str(result.get("formal_hparam_id")),
        "source_split_id": str(result.get("source_split", {}).get("split_id")),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--outer-fold", type=int, required=True)
    value.add_argument("--label-free-panel", type=Path, required=True)
    value.add_argument("--graph-cache-dir", type=Path, required=True)
    value.add_argument("--target-graph-pt", type=Path, required=True)
    value.add_argument("--model-source", type=Path, required=True)
    value.add_argument("--model-path", type=Path, required=True)
    value.add_argument("--model-identity-file", type=Path, required=True)
    value.add_argument("--expected-model-identity-sha256", required=True)
    value.add_argument("--split-manifest", type=Path, required=True)
    value.add_argument("--outer-refit", action="append", required=True)
    value.add_argument("--output-json", type=Path, required=True)
    value.add_argument("--replay-atol", type=float, default=1e-6)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    require(0 <= args.outer_fold < 5, "outer_fold")
    require(math.isfinite(args.replay_atol) and 0.0 < args.replay_atol <= 1e-4, "replay_atol")
    reject_sealed_path(args.output_json)
    regular(args.label_free_panel, "label_free_panel")
    regular(args.target_graph_pt, "target_graph")
    regular(args.model_source, "model_source")
    regular(args.model_identity_file, "model_identity")
    regular(args.split_manifest, "split_manifest")
    reject_sealed_path(args.model_path)
    require(args.model_path.is_dir() and not args.model_path.is_symlink(), "model_path")
    require(sha256_file(args.model_identity_file) == args.expected_model_identity_sha256, "model_identity_hash")
    reject_sealed_path(args.graph_cache_dir)
    require(args.graph_cache_dir.is_dir() and not args.graph_cache_dir.is_symlink(), "graph_cache_dir")
    graph_files = {
        name: record(args.graph_cache_dir / name)
        for name in ("graph_manifest_v2.tsv", "graph_cache_receipt_v2.json", "graph_cache_v2.npz")
    }
    split = json.loads(args.split_manifest.read_text())
    require(split.get("open_only") is True and int(split.get("v4_f_test32_access_count", -1)) == 0, "split_not_open")
    require(int(split.get("outer_fold")) == args.outer_fold, "split_outer_fold")
    parsed = [parse_outer_refit(value) for value in args.outer_refit]
    require(tuple(sorted(seed for seed, _ in parsed)) == SEEDS, "seed_closure")
    checkpoints = [checkpoint_record(seed, directory, args.outer_fold) for seed, directory in sorted(parsed)]
    require(len({item["source_split_id"] for item in checkpoints}) == 1, "checkpoint_split_id_disagreement")
    require(checkpoints[0]["source_split_id"] == str(split.get("split_id")), "checkpoint_split_id")
    payload = {
        "schema_version": SCHEMA,
        "status": "FROZEN_LABEL_FREE_EXPORT_CONTRACT",
        "outer_fold": args.outer_fold,
        "lane": LANE,
        "seeds": list(SEEDS),
        "backbone": {
            "kind": "hf_local",
            "model_path": str(args.model_path.resolve()),
            "model_identity_file": record(args.model_identity_file),
            "expected_model_identity_sha256": args.expected_model_identity_sha256,
        },
        "inputs": {
            "label_free_panel": record(args.label_free_panel),
            "graph_cache": {"path": str(args.graph_cache_dir.resolve()), "files": graph_files},
            "target_graph": record(args.target_graph_pt),
            "model_source": record(args.model_source),
            "split_manifest": record(args.split_manifest),
        },
        "outer_refits": checkpoints,
        "replay_atol": args.replay_atol,
        "pair_summary_feature_scope": "FUTURE_VERSION_DIAGNOSTIC_ONLY_NOT_CURRENT_V2_5_SELECTION",
        "current_v2_5_primary_contact_fields": ["contact_score_R8", "contact_score_R9"],
        "teacher_metric_files_read": 0,
        "v4_f_test32_access_count": 0,
    }
    atomic_json(args.output_json, payload)
    print(json.dumps({"status": payload["status"], "outer_fold": args.outer_fold}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
