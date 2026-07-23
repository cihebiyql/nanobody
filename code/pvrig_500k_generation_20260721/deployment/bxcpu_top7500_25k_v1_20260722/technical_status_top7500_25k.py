#!/usr/bin/env python3
from __future__ import annotations
import collections, csv, json, os, pathlib, time

root=pathlib.Path(os.environ["PVRIG_TOP7500_PUBLISH_ROOT"])
project="pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722"
manifest=pathlib.Path.home()/f"{project}.manifest.tsv"
expected=[]
if manifest.is_file():
    with manifest.open(newline="") as f: expected=[r["job_id"] for r in csv.DictReader(f,delimiter="\t")]
counts=collections.Counter(); terminal=0
for job_id in expected:
    path=root/"status/jobs"/f"{job_id}.json"
    if not path.is_file(): counts["MISSING"]+=1; continue
    try: state=json.load(path.open()).get("status","UNKNOWN")
    except Exception: state="INVALID_JSON"
    counts[state]+=1
    if state in {"SUCCESS","FAILED_MAX_ATTEMPTS"}: terminal+=1
payload={
    "schema_version":"pvrig_top7500_25k_technical_status_v1",
    "status":"COMPLETE" if len(expected)==25000 and terminal==25000 else "INCOMPLETE",
    "expected_jobs":len(expected), "terminal_jobs":terminal,
    "state_counts":dict(sorted(counts.items())), "updated_epoch":time.time(),
    "claim_boundary":"Technical Docking completion only; not biological blocking evidence.",
}
(root/"reports").mkdir(parents=True,exist_ok=True)
(root/"reports/TECHNICAL_COMPLETION.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
print(json.dumps(payload,sort_keys=True))
