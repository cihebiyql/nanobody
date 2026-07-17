#!/usr/bin/env bash
set -Eeuo pipefail

EXP=/mnt/d/work/抗体/data/experiments/phase2_5080_v1
PYTHON=$EXP/.venv-phase2-5080/bin/python
WATCHER=$EXP/src/monitor_phase2_v4_d_surrogate_training_v2.sh
ANCHOR=$EXP/audits/phase2_v4_d_surrogate_training_v2_implementation_trust_anchor.json
ANCHOR_SHA=9d5aff568b9473a56c6111fae6221266eabe09f92be7752c76bbc596ef2d74cf
STATUS_DIR=$EXP/status/pvrig_v4_d_surrogate_training_v2

[[ -x "$PYTHON" && -f "$WATCHER" && -f "$ANCHOR" ]]
observed=$(sha256sum "$ANCHOR" | awk '{print $1}')
[[ "$observed" == "$ANCHOR_SHA" ]] || {
  echo "surrogate V2 trust-anchor hash mismatch: $observed != $ANCHOR_SHA" >&2
  exit 2
}

mkdir -p "$STATUS_DIR"
LAUNCHER_PATH=$0 WATCHER_PATH=$WATCHER ANCHOR_PATH=$ANCHOR ANCHOR_SHA_VALUE=$ANCHOR_SHA \
  "$PYTHON" - "$STATUS_DIR/launcher_receipt.json" <<'PY'
import hashlib, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
path=Path(sys.argv[1])
def digest(value): return hashlib.sha256(Path(value).read_bytes()).hexdigest()
payload={
 "schema_version":"phase2_v4_d_surrogate_v2_launcher_receipt_v1",
 "status":"PASS_LAUNCHER_BOUND_BEFORE_EXEC",
 "launcher":{"path":str(Path(os.environ["LAUNCHER_PATH"]).resolve()),"sha256":digest(os.environ["LAUNCHER_PATH"])},
 "watcher":{"path":str(Path(os.environ["WATCHER_PATH"]).resolve()),"sha256":digest(os.environ["WATCHER_PATH"])},
 "trust_anchor":{"path":str(Path(os.environ["ANCHOR_PATH"]).resolve()),"sha256":os.environ["ANCHOR_SHA_VALUE"]},
 "prospective_test_labels_read":False,
 "prospective_test_label_paths_accepted":0,
 "created_at":datetime.now(timezone.utc).isoformat(),
}
with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,delete=False) as handle:
 json.dump(payload,handle,indent=2,sort_keys=True); handle.write("\n"); tmp=Path(handle.name)
tmp.replace(path)
PY

exec env \
  PVRIG_EXP_DIR="$EXP" \
  PYTHON="$PYTHON" \
  V4D_V2_TRUST_ANCHOR="$ANCHOR" \
  V4D_V2_EXPECTED_TRUST_ANCHOR_SHA="$ANCHOR_SHA" \
  "$WATCHER"
