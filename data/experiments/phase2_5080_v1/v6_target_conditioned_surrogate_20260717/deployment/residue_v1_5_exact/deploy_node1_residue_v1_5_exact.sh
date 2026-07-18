#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LOCAL_BASE=$(cd "$SCRIPT_DIR/../.." && pwd)
LOCAL_PHASE2=$(cd "$LOCAL_BASE/.." && pwd)
LOCAL_RESIDUE=$LOCAL_BASE/residue_v1
REMOTE_HOST=node1
SSH_BIN=${SSH_BIN:-ssh.exe}
REMOTE_ROOT=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
REMOTE_CODE_ROOT=$REMOTE_ROOT/code_v1_5
REMOTE_MODEL=/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c/model.safetensors
MODEL_SHA=a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0

if [[ "${1:-}" == --print-plan ]]; then
  cat <<'JSON'
{
  "hashes": {
    "collector": "a15db4aceaeb8c62bca277d9d39015aff3e7e95bacf30a3dd635c1d18558cee0",
    "contact": "bd3cb205af606391aa2153f3c2bbc243c9630796228e12b4a561a2a7da7c7f0f",
    "contact_receipt": "de3973e76e48f0be0c8854fe3f8560c42522ec3e42f90ea4861ce8f9b0ed9027",
    "contact_validation": "8dae292b1dd922ff2af7f9f73bdaa662e4fe3f827f30f633df9d3a3ebd603911",
    "freeze": "3a4046462bcf138c25c5c36005d1f6e24f2df3f931fe32369dba80ee834e155e",
    "governance": "dddc693483c1f9a4145b6e28b74bdc9290ec5e7544e9da302e88cc4c10aa1226",
    "model": "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0",
    "trainer": "6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af",
    "training": "ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633",
    "training_receipt": "46fae18a63e10920c05ccf1dc873de2b588ec436a0320d909405164f9d14c529"
  },
  "launches_remote_jobs": false,
  "remote_code_root": "/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717/code_v1_5",
  "remote_host": "node1",
  "remote_root": "/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717"
}
JSON
  exit 0
