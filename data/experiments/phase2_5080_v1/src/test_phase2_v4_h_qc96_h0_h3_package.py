#!/usr/bin/env python3
from __future__ import annotations
import json,os,sys,tempfile,time,unittest
from collections import Counter
from pathlib import Path
from unittest import mock

SRC=Path(__file__).resolve().parent
if str(SRC) not in sys.path:sys.path.insert(0,str(SRC))
import build_phase2_v4_h_qc96_h0_h3_package as b
import run_phase2_v4_h_qc96_generation_node1 as g
import run_phase2_v4_h_qc96_qc_node1 as q

class V4HTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.parents,cls.audit=b.derive_queue();cls.tasks=b.build_tasks(cls.parents)

 def test_01_exact_parent_queue(self):
  self.assertEqual(len(self.parents),12);self.assertEqual(tuple(r['parent_framework_cluster'] for r in self.parents),b.EXACT_QUEUE);self.assertEqual(self.audit['eligible_parent_count'],67)

 def test_02_anarci_is_sequence_authority(self):
  self.assertEqual(self.audit['source_vs_anarci_cdr_mismatch_counts']['source_cdr3_mismatch'],10)
  self.assertEqual(self.audit['source_vs_anarci_cdr_mismatch_counts']['source_cdr2_mismatch'],1)
  for p in self.parents:self.assertIn(p['cdr1'],p['sequence']);self.assertIn(p['cdr2'],p['sequence']);self.assertIn(p['cdr3'],p['sequence'])

 def test_03_generation_shape(self):
  self.assertEqual(len(self.tasks),72);self.assertEqual(sum(int(r['expected_raw_records']) for r in self.tasks),2592)
  self.assertEqual(Counter((r['parent_framework_cluster'],r['patch_id'],r['design_mode']) for r in self.tasks).most_common(1)[0][1],1)

 def test_04_generator_contract(self):
  self.assertEqual({r['target_backbones'] for r in self.tasks},{12});self.assertEqual({r['sequences_per_backbone'] for r in self.tasks},{3})
  self.assertEqual({r['selected_exact_unique_target'] for r in self.tasks},{20});self.assertEqual({r['proteinmpnn_deterministic_contract'] for r in self.tasks},{'bound_script_-deterministic_hardcodes_seed42'})

 def test_05_exclusion_manifest_sources(self):
  rows=b.exclusions();self.assertGreater(len(rows),7000);self.assertEqual(len(rows),len({r['sequence_sha256'] for r in rows}))
  roles=';'.join(r['exclusion_sources'] for r in rows);self.assertIn('LEGACY7087',roles);self.assertIn('RFANTIBODY1000',roles);self.assertIn('CALIBRATION_POSITIVE_EXCLUSION',roles)

 def test_06_resource_contract_exact(self):
  p=b.package_config()['resource_policy'];self.assertEqual(p['gpu_ids'],[0,1,2,3]);self.assertEqual(p['cpu_sets'],['0-7','8-15','16-23','24-31'])
  cores=set()
  for spec in p['cpu_sets']:
   lo,hi=map(int,spec.split('-'));self.assertEqual(hi-lo+1,8);self.assertFalse(cores&set(range(lo,hi+1)));cores.update(range(lo,hi+1))
  self.assertEqual(cores,set(range(32)))

 def test_07_prereg_semantics(self):
  p=b.prereg(self.parents,self.audit,self.tasks,b.exclusions());self.assertEqual(p['generation_contract']['raw_records'],2592);self.assertEqual(p['generation_contract']['selected_exact_unique_total'],1440)
  self.assertEqual(p['qc_contract']['tnp_policy'],'DEFERRED_THREE_STATE_NA_NO_IMPUTATION; numeric/flags blank');self.assertIn('descriptive',p['qc_contract']['sapiens_policy'])
  self.assertTrue(all(v==0 for v in p['label_path_access'].values()))

 def _candidate(self,parent,mode='H3'):
  seq=list(parent['sequence']);i=int(parent['h3_start_1based'])-1;seq[i]='A' if seq[i]!='A' else 'G'
  if mode=='H1H3':
   j=int(parent['h1_start_1based'])-1;seq[j]='A' if seq[j]!='A' else 'G'
  return ''.join(seq)

 def test_08_framework_valid_candidate(self):
  p=self.parents[0];result=g.validate_candidate_sequence(self._candidate(p),p,'H3');self.assertEqual(result['cdr2'],p['cdr2']);self.assertNotEqual(result['cdr3'],p['cdr3'])

 def test_09_framework_mutations_fail_closed(self):
  p=self.parents[0]
  for index,mode in [(0,'H3'),(int(p['h2_start_1based'])-1,'H3'),(int(p['h1_start_1based'])-1,'H3'),(len(p['sequence'])-1,'H3')]:
   seq=list(self._candidate(p,mode));seq[index]='A' if seq[index]!='A' else 'G'
   with self.assertRaises(RuntimeError):g.validate_candidate_sequence(''.join(seq),p,mode)

 def test_10_exact_unique_selection_and_exclusion(self):
  rows=[]
  for i in range(25):rows.append({'raw_candidate_id':f'RAWV4H__x{i}','sequence_sha256':f'{i:064x}','parent_framework_cluster':'C','target_patch_id':'A','design_mode':'H3'})
  selected=g.select_exact_unique(rows,target=20,seed='s',excluded_sequence_hashes={f'{i:064x}' for i in range(3)})
  self.assertEqual(len(selected),20);self.assertFalse({r['sequence_sha256'] for r in selected}&{f'{i:064x}' for i in range(3)})
  with self.assertRaises(RuntimeError):g.select_exact_unique(rows[:19],target=20,seed='s')

 def test_11_hash_closed_reuse_detects_mutation(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'x').write_text('a');mapping=g.build_hash_map(root);g.verify_hash_map(root,mapping);(root/'x').write_text('b')
   with self.assertRaises(RuntimeError):g.verify_hash_map(root,mapping)

 def test_12_symlink_output_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'a').write_text('x');(root/'link').symlink_to(root/'a')
   with self.assertRaises(RuntimeError):g.build_hash_map(root)

 def _h4_fixture(self,parent_count=4,per=4):
  candidates=[];full={};idx=0
  for pr in range(1,parent_count+1):
   parent=f'C{pr:04d}'
   for patch in ('A_CENTER','B_LOWER','C_CROSS'):
    for mode in ('H3','H1H3'):
     for _ in range(per):
      cid=f'c{idx}';idx+=1;candidates.append({'candidate_id':cid,'sequence_sha256':f'{idx:064x}','sequence':'A','parent_id':f'p{pr}','parent_framework_cluster':parent,'parent_queue_rank':str(pr),'target_patch_id':patch,'design_mode':mode,'cdr1_after':'A','cdr2_after':'A','cdr3_after':'A','cdr3_length':'1'});full[cid]={'candidate_id':cid,'hard_fail':'false'}
  return candidates,full

 def test_13_h4_exact_4x6x4(self):
  candidates,full=self._h4_fixture();selected,capacity=q.h4_select(candidates,full,seed='h4');self.assertEqual(len(selected),96);self.assertEqual(len(capacity),4);self.assertEqual(set(Counter(r['selection_stratum'] for r in selected).values()),{4})

 def test_14_h4_insufficient_parent_fail(self):
  candidates,full=self._h4_fixture(parent_count=3)
  with self.assertRaisesRegex(RuntimeError,'INSUFFICIENT'):q.h4_select(candidates,full,seed='h4')

 def test_15_tnp_is_blank_na(self):
  candidates,full=self._h4_fixture();selected,_=q.h4_select(candidates,full,seed='h4');self.assertEqual({r['tnp_supervision_state'] for r in selected},{'NOT_RUN_DEFERRED_NA'});self.assertEqual({r['tnp_score'] for r in selected},{''})

 def test_16_command_timeout_kills_group(self):
  rt=object.__new__(g.Runtime);rt.config={'command_timeouts_seconds':{'test':1}}
  rt.clean_env=lambda gpu,cpu_threads=8:{'PATH':'/usr/bin:/bin','HOME':'/tmp','LANG':'C.UTF-8'}
  with tempfile.TemporaryDirectory() as td:
   start=time.monotonic()
   with self.assertRaisesRegex(RuntimeError,'command_timeout'):rt.command(['bash','-c','sleep 20'],Path(td)/'hang.log',0,'0','test')
   self.assertLess(time.monotonic()-start,5)

 def test_17_static_package_build(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'pkg';result=b.build(out,False);self.assertEqual(result['status'],'PASS_H0_STATIC_PACKAGE_BUILT_NOT_FROZEN');self.assertEqual(len(b.read(out/'manifests/generation_tasks.tsv')),72);self.assertFalse((out/'IMPLEMENTATION_FREEZE.json').exists())

 def test_18_freeze_requires_real_test_log(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'pkg';b.build(out,False);bad=Path(td)/'bad.log';bad.write_text('OK\n')
   with self.assertRaises(RuntimeError):b.freeze(out,bad)

 def test_19_runner_source_has_cartesian_and_zero_work_gates(self):
  text=(SRC/'run_phase2_v4_h_qc96_generation_node1.py').read_text();self.assertIn('task_cartesian_b00_b11_m00_m02_failed',text);self.assertIn('zero_work_preflight_found_scientific_output',text);self.assertIn('PYTHONOPTIMIZE',text)

 def test_20_canonical_h4_output_names(self):
  text=(SRC/'run_phase2_v4_h_qc96_qc_node1.py').read_text();self.assertIn('qc96_manifest_v1.tsv',text);self.assertIn('qc96_audit_v1.json',text);self.assertIn('qc96_receipt_v1.json',text)

if __name__=='__main__':unittest.main(verbosity=2)
