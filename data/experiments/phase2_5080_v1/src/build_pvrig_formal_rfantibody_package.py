#!/usr/bin/env python3
"""Build a resumable 8,640-record multi-parent RFantibody generation package."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
WORKSPACE_ROOT = EXP_DIR.parents[2]
DEFAULT_PARENTS = EXP_DIR / "data_splits/pvrig_teacher_formal_v1/parent40_manifest.tsv"
DEFAULT_TARGET = WORKSPACE_ROOT / "node1/rfantibody_pvrig_1000/inputs/pvrig_8x6b_chainT.pdb"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_teacher_formal_v1/rfantibody_generation_package"
REMOTE_ROOT = "/data/qlyu/projects/pvrig_teacher_formal_v1_20260712/rfantibody_generation"
REMOTE_FRAMEWORK_ROOT = "/data/qlyu/projects/pvrig_teacher_formal_v1_20260712/parent40_structures"
BACKBONES_PER_TASK = 12
SEQUENCES_PER_BACKBONE = 3
GPU_IDS = tuple(range(1, 8))
CLAIM_BOUNDARY = "pvrig_hotspot_conditioned_generated_candidates_not_binding_or_blocking_truth"
PATCHES = {
    "A_CENTER": {"hotspots": "T57,T101,T106", "uniprot": "R95,F139,W144"},
    "B_LOWER": {"hotspots": "T97,T101,T105,T106", "uniprot": "K135,F139,S143,W144"},
    "C_CROSS": {"hotspots": "T33,T36,T105,T106", "uniprot": "S71,T74,S143,W144"},
}
MODES = ("H3", "H1H3")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def h3_range(length: int) -> tuple[int, int]:
    lower = min(20, max(5, length - 2))
    upper = min(20, max(lower, length + 2))
    return lower, upper


def build_tasks(parents: Sequence[dict[str, str]]) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for parent in sorted(parents, key=lambda row: int(row["selection_rank"])):
        h1_length = len(parent["cdr1"])
        lower, upper = h3_range(int(parent["cdr3_length"]))
        h3_spec = str(lower) if lower == upper else f"{lower}-{upper}"
        for patch_id, patch in PATCHES.items():
            for mode in MODES:
                design_loops = f"H3:{h3_spec}" if mode == "H3" else f"H1:{h1_length},H3:{h3_spec}"
                mpnn_loops = "H3" if mode == "H3" else "H1,H3"
                task_id = f"{parent['parent_id']}__{patch_id}__{mode}"
                tasks.append(
                    {
                        "task_id": task_id,
                        "parent_id": parent["parent_id"],
                        "parent_framework_cluster": parent["parent_framework_cluster"],
                        "formal_split": parent["formal_split"],
                        "cdr3_length_bin": parent["cdr3_length_bin"],
                        "patch_id": patch_id,
                        "hotspots_pdb": patch["hotspots"],
                        "hotspots_uniprot": patch["uniprot"],
                        "design_mode": mode,
                        "design_loops": design_loops,
                        "mpnn_loops": mpnn_loops,
                        "target_backbones": BACKBONES_PER_TASK,
                        "sequences_per_backbone": SEQUENCES_PER_BACKBONE,
                        "expected_raw_records": BACKBONES_PER_TASK * SEQUENCES_PER_BACKBONE,
                        "claim_boundary": CLAIM_BOUNDARY,
                    }
                )
    return tasks


def validation_tasks(tasks: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    patch_cycle = tuple(PATCHES)
    for task in tasks:
        key = (str(task["cdr3_length_bin"]), str(task["design_mode"]))
        if key in seen:
            continue
        desired_patch = patch_cycle[len(selected) % len(patch_cycle)]
        if task["patch_id"] != desired_patch:
            continue
        row = dict(task)
        row["target_backbones"] = 1
        row["sequences_per_backbone"] = 1
        row["expected_raw_records"] = 1
        row["task_id"] = f"VALIDATE__{row['task_id']}"
        selected.append(row)
        seen.add(key)
    if len(selected) != 8:
        raise ValueError(f"Expected eight validation tasks, found {len(selected)}")
    return selected


def task_runner_script() -> str:
    return r'''#!/usr/bin/env bash
set -Eeuo pipefail
TASK_ID=${1:?task id}
GPU=${2:?gpu id}
RUN_ROOT=${3:?run root}
PARENT_ID=${4:?parent id}
PATCH_ID=${5:?patch id}
HOTSPOTS=${6:?hotspots}
DESIGN_MODE=${7:?design mode}
DESIGN_LOOPS=${8:?design loops}
MPNN_LOOPS=${9:?mpnn loops}
TARGET_BACKBONES=${10:?target backbones}
SEQS_PER_BACKBONE=${11:?sequences per backbone}
RF_ROOT=${RF_ROOT:-/data/qlyu/software/RFantibody}
FRAMEWORK_ROOT=${FRAMEWORK_ROOT:-/data/qlyu/projects/pvrig_teacher_formal_v1_20260712/parent40_structures}
TARGET=${PVRIG_TARGET:-$RUN_ROOT/inputs/pvrig_8x6b_chainT.pdb}
TASK_DIR="$RUN_ROOT/tasks/$TASK_ID"
BACKBONE_DIR="$TASK_DIR/backbones"
SEQUENCE_DIR="$TASK_DIR/sequences"
TMP_DIR="$TASK_DIR/tmp"
STATUS_DIR="$TASK_DIR/status"
mkdir -p "$BACKBONE_DIR" "$SEQUENCE_DIR" "$TMP_DIR" "$STATUS_DIR"
exec 9>"$TASK_DIR/run.lock"
flock -n 9 || exit 75

mapfile -t framework_matches < <(find "$FRAMEWORK_ROOT" -path "*/frameworks/${PARENT_ID}_HLT.pdb" -type f | sort)
if [[ ${#framework_matches[@]} -ne 1 ]]; then
  echo "Expected one framework for $PARENT_ID, found ${#framework_matches[@]}" >&2
  exit 2
fi
FRAMEWORK=${framework_matches[0]}
test -s "$TARGET"
test -s "$FRAMEWORK"

write_status() {
  local state=$1 rc=${2:-0}
  python3 - "$STATUS_DIR/status.json" "$TASK_ID" "$GPU" "$PARENT_ID" "$PATCH_ID" "$DESIGN_MODE" \
    "$DESIGN_LOOPS" "$MPNN_LOOPS" "$TARGET_BACKBONES" "$SEQS_PER_BACKBONE" "$state" "$rc" \
    "$BACKBONE_DIR" "$SEQUENCE_DIR" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
out, task, gpu, parent, patch, mode, loops, mpnn, nb, ns, state, rc, bb, seq = sys.argv[1:]
payload = {
    "task_id": task, "gpu": int(gpu), "parent_id": parent, "patch_id": patch,
    "design_mode": mode, "design_loops": loops, "mpnn_loops": mpnn,
    "target_backbones": int(nb), "sequences_per_backbone": int(ns),
    "state": state, "return_code": int(rc),
    "backbone_count": len(list(Path(bb).glob("design_*.pdb"))),
    "sequence_count": len(list(Path(seq).glob("design_*_dldesign_*.pdb"))),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
Path(out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
if state == "complete":
    Path(out).with_name("complete.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}
trap 'rc=$?; if [[ $rc -ne 0 ]]; then write_status failed "$rc" || true; fi' EXIT
write_status running 0

existing_backbones=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.pdb' | wc -l)
missing_backbones=$((TARGET_BACKBONES - existing_backbones))
if (( missing_backbones < 0 )); then
  echo "Too many backbones: $existing_backbones > $TARGET_BACKBONES" >&2
  exit 3
fi
if (( missing_backbones > 0 )); then
  echo "RFD_START task=$TASK_ID parent=$PARENT_ID patch=$PATCH_ID mode=$DESIGN_MODE missing=$missing_backbones gpu=$GPU $(date -Is)"
  cd "$RF_ROOT"
  CUDA_VISIBLE_DEVICES="$GPU" bin/rfdiffusion \
    --target "$TARGET" --framework "$FRAMEWORK" --output "$BACKBONE_DIR/design" \
    --num-designs "$missing_backbones" --design-loops "$DESIGN_LOOPS" --hotspots "$HOTSPOTS" \
    --diffuser-t 50 --deterministic --no-trajectory
fi
backbone_count=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.pdb' | wc -l)
trb_count=$(find "$BACKBONE_DIR" -maxdepth 1 -type f -name 'design_*.trb' | wc -l)
if [[ $backbone_count -ne $TARGET_BACKBONES || $trb_count -ne $TARGET_BACKBONES ]]; then
  echo "Incomplete backbones: pdb=$backbone_count trb=$trb_count expected=$TARGET_BACKBONES" >&2
  exit 4
fi

pending="$TMP_DIR/pending_$$"
work="$TMP_DIR/mpnn_work_$$"
mkdir -p "$pending" "$work"
for pdb in "$BACKBONE_DIR"/design_*.pdb; do
  base=$(basename "$pdb" .pdb)
  count=$(find "$SEQUENCE_DIR" -maxdepth 1 -type f -name "${base}_dldesign_*.pdb" | wc -l)
  if (( count < SEQS_PER_BACKBONE )); then ln -s "$pdb" "$pending/$(basename "$pdb")"; fi
  if (( count > SEQS_PER_BACKBONE )); then echo "Too many sequences for $base" >&2; exit 5; fi
done
pending_count=$(find "$pending" -maxdepth 1 -type l -name 'design_*.pdb' | wc -l)
if (( pending_count > 0 )); then
  echo "MPNN_START task=$TASK_ID pending=$pending_count gpu=$GPU $(date -Is)"
  cd "$work"
  PYTHONHASHSEED=0 CUDA_VISIBLE_DEVICES="$GPU" "$RF_ROOT/bin/rfantibody-env" \
    "$RF_ROOT/scripts/proteinmpnn_interface_design.py" \
    -pdbdir "$pending" -outpdbdir "$SEQUENCE_DIR" -loop_string "$MPNN_LOOPS" \
    -seqs_per_struct "$SEQS_PER_BACKBONE" -temperature 0.2 \
    -checkpoint_path "$RF_ROOT/weights/ProteinMPNN_v48_noise_0.2.pt" \
    -omit_AAs CX -augment_eps 0 -checkpoint_name "$TMP_DIR/mpnn_checkpoint_$$.txt" -deterministic
fi
sequence_count=$(find "$SEQUENCE_DIR" -maxdepth 1 -type f -name 'design_*_dldesign_*.pdb' | wc -l)
expected=$((TARGET_BACKBONES * SEQS_PER_BACKBONE))
if [[ $sequence_count -ne $expected ]]; then
  echo "Incomplete sequences: $sequence_count != $expected" >&2
  exit 6
fi
write_status complete 0
trap - EXIT
echo "TASK_COMPLETE task=$TASK_ID backbones=$backbone_count sequences=$sequence_count $(date -Is)"
'''


def worker_script() -> str:
    return r'''#!/usr/bin/env bash
set -Eeuo pipefail
GPU=${1:?gpu}
TASK_FILE=${2:?task file}
RUN_ROOT=${3:?run root}
while IFS=$'\t' read -r task_id parent_id parent_cluster formal_split cdr3_bin patch_id hotspots_pdb hotspots_uniprot design_mode design_loops mpnn_loops target_backbones sequences_per_backbone expected_raw claim_boundary; do
  [[ "$task_id" == task_id ]] && continue
  [[ -z "$task_id" ]] && continue
  bash "$RUN_ROOT/scripts/run_task.sh" "$task_id" "$GPU" "$RUN_ROOT" "$parent_id" "$patch_id" \
    "$hotspots_pdb" "$design_mode" "$design_loops" "$mpnn_loops" "$target_backbones" "$sequences_per_backbone"
done < "$TASK_FILE"
'''


def controller_script(validation: bool) -> str:
    task_name = "validation_tasks.tsv" if validation else "tasks.tsv"
    run_subdir = "validation" if validation else "production"
    marker = "validation.complete" if validation else "generation.complete"
    return f'''#!/usr/bin/env bash
set -euo pipefail
ROOT=${{PVRIG_RFANTIBODY_REMOTE_ROOT:-{REMOTE_ROOT}}}
FRAMEWORK_ROOT=${{FRAMEWORK_ROOT:-{REMOTE_FRAMEWORK_ROOT}}}
test -f "$FRAMEWORK_ROOT/structures.complete"
RUN_ROOT="$ROOT/{run_subdir}"
mkdir -p "$RUN_ROOT/inputs" "$RUN_ROOT/scripts" "$RUN_ROOT/logs" "$RUN_ROOT/task_lists"
cp "$ROOT/inputs/pvrig_8x6b_chainT.pdb" "$RUN_ROOT/inputs/"
cp "$ROOT/scripts/run_task.sh" "$ROOT/scripts/run_worker.sh" "$RUN_ROOT/scripts/"
python3 "$ROOT/scripts/shard_tasks.py" --input "$ROOT/manifests/{task_name}" --outdir "$RUN_ROOT/task_lists" --workers {len(GPU_IDS)}
pids=()
for worker in $(seq 0 {len(GPU_IDS) - 1}); do
  gpu=$((worker + 1))
  FRAMEWORK_ROOT="$FRAMEWORK_ROOT" bash "$RUN_ROOT/scripts/run_worker.sh" "$gpu" \
    "$RUN_ROOT/task_lists/worker_${{worker}}.tsv" "$RUN_ROOT" \
    >"$RUN_ROOT/logs/worker_${{worker}}.log" 2>&1 &
  pids+=("$!")
done
status=0
for pid in "${{pids[@]}}"; do wait "$pid" || status=1; done
if [[ $status -ne 0 ]]; then echo "RFANTIBODY_{run_subdir.upper()}_FAILED $(date -Is)" >&2; exit 1; fi
touch "$ROOT/{marker}"
echo "RFANTIBODY_{run_subdir.upper()}_COMPLETE $(date -Is)"
'''


def shard_script() -> str:
    return r'''#!/usr/bin/env python3
import argparse, csv
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--input',type=Path,required=True); p.add_argument('--outdir',type=Path,required=True); p.add_argument('--workers',type=int,required=True); a=p.parse_args()
with a.input.open(newline='',encoding='utf-8') as h: rows=list(csv.DictReader(h,delimiter='\t'))
a.outdir.mkdir(parents=True,exist_ok=True)
for index in range(a.workers):
    part=rows[index::a.workers]
    with (a.outdir/f'worker_{index}.tsv').open('w',newline='',encoding='utf-8') as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]),delimiter='\t'); w.writeheader(); w.writerows(part)
'''


def run(parents_path: Path, target: Path, outdir: Path, force: bool) -> dict[str, object]:
    parents = read_tsv(parents_path)
    if len(parents) != 40 or len({row["parent_framework_cluster"] for row in parents}) != 40:
        raise ValueError("Expected 40 unique parent clusters")
    tasks = build_tasks(parents)
    validation = validation_tasks(tasks)
    if len(tasks) != 240 or sum(int(row["expected_raw_records"]) for row in tasks) != 8640:
        raise ValueError("Unexpected production task shape")
    if outdir.exists():
        if not force:
            raise FileExistsError(outdir)
        shutil.rmtree(outdir)
    for directory in ("inputs", "manifests", "scripts"):
        (outdir / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, outdir / "inputs/pvrig_8x6b_chainT.pdb")
    write_tsv(outdir / "manifests/tasks.tsv", tasks)
    write_tsv(outdir / "manifests/validation_tasks.tsv", validation)
    shutil.copy2(parents_path, outdir / "manifests/parent40_manifest.tsv")
    scripts = {
        "run_task.sh": task_runner_script(),
        "run_worker.sh": worker_script(),
        "shard_tasks.py": shard_script(),
        "run_validation_controller.sh": controller_script(True),
        "run_generation_controller.sh": controller_script(False),
    }
    for name, content in scripts.items():
        path = outdir / "scripts" / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        if name.endswith(".sh"):
            subprocess.run(["bash", "-n", str(path)], check=True)
    top_validation = outdir / "run_validation_controller.sh"
    top_generation = outdir / "run_generation_controller.sh"
    shutil.copy2(outdir / "scripts/run_validation_controller.sh", top_validation)
    shutil.copy2(outdir / "scripts/run_generation_controller.sh", top_generation)
    top_validation.chmod(0o755)
    top_generation.chmod(0o755)

    files = sorted(path for path in outdir.rglob("*") if path.is_file())
    hashes = outdir / "package_sha256.tsv"
    with hashes.open("w", encoding="utf-8") as handle:
        handle.write("sha256\tpath\n")
        for path in files:
            handle.write(f"{sha256_file(path)}\t{path.relative_to(outdir)}\n")
    audit: dict[str, object] = {
        "status": "PASS_RFANTIBODY_MULTIPARENT_PACKAGE_READY",
        "schema_version": "pvrig_formal_rfantibody_package_v1",
        "parent_count": len(parents),
        "parent_cluster_count": len({row["parent_framework_cluster"] for row in parents}),
        "task_count": len(tasks),
        "validation_task_count": len(validation),
        "patch_counts": dict(sorted(Counter(str(row["patch_id"]) for row in tasks).items())),
        "mode_counts": dict(sorted(Counter(str(row["design_mode"]) for row in tasks).items())),
        "split_task_counts": dict(sorted(Counter(str(row["formal_split"]) for row in tasks).items())),
        "backbones_per_task": BACKBONES_PER_TASK,
        "sequences_per_backbone": SEQUENCES_PER_BACKBONE,
        "expected_backbones": len(tasks) * BACKBONES_PER_TASK,
        "expected_raw_records": sum(int(row["expected_raw_records"]) for row in tasks),
        "remote_root": REMOTE_ROOT,
        "remote_framework_root": REMOTE_FRAMEWORK_ROOT,
        "input_sha256": {str(parents_path): sha256_file(parents_path), str(target): sha256_file(target)},
        "package_hash_manifest": str(hashes),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    (outdir / "package_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parents", type=Path, default=DEFAULT_PARENTS)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.parents, args.target, args.outdir, args.force), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
