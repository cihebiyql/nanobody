#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_CALIBRATION_ROOT:-/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724}"
MANIFEST="$ROOT/manifests/MD_EXPANSION_SYSTEMS.tsv"
GMX="${GMX:-/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx}"
FFROOT="$ROOT/forcefields"
FF="charmm36-feb2026_cgenff-5.0"
OUT="$ROOT/md/expansion/jobs"
STATUS="$ROOT/status/MD_EXPANSION_TOPOLOGY_STATUS.json"
export GMXLIB="$FFROOT"
mkdir -p "$OUT" "$ROOT"/{status,logs,locks}
exec 9>"$ROOT/locks/md_expansion_topology.lock"
if ! flock -n 9; then
  echo "another expansion topology controller owns the lock" >&2
  exit 75
fi

MINIM="$ROOT/md/expansion/minim.mdp"
mkdir -p "$(dirname "$MINIM")"
cat > "$MINIM" <<'EOF'
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
  local system_id="$1" source_job_id="$2" source_hash="$3" source_rel="$4"
  local source="$ROOT/$source_rel"
  local d="$OUT/$system_id"
  mkdir -p "$d"
  exec {lock_fd}>"$d/run.lock"
  if ! flock -n "$lock_fd"; then return 75; fi
  if [[ -s "$d/COMPLETE.json" ]]; then return 0; fi
  rm -f "$d/FAILED.json"
  if [[ ! -s "$source" ]]; then
    printf '{"state":"FAILED","reason":"SOURCE_PDB_MISSING"}\n' > "$d/FAILED.json"
    return 1
  fi
  if [[ ! -s "$d/complex.pdb" ]]; then
    awk '/^(ATOM  |TER|END)/' "$source" > "$d/complex.pdb"
  fi
  local start="$(date +%s)" rc=0
  (
    set -e
    cd "$d"
    "$GMX" pdb2gmx -f complex.pdb -o processed.gro -p topol.top -i posre.itp \
      -ff "$FF" -water tip3p -ignh
    "$GMX" editconf -f processed.gro -o boxed.gro -c -d 1.0 -bt dodecahedron
    "$GMX" solvate -cp boxed.gro -cs spc216.gro -o solv.gro -p topol.top
    # Audited exception: the pre-genion system can be charged by construction.
    # Exactly this stage may pass the net-charge PME warning; the post-genion
    # minimization grompp below remains strict.
    "$GMX" grompp -f "$MINIM" -c solv.gro -p topol.top -o ions.tpr -maxwarn 1
    printf 'SOL\n' | "$GMX" genion -s ions.tpr -o solv_ions.gro -p topol.top \
      -pname NA -nname CL -neutral -conc 0.15
    "$GMX" grompp -f "$MINIM" -c solv_ions.gro -p topol.top -o em.tpr
    "$GMX" mdrun -deffnm em -ntmpi 1 -ntomp 8 -pin on
  ) >"$d/stdout.log" 2>"$d/stderr.log" || rc=$?
  local end="$(date +%s)"
  if [[ "$rc" -eq 0 && -s "$d/em.gro" ]] &&
     grep -q "Finished mdrun on rank 0" "$d/em.log"; then
    python3 - "$d/COMPLETE.json.tmp" "$system_id" "$source_job_id" "$source_hash" "$source" "$start" "$end" <<'PY'
import hashlib,json,os,sys
p=sys.argv[5]
h=hashlib.sha256(open(p,"rb").read()).hexdigest()
json.dump({"state":"COMPLETE","system_id":sys.argv[2],"source_job_id":sys.argv[3],
           "source_job_hash":sys.argv[4],"source_pdb":p,"source_pdb_sha256":h,
           "started_epoch":int(sys.argv[6]),"finished_epoch":int(sys.argv[7]),
           "elapsed_seconds":int(sys.argv[7])-int(sys.argv[6])},
          open(sys.argv[1],"w"),indent=2)
PY
    mv "$d/COMPLETE.json.tmp" "$d/COMPLETE.json"
  else
    printf '{"state":"FAILED","return_code":%d,"elapsed_seconds":%d}\n' "$rc" "$((end-start))" \
      > "$d/FAILED.json.tmp"
    mv "$d/FAILED.json.tmp" "$d/FAILED.json"
    return 1
  fi
}
export -f run_one
export ROOT OUT GMX FF MINIM GMXLIB

tail -n +2 "$MANIFEST" |
while IFS=$'\t' read -r system_id pair_id pair_role source_job_id entity_id source_hash source_rel rest; do
  printf '%s\0%s\0%s\0%s\0' "$system_id" "$source_job_id" "$source_hash" "$source_rel"
done |
xargs -0 -n4 -P3 bash -c 'run_one "$0" "$1" "$2" "$3"' || true

python3 - "$ROOT" "$MANIFEST" "$OUT" "$STATUS.tmp" <<'PY'
import csv,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
root,manifest,out,status=Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4])
rows=list(csv.DictReader(open(manifest),delimiter="\t"))
done=sum((out/r["system_id"]/"COMPLETE.json").is_file() for r in rows)
failed=sum((out/r["system_id"]/"FAILED.json").is_file() for r in rows)
state="COMPLETE" if done==len(rows) and failed==0 else "PARTIAL"
json.dump({"state":state,"updated_at":datetime.now(timezone.utc).isoformat(),
           "total":len(rows),"completed":done,"failed":failed},open(status,"w"),indent=2)
print(json.dumps({"state":state,"completed":done,"failed":failed}))
PY
mv "$STATUS.tmp" "$STATUS"
