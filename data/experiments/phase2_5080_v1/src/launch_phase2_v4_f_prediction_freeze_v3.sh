#!/usr/bin/env bash
set -Eeuo pipefail

EXP=/mnt/d/work/抗体/data/experiments/phase2_5080_v1
PYTHON=$EXP/.venv-phase2-5080/bin/python
WATCHER=$EXP/src/monitor_phase2_v4_f_prediction_freeze_v3.sh
ANCHOR=$EXP/audits/phase2_v4_f_prediction_freeze_v3_implementation_trust_anchor.json
ANCHOR_SHA=31f7f2cc66fcee3dcf665b76fd2a4985be3ce9d64460dd74956d776e4ee9197e
SURROGATE_ANCHOR_SHA=bddee8dc7a303b7239641bf0e74317ee2af8a7509506564714227b5118a6ef11
STATUS_DIR=$EXP/status/pvrig_v4_f_prediction_freeze_v3

[[ -x "$PYTHON" && -f "$WATCHER" && -f "$ANCHOR" ]]
observed=$(sha256sum "$ANCHOR" | awk '{print $1}')
[[ "$observed" == "$ANCHOR_SHA" ]] || {
  echo "V4-F V3 trust-anchor hash mismatch: $observed != $ANCHOR_SHA" >&2
  exit 2
}

mkdir -p "$STATUS_DIR"
env -i HOME="${HOME:-/root}" USER="${USER:-root}" LANG=C.UTF-8 \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LAUNCHER_PATH=$0 WATCHER_PATH=$WATCHER ANCHOR_PATH=$ANCHOR \
  ANCHOR_SHA_VALUE=$ANCHOR_SHA SURROGATE_ANCHOR_SHA_VALUE=$SURROGATE_ANCHOR_SHA \
  "$PYTHON" - "$STATUS_DIR/launcher_receipt.json" <<'PY'
import hashlib, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
path=Path(sys.argv[1])
def digest(value): return hashlib.sha256(Path(value).read_bytes()).hexdigest()
payload={
 "schema_version":"phase2_v4_f_prediction_v3_launcher_receipt_v1",
 "status":"PASS_LAUNCHER_BOUND_BEFORE_EXEC",
 "launcher":{"path":str(Path(os.environ["LAUNCHER_PATH"]).resolve()),"sha256":digest(os.environ["LAUNCHER_PATH"])},
 "watcher":{"path":str(Path(os.environ["WATCHER_PATH"]).resolve()),"sha256":digest(os.environ["WATCHER_PATH"])},
 "trust_anchor":{"path":str(Path(os.environ["ANCHOR_PATH"]).resolve()),"sha256":os.environ["ANCHOR_SHA_VALUE"]},
 "surrogate_trust_anchor_sha256":os.environ["SURROGATE_ANCHOR_SHA_VALUE"],
 "v4_f_labels_read":False,
 "v4_f_label_paths_accepted":0,
 "created_at":datetime.now(timezone.utc).isoformat(),
}
with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,delete=False) as handle:
 json.dump(payload,handle,indent=2,sort_keys=True); handle.write("\n"); tmp=Path(handle.name)
tmp.replace(path)
PY

exec env -i \
  HOME="${HOME:-/root}" \
  USER="${USER:-root}" \
  LANG=C.UTF-8 \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  PVRIG_EXP_DIR="$EXP" \
  V4F_V3_TRUST_ANCHOR="$ANCHOR" \
  V4F_V3_EXPECTED_TRUST_ANCHOR_SHA="$ANCHOR_SHA" \
  V4D_V3_EXPECTED_TRUST_ANCHOR_SHA="$SURROGATE_ANCHOR_SHA" \
  "$WATCHER"
