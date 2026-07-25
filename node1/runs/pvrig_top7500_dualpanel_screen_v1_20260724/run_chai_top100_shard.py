#!/usr/bin/env python3
"""Run one resumable Chai-1 Top100 shard in a persistent Python process."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("CHAI_DOWNLOADS_DIR", "/data/qlyu/software/models/chai1")

from chai_lab.chai1 import run_inference  # noqa: E402


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "top100_rank", "candidate_id", "shard", "state",
        "output_dir", "pose_count", "elapsed_seconds", "error",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def complete_outputs(path: Path, expected: int) -> bool:
    return (
        len(list(path.glob("pred.model_idx_*.cif"))) == expected
        and len(list(path.glob("scores.model_idx_*.npz"))) == expected
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--max-candidates", type=int, default=0)
    args = parser.parse_args()

    with args.manifest.open(newline="", encoding="utf-8-sig") as handle:
        selected = [
            row for row in csv.DictReader(handle, delimiter="\t")
            if int(row["shard"]) == args.shard
        ]
    if args.max_candidates:
        selected = selected[: args.max_candidates]

    project = args.project.resolve()
    status_dir = project / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    status_path = status_dir / f"chai_shard_{args.shard}.tsv"
    heartbeat = status_dir / f"chai_shard_{args.shard}.json"
    statuses: list[dict[str, object]] = []

    for row in selected:
        started = time.time()
        candidate = row["candidate_id"]
        output = project / "outputs" / "chai" / candidate
        state = "FAILED"
        error = ""
        if complete_outputs(output, 2):
            state = "REUSED"
        else:
            if output.exists() and any(output.iterdir()):
                failed = (
                    project / "failed_attempts" / "chai"
                    / f"{candidate}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
                )
                failed.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(output), str(failed))
            output.mkdir(parents=True, exist_ok=True)
            try:
                run_inference(
                    Path(row["chai_input"]),
                    output_dir=output,
                    use_esm_embeddings=False,
                    use_msa_server=False,
                    use_templates_server=False,
                    num_trunk_recycles=3,
                    num_diffn_timesteps=50,
                    num_diffn_samples=2,
                    num_trunk_samples=1,
                    seed=100000 + int(row["top100_rank"]),
                    device="cuda:0",
                    low_memory=True,
                )
                if not complete_outputs(output, 2):
                    raise RuntimeError("expected two Chai CIF/NPZ pose pairs")
                state = "SUCCESS"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
        statuses.append(
            {
                "top100_rank": row["top100_rank"],
                "candidate_id": candidate,
                "shard": args.shard,
                "state": state,
                "output_dir": str(output),
                "pose_count": len(list(output.glob("pred.model_idx_*.cif"))),
                "elapsed_seconds": f"{time.time() - started:.3f}",
                "error": error,
            }
        )
        write_tsv(status_path, statuses)
        heartbeat.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "pid": os.getpid(),
                    "shard": args.shard,
                    "gpu_visible": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
                    "selected": len(selected),
                    "completed": sum(
                        item["state"] in {"SUCCESS", "REUSED"}
                        for item in statuses
                    ),
                    "failed": sum(item["state"] == "FAILED" for item in statuses),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if all(
        item["state"] in {"SUCCESS", "REUSED"} for item in statuses
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
