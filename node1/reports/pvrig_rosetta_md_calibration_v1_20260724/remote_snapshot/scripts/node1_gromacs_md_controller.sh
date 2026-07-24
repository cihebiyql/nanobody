#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_CALIBRATION_ROOT:-/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724}"
MANIFEST="${PVRIG_MD_MANIFEST:-$ROOT/manifests/MD_PRODUCTION_MANIFEST.tsv}"
SOURCE_BASE="${PVRIG_MD_SOURCE_BASE:-$ROOT/md/jobs}"
PRODUCTION_BASE="${PVRIG_MD_PRODUCTION_BASE:-$ROOT/md/production}"
STATUS_FILE="${PVRIG_MD_STATUS_FILE:-$ROOT/status/MD_PRODUCTION_STATUS.json}"
LOCK_FILE="${PVRIG_MD_LOCK_FILE:-$ROOT/locks/gromacs_md_controller.lock}"
CONTROLLER_PID_FILE="${PVRIG_MD_CONTROLLER_PID_FILE:-$ROOT/status/MD_PRODUCTION_CONTROLLER.pid}"
GMX="${GMX:-/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx}"
PROTOCOL="$ROOT/md/protocol"
mkdir -p "$ROOT"/{md/production,status,logs,locks} "$PROTOCOL"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "another GROMACS MD controller owns the lock" >&2
  exit 75
fi
printf '%s\n' "$$" > "${CONTROLLER_PID_FILE}.tmp.$$"
mv "${CONTROLLER_PID_FILE}.tmp.$$" "$CONTROLLER_PID_FILE"
cleanup_pid() {
  if [[ -s "$CONTROLLER_PID_FILE" ]] && [[ "$(cat "$CONTROLLER_PID_FILE")" == "$$" ]]; then
    rm -f "$CONTROLLER_PID_FILE"
  fi
}
trap cleanup_pid EXIT

python3 - "$MANIFEST" <<'PY'
import csv
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8"), delimiter="\t"))
required = {"system_id", "source_job_id", "md_seed", "gpu"}
missing = required.difference(rows[0] if rows else {})
if not rows:
    raise SystemExit("MD manifest is empty")
if missing:
    raise SystemExit(f"MD manifest missing columns: {sorted(missing)}")
keys = [(row["system_id"], row["md_seed"]) for row in rows]
if len(keys) != len(set(keys)):
    raise SystemExit("MD manifest contains duplicate (system_id, md_seed) keys")
for row in rows:
    if not row["md_seed"].isdigit() or not row["gpu"].isdigit():
        raise SystemExit(f"invalid seed/GPU row: {row}")
PY

cat > "$PROTOCOL/nvt.mdp.template" <<'EOF'
define                   = -DPOSRES
integrator               = md
dt                       = 0.002
nsteps                   = 50000
continuation             = no
constraint_algorithm     = lincs
constraints              = h-bonds
lincs_iter               = 1
lincs_order              = 4
cutoff-scheme            = Verlet
nstlist                  = 20
coulombtype              = PME
rcoulomb                 = 1.2
vdwtype                  = Cut-off
vdw-modifier             = Force-switch
rvdw-switch              = 1.0
rvdw                     = 1.2
DispCorr                  = no
tcoupl                   = V-rescale
tc-grps                  = System
tau_t                    = 1.0
ref_t                    = 300
pcoupl                   = no
pbc                      = xyz
gen_vel                  = yes
gen_temp                 = 300
gen_seed                 = __SEED__
nstxout-compressed       = 5000
nstenergy                = 1000
nstlog                   = 1000
EOF

cat > "$PROTOCOL/npt.mdp" <<'EOF'
define                   = -DPOSRES
integrator               = md
dt                       = 0.002
nsteps                   = 50000
continuation             = yes
constraint_algorithm     = lincs
constraints              = h-bonds
lincs_iter               = 1
lincs_order              = 4
cutoff-scheme            = Verlet
nstlist                  = 20
coulombtype              = PME
rcoulomb                 = 1.2
vdwtype                  = Cut-off
vdw-modifier             = Force-switch
rvdw-switch              = 1.0
rvdw                     = 1.2
DispCorr                  = no
tcoupl                   = V-rescale
tc-grps                  = System
tau_t                    = 1.0
ref_t                    = 300
pcoupl                   = C-rescale
pcoupltype               = isotropic
tau_p                    = 5.0
ref_p                    = 1.0
compressibility          = 4.5e-5
refcoord_scaling         = com
pbc                      = xyz
gen_vel                  = no
nstxout-compressed       = 5000
nstenergy                = 1000
nstlog                   = 1000
EOF