fi
[[ $# -eq 0 ]] || { echo 'usage: deploy_node1_residue_v1_5_exact.sh [--print-plan]' >&2; exit 64; }
command -v "$SSH_BIN" >/dev/null || { echo "missing_ssh_binary:$SSH_BIN" >&2; exit 69; }

stage=$(mktemp -d)
cleanup_stage() {
  python3 - "$stage" <<'PY'
import pathlib,shutil,sys
path=pathlib.Path(sys.argv[1])
if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
PY
}
trap cleanup_stage EXIT
mkdir -p "$stage/inputs_v1_2/full1507" "$stage/inputs_v1_2/residue_contact_targets_v1" \
  "$stage/inputs_v1_2/smoke93" "$stage/deployment_v1_5"

# Verify the intended frozen code locally, but never stage or overwrite code_v1_5.
sha256sum -c <<HASHES
3a4046462bcf138c25c5c36005d1f6e24f2df3f931fe32369dba80ee834e155e  $LOCAL_RESIDUE/IMPLEMENTATION_FREEZE_V1_5.json
6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af  $LOCAL_RESIDUE/src/train_nested_residue_surrogate_v1_5.py
a15db4aceaeb8c62bca277d9d39015aff3e7e95bacf30a3dd635c1d18558cee0  $LOCAL_RESIDUE/src/collect_residue_oof_v1_5.py
dddc693483c1f9a4145b6e28b74bdc9290ec5e7544e9da302e88cc4c10aa1226  $LOCAL_BASE/PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json
ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633  $LOCAL_BASE/data/materialized_v1_1/v6_supervised1507.tsv
46fae18a63e10920c05ccf1dc873de2b588ec436a0320d909405164f9d14c529  $LOCAL_BASE/data/materialized_v1_1/v6_training_table_receipt.json
bd3cb205af606391aa2153f3c2bbc243c9630796228e12b4a561a2a7da7c7f0f  $LOCAL_PHASE2/prepared/pvrig_v6_dual_residue_contact_targets_v1_20260718/v6_dual_residue_contact_targets.tsv.gz
de3973e76e48f0be0c8854fe3f8560c42522ec3e42f90ea4861ce8f9b0ed9027  $LOCAL_PHASE2/prepared/pvrig_v6_dual_residue_contact_targets_v1_20260718/RUN_RECEIPT.json
8dae292b1dd922ff2af7f9f73bdaa662e4fe3f827f30f633df9d3a3ebd603911  $LOCAL_PHASE2/prepared/pvrig_v6_dual_residue_contact_targets_v1_20260718/INDEPENDENT_VALIDATION.json
48fadb1b104d7528a574972e5d391f88b1a21df375e281e119025e5ed170683d  $LOCAL_RESIDUE/RESIDUE_PRODUCTION_MATRIX_V1_2.json
HASHES

cp "$LOCAL_BASE/data/materialized_v1_1/v6_supervised1507.tsv" "$LOCAL_BASE/data/materialized_v1_1/v6_training_table_receipt.json" "$stage/inputs_v1_2/full1507/"
cp "$LOCAL_PHASE2/prepared/pvrig_v6_dual_residue_contact_targets_v1_20260718/v6_dual_residue_contact_targets.tsv.gz" "$stage/inputs_v1_2/residue_contact_targets_v1/"
cp "$LOCAL_PHASE2/prepared/pvrig_v6_dual_residue_contact_targets_v1_20260718/RUN_RECEIPT.json" "$stage/inputs_v1_2/residue_contact_targets_v1/"
cp "$LOCAL_PHASE2/prepared/pvrig_v6_dual_residue_contact_targets_v1_20260718/INDEPENDENT_VALIDATION.json" "$stage/inputs_v1_2/residue_contact_targets_v1/"
cp "$LOCAL_BASE/data/smoke93_v1/v6_smoke93.tsv" "$stage/inputs_v1_2/smoke93/"
cp "$LOCAL_BASE/data/smoke93_v1/v6_smoke93_dual_residue_contact_targets.tsv.gz" "$stage/inputs_v1_2/smoke93/"
cp "$LOCAL_BASE/data/smoke93_v1/v6_smoke93_dual_residue_contact_targets_receipt_v1_1.json" "$stage/inputs_v1_2/smoke93/"
cp "$LOCAL_RESIDUE/RESIDUE_PRODUCTION_MATRIX_V1_2.json" "$LOCAL_RESIDUE/RESIDUE_PRODUCTION_MATRIX_V1_1_SUPERSEDED_PREPRODUCTION.json" "$stage/deployment_v1_5/"
cp "$SCRIPT_DIR/residue_v1_5_common.sh" "$SCRIPT_DIR/run_node1_residue_v1_5_smoke.sh" \
  "$SCRIPT_DIR/supervise_node1_residue_v1_5_production.sh" \
  "$SCRIPT_DIR/validate_residue_v1_5_smoke_checkpoint.py" "$SCRIPT_DIR/README_ZH.md" \
  "$stage/deployment_v1_5/"

(
  cd "$stage"
  find . -type f ! -path './deployment_v1_5/DEPLOY_MANIFEST.sha256' -print0 \
    | sort -z | xargs -0 sha256sum > deployment_v1_5/DEPLOY_MANIFEST.sha256
  ! grep -qE '(^|/)code_v1_5/' deployment_v1_5/DEPLOY_MANIFEST.sha256
)
manifest_sha=$(sha256sum "$stage/deployment_v1_5/DEPLOY_MANIFEST.sha256" | awk '{print $1}')
remote_tmp=$REMOTE_ROOT/.residue_v1_5_orchestration_${manifest_sha:0:16}_$$

# First validate the already-deployed immutable code and model. No code file is uploaded.
remote_validation_json=$("$SSH_BIN" "$REMOTE_HOST" "python3 - '$REMOTE_CODE_ROOT' '$REMOTE_MODEL' '$MODEL_SHA'" <<'PYREMOTEVALIDATE'
import hashlib,json,os,pathlib,re,subprocess,sys,tempfile
code=pathlib.Path(sys.argv[1]); model=pathlib.Path(sys.argv[2]); model_sha=sys.argv[3]
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(8*1024*1024),b''): h.update(block)
    return h.hexdigest()
expected={
 'residue_v1/IMPLEMENTATION_FREEZE_V1_5.json':'3a4046462bcf138c25c5c36005d1f6e24f2df3f931fe32369dba80ee834e155e',
 'residue_v1/src/train_nested_residue_surrogate_v1_5.py':'6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af',
 'residue_v1/src/collect_residue_oof_v1_5.py':'a15db4aceaeb8c62bca277d9d39015aff3e7e95bacf30a3dd635c1d18558cee0',
 'PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json':'dddc693483c1f9a4145b6e28b74bdc9290ec5e7544e9da302e88cc4c10aa1226',
 'data/materialized_v1_1/v6_supervised1507.tsv':'ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633',
}
for relative,digest in expected.items():
    path=code/relative; assert path.is_file() and not path.is_symlink() and sha(path)==digest,(relative,sha(path) if path.is_file() else None)
freeze=json.loads((code/'residue_v1/IMPLEMENTATION_FREEZE_V1_5.json').read_text())
for relative,digest in freeze['implementation_sha256'].items():
    path=code/'residue_v1'/relative; assert path.is_file() and not path.is_symlink() and sha(path)==digest,relative
assert model.is_file() and not model.is_symlink() and sha(model)==model_sha
residue=code/'residue_v1'
python=pathlib.Path('/data1/qlyu/software/envs/pvrig-v6-tc/bin/python')
assert python.is_file() and os.access(python,os.X_OK),python
compile_sources=sorted((residue/'src').glob('*.py'))+sorted((residue/'tests').glob('*.py'))
assert compile_sources
with tempfile.TemporaryDirectory(prefix='pvrig_v1_5_pycompile_') as temporary:
    compile_env=dict(os.environ)
    compile_env['PYTHONPYCACHEPREFIX']=temporary
    compile_run=subprocess.run(
        [str(python),'-m','py_compile',*[str(path) for path in compile_sources]],
        cwd=residue,env=compile_env,text=True,capture_output=True,
    )
    assert compile_run.returncode==0,compile_run.stdout+'\n'+compile_run.stderr
env=dict(os.environ)
env['PYTHONPATH']=str(residue/'src')
env['PYTHONDONTWRITEBYTECODE']='1'
test=subprocess.run(
    [str(python),'-m','unittest','discover','-s',str(residue/'tests'),'-p','test_*.py','-v'],
    cwd=residue,env=env,text=True,capture_output=True,
)
test_output=test.stdout+'\n'+test.stderr
assert test.returncode==0,test_output[-8000:]
match=re.search(r'Ran\s+(\d+)\s+tests?',test_output)
assert match and int(match.group(1))==41,test_output[-8000:]
assert re.search(r'(^|\n)OK\s*$',test_output),test_output[-8000:]
print(json.dumps({'status':'PASS_EXISTING_CODE_V1_5_MODEL_AND_REMOTE_TEST_VALIDATION','implementation_files':len(freeze['implementation_sha256']),'remote_test_count':41,'remote_test_result':'PASS','py_compile_file_count':len(compile_sources)},sort_keys=True))
PYREMOTEVALIDATE
)
python3 - "$remote_validation_json" <<'PYLOCALVALIDATE'
import json,sys
x=json.loads(sys.argv[1])
assert x['status']=='PASS_EXISTING_CODE_V1_5_MODEL_AND_REMOTE_TEST_VALIDATION'
assert x['remote_test_count']==41 and x['remote_test_result']=='PASS'
assert x['py_compile_file_count']>0
PYLOCALVALIDATE

"$SSH_BIN" "$REMOTE_HOST" "python3 - '$remote_tmp'" <<'PYREMOTESTAGE'
import pathlib,shutil,sys
path=pathlib.Path(sys.argv[1])
if path.exists():
    assert path.is_dir() and not path.is_symlink()
    shutil.rmtree(path)
path.mkdir(parents=True)
PYREMOTESTAGE
tar -C "$stage" -cf - . | "$SSH_BIN" "$REMOTE_HOST" "tar -C '$remote_tmp' -xf -"
"$SSH_BIN" "$REMOTE_HOST" "python3 - '$remote_tmp' '$REMOTE_ROOT' '$REMOTE_MODEL' '$MODEL_SHA' '$manifest_sha'" <<'PYREMOTEINSTALL'
import datetime,hashlib,json,os,pathlib,shutil,sys
stage=pathlib.Path(sys.argv[1]); root=pathlib.Path(sys.argv[2]); model=pathlib.Path(sys.argv[3]); model_sha=sys.argv[4]; expected_manifest_sha=sys.argv[5]
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(8*1024*1024),b''): h.update(block)
    return h.hexdigest()
