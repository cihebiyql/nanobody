#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 CAMPAIGN_DIR" >&2
  exit 2
fi

campaign_dir=$(realpath "$1")
env_dir=/mnt/d/work/抗体/.conda-envs/ab-data-validator
python_bin="$env_dir/bin/python"
anarci_bin="$env_dir/bin/ANARCI"
input_fasta="$campaign_dir/qc/local_cpu_routes_pre_anarci.fasta"
output_prefix="$campaign_dir/qc/local_cpu_routes_anarci_v1"
log_path="$campaign_dir/logs/local_cpu_routes_anarci_v1.log"

test -x "$python_bin"
test -f "$anarci_bin"
test -s "$input_fasta"
mkdir -p "$campaign_dir/qc" "$campaign_dir/logs" "$campaign_dir/status"

export PATH="$env_dir/bin:$PATH"
exec "$python_bin" "$anarci_bin" \
  -i "$input_fasta" \
  -o "$output_prefix" \
  --scheme imgt \
  --csv \
  --ncpu 2 \
  >"$log_path" 2>&1
