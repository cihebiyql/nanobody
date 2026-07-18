#!/usr/bin/env bash
set -euo pipefail
ROOT=/data1/qlyu/projects/pvrig_v6_residue_v2_4_post_outer_watcher_v1_1_20260718
BUNDLE=/data1/qlyu/projects/pvrig_v6_residue_v2_4_deployment_bundle_v2_2_2_20260718
RUNTIME=/data1/qlyu/projects/pvrig_v6_residue_v2_4_four_lane_oof_v2_2_2_20260718
PYTHON=/data1/qlyu/software/envs/pvrig-v6-tc/bin/python
OLD=/data1/qlyu/projects/pvrig_v6_residue_v2_4_post_outer_watcher_v1_20260718
[[ -d "$ROOT" && -d "$ROOT/package" ]]
[[ -s "$RUNTIME/status/OUTER_DEVELOPMENT_RECEIPT.json" ]]
[[ "$(cat "$OLD/WATCHER_STDERR.log")" == 'FAIL_V2_2_2_POST_OUTER_COLLECTION:result_split_exact:A_VHH_ONLY:0' ]]
[[ ! -e "$ROOT/WATCHER_PID" && ! -e "$ROOT/runtime" ]]
cd "$ROOT"
sha256sum -c SHA256SUMS
"$PYTHON" -m unittest package.test_collect_v2_2_2_outer_oof_v1_1 > REMOTE_TEST_RESULTS.log 2>&1
setsid "$PYTHON" "$ROOT/package/collect_v2_2_2_outer_oof_v1_1.py" \
  --ready-manifest "$BUNDLE/V2_4_NODE1_READY_MANIFEST_V2_2_2.json" \
  --implementation-freeze "$BUNDLE/IMPLEMENTATION_FREEZE_V2_4_ADAPTIVE_V2_2_2.json" \
  --runtime-root "$RUNTIME" \
  --output-root "$ROOT/runtime" \
  --poll-seconds 20 --timeout-seconds 0 \
  > "$ROOT/WATCHER_STDOUT.log" 2> "$ROOT/WATCHER_STDERR.log" < /dev/null &
pid=$!
echo "$pid" > WATCHER_PID
echo "WATCHER_V1_1_STARTED pid=$pid output=$ROOT/runtime"
