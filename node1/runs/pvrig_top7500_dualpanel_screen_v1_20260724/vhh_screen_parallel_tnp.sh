#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

OUT_DIR=""
ARGS=("$@")
for ((index = 0; index < ${#ARGS[@]}; index++)); do
  case "${ARGS[$index]}" in
    -o|--out-dir)
      OUT_DIR="${ARGS[$((index + 1))]}"
      ;;
    --out-dir=*)
      OUT_DIR="${ARGS[$index]#*=}"
      ;;
  esac
done

if [[ -z "$OUT_DIR" ]]; then
  echo "vhh_screen_parallel_tnp.sh: output directory argument is required" >&2
  exit 2
fi

TNP_CACHE="$ROOT/run/full_qc/tnp_cache"
mkdir -p "$OUT_DIR" "$TNP_CACHE"
if [[ ! -e "$OUT_DIR/layer3_tnp" ]]; then
  ln -s "$TNP_CACHE" "$OUT_DIR/layer3_tnp"
fi

exec /data/qlyu/software/envs/vhh-eval/bin/python \
  "$ROOT/vhh_screen_parallel_tnp.py" \
  "$@" \
  --tnp-workers 24 \
  --tnp-gpus 0,1,2,4
