#!/usr/bin/env bash
set -euo pipefail

ROOT=/data/qlyu/projects/pvrig_v4_h_adaptive_contact_teacher_v2_20260718
CODE="$ROOT/v6_target_conditioned_surrogate_20260717/contact_teacher_adaptive_v2_20260718"
CAMPAIGN=/data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717
OUTPUT="$ROOT/production_output_v2"
PYTHON=/data/qlyu/anaconda3/bin/python
EXTRACTOR="$CODE/src/extract_v4h_adaptive_multiseed_contact_teacher_v2.py"
CONTRACT="$CODE/V4H_ADAPTIVE_MULTISEED_CONTACT_TEACHER_CONTRACT_V2.json"
RECON="$CODE/UPSTREAM_RECEIPT_RECONCILIATION_V2.json"
BASE="$CODE/../contact_teacher/src/extract_v4h_stage1_contact_teacher_v1_1.py"

check_hash() {
  local path="$1" expected="$2" label="$3" observed
  test -f "$path" && test ! -L "$path" || {
    echo "FAIL_${label}_MISSING_OR_SYMLINK"
    exit 31
  }
  observed=$(sha256sum "$path" | cut -d ' ' -f 1)
  test "$observed" = "$expected" || {
    echo "FAIL_${label}_HASH:$observed:$expected"
    exit 32
  }
}

check_hash "$EXTRACTOR" d8c094ea53e7471b92a982d8e76489bd31b37839fcd5079fc0a4cf3c8bf876ae EXTRACTOR
check_hash "$CONTRACT" 331c5c895a23ee9b34a66b31d8f4bd8fade63ff0461ff3e3b6ed32d8a4132fa8 CONTRACT
check_hash "$RECON" c875ce34b55bbdad42f9485d14902dba4052d5785ce80257d6ad060b2d2f92b6 RECONCILIATION
check_hash "$BASE" baa82f9291d096b8d59ba222432fbfb7e4c20aba34040bbae91d19a0eec79022 BASE_EXTRACTOR

test -x "$PYTHON" || { echo FAIL_PYTHON_MISSING; exit 33; }
test ! -e "$OUTPUT" || { echo FAIL_OUTPUT_ALREADY_EXISTS; exit 34; }

echo "START_UTC=$(date -u +%FT%TZ)"
echo "HOST=$(hostname)"
echo "PID=$$"
echo "OUTPUT=$OUTPUT"

exec ionice -c3 nice -n 15 "$PYTHON" "$EXTRACTOR" \
  --campaign-root "$CAMPAIGN" \
  --contract "$CONTRACT" \
  --reconciliation-receipt "$RECON" \
  --output-dir "$OUTPUT" \
  --workers 4
