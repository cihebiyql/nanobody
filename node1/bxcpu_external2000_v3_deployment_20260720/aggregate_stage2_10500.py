#!/usr/bin/env python3
import argparse,csv,datetime,hashlib,json,os,pathlib,collections
p=argparse.ArgumentParser();p.add_argument('--publish-root',required=True);p.add_argument('--manifest',required=True);a=p.parse_args()
root=pathlib.Path(a.publish_root); manifest=pathlib.Path(a.manifest)
with manifest.open() as f: rows=list(csv.DictReader(f,delimiter='\t'))
assert len(rows)==10500 and len({r['job_id'] for r in rows})==10500
outrows=[]; counts=collections.Counter(); errors=[]
for row in rows:
 jid=row['job_id']; sp=root/'status/jobs'/(jid+'.json'); rp=root/'results'/jid/'job_result.json'
 if not sp.exists(): state='ABSENT'; result={}
 else:
  try:
   status_payload=json.load(open(sp)); state=status_payload.get('status','MISSING')
   if state=='FAILED' and int(status_payload.get('attempts',0) or 0)>=2:
    state='FAILED_MAX_ATTEMPTS'
  except Exception as e: state='BAD_STATUS';errors.append({'job_id':jid,'error':repr(e)});result={}
 if rp.exists():
  try: result=json.load(open(rp))
  except Exception as e: errors.append({'job_id':jid,'error':repr(e)});result={}
 counts[state]+=1
 if state=='SUCCESS':
  if result.get('state')!='SUCCESS' or result.get('job_hash')!=row['job_hash'] or result.get('protocol_core_sha256')!=row['protocol_core_sha256']:
   errors.append({'job_id':jid,'error':'success result identity/protocol mismatch'})
 outrows.append({'job_id':jid,'entity_id':row['entity_id'],'conformation':row['conformation'],'seed':row['seed'],'status':state,'selected_model_count':result.get('selected_model_count',''),'job_hash':row['job_hash'],'protocol_core_sha256':row['protocol_core_sha256']})
reports=root/'reports';reports.mkdir(parents=True,exist_ok=True)
tsv=reports/'stage2_10500_job_results.tsv';tmp=tsv.with_suffix('.tsv.tmp')
with tmp.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=outrows[0].keys(),delimiter='\t',lineterminator='\n');w.writeheader();w.writerows(outrows)
os.replace(tmp,tsv)
terminal=counts.get('SUCCESS',0)+counts.get('FAILED_MAX_ATTEMPTS',0)
receipt={'schema_version':'pvrig_v29_bxcpu_stage2_aggregation_v1','state':'COMPLETE' if terminal==10500 and not errors else 'INCOMPLETE_OR_INVALID','created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'expected_jobs':10500,'counts':dict(counts),'terminal_jobs':terminal,'errors':errors,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'job_results_tsv':'reports/stage2_10500_job_results.tsv','job_results_sha256':hashlib.sha256(tsv.read_bytes()).hexdigest()}
out=reports/'STAGE2_10500_AGGREGATION.json';t=out.with_suffix('.json.tmp');t.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');os.replace(t,out)
print(json.dumps({k:v for k,v in receipt.items() if k!='errors'},indent=2,sort_keys=True))
raise SystemExit(0 if receipt['state']=='COMPLETE' else 1)
