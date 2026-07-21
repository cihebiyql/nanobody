#!/usr/bin/env python3
"""Safely extract one verified per-job archive from the Node1 mirror."""

import argparse
import pathlib
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument(
        "--campaign-root",
        default="/data/qlyu/projects/pvrig_v29_bxcpu_results_mirror_20260720/stage2",
    )
    parser.add_argument("--output-root")
    args = parser.parse_args()
    if not args.job_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in args.job_id):
        raise SystemExit("unsafe job_id")
    campaign = pathlib.Path(args.campaign_root).resolve()
    archive = campaign / "compressed_queue" / f"{args.job_id}.tar.gz"
    output = pathlib.Path(args.output_root).resolve() if args.output_root else campaign
    if not archive.is_file():
        raise SystemExit(f"archive not found: {archive}")
    output.mkdir(parents=True, exist_ok=True)
    listing = subprocess.run(
        ["tar", "-tzf", str(archive)], check=True, text=True, stdout=subprocess.PIPE
    ).stdout.splitlines()
    for member in listing:
        path = pathlib.PurePosixPath(member)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"unsafe archive member: {member}")
    subprocess.run(["tar", "-xzf", str(archive), "-C", str(output)], check=True)
    print(f"extracted {args.job_id} to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
