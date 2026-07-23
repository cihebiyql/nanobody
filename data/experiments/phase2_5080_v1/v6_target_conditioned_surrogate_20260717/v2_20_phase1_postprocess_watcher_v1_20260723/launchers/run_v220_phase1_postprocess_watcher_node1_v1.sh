#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/data1/qlyu/software/envs/pvrig-v6-tc/bin/python"
OUTPUT_DIR="/data1/qlyu/projects/pvrig_v2_20_phase1_postprocess_watcher_v1_20260723/runtime_v1"
PREREG="$ROOT/PREREGISTRATION_POSTPROCESS_V1.json"
WATCHER="$ROOT/src/run_v220_phase1_postprocess_watcher_v1.py"

EXPECTED_PREREG_SHA="168a12f29de587e4c0d245da6a923143b6726c47de40e80ea1daecff900cca3a"
EXPECTED_WATCHER_SHA="df3ffbfd1c211eda247375e6edd94acc523e0703da6652f8eecfdb6292929016"

[[ ! -e "$OUTPUT_DIR" ]] || {
  echo "output_dir_exists:$OUTPUT_DIR" >&2
  exit 2
}

sha256sum -c <<SUMS
$EXPECTED_PREREG_SHA  $PREREG
$EXPECTED_WATCHER_SHA  $WATCHER
SUMS

exec "$PYTHON_BIN" "$WATCHER" \
  --postprocess-preregistration "$PREREG" \
  --expected-postprocess-preregistration-sha256 "$EXPECTED_PREREG_SHA" \
  --output-dir "$OUTPUT_DIR" \
  --poll-seconds 60 \
  --timeout-seconds 0
