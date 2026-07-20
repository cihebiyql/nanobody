#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PVRIG_PROJECT_ROOT:-$HOME/pvrig_v29_external2000_sequences_v2_20260720}"
ENV_ROOT="${PVRIG_HADDOCK_ENV:-$HOME/.local/opt/haddock3-2025.11.0}"
HADDOCK_SOURCE="${PVRIG_HADDOCK_SOURCE:-$HOME/.local/opt/haddock3-source-2025.11.0/src}"

[[ -d "$PROJECT_ROOT" ]] || { echo "project missing: $PROJECT_ROOT" >&2; exit 66; }
[[ -x "$ENV_ROOT/bin/python" && -x "$ENV_ROOT/bin/haddock3" ]] || {
    echo "environment missing: $ENV_ROOT" >&2
    exit 69
}
[[ -d "$HADDOCK_SOURCE/haddock" ]] || { echo "HADDOCK source missing: $HADDOCK_SOURCE" >&2; exit 69; }
[[ $(wc -l < "$PROJECT_ROOT/manifests/external_ready_now_jobs.tsv") -eq 3815 ]] || exit 65
[[ $(wc -l < "$PROJECT_ROOT/manifests/external_transfer_from_node21_jobs.tsv") -eq 187 ]] || exit 65
PYTHONPATH="$HADDOCK_SOURCE${PYTHONPATH:+:$PYTHONPATH}" "$ENV_ROOT/bin/haddock3" --version
"$ENV_ROOT/bin/python" --version
PYTHONPATH="$HADDOCK_SOURCE${PYTHONPATH:+:$PYTHONPATH}" "$ENV_ROOT/bin/python" -c 'import haddock; print("haddock_import=PASS")'
(cd "$PROJECT_ROOT" && sha256sum --status -c SHA256SUMS)
printf 'safe_jobs=3814\ntransfer_frozen_jobs=186\npreflight=PASS\n'
