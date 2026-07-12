#!/usr/bin/env python3
"""Build a resumable Node1 package for 40 parent VHH structures and HLT files."""
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
WORKSPACE_ROOT = EXP_DIR.parents[2]
DEFAULT_MANIFEST = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/parent40_manifest.tsv"
DEFAULT_TEMPLATE = WORKSPACE_ROOT / "docking/candidates/v2_5_pose_batch/scripts"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_teacher_formal_v1/parent40_structure_package"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_teacher_formal_v1_20260712/parent40_structures"
SHARD_COUNT = 4
CLAIM_BOUNDARY = "predicted_parent_structures_for_rfantibody_generation_not_binding_truth"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def runner_script() -> str:
    return r'''#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${PVRIG_PARENT_ROOT:?PVRIG_PARENT_ROOT is required}
GPU=${PVRIG_PARENT_GPU:-1}
BIN_BOLTZ=${PVRIG_BIN_BOLTZ:-/data/qlyu/anaconda3/envs/boltz/bin}
THREADS=${PVRIG_PARENT_THREADS:-2}
mkdir -p "$ROOT/logs" "$ROOT/monomer" "$ROOT/frameworks" "$ROOT/reports"
cd "$ROOT"

run_nbb2() {
  local seq=$1 raw=$2 log=$3
  CUDA_VISIBLE_DEVICES="$GPU" PATH="$BIN_BOLTZ:$PATH" \
    "$BIN_BOLTZ/NanoBodyBuilder2" -H "$seq" -o "$raw" --n_threads "$THREADS" -v >"$log" 2>&1
}

while IFS=$'\t' read -r parent_id sequence sequence_sha256 cdr1_start cdr1_end cdr2_start cdr2_end cdr3_start cdr3_end parent_cluster formal_split; do
  [[ "$parent_id" == parent_id ]] && continue
  [[ -z "$parent_id" ]] && continue
  mkdir -p "monomer/$parent_id" "reports/$parent_id"
  raw="monomer/$parent_id/${parent_id}_nanobodybuilder2_raw.pdb"
  norm="monomer/$parent_id/${parent_id}_chainH.pdb"
  hlt="frameworks/${parent_id}_HLT.pdb"
  if [[ ! -s "$raw" ]]; then
    echo "NBB2_START $parent_id gpu=$GPU $(date -Is)"
    if ! run_nbb2 "$sequence" "$raw" "logs/${parent_id}_nanobodybuilder2.log"; then
      echo "NBB2_FALLBACK_UNREFINED $parent_id $(date -Is)"
      CUDA_VISIBLE_DEVICES="$GPU" PATH="$BIN_BOLTZ:$PATH" \
        "$BIN_BOLTZ/NanoBodyBuilder2" -H "$sequence" -o "$raw" --n_threads "$THREADS" -u -v \
        >"logs/${parent_id}_nanobodybuilder2_unrefined.log" 2>&1
    fi
  fi
  python3 scripts/normalize_pdb_chain.py --in-pdb "$raw" --out-pdb "$norm" --chain-id H \
    --expected-residue-count "${#sequence}" >"logs/${parent_id}_normalize.log" 2>&1
  python3 scripts/validate_pdb_sequence.py --pdb "$norm" --chain H --expected-seq "$sequence" \
    --out-json "reports/$parent_id/${parent_id}_sequence_validation.json" \
    >"logs/${parent_id}_sequence_validation.log" 2>&1
  python3 scripts/pdb_geometry_qc.py --pdb "$norm" --chain H \
    --out-json "reports/$parent_id/${parent_id}_geometry_qc.json" \
    >"logs/${parent_id}_geometry_qc.log" 2>&1
  python3 scripts/make_rfantibody_hlt_framework.py \
    --input-pdb "$norm" --output-pdb "$hlt" --input-chain H --expected-residues "${#sequence}" \
    --h1 "$cdr1_start-$cdr1_end" --h2 "$cdr2_start-$cdr2_end" --h3 "$cdr3_start-$cdr3_end" \
    --audit "reports/$parent_id/${parent_id}_hlt_audit.json" \
    >"logs/${parent_id}_hlt.log" 2>&1
  sha256sum "$raw" "$norm" "$hlt" >"reports/$parent_id/${parent_id}_sha256.tsv"
  echo "PARENT_COMPLETE $parent_id cluster=$parent_cluster split=$formal_split $(date -Is)"
done < manifests/parents.tsv
'''


