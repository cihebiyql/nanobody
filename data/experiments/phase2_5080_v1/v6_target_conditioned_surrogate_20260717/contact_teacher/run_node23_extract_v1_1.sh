#!/usr/bin/env bash
set -euo pipefail
R=/data/qlyu/projects/pvrig_v6_v4h_stage1_contact_teacher_v1_20260718
PY=/data/qlyu/software/micromamba-root/envs/torch-cu126-py311/bin/python
CODE=$R/code/extract_v4h_stage1_contact_teacher_v1_1.py
OUT=$R/output_v1_1
STATUS=$R/status
sha256sum -c <<'HASHES'
baa82f9291d096b8d59ba222432fbfb7e4c20aba34040bbae91d19a0eec79022  /data/qlyu/projects/pvrig_v6_v4h_stage1_contact_teacher_v1_20260718/code/extract_v4h_stage1_contact_teacher_v1_1.py
fee2db4965f48df710dabf6afa7e136d72727671357015e1a48555b94748177d  /data/qlyu/projects/pvrig_v6_v4h_stage1_contact_teacher_v1_20260718/code/IMPLEMENTATION_FREEZE_V1_1.json
HASHES
python3 - <<'PY'
import json
p='/data/qlyu/projects/pvrig_v6_v4h_stage1_contact_teacher_v1_20260718/status/dry_run_v1_1_terminal.json'
x=json.load(open(p));assert x['status']=='PASS_CONTACT_DRY_RUN_V1_1' and x['return_code']==0
PY
if [[ -e "$OUT" ]]; then echo output_exists >&2; exit 74; fi
printf '{"status":"RUNNING","pid":%s,"workers":8,"started_at":"%s"}\n' "$$" "$(date -Is)" > "$STATUS/extraction_v1_1_status.json"
set +e
"$PY" "$CODE" --campaign-root /data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717 --terminal-package "$R/terminal_package" --contract "$R/code/V4H_STAGE1_CONTACT_TEACHER_CONTRACT_V1.json" --output-dir "$OUT" --workers 8 > "$STATUS/extraction_v1_1.stdout.tmp" 2> "$STATUS/extraction_v1_1.stderr"
rc=$?
set -e
if (( rc != 0 )); then printf '{"status":"FAIL_CONTACT_EXTRACTION_V1_1","return_code":%s,"finished_at":"%s"}\n' "$rc" "$(date -Is)" > "$STATUS/extraction_v1_1_terminal.json"; exit "$rc"; fi
mv "$STATUS/extraction_v1_1.stdout.tmp" "$STATUS/extraction_v1_1.stdout"
python3 - "$OUT" "$STATUS" <<'PY'
import json,sys,pathlib,hashlib,datetime
out=pathlib.Path(sys.argv[1]);status=pathlib.Path(sys.argv[2]);receipt=out/'RUN_RECEIPT.json';x=json.loads(receipt.read_text());assert x['status']=='PASS_STAGE1_CONTACT_TEACHER_COMPLETE'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(status/'extraction_v1_1_terminal.json').write_text(json.dumps({'status':'PASS_CONTACT_EXTRACTION_V1_1','receipt_sha256':sha(receipt),'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2,sort_keys=True)+'\n')
PY
