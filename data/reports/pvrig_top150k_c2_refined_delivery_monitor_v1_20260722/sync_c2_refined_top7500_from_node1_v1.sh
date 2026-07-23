#!/usr/bin/env bash
set -euo pipefail
umask 027
SSH=/mnt/c/Windows/System32/OpenSSH/ssh.exe
REMOTE_HOST=node1
REMOTE_ROOT=/data1/qlyu/projects/pvrig_1m_fixed_pose_top150k_surrogate_ensemble_v1_20260722
REMOTE_FINAL=c2_refined_top7500_docking_handoff_v1
REMOTE_TERMINAL=status/C2_REFINED_TOP7500_PUBLICATION_VERIFIED.json
LOCAL_ROOT=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/prepared
LOCAL_FINAL="$LOCAL_ROOT/pvrig_top150k_c2_refined_top7500_v1_20260722"
MON=/mnt/d/work/抗体/data/reports/pvrig_top150k_c2_refined_delivery_monitor_v1_20260722
STATUS="$MON/SYNC_LIVE_STATUS.json"
LOG="$MON/SYNC_MONITOR.log"
mkdir -p "$LOCAL_ROOT" "$MON"
write_status() {
  local status="$1" message="$2"
  python3 - "$STATUS" "$status" "$message" <<'PY'
import json,os,sys
from datetime import datetime,timezone
p,status,msg=sys.argv[1:]
d={"schema_version":"pvrig_top150k_c2_refined_local_sync_status_v1","status":status,"message":msg,"updated_at_utc":datetime.now(timezone.utc).isoformat()}
t=p+".tmp";open(t,"w").write(json.dumps(d,indent=2,sort_keys=True)+"\n");os.replace(t,p)
PY
}
verify_existing() {
  [[ -d "$LOCAL_FINAL" ]] || return 1
  (cd "$LOCAL_FINAL" && sha256sum -c SHA256SUMS >/dev/null) || return 1
  python3 - "$LOCAL_FINAL/RUN_RECEIPT.json" "$LOCAL_FINAL/PUBLICATION_VERIFICATION.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]));v=json.load(open(sys.argv[2]))
assert d["status"]=="PASS_C2_REFINED_TOP7500_DOCKING_READY"
assert d["rows"]==7500
assert d["invariants"]["teacher_label_values_read"]==0
assert d["invariants"]["candidate_docking_pose_files_opened"]==0
assert v["status"]=="PASS_C2_REFINED_TOP7500_PUBLICATION_VERIFIED"
PY
}
if verify_existing; then
  write_status PASS_LOCAL_REFINED_TOP7500_READY existing_delivery_verified
  exit 0
fi
write_status WAITING_REMOTE_REFINED_TOP7500 remote_terminal_not_ready
while true; do
  if "$SSH" -o BatchMode=yes -o ConnectTimeout=20 "$REMOTE_HOST"        "test -s '$REMOTE_ROOT/$REMOTE_TERMINAL' -a -s '$REMOTE_ROOT/$REMOTE_FINAL/RUN_RECEIPT.json'"        >>"$LOG" 2>&1; then
    break
  fi
  sleep 60
done
write_status COPYING_REMOTE_REFINED_TOP7500 remote_terminal_ready
TMP="$LOCAL_ROOT/.pvrig_top150k_c2_refined_top7500_v1_20260722.$$.tmp"
rm -rf "$TMP"; mkdir -p "$TMP"
copied=0
for attempt in 1 2 3 4 5; do
  find "$TMP" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  if "$SSH" -o BatchMode=yes -o ConnectTimeout=30 "$REMOTE_HOST"       "cd '$REMOTE_ROOT' && tar -cf - '$REMOTE_FINAL' '$REMOTE_TERMINAL'"       2>>"$LOG" | tar -C "$TMP" -xf - >>"$LOG" 2>&1; then
    copied=1; break
  fi
  sleep 30
done
[[ "$copied" == 1 ]]
SRC="$TMP/$REMOTE_FINAL"
PUBLICATION="$TMP/$REMOTE_TERMINAL"
(cd "$SRC" && sha256sum -c SHA256SUMS) >>"$LOG" 2>&1
python3 - "$PUBLICATION" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d["schema_version"]=="pvrig_v2_19_c2_refined_top7500_publication_verification_v1"
assert d["status"]=="PASS_C2_REFINED_TOP7500_PUBLICATION_VERIFIED"
PY
python3 - "$SRC/RUN_RECEIPT.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d["schema_version"]=="pvrig_v2_19_c2_refined_top7500_v1"
assert d["status"]=="PASS_C2_REFINED_TOP7500_DOCKING_READY"
assert d["rows"]==7500
assert sum(d["channels"].values())==7500
assert d["invariants"]["candidate_set_subset_of_frozen_top30000"] is True
assert d["invariants"]["sequence_sha256_join_exact"] is True
assert d["invariants"]["final_quota_exact"] is True
assert d["invariants"]["teacher_label_values_read"]==0
assert d["invariants"]["candidate_docking_pose_files_opened"]==0
PY
[[ ! -e "$LOCAL_FINAL" ]]
mv "$SRC" "$LOCAL_FINAL"
cp "$PUBLICATION" "$LOCAL_FINAL/PUBLICATION_VERIFICATION.json"
rm -rf "$TMP"
python3 - "$LOCAL_FINAL/RUN_RECEIPT.json" "$MON/LOCAL_SYNC_RECEIPT.json" <<'PY'
import hashlib,json,os,sys
from datetime import datetime,timezone
src,out=sys.argv[1:]
d=json.load(open(src))
payload={"schema_version":"pvrig_top150k_c2_refined_local_sync_receipt_v1","status":"PASS_LOCAL_REFINED_TOP7500_READY","synced_at_utc":datetime.now(timezone.utc).isoformat(),"rows":d["rows"],"remote_run_receipt_sha256":hashlib.sha256(open(src,"rb").read()).hexdigest(),"local_directory":os.path.dirname(src),"claim_boundary":d["claim_boundary"]}
t=out+".tmp";open(t,"w").write(json.dumps(payload,indent=2,sort_keys=True)+"\n");os.replace(t,out)
PY
write_status PASS_LOCAL_REFINED_TOP7500_READY verified_hash_closed_delivery
