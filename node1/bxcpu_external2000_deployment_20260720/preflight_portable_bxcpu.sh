#!/usr/bin/env bash
# Verify the immutable bxcpu-side cache without unpacking it on GPFS.
set -euo pipefail

CACHE_ROOT="${PVRIG_BXCPU_CACHE:-$HOME/.local/opt}"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

check() {
    local expected=$1
    local file=$2
    printf '%s  %s\n' "$expected" "$file" | sha256sum -c -
}

check 411d15ca971adc6b114387a8d2f92b689bb0b6bf4c39d5c01cb77c46ed6c6d96 \
    "$HOME/pvrig_v29_external2000_sequences_v2_20260720.tar.zst"
check c65d7024262fffd819f452eeb7974f5674a6ae396c06456e1e3d405c931a91dd \
    "$CACHE_ROOT/haddock3_source_2025.11.0.tar.gz"
check 29265353ff34a5206449d5bf98bd10564bdc5af8c9886adb755295edecc49c5d \
    "$CACHE_ROOT/haddock3_runtime_core.tar.gz"
check 448561ec234adcf46731c64df215707a917394818d0fdfe6989bd0a1b04672bf \
    "$CACHE_ROOT/haddock3_runtime_python.tar.gz"
check 2cadab93efa5553f51a5ffe27affd4a19fe9eeffb704bb62eafd93caf82e62ab \
    "$CACHE_ROOT/haddock3_runtime_lib.tar.gz"
check 4fc125968ff7e4a25f0276c36d4dd8c8c4775520f0b79997b0c1d9f12e8dbc2a \
    "$CACHE_ROOT/numpy_el7_overlay_2.0.1.tar.gz"
check 7fa190ed91a1bbafcdcc21f6cd74f0345b43b3a3e6e8379c3bf3f1810abeb1c3 \
    "$SCRIPT_DIR/reference_normalization_summary.json"
printf 'portable_cache=PASS\n'
