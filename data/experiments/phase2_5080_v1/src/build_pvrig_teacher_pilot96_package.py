#!/usr/bin/env python3
"""Build four resumable Node1 shards for the PVRIG teacher docking pilot."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_SELECTION = EXP_DIR / "data_splits/pvrig_teacher_pilot96/pvrig_teacher_pilot96_manifest.tsv"
DEFAULT_TEMPLATE = WORKSPACE_ROOT / "docking/candidates/v2_5_pose_batch"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_teacher_v1_20260712/pilot96_package"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_teacher_v1_20260712/pilot96"
SHARD_COUNT = 4
HADDOCK_NCORES = 4
CLAIM_BOUNDARY = "computational_docking_teacher_proxy_not_binding_or_blocker_proof"

TEMPLATE_SCRIPTS = [
    "make_candidate_haddock_assets.py",
    "normalize_pdb_chain.py",
    "pdb_geometry_qc.py",
    "run_node1_v2_5_pose_batch.sh",
    "validate_pdb_sequence.py",
]
TEMPLATE_INPUTS = [
    "pvrig_8x6b_chainB.pdb",
    "pvrig_8x6b_chainB.fasta",
    "hotspot_residues_8x6b.txt",
    "8X6B_PVRL2_chainA.pdb",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def cdr_range(sequence: str, cdr: str) -> tuple[int, int]:
    start = sequence.find(cdr)
    if start < 0 or sequence.find(cdr, start + 1) >= 0:
        raise ValueError(f"CDR is missing or ambiguous: {cdr}")
    return start + 1, start + len(cdr)


def patch_runner(source: str) -> str:
    residue_count_anchor = "--expected-residue-count 130"
    if residue_count_anchor not in source:
        raise ValueError("Runner expected residue count anchor not found")
    source = source.replace(
        residue_count_anchor,
        '--expected-residue-count "${#seq}"',
        1,
    )
    load_anchor = "MAX_LOAD1=${V2_5_MAX_LOAD1:-32}\n"
    if load_anchor not in source:
        raise ValueError("Runner MAX_LOAD1 anchor not found")
    source = source.replace(load_anchor, load_anchor + "LOAD_WAIT_SECONDS=${V2_5_LOAD_WAIT_SECONDS:-300}\n", 1)
    gate_anchor = "    check_load_gate || exit $?\n"
    if gate_anchor not in source:
        raise ValueError("Runner load gate anchor not found")
    source = source.replace(
        gate_anchor,
        "    while ! check_load_gate; do\n"
        "      echo \"LOAD_GATE_WAIT $cid sleep=$LOAD_WAIT_SECONDS $(date -Is)\"\n"
        "      sleep \"$LOAD_WAIT_SECONDS\"\n"
        "    done\n",
        1,
    )
    start_anchor = "    echo \"HADDOCK_START $cid $(date -Is)\"\n"
    if start_anchor not in source:
        raise ValueError("Runner HADDOCK start anchor not found")
    source = source.replace(
        start_anchor,
        "    if find \"haddock3/$cid/run_${cid}_pvrig_hotspot/6_seletopclusts\" "
        "-maxdepth 1 \\( -name 'cluster_*_model_*.pdb' -o -name 'cluster_*_model_*.pdb.gz' \\) "
        "-print -quit 2>/dev/null | grep -q .; then\n"
        "      echo \"HADDOCK_SKIP_COMPLETE $cid\"\n"
        "      continue\n"
        "    fi\n"
        + start_anchor,
        1,
    )
    return source


def patch_haddock_config(source: str) -> str:
    anchor = 'ncores = 8\n'
    if anchor not in source:
        raise ValueError("HADDOCK ncores anchor not found")
    return source.replace(anchor, f"ncores = {HADDOCK_NCORES}\n", 1)


def manifest_row(source: dict[str, str]) -> dict[str, str]:
    sequence = source["sequence"]
    cdr_ranges = {name: cdr_range(sequence, source[name]) for name in ("cdr1", "cdr2", "cdr3")}
    return {
        "schema_version": "pvrig_teacher_pilot96_node1_manifest_v1",
        "selection_rank": source["selection_rank"],
        "candidate_id": source["candidate_id"],
        "vhh_seq": sequence,
        "vhh_seq_sha256": source["sequence_sha256"],
        "cdr1_seq": source["cdr1"],
        "cdr2_seq": source["cdr2"],
        "cdr3_seq": source["cdr3"],
        "cdr1_start_1based": str(cdr_ranges["cdr1"][0]),
        "cdr1_end_1based": str(cdr_ranges["cdr1"][1]),
        "cdr2_start_1based": str(cdr_ranges["cdr2"][0]),
        "cdr2_end_1based": str(cdr_ranges["cdr2"][1]),
        "cdr3_start_1based": str(cdr_ranges["cdr3"][0]),
        "cdr3_end_1based": str(cdr_ranges["cdr3"][1]),
        "hotspot_set": source["hotspot_set"],
        "hotspots_uniprot": source["hotspots_uniprot"],
        "framework_id": source["framework_id"],
        "parent_framework_cluster": source["parent_framework_cluster"],
        "backbone_index": source["backbone_index"],
        "mpnn_index": source["mpnn_index"],
        "rfd_mindist": source["rfd_mindist"],
        "selection_stratum": source["selection_stratum"],
        "formal_model_eligible": source["formal_model_eligible"],
        "source_mpnn_pdb": source["source_mpnn_pdb"],
        "evidence_boundary": CLAIM_BOUNDARY,
    }


def write_tsv(path: Path, rows: Sequence[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def build_shard(shard_root: Path, rows: Sequence[dict[str, str]], template: Path) -> None:
    for directory in ("inputs", "scripts", "manifests", "haddock3"):
        (shard_root / directory).mkdir(parents=True, exist_ok=True)
    for name in TEMPLATE_INPUTS:
        shutil.copy2(template / "inputs" / name, shard_root / "inputs" / name)
    for name in TEMPLATE_SCRIPTS:
        source = template / "scripts" / name
        destination = shard_root / "scripts" / name
        if name == "run_node1_v2_5_pose_batch.sh":
            destination.write_text(patch_runner(source.read_text(encoding="utf-8")), encoding="utf-8")
            destination.chmod(0o755)
        else:
            shutil.copy2(source, destination)

    manifest = [manifest_row(row) for row in rows]
    write_tsv(shard_root / "manifests/selected_candidates_manifest.tsv", manifest)
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
    write_tsv(shard_root / "inputs/candidate_cdr_ranges.tsv", cdr_rows)
    with (shard_root / "inputs/v2_5_pose_batch_vhh.fasta").open("w", encoding="utf-8") as handle:
        for row in manifest:
            handle.write(f">{row['candidate_id']}\n{row['vhh_seq']}\n")
    subprocess.run(["python3", "scripts/make_candidate_haddock_assets.py"], cwd=shard_root, check=True, capture_output=True, text=True)
    for config in sorted((shard_root / "haddock3").glob("*/*_pvrig_hotspot.cfg")):
        config.write_text(patch_haddock_config(config.read_text(encoding="utf-8")), encoding="utf-8")


def controller_script() -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
ROOT=${{PVRIG_PILOT_REMOTE_ROOT:-{REMOTE_ROOT}}}
MODE=${{1:-all}}
MONOMER_START_MAX_LOAD1=${{PVRIG_MONOMER_START_MAX_LOAD1:-96}}
DOCKING_START_MAX_LOAD1=${{PVRIG_DOCKING_START_MAX_LOAD1:-48}}
INTERNAL_MAX_LOAD1=${{PVRIG_INTERNAL_MAX_LOAD1:-48}}
LOAD_WAIT_SECONDS=${{PVRIG_LOAD_WAIT_SECONDS:-300}}
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
  for shard in 0 1 2 3; do
    shard_root="$ROOT/shard_$shard"
    gpu=$((shard + 1))
    echo "SHARD_START phase=$phase shard=$shard gpu=$gpu $(date -Is)"
    (
      V2_5_REMOTE_ROOT="$shard_root" \
      V2_5_CUDA_DEVICES="$gpu" \
      V2_5_NBB2_THREADS=2 \
      V2_5_RUN_HADDOCK3="$run_haddock" \
      V2_5_MAX_LOAD1="$INTERNAL_MAX_LOAD1" \
      V2_5_LOAD_WAIT_SECONDS="$LOAD_WAIT_SECONDS" \
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


def run(selection: Path, template: Path, outdir: Path, force: bool) -> dict[str, object]:
    rows = read_tsv(selection)
    if len(rows) != 96:
        raise ValueError(f"Expected 96 selected rows, found {len(rows)}")
    if outdir.exists():
        if not force:
            raise FileExistsError(f"Output already exists: {outdir}")
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    shards: list[list[dict[str, str]]] = [[] for _ in range(SHARD_COUNT)]
    for index, row in enumerate(rows):
        shards[index % SHARD_COUNT].append(row)
    for index, shard_rows in enumerate(shards):
        build_shard(outdir / f"shard_{index}", shard_rows, template)
    controller = outdir / "run_pilot96_controller.sh"
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
            handle.write(f"{sha256_file(path)}\t{path.relative_to(outdir)}\n")
    audit: dict[str, object] = {
        "status": "PASS",
        "schema_version": "pvrig_teacher_pilot96_node1_package_v1",
        "selection_manifest": str(selection),
        "selection_sha256": sha256_file(selection),
        "remote_root": REMOTE_ROOT,
        "records": len(rows),
        "shard_counts": {f"shard_{index}": len(shard) for index, shard in enumerate(shards)},
        "haddock_configs": len(list(outdir.glob("shard_*/haddock3/*/*.cfg"))),
        "haddock_ncores_per_shard": HADDOCK_NCORES,
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


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.selection, args.template, args.outdir, args.force), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
