#!/usr/bin/env bash
set -euo pipefail

ROOT="${PVRIG_RUN_ROOT:-/data/qlyu/projects/pvrig_top10_md_completion_v1_20260725}"
MDROOT="$ROOT/run/md"
STATUS="$ROOT/CONTROLLER_STATUS.json"
LOG="$ROOT/controller.log"
mkdir -p "$MDROOT/locks"
exec 9>"$MDROOT/locks/controller.lock"
if ! flock -n 9; then
  echo "another Top10 MD completion controller owns the lock" >&2
  exit 75
fi

write_status() {
  local state="$1" stage="$2" rc="${3:-0}"
  python3 - "$STATUS.tmp.$$" "$state" "$stage" "$rc" <<'PY'
import json,os,sys
from datetime import datetime,timezone
json.dump(
    {
        "schema_version": "pvrig.top10.md_completion.controller.v1",
        "state": sys.argv[2],
        "stage": sys.argv[3],
        "return_code": int(sys.argv[4]),
        "pid": os.getppid(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
    open(sys.argv[1], "w"),
    indent=2,
)
PY
  mv "$STATUS.tmp.$$" "$STATUS"
}

fail() {
  local rc=$?
  write_status FAILED "${CURRENT_STAGE:-UNKNOWN}" "$rc"
  exit "$rc"
}
trap fail ERR

CURRENT_STAGE=READY_VALIDATION
if [[ ! -e "$ROOT/READY.json" ]]; then
python3 - "$MDROOT" "$ROOT/READY.json.tmp.$$" <<'PY'
import csv,hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path

mdroot=Path(sys.argv[1]); out=Path(sys.argv[2])
systems=list(csv.DictReader(open(mdroot/"md_systems.tsv"),delimiter="\t"))
jobs=list(csv.DictReader(open(mdroot/"md_manifest.tsv"),delimiter="\t"))
assert len(systems)==6
assert len(jobs)==18
assert len({r["candidate_id"] for r in systems})==6
assert len({(r["system_id"],r["md_seed"]) for r in jobs})==18
assert {int(r["md_seed"]) for r in jobs}=={917,1931,3253}
for row in systems:
    path=Path(row["source_pdb"])
    assert path.is_file()
    observed=hashlib.sha256(path.read_bytes()).hexdigest()
    assert observed==row["source_pdb_sha256"]
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
json.dump(
    {
        "schema_version":"pvrig.top10.md.completion.ready.v1",
        "state":"READY",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "candidates":6,
        "trajectories":18,
        "production_ns_each":2,
        "seeds":[917,1931,3253],
        "gpus":sorted({int(r["gpu"]) for r in jobs}),
        "hashes":{
            "md_systems.tsv":sha(mdroot/"md_systems.tsv"),
            "md_manifest.tsv":sha(mdroot/"md_manifest.tsv"),
        },
        "claim_boundary":"Descriptive pose-persistence evidence only.",
    },
    open(out,"w"),
    indent=2,
)
PY
mv "$ROOT/READY.json.tmp.$$" "$ROOT/READY.json"
else
  python3 - "$ROOT/READY.json" "$MDROOT/md_systems.tsv" "$MDROOT/md_manifest.tsv" <<'PY'
import hashlib,json,sys
x=json.load(open(sys.argv[1]))
assert x["state"]=="READY" and x["candidates"]==6 and x["trajectories"]==18
for path in sys.argv[2:]:
    observed=hashlib.sha256(open(path,"rb").read()).hexdigest()
    assert x["hashes"][path.rsplit("/",1)[-1]]==observed
PY
fi

write_status RUNNING "$CURRENT_STAGE"

CURRENT_STAGE=TOPOLOGY
write_status RUNNING "$CURRENT_STAGE"
PVRIG_RUN_ROOT="$ROOT" "$ROOT/run_top10_md_completion_topology.sh"
python3 - "$MDROOT/MD_TOPOLOGY_STATUS.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
assert x["state"]=="COMPLETE" and x["completed"]==6 and x["failed"]==0
PY

CURRENT_STAGE=PRODUCTION
write_status RUNNING "$CURRENT_STAGE"
PVRIG_RUN_ROOT="$ROOT" MD_SLOTS_PER_GPU=1 MD_NTOMP_PER_TRAJECTORY=2 \
  "$ROOT/run_top10_md_completion_production.sh"
python3 - "$MDROOT/MD_PRODUCTION_STATUS.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
assert x["state"]=="COMPLETE" and x["completed"]==18 and x["failed"]==0
PY

CURRENT_STAGE=ANALYSIS
write_status RUNNING "$CURRENT_STAGE"
python3 "$ROOT/analyze_top10_md_completion.py" --root "$ROOT"

CURRENT_STAGE=COMPLETE
python3 - "$ROOT" "$ROOT/COMPLETE.json.tmp.$$" <<'PY'
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1]); out=Path(sys.argv[2])
reports=root/"run/md/reports"
files=[
    reports/"md_trajectory_metrics.tsv",
    reports/"md_candidate_summary.tsv",
    reports/"TOP10_MD_COMPLETION_ANALYSIS_COMPLETE.json",
]
assert all(path.is_file() for path in files)
json.dump(
    {
        "schema_version":"pvrig.top10.md.completion.complete.v1",
        "state":"COMPLETE",
        "created_at":datetime.now(timezone.utc).isoformat(),
        "candidates":6,
        "trajectories":18,
        "production_ns_each":2,
        "hashes":{path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
        "claim_boundary":"Descriptive pose-persistence evidence only.",
    },
    open(out,"w"),
    indent=2,
)
PY
if [[ ! -e "$ROOT/COMPLETE.json" ]]; then
  mv "$ROOT/COMPLETE.json.tmp.$$" "$ROOT/COMPLETE.json"
else
  cmp -s "$ROOT/COMPLETE.json.tmp.$$" "$ROOT/COMPLETE.json" || {
    echo "existing COMPLETE receipt differs" >&2
    exit 65
  }
  rm -f "$ROOT/COMPLETE.json.tmp.$$"
fi
write_status COMPLETE COMPLETE
trap - ERR
echo "Top10 MD completion pipeline finished" | tee -a "$LOG"
