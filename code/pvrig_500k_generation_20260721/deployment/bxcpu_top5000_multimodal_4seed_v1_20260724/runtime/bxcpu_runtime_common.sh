#!/usr/bin/env bash
# shellcheck shell=bash

pvrig_die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 65
}

pvrig_require_sha256() {
    local name=$1 value=${!1:-}
    [[ "$value" =~ ^[0-9a-f]{64}$ ]] || pvrig_die "$name must be a lowercase SHA256"
}

pvrig_check_sha256() {
    local path=$1 expected=$2 label=$3 actual
    [[ -f "$path" && ! -L "$path" ]] || pvrig_die "missing or unsafe $label: $path"
    actual=$(sha256sum "$path" | awk '{print $1}')
    [[ "$actual" == "$expected" ]] || pvrig_die "$label SHA256 mismatch"
}

pvrig_unpack_runtime() {
    local cache_root=$1 work_base=$2 archive
    LOCAL_ENV="$work_base/haddock3-env"
    LOCAL_SOURCE="$work_base/haddock3-source"
    NUMPY_OVERLAY="$work_base/numpy-el7-overlay"
    mkdir -p "$LOCAL_ENV" "$LOCAL_SOURCE" "$NUMPY_OVERLAY"
    for archive in \
        haddock3_runtime_core.tar.gz \
        haddock3_runtime_python.tar.gz \
        haddock3_runtime_lib.tar.gz; do
        [[ -s "$cache_root/$archive" && ! -L "$cache_root/$archive" ]] ||
            pvrig_die "missing runtime archive: $cache_root/$archive"
        tar -xzf "$cache_root/$archive" -C "$LOCAL_ENV"
    done
    [[ -s "$cache_root/haddock3_source_2025.11.0.tar.gz" ]] ||
        pvrig_die "missing HADDOCK source archive"
    [[ -s "$cache_root/numpy_el7_overlay_2.0.1.tar.gz" ]] ||
        pvrig_die "missing NumPy overlay archive"
    tar -xzf "$cache_root/haddock3_source_2025.11.0.tar.gz" -C "$LOCAL_SOURCE"
    tar -xzf "$cache_root/numpy_el7_overlay_2.0.1.tar.gz" -C "$NUMPY_OVERLAY"

    export PATH="$LOCAL_ENV/bin:$PATH"
    export PYTHONNOUSERSITE=1
    export PYTHONPATH="$NUMPY_OVERLAY/lib/python3.11/site-packages:$LOCAL_SOURCE/src"
    export OMP_NUM_THREADS=1
    export OPENBLAS_NUM_THREADS=1
    export MKL_NUM_THREADS=1
    export NUMEXPR_MAX_THREADS=1
}

pvrig_validate_runtime() {
    "$LOCAL_ENV/bin/python" -m haddock.clis.cli --version |
        head -n 1 | grep -Fx 'cli.py - 2025.11.0' >/dev/null ||
        pvrig_die "HADDOCK version is not 2025.11.0"
    "$LOCAL_ENV/bin/python" - <<'PY' ||
import numpy
assert numpy.__version__ == "2.0.1", numpy.__version__
PY
        pvrig_die "NumPy version is not 2.0.1"
}

pvrig_extract_bundle() {
    local archive=$1 destination=$2
    case "$archive" in
        *.tar.zst | *.tzst)
            [[ -x "$LOCAL_ENV/bin/zstd" ]] || pvrig_die "runtime zstd is unavailable"
            "$LOCAL_ENV/bin/zstd" -dc "$archive" | tar -xf - -C "$destination"
            ;;
        *.tar.gz | *.tgz)
            tar -xzf "$archive" -C "$destination"
            ;;
        *.tar)
            tar -xf "$archive" -C "$destination"
            ;;
        *)
            pvrig_die "unsupported bundle suffix: $archive"
            ;;
    esac
}

pvrig_atomic_write_stdin() {
    local destination=$1 temporary
    mkdir -p "$(dirname "$destination")"
    temporary="$(dirname "$destination")/.$(basename "$destination").partial.$$"
    cat >"$temporary"
    mv -f "$temporary" "$destination"
}
