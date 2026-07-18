#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,datetime
from pathlib import Path

def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def count_gzip_rows(path:Path)->int:
    with gzip.open(path,'rt',newline='') as h:return sum(1 for _ in csv.DictReader(h,delimiter='\t'))
def main(output:Path,status_dir:Path)->dict:
    receipt_path=output/'RUN_RECEIPT.json'; audit_path=output/'v4h_stage1_contact_extraction_audit.json'
    receipt=json.loads(receipt_path.read_text());audit=json.loads(audit_path.read_text())
    if receipt['status']!='COMPLETE_V4H_STAGE1_CONTACT_TEACHER_EXTRACTION':raise ValueError('receipt_status')
    expected={'v4h_stage1_candidate_contact_teacher.tsv.gz':1320,'v4h_stage1_receptor_contact_teacher.tsv.gz':2640,'v4h_stage1_residue_pair_contact_teacher.tsv.gz':460472}
    counts={}
    for name,rows in expected.items():
        path=output/name
        if sha(path)!=receipt['output_hashes'][name]:raise ValueError('output_hash:'+name)
        counts[name]=count_gzip_rows(path)
        if counts[name]!=rows:raise ValueError('output_rows:'+name)
    if audit['read_only_boundary']['source_mutation_operations']!=0:raise ValueError('source_mutation')
    if audit['read_only_boundary']['technical_incomplete_pose_files_opened']!=0:raise ValueError('incomplete_pose_open')
    if receipt['technical_incomplete_candidate_rows']!=39 or receipt['valid_candidate_rows']!=1281:raise ValueError('candidate_states')
    payload={'schema_version':'pvrig_v6_contact_extraction_recovery_terminal_v1_1','status':'PASS_CONTACT_EXTRACTION_V1_1_RECOVERED_TERMINAL','reason':'Extraction succeeded; original launcher post-validator expected the wrong literal status and failed after immutable outputs were complete.','receipt_sha256':sha(receipt_path),'audit_sha256':sha(audit_path),'verified_rows':counts,'source_mutation_operations':0,'technical_incomplete_pose_files_opened':0,'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    status_dir.mkdir(parents=True,exist_ok=True);out=status_dir/'extraction_v1_1_recovery_terminal.json';out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n');return payload
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--status-dir',type=Path,required=True);a=p.parse_args();print(json.dumps(main(a.output,a.status_dir),indent=2,sort_keys=True))
