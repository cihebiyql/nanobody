#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_RUN_ROOT:-/data/qlyu/projects/pvrig_top10_md_completion_v1_20260725}"
MDROOT="$ROOT/run/md"
MANIFEST="$MDROOT/md_manifest.tsv"
SOURCE_BASE="$MDROOT/topology"
PRODUCTION_BASE="$MDROOT/production"
STATUS_FILE="$MDROOT/MD_PRODUCTION_STATUS.json"
GMX="${GMX:-/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx}"
PROTOCOL="$MDROOT/protocol"
SLOTS_PER_GPU="${MD_SLOTS_PER_GPU:-4}"
NTOMP_PER_TRAJECTORY="${MD_NTOMP_PER_TRAJECTORY:-2}"
mkdir -p "$PRODUCTION_BASE" "$MDROOT"/{status,logs,locks} "$PROTOCOL"
exec 9>"$MDROOT/locks/md_production.lock"
if ! flock -n 9; then
  echo "another MD production controller owns the lock" >&2
  exit 75
fi

python3 - "$MANIFEST" <<'PY'
import csv,sys
rows=list(csv.DictReader(open(sys.argv[1]),delimiter="\t"))
assert rows
required={"system_id","candidate_id","source_job_id","md_seed","gpu"}
assert not required.difference(rows[0])
keys=[(r["system_id"],r["md_seed"]) for r in rows]
assert len(keys)==len(set(keys))
systems={r["system_id"] for r in rows}
assert len(rows)==3*len(systems)
assert all(len({r["md_seed"] for r in rows if r["system_id"]==system})==3 for system in systems)
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
  # A gracefully interrupted production run may already have written prod.gro.
  # Only the validated 1,000,000-step receipt is terminal; otherwise resume from
  # prod.cpt instead of mistaking a partial final-coordinate file for completion.
  if [[ "$stage" == "prod" ]]; then
    valid_outputs "$d" && return 0
  elif [[ -s "$d/${stage}.gro" ]]; then
    return 0
  fi
  if [[ ! -s "$d/${stage}.tpr" ]]; then
    local args=(-f "$mdp" -c "$input_gro" -r "$input_gro" -p "$d/topol.top" -o "$d/${stage}.tpr" -maxwarn 0)
    [[ -n "$checkpoint" ]] && args+=(-t "$checkpoint")
    "$GMX" grompp "${args[@]}" >"$d/${stage}.grompp.stdout.log" 2>"$d/${stage}.grompp.stderr.log" || return 1
  fi
  local cpi=()
  [[ -s "$d/${stage}.cpt" ]] && cpi=(-cpi "$d/${stage}.cpt" -append)
  if [[ "$stage" == "prod" && -s "$d/${stage}.gro" && ! -s "$d/${stage}.cpt" ]]; then
    echo "incomplete prod.gro exists without a resumable prod.cpt: $d" >&2
    return 1
  fi
  (
    cd "$d"
    CUDA_VISIBLE_DEVICES="$gpu" "$GMX" mdrun -deffnm "$stage" \
      -ntmpi 1 -ntomp "$NTOMP_PER_TRAJECTORY" -pin off \
      -nb gpu -pme gpu -bonded gpu -gpu_id 0 "${cpi[@]}"
  ) >"$d/${stage}.mdrun.stdout.log" 2>"$d/${stage}.mdrun.stderr.log" || return 1
  [[ -s "$d/${stage}.gro" ]]
}

valid_outputs() {
  local d="$1" name
  for name in prod.tpr prod.xtc prod.cpt prod.gro prod.log; do
    [[ -s "$d/$name" ]] || return 1
  done
  grep -q "Finished mdrun on rank 0" "$d/prod.log" || return 1
  python3 - "$d/prod.log" <<'PY'
import re,sys
text=open(sys.argv[1],errors="replace").read()
steps=[int(x) for x in re.findall(r"^\s*(\d+)\s+[0-9]+(?:\.[0-9]+)?\s*$",text,re.M)]
raise SystemExit(0 if steps and steps[-1]>=1_000_000 else 1)
PY
}

