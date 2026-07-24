#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_CALIBRATION_ROOT:-/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724}"
MANIFEST="$ROOT/manifests/MD_STAGE_A_MANIFEST.tsv"
GMX="${GMX:-/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx}"
FFROOT="${GMX_FORCE_FIELD_ROOT:-$ROOT/forcefields}"
FF="${GMX_FORCE_FIELD:-charmm36-feb2026_cgenff-5.0}"
WATER="${GMX_WATER_MODEL:-tip3p}"
export GMXLIB="$FFROOT"

mkdir -p "$ROOT"/{md/jobs,status,logs,locks}
exec 9>"$ROOT/locks/md_topology_smoke.lock"
if ! flock -n 9; then
  echo "another MD topology controller owns the lock" >&2
  exit 75
fi

cat > "$ROOT/md/minim.mdp" <<'EOF'
integrator               = steep
emtol                    = 1000.0
emstep                   = 0.01
nsteps                   = 50000
cutoff-scheme            = Verlet
nstlist                  = 20
coulombtype              = PME
rcoulomb                 = 1.2
vdwtype                  = Cut-off
vdw-modifier             = Force-switch
rvdw-switch              = 1.0
rvdw                     = 1.2
DispCorr                  = no
pbc                      = xyz
constraints              = h-bonds
EOF

run_one() {
  local pair_id="$1" pair_role="$2" job_id="$3"
  local source_pdb="$ROOT/inputs/pdb/${job_id}.pdb"
  local d="$ROOT/md/jobs/${pair_id}_${pair_role}"
  mkdir -p "$d"
  if [[ -s "$d/COMPLETE.json" ]]; then return 0; fi
  if [[ ! -s "$source_pdb" ]]; then
    printf '{"state":"BLOCKED","reason":"ROSETTA_FROZEN_INPUT_MISSING"}\n' > "$d/BLOCKED.json"
    return 1
  fi
  rm -f "$d/BLOCKED.json" "$d/FAILED.json"
  awk '/^(ATOM  |TER|END)/' "$source_pdb" > "$d/complex.pdb"
  local start="$(date +%s)" rc=0
  (
    cd "$d"
    "$GMX" pdb2gmx -f complex.pdb -o processed.gro -p topol.top -i posre.itp \
      -ff "$FF" -water "$WATER" -ignh
    "$GMX" editconf -f processed.gro -o boxed.gro -c -d 1.0 -bt dodecahedron
    "$GMX" solvate -cp boxed.gro -cs spc216.gro -o solv.gro -p topol.top
    "$GMX" grompp -f "$ROOT/md/minim.mdp" -c solv.gro -p topol.top -o ions.tpr -maxwarn 1
    printf 'SOL\n' | "$GMX" genion -s ions.tpr -o solv_ions.gro -p topol.top \
      -pname NA -nname CL -neutral -conc 0.15
    "$GMX" grompp -f "$ROOT/md/minim.mdp" -c solv_ions.gro -p topol.top -o em.tpr -maxwarn 1
    "$GMX" mdrun -deffnm em -ntmpi 1 -ntomp 8
  ) >"$d/stdout.log" 2>"$d/stderr.log" || rc=$?
  local end="$(date +%s)"
  if [[ "$rc" -eq 0 && -s "$d/em.tpr" && -s "$d/em.gro" && -s "$d/topol.top" ]]; then
    python3 - "$d/COMPLETE.json" "$pair_id" "$pair_role" "$job_id" "$FF" "$WATER" "$start" "$end" <<'PY'
import json,sys
json.dump({"state":"COMPLETE","pair_id":sys.argv[2],"pair_role":sys.argv[3],
           "job_id":sys.argv[4],"force_field":sys.argv[5],"water_model":sys.argv[6],
           "started_epoch":int(sys.argv[7]),"finished_epoch":int(sys.argv[8]),
           "elapsed_seconds":int(sys.argv[8])-int(sys.argv[7]),"em_tpr_ready":True,
           "energy_minimization_complete":True},
          open(sys.argv[1],"w"),indent=2)
PY
  else
    printf '{"state":"FAILED","return_code":%d,"elapsed_seconds":%d}\n' "$rc" "$((end-start))" > "$d/FAILED.json"
    return 1
  fi
}

tail -n +2 "$MANIFEST" |
while IFS=$'\t' read -r pair_id pair_role job_id rest; do
  run_one "$pair_id" "$pair_role" "$job_id" || true
done

python3 - "$ROOT" <<'PY'
import csv,json,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1])
rows=list(csv.DictReader(open(root/"manifests/MD_STAGE_A_MANIFEST.tsv"),delimiter="\t"))
done=sum((root/"md/jobs"/f'{r["pair_id"]}_{r["pair_role"]}'/"COMPLETE.json").is_file() for r in rows)
failed=sum((root/"md/jobs"/f'{r["pair_id"]}_{r["pair_role"]}'/"FAILED.json").is_file() for r in rows)
payload={"state":"TOPOLOGY_AND_MINIMIZATION_COMPLETE" if done==len(rows) and not failed else "PARTIAL",
         "updated_at":datetime.now(timezone.utc).isoformat(),"total":len(rows),
         "completed":done,"failed":failed}
json.dump(payload,open(root/"status/MD_TOPOLOGY_STATUS.json","w"),indent=2)
print(json.dumps(payload))
PY
