#!/usr/bin/env bash
set -Eeuo pipefail
ANCHOR=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/audits/phase2_v4_f96_formal_evaluator_v1_runtime_trust_anchor.json
EXPECTED=86066e7508c701d03f3c32e17df38be398455e92643c88f761ca96c109041651
PYTHON=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/.venv-phase2-5080/bin/python
EVALUATOR=/mnt/d/work/抗体/data/experiments/phase2_5080_v1/src/evaluate_phase2_v4_f96_formal.py
observed=$(sha256sum "$ANCHOR" | awk '{print $1}')
[[ "$observed" == "$EXPECTED" ]] || { echo runtime_trust_anchor_hash_mismatch >&2; exit 2; }
"$PYTHON" - "$ANCHOR" <<'PYVERIFY'
import hashlib,json,sys
from pathlib import Path
a=Path(sys.argv[1]); x=json.loads(a.read_text())
assert x['status']=='PASS_NONCIRCULAR_RUNTIME_TRUST_ANCHOR_FROZEN'
for role,item in x['files'].items():
 p=Path(item['path']); assert p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'], role
print('PASS_V4_F96_RUNTIME_TRUST_ANCHOR')
PYVERIFY
[[ "${1:-}" == "--verify-trust-only" ]] && exit 0
(( $# == 0 )) || { echo launcher_accepts_no_runtime_overrides >&2; exit 2; }
export V4F96_FORMAL_TRUST_ANCHOR_SHA256="$EXPECTED"
exec "$PYTHON" "$EVALUATOR" --trust-anchor "$ANCHOR"
