#!/usr/bin/env python3
"""Run a frozen inner-split D-lane optimizer/loss pilot on one physical GPU."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


class PilotError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PilotError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def set_arg(command: list[str], flag: str, value: object) -> None:
    require(command.count(flag) == 1, f"flag_count:{flag}:{command.count(flag)}")
    command[command.index(flag) + 1] = str(value)


def materialize_variant_split(source: Path, destination: Path, epochs: int) -> dict[str, object]:
    require(source.is_file() and not source.is_symlink(), "source_split_missing_or_symlink")
    require(epochs > 0, "variant_epochs_invalid")
    payload = json.loads(source.read_text(encoding="utf-8"))
    required = {
        "split_id", "outer_fold", "train_parents", "score_parents", "fixed_epochs",
        "open_only", "v4_f_test32_access_count", "train_parent_set_sha256", "score_parent_set_sha256",
    }
    require(required <= set(payload), "source_split_fields_missing")
    require(payload["open_only"] is True and payload["v4_f_test32_access_count"] == 0, "source_split_not_open")
    original = dict(payload)
    payload["fixed_epochs"] = int(epochs)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(destination, payload)
    changed = {key for key in payload if payload[key] != original[key]}
    require(changed <= {"fixed_epochs"}, f"variant_split_field_drift:{sorted(changed)}")
    return {
        "source_sha256": sha256_file(source),
        "variant_sha256": sha256_file(destination),
        "changed_fields": sorted(changed),
        "fixed_epochs_from": int(original["fixed_epochs"]),
        "fixed_epochs_to": int(payload["fixed_epochs"]),
        "train_parent_set_sha256": payload["train_parent_set_sha256"],
        "score_parent_set_sha256": payload["score_parent_set_sha256"],
    }


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        mean_rank = 0.5 * (cursor + end - 1) + 1.0
        for index in order[cursor:end]:
            result[index] = mean_rank
        cursor = end
    return result


def pearson(left: list[float], right: list[float]) -> float:
    require(len(left) == len(right) and len(left) >= 3, "pearson_shape")
    lm, rm = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((x - lm) * (y - rm) for x, y in zip(left, right))
    denominator = math.sqrt(sum((x - lm) ** 2 for x in left) * sum((y - rm) ** 2 for y in right))
    return numerator / denominator if denominator > 0 else 0.0


def metrics(rows: list[dict[str, str]], target: str) -> dict[str, float]:
    truth = [float(row[f"truth_{target}"]) for row in rows]
    prediction = [float(row[f"neural_{target}"]) for row in rows]
    errors = [a - b for a, b in zip(truth, prediction)]
    return {
        "spearman": pearson(ranks(truth), ranks(prediction)),
        "mae": sum(abs(value) for value in errors) / len(errors),
        "rmse": math.sqrt(sum(value * value for value in errors) / len(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    require(args.plan.is_file() and not args.plan.is_symlink(), "plan_missing_or_symlink")
    require(not os.path.lexists(args.output_root), "output_root_exists")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    require(plan["sealed_evaluation_access_count"] == 0, "sealed_access_nonzero")
    require(plan["base_job"]["physical_gpu"] == 1, "physical_gpu_not_one")
    graph_path = Path(plan["base_job"]["source_graph"])
    require(graph_path.is_file(), "source_graph_missing")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    matches = [job for job in graph["jobs"] if job["job_id"] == plan["base_job"]["source_job_id"]]
    require(len(matches) == 1, "source_job_not_unique")
    source_job = matches[0]
    require(source_job["lane"] == "D_SPLIT_PAIR" and source_job["outer_fold"] == 0 and source_job["inner_fold"] == 0, "source_job_identity")
    require(source_job["command"] and graph["sealed_evaluation_access_count"] == 0, "source_graph_not_authorized_open")
    args.output_root.mkdir(parents=True)
    (args.output_root / "logs").mkdir()
    (args.output_root / "variants").mkdir()
    (args.output_root / "variant_splits").mkdir()
    atomic_json(args.output_root / "STATUS.json", {
        "status": "RUNNING",
        "plan_sha256": sha256_file(args.plan),
        "source_graph_sha256": sha256_file(graph_path),
        "started_unix": time.time(),
        "sealed_evaluation_access_count": 0,
    })
    summary_rows: list[dict[str, object]] = []
    environment = dict(os.environ)
    environment.update({
        "CUDA_VISIBLE_DEVICES": "1",
        "OMP_NUM_THREADS": "8",
        "MKL_NUM_THREADS": "8",
        "OPENBLAS_NUM_THREADS": "8",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTHONUNBUFFERED": "1",
    })
    try:
        for variant in plan["variants"]:
            name = variant["name"]
            require(name and name.replace("_", "").replace("-", "").isalnum(), f"variant_name:{name}")
            command = list(source_job["command"])
            output_dir = args.output_root / "variants" / name
            source_split = Path(command[command.index("--split-manifest") + 1])
            variant_split = args.output_root / "variant_splits" / f"{name}.json"
            split_receipt = materialize_variant_split(source_split, variant_split, int(variant["epochs"]))
            set_arg(command, "--output-dir", output_dir)
            set_arg(command, "--split-manifest", variant_split)
            set_arg(command, "--fixed-epochs", variant["epochs"])
            set_arg(command, "--learning-rate", variant["learning_rate"])
            set_arg(command, "--weight-decay", variant["weight_decay"])
            set_arg(command, "--huber-delta", variant["huber_delta"])
            require(command[command.index("--marginal-weight") + 1] == "1.0", "marginal_weight_drift")
            require(command[command.index("--pair-weight") + 1] == "0.5", "pair_weight_drift")
            log_path = args.output_root / "logs" / f"{name}.log"
            started = time.time()
            with log_path.open("xb") as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=environment, check=False)
            require(completed.returncode == 0, f"variant_failed:{name}:{completed.returncode}:{log_path}")
            result = json.loads((output_dir / "RESULT.json").read_text())
            require(result["status"] == "PASS_OPEN_BASE_SPLIT_COMPLETE", f"variant_result:{name}")
            require(result["v4_f_test32_access_count"] == 0, f"variant_test32:{name}")
            with (output_dir / "base_score_predictions.tsv").open(newline="", encoding="utf-8") as handle:
                predictions = list(csv.DictReader(handle, delimiter="\t"))
            require(predictions, f"variant_predictions_empty:{name}")
            for row in predictions:
                require(abs(float(row["neural_Rdual"]) - min(float(row["neural_R8"]), float(row["neural_R9"]))) <= 1e-7, f"exact_min:{name}:{row['candidate_id']}")
            record: dict[str, object] = {
                **variant,
                "rows": len(predictions),
                "runtime_seconds": time.time() - started,
                "optimizer_steps": result["training"]["optimizer_steps"],
                "prediction_sha256": sha256_file(output_dir / "base_score_predictions.tsv"),
                "variant_split_sha256": split_receipt["variant_sha256"],
            }
            for target in ("R8", "R9", "Rdual"):
                for metric, value in metrics(predictions, target).items():
                    record[f"{target}_{metric}"] = value
            summary_rows.append(record)
            atomic_json(args.output_root / "STATUS.json", {
                "status": "RUNNING",
                "completed_variants": len(summary_rows),
                "total_variants": len(plan["variants"]),
                "last_variant": name,
                "sealed_evaluation_access_count": 0,
            })
        fields = list(summary_rows[0])
        with (args.output_root / "RESULTS.tsv").open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(summary_rows)
        best = max(summary_rows, key=lambda row: (float(row["Rdual_spearman"]), -float(row["Rdual_mae"])))
        atomic_json(args.output_root / "TERMINAL.json", {
            "status": "PASS_INNER_ONLY_OPTIMIZER_PILOT_COMPLETE",
            "variants": len(summary_rows),
            "best_descriptive_variant": best["name"],
            "results_sha256": sha256_file(args.output_root / "RESULTS.tsv"),
            "formal_promotion_authorized": False,
            "sealed_evaluation_access_count": 0,
            "claim_boundary": plan["claim_boundary"],
        })
    except Exception as error:
        atomic_json(args.output_root / "TERMINAL.json", {
            "status": "FAIL_INNER_ONLY_OPTIMIZER_PILOT",
            "error": f"{type(error).__name__}:{error}",
            "formal_promotion_authorized": False,
            "sealed_evaluation_access_count": 0,
        })
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
