#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DATA_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
TRUST_FILE="$SCRIPT_DIR/SHA256SUMS"
EXPECTED_TRUST_SHA256="0ff5b38900750e919bbfd8d6a203e7d74e4507921f68ecb2ffd7505f98fd6656"
EXPECTED_FREEZE_SHA256="2d541646bf0af762cdd5bb38f0519acee0dc11dc059f2d09ba79ab86f270882c"
EXPECTED_FREEZE_RECEIPT_SHA256="acf6da8563ff49bbcb6d95d1d21d81c51a1db6185dd9ed554275f6f925acd8b8"
EXPECTED_PREREGISTRATION_SHA256="72dc6adc1e3404c65304d489b303f6d7ba6a08d3edd626518dbcfc74c34c186a"
EXPECTED_MATERIALIZER_SHA256="746a30e4fd6f1d51b9f95933543459f3c88db03c5777a28d835d64b60c6cace3"
OBSERVED_TRUST_SHA256=$(sha256sum "$TRUST_FILE" | awk '{print $1}')
if [[ "$OBSERVED_TRUST_SHA256" != "$EXPECTED_TRUST_SHA256" ]]; then
  echo "Support V3 trust-root digest mismatch" >&2
  exit 91
fi
(
  cd "$DATA_ROOT"
  sha256sum --strict -c "$TRUST_FILE"
)
PY="$DATA_ROOT/experiments/phase2_5080_v1/.venv-phase2-5080/bin/python"
MATERIALIZER="$DATA_ROOT/experiments/phase2_5080_v1/src/materialize_phase2_v4_d_sequence_support_v3.py"
FREEZE="$DATA_ROOT/experiments/phase2_5080_v1/audits/phase2_v4_d_sequence_support_v3_implementation_freeze_v2.json"
FREEZE_RECEIPT="$DATA_ROOT/experiments/phase2_5080_v1/audits/phase2_v4_d_sequence_support_v3_implementation_freeze_v2.receipt.json"
PREREGISTRATION="$DATA_ROOT/experiments/phase2_5080_v1/audits/phase2_v4_d_sequence_support_v3_preregistration.json"
RUNTIME=/root/pvrig_v4_d_sequence_support_v3_runtime_v2_72dc6adc1e34
PUBLISH="$DATA_ROOT/experiments/phase2_5080_v1/prepared/pvrig_v4_d_sequence_support_v3"
check_exact_hash() {
  local path=$1 expected=$2 label=$3 observed
  observed=$(sha256sum "$path" | awk '{print $1}')
  if [[ "$observed" != "$expected" ]]; then
    echo "$label SHA256 mismatch" >&2
    exit 94
  fi
}
check_exact_hash "$FREEZE" "$EXPECTED_FREEZE_SHA256" freeze
check_exact_hash "$FREEZE_RECEIPT" "$EXPECTED_FREEZE_RECEIPT_SHA256" freeze_receipt
check_exact_hash "$PREREGISTRATION" "$EXPECTED_PREREGISTRATION_SHA256" preregistration
check_exact_hash "$MATERIALIZER" "$EXPECTED_MATERIALIZER_SHA256" materializer
if [[ "${1:-}" == "--verify-only" ]]; then
  CUDA_VISIBLE_DEVICES=0 "$PY" "$MATERIALIZER" verify-freeze >/dev/null
  echo PASS_SUPPORT_V3_V2_DEPLOYMENT_TRUST_ROOT_VERIFIED
  exit 0
fi
if [[ $# -ne 0 ]]; then
  echo "No production overrides are accepted" >&2
  exit 92
fi
if [[ -e "$RUNTIME/production.rc" || -e "$RUNTIME/terminal.json" ]]; then
  echo "Existing terminal state refuses relaunch" >&2
  exit 93
fi
mkdir -p "$RUNTIME"
LOG="$RUNTIME/production.log"
printf '{"status":"STARTING","launcher_sha256":"%s","trust_sha256":"%s"}\n'   "$(sha256sum "${BASH_SOURCE[0]}" | awk '{print $1}')"   "$EXPECTED_TRUST_SHA256" > "$RUNTIME/start.json"
set +e
CUDA_VISIBLE_DEVICES=0 PYTHONUNBUFFERED=1   nice -n 5 ionice -c2 -n6   "$PY" "$MATERIALIZER" production >"$LOG" 2>&1 &
CHILD_PID=$!
echo "$CHILD_PID" > "$RUNTIME/production.pid"
wait "$CHILD_PID"
RC=$?
set -e
echo "$RC" > "$RUNTIME/production.rc"
STATUS=FAILED
if [[ $RC -eq 0 ]]; then STATUS=COMPLETE; fi
TMP="$RUNTIME/terminal.json.tmp.$$"
printf '{"status":"%s","return_code":%d,"child_pid":%d,"log":"%s"}\n'   "$STATUS" "$RC" "$CHILD_PID" "$LOG" > "$TMP"
mv -f "$TMP" "$RUNTIME/terminal.json"
exit "$RC"
