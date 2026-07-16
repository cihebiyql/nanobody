#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/data/qlyu/projects/pvrig_pre_shortlist100_deepqc_v1_20260716
PYTHON=/data/qlyu/software/envs/vhh-eval/bin/python
MAX_WAIT_SECONDS=${MAX_WAIT_SECONDS:-86400}
cd "$ROOT"

mkdir -p status reports logs
exec 9>status/package_watcher.lock
flock -n 9 || exit 75

write_status() {
  local state=$1 reason=$2
  STATE_VALUE=$state REASON_VALUE=$reason "$PYTHON" - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
Path("status/package_watcher_status.json").write_text(json.dumps({
    "status": os.environ["STATE_VALUE"],
    "reason": os.environ["REASON_VALUE"],
    "updated_at": datetime.now(timezone.utc).isoformat(),
}, indent=2, sort_keys=True) + "\n")
PY
}

fail() {
  local rc=$? line=$1
  write_status FAILED "postprocess_error_line=$line rc=$rc"
  exit "$rc"
}
trap 'fail $LINENO' ERR

if [[ -s reports/deepqc_delivery_receipt_v1.json &&
      -s reports/deepqc_delivery_v1.tar.gz &&
      -s reports/deepqc_delivery_v1.tar.gz.sha256 ]] &&
   sha256sum -c reports/deepqc_delivery_v1.tar.gz.sha256 >/dev/null 2>&1 &&
   "$PYTHON" - <<'PY'
import json
from pathlib import Path
p=Path("reports/deepqc_delivery_receipt_v1.json")
raise SystemExit(0 if json.loads(p.read_text()).get("status")=="PASS_DEEPQC100_DELIVERY_READY" else 1)
PY
then
  write_status COMPLETE "existing hash-bound DeepQC delivery verified"
  exit 0
fi

started=$(date +%s)
write_status WAITING_DEEPQC "waiting for terminal Top100 TNP/IgFold run"
while true; do
  status=$($PYTHON - <<'PY'
import json
from pathlib import Path
p=Path("status/deepqc_status.json")
print(json.loads(p.read_text()).get("status","MISSING") if p.is_file() else "MISSING")
PY
)
  case "$status" in
    COMPLETE) break ;;
    FAILED) write_status BLOCKED "deepqc_failed"; exit 2 ;;
  esac
  if (( $(date +%s) - started > MAX_WAIT_SECONDS )); then
    write_status BLOCKED "deepqc_wait_timeout_seconds=$MAX_WAIT_SECONDS"
    exit 3
  fi
  sleep 300
done

write_status PACKAGING "validating 100-row TNP/IgFold closure and building delivery"
$PYTHON - <<'PY'
import csv, hashlib, json
from pathlib import Path

root=Path(".")
def rows(path):
    with path.open(newline="", encoding="utf-8-sig") as h:
        return list(csv.DictReader(h, delimiter="\t"))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

tnp=rows(root/"reports/tnp_summary.tsv")
ig=rows(root/"reports/igfold_summary.tsv")
tnp_ids={r["id"] for r in tnp}; ig_ids={r["id"] for r in ig}
pdbs=sorted(root.glob("runs/igfold_*/structures/*/igfold.pdb"))
if len(tnp)!=100 or len(tnp_ids)!=100:
    raise SystemExit(f"TNP closure failed rows={len(tnp)} ids={len(tnp_ids)}")
if len(ig)!=100 or len(ig_ids)!=100 or tnp_ids != ig_ids:
    raise SystemExit(f"IgFold closure failed rows={len(ig)} ids={len(ig_ids)} parity={tnp_ids==ig_ids}")
if len(pdbs)!=100:
    raise SystemExit(f"IgFold PDB closure failed count={len(pdbs)}")

files=[
    root/"run_deepqc.sh", root/"deepqc_config.json", root/"input_audit.json",
    root/"inputs/pre_shortlist100.fasta", root/"inputs/pre_shortlist100.tsv",
    root/"reports/tnp_summary.tsv", root/"reports/tnp_merge.json",
    root/"reports/igfold_summary.tsv", root/"reports/igfold_merge.json",
    root/"reports/INPUT_SHA256SUMS.txt", root/"status/deepqc_status.json", *pdbs,
]
manifest=root/"reports/delivery_file_manifest.tsv"
with manifest.open("w", encoding="utf-8", newline="") as h:
    h.write("path\tbytes\tsha256\n")
    for p in files:
        raw=p.read_bytes(); h.write(f"{p.as_posix()}\t{len(raw)}\t{hashlib.sha256(raw).hexdigest()}\n")
receipt={
    "schema_version":"pvrig_pre_shortlist100_deepqc_delivery_v1",
    "status":"PASS_DEEPQC100_DELIVERY_READY",
    "candidate_count":100, "tnp_row_count":len(tnp),
    "igfold_row_count":len(ig), "igfold_pdb_count":len(pdbs),
    "id_parity":tnp_ids==ig_ids,
    "delivery_manifest_sha256":sha(manifest),
    "run_deepqc_sha256":sha(root/"run_deepqc.sh"),
    "deepqc_config_sha256":sha(root/"deepqc_config.json"),
    "input_audit_sha256":sha(root/"input_audit.json"),
    "input_fasta_sha256":sha(root/"inputs/pre_shortlist100.fasta"),
    "claim_boundary":"TNP and monomer-structure QC annotations only; not PVRIG binding, affinity, docking, or experimental blocking evidence.",
}
(root/"reports/deepqc_delivery_receipt_v1.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
PY

{
  printf '%s\0' run_deepqc.sh deepqc_config.json input_audit.json \
    inputs/pre_shortlist100.fasta inputs/pre_shortlist100.tsv \
    reports/tnp_summary.tsv reports/tnp_merge.json \
    reports/igfold_summary.tsv reports/igfold_merge.json \
    reports/INPUT_SHA256SUMS.txt reports/delivery_file_manifest.tsv \
    reports/deepqc_delivery_receipt_v1.json status/deepqc_status.json
  find runs -path 'runs/igfold_*/structures/*/igfold.pdb' -type f -print0 | sort -z
} | tar --null -T - -czf reports/deepqc_delivery_v1.tar.gz
sha256sum reports/deepqc_delivery_v1.tar.gz >reports/deepqc_delivery_v1.tar.gz.sha256
write_status COMPLETE "100-row DeepQC delivery ready"
