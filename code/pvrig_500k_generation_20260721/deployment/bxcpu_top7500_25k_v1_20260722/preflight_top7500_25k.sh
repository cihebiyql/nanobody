#!/usr/bin/env bash
set -euo pipefail
DEPLOY=$(cd "$(dirname "$0")" && pwd)
PROJECT=pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722
ARCHIVE="$HOME/$PROJECT.tar.zst"
EXPECTED=359a695f4d6d823ae7f0cf76abaf45e7665ec404bf4a38f5179d66abc86f6919
[[ -f "$ARCHIVE" ]] || { echo missing_archive >&2; exit 65; }
[[ $(sha256sum "$ARCHIVE" | awk '{print $1}') == "$EXPECTED" ]] || { echo archive_hash_mismatch >&2; exit 65; }
for file in haddock3_runtime_core.tar.gz haddock3_runtime_python.tar.gz haddock3_runtime_lib.tar.gz \
            haddock3_source_2025.11.0.tar.gz numpy_el7_overlay_2.0.1.tar.gz; do
    [[ -s "$HOME/.local/opt/$file" ]] || { echo "missing runtime $file" >&2; exit 65; }
done
[[ $(squeue -h -u "$USER" -n pvrig-top7500-25k | wc -l) -eq 0 ]] || { echo active_campaign_exists >&2; exit 66; }
sbatch --test-only --partition=amd_256q --nodes=1 --ntasks=1 --cpus-per-task=64 --mem=230G \
    --exclusive --time=24:00:00 --array=1-8%8 "$DEPLOY/bxcpu_top7500_25k_eight_node_worker.sh" >/dev/null
printf 'PREFLIGHT=PASS archive_sha256=%s nodes=8 jobs=25000\n' "$EXPECTED"
