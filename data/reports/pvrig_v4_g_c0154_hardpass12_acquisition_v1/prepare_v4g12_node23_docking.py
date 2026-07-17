#!/usr/bin/env python3
"""Build the sealed 72-job V4-G C0154 acquisition-only docking package.

The package inherits byte-identical V4-D physical render/run code and exact
normalized receptor/reference inputs.  It never reads any V4-D result, pose,
score, or label.  Candidate membership is bound exclusively to the exact V4-G
Full-QC recovery receipt and the Node1 hard-pass-12 structure receipt.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_COUNT = 12
EXPECTED_JOBS = 72
EXPECTED_PARENT = "PLDNANO_VHH_00220"
EXPECTED_CLUSTER = "C0154"
EXPECTED_NODE1_PREREG_SHA256 = "4b11ab21d9abcca4092a78c9bdbe9c4d514d871ac143ede8c8e19a473da1da7d"
EXPECTED_RECOVERY_RECEIPT_SHA256 = "7b2786274045a45d7b487fa7b9cc4e14d7a2e6215e2cb6286d950e2b9632f356"
EXPECTED_FULL_MERGED_SHA256 = "f6b0ca1d3de522f6cc3269d498bcd89cd40e73576b81d16291bd81f49b7d6962"
SOURCE_PROTOCOL_ID = "pvrig_v4_d_fullqc290_dual_redocking_20260715"
SOURCE_CORE_HASH = "91d75291ff832c1e94cbc0bf6f1cdd75de6a8bb74611230cdcd1716466f37cb7"
SOURCE_PROTOCOL_LOCK_VALUE = "a24eaf37730bc569067d64cdc1a43a763b70878d13d50e804bf3000ce43f5e84"
SOURCE_ROOT_DEFAULT = Path("/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715")
CLAIM_BOUNDARY = (
    "acquisition_only_independent_8x6b_9e6y_x3seed_computational_geometry;"
    "not_binding_affinity_competition_experimental_blocking_or_docking_gold"
)
SOURCE_FILES = {
    "config/protocol_spec.json": "89331894ee74274b82fddae4ecabc413351a6b68721f2a096cc0fca6415c78e8",
    "config/blocker_judgment_rules_v2.json": "60424c514d0e1c4f32bfec28631b969ed511c89babb4a73dcecf504e1e6a16a5",
    "inputs/normalized/8x6b_pvrig_receptor.pdb": "31b530edf01fe9b8f354935cc6140d863ba78faf50f93cf5303d0223c2a94e5a",
    "inputs/normalized/8x6b_TL_reference.pdb": "80c9e36c63ba9fa8f28f606ad5864d9eb8c50b9b228424e1db5cdfc1bc6725b0",
    "inputs/normalized/9e6y_pvrig_receptor.pdb": "c850363e92aa0ed00266b0f49ecea364bc661a768b2ac3ebe90cc8946b6f64c6",
    "inputs/normalized/9e6y_TL_reference.pdb": "01f13b5899624cb8c0450c458fbe055cae706804a78a0f7997940b787e6f2744",
    "inputs/normalized/interface_hotspots_uniprot.tsv": "dacb4f3fbf8aeaea17885ebfe0a548857a52f5ac863429e648af55ea196a7d44",
    "inputs/source/PVRIG_hotspot_set_v1.csv": "9e5e82ad1f8193efbbb72865a632528c6b6a08d8a686c5b3e8ac74d2fd1564dd",
    "reports/reference_normalization_summary.json": "7fa190ed91a1bbafcdcc21f6cd74f0345b43b3a3e6e8379c3bf3f1810abeb1c3",
    "scripts/common.py": "479cff3f2215f45952009d54869462cd90937cca56e15ddaf6af54a418f16d4a",
    "scripts/build_docking_jobs.py": "41b1e7755f0b435930dbf87bd0d11dd542c6567cc2e1e9a82526df2b7d6328f7",
    "scripts/run_job.py": "9957e6dc80db2345737576d65606601064725c09b654518b1df76427e48a3d0a",
    "scripts/run_controller.py": "682aa8eb41d517c648b27194886c44d1a4a1096a63ce574cc65ff909e31546af",
    "scripts/status.py": "3911523d71a06167ff3b9d780abf183cc0295c73f27cb32cda855f5771e1231c",
    "scripts/score_pose.py": "979f9c48ce0be744f9b1ab53b854d43b3444d576755a7b293c2c11553b30d6b9",
    "PROTOCOL_CORE_LOCK.json": "767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24",
    "PROTOCOL_LOCK.json": "56ef539cb54a1aba8e665ec5d62b3653088e2289e371d8fa5bbadbc725c1d574",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_source(source_root: Path) -> None:
    for relative, expected in SOURCE_FILES.items():
        path = source_root / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"frozen V4-D source hash mismatch: {path}")
    source_spec = json.loads((source_root / "config/protocol_spec.json").read_text(encoding="utf-8"))
    docking = source_spec["docking"]
    expected = {
        "ncores": 4, "sampling": 40, "seeds": [917, 1931, 3253],
        "seletop_select": 10, "seletopclusts_top_models": 4,
        "rigidbody_tolerance": 5, "flexref_tolerance": 10,
        "randremoval": True, "npart": 2,
    }
    if any(docking.get(key) != value for key, value in expected.items()):
        raise RuntimeError("V4-D physical protocol field drift")


def wrapper_source() -> str:
    return r'''#!/usr/bin/env python3
"""Acquisition-only 12-candidate wrapper around frozen V4-D physical renderer."""
from __future__ import annotations
import argparse, sys
import v4d_build_docking_jobs_frozen as frozen
from v4d_build_docking_jobs_frozen import (
    JOB_FIELDS, CONFORMATIONS, available_residue_numbers, make_job, parse_range,
    render_cfg_from_job, render_restraints_from_job, unique_sequence_range,
)
from common import read_tsv, sha256_file, write_json, write_tsv

def load_candidates():
    root=frozen.root(); spec=frozen.protocol()
    rows=read_tsv(root/'inputs/candidates_12.tsv')
    monomer_rows=read_tsv(root/'inputs/candidate_monomers_manifest.tsv')
    monomers={row['candidate_id']:row for row in monomer_rows}
    expected=int(spec['candidate_panel']['expected_count'])
    if len(rows)!=expected or len(monomers)!=expected: raise RuntimeError('candidate/monomer count drift')
    entities=[]
    for row in rows:
        cid=row['candidate_id']; mon=monomers[cid]; path=root/mon['frozen_monomer_path']
        if not path.is_file() or sha256_file(path)!=mon['sha256']: raise RuntimeError(f'monomer hash mismatch: {cid}')
        if mon['sequence_sha256']!=row['sequence_sha256']: raise RuntimeError(f'sequence hash mismatch: {cid}')
        ranges={k:unique_sequence_range(row['sequence'],row[k],k,cid) for k in ('cdr1','cdr2','cdr3')}
        requested=set().union(*(set(parse_range(v)) for v in ranges.values()))
        if not requested.issubset(available_residue_numbers(path,mon['source_chain'])):
            raise RuntimeError(f'monomer lacks CDR residues: {cid}')
        entities.append({
          'entity_id':cid,'control_class':'','expected_behavior':'CANDIDATE_UNKNOWN',
          'sequence_sha256':row['sequence_sha256'],
          **{f'{k}_range':v for k,v in ranges.items()},
          'cdr_residues':','.join(map(str,sorted(requested))),
          'monomer_source':mon['frozen_monomer_path'],
          'monomer_source_kind':'frozen_node1_nbb2_acquisition',
          'monomer_source_chain':mon['source_chain'],
        })
    if len({e['entity_id'] for e in entities})!=expected: raise RuntimeError('duplicate candidate IDs')
    return sorted(entities,key=lambda e:e['entity_id'])

def build_jobs():
    jobs=[]; priority=0; seeds=[int(x) for x in frozen.protocol()['docking']['seeds']]
    for entity in load_candidates():
      for conf in CONFORMATIONS:
       for seed in seeds:
        priority+=1; jobs.append(make_job('candidate',entity,conf,seed,priority))
    expected=int(frozen.protocol()['docking']['expected_total_jobs'])
    if len(jobs)!=expected or len({j['job_id'] for j in jobs})!=expected or len({j['job_hash'] for j in jobs})!=expected:
        raise RuntimeError('72-job closure failed')
    return jobs

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--output',default='manifests/docking_jobs.tsv'); p.add_argument('--summary',default='reports/job_manifest_summary.json'); a=p.parse_args(argv)
    try:
      jobs=build_jobs(); out=frozen.root()/a.output; write_tsv(out,jobs,JOB_FIELDS)
      write_json(frozen.root()/a.summary,{
        'status':'PASS_ACQUISITION_72_JOB_MANIFEST','job_count':len(jobs),
        'candidate_jobs':len(jobs),'control_jobs':0,'sha256':sha256_file(out),
        'source_v4d_physical_core_sha256':jobs[0]['protocol_core_sha256'],
      }); return 0
    except Exception as e:
      print(f'ERROR: {e}',file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
'''


def waiter_source() -> str:
    return r'''#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=${PVRIG_V4G12_ROOT:?PVRIG_V4G12_ROOT required}
SOURCE=${PVRIG_V4D_SOURCE:-/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715}
POLL=${PVRIG_V4G12_POLL_SECONDS:-300}
MAX_LOAD1=${PVRIG_V4G12_MAX_LOAD1:-16}
mkdir -p "$ROOT/status" "$ROOT/logs"
echo $$ > "$ROOT/status/waiter.pid"
while true; do
  set +e
  python3 - "$ROOT" "$SOURCE" "$MAX_LOAD1" "$0" <<'PY'
import hashlib,json,os,sys
from pathlib import Path
root,source,max_load,self_path=Path(sys.argv[1]),Path(sys.argv[2]),float(sys.argv[3]),Path(sys.argv[4])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
anchor=json.loads((root/'WAITER_TRUST_ANCHOR.json').read_text())
assert sha(root/'ACQUISITION_PROTOCOL_LOCK.json')==anchor['acquisition_protocol_lock_sha256']
assert sha(self_path)==anchor['waiter_sha256']
lock=json.loads((root/'ACQUISITION_PROTOCOL_LOCK.json').read_text())
assert lock['status']=='LOCKED_ACQUISITION_ONLY_72_JOBS'
controller=json.loads((source/'status/controller.json').read_text())
terminal=controller.get('status') in {'COMPLETE','COMPLETE_WITH_FAILURES'}
counts=controller.get('counts') or controller.get('counts_before') or {}
closed=int(counts.get('SUCCESS',0))+int(counts.get('FAILED_MAX_ATTEMPTS',0))==2022
no_active=int(counts.get('RUNNING',0))==0 and int(counts.get('PENDING',0))==0 and int(counts.get('QUEUED',0))==0
load1=os.getloadavg()[0]
payload={'source_status':controller.get('status'),'counts':counts,'terminal':terminal,'closed':closed,'no_active':no_active,'load1':load1,'max_load1':max_load}
(root/'status/waiter_gate.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
if not (terminal and closed and no_active and load1<=max_load): raise SystemExit(3)
PY
  rc=$?
  set -e
  if [[ $rc -eq 0 ]]; then break; fi
  echo "WAIT_V4D_TERMINAL_OR_LOAD $(date -Is) rc=$rc" >> "$ROOT/logs/waiter.log"
  sleep "$POLL"
done
echo "GATE_PASS_START_ACQUISITION $(date -Is)" >> "$ROOT/logs/waiter.log"
cd "$ROOT"
export PVRIG_PROJECT_ROOT="$ROOT"
exec /data/qlyu/anaconda3/envs/haddock3/bin/python scripts/run_controller.py \
  --max-parallel 12 --max-attempts 2 --poll-seconds 60 \
  >> "$ROOT/logs/acquisition_controller.log" 2>&1
'''


def acquisition_test_source() -> str:
    return r'''#!/usr/bin/env python3
import csv,hashlib,json,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts')); os.environ['PVRIG_PROJECT_ROOT']=str(ROOT)
import build_docking_jobs as jobs
class AcquisitionProtocolTest(unittest.TestCase):
 def test_exact_72_matrix(self):
  rows=jobs.build_jobs(); self.assertEqual(len(rows),72)
  self.assertEqual({r['conformation'] for r in rows},{'8x6b','9e6y'})
  self.assertEqual({int(r['seed']) for r in rows},{917,1931,3253})
  self.assertEqual(len({r['entity_id'] for r in rows}),12)
  self.assertEqual({r['protocol_core_sha256'] for r in rows},{'91d75291ff832c1e94cbc0bf6f1cdd75de6a8bb74611230cdcd1716466f37cb7'})
 def test_physical_config_exact(self):
  spec=json.loads((ROOT/'config/protocol_spec.json').read_text()); d=spec['docking']
  self.assertEqual({k:d[k] for k in ('ncores','sampling','seeds','seletop_select','seletopclusts_top_models','rigidbody_tolerance','flexref_tolerance','randremoval','npart')},{'ncores':4,'sampling':40,'seeds':[917,1931,3253],'seletop_select':10,'seletopclusts_top_models':4,'rigidbody_tolerance':5,'flexref_tolerance':10,'randremoval':True,'npart':2})
 def test_no_results_or_labels_at_freeze(self):
  self.assertFalse((ROOT/'results').exists()); self.assertFalse((ROOT/'runs').exists())
  for p in ROOT.rglob('*'):
   if p.is_file(): self.assertNotIn('docking_gold',p.name.lower())
if __name__=='__main__': unittest.main()
'''


def build(args: argparse.Namespace) -> dict[str, Any]:
    source_root, staging, output = args.source_root, args.staging, args.output_root
    validate_source(source_root)
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"refusing non-empty output root: {output}")
    prereg_path, selection_path = staging / "PREREGISTRATION.json", staging / "hardpass12.tsv"
    structure_receipt_path, monomer_manifest_path = staging / "structures.complete.json", staging / "monomer_manifest.tsv"
    for path in (prereg_path, selection_path, structure_receipt_path, monomer_manifest_path):
        if not path.is_file(): raise RuntimeError(f"missing staging input: {path}")
    if sha256_file(prereg_path) != EXPECTED_NODE1_PREREG_SHA256:
        raise RuntimeError("Node1 preregistration hash drift")
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    if prereg["frozen_inputs"]["recovery_receipt_sha256"] != EXPECTED_RECOVERY_RECEIPT_SHA256 or prereg["frozen_inputs"]["full_merged_sha256"] != EXPECTED_FULL_MERGED_SHA256:
        raise RuntimeError("Node1 preregistration recovery binding drift")
    if sha256_file(selection_path) != prereg["frozen_inputs"]["hardpass12_manifest_sha256"]:
        raise RuntimeError("hardpass12 manifest hash drift")
    selection = read_tsv(selection_path)
    if len(selection) != EXPECTED_COUNT or [r["candidate_id"] for r in selection] != prereg["selection"]["candidate_ids"]:
        raise RuntimeError("candidate identity/order drift")
    if {r["parent_id"] for r in selection} != {EXPECTED_PARENT} or {r["parent_framework_cluster"] for r in selection} != {EXPECTED_CLUSTER}:
        raise RuntimeError("parent/cluster drift")
    structure_receipt = json.loads(structure_receipt_path.read_text(encoding="utf-8"))
    if structure_receipt.get("status") != "PASS_V4_G_HARDPASS12_NBB2_IGFOLD_STRUCTURE_ACQUISITION" or structure_receipt.get("candidate_count") != EXPECTED_COUNT:
        raise RuntimeError("structure receipt is not a 12-candidate PASS")
    if sha256_file(monomer_manifest_path) != structure_receipt.get("manifest_sha256"):
        raise RuntimeError("structure receipt does not bind monomer manifest")
    monomers = {row["candidate_id"]: row for row in read_tsv(monomer_manifest_path)}
    if set(monomers) != {r["candidate_id"] for r in selection}:
        raise RuntimeError("monomer/candidate ID closure failed")

    for name in ("config", "inputs/normalized", "inputs/source", "inputs/candidate_monomers", "manifests", "reports", "scripts", "status", "tests", "logs"):
        (output / name).mkdir(parents=True, exist_ok=True)
    # Copy only frozen protocol code/reference inputs; never copy V4-D runs/results/status.
    direct = [
        "config/blocker_judgment_rules_v2.json",
        "inputs/normalized/8x6b_pvrig_receptor.pdb", "inputs/normalized/8x6b_TL_reference.pdb",
        "inputs/normalized/9e6y_pvrig_receptor.pdb", "inputs/normalized/9e6y_TL_reference.pdb",
        "inputs/normalized/interface_hotspots_uniprot.tsv", "inputs/source/PVRIG_hotspot_set_v1.csv",
        "reports/reference_normalization_summary.json",
        "scripts/common.py", "scripts/run_job.py", "scripts/run_controller.py", "scripts/status.py", "scripts/score_pose.py",
    ]
    for relative in direct:
        destination = output / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source_root / relative, destination)
    shutil.copy2(source_root / "scripts/build_docking_jobs.py", output / "scripts/v4d_build_docking_jobs_frozen.py")
    shutil.copy2(source_root / "PROTOCOL_CORE_LOCK.json", output / "SOURCE_V4D_PROTOCOL_CORE_LOCK.json")
    shutil.copy2(source_root / "PROTOCOL_LOCK.json", output / "SOURCE_V4D_PROTOCOL_LOCK.json")
    shutil.copy2(prereg_path, output / "NODE1_PREREGISTRATION.json")
    shutil.copy2(structure_receipt_path, output / "NODE1_STRUCTURE_RECEIPT.json")
    shutil.copy2(selection_path, output / "inputs/hardpass12_selection.tsv")

    candidate_fields = ["candidate_id", "sequence", "sequence_sha256", "cdr1", "cdr2", "cdr3", "parent_id", "parent_framework_cluster", "claim_boundary"]
    candidate_rows = [{k: row[k] for k in candidate_fields} for row in selection]
    write_tsv(output / "inputs/candidates_12.tsv", candidate_rows, candidate_fields)
    monomer_rows: list[dict[str, str]] = []
    for row in selection:
        cid = row["candidate_id"]; evidence = monomers[cid]
        source_pdb = staging / "monomers" / f"{cid}.pdb"
        if not source_pdb.is_file() or sha256_file(source_pdb) != evidence["primary_pdb_sha256"]:
            raise RuntimeError(f"staged NBB2 monomer hash mismatch: {cid}")
        destination = output / "inputs/candidate_monomers" / f"{cid}.pdb"
        shutil.copy2(source_pdb, destination)
        monomer_rows.append({
            "candidate_id": cid, "sequence_sha256": row["sequence_sha256"],
            "frozen_monomer_path": str(destination.relative_to(output)), "source_chain": "A",
            "sha256": sha256_file(destination), "source_method": "NanoBodyBuilder2",
            "node1_structure_receipt_sha256": sha256_file(structure_receipt_path),
        })
    write_tsv(output / "inputs/candidate_monomers_manifest.tsv", monomer_rows)

    source_spec = json.loads((source_root / "config/protocol_spec.json").read_text(encoding="utf-8"))
    spec = json.loads(json.dumps(source_spec))
    spec["protocol_id"] = "pvrig_v4_g_c0154_hardpass12_dual_redocking_v1_20260717"
    spec["candidate_panel"] = {
        "expected_count": 12, "panel_id": "v4_g_c0154_exact_fullqc_hardpass12",
        "selection_algorithm": "every_and_only_hard_fail_false_from_exact_recovery",
        "replacement_policy": "NO_REPLACEMENT", "parent_framework_cluster": EXPECTED_CLUSTER,
        "monomer_source_policy": "12_Node1_NanoBodyBuilder2_PDBs_hash_bound_to_structure_receipt",
    }
    spec["controls"] = {"expected_count": 0, "panel_id": "none_acquisition_only"}
    spec["docking"].update({"expected_candidate_jobs": 72, "expected_control_jobs": 0, "expected_smoke_jobs": 0, "expected_total_jobs": 72})
    spec["evidence_boundary"] = CLAIM_BOUNDARY
    spec["status"] = "ACQUISITION_PREREGISTERED"
    write_json(output / "config/protocol_spec.json", spec)
    write_json(output / "PROTOCOL_CORE_LOCK.json", {
        "status": "CORE_LOCKED", "schema_version": 1,
        "protocol_core_sha256": SOURCE_CORE_HASH,
        "source_protocol_id": SOURCE_PROTOCOL_ID,
        "source_protocol_lock_sha256": SOURCE_PROTOCOL_LOCK_VALUE,
        "scope": "inherit_exact_V4_D_physical_renderer_and_parameters;new_candidate_inputs_bound_separately",
    })
    (output / "scripts/build_docking_jobs.py").write_text(wrapper_source(), encoding="utf-8")
    (output / "scripts/wait_for_v4d_terminal_then_run.sh").write_text(waiter_source(), encoding="utf-8")
    (output / "tests/test_acquisition_protocol.py").write_text(acquisition_test_source(), encoding="utf-8")
    for path in (output / "scripts/build_docking_jobs.py", output / "scripts/wait_for_v4d_terminal_then_run.sh", output / "tests/test_acquisition_protocol.py"):
        path.chmod(0o755)

    env = {**os.environ, "PVRIG_PROJECT_ROOT": str(output)}
    subprocess.run([sys.executable, str(output / "scripts/build_docking_jobs.py")], cwd=output, env=env, check=True)
    test = subprocess.run([sys.executable, "-m", "unittest", "-v", "tests/test_acquisition_protocol.py"], cwd=output, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / "reports/preflight_tests.log").write_text(test.stdout, encoding="utf-8")
    if test.returncode != 0 or "OK" not in test.stdout:
        raise RuntimeError("acquisition protocol tests failed")
    dry = subprocess.run([sys.executable, str(output / "scripts/run_controller.py"), "--dry-run", "--once", "--max-parallel", "12"], cwd=output, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / "reports/controller_dry_run.log").write_text(dry.stdout, encoding="utf-8")
    if dry.returncode != 0:
        raise RuntimeError("controller dry-run failed")
    # Remove only preflight runtime state; no run/result directory exists and no job was launched.
    controller_state = output / "status/controller.json"
    if controller_state.exists(): controller_state.unlink()
    controller_lock = output / "status/controller.lock"
    if controller_lock.exists(): controller_lock.unlink()

    lock_files = []
    excluded = {"ACQUISITION_PROTOCOL_LOCK.json", "WAITER_TRUST_ANCHOR.json"}
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p.name not in excluded):
        lock_files.append({"path": str(path.relative_to(output)), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    lock = {
        "schema_version": "pvrig_v4_g_c0154_hardpass12_acquisition_protocol_lock_v1",
        "status": "LOCKED_ACQUISITION_ONLY_72_JOBS",
        "locked_at_utc": utc_now(),
        "candidate_count": 12, "job_count": 72,
        "source_v4d_protocol_id": SOURCE_PROTOCOL_ID,
        "source_v4d_protocol_core_sha256": SOURCE_CORE_HASH,
        "source_v4d_protocol_lock_sha256": SOURCE_PROTOCOL_LOCK_VALUE,
        "node1_preregistration_sha256": sha256_file(prereg_path),
        "node1_structure_receipt_sha256": sha256_file(structure_receipt_path),
        "candidate_manifest_sha256": sha256_file(output / "inputs/candidates_12.tsv"),
        "monomer_manifest_sha256": sha256_file(output / "inputs/candidate_monomers_manifest.tsv"),
        "job_manifest_sha256": sha256_file(output / "manifests/docking_jobs.tsv"),
        "launch_gate": "source V4-D terminal closure plus node23 load1 <= 16",
        "files": lock_files, "claim_boundary": CLAIM_BOUNDARY,
    }
    lock_path = output / "ACQUISITION_PROTOCOL_LOCK.json"; write_json(lock_path, lock)
    waiter = output / "scripts/wait_for_v4d_terminal_then_run.sh"
    anchor = {
        "status": "TRUST_ANCHOR_FROZEN_BEFORE_WAITER_START",
        "acquisition_protocol_lock_sha256": sha256_file(lock_path),
        "waiter_sha256": sha256_file(waiter),
        "source_v4d_controller_path": str(source_root / "status/controller.json"),
        "created_at_utc": utc_now(),
    }
    write_json(output / "WAITER_TRUST_ANCHOR.json", anchor)
    receipt = {
        "status": "PASS_V4_G_C0154_HARDPASS12_DOCKING_PACKAGE_PREFLIGHT",
        "candidate_count": 12, "job_count": 72,
        "tests": 3, "controller_dry_run": "PASS_NO_LAUNCH",
        "acquisition_protocol_lock_sha256": sha256_file(lock_path),
        "waiter_trust_anchor_sha256": sha256_file(output / "WAITER_TRUST_ANCHOR.json"),
        "waiter_sha256": sha256_file(waiter),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    write_json(output / "reports/PREFLIGHT_RECEIPT.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT_DEFAULT)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args), indent=2, sort_keys=True)); return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
