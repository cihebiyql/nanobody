#!/usr/bin/env python3
"""Run one resumable IgFold shard while loading the model only once."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

os.environ["PATH"] = (
    "/data/qlyu/anaconda3/envs/boltz/bin:"
    + os.environ.get("PATH", "")
)

import torch

_ORIGINAL_TORCH_LOAD = torch.load


def _torch_load_compat(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _ORIGINAL_TORCH_LOAD(*args, **kwargs)


torch.load = _torch_load_compat

from igfold import IgFoldRunner  # noqa: E402


AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def pdb_sequence(path: Path) -> str:
    chains: dict[str, list[str]] = {}
    seen: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
            continue
        if line[16] not in (" ", "A"):
            continue
        chain = line[21].strip() or "_"
        key = (chain, line[22:26], line[26])
        if key in seen:
            continue
        seen.add(key)
        aa = AA3.get(line[17:20].strip().upper())
        if aa:
            chains.setdefault(chain, []).append(aa)
    return max(("".join(value) for value in chains.values()), key=len, default="")


def write_status(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "top200_rank", "candidate_id", "shard", "state", "output_pdb",
        "sequence_match", "elapsed_seconds", "error",
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--models", type=int, default=1)
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
    output_dir = project / "models" / "igfold"
    status_dir = project / "status"
    output_dir.mkdir(parents=True, exist_ok=True)
    status_dir.mkdir(parents=True, exist_ok=True)
    status_path = status_dir / f"igfold_shard_{args.shard}.tsv"
    heartbeat_path = status_dir / f"igfold_shard_{args.shard}.json"

    statuses: list[dict[str, object]] = []
    pending: list[dict[str, str]] = []
    for row in selected:
        output = output_dir / f"{row['candidate_id']}.pdb"
        if output.is_file() and pdb_sequence(output) == row["sequence"]:
            statuses.append(
                {
                    "top200_rank": row["top200_rank"],
                    "candidate_id": row["candidate_id"],
                    "shard": args.shard,
                    "state": "REUSED",
                    "output_pdb": str(output),
                    "sequence_match": "true",
                    "elapsed_seconds": "0.000",
                    "error": "",
                }
            )
        else:
            pending.append(row)
    write_status(status_path, statuses)

    runner = IgFoldRunner(num_models=args.models, try_gpu=True) if pending else None
    for row in pending:
        started = time.time()
        output = output_dir / f"{row['candidate_id']}.pdb"
        state = "FAILED"
        error = ""
        sequence_match = "false"
        try:
            assert runner is not None
            runner.fold(
                str(output),
                sequences={"H": row["sequence"]},
                do_refine=False,
                use_openmm=False,
            )
            sequence_match = str(pdb_sequence(output) == row["sequence"]).lower()
            if sequence_match != "true":
                raise RuntimeError("IgFold output sequence mismatch")
            state = "SUCCESS"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        statuses.append(
            {
                "top200_rank": row["top200_rank"],
                "candidate_id": row["candidate_id"],
                "shard": args.shard,
                "state": state,
                "output_pdb": str(output),
                "sequence_match": sequence_match,
                "elapsed_seconds": f"{time.time() - started:.3f}",
                "error": error,
            }
        )
        write_status(status_path, statuses)
        heartbeat_path.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "pid": os.getpid(),
                    "shard": args.shard,
                    "gpu_visible": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
                    "selected": len(selected),
                    "completed": sum(
                        row["state"] in {"SUCCESS", "REUSED"} for row in statuses
                    ),
                    "failed": sum(row["state"] == "FAILED" for row in statuses),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    success = sum(row["state"] in {"SUCCESS", "REUSED"} for row in statuses)
    return 0 if success == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
