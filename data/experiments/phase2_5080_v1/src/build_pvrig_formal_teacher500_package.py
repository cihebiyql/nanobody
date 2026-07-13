#!/usr/bin/env python3
"""Build a resumable seven-shard Node1 package for formal Teacher500 docking."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import build_pvrig_teacher_pilot96_package as pilot  # noqa: E402

DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"
DEFAULT_TEMPLATE = WORKSPACE_ROOT / "docking/candidates/v2_5_pose_batch"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_teacher_formal_v1/teacher500_docking_package"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_teacher_formal_v1_20260712/teacher500_docking"
SHARD_COUNT = 7
GPU_OFFSET = 1
EXPECTED_CANDIDATES = 500
CLAIM_BOUNDARY = "prospective_computational_docking_teacher_not_binding_or_experimental_blocking_truth"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verified_range(sequence: str, cdr: str, start_raw: str, end_raw: str) -> tuple[int, int]:
    start, end = int(start_raw), int(end_raw)
    if not (1 <= start <= end <= len(sequence)) or sequence[start - 1 : end] != cdr:
        raise ValueError(f"Frozen CDR coordinates do not match sequence: {start}-{end} {cdr}")
    return start, end


def manifest_row(source: dict[str, str]) -> dict[str, str]:
    sequence = source["vhh_sequence"]
    ranges = {
        name: verified_range(
            sequence,
            source[f"{name}_after"],
            source[f"{name}_start_1based"],
            source[f"{name}_end_1based"],
        )
        for name in ("cdr1", "cdr2", "cdr3")
    }
    return {
        "schema_version": "pvrig_formal_teacher500_node1_manifest_v1",
        "selection_rank": source["selection_rank"],
        "candidate_id": source["candidate_id"],
        "vhh_seq": sequence,
        "vhh_seq_sha256": source["sequence_sha256"],
        "cdr1_seq": source["cdr1_after"],
        "cdr2_seq": source["cdr2_after"],
        "cdr3_seq": source["cdr3_after"],
        "cdr1_start_1based": str(ranges["cdr1"][0]),
        "cdr1_end_1based": str(ranges["cdr1"][1]),
        "cdr2_start_1based": str(ranges["cdr2"][0]),
        "cdr2_end_1based": str(ranges["cdr2"][1]),
        "cdr3_start_1based": str(ranges["cdr3"][0]),
        "cdr3_end_1based": str(ranges["cdr3"][1]),
        "hotspot_set": source["target_patch_id"],
        "hotspots_uniprot": source.get("hotspots_uniprot", ""),
        "framework_id": source["parent_id"],
        "parent_framework_cluster": source["parent_framework_cluster"],
        "backbone_index": source["backbone_index"],
        "mpnn_index": source["mpnn_index"],
        "design_mode": source["design_mode"],
        "design_method": source["design_method"],
        "selection_stratum": source["teacher_selection_layer"],
        "teacher_split": source["formal_split"],
        "fast_gate_tier": source["fast_gate_tier"],
        "generic_binding_prior": source["generic_binding_prior"],
        "model_uncertainty": source["model_uncertainty"],
        "cheap_qc_score": source["cheap_qc_score"],
        "source_mpnn_pdb": source["source_pdb"],
        "evidence_boundary": CLAIM_BOUNDARY,
    }


def build_shard(shard_root: Path, rows: Sequence[dict[str, str]], template: Path) -> None:
    for directory in ("inputs", "scripts", "manifests", "haddock3"):
        (shard_root / directory).mkdir(parents=True, exist_ok=True)
    for name in pilot.TEMPLATE_INPUTS:
        shutil.copy2(template / "inputs" / name, shard_root / "inputs" / name)
    for name in pilot.TEMPLATE_SCRIPTS:
        source = template / "scripts" / name
        destination = shard_root / "scripts" / name
        if name == "run_node1_v2_5_pose_batch.sh":
            destination.write_text(pilot.patch_runner(source.read_text(encoding="utf-8")), encoding="utf-8")
            destination.chmod(0o755)
        else:
            shutil.copy2(source, destination)

    manifest = [manifest_row(row) for row in rows]
    pilot.write_tsv(shard_root / "manifests/selected_candidates_manifest.tsv", manifest)
    cdr_rows = [
        {
            "candidate_id": row["candidate_id"],
            "cdr1_range": f"{row['cdr1_start_1based']}-{row['cdr1_end_1based']}",
            "cdr2_range": f"{row['cdr2_start_1based']}-{row['cdr2_end_1based']}",
            "cdr3_range": f"{row['cdr3_start_1based']}-{row['cdr3_end_1based']}",
            "cdr1_seq": row["cdr1_seq"],
            "cdr2_seq": row["cdr2_seq"],
            "cdr3_seq": row["cdr3_seq"],
        }
        for row in manifest
    ]
    pilot.write_tsv(shard_root / "inputs/candidate_cdr_ranges.tsv", cdr_rows)
    with (shard_root / "inputs/v2_5_pose_batch_vhh.fasta").open("w", encoding="utf-8") as handle:
        for row in manifest:
            handle.write(f">{row['candidate_id']}\n{row['vhh_seq']}\n")
    subprocess.run(
        ["python3", "scripts/make_candidate_haddock_assets.py"],
        cwd=shard_root,
        check=True,
        capture_output=True,
        text=True,
    )
    for config in sorted((shard_root / "haddock3").glob("*/*_pvrig_hotspot.cfg")):
        config.write_text(pilot.patch_haddock_config(config.read_text(encoding="utf-8")), encoding="utf-8")


def controller_script(shard_count: int = SHARD_COUNT) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
ROOT=${{PVRIG_TEACHER500_REMOTE_ROOT:-{REMOTE_ROOT}}}
MODE=${{1:-all}}
MONOMER_START_MAX_LOAD1=${{PVRIG_MONOMER_START_MAX_LOAD1:-96}}
DOCKING_START_MAX_LOAD1=${{PVRIG_DOCKING_START_MAX_LOAD1:-48}}
INTERNAL_MAX_LOAD1=${{PVRIG_INTERNAL_MAX_LOAD1:-48}}
LOAD_WAIT_SECONDS=${{PVRIG_LOAD_WAIT_SECONDS:-300}}
HADDOCK_NCORES=${{PVRIG_HADDOCK_NCORES:-{pilot.HADDOCK_NCORES}}}
mkdir -p "$ROOT/controller_logs"
exec > >(tee -a "$ROOT/controller_logs/controller.$(date +%Y%m%d_%H%M%S).log") 2>&1

wait_for_load() {{
  local threshold="$1" label="$2"
  while true; do
    load1=$(cut -d' ' -f1 /proc/loadavg)
    if python3 - "$load1" "$threshold" <<'PY'
import sys
raise SystemExit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)
PY
    then
      echo "LOAD_GATE_OK label=$label load1=$load1 threshold=$threshold $(date -Is)"
      return
    fi
    echo "LOAD_GATE_WAIT label=$label load1=$load1 threshold=$threshold sleep=$LOAD_WAIT_SECONDS $(date -Is)"
    sleep "$LOAD_WAIT_SECONDS"
  done
}}

run_shards() {{
  local run_haddock="$1" phase="$2"
  local pids=()
  for shard in $(seq 0 {shard_count - 1}); do
    shard_root="$ROOT/shard_$shard"
    gpu=$((shard + {GPU_OFFSET}))
    echo "SHARD_START phase=$phase shard=$shard gpu=$gpu $(date -Is)"
    (
      V2_5_REMOTE_ROOT="$shard_root" \
      V2_5_CUDA_DEVICES="$gpu" \
      V2_5_NBB2_THREADS=2 \
      V2_5_RUN_HADDOCK3="$run_haddock" \
      V2_5_MAX_LOAD1="$INTERNAL_MAX_LOAD1" \
      V2_5_LOAD_WAIT_SECONDS="$LOAD_WAIT_SECONDS" \
      V2_5_HADDOCK_NCORES="$HADDOCK_NCORES" \
      bash "$shard_root/scripts/run_node1_v2_5_pose_batch.sh"
    ) >"$ROOT/controller_logs/${{phase}}_shard_${{shard}}.log" 2>&1 &
    pids+=("$!")
  done
  status=0
  for pid in "${{pids[@]}}"; do wait "$pid" || status=1; done
  if [[ "$status" != 0 ]]; then
    echo "SHARD_PHASE_FAILED phase=$phase"
    return 1
  fi
  touch "$ROOT/${{phase}}.complete"
  echo "SHARD_PHASE_COMPLETE phase=$phase $(date -Is)"
}}

if [[ "$MODE" == "monomer" || "$MODE" == "all" ]]; then
  wait_for_load "$MONOMER_START_MAX_LOAD1" monomer_start
  run_shards 0 monomer
fi
if [[ "$MODE" == "docking" || "$MODE" == "all" ]]; then
  wait_for_load "$DOCKING_START_MAX_LOAD1" docking_start
  run_shards 1 docking
fi
echo "CONTROLLER_COMPLETE mode=$MODE $(date -Is)"
"""


