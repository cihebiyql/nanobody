#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_RUN_ROOT:-/data/qlyu/projects/pvrig_top10_md_completion_v1_20260725}"
MDROOT="$ROOT/run/md"
MANIFEST="$MDROOT/md_systems.tsv"
OUT="$MDROOT/topology"
STATUS="$MDROOT/MD_TOPOLOGY_STATUS.json"
GMX="${GMX:-/data/qlyu/software/gromacs-2024.4-cuda/bin/gmx}"
FFROOT="${GMX_FORCE_FIELD_ROOT:-/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724/forcefields}"
FF="${GMX_FORCE_FIELD:-charmm36-feb2026_cgenff-5.0}"
export GMXLIB="$FFROOT"
mkdir -p "$OUT" "$MDROOT"/{protocol,logs,locks}
exec 9>"$MDROOT/locks/md_topology.lock"
if ! flock -n 9; then
  echo "another MD topology controller owns the lock" >&2
  exit 75
fi

python3 - "$MANIFEST" <<'PY'
import csv,sys
rows=list(csv.DictReader(open(sys.argv[1]),delimiter="\t"))
assert rows
assert len({r["system_id"] for r in rows})==len(rows)
PY

MINIM="$MDROOT/protocol/minim.mdp"
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
  local system_id="$1" source_pdb="$2" source_hash="$3"
  local d="$OUT/$system_id"
  mkdir -p "$d"
  exec {lock_fd}>"$d/run.lock"
  flock -n "$lock_fd" || return 75
  if [[ -s "$d/COMPLETE.json" ]]; then
    local observed
    observed="$(sha256sum "$source_pdb" | awk '{print $1}')"
    [[ "$observed" == "$source_hash" ]] || return 65
    [[ -s "$d/em.gro" && -s "$d/topol.top" ]] || return 66
    return 0
  fi
  rm -f "$d/FAILED.json"
  [[ -s "$source_pdb" ]] || {
    printf '{"state":"FAILED","reason":"SOURCE_PDB_MISSING"}\n' > "$d/FAILED.json"
    return 1
  }
  local observed
  observed="$(sha256sum "$source_pdb" | awk '{print $1}')"
  [[ "$observed" == "$source_hash" ]] || {
    printf '{"state":"FAILED","reason":"SOURCE_HASH_MISMATCH"}\n' > "$d/FAILED.json"
    return 1
  }
  if [[ ! -s "$d/complex.pdb" ]]; then
    cp --reflink=auto "$source_pdb" "$d/complex.pdb.tmp.$$"
    mv "$d/complex.pdb.tmp.$$" "$d/complex.pdb"
  elif ! cmp -s "$source_pdb" "$d/complex.pdb"; then
    printf '{"state":"FAILED","reason":"FROZEN_COMPLEX_MISMATCH"}\n' > "$d/FAILED.json"
    return 1
  fi
  local start end rc=0
  start="$(date +%s)"
  (
    set -e
    cd "$d"
    "$GMX" pdb2gmx -f complex.pdb -o processed.gro -p topol.top -i posre.itp \
      -ff "$FF" -water tip3p -ignh
    "$GMX" editconf -f processed.gro -o boxed.gro -c -d 1.0 -bt dodecahedron
    "$GMX" solvate -cp boxed.gro -cs spc216.gro -o solv.gro -p topol.top
    "$GMX" grompp -f "$MINIM" -c solv.gro -p topol.top -o ions.tpr -maxwarn 1
    printf 'SOL\n' | "$GMX" genion -s ions.tpr -o solv_ions.gro -p topol.top \
      -pname NA -nname CL -neutral -conc 0.15
    "$GMX" grompp -f "$MINIM" -c solv_ions.gro -p topol.top -o em.tpr
    "$GMX" mdrun -deffnm em -ntmpi 1 -ntomp 8 -pin on
  ) >"$d/stdout.log" 2>"$d/stderr.log" || rc=$?
  end="$(date +%s)"
  if [[ "$rc" -eq 0 && -s "$d/em.gro" && -s "$d/topol.top" ]] &&
     grep -q "Finished mdrun on rank 0" "$d/em.log"; then
    python3 - "$d/COMPLETE.json.tmp.$$" "$system_id" "$source_pdb" "$source_hash" "$start" "$end" <<'PY'
import json,sys
json.dump({"state":"COMPLETE","system_id":sys.argv[2],"source_pdb":sys.argv[3],
           "source_pdb_sha256":sys.argv[4],"started_epoch":int(sys.argv[5]),
           "finished_epoch":int(sys.argv[6]),"elapsed_seconds":int(sys.argv[6])-int(sys.argv[5])},
          open(sys.argv[1],"w"),indent=2)
PY
    mv "$d/COMPLETE.json.tmp.$$" "$d/COMPLETE.json"
  else
    printf '{"state":"FAILED","return_code":%d,"elapsed_seconds":%d}\n' \
      "$rc" "$((end-start))" > "$d/FAILED.json.tmp.$$"
    mv "$d/FAILED.json.tmp.$$" "$d/FAILED.json"
    return 1
  fi
}
export -f run_one
export OUT GMX FF MINIM GMXLIB

tail -n +2 "$MANIFEST" |
while IFS=$'\t' read -r system_id candidate_id top80_rank channel route parent cluster cdr3 source_job conformation source_pdb source_hash rest; do
  printf '%s\0%s\0%s\0' "$system_id" "$source_pdb" "$source_hash"
done |
xargs -0 -n3 -P3 bash -c 'run_one "$0" "$1" "$2"' || true

python3 - "$MANIFEST" "$OUT" "$STATUS.tmp" <<'PY'
import csv,json,sys
from datetime import datetime,timezone
from pathlib import Path
manifest,out,status=Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3])
rows=list(csv.DictReader(open(manifest),delimiter="\t"))
done=sum((out/r["system_id"]/"COMPLETE.json").is_file() for r in rows)
failed=sum((out/r["system_id"]/"FAILED.json").is_file() for r in rows)
state="COMPLETE" if done==len(rows) and failed==0 else "PARTIAL"
json.dump({"state":state,"updated_at":datetime.now(timezone.utc).isoformat(),
           "total":len(rows),"completed":done,"failed":failed,"cpu_limit":24},
          open(status,"w"),indent=2)
print(json.dumps({"state":state,"completed":done,"failed":failed}))
raise SystemExit(0 if state=="COMPLETE" else 1)
PY
mv "$STATUS.tmp" "$STATUS"
