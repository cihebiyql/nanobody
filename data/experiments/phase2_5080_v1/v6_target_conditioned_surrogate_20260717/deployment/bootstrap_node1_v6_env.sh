#!/usr/bin/env bash
set -euo pipefail

BASE_ENV=/data1/qlyu/software/envs/vhh-igfold
V6_ENV=/data1/qlyu/software/envs/pvrig-v6-tc
RUNTIME=/data1/qlyu/projects/pvrig_v6_target_conditioned_surrogate_20260717
PROXY=http://127.0.0.1:10800

export HTTP_PROXY="$PROXY"
export HTTPS_PROXY="$PROXY"
export http_proxy="$PROXY"
export https_proxy="$PROXY"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1

mkdir -p "$RUNTIME"/{env,logs,status,inputs,outputs,checkpoints,tmp}

free_gb=$(df -BG --output=avail /data1 | tail -1 | tr -dc '0-9')
if [[ -z "$free_gb" || "$free_gb" -lt 180 ]]; then
  echo "insufficient_data1_free_gb:${free_gb:-unknown}" >&2
  exit 31
fi

if [[ ! -x "$BASE_ENV/bin/python" ]]; then
  echo "missing_base_python:$BASE_ENV/bin/python" >&2
  exit 32
fi

if [[ ! -x "$V6_ENV/bin/python" ]]; then
  "$BASE_ENV/bin/python" -m venv --system-site-packages "$V6_ENV"
fi

base_site=$(
  "$BASE_ENV/bin/python" - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)
v6_site=$(
  "$V6_ENV/bin/python" - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)
printf '%s\n' "$base_site" > "$v6_site/00_pvrig_v6_base_env.pth"

"$V6_ENV/bin/python" -m pip install --upgrade --no-deps \
  'accelerate>=1.2,<2' \
  'peft>=0.14,<1' \
  >"$RUNTIME/logs/bootstrap_pip.log" 2>&1

"$V6_ENV/bin/python" - <<'PY' >"$RUNTIME/logs/bootstrap_imports.log"
import json
import torch, transformers, accelerate, peft, sklearn, scipy
payload = {
    "torch": torch.__version__,
    "transformers": transformers.__version__,
    "accelerate": accelerate.__version__,
    "peft": peft.__version__,
    "sklearn": sklearn.__version__,
    "scipy": scipy.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda_device_count": torch.cuda.device_count(),
    "gpu_names": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
}
print(json.dumps(payload, indent=2, sort_keys=True))
if not payload["cuda_available"] or payload["cuda_device_count"] < 5:
    raise SystemExit("insufficient_cuda_devices")
PY

"$V6_ENV/bin/python" - <<'PY' >"$RUNTIME/status/environment_receipt.json"
import datetime, hashlib, json, os, pathlib, subprocess

paths = {
    "esmc_600m": pathlib.Path("/data/qlyu/.cache/huggingface/hub/models--EvolutionaryScale--esmc-600m-2024-12/snapshots/d11cc14d44078eaecbc6a843d5eb20f4eecc1e7e/data/weights/esmc_600m_2024_12_v0.pth"),
    "esm2_650m": pathlib.Path("/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t33_650M_UR50D/snapshots/08e4846e537177426273712802403f7ba8261b6c/model.safetensors"),
    "esm2_3b_1": pathlib.Path("/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t36_3B_UR50D/snapshots/476b639933c8baad5ad09a60ac1a87f987b656fc/pytorch_model-00001-of-00002.bin"),
    "esm2_3b_2": pathlib.Path("/data/qlyu/.cache/huggingface/hub/models--facebook--esm2_t36_3B_UR50D/snapshots/476b639933c8baad5ad09a60ac1a87f987b656fc/pytorch_model-00002-of-00002.bin"),
}
def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(8*1024*1024), b""):
            h.update(block)
    return h.hexdigest()
payload={
    "schema_version":"pvrig_v6_node1_environment_receipt_v1",
    "status":"PASS_NODE1_V6_ENVIRONMENT_READY",
    "created_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "environment":"/data1/qlyu/software/envs/pvrig-v6-tc",
    "base_environment":"/data1/qlyu/software/envs/vhh-igfold",
    "gpu_indices_reserved":[1,2,3,4],
    "model_files":{},
}
for name,path in paths.items():
    if not path.is_file():
        raise SystemExit(f"missing_model_file:{name}:{path}")
    payload["model_files"][name]={"path":str(path),"bytes":path.stat().st_size,"sha256":sha256(path)}
print(json.dumps(payload,indent=2,sort_keys=True))
PY

echo PASS_NODE1_V6_ENVIRONMENT_READY