manifest=stage/'deployment_v1_5/DEPLOY_MANIFEST.sha256'
assert manifest.is_file() and not manifest.is_symlink() and sha(manifest)==expected_manifest_sha
entries=[]
for line in manifest.read_text().splitlines():
    digest,relative=line.split(None,1); relative=relative.lstrip('*').removeprefix('./')
    assert not relative.startswith('code_v1_5/'), 'immutable_code_upload_forbidden'
    source=stage/relative; assert source.is_file() and not source.is_symlink() and sha(source)==digest
    entries.append((digest,relative,source))
for digest,relative,source in entries:
    destination=root/relative
    if destination.exists() or destination.is_symlink():
        assert destination.is_file() and not destination.is_symlink() and sha(destination)==digest, f'existing_destination_mismatch:{destination}'
        continue
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name('.'+destination.name+'.deploy.tmp')
    shutil.copy2(source,temporary); assert sha(temporary)==digest; os.replace(temporary,destination)
assert model.is_file() and not model.is_symlink() and sha(model)==model_sha
receipt={'schema_version':'pvrig_v6_residue_v1_5_exact_orchestration_deployment_receipt_v1_1','status':'PASS_RESIDUE_V1_5_EXACT_DEPLOYMENT_NOT_LAUNCHED','manifest_sha256':expected_manifest_sha,'file_count':len(entries),'immutable_code_v1_5_touched':False,'model_identity':{'path':str(model),'sha256':model_sha},'remote_test_count':41,'remote_test_result':'PASS','remote_py_compile_result':'PASS','remote_jobs_launched':False,'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
receipt_path=root/'deployment_v1_5/DEPLOYMENT_RECEIPT.json'; receipt_path.parent.mkdir(parents=True,exist_ok=True)
if receipt_path.exists():
    old=json.loads(receipt_path.read_text()); assert old.get('manifest_sha256')==expected_manifest_sha,'existing_deployment_receipt_mismatch'; assert old.get('remote_test_count')==41 and old.get('remote_test_result')=='PASS','existing_deployment_remote_test_gate_missing'
else:
    tmp=receipt_path.with_name('.DEPLOYMENT_RECEIPT.json.tmp'); tmp.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n'); os.replace(tmp,receipt_path)
shutil.rmtree(stage); print(json.dumps(receipt,sort_keys=True))
PYREMOTEINSTALL

echo "PASS_RESIDUE_V1_5_EXACT_DEPLOYMENT_NOT_LAUNCHED manifest_sha256=$manifest_sha"
