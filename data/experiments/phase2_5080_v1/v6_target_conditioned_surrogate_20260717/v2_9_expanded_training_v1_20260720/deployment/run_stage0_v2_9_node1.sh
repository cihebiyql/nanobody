#!/usr/bin/env bash
# Fail-closed Node1 wrapper for one immutable D0 or D1 open teacher snapshot.
set -euo pipefail

: "${TRAINING_TSV:?set TRAINING_TSV to the open-only teacher TSV}"
: "${SPLIT_MANIFEST:?set SPLIT_MANIFEST to the whole-parent split manifest}"
: "${DATA_VERSION:?set DATA_VERSION to D0 or D1}"
: "${ESM2_650M_CACHE:?set ESM2_650M_CACHE}"
: "${ESM2_3B_CACHE:?set ESM2_3B_CACHE}"
: "${OUTPUT_DIR:?set OUTPUT_DIR to a nonexistent versioned directory}"

case "$DATA_VERSION" in D0|D1) ;; *) echo "DATA_VERSION must be D0 or D1" >&2; exit 2;; esac

PY="${PY:-/data1/qlyu/software/envs/pvrig-v6-tc/bin/python}"
CODE="${CODE:-/data1/qlyu/projects/pvrig_v2_9_expanded_training_v1_20260720/code/run_sequence_stage0_expanded_v2_9.py}"
SEEDS="${SEEDS:-43,97,193}"
RIDGE_ALPHAS="${RIDGE_ALPHAS:-1,10,100,1000}"
STATUS_DIR="${STATUS_DIR:-$(dirname "$OUTPUT_DIR")/status_$(basename "$OUTPUT_DIR")}" 
TRAINING_SHA256="${TRAINING_SHA256:-$(sha256sum "$TRAINING_TSV" | awk '{print $1}')}"
PREFLIGHT_JSON="$STATUS_DIR/PREFLIGHT.json"

test -x "$PY"
test -f "$CODE"
test -f "$TRAINING_TSV"
test -f "$SPLIT_MANIFEST"
test -f "$ESM2_650M_CACHE/embedding_cache_receipt.json"
test -f "$ESM2_3B_CACHE/embedding_cache_receipt.json"
test ! -e "$OUTPUT_DIR"
mkdir -p "$STATUS_DIR"
test ! -e "$PREFLIGHT_JSON"

COMMON=(
  --training-tsv "$TRAINING_TSV"
  --expected-training-tsv-sha256 "$TRAINING_SHA256"
  --split-manifest "$SPLIT_MANIFEST"
  --expected-data-version "$DATA_VERSION"
  --esm2-650m-cache "$ESM2_650M_CACHE"
  --esm2-3b-cache "$ESM2_3B_CACHE"
  --output-dir "$OUTPUT_DIR"
  --seeds "$SEEDS"
  --ridge-alphas "$RIDGE_ALPHAS"
)

"$PY" "$CODE" "${COMMON[@]}" --dry-run --preflight-json "$PREFLIGHT_JSON"
test "$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$PREFLIGHT_JSON")" = PASS_PREFLIGHT

exec "$PY" "$CODE" "${COMMON[@]}"
