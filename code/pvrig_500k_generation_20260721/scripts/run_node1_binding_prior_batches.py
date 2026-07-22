#!/usr/bin/env python3
"""Resumable sequential batch controller for Node1 binding-prior models."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import time
from pathlib import Path


def read_fasta(path: Path):
    name = None
    parts: list[str] = []
    with gzip.open(path, "rt") if path.suffix == ".gz" else path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    yield name, "".join(parts)
                name, parts = line[1:].split()[0], []
            else:
                parts.append(line)
    if name is not None:
        yield name, "".join(parts)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def split_batches(input_fasta: Path, root: Path, batch_size: int) -> list[Path]:
    batch_root = root / "batches"
    marker = root / "status" / "SPLIT_COMPLETE.json"
    if marker.exists():
        return sorted(batch_root.glob("batch_*/candidates.fasta"))
    paths: list[Path] = []
    handle = None
    try:
        for index, (name, sequence) in enumerate(read_fasta(input_fasta)):
            batch_index = index // batch_size + 1
            if index % batch_size == 0:
                if handle is not None:
                    handle.close()
                batch_dir = batch_root / f"batch_{batch_index:06d}"
                batch_dir.mkdir(parents=True, exist_ok=True)
                path = batch_dir / "candidates.fasta"
                # Preserve an already running first batch if it is identical in scope.
                if batch_index == 1 and path.exists():
                    handle = path.open("a") if sum(1 for x in path.open() if x.startswith(">")) < batch_size else None
                else:
                    handle = path.open("w")
                paths.append(path)
            if handle is not None:
                handle.write(f">{name}\n{sequence}\n")
    finally:
        if handle is not None:
            handle.close()
    paths = sorted(batch_root.glob("batch_*/candidates.fasta"))
    write_json(marker, {"status": "PASS", "batch_size": batch_size, "batches": len(paths)})
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--antigen", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--deepnano-gpu", default="1")
    parser.add_argument("--nanobind-gpu", default="2")
    parser.add_argument("--start-batch", type=int, default=1)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    batches = split_batches(args.input, args.root, args.batch_size)
    wrapper = Path("/data1/qlyu/software/vhh_eval_tools/competition_qc/run_binding_prior_prefilter_node1.sh")
    failures: list[int] = []
    for ordinal, fasta in enumerate(batches, start=1):
        if ordinal < args.start_batch:
            continue
        batch_dir = fasta.parent
        output = batch_dir / "output"
        receipt = output / "RUN_RECEIPT.json"
        if receipt.exists() and json.loads(receipt.read_text()).get("status") == "PASS":
            continue
        # Batch 1 may have been started manually before this controller.
        manual_pid = args.root / "status" / f"batch_{ordinal:06d}.pid"
        if manual_pid.exists() and ordinal == 1:
            pid = int(manual_pid.read_text().strip())
            while Path(f"/proc/{pid}").exists() and not receipt.exists():
                time.sleep(30)
            if receipt.exists():
                continue
        env = os.environ.copy()
        env.update({
            "DEEPNANO_GPU": args.deepnano_gpu,
            "NANOBIND_GPU": args.nanobind_gpu,
            "RUN_AFFINITY": "0",
        })
        log = args.root / "logs" / f"batch_{ordinal:06d}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        success = False
        for attempt in (1, 2):
            with log.open("a") as handle:
                handle.write(f"attempt={attempt} start={time.time()}\n")
                rc = subprocess.run(
                    [str(wrapper), str(fasta), str(args.antigen), str(output)],
                    stdout=handle, stderr=subprocess.STDOUT, env=env,
                ).returncode
                handle.write(f"attempt={attempt} rc={rc} end={time.time()}\n")
            if rc == 0 and receipt.exists():
                success = True
                break
            time.sleep(30)
        if not success:
            failures.append(ordinal)
        complete = sum((path.parent / "output" / "RUN_RECEIPT.json").exists() for path in batches)
        write_json(args.root / "status" / "PROGRESS.json", {
            "status": "RUNNING", "total_batches": len(batches),
            "completed_batches": complete, "failed_batches": failures,
            "current_batch": ordinal, "updated_epoch": time.time(),
            "scientific_boundary": "weak binding priors; not Kd, IC50, or blocking evidence",
        })
    write_json(args.root / "status" / "TERMINAL.json", {
        "status": "COMPLETE" if not failures else "PARTIAL",
        "total_batches": len(batches), "failed_batches": failures,
        "updated_epoch": time.time(),
    })
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