run_one() {
  local system_id="$1" source_job_id="$2" seed="$3" gpu="$4"
  local source="$SOURCE_BASE/$system_id"
  local d="$PRODUCTION_BASE/$system_id/seed_$seed"
  mkdir -p "$d"
  exec {job_lock}>"$d/run.lock"
  flock -n "$job_lock" || return 75
  if [[ -s "$d/COMPLETE.json" ]]; then
    valid_outputs "$d" && return 0
    printf '{"state":"FAILED","reason":"INVALID_COMPLETE_OUTPUTS"}\n' > "$d/FAILED.json"
    return 1
  fi
  rm -f "$d/FAILED.json"
  local required=(em.gro topol.top)
  mapfile -t itps < <(find "$source" -maxdepth 1 -type f -name '*.itp' -printf '%f\n' | sort)
  required+=("${itps[@]}")
  for f in "${required[@]}"; do
    [[ -s "$source/$f" ]] || {
      printf '{"state":"FAILED","reason":"SOURCE_FILE_MISSING","file":"%s"}\n' "$f" > "$d/FAILED.json"
      return 1
    }
    [[ -e "$d/$f" ]] || cp --reflink=auto "$source/$f" "$d/$f"
    cmp -s "$source/$f" "$d/$f" || {
      printf '{"state":"FAILED","reason":"FROZEN_FILE_MISMATCH","file":"%s"}\n' "$f" > "$d/FAILED.json"
      return 1
    }
  done
  sed "s/__SEED__/$seed/" "$PROTOCOL/nvt.mdp.template" > "$d/nvt.mdp"
  local start end rc=0
  start="$(date +%s)"
  run_stage "$d" nvt "$d/em.gro" "" "$d/nvt.mdp" "$gpu" || rc=$?
  [[ "$rc" -ne 0 ]] || run_stage "$d" npt "$d/nvt.gro" "$d/nvt.cpt" "$PROTOCOL/npt.mdp" "$gpu" || rc=$?
  [[ "$rc" -ne 0 ]] || run_stage "$d" prod "$d/npt.gro" "$d/npt.cpt" "$PROTOCOL/prod_2ns.mdp" "$gpu" || rc=$?
  end="$(date +%s)"
  if [[ "$rc" -eq 0 ]] && valid_outputs "$d"; then
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
    printf '{"state":"FAILED","return_code":%d,"elapsed_seconds":%d}\n' "$rc" "$((end-start))" > "$d/FAILED.json"
    return 1
  fi
}
export -f run_one run_stage valid_outputs
export SOURCE_BASE PRODUCTION_BASE GMX PROTOCOL NTOMP_PER_TRAJECTORY

run_gpu_queue() {
  local gpu="$1" slot="$2" slots="$3" ordinal=0
  tail -n +2 "$MANIFEST" |
  while IFS=$'\t' read -r system_id candidate_id channel source_job seed row_gpu rest; do
    [[ "$row_gpu" == "$gpu" ]] || continue
    if (( ordinal % slots == slot )); then
      run_one "$system_id" "$source_job" "$seed" "$gpu" || true
    fi
    ordinal=$((ordinal + 1))
  done
}
export -f run_gpu_queue
export MANIFEST

python3 - "$STATUS_FILE.tmp" "$MANIFEST" "$SLOTS_PER_GPU" "$NTOMP_PER_TRAJECTORY" <<'PY'
import csv,json,os,sys
from datetime import datetime,timezone
rows=list(csv.DictReader(open(sys.argv[2]),delimiter="\t"))
total=len(rows)
gpu_count=len({r["gpu"] for r in rows})
slots=int(sys.argv[3]); ntomp=int(sys.argv[4])
json.dump({"state":"RUNNING","pid":os.getppid(),"started_at":datetime.now(timezone.utc).isoformat(),
           "total":total,"completed":0,"failed":0,"production_ns_each":2,
           "gpu_limit":gpu_count,"cpu_limit":gpu_count*slots*ntomp,"slots_per_gpu":slots,
           "ntomp_per_trajectory":ntomp},open(sys.argv[1],"w"),indent=2)
PY
mv "$STATUS_FILE.tmp" "$STATUS_FILE"

mapfile -t gpu_list < <(tail -n +2 "$MANIFEST" | cut -f6 | sort -n -u)
[[ "${#gpu_list[@]}" -le 8 ]] || { echo "manifest exceeds eight GPUs" >&2; exit 64; }
for gpu in "${gpu_list[@]}"; do
  for ((slot = 0; slot < SLOTS_PER_GPU; slot++)); do
    run_gpu_queue "$gpu" "$slot" "$SLOTS_PER_GPU" &
  done
done
wait

python3 - "$MANIFEST" "$PRODUCTION_BASE" "$STATUS_FILE.tmp" "$SLOTS_PER_GPU" "$NTOMP_PER_TRAJECTORY" <<'PY'
import csv,json,sys
from datetime import datetime,timezone
from pathlib import Path
rows=list(csv.DictReader(open(sys.argv[1]),delimiter="\t"))
root=Path(sys.argv[2]); status=Path(sys.argv[3])
gpu_count=len({r["gpu"] for r in rows})
slots=int(sys.argv[4]); ntomp=int(sys.argv[5])
done=sum((root/r["system_id"]/f'seed_{r["md_seed"]}'/"COMPLETE.json").is_file() for r in rows)
failed=sum((root/r["system_id"]/f'seed_{r["md_seed"]}'/"FAILED.json").is_file() for r in rows)
state="COMPLETE" if done==len(rows) and failed==0 else "PARTIAL"
json.dump({"state":state,"updated_at":datetime.now(timezone.utc).isoformat(),
           "total":len(rows),"completed":done,"failed":failed,"production_ns_each":2,
           "gpu_limit":gpu_count,"cpu_limit":gpu_count*slots*ntomp,"slots_per_gpu":slots,
           "ntomp_per_trajectory":ntomp},open(status,"w"),indent=2)
print(json.dumps({"state":state,"completed":done,"failed":failed}))
raise SystemExit(0 if state=="COMPLETE" else 1)
PY
mv "$STATUS_FILE.tmp" "$STATUS_FILE"