def controller_script() -> str:
    return f'''#!/usr/bin/env bash
set -euo pipefail
ROOT=${{PVRIG_PARENT40_REMOTE_ROOT:-{REMOTE_ROOT}}}
mkdir -p "$ROOT/controller_logs"
pids=()
for shard in 0 1 2 3; do
  shard_root="$ROOT/shard_$shard"
  gpu=$((shard + 1))
  (
    PVRIG_PARENT_ROOT="$shard_root" PVRIG_PARENT_GPU="$gpu" PVRIG_PARENT_THREADS=2 \
      bash "$shard_root/scripts/run_parent_structures.sh"
  ) >"$ROOT/controller_logs/shard_${{shard}}.log" 2>&1 &
  pids+=("$!")
done
status=0
for pid in "${{pids[@]}}"; do wait "$pid" || status=1; done
if [[ "$status" != 0 ]]; then
  echo "PARENT40_FAILED $(date -Is)" >&2
  exit 1
fi
touch "$ROOT/structures.complete"
echo "PARENT40_COMPLETE $(date -Is)"
'''


def build_shard(root: Path, rows: Sequence[dict[str, str]], template: Path) -> None:
    for directory in ("scripts", "manifests", "inputs"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name in ("normalize_pdb_chain.py", "validate_pdb_sequence.py", "pdb_geometry_qc.py"):
        shutil.copy2(template / name, root / "scripts" / name)
    shutil.copy2(SCRIPT_DIR / "make_rfantibody_hlt_framework.py", root / "scripts/make_rfantibody_hlt_framework.py")
    manifest_rows = [
        {
            "parent_id": row["parent_id"],
            "sequence": row["sequence"],
            "sequence_sha256": row["sequence_sha256"],
            "cdr1_start_1based": row["cdr1_start_1based"],
            "cdr1_end_1based": row["cdr1_end_1based"],
            "cdr2_start_1based": row["cdr2_start_1based"],
            "cdr2_end_1based": row["cdr2_end_1based"],
            "cdr3_start_1based": row["cdr3_start_1based"],
            "cdr3_end_1based": row["cdr3_end_1based"],
            "parent_framework_cluster": row["parent_framework_cluster"],
            "formal_split": row["formal_split"],
        }
        for row in rows
    ]
    write_tsv(root / "manifests/parents.tsv", manifest_rows)
    with (root / "inputs/parents.fasta").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f">{row['parent_id']}\n{row['sequence']}\n")
    runner = root / "scripts/run_parent_structures.sh"
    runner.write_text(runner_script(), encoding="utf-8")
    runner.chmod(0o755)
    subprocess.run(["bash", "-n", str(runner)], check=True)


def run(manifest: Path, outdir: Path, force: bool) -> dict[str, object]:
    rows = read_tsv(manifest)
    if len(rows) != 40 or len({row["parent_id"] for row in rows}) != 40:
        raise ValueError("Parent manifest must contain 40 unique parents")
    if outdir.exists():
        if not force:
            raise FileExistsError(outdir)
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    shards: list[list[dict[str, str]]] = [[] for _ in range(SHARD_COUNT)]
    for index, row in enumerate(rows):
        shards[index % SHARD_COUNT].append(row)
    for index, shard in enumerate(shards):
        build_shard(outdir / f"shard_{index}", shard, DEFAULT_TEMPLATE)
    controller = outdir / "run_parent40_controller.sh"
    controller.write_text(controller_script(), encoding="utf-8")
    controller.chmod(0o755)
    subprocess.run(["bash", "-n", str(controller)], check=True)

    files = sorted(path for path in outdir.rglob("*") if path.is_file())
    hashes = outdir / "package_sha256.tsv"
    with hashes.open("w", encoding="utf-8") as handle:
        handle.write("sha256\tpath\n")
        for path in files:
            handle.write(f"{sha256_file(path)}\t{path.relative_to(outdir)}\n")
    audit: dict[str, object] = {
        "status": "PASS_PARENT40_STRUCTURE_PACKAGE_READY",
        "schema_version": "pvrig_formal_parent40_structure_package_v1",
        "records": len(rows),
        "shard_counts": {f"shard_{index}": len(shard) for index, shard in enumerate(shards)},
        "manifest": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "remote_root": REMOTE_ROOT,
        "package_hash_manifest": str(hashes),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (outdir / "package_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.manifest, args.outdir, args.force), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
