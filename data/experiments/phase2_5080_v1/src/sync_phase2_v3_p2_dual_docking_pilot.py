#!/usr/bin/env python3
"""Sync minimal completed Pilot64 HADDOCK evidence from Node1."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shlex
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_PACKAGE_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_package"
DEFAULT_MANIFEST = DEFAULT_PACKAGE_ROOT / "manifests/run_manifest.csv"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_node1_selected"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p2_dual_docking_pilot_sync_audit.json"
DEFAULT_REMOTE_ROOT = "/data/qlyu/projects/pvrig_v3_p2_dual_docking_pilot64_20260713"
CLAIM_BOUNDARY = "selected_node1_runtime_evidence_for_independent_dual_conformer_docking_gold"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def filter_rows(rows: Sequence[dict[str, str]], args: argparse.Namespace) -> list[dict[str, str]]:
    output = list(rows)
    if args.pilot_id:
        wanted = set(args.pilot_id)
        output = [row for row in output if row["pilot_id"] in wanted]
        missing = wanted - {row["pilot_id"] for row in output}
        if missing:
            raise ValueError(f"Unknown pilot IDs: {sorted(missing)}")
    if args.receptor:
        output = [row for row in output if row["receptor_id"].lower() in set(args.receptor)]
    if args.seed_role:
        output = [row for row in output if row["seed_role"] in set(args.seed_role)]
    return output


def remote_archive_command(remote_root: str, run_ids: Sequence[str]) -> str:
    quoted_ids = " ".join(shlex.quote(run_id) for run_id in run_ids)
    return f"""set -euo pipefail
ROOT={shlex.quote(remote_root)}
cd "$ROOT"
{{
  find manifests receptors hotspots scripts -type f -print0
  find . -maxdepth 1 -type f -name 'package_audit.json' -print0
  for run_id in {quoted_ids}; do
    test -s "runs/$run_id/$run_id.complete.json"
    find "runs/$run_id" -type f \
      \( -name "$run_id.complete.json" \
         -o -name '*.cfg' \
         -o -path '*/logs/*' \
         -o -path '*/run_*/6_seletopclusts/cluster_*_model_*.pdb*' \
         -o -path '*/run_*/traceback/consensus.tsv' \
         -o -path '*/run_*/0_topoaa/params.cfg' \
         -o -path '*/run_*/1_rigidbody/params.cfg' \
         -o -path '*/run_*/1_rigidbody/io.json' \
         -o -path '*/run_*/2_seletop/io.json' \
         -o -path '*/run_*/3_flexref/io.json' \
         -o -path '*/run_*/4_emref/io.json' \
         -o -path '*/run_*/5_clustfcc/clustfcc.tsv' \
         -o -path '*/run_*/6_seletopclusts/io.json' \) -print0
  done
}} | sort -z -u | tar --null --files-from=- -cf -
"""


def model_and_cluster_counts(run_dir: Path) -> tuple[int, int]:
    names = {
        path.name.removesuffix(".pdb.gz").removesuffix(".pdb")
        for path in (run_dir / "6_seletopclusts").glob("cluster_*_model_*.pdb*")
    }
    clusters = {name.split("_model_", 1)[0] for name in names}
    return len(names), len(clusters)


def inventory(outdir: Path, rows: Sequence[dict[str, str]], min_models: int, min_clusters: int) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for row in rows:
        run_id = row["run_id"]
        run_root = outdir / "runs" / run_id
        run_dir = run_root / f"run_{run_id}"
        marker = run_root / f"{run_id}.complete.json"
        models, clusters = model_and_cluster_counts(run_dir) if run_dir.is_dir() else (0, 0)
        consensus = run_dir / "traceback/consensus.tsv"
        config = run_root / row.get("config_relpath", f"{run_id}.cfg")
        if not config.exists():
            config = run_root / f"{run_id}.cfg"
        complete = marker.is_file() and consensus.is_file() and config.is_file() and models >= min_models and clusters >= min_clusters
        results.append(
            {
                "run_id": run_id,
                "pilot_id": row["pilot_id"],
                "receptor_id": row["receptor_id"],
                "seed_role": row["seed_role"],
                "selected_models": models,
                "pose_clusters": clusters,
                "completion_marker": marker.is_file(),
                "traceback_consensus": consensus.is_file(),
                "config_present": config.is_file(),
                "complete": complete,
            }
        )
    failures = [row for row in results if not row["complete"]]
    return {
        "status": "PASS" if not failures else "FAIL_SYNC_INCOMPLETE",
        "requested_runs": len(rows),
        "complete_runs": len(rows) - len(failures),
        "failed_runs": len(failures),
        "selected_models": sum(row["selected_models"] for row in results),
        "minimum_models_per_run": min_models,
        "minimum_clusters_per_run": min_clusters,
        "results": results,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    rows = filter_rows(read_csv(args.manifest), args)
    if not rows:
        raise ValueError("No docking runs selected")
    args.outdir.mkdir(parents=True, exist_ok=True)
    if not args.inventory_only:
        archive = args.outdir.parent / f".{args.outdir.name}.partial.tar"
        command = remote_archive_command(args.remote_root, [row["run_id"] for row in rows])
        with archive.open("wb") as handle:
            subprocess.run(
                [args.ssh_command, args.host, f"bash -lc {shlex.quote(command)}"],
                stdout=handle,
                check=True,
            )
        subprocess.run(["tar", "-C", str(args.outdir), "-xf", str(archive)], check=True)
        archive.unlink()

    evidence = inventory(args.outdir, rows, args.min_models, args.min_clusters)
    files = sorted(path for path in args.outdir.rglob("*") if path.is_file())
    audit = {
        **evidence,
        "schema_version": "phase2_v3_p2_dual_docking_pilot_sync_audit_v1",
        "sync_mode": "local_inventory_only" if args.inventory_only else "remote_sync_then_inventory",
        "host": args.host,
        "remote_root": args.remote_root,
        "manifest": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "outdir": str(args.outdir),
        "generation_receptor_counts": dict(Counter(row["receptor_id"].lower() for row in rows)),
        "seed_role_counts": dict(Counter(row["seed_role"] for row in rows)),
        "synced_file_count": len(files),
        "synced_bytes": sum(path.stat().st_size for path in files),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if audit["status"] != "PASS":
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ssh-command", default="ssh.exe")
    parser.add_argument("--host", default="node1")
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--min-models", type=int, default=8)
    parser.add_argument("--min-clusters", type=int, default=2)
    parser.add_argument("--pilot-id", action="append")
    parser.add_argument("--receptor", action="append", choices=("8x6b", "9e6y"))
    parser.add_argument("--seed-role", action="append", choices=("main", "replicate"))
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args(argv)
    if args.min_models <= 0 or args.min_clusters <= 0:
        parser.error("Minimum model and cluster counts must be positive")
    return args


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
