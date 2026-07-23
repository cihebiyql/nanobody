#!/usr/bin/env bash
set -euo pipefail

PROJECT="pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722"
MANIFEST="$HOME/${PROJECT}.manifest.tsv"
PUBLISH_ROOT="$HOME/${PROJECT}_bxcpu_results"
CODE_ROOT="$HOME/.local/share/bxcpu_top7500_25k_terminal_audit_v2_20260723"
OUTPUT="$PUBLISH_ROOT/reports_v2/TECHNICAL_COMPLETION_V2.json"
PYTHON="$HOME/.local/opt/haddock3-2025.11.0/bin/python"

test -x "$PYTHON"
"$PYTHON" "$CODE_ROOT/technical_status_top7500_25k_v2.py" \
  --manifest "$MANIFEST" \
  --publish-root "$PUBLISH_ROOT" \
  --expected-count 25000 \
  --output "$OUTPUT"

"$PYTHON" - "$OUTPUT" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
d = json.loads(p.read_text())
if d["status"] not in {"COMPLETE_WITH_TECHNICAL_NA", "INCOMPLETE"}:
    raise SystemExit(f"unexpected_status:{d['status']}")
print(d["status"])
PY