def run(selection: Path, template: Path, outdir: Path, force: bool) -> dict[str, Any]:
    rows = read_csv(selection)
    if len(rows) != EXPECTED_CANDIDATES or len({row["candidate_id"] for row in rows}) != EXPECTED_CANDIDATES:
        raise ValueError(f"Expected {EXPECTED_CANDIDATES} unique selected rows, found {len(rows)}")
    if outdir.exists():
        if not force:
            raise FileExistsError(f"Output already exists: {outdir}")
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    shards: list[list[dict[str, str]]] = [[] for _ in range(SHARD_COUNT)]
    for index, row in enumerate(sorted(rows, key=lambda value: int(value["selection_rank"]))):
        shards[index % SHARD_COUNT].append(row)
    for index, shard_rows in enumerate(shards):
        build_shard(outdir / f"shard_{index}", shard_rows, template)
    controller = outdir / "run_teacher500_controller.sh"
    controller.write_text(controller_script(), encoding="utf-8")
    controller.chmod(0o755)
    subprocess.run(["bash", "-n", str(controller)], check=True)
    for index in range(SHARD_COUNT):
        subprocess.run(["bash", "-n", str(outdir / f"shard_{index}/scripts/run_node1_v2_5_pose_batch.sh")], check=True)

    files = sorted(path for path in outdir.rglob("*") if path.is_file())
    hashes_path = outdir / "package_sha256.tsv"
    with hashes_path.open("w", encoding="utf-8") as handle:
        handle.write("sha256\tpath\n")
        for path in files:
            handle.write(f"{pilot.sha256_file(path)}\t{path.relative_to(outdir)}\n")
    audit = {
        "status": "PASS_TEACHER500_NODE1_PACKAGE_READY",
        "schema_version": "pvrig_formal_teacher500_node1_package_v1",
        "selection_manifest": str(selection),
        "selection_sha256": pilot.sha256_file(selection),
        "remote_root": REMOTE_ROOT,
        "records": len(rows),
        "shard_count": SHARD_COUNT,
        "shard_counts": {f"shard_{index}": len(shard) for index, shard in enumerate(shards)},
        "gpu_indices": list(range(GPU_OFFSET, GPU_OFFSET + SHARD_COUNT)),
        "haddock_configs": len(list(outdir.glob("shard_*/haddock3/*/*.cfg"))),
        "haddock_ncores_per_shard": pilot.HADDOCK_NCORES,
        "controller": str(controller),
        "package_hash_manifest": str(hashes_path),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (outdir / "package_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    print(json.dumps(run(args.selection, args.template, args.outdir, args.force), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
