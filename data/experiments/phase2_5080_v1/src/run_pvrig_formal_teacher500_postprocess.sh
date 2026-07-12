#!/usr/bin/env bash
# Sync completed Node1 Teacher500 poses and build the frozen geometry teacher set.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REMOTE_ROOT=${REMOTE_ROOT:-/data/qlyu/projects/pvrig_teacher_formal_v1_20260712/teacher500_docking}
SYNC_ROOT="$ROOT/runs/pvrig_teacher_formal_v1/teacher500_node1_selected"
WORK_ROOT="$ROOT/runs/pvrig_teacher_formal_v1/teacher500_postprocessed"
SELECTION="$ROOT/data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_manifest_v1.csv"

python "$ROOT/src/sync_pvrig_teacher_pilot96_outputs.py" \
  --remote-root "$REMOTE_ROOT" \
  --outdir "$SYNC_ROOT" \
  --audit "$ROOT/audits/pvrig_formal_teacher500_sync_audit.json" \
  --expected-candidates 500 --top-n 10 --min-models 4

python "$ROOT/src/process_pvrig_formal_teacher500.py" \
  --selection "$SELECTION" \
  --sync-root "$SYNC_ROOT" \
  --work-root "$WORK_ROOT" \
  --audit "$ROOT/audits/pvrig_formal_teacher500_postprocess_audit.json" \
  --top-n 10 --min-models 4 --workers 8

python "$ROOT/src/build_pvrig_formal_teacher500.py" \
  --selection "$SELECTION" \
  --work-root "$WORK_ROOT" \
  --prepared-out "$ROOT/prepared/pvrig_teacher_formal_v1" \
  --manifest-out "$ROOT/data_splits/pvrig_teacher_formal_v1/teacher500/pvrig_teacher500_teacher_manifest_v1.csv" \
  --audit-json "$ROOT/audits/pvrig_formal_teacher500_audit.json" \
  --audit-md "$ROOT/audits/PVRIG_FORMAL_TEACHER500_AUDIT.md" \
  --top-k 10 --min-poses 4 --min-supporting-clusters 2

echo PASS_PVRIG_FORMAL_TEACHER500_POSTPROCESSED
