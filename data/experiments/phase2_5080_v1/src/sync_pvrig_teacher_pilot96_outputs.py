#!/usr/bin/env python3
"""Sync the minimal completed Node1 evidence needed for pilot96 postprocessing."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
from collections import Counter
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_teacher_v1_20260712/pilot96_node1_selected"
DEFAULT_AUDIT = EXP_DIR / "audits/pvrig_teacher_pilot96_sync_audit.json"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_teacher_v1_20260712/pilot96"
CLAIM_BOUNDARY = "selected_node1_runtime_evidence_for_docking_teacher_postprocessing"
SELECTED_CORES_RE = re.compile(r"Selected (\d+) cores to process")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote_archive_command(remote_root: str) -> str:
    return f"""set -euo pipefail
ROOT={remote_root!r}
test -f "$ROOT/docking.complete"
cd "$ROOT"
{{
  find shard_* -type f \
    \( -path '*/run_*_pvrig_hotspot/6_seletopclusts/cluster_*_model_*.pdb*' \
       -o -path '*/run_*_pvrig_hotspot/traceback/consensus.tsv' \
       -o -path '*/reports/*/*_sequence_validation.json' \
       -o -path '*/reports/*/*_monomer_geometry_qc.json' \
       -o -path '*/reports/*/*_pvrig_receptor_geometry_qc.json' \
       -o -path '*/reports/*/*_asset_sha256.tsv' \
       -o -path '*/reports/*/*_haddock_outputs.txt' \
       -o -path '*/monomer/*/*_chainA.pdb' \
       -o -path '*/haddock3/*/*_pvrig_hotspot.cfg' \
       -o -path '*/haddock3/*/logs/*_haddock3_run.log' \
       -o -path '*/manifests/*.tsv' \) -print0
  find . -maxdepth 1 -type f -name '*.complete' -print0
  find controller_logs -maxdepth 1 -type f -name '*.log' -print0
}} | sort -z -u | tar --null --files-from=- -cf -
"""


def runtime_core_evidence(root: Path) -> dict[str, object]:
    logs = sorted(root.glob("shard_*/haddock3/*/logs/*_haddock3_run.log"))
    per_run_max: dict[str, int] = {}
    per_run_values: dict[str, list[int]] = {}
    missing: list[str] = []
    for path in logs:
        relative = str(path.relative_to(root))
        values = [int(value) for value in SELECTED_CORES_RE.findall(path.read_text(encoding="utf-8", errors="replace"))]
        if not values:
            missing.append(relative)
            continue
        per_run_max[relative] = max(values)
        per_run_values[relative] = sorted(set(values))
    return {
        "runtime_haddock_log_files": len(logs),
        "runtime_logs_with_selected_core_evidence": len(per_run_max),
        "runtime_logs_without_selected_core_evidence": missing,
        "runtime_max_selected_core_counts": dict(sorted(Counter(per_run_max.values()).items())),
        "per_run_max_selected_cores": per_run_max,
        "per_run_selected_core_values": per_run_values,
        "runtime_core_evidence_definition": (
            "maximum value in HADDOCK log lines matching "
            "'Selected N cores to process'; post-run config is not treated as runtime evidence"
        ),
    }


def inventory(root: Path, expected_candidates: int, top_n: int, min_models: int) -> dict[str, object]:
    run_dirs = sorted(root.glob("shard_*/haddock3/*/run_*_pvrig_hotspot"))
    model_files = sorted(root.glob("shard_*/haddock3/*/run_*_pvrig_hotspot/6_seletopclusts/cluster_*_model_*.pdb*"))
    consensus = sorted(root.glob("shard_*/haddock3/*/run_*_pvrig_hotspot/traceback/consensus.tsv"))
    sequence_qc = sorted(root.glob("shard_*/reports/*/*_sequence_validation.json"))
    monomer_qc = sorted(root.glob("shard_*/reports/*/*_monomer_geometry_qc.json"))
    receptor_qc = sorted(root.glob("shard_*/reports/*/*_pvrig_receptor_geometry_qc.json"))
    configs = sorted(root.glob("shard_*/haddock3/*/*_pvrig_hotspot.cfg"))
    core_evidence = runtime_core_evidence(root)
    per_run_models = {}
    for run in run_dirs:
        names = {
            path.name.removesuffix(".pdb.gz").removesuffix(".pdb")
            for path in (run / "6_seletopclusts").glob("cluster_*_model_*.pdb*")
        }
        per_run_models[str(run.relative_to(root))] = len(names)
    expected_models = expected_candidates * top_n
    status = "PASS"
    if not (root / "docking.complete").exists():
        status = "FAIL_MISSING_DOCKING_MARKER"
    elif len(run_dirs) != expected_candidates or len(consensus) != expected_candidates:
        status = "FAIL_INCOMPLETE_RUN_INVENTORY"
    elif any(count < min_models or count > top_n for count in per_run_models.values()):
        status = "FAIL_UNEXPECTED_SELECTED_MODEL_COUNT"
    elif any(len(paths) != expected_candidates for paths in (sequence_qc, monomer_qc, receptor_qc)):
        status = "FAIL_INCOMPLETE_QC_INVENTORY"
    elif core_evidence["runtime_haddock_log_files"] != expected_candidates:
        status = "FAIL_INCOMPLETE_RUNTIME_LOG_INVENTORY"
    elif core_evidence["runtime_logs_without_selected_core_evidence"]:
        status = "FAIL_MISSING_RUNTIME_CORE_EVIDENCE"
    return {
        "status": status,
        "run_dirs": len(run_dirs),
        "selected_models": sum(per_run_models.values()),
        "selected_model_files_including_compression_duplicates": len(model_files),
        "expected_selected_models": expected_models,
        "minimum_selected_models": expected_candidates * min_models,
        "per_run_model_counts": per_run_models,
        "traceback_consensus_files": len(consensus),
        "sequence_qc_files": len(sequence_qc),
        "monomer_geometry_qc_files": len(monomer_qc),
        "receptor_geometry_qc_files": len(receptor_qc),
        "haddock_config_files": len(configs),
        "postrun_haddock_config_ncores_counts": {
            str(ncores): sum(f"ncores = {ncores}" in path.read_text(encoding="utf-8") for path in configs)
            for ncores in (4, 8)
        },
        **core_evidence,
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    args.outdir.mkdir(parents=True, exist_ok=True)
    if not args.inventory_only:
        partial_tar = args.outdir.parent / f".{args.outdir.name}.partial.tar"
        command = remote_archive_command(args.remote_root)
        with partial_tar.open("wb") as handle:
            subprocess.run(
                [args.ssh_command, args.host, f"bash -lc {shlex.quote(command)}"],
                stdout=handle,
                check=True,
            )
        subprocess.run(["tar", "-C", str(args.outdir), "-xf", str(partial_tar)], check=True)
        partial_tar.unlink()

    evidence = inventory(args.outdir, args.expected_candidates, args.top_n, args.min_models)
    files = sorted(path for path in args.outdir.rglob("*") if path.is_file())
    audit: dict[str, object] = {
        **evidence,
        "schema_version": "pvrig_teacher_pilot96_sync_audit_v2",
        "sync_mode": "local_inventory_only" if args.inventory_only else "remote_sync_then_inventory",
        "host": args.host,
        "remote_root": args.remote_root,
        "outdir": str(args.outdir),
        "synced_file_count": len(files),
        "synced_bytes": sum(path.stat().st_size for path in files),
        "docking_marker_sha256": sha256_file(args.outdir / "docking.complete") if (args.outdir / "docking.complete").exists() else "",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if audit["status"] != "PASS":
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-command", default="ssh.exe")
    parser.add_argument("--host", default="node1")
    parser.add_argument("--remote-root", default=REMOTE_ROOT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--expected-candidates", type=int, default=96)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--min-models", type=int, default=4)
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Audit an already-synced --outdir without contacting Node1.",
    )
    args = parser.parse_args(argv)
    if args.expected_candidates <= 0 or args.top_n <= 0 or args.min_models <= 0 or args.min_models > args.top_n:
        parser.error("Require positive candidates and 0 < --min-models <= --top-n")
    return args


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
