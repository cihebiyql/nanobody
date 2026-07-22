#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${ROOT:-/mnt/d/work/抗体/code}
BASE="$ROOT/pvrig_500k_generation_20260721"
RUNTIME_REL=pvrig_bxcpu_model_runtime_v1_20260721
PREF_REL="$RUNTIME_REL/pvrig1m_gpu_raw_prefilter_v1_20260722"
PREF_LOCAL="$BASE/run/pvrig_1m_gpu_prefilter_v1_20260722"
NORMAL="$BASE/run/pvrig_1m_gpu_raw_normalized_v1_20260722"
CPU_CORRECTED="$BASE/run/pvrig_1m_cpu700k_corrected_v1_20260722"
FINAL="$BASE/run/pvrig_1m_final_library_v1_20260722"
STRUCT_REL="$RUNTIME_REL/pvrig1m_gpu_selected300k_structures_v1_20260722"
POLL_SECONDS=${POLL_SECONDS:-60}
mkdir -p "$PREF_LOCAL/status" "$FINAL"
exec 9>"$PREF_LOCAL/status/finalize.lock"; flock -n 9 || exit 75
remote_home=$(ssh bxcpu 'printf %s "$HOME"'); pref="$remote_home/$PREF_REL"
while ! ssh bxcpu "test -s '$pref/aggregated/READY.json'"; do sleep "$POLL_SECONDS"; done
while [[ ! -s "$CPU_CORRECTED/READY.json" || ! -s "$CPU_CORRECTED/cpu700k_corrected.tsv.gz" ]]; do
  sleep "$POLL_SECONDS"
done
rsync -a --partial --append-verify "bxcpu:$pref/aggregated/" "$PREF_LOCAL/aggregated/"
(cd "$PREF_LOCAL/aggregated" && sha256sum -c SHA256SUMS)
python3 "$BASE/scripts/freeze_final_1m_from_gpu_prefilter.py" \
 --cpu "$CPU_CORRECTED/cpu700k_corrected.tsv.gz" \
 --gpu-candidates "$NORMAL/gpu_fast_qc_pass_exact_unique.tsv.gz" \
 --gpu-prefilter "$PREF_LOCAL/aggregated/prefilter_all.tsv.gz" \
 --output-dir "$FINAL" >"$FINAL/freeze.stdout.log" 2>"$FINAL/freeze.stderr.log"
(cd "$FINAL" && sha256sum -c SHA256SUMS)
ssh bxcpu "mkdir -p '$STRUCT_REL/input' '$STRUCT_REL/nbb2/input' '$STRUCT_REL/nbb2/status' '$STRUCT_REL/nbb2/logs'"
rsync -a --partial --append-verify "$FINAL/gpu_selected300k.fasta.gz" "$FINAL/gpu_selected300k_prefilter.tsv.gz" "$FINAL/FREEZE_RECEIPT.json" bxcpu:"$STRUCT_REL/input/"
ssh bxcpu 'bash -s' <<EOF
set -euo pipefail
R="\$HOME/$RUNTIME_REL"; C="\$HOME/$STRUCT_REL"
"\$R/env/bin/python" "\$R/scripts/prepare_bxcpu_anarci_shards.py" --input "\$C/input/gpu_selected300k.fasta.gz" --output-dir "\$C/nbb2/input" --shards 8 >"\$C/nbb2/prepare.log"
python3 - "\$C" <<'PY'
import hashlib,json,sys,time
from pathlib import Path
c=Path(sys.argv[1]); f=c/'input/gpu_selected300k.fasta.gz'; s=c/'input/gpu_selected300k_prefilter.tsv.gz'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as x:
  for b in iter(lambda:x.read(8<<20),b''): h.update(b)
 return h.hexdigest()
m=json.loads((c/'nbb2/input/MANIFEST.json').read_text())
assert m['records']==300000 and m['shards']==8
(c/'input/SELECTION_READY.json').write_text(json.dumps({'status':'READY','records':300000,'fasta_sha256':sha(f),'selection_sha256':sha(s),'created_epoch':time.time()},indent=2,sort_keys=True)+'\n')
PY
nohup bash -c '
 set -Eeuo pipefail
 R="\$HOME/$RUNTIME_REL"; PREV="\$R/pvrig1m_old_cpu_remainder344295_v1/nbb2"; C="\$HOME/$STRUCT_REL"
 while [[ ! -s "\$PREV/status/CHAIN_COMPLETE" ]]; do sleep 60; done
 exec env RUNTIME_ROOT="\$R" CAMPAIGN_ROOT="\$C/nbb2" EXPECTED_RECORDS=300000 SHARDS=8 SELECTION="\$C/input/gpu_selected300k_prefilter.tsv.gz" PREFILTER_READY="\$C/input/SELECTION_READY.json" bash "\$R/scripts/monitor_bxcpu_nbb2_tnp_generic.sh"
' >"\$C/nbb2/logs/sequential_launcher.stdout.log" 2>"\$C/nbb2/logs/sequential_launcher.stderr.log" &
echo \$! >"\$C/nbb2/status/sequential_launcher.pid"
EOF
date -Is >"$FINAL/STRUCTURE_CAMPAIGN_DEPLOYED"