cat > "$PROTOCOL/prod_2ns.mdp" <<'EOF'
integrator               = md
dt                       = 0.002
nsteps                   = 1000000
continuation             = yes
constraint_algorithm     = lincs
constraints              = h-bonds
lincs_iter               = 1
lincs_order              = 4
cutoff-scheme            = Verlet
nstlist                  = 20
coulombtype              = PME
rcoulomb                 = 1.2
vdwtype                  = Cut-off
vdw-modifier             = Force-switch
rvdw-switch              = 1.0
rvdw                     = 1.2
DispCorr                  = no
tcoupl                   = Nose-Hoover
tc-grps                  = System
tau_t                    = 1.0
ref_t                    = 300
pcoupl                   = C-rescale
pcoupltype               = isotropic
tau_p                    = 5.0
ref_p                    = 1.0
compressibility          = 4.5e-5
pbc                      = xyz
gen_vel                  = no
nstxout-compressed       = 5000
nstenergy                = 1000
nstlog                   = 1000
EOF

run_stage() {
  local d="$1" stage="$2" input_gro="$3" checkpoint="$4" mdp="$5" gpu="$6"
  if [[ -s "$d/${stage}.gro" ]]; then return 0; fi
  if [[ ! -s "$d/${stage}.tpr" ]]; then
    local args=(-f "$mdp" -c "$input_gro" -r "$input_gro" -p "$d/topol.top" -o "$d/${stage}.tpr" -maxwarn 0)
    if [[ -n "$checkpoint" ]]; then args+=(-t "$checkpoint"); fi
    if ! "$GMX" grompp "${args[@]}" >"$d/${stage}.grompp.stdout.log" 2>"$d/${stage}.grompp.stderr.log"; then
      return 1
    fi
  fi
  local cpi=()
  if [[ -s "$d/${stage}.cpt" ]]; then cpi=(-cpi "$d/${stage}.cpt" -append); fi
  if ! (
    cd "$d"
    CUDA_VISIBLE_DEVICES="$gpu" "$GMX" mdrun -deffnm "$stage" \
      -ntmpi 1 -ntomp 8 -pin on -pinoffset "$((gpu * 8))" -pinstride 1 \
      -nb gpu -pme gpu -bonded gpu -gpu_id 0 "${cpi[@]}"
  ) >"$d/${stage}.mdrun.stdout.log" 2>"$d/${stage}.mdrun.stderr.log"; then
    return 1
  fi
  [[ -s "$d/${stage}.gro" ]]
}

valid_production_outputs() {
  local d="$1" name
  for name in prod.tpr prod.xtc prod.cpt prod.gro prod.log; do
    [[ -s "$d/$name" ]] || return 1
  done
  grep -q "Finished mdrun on rank 0" "$d/prod.log" || return 1
  python3 - "$d/prod.log" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
steps = [int(match.group(1)) for match in re.finditer(
    r"^\s*(\d+)\s+[0-9]+(?:\.[0-9]+)?\s*$", text, flags=re.MULTILINE
)]
raise SystemExit(0 if steps and steps[-1] >= 1_000_000 else 1)
PY
}

