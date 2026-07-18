#!/usr/bin/env bash
set -euo pipefail

ROOT=/data/qlyu/projects/pvrig_v6_residue_v2_contact_teacher_20260718
RAW=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
PYTHON=/data/qlyu/anaconda3/bin/python
OUTPUT="$ROOT/output"
STATUS="$ROOT/status"
LOG="$ROOT/logs/extraction.log"

mkdir -p "$STATUS" "$ROOT/logs"
test ! -e "$OUTPUT"
test "$(sha256sum "$ROOT/src/extract_v4d_contact_teacher_v2.py" | cut -d' ' -f1)" = \
  6e7d41fa23ff0e3dec60796d01fb7c9622e3ab8caed3e0a6ad4dd326ab904efb
test "$(sha256sum "$ROOT/tests/test_extract_v4d_contact_teacher_v2.py" | cut -d' ' -f1)" = \
  06992ff7dfe874d4d00baf453b098eec46177f123aa3d2d604204e5fb029ed89
test "$(sha256sum "$ROOT/config/CONTRACT_V2.json" | cut -d' ' -f1)" = \
  ff220a5b1544c0e75bc587c91db60ac84798d37500e8a6bee640de99c92171d7
test "$(sha256sum "$RAW/inputs/candidates_290.tsv" | cut -d' ' -f1)" = \
  c8845838de0a8bf524901f8257d8616b57afa655be1c0a095ca99156121fbfbd
test "$(sha256sum "$RAW/manifests/docking_jobs.tsv" | cut -d' ' -f1)" = \
  96fec07a5535615f50bff40ac48bb323a94213e06a7b12726ae5b4b2d1161737

printf '%s\n' "$$" > "$STATUS/extractor.pid"
trap 'rc=$?; "$PYTHON" - "$STATUS/terminal.json" "$rc" <<'"'"'PY'"'"'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
rc = int(sys.argv[2])
path.write_text(json.dumps({
    "schema_version": "pvrig_v6_v4d_contact_teacher_v2_terminal",
    "status": "PASS_V4D_CONTACT_TEACHER_V2" if rc == 0 else "FAIL_V4D_CONTACT_TEACHER_V2",
    "return_code": rc,
}, indent=2, sort_keys=True) + "\n")
PY
exit "$rc"' EXIT

cd "$ROOT"
"$PYTHON" -m unittest -v tests/test_extract_v4d_contact_teacher_v2.py
"$PYTHON" src/extract_v4d_contact_teacher_v2.py \
  --raw-root "$RAW" \
  --contract "$ROOT/config/CONTRACT_V2.json" \
  --output-dir "$OUTPUT" \
  --workers 8
"$PYTHON" - "$OUTPUT/RUN_RECEIPT.json" <<'PY'
import json, pathlib, sys
receipt = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert receipt["status"] == "COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2"
assert receipt["counts"]["teacher_candidates"] == 226
assert receipt["counts"]["successful_open_train_jobs"] == 1355
assert receipt["counts"]["failed_open_train_jobs"] == 1
assert receipt["counts"]["residue_marginal_rows"] == 55138
assert receipt["sealed_boundary"]["sealed_result_files_opened"] == 0
assert receipt["sealed_boundary"]["sealed_pose_files_opened"] == 0
PY

