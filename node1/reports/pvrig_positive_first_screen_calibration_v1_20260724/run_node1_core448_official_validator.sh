#!/usr/bin/env bash
set -euo pipefail

PROJECT=/data1/qlyu/projects/pvrig_core448_positive_calibrated_v1_20260724
CLOSURE=/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716/runtime_closure
INPUT="$PROJECT/qc_out/core448.official_submit.xlsx"
OUTPUT="$PROJECT/qc_out/official_failed_reasons_full.csv"
LOG="$PROJECT/logs"
STATUS="$PROJECT/status"

mkdir -p "$LOG" "$STATUS"
exec 8>"$STATUS/official_validator.lock"
if ! flock -n 8; then
  echo "official validator already locked"
  exit 0
fi
if [[ -s "$STATUS/OFFICIAL_COMPLETE" ]]; then
  echo "official validator already complete"
  exit 0
fi
if [[ ! -s "$INPUT" ]]; then
  echo "missing official validator input: $INPUT" >&2
  exit 2
fi

printf '%s\n' "$$" >"$STATUS/official_validator.pid"
printf '{"status":"RUNNING","pid":%s,"started_at":"%s"}\n' \
  "$$" "$(date --iso-8601=seconds)" >"$STATUS/OFFICIAL_STATUS.json"

set +e
/usr/bin/time -v "$CLOSURE/bin/ab-data-validator" validate \
  --input "$INPUT" \
  --output "$OUTPUT" \
  --identity-threshold 0.8 \
  --anarci-bin "$CLOSURE/bin/ANARCI" \
  --muscle-bin "$CLOSURE/bin/muscle" \
  --workers 4 \
  >"$LOG/official_validator_full.stdout.log" \
  2>"$LOG/official_validator_full.stderr.log"
rc=$?
set -e

if [[ "$rc" -ne 0 ]]; then
  printf '{"status":"FAILED","pid":%s,"return_code":%s,"finished_at":"%s"}\n' \
    "$$" "$rc" "$(date --iso-8601=seconds)" >"$STATUS/OFFICIAL_STATUS.json"
  exit "$rc"
fi

python3 - "$OUTPUT" "$STATUS" <<'PY'
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

output = Path(sys.argv[1])
status_dir = Path(sys.argv[2])
rows = []
if output.exists() and output.stat().st_size:
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

candidate_key = next(
    (key for key in (rows[0].keys() if rows else []) if key.lower() in {"candidate_id", "antibody_id", "name", "id"}),
    None,
)
reason_key = next(
    (key for key in (rows[0].keys() if rows else []) if "reason" in key.lower()),
    None,
)
failed_candidates = len({row[candidate_key] for row in rows}) if candidate_key else 0
reasons = Counter(row[reason_key] for row in rows) if reason_key else Counter()
receipt = {
    "status": "COMPLETE",
    "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    "total_candidates": 448,
    "passed_candidates": 448 - failed_candidates,
    "failed_candidates": failed_candidates,
    "failure_rows": len(rows),
    "failure_reasons": dict(reasons),
    "output": str(output),
    "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
}
(status_dir / "OFFICIAL_STATUS.json").write_text(json.dumps(receipt, indent=2) + "\n")
(status_dir / "OFFICIAL_COMPLETE").write_text(receipt["finished_at_utc"] + "\n")
PY