run_one() {
  local system_id="$1" source_job_id="$2" seed="$3" gpu="$4"
  local source="$SOURCE_BASE/$system_id"
  local d="$PRODUCTION_BASE/$system_id/seed_$seed"
  mkdir -p "$d"
  local job_lock
  exec {job_lock}>"$d/run.lock"
  if ! flock -n "$job_lock"; then
    echo "job already locked: $system_id seed=$seed" >&2
    return 75
  fi
  if [[ -s "$d/COMPLETE.json" ]]; then
    if valid_production_outputs "$d"; then
      return 0
    fi
    printf '{"state":"FAILED","reason":"INVALID_COMPLETE_OUTPUTS"}\n' \
      > "$d/FAILED.json.tmp.$$"
    mv "$d/FAILED.json.tmp.$$" "$d/FAILED.json"
    return 1
  fi
  rm -f "$d/FAILED.json"
  for f in em.gro topol.top topol_Protein_chain_A.itp topol_Protein_chain_T.itp posre_Protein_chain_A.itp posre_Protein_chain_T.itp; do
    if [[ ! -s "$source/$f" ]]; then
      printf '{"state":"FAILED","reason":"SOURCE_FILE_MISSING","file":"%s"}\n' "$f" \
        > "$d/FAILED.json.tmp.$$"
      mv "$d/FAILED.json.tmp.$$" "$d/FAILED.json"
      return 1
    fi
    if [[ ! -e "$d/$f" ]]; then cp --reflink=auto "$source/$f" "$d/$f"; fi
    if ! cmp -s "$source/$f" "$d/$f"; then
      printf '{"state":"FAILED","reason":"FROZEN_FILE_MISMATCH","file":"%s"}\n' "$f" \
        > "$d/FAILED.json.tmp.$$"
      mv "$d/FAILED.json.tmp.$$" "$d/FAILED.json"
      return 1
    fi
  done
  sed "s/__SEED__/$seed/" "$PROTOCOL/nvt.mdp.template" > "$d/nvt.mdp"
  local start="$(date +%s)" rc=0
  run_stage "$d" nvt "$d/em.gro" "" "$d/nvt.mdp" "$gpu" || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    run_stage "$d" npt "$d/nvt.gro" "$d/nvt.cpt" "$PROTOCOL/npt.mdp" "$gpu" || rc=$?
  fi
  if [[ "$rc" -eq 0 ]]; then
    run_stage "$d" prod "$d/npt.gro" "$d/npt.cpt" "$PROTOCOL/prod_2ns.mdp" "$gpu" || rc=$?
  fi
  local end="$(date +%s)"
  if [[ "$rc" -eq 0 ]] && valid_production_outputs "$d"; then
    python3 - "$d/COMPLETE.json.tmp.$$" "$system_id" "$source_job_id" "$seed" "$gpu" "$start" "$end" <<'PY'
import json,sys
json.dump({"state":"COMPLETE","system_id":sys.argv[2],"source_job_id":sys.argv[3],
           "md_seed":int(sys.argv[4]),"gpu":int(sys.argv[5]),
           "started_epoch":int(sys.argv[6]),"finished_epoch":int(sys.argv[7]),
           "elapsed_seconds":int(sys.argv[7])-int(sys.argv[6]),"production_ns":2},
          open(sys.argv[1],"w"),indent=2)
PY
    mv "$d/COMPLETE.json.tmp.$$" "$d/COMPLETE.json"
  else
    printf '{"state":"FAILED","reason":"PRODUCTION_OUTPUT_VALIDATION_FAILED","return_code":%d,"elapsed_seconds":%d}\n' \
      "$rc" "$((end-start))" > "$d/FAILED.json.tmp.$$"
    mv "$d/FAILED.json.tmp.$$" "$d/FAILED.json"
    return 1
  fi
}

run_gpu_queue() {
  local gpu="$1"
  tail -n +2 "$MANIFEST" |
  while IFS=$'\t' read -r system_id pair_id pair_role source_job_id seed row_gpu rest; do
    if [[ "$row_gpu" == "$gpu" ]]; then
      run_one "$system_id" "$source_job_id" "$seed" "$gpu" || true
    fi
  done
}

python3 - "$STATUS_FILE.tmp" "$MANIFEST" <<'PY'
import csv,json,os,sys
from datetime import datetime,timezone
total=len(list(csv.DictReader(open(sys.argv[2]),delimiter="\t")))
json.dump({"state":"RUNNING","pid":os.getppid(),"started_at":datetime.now(timezone.utc).isoformat(),
           "total":total,"completed":0,"failed":0,"production_ns_each":2},
          open(sys.argv[1],"w"),indent=2)
PY
mv "$STATUS_FILE.tmp" "$STATUS_FILE"

mapfile -t gpu_list < <(tail -n +2 "$MANIFEST" | cut -f6 | sort -n -u)
mapfile -t available_gpu_list < <(nvidia-smi --query-gpu=index --format=csv,noheader,nounits | tr -d ' ')
for gpu in "${gpu_list[@]}"; do
  if [[ ! " ${available_gpu_list[*]} " =~ " ${gpu} " ]]; then
    echo "manifest requests unavailable GPU: $gpu" >&2
    exit 64
  fi
done
for gpu in "${gpu_list[@]}"; do run_gpu_queue "$gpu" & done
wait

python3 - "$ROOT" "$MANIFEST" "$PRODUCTION_BASE" "$STATUS_FILE.tmp" <<'PY'
import csv,json,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1])
manifest=Path(sys.argv[2]); production=Path(sys.argv[3]); status=Path(sys.argv[4])
rows=list(csv.DictReader(open(manifest),delimiter="\t"))
done=sum((production/r["system_id"]/f'seed_{r["md_seed"]}'/"COMPLETE.json").is_file() for r in rows)
failed=sum((production/r["system_id"]/f'seed_{r["md_seed"]}'/"FAILED.json").is_file() for r in rows)
state="COMPLETE" if done==len(rows) and failed==0 else "PARTIAL"
payload={"state":state,"updated_at":datetime.now(timezone.utc).isoformat(),
         "total":len(rows),"completed":done,"failed":failed,"production_ns_each":2}
json.dump(payload,open(status,"w"),indent=2)
print(json.dumps(payload))
PY
mv "$STATUS_FILE.tmp" "$STATUS_FILE"
python3 - "$STATUS_FILE" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
raise SystemExit(0 if payload.get("state") == "COMPLETE" else 1)
PY
