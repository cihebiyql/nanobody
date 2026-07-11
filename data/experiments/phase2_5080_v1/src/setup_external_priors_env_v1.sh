#!/usr/bin/env bash
# Minimal runtime enablement for existing run_external_priors_v1.py.
# Reuses the Phase 2 venv so the torch/CUDA stack remains provenance-stable.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PHASE2_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)
PYTHON="${PHASE2_ROOT}/.venv-phase2-5080/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Expected Phase 2 venv python not found: ${PYTHON}" >&2
  exit 2
fi

"${PYTHON}" -m pip install \
  'transformers==4.27.4' \
  'biopython==1.78'

"${PYTHON}" - <<'PY'
import importlib.util, sys
required = ["torch", "transformers", "Bio", "numpy", "pandas"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit(f"Missing after install: {missing}")
print("external-priors runtime ready", sys.executable)
PY
