#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

readonly SOURCE_ROOT=/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_v1_20260716
readonly RECOVERY_ROOT=/data1/qlyu/projects/pvrig_v4_g_unseen96_full_qc_recovery_v2_1_20260716
readonly RUNTIME_ROOT="$RECOVERY_ROOT/runtime_closure"
readonly CONTRACT_SOURCE="$RECOVERY_ROOT/deployment_inbox/RECOVERY_CONTRACT.json"
readonly PYTHON=/data1/qlyu/anaconda3/envs/boltz/bin/python
readonly TOOL_SOURCE=/data1/qlyu/software/vhh_eval_tools
readonly VALIDATOR_SOURCE=/data/qlyu/software/ab-data-validator/src

[[ -f "$CONTRACT_SOURCE" ]]
[[ ! -e "$RUNTIME_ROOT/RUNTIME_MANIFEST.json" ]]
mkdir -p "$RUNTIME_ROOT"/{bin,src,references,models,validator_src} "$RECOVERY_ROOT"/{inputs,status,logs,work/full_chunks,outputs}

cp -a "$VALIDATOR_SOURCE"/. "$RUNTIME_ROOT/validator_src/"
cp -a /data/qlyu/software/AbNatiV_models "$RUNTIME_ROOT/models/AbNatiV_models"
cp -a /data/qlyu/software/Sapiens_models "$RUNTIME_ROOT/models/Sapiens_models"
cp -a "$TOOL_SOURCE/competition_qc/vhh_competition_qc.py" "$RUNTIME_ROOT/src/"
cp -a "$TOOL_SOURCE/vhh_screen.py" "$RUNTIME_ROOT/src/"
cp -a "$TOOL_SOURCE/vhh_eval.py" "$RUNTIME_ROOT/src/"
cp -a "$TOOL_SOURCE/sapiens_score.py" "$RUNTIME_ROOT/src/"
cp -a "$TOOL_SOURCE/references/official_positive_library_cdrs.csv" "$RUNTIME_ROOT/references/"
cp -a "$TOOL_SOURCE/references/local_pvrig_positive_vhh_cdrs.csv" "$RUNTIME_ROOT/references/"
cp -a "$TOOL_SOURCE/bin/muscle" "$RUNTIME_ROOT/bin/muscle"
cp -a /data1/qlyu/anaconda3/envs/boltz/bin/ANARCI "$RUNTIME_ROOT/bin/ANARCI"
find "$RUNTIME_ROOT" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$RUNTIME_ROOT" -type f -name "*.py[co]" -delete

RUNTIME_ROOT_VALUE="$RUNTIME_ROOT" "$PYTHON" - <<'PY'
import os
from pathlib import Path
root=Path(os.environ['RUNTIME_ROOT_VALUE'])
replacements={
 root/'src/vhh_screen.py':{
  "ROOT = Path('/data1/qlyu/software/vhh_eval_tools')":f"ROOT = Path({str(root)!r})",
 },
 root/'src/sapiens_score.py':{
  "DEFAULT_MODELS = Path('/data/qlyu/software/Sapiens_models')":f"DEFAULT_MODELS = Path({str(root/'models/Sapiens_models')!r})",
 },
 root/'src/vhh_competition_qc.py':{
  '/data/qlyu/software/vhh_eval_tools/bin/vhh-screen':str(root/'bin/vhh-screen'),
  '/data/qlyu/software/vhh_eval_tools/bin/ab-data-validator':str(root/'bin/ab-data-validator'),
  '/data/qlyu/anaconda3/envs/boltz/bin/ANARCI':str(root/'bin/ANARCI'),
  '/data/qlyu/software/vhh_eval_tools/bin/muscle':str(root/'bin/muscle'),
  '/data/qlyu/software/ab-data-validator/src/ab_data_validator/data/positive.csv':str(root/'validator_src/ab_data_validator/data/positive.csv'),
  '/data/qlyu/software/vhh_eval_tools/references/official_positive_library_cdrs.csv':str(root/'references/official_positive_library_cdrs.csv'),
  '/data/qlyu/software/ab-data-validator/src':str(root/'validator_src'),
 },
}
for path,mapping in replacements.items():
    text=path.read_text()
    for old,new in mapping.items():
        if old not in text:
            raise SystemExit(f'missing patch token in {path}: {old}')
        text=text.replace(old,new)
    path.write_text(text)
PY

