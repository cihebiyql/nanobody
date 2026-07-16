#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

readonly EXPECTED_TRUST_ROOT_SHA256=54d6bdc263c0ee40538d2d229fbc0df8462d8921d4365f282b8acfbb873ef5d6
readonly SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly DATA_ROOT=$(realpath -e -- "$SCRIPT_DIR/../..")
readonly TRUST_ROOT=$SCRIPT_DIR/SHA256SUMS
readonly PYTHON=/usr/bin/python3
readonly BUILDER=$DATA_ROOT/experiments/phase2_5080_v1/src/build_phase2_v4_d_cross_campaign_control_bridge.py
readonly LEFT_ROOT=/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714
readonly RIGHT_ROOT=/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715
readonly OUTPUT_ROOT=/data/qlyu/projects/pvrig_v4_d_cross_campaign_control_bridge_v1

observed_trust_root_sha256=$(sha256sum "$TRUST_ROOT" | awk '{print $1}')
[[ "$observed_trust_root_sha256" == "$EXPECTED_TRUST_ROOT_SHA256" ]] || {
  echo "deployment SHA256SUMS digest mismatch" >&2
  exit 2
}

cd "$DATA_ROOT"
sha256sum --strict -c "$TRUST_ROOT"
[[ -x "$PYTHON" && -f "$BUILDER" ]] || {
  echo "canonical production Python or bridge builder is unavailable" >&2
  exit 2
}

unset PVRIG_V4_D_CONTROL_BRIDGE_TRUST_ROOT_SHA256
export PVRIG_V4_D_CONTROL_BRIDGE_TRUST_ROOT_SHA256=$EXPECTED_TRUST_ROOT_SHA256

if [[ ${1:-} == --verify-trust-root-only ]]; then
  "$PYTHON" -S "$BUILDER" --help >/dev/null
  echo "PASS_V4_D_CONTROL_BRIDGE_DEPLOYMENT_TRUST_ROOT_VERIFIED"
  exit 0
fi
(( $# == 0 )) || {
  echo "production launcher accepts no overrides" >&2
  exit 2
}

exec "$PYTHON" -S "$BUILDER" build \
  --left-root "$LEFT_ROOT" \
  --right-root "$RIGHT_ROOT" \
  --left-label legacy_v4_c \
  --right-label primary_v4_d \
  --expected-controls 47 \
  --expected-jobs 282 \
  --out-dir "$OUTPUT_ROOT"
