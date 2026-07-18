#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v6_residue_v2_4_post_outer_watcher_v1_20260718
BUNDLE=/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v2_2_2_20260718
RUNTIME=/data1/qlyu/projects/pvrig_v6_residue_v2_4_four_lane_oof_v2_2_2_20260718
OUTPUT="$ROOT/runtime"
PYTHON=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
COLLECTOR="$ROOT/package/collect_v2_2_2_outer_oof_v1.py"
TEST="$ROOT/package/test_collect_v2_2_2_outer_oof_v1.py"
PREREG="$ROOT/V2_2_2_POST_OUTER_WATCHER_PREREGISTRATION_V1.json"
READY="$BUNDLE/V2_4_NODE1_READY_MANIFEST_V2_2_2.json"
FREEZE="$BUNDLE/IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_2.json"
OUTER_RECEIPT="$RUNTIME/status/OUTER_DEVELOPMENT_RECEIPT.json"

[[ -d "$ROOT" && ! -L "$ROOT" ]]
[[ ! -e "$OUTPUT" ]]
[[ ! -e "$ROOT/WATCHER_PID" ]]
[[ ! -e "$OUTER_RECEIPT" ]]
printf '%s  %s\n' \
  0fd67b2e5879827f972d49e898f0fa38fc3ff00d7597e896f6e967de758e0222 "$COLLECTOR" \
  05eea316c33b1d83cadfff128839132583f789a8406e208ceb694128c605884e "$TEST" \
  10f31f9c204838e8f4cc9b89bf7a41f35dc98ae77f5bd1a6509b6f629fe85949 "$PREREG" \
  c7c95697e40feffe6063f68daf2eabe6cc596f36f4547f563c96bdad973c6df2 "$READY" \
  d7c4975313c249e72e2490c85e545ae2ba8d03b0fd90d8b85cd82c23194f76fc "$FREEZE" \
  | sha256sum -c -

cd "$ROOT"
"$PYTHON" -m unittest package.test_collect_v2_2_2_outer_oof_v1 > REMOTE_TEST_RESULTS.log 2>&1
setsid "$PYTHON" "$COLLECTOR" \
  --ready-manifest "$READY" \
  --implementation-freeze "$FREEZE" \
  --runtime-root "$RUNTIME" \
  --output-root "$OUTPUT" \
  --poll-seconds 20 \
  --timeout-seconds 0 \
  > WATCHER_STDOUT.log 2> WATCHER_STDERR.log < /dev/null &
pid=$!
printf '%s\n' "$pid" > WATCHER_PID
sleep 1
kill -0 "$pid"
printf 'WATCHER_STARTED pid=%s output=%s\n' "$pid" "$OUTPUT"
