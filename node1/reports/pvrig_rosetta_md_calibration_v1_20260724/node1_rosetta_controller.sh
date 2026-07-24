#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_CALIBRATION_ROOT:-/data/qlyu/projects/pvrig_rosetta_md_calibration_v1_20260724}"
SOURCE_ROOT="${PVRIG_V3_ROOT:-/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714}"
MANIFEST="$ROOT/manifests/ROSETTA_JOB_MANIFEST.tsv"
ROSETTA="${ROSETTA_INTERFACE_ANALYZER:-/data/qlyu/software/rosetta_3.15/main/source/bin/InterfaceAnalyzer.static.linuxgccrelease}"
MAX_PARALLEL="${ROSETTA_MAX_PARALLEL:-4}"

mkdir -p "$ROOT"/{inputs/pdbgz,inputs/pdb,rosetta/jobs,status,logs,locks}
exec 9>"$ROOT/locks/rosetta_controller.lock"
if ! flock -n 9; then
  echo "another Rosetta controller owns the lock" >&2
  exit 75
fi

python3 - "$MANIFEST" "$ROOT/status/ROSETTA_STATUS.json" <<'PY'
import csv,json,os,sys
from datetime import datetime,timezone
rows=list(csv.DictReader(open(sys.argv[1]),delimiter="\t"))
assert len(rows)==150
assert len({r["job_id"] for r in rows})==150
assert all(r["state"]=="SUCCESS" for r in rows)
json.dump({"state":"RUNNING","pid":os.getppid(),"started_at":datetime.now(timezone.utc).isoformat(),
           "total":150,"positive":66,"destructive":84,"completed":0,"failed":0},
          open(sys.argv[2],"w"),indent=2)
PY

run_one() {
  local job_id="$1" source_gz="$2" expected_job_hash="$3"
  local frozen_gz="$ROOT/inputs/pdbgz/${job_id}.pdb.gz"
  local frozen_pdb="$ROOT/inputs/pdb/${job_id}.pdb"
  local job_dir="$ROOT/rosetta/jobs/$job_id"
  local complete="$job_dir/COMPLETE.json"
  local failed="$job_dir/FAILED.json"
  mkdir -p "$job_dir"
  if [[ -s "$complete" ]]; then
    return 0
  fi
  rm -f "$failed"
  if [[ ! -s "$source_gz" ]]; then
    printf '{"state":"FAILED","reason":"SOURCE_MISSING","source":"%s"}\n' "$source_gz" > "$failed"
    return 1
  fi
  if [[ ! -e "$frozen_gz" ]]; then
    cp --reflink=auto "$source_gz" "$frozen_gz.tmp.$$"
    mv "$frozen_gz.tmp.$$" "$frozen_gz"
  elif ! cmp -s "$source_gz" "$frozen_gz"; then
    printf '{"state":"FAILED","reason":"FROZEN_SOURCE_MISMATCH"}\n' > "$failed"
    return 1
  fi
  local gz_sha
  gz_sha="$(sha256sum "$frozen_gz" | awk '{print $1}')"
  if [[ ! -s "$frozen_pdb" ]]; then
    gzip -cd "$frozen_gz" > "$frozen_pdb.tmp.$$"
    mv "$frozen_pdb.tmp.$$" "$frozen_pdb"
  fi
  local chain_set
  chain_set="$(awk '/^(ATOM  |HETATM)/ {a[substr($0,22,1)]=1} END {for(k in a) printf "%s",k}' "$frozen_pdb" | fold -w1 | sort | tr -d '\n')"
  if [[ "$chain_set" != "AT" ]]; then
    printf '{"state":"FAILED","reason":"CHAIN_CONTRACT","observed":"%s"}\n' "$chain_set" > "$failed"
    return 1
  fi
  local start end rc
  start="$(date +%s)"
  set +e
  (
    cd "$job_dir"
    "$ROSETTA" \
      -s "$frozen_pdb" \
      -interface T_A \
      -pack_input true \
      -pack_separated true \
      -compute_packstat true \
      -tracer_data_print true \
      -out:file:score_only score.sc \
      -out:file:scorefile score.sc \
      -overwrite
  ) >"$job_dir/stdout.log" 2>"$job_dir/stderr.log"
  rc=$?
  set -e
  end="$(date +%s)"
  if [[ "$rc" -eq 0 && -s "$job_dir/score.sc" ]]; then
    python3 - "$complete" "$job_id" "$expected_job_hash" "$gz_sha" "$start" "$end" <<'PY'
import json,sys
json.dump({"state":"COMPLETE","job_id":sys.argv[2],"source_job_hash":sys.argv[3],
           "frozen_pdb_gz_sha256":sys.argv[4],"started_epoch":int(sys.argv[5]),
           "finished_epoch":int(sys.argv[6]),"elapsed_seconds":int(sys.argv[6])-int(sys.argv[5]),
           "interface":"T_A"},open(sys.argv[1],"w"),indent=2)
PY
  else
    printf '{"state":"FAILED","return_code":%d,"elapsed_seconds":%d}\n' "$rc" "$((end-start))" > "$failed"
    return 1
  fi
}
export -f run_one
export ROOT SOURCE_ROOT ROSETTA

tail -n +2 "$MANIFEST" |
while IFS=$'\t' read -r job_id entity_id control_class expected_behavior conformation docking_seed state representative_model remote_gz job_hash rest; do
  printf '%s\0%s\0%s\0' "$job_id" "$remote_gz" "$job_hash"
done |
xargs -0 -n3 -P "$MAX_PARALLEL" bash -c 'run_one "$0" "$1" "$2"' || true

python3 - "$ROOT" <<'PY'
import csv,json,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1])
rows=list(csv.DictReader(open(root/"manifests/ROSETTA_JOB_MANIFEST.tsv"),delimiter="\t"))
complete=sum((root/"rosetta/jobs"/r["job_id"]/"COMPLETE.json").is_file() for r in rows)
failed=sum((root/"rosetta/jobs"/r["job_id"]/"FAILED.json").is_file() for r in rows)
state="COMPLETE" if complete==len(rows) and failed==0 else "PARTIAL"
payload={"state":state,"finished_at":datetime.now(timezone.utc).isoformat(),
         "total":len(rows),"completed":complete,"failed":failed}
json.dump(payload,open(root/"status/ROSETTA_STATUS.json","w"),indent=2)
if state=="COMPLETE":
    (root/"status/ROSETTA_COMPLETE").write_text(payload["finished_at"]+"\n")
print(json.dumps(payload))
PY
