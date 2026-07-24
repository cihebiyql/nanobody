#!/usr/bin/env bash
set -euo pipefail

PROJECT=/data1/qlyu/projects/pvrig_core448_positive_calibrated_v1_20260724
CLOSURE=/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716/runtime_closure
INPUT="$PROJECT/inputs/core448.fasta"
OUT="$PROJECT/qc_out"
LOG="$PROJECT/logs"
STATUS="$PROJECT/status"
EXPECTED_FASTA_SHA256=047f4a630d1551eee7d7dae7ce729fd6c42f7c657b9393a6d06c0c8b8942eb65

mkdir -p "$OUT" "$LOG" "$STATUS"
exec 9>"$STATUS/controller.lock"
if ! flock -n 9; then
  echo "controller already locked"
  exit 0
fi

observed_sha256="$(sha256sum "$INPUT" | awk '{print $1}')"
if [[ "$observed_sha256" != "$EXPECTED_FASTA_SHA256" ]]; then
  printf '{"status":"FAILED_INPUT_HASH","expected":"%s","observed":"%s"}\n' \
    "$EXPECTED_FASTA_SHA256" "$observed_sha256" >"$STATUS/STATUS.json"
  exit 2
fi

if [[ -s "$STATUS/COMPLETE" ]]; then
  echo "already complete"
  exit 0
fi

printf '%s\n' "$$" >"$STATUS/controller.pid"
printf '{"status":"RUNNING","pid":%s,"input_sha256":"%s","started_at":"%s"}\n' \
  "$$" "$observed_sha256" "$(date --iso-8601=seconds)" >"$STATUS/STATUS.json"
touch "$STATUS/READY"

cmd=(
  "$CLOSURE/bin/vhh-competition-qc"
  "$INPUT"
  -o "$OUT"
  --prefix core448
  --workers 4
  --tnp-ncores 1
  --identity-cache-size 500000
  --gate-policy blocker_calibrated
  --skip-team-diversity
  --top-n 100000000
  --reserve-n 0
  --vhh-screen-bin "$CLOSURE/bin/vhh-screen"
  --validator-bin "$CLOSURE/bin/ab-data-validator"
  --anarci-bin "$CLOSURE/bin/ANARCI"
  --muscle-bin "$CLOSURE/bin/muscle"
  --positive-csv "$CLOSURE/validator_src/ab_data_validator/data/positive.csv"
  --official-positive-cdr-cache "$CLOSURE/references/official_positive_library_cdrs.csv"
  --local-positive-cdr-csv "$CLOSURE/references/local_pvrig_positive_vhh_cdrs.csv"
  --large-scale-fast
)

printf '%q ' "${cmd[@]}" >"$STATUS/COMMAND.sh"
printf '\n' >>"$STATUS/COMMAND.sh"

set +e
/usr/bin/time -v "${cmd[@]}" >"$LOG/core448_fast_qc.stdout.log" 2>"$LOG/core448_fast_qc.stderr.log"
rc=$?
set -e

if [[ "$rc" -ne 0 ]]; then
  printf '{"status":"FAILED","pid":%s,"return_code":%s,"finished_at":"%s"}\n' \
    "$$" "$rc" "$(date --iso-8601=seconds)" >"$STATUS/STATUS.json"
  exit "$rc"
fi

python3 - "$PROJECT" "$observed_sha256" <<'PY'
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

project = Path(sys.argv[1])
input_hash = sys.argv[2]
out = project / "qc_out"
status = project / "status"

def rows(path, delimiter="\t"):
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.reader(handle, delimiter=delimiter)) - 1

files = {}
for path in sorted(out.rglob("*")):
    if path.is_file():
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        files[str(path.relative_to(project))] = {"size": path.stat().st_size, "sha256": h}

receipt = {
    "status": "COMPLETE",
    "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    "input_sha256": input_hash,
    "expected_candidates": 448,
    "portfolio_rows": rows(out / "portfolio_ranked.tsv"),
    "novelty_rows": rows(out / "cdr_novelty.tsv"),
    "official_failure_rows": rows(out / "official_failed_reasons.csv", delimiter=","),
    "output_files": files,
}
(status / "STATUS.json").write_text(json.dumps(receipt, indent=2) + "\n")
(status / "COMPLETE").write_text(receipt["finished_at_utc"] + "\n")
PY
