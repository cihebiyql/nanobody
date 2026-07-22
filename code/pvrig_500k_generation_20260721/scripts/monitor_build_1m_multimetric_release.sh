#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${ROOT:-/mnt/d/work/抗体/code}; BASE="$ROOT/pvrig_500k_generation_20260721"; POLL_SECONDS=${POLL_SECONDS:-60}
FINAL="$BASE/run/pvrig_1m_final_library_v1_20260722"
GPU="$BASE/run/pvrig_1m_gpu_selected300k_nbb2_tnp_v1_20260722"
CPU_METRICS="$BASE/run/pvrig_1m_cpu700k_corrected_metrics_v1_20260722"
OUT="$BASE/run/pvrig_1m_multimetric_release_v1_20260722"
WRAP="$BASE/scripts/ssh_node1_windows_proxy.sh"; NODE1=/data1/qlyu/projects/pvrig_1m_multimetric_release_v1_20260722
mkdir -p "$OUT/status"; exec 9>"$OUT/status/build.lock"; flock -n 9 || exit 75
required=(
 "$FINAL/FREEZE_RECEIPT.json"
 "$CPU_METRICS/READY.json"
 "$CPU_METRICS/cpu700k_prefilter.tsv.gz"
 "$CPU_METRICS/cpu700k_nbb2.tsv.gz"
 "$CPU_METRICS/cpu700k_tnp.tsv.gz"
 "$CPU_METRICS/SHA256SUMS"
 "$GPU/aggregate/nbb2/nbb2_manifest.tsv.gz" "$GPU/aggregate/nbb2/COMPLETE.json"
 "$GPU/aggregate/tnp/tnp_all.tsv.gz" "$GPU/aggregate/tnp/READY.json"
 "$FINAL/gpu_selected300k_prefilter.tsv.gz"
)
while true; do
 missing=0; for p in "${required[@]}"; do [[ -s "$p" ]] || missing=$((missing+1)); done
 printf '{"state":"WAITING_INPUTS","missing":%s,"updated_at":"%s"}\n' "$missing" "$(date -Is)" >"$OUT/status/STATUS.json"
 [[ "$missing" -eq 0 ]] && break; sleep "$POLL_SECONDS"
done
printf '{"state":"VALIDATING_INPUTS","updated_at":"%s"}\n' "$(date -Is)" >"$OUT/status/STATUS.json"
(cd "$CPU_METRICS" && sha256sum -c SHA256SUMS)
python3 - "$FINAL/FREEZE_RECEIPT.json" "$CPU_METRICS/READY.json" \
 "$GPU/aggregate/nbb2/COMPLETE.json" "$GPU/aggregate/tnp/READY.json" <<'PY'
import json,sys
freeze,cpu,nbb2,tnp=(json.load(open(path)) for path in sys.argv[1:])
if freeze.get('status')!='PASS' or int(freeze.get('records',-1))!=1_000_000:
 raise SystemExit(f'final freeze is not strict PASS/1000000: {freeze}')
if cpu.get('status')!='PASS' or int(cpu.get('records',-1))!=700_000:
 raise SystemExit(f'CPU metrics are not strict PASS/700000: {cpu}')
cpu_counts=cpu.get('status_counts',{})
if cpu_counts.get('anarci')!={'PASS':700_000} or cpu_counts.get('nbb2')!={'SUCCESS':700_000} or cpu_counts.get('tnp')!={'PASS':700_000}:
 raise SystemExit(f'CPU metrics status closure is not strict: {cpu_counts}')
if nbb2.get('status')!='PASS' or int(nbb2.get('records',-1))!=300_000 or nbb2.get('status_counts')!={'SUCCESS':300_000}:
 raise SystemExit(f'GPU NBB2 closure is not strict SUCCESS/300000: {nbb2}')
if tnp.get('status')!='PASS' or int(tnp.get('records',-1))!=300_000 or tnp.get('status_counts')!={'PASS':300_000}:
 raise SystemExit(f'GPU TNP closure is not strict PASS/300000: {tnp}')
PY
printf '{"state":"BUILDING","updated_at":"%s"}\n' "$(date -Is)" >"$OUT/status/STATUS.json"
python3 "$BASE/scripts/build_1m_multimetric_release.py" \
 --candidates "$FINAL/pvrig_1m_candidates.tsv.gz" \
 --prefilter "$CPU_METRICS/cpu700k_prefilter.tsv.gz" \
 --prefilter "$FINAL/gpu_selected300k_prefilter.tsv.gz" \
 --nbb2 "$CPU_METRICS/cpu700k_nbb2.tsv.gz" \
 --nbb2 "$GPU/aggregate/nbb2/nbb2_manifest.tsv.gz" \
 --tnp "$CPU_METRICS/cpu700k_tnp.tsv.gz" \
 --tnp "$GPU/aggregate/tnp/tnp_all.tsv.gz" \
 --output-dir "$OUT" --expected 1000000 >"$OUT/build.stdout.log" 2>"$OUT/build.stderr.log"
python3 "$BASE/scripts/validate_final_1m_release.py" \
 --candidates "$FINAL/pvrig_1m_candidates.tsv.gz" \
 --multimetric "$OUT/pvrig_1m_multimetric.tsv.gz" \
 --freeze-receipt "$FINAL/FREEZE_RECEIPT.json" \
 --release-ready "$OUT/READY.json" \
 --output "$OUT/FINAL_VALIDATION.json" --expected 1000000 \
 >"$OUT/validate.stdout.log" 2>"$OUT/validate.stderr.log"
python3 - "$OUT" <<'PY'
import hashlib,sys
from pathlib import Path
root=Path(sys.argv[1]); paths=[root/'pvrig_1m_multimetric.tsv.gz',root/'FINAL_VALIDATION.json']
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(8<<20),b''): h.update(block)
 return h.hexdigest()
(root/'SHA256SUMS').write_text(''.join(f'{sha(path)}  {path.name}\n' for path in paths))
PY
(cd "$OUT" && sha256sum -c SHA256SUMS)
"$WRAP" node1 "mkdir -p '$NODE1'"
rsync -a --partial --append-verify --exclude status --exclude '*.log' -e "$WRAP" "$OUT/" "node1:$NODE1/"
"$WRAP" node1 "cd '$NODE1' && sha256sum -c SHA256SUMS"
printf '{"state":"COMPLETE","updated_at":"%s"}\n' "$(date -Is)" >"$OUT/status/STATUS.json"
date -Is >"$OUT/NODE1_SYNC_COMPLETE"
