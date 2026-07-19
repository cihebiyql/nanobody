#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime-root',type=Path,required=True);p.add_argument('--collector',type=Path,required=True);p.add_argument('--python',required=True);a=p.parse_args()
 expected=[
  ('F0_SHARED_GATED_NO_RANK',43),('F0_SHARED_GATED_NO_RANK',97),('F0_SHARED_GATED_NO_RANK',193),
  ('F1_SHARED_GATED_V4D_EXACT_MIN_RANK',43),('F1_SHARED_GATED_V4D_EXACT_MIN_RANK',97),('F1_SHARED_GATED_V4D_EXACT_MIN_RANK',193),
  ('B_SCALAR_ATTENTION_ONLY',43),('E_STRICT_DETACHED_DYNAMICS_CONTROL',43)]
 while True:
  ready=[]
  for v,s in expected:
   q=a.runtime_root/'gpu_jobs'/v/f'seed_{s}'/'RESULT.json'
   if q.is_file():
    try: ready.append(json.loads(q.read_text()).get('status','').startswith('PASS'))
    except Exception: ready.append(False)
   else: ready.append(False)
  if all(ready): break
  terminal=a.runtime_root/'TERMINAL.json'
  if terminal.is_file():
   t=json.loads(terminal.read_text())
   if t.get('status')=='FAIL' and not all(ready): raise RuntimeError('gpu_jobs_failed_before_recovery')
  time.sleep(10)
 out=a.runtime_root/'collector_recovery_v1_2_1'
 cmd=[a.python,str(a.collector),'--job-id','outer0.inner0.collect_open_inner_metrics','--runtime-root',str(a.runtime_root),'--training-tsv','/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718/inputs/split_training/outer_0_inner_0.tsv','--expected-training-tsv-sha256','5abacbe69e85a5f6e3a13d6af23ae7e2b2903d59554dbce46e14ea165acc4d21','--split-manifest','/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_1_20260718/plan/trainer_splits/outer_0_inner_0.json','--expected-split-manifest-sha256','11b3f0f394fa3057b3e3f7fec4d91ecf677f2a3546fab223d727bf9f707d219d','--output-dir',str(out)]
 return subprocess.run(cmd,check=False).returncode
if __name__=='__main__': raise SystemExit(main())