cat > "$RUNTIME_ROOT/bin/ab-data-validator" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export PATH="$RUNTIME_ROOT/bin:/data1/qlyu/anaconda3/envs/boltz/bin:\${PATH:-}"
export PYTHONPATH="$RUNTIME_ROOT/validator_src:\${PYTHONPATH:-}"
exec /data1/qlyu/software/envs/vhh-eval/bin/python -m ab_data_validator.cli "\$@"
EOF
cat > "$RUNTIME_ROOT/bin/vhh-eval" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export PATH="$RUNTIME_ROOT/bin:/data1/qlyu/anaconda3/envs/boltz/bin:\${PATH:-}"
export PYTHONPATH="$RUNTIME_ROOT/src:\${PYTHONPATH:-}"
exec /data1/qlyu/software/envs/vhh-eval/bin/python "$RUNTIME_ROOT/src/vhh_eval.py" "\$@"
EOF
cat > "$RUNTIME_ROOT/bin/abnativ" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export ABNATIV_MODELS_DIR="$RUNTIME_ROOT/models/AbNatiV_models"
export PATH="$RUNTIME_ROOT/bin:/data1/qlyu/anaconda3/envs/boltz/bin:\${PATH:-}"
exec /data1/qlyu/software/envs/vhh-eval/bin/abnativ "\$@"
EOF
cat > "$RUNTIME_ROOT/bin/sapiens-score" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
exec /data1/qlyu/software/envs/vhh-eval/bin/python "$RUNTIME_ROOT/src/sapiens_score.py" "\$@"
EOF
cat > "$RUNTIME_ROOT/bin/vhh-screen" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export OPENMM_PLUGIN_DIR=/data1/qlyu/anaconda3/envs/boltz/lib/plugins
export PATH="$RUNTIME_ROOT/bin:/data1/qlyu/anaconda3/envs/boltz/bin:\${PATH:-}"
export PYTHONPATH="$RUNTIME_ROOT/src:$RUNTIME_ROOT/validator_src:\${PYTHONPATH:-}"
exec /data1/qlyu/software/envs/vhh-eval/bin/python "$RUNTIME_ROOT/src/vhh_screen.py" "\$@"
EOF
cat > "$RUNTIME_ROOT/bin/vhh-competition-qc" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export PATH="$RUNTIME_ROOT/bin:/data1/qlyu/anaconda3/envs/boltz/bin:\${PATH:-}"
export PYTHONPATH="$RUNTIME_ROOT/validator_src:$RUNTIME_ROOT/src:\${PYTHONPATH:-}"
export AB_DATA_VALIDATOR_SRC="$RUNTIME_ROOT/validator_src"
exec /data1/qlyu/software/envs/vhh-eval/bin/python "$RUNTIME_ROOT/src/vhh_competition_qc.py" "\$@"
EOF
chmod 0755 "$RUNTIME_ROOT/bin"/*

cp -a "$SOURCE_ROOT/cascade/full_qc_shortlist.tsv" "$RECOVERY_ROOT/inputs/"
cp -a "$SOURCE_ROOT/cascade/full_qc_shortlist.fasta" "$RECOVERY_ROOT/inputs/"
cp -a "$SOURCE_ROOT/cascade/full_chunks/chunk_000001/input.fasta" "$RECOVERY_ROOT/work/full_chunks/chunk_000001.input.fasta"
cp -a "$SOURCE_ROOT/cascade/full_chunks/chunk_000002/input.fasta" "$RECOVERY_ROOT/work/full_chunks/chunk_000002.input.fasta"

if grep -RIl --exclude='RUNTIME_MANIFEST.json' '/data/qlyu' "$RUNTIME_ROOT" | grep -q .; then
  echo 'runtime closure retains forbidden /data/qlyu dependency' >&2
  grep -RIn '/data/qlyu' "$RUNTIME_ROOT" | head -100 >&2
  exit 80
fi

RUNTIME_ROOT_VALUE="$RUNTIME_ROOT" RECOVERY_ROOT_VALUE="$RECOVERY_ROOT" "$PYTHON" - <<'PY'
import hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
root=Path(os.environ['RUNTIME_ROOT_VALUE'])
recovery=Path(os.environ['RECOVERY_ROOT_VALUE'])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
files={str(p.relative_to(root)):{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(root.rglob('*')) if p.is_file()}
external={
 '/data1/qlyu/software/envs/vhh-eval/bin/python':sha(Path('/data1/qlyu/software/envs/vhh-eval/bin/python').resolve()),
 '/data1/qlyu/software/envs/vhh-eval/bin/abnativ':sha(Path('/data1/qlyu/software/envs/vhh-eval/bin/abnativ')),
 '/data1/qlyu/anaconda3/envs/boltz/bin/hmmscan':sha(Path('/data1/qlyu/anaconda3/envs/boltz/bin/hmmscan')),
}
payload={
 'schema_version':'pvrig_v4_g_ssd_runtime_closure_manifest_v2',
 'status':'PASS_SSD_RUNTIME_CLOSURE_FROZEN',
 'created_at_utc':datetime.now(timezone.utc).isoformat(),
 'runtime_root':str(root),
 'files':files,
 'external_data1_runtime_hashes':external,
 'forbidden_runtime_prefix':'/data/qlyu',
 'forbidden_runtime_prefix_hits':0,
}
out=root/'RUNTIME_MANIFEST.json'; out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n'); out.chmod(0o444)
(recovery/'status/runtime_closure_ready.json').write_text(json.dumps({'status':'PASS_RUNTIME_CLOSURE_READY','runtime_manifest_sha256':sha(out),'file_count':len(files)},indent=2,sort_keys=True)+'\n')
print(json.dumps({'runtime_manifest_sha256':sha(out),'file_count':len(files)},sort_keys=True))
PY
