#!/usr/bin/env bash
set -euo pipefail
OUT=$1
PID_FILE="$OUT/status/tnp_patched_all50.pid"
TNP_JSON="$OUT/tnp/patched_all50/TNP_Results_Multientry.json"
STATUS="$OUT/status/finalize_controller_status.json"
python3 - "$STATUS" <<'PY'
import json,sys,datetime
open(sys.argv[1],'w').write(json.dumps({'state':'WAITING_TNP','updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2)+'\n')
PY
pid=$(cat "$PID_FILE")
while kill -0 "$pid" 2>/dev/null; do sleep 30; done
python3 - "$TNP_JSON" "$STATUS" <<'PY'
import json,sys,datetime
try:
 x=json.load(open(sys.argv[1])); ok=len(x)==50 and all(set(v.get('Flags',{}))=={'L','L3','C','PSH','PPC','PNC'} for v in x.values())
except Exception as e:
 x={};ok=False;err=repr(e)
d={'state':'TNP_VALID' if ok else 'TNP_INCOMPLETE','updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'tnp_candidates':len(x)}
if not ok:d['error']=locals().get('err','missing candidates or flags')
open(sys.argv[2],'w').write(json.dumps(d,indent=2)+'\n')
raise SystemExit(0 if ok else 2)
PY
python3 "$OUT/scripts/integrate_final50_manufacturability_v1.py" \
 --final50 /data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/common4_rerank_v2_20260725/final50/final50_ranked.tsv \
 --top10 /data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/run/common4_rerank_v2_20260725/final50/top10_priority.tsv \
 --audit "$OUT/inputs/PVRIG_Final50_比赛表达纯度可开发性复核.tsv" \
 --tnp-json "$TNP_JSON" \
 --structure "$OUT/structure_sidecar/final50/candidate_structure_manufacturability_sidecar.tsv" \
 --format-assessment "$OUT/format_pilot/FORMAT_PILOT_ASSESSMENT.json" \
 --outdir "$OUT/reports/integrated"
python3 - "$STATUS" <<'PY'
import json,sys,datetime
open(sys.argv[1],'w').write(json.dumps({'state':'COMPLETE','updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2)+'\n')
PY
