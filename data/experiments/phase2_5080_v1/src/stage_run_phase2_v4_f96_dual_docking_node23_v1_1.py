#!/usr/bin/env python3
"""Stage and run V4-F96 hard-pass Docking by cloning the frozen V4-D runtime.

The input release contains all 96 Full-QC eligibility rows and one terminal
monomer attempt for every hard-pass row.  Only monomer-success hard-pass rows
enter HADDOCK; all other hard-pass rows remain technical failures without
replacement.  This script does not read surrogate scores.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, pstdev
from typing import Any, Mapping


SOURCE = Path("/data/qlyu/projects/pvrig_v4_d_fullqc290_dual_redocking_20260715")
INPUT_ROOT = Path("/data/qlyu/projects/pvrig_v4_f96_docking_input_release_v1_1_20260717")
ROOT = Path("/data/qlyu/projects/pvrig_v4_f96_dual_redocking_v1_1_20260717")
PYTHON = Path("/data/qlyu/anaconda3/envs/haddock3/bin/python")
HADDOCK3 = Path("/data/qlyu/anaconda3/envs/haddock3/bin/haddock3")
SCRATCH = Path("/tmp/pvrig_v4f96_dual_redocking_v1_1")
SEEDS = (917, 1931, 3253)
CONFORMATIONS = ("8x6b", "9e6y")
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "COMPLETE", "COMPLETED", "DONE"}
PROTOCOL_ID = "pvrig_v4_f96_independent_dual_redocking_v1_1_20260717"
EXPECTED_SOURCE = {
    "protocol_core_lock": "767117dc2c506cfdfc83fce8e12931514d268941348d69a9abbda5a6500bdd24",
    "protocol_lock": "56ef539cb54a1aba8e665ec5d62b3653088e2289e371d8fa5bbadbc725c1d574",
    "evaluator_gate": "fb01cdaa5939f2846b16e4e02a09903417cd6cea04d42350c4ed57f9ae7eb774",
    "aggregate": "b339c278c7146b5b1a6d1b0f106e06786ad6cfc6440998f3bbd7b272c7b18e4b",
    "run_job": "9957e6dc80db2345737576d65606601064725c09b654518b1df76427e48a3d0a",
    "run_controller": "682aa8eb41d517c648b27194886c44d1a4a1096a63ce574cc65ff909e31546af",
}
CLAIM = (
    "Fixed-PVRIG computational independent 8X6B/9E6Y Docking geometry only; "
    "not binding, affinity, competition, experimental blocking, Docking Gold, or final submission authority."
)
LABEL_FIELDS = [
    "candidate_id","sequence_sha256","parent_framework_cluster","model_split",
    "docking_status","R_dual_min","successful_seed_count_8X6B","successful_seed_ids_8X6B",
    "successful_seed_count_9E6Y","successful_seed_ids_9E6Y","independent_receptor_docking",
    "technical_failure_reason",
]


class DockingReleaseError(RuntimeError): pass


def require(condition: bool, message: str) -> None:
    if not condition: raise DockingReleaseError(message)


def now() -> str: return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""): digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str,str]]]:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size>0,f"missing_or_invalid_tsv:{path}")
    with path.open(newline="",encoding="utf-8-sig") as handle:
        reader=csv.DictReader(handle,delimiter="\t"); rows=list(reader)
        require(None not in (reader.fieldnames or []) and all(None not in row for row in rows),f"ragged_tsv:{path}")
        return list(reader.fieldnames or []),rows


def write_tsv(path: Path, rows: list[dict[str,Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,delimiter="\t",lineterminator="\n");writer.writeheader();writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n"); os.replace(temporary,path)


def replace(path: Path, replacements: Mapping[str,str]) -> None:
    text=path.read_text()
    for old,new in replacements.items():
        require(old in text or new in text,f"patch_token_missing:{path}:{old}")
        if old in text: text=text.replace(old,new)
    path.write_text(text)


def validate_source_terminal() -> None:
    files={
        "protocol_core_lock":SOURCE/"PROTOCOL_CORE_LOCK.json", "protocol_lock":SOURCE/"PROTOCOL_LOCK.json",
        "evaluator_gate":SOURCE/"config/evaluator_stability_gate.json", "aggregate":SOURCE/"scripts/aggregate_results.py",
        "run_job":SOURCE/"scripts/run_job.py", "run_controller":SOURCE/"scripts/run_controller.py",
    }
    for name,path in files.items(): require(path.is_file() and not path.is_symlink() and sha256(path)==EXPECTED_SOURCE[name],f"source_v4d_hash_mismatch:{name}")
    _,jobs=read_tsv(SOURCE/"manifests/docking_jobs.tsv"); require(len(jobs)==2022,"source_v4d_job_count_invalid")
    states=[]
    for job in jobs:
        status=SOURCE/"status/jobs"/f"{job['job_id']}.json"; require(status.is_file(),f"source_v4d_status_missing:{job['job_id']}")
        states.append(str(json.loads(status.read_text()).get("state","")).upper())
    require(all(state in SUCCESS_STATES or state=="FAILED_MAX_ATTEMPTS" for state in states),"source_v4d_not_terminal")
    require(not (SOURCE/"status/smoke_then_full.pid").is_file() or not _pid_alive(SOURCE/"status/smoke_then_full.pid"),"source_v4d_orchestrator_alive")


def _pid_alive(path: Path) -> bool:
    if not path.is_file(): return False
    try: os.kill(int(path.read_text().strip()),0); return True
    except (ValueError,ProcessLookupError): return False
    except PermissionError: return True


def locate_input_release() -> tuple[Path,dict[str,Any],list[dict[str,str]],list[dict[str,str]],list[dict[str,str]]]:
    pointer_path=INPUT_ROOT/"CURRENT_RELEASE.json"; require(pointer_path.is_file() and not pointer_path.is_symlink(),"input_pointer_missing")
    pointer=json.loads(pointer_path.read_text()); release_id=str(pointer.get("release_id","")); require(re.fullmatch(r"[0-9a-f]{64}",release_id) is not None,"input_release_id_invalid")
    release=Path(str(pointer.get("release_path",""))).resolve(); require(release==INPUT_ROOT/"releases"/release_id,"input_release_path_noncanonical")
    receipt_path=release/"full_qc_eligibility.receipt.json"; require(receipt_path.is_file() and sha256(receipt_path)==pointer.get("eligibility_receipt_sha256"),"input_receipt_pointer_binding_invalid")
    receipt=json.loads(receipt_path.read_text()); require(receipt.get("schema_version")=="phase2_v4_f96_full_qc_eligibility_receipt_v1" and receipt.get("status")=="PASS_V4_F96_FULL_QC_ELIGIBILITY_FROZEN_NO_REPLACEMENT" and receipt.get("execution_mode")=="production","eligibility_receipt_contract_invalid")
    fields,eligibility=read_tsv(release/"full_qc_eligibility.tsv"); require(len(eligibility)==96 and receipt.get("eligibility",{}).get("sha256")==sha256(release/"full_qc_eligibility.tsv"),"eligibility_tsv_binding_invalid")
    _,manifest=read_tsv(INPUT_ROOT/"prospective_holdout96_manifest.tsv")
    _,monomers=read_tsv(release/"monomer_manifest.tsv")
    require([row["candidate_id"] for row in eligibility]==[row["candidate_id"] for row in manifest],"eligibility_manifest_order_mismatch")
    hard=[row for row in eligibility if row["full_qc_hard_pass"]=="true"]
    require([row["candidate_id"] for row in monomers]==[row["candidate_id"] for row in hard],"monomer_hardpass_order_mismatch")
    by_manifest={row["candidate_id"]:row for row in manifest}
    for row in monomers:
        require(row["sequence_sha256"]==by_manifest[row["candidate_id"]]["sequence_sha256"],f"monomer_sequence_hash_mismatch:{row['candidate_id']}")
        if row["monomer_status"]=="SUCCESS":
            path=Path(row["pdb_path"]); require(path.resolve().is_relative_to(release/"monomers") and path.is_file() and not path.is_symlink() and sha256(path)==row["pdb_sha256"],f"monomer_artifact_invalid:{row['candidate_id']}")
        else: require(row["monomer_status"]=="TECHNICAL_FAILURE" and not row["pdb_path"] and bool(row["technical_failure_reason"]),f"monomer_failure_contract_invalid:{row['candidate_id']}")
    return release,receipt,manifest,eligibility,monomers


def stage() -> dict[str,Any]:
    validate_source_terminal(); release,eligibility_receipt,manifest,eligibility,monomers=locate_input_release()
    require(not ROOT.exists(),"docking_root_already_exists")
    for directory in ("config","scripts","tests"):
        shutil.copytree(SOURCE/directory,ROOT/directory)
    for directory in ("source","normalized","control_monomers"):
        shutil.copytree(SOURCE/"inputs"/directory,ROOT/"inputs"/directory)
    for name in ("calibration_controls_47.tsv",): shutil.copy2(SOURCE/"inputs"/name,ROOT/"inputs"/name)
    (ROOT/"reports").mkdir(); shutil.copy2(SOURCE/"reports/reference_normalization_summary.json",ROOT/"reports/reference_normalization_summary.json")
    for name in ("candidate_monomers","manifests","status/jobs","logs","runs","results","failed_attempts"):(ROOT/name).mkdir(parents=True,exist_ok=True)
    by_manifest={row["candidate_id"]:row for row in manifest}; success=[row for row in monomers if row["monomer_status"]=="SUCCESS"]
    candidates=[by_manifest[row["candidate_id"]] for row in success]; require(bool(candidates),"zero_dockable_hardpass_monomers")
    candidate_path=ROOT/"inputs/candidates_290.tsv"; write_tsv(candidate_path,candidates,list(candidates[0]))
    write_tsv(ROOT/"inputs/fullqc290_split_manifest.tsv",candidates,list(candidates[0]))
    write_json(ROOT/"inputs/fullqc290_split_audit.json",{"status":"PASS_V4_F96_DOCKABLE_HARDPASS_SUBSET_FROZEN_NO_REPLACEMENT","candidate_count":len(candidates),"source_eligibility_sha256":sha256(release/"full_qc_eligibility.tsv"),"monomer_failure_count":len(monomers)-len(success),"claim_boundary":CLAIM})
    monomer_rows=[]
    for row in success:
        source=Path(row["pdb_path"]); destination=ROOT/"inputs/candidate_monomers"/f"{row['candidate_id']}.pdb"; shutil.copy2(source,destination)
        monomer_rows.append({"candidate_id":row["candidate_id"],"sequence_sha256":row["sequence_sha256"],"source_remote_path":str(source),"frozen_monomer_path":str(destination.relative_to(ROOT)),"source_chain":"A","sha256":sha256(destination),"size_bytes":str(destination.stat().st_size),"atom_count":str(sum(line.startswith("ATOM  ") for line in destination.read_text().splitlines())),"residue_count":str(len(by_manifest[row["candidate_id"]]["sequence"])),"first_residue":"1","last_residue":str(len(by_manifest[row["candidate_id"]]["sequence"]))})
    write_tsv(ROOT/"inputs/candidate_monomers_manifest.tsv",monomer_rows,list(monomer_rows[0]))
    count=len(candidates); candidate_jobs=count*6; total=282+candidate_jobs; smoke=candidates[0]["candidate_id"]
    protocol_path=ROOT/"config/protocol_spec.json"; protocol=json.loads(protocol_path.read_text()); protocol.update({"protocol_id":PROTOCOL_ID,"status":"PRELOCK_VALIDATION_REQUIRED","evidence_boundary":"prospective_v4f96_fullqc_hardpass_independent_dual_receptor_computational_geometry_only"})
    protocol["candidate_panel"].update({"panel_id":"v4f96_fullqc_hardpass_no_replacement_v1","expected_count":count,"selection_algorithm":"all_full_qc_hard_pass_no_model_reselection_no_replacement","split_counts":{"PROSPECTIVE_V4_F_COMPUTATIONAL_HOLDOUT":count},"monomer_source_policy":"all_hardpass_NanoBodyBuilder2_attempted_failures_retained_as_technical"})
    protocol["docking"].update({"expected_candidate_jobs":candidate_jobs,"expected_control_jobs":282,"expected_total_jobs":total,"smoke_candidate_id":smoke}); protocol["scheduler"]["max_parallel"]=12; write_json(protocol_path,protocol)
    replace(ROOT/"scripts/build_docking_jobs.py",{"candidate panel expected 290 rows":f"candidate panel expected {count} rows","len(rows) != 290":f"len(rows) != {count}","fullqc290 panel":"V4-F96 hard-pass panel"})
    replace(ROOT/"scripts/validate_protocol.py",{"all 2022 docking jobs":f"all {total} docking jobs",'Counter({"control": 282, "candidate": 1740})':f'Counter({{"control": 282, "candidate": {candidate_jobs}}})'})
    freeze=ROOT/"scripts/freeze_protocol.py"; text=freeze.read_text().replace("len(monomers) != 290",f"len(monomers) != {count}").replace("expected 290 frozen candidate monomers",f"expected {count} frozen candidate monomers"); freeze.write_text(text)
    replace(ROOT/"tests/test_job_manifest_and_controller.py",{"range(1, 291)":f"range(1, {count+1})",'RFV1__PLDNANO_VHH_00010__A_CENTER__H1H3__B03__M00':smoke,"freezes_2022_unique_rows":f"freezes_{total}_unique_rows","len(rows), 2022":f"len(rows), {total}",'len({row["job_id"] for row in rows}), 2022':f'len({{row["job_id"] for row in rows}}), {total}','row["entity_type"] == "candidate" for row in rows[282:]), 1740':f'row["entity_type"] == "candidate" for row in rows[282:]), {candidate_jobs}'})
    replace(ROOT/"tests/test_protocol_freeze.py",{'"candidate_panel": {"expected_count": 290}':f'"candidate_panel": {{"expected_count": {count}}}'})
    stability=ROOT/"tests/test_stability_gate.py"; stability.write_text(stability.read_text().replace("2022",str(total)))
    summary={"status":"PASS_V4_F96_DOCKING_CANDIDATES_AND_MONOMERS_STAGED","hard_pass_count":len(monomers),"dockable_count":count,"monomer_technical_failure_count":len(monomers)-count,"expected_candidate_jobs":candidate_jobs,"expected_control_jobs":282,"expected_total_jobs":total,"eligibility_sha256":sha256(release/"full_qc_eligibility.tsv"),"input_release_id":release.name,"claim_boundary":CLAIM}
    write_json(ROOT/"reports/v4f96_candidate_freeze_summary.json",summary)
    # Keep the V4-D frozen file list shape while binding the new summary.
    fp=freeze.read_text().replace('"reports/fullqc290_candidate_freeze_summary.json",','"reports/v4f96_candidate_freeze_summary.json",'); freeze.write_text(fp)
    env={"PATH":f"{PYTHON.parent}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","PVRIG_PROJECT_ROOT":str(ROOT),"PYTHONOPTIMIZE":"0"}
    commands=[
        [str(PYTHON),"scripts/freeze_protocol.py","--phase","core"],
        [str(PYTHON),"scripts/build_docking_jobs.py"],
        [str(PYTHON),"-m","unittest","discover","-s","tests","-v"],
        [str(PYTHON),"scripts/validate_protocol.py","--expected-total-jobs",str(total)],
        [str(PYTHON),"scripts/freeze_protocol.py","--phase","final"],
    ]
    for command in commands:
        completed=subprocess.run(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (ROOT/"logs/staging.log").open("a").write("$ "+" ".join(command)+"\n"+completed.stdout+"\n")
        require(completed.returncode==0,f"staging_command_failed:{command[1:]}:rc={completed.returncode}")
    summary["protocol_core_lock_sha256"]=sha256(ROOT/"PROTOCOL_CORE_LOCK.json");summary["protocol_lock_sha256"]=sha256(ROOT/"PROTOCOL_LOCK.json");summary["job_manifest_sha256"]=sha256(ROOT/"manifests/docking_jobs.tsv");write_json(ROOT/"status/STAGED.json",summary)
    return summary


def as_float(value:Any,field:str)->float:
    try: output=float(value)
    except (TypeError,ValueError) as error: raise DockingReleaseError(f"invalid_float:{field}") from error
    require(math.isfinite(output),f"nonfinite:{field}"); return output


def soft(value:float,threshold:float)->float:return value/(value+threshold)


def utility(score:Mapping[str,Any])->float:
    hotspot=as_float(score["hotspot_overlap"]["full"]["count"],"hotspot");holdout=as_float(score["hotspot_overlap"]["holdout"]["count"],"holdout")
    occ=score["vhh_pvrl2_occlusion"];total=as_float(occ["residue_pair_count"],"total");cdr3=as_float(occ["by_vhh_region_pair_count"]["cdr3"],"cdr3");fraction=as_float(occ["cdr3_fraction"],"fraction")
    rmsd=as_float(score["overlay"]["t_ca_rmsd_a"],"rmsd");require(rmsd<=1.0,f"native_overlay_rmsd_above_1A:{rmsd}")
    clashes=as_float(score["clashes_2p5a"]["vhh_pvrig"]["residue_pair_count"],"clashes")
    base=.15*min(max(hotspot/23,0),1)+.25*min(max(holdout/11,0),1)+.25*soft(total,500)+.20*soft(cdr3,100)+.15*soft(fraction,.15)
    return base/(1+clashes/5)


def summarize_job(result:Mapping[str,Any], conformation:str)->float:
    complete=[]
    for pose in result.get("pose_scores",[]):
        scores={str(item["reference_id"]).lower():item for item in pose.get("scores",[])}
        if set(scores)==set(CONFORMATIONS): complete.append((float((pose.get("haddock_io") or {})["score"]),str(pose.get("pose","")),scores))
    require(len(complete)>=4,"fewer_than_4_complete_top8_models");complete.sort(key=lambda item:(item[0],item[1]));require(len(complete)<=8,"more_than_fixed_top8_models")
    raw=[1/math.log2(rank+1) for rank in range(1,len(complete)+1)];weights=[value/sum(raw) for value in raw]
    score=sum(weight*utility(item[2][conformation]) for weight,item in zip(weights,complete)); reliability=.5+.5*min(len(complete)/8,1)
    # V4-D agreement factors are recomputed from the same complete 2x2 models.
    def cls(item:Mapping[str,Any])->str:
        h=float(item["hotspot_overlap"]["full"]["count"]);o=float(item["vhh_pvrl2_occlusion"]["residue_pair_count"]);c=float(item["vhh_pvrl2_occlusion"]["by_vhh_region_pair_count"]["cdr3"]);f=float(item["vhh_pvrl2_occlusion"]["cdr3_fraction"])
        if h>=14 and o>=500 and c>=100 and f>=.15:return "A"
        if h>=14 and o<50:return "C"
        if h>=10 and o>=100 and c>=20 and f>=.10:return "B"
        return "E"
    other="9e6y" if conformation=="8x6b" else "8x6b"; pairs=[(cls(item[2][conformation]),cls(item[2][other])) for item in complete]
    support=[(a in {"A","B"})==(b in {"A","B"}) for a,b in pairs];labels=["STRICT_A" if a==b=="A" else "SUPPORTED_AB" if a in {"A","B"} and b in {"A","B"} else "OTHER" for a,b in pairs]
    agreement=sum(support)/len(support); consensus=max(labels.count(label) for label in set(labels))/len(labels)
    return score*reliability*(.5+.25*agreement+.25*consensus)


def publish_labels() -> dict[str,Any]:
    release,eligibility_receipt,manifest,eligibility,monomers=locate_input_release(); by_manifest={row["candidate_id"]:row for row in manifest}; by_monomer={row["candidate_id"]:row for row in monomers}
    _,jobs=read_tsv(ROOT/"manifests/docking_jobs.tsv"); candidate_jobs=defaultdict(lambda:defaultdict(list))
    terminal_jobs=0
    for job in jobs:
        result_path=ROOT/"results"/job["job_id"]/"job_result.json"; require(result_path.is_file(),f"job_result_missing:{job['job_id']}"); terminal_jobs+=1
        if job["entity_type"]=="candidate":candidate_jobs[job["entity_id"]][job["conformation"]].append((job,result_path))
    rows=[]
    for eligible in [row for row in eligibility if row["full_qc_hard_pass"]=="true"]:
        cid=eligible["candidate_id"]; counts={};ids={};scores={};reason=""
        monomer=by_monomer[cid]
        if monomer["monomer_status"]!="SUCCESS": reason=monomer["technical_failure_reason"]
        else:
            for conformation in CONFORMATIONS:
                successful=[]
                for job,path in candidate_jobs[cid][conformation]:
                    result=json.loads(path.read_text()); state=str(result.get("state","")).upper()
                    if state in SUCCESS_STATES:
                        successful.append((int(job["seed"]),summarize_job(result,conformation)))
                successful.sort();counts[conformation]=len(successful);ids[conformation]=[seed for seed,_ in successful]
                if len(successful)>=2:scores[conformation]=median([score for _,score in successful])
                else:reason=(reason+";" if reason else "")+f"FEWER_THAN_2_SUCCESSFUL_SEEDS_{conformation.upper()}"
        for conformation in CONFORMATIONS: counts.setdefault(conformation,0);ids.setdefault(conformation,[])
        analyzable=not reason and set(scores)==set(CONFORMATIONS)
        source=by_manifest[cid]
        rows.append({"candidate_id":cid,"sequence_sha256":source["sequence_sha256"],"parent_framework_cluster":source["parent_framework_cluster"],"model_split":source["model_split"],"docking_status":"PASS_COMPLETE_DUAL_DOCKING" if analyzable else "TECHNICAL_FAILURE","R_dual_min":f"{min(scores.values()):.9f}" if analyzable else "","successful_seed_count_8X6B":str(counts["8x6b"]),"successful_seed_ids_8X6B":",".join(map(str,ids["8x6b"])),"successful_seed_count_9E6Y":str(counts["9e6y"]),"successful_seed_ids_9E6Y":",".join(map(str,ids["9e6y"])),"independent_receptor_docking":"true","technical_failure_reason":reason})
    labels=ROOT/"release/dual_docking_labels.tsv";write_tsv(labels,rows,LABEL_FIELDS)
    payload={"schema_version":"phase2_v4_f96_remote_dual_docking_label_release_v1_1","status":"PASS_REMOTE_V4_F96_DUAL_DOCKING_LABELS_READY_FOR_CANONICAL_DELIVERY","execution_mode":"production","manifest_sha256":"3f3c504844756703acecf586b2b218f2e2855c3a108ee22656c8f08e7f57e334","eligibility_sha256":sha256(release/"full_qc_eligibility.tsv"),"labels":{"path":str(labels),"sha256":sha256(labels)},"eligible_hard_pass_count":len(rows),"label_row_count":len(rows),"analyzable_count":sum(row["docking_status"]=="PASS_COMPLETE_DUAL_DOCKING" for row in rows),"technical_failure_count":sum(row["docking_status"]=="TECHNICAL_FAILURE" for row in rows),"expected_receptor_seed_job_count":len(rows)*6,"terminal_receptor_seed_job_count":len(rows)*6,"all_jobs_terminal":True,"receptors":["8X6B","9E6Y"],"seeds":list(SEEDS),"protocol_lock_sha256":sha256(ROOT/"PROTOCOL_LOCK.json"),"job_manifest_sha256":sha256(ROOT/"manifests/docking_jobs.tsv"),"claim_boundary":CLAIM}
    write_json(ROOT/"release/remote_dual_docking_labels.receipt.json",payload);return payload


def run() -> dict[str,Any]:
    staged=stage(); total=staged["expected_total_jobs"]; env={"PVRIG_PROJECT_ROOT":str(ROOT),"HADDOCK3":str(HADDOCK3),"PATH":f"{PYTHON.parent}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","PVRIG_LOCAL_SCRATCH_ROOT":str(SCRATCH),"PVRIG_MAX_PARALLEL":"12","PYTHONOPTIMIZE":"0"}
    SCRATCH.mkdir(parents=True,exist_ok=True);require("nfs" not in subprocess.check_output(["stat","-f","-c","%T",str(SCRATCH)],text=True).lower(),"scratch_on_nfs")
    completed=subprocess.run([str(PYTHON),"scripts/orchestrate_smoke_then_full.py"],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True);(ROOT/"logs/smoke_then_full.log").write_text(completed.stdout);require(completed.returncode==0,f"orchestrator_failed:{completed.returncode}")
    # The orchestrator invokes aggregate_results; require all statuses terminal independently.
    _,jobs=read_tsv(ROOT/"manifests/docking_jobs.tsv");require(len(jobs)==total,"job_manifest_total_drift")
    require(all((ROOT/"results"/row["job_id"]/"job_result.json").is_file() for row in jobs),"not_all_job_results_terminal")
    return publish_labels()


def main()->int:
    if "--smoke-test" in sys.argv:
        print(json.dumps({"status":"PASS_NODE23_V4_F96_DUAL_DOCKING_RUNNER_SMOKE","source":str(SOURCE),"input_root":str(INPUT_ROOT),"output_root":str(ROOT),"seeds":list(SEEDS),"receptors":["8X6B","9E6Y"],"label_paths_read_before_run":0},sort_keys=True));return 0
    print(json.dumps(run(),indent=2,sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
