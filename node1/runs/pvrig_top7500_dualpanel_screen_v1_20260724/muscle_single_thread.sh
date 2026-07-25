#!/usr/bin/env bash
set -euo pipefail

exec /data/qlyu/software/vhh_eval_tools/bin/muscle "$@" -threads 1
