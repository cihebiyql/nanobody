from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(name):
 p=ROOT/"src"/name; s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
BUILD=load("build_top30k_c2_shards_v1.py");MERGE=load("merge_top30k_c2_features_v1.py");SELECT=load("select_top7500_c2_refined_v1.py")
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(path,rows):
 with path.open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows)

class C2Top30KTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
 def tearDown(self):self.t.cleanup()
 def fixture(self,n=16):
  prelim=[];struct=[]
  for i in range(n):
   c=f"C{i:03d}"; seqhash=hashlib.sha256(c.encode()).hexdigest();pdb=self.root/f"{c}.pdb";pdb.write_text(f"ATOM      1  CA  ALA A   1       {i:6.3f}   0.000   0.000  1.00 20.00           C\n")
   prelim.append({"candidate_id":c,"sequence":"A"*100,"sequence_sha256":seqhash,"parent_framework_cluster":f"P{i%3}","four_model_ensemble_utility":str(1-i/n),"l1_utility":str(1-i/n),"b_utility":str(.5),"s0_utility":str(.4),"m2_utility":str(.3),"tnp_review_tier":"CLEAR","cdr3":"AAA","target_patch_id":"A","design_method":"X"})
   struct.append({"candidate_id":c,"sequence_sha256":seqhash,"parent_framework_cluster":f"P{i%3}","monomer_path":str(pdb),"monomer_sha256":sha(pdb),"cdr1_range":"1-2","cdr2_range":"3-4","cdr3_range":"5-6"})
  stage=self.root/"stage.tsv";structure=self.root/"structure.tsv";write(stage,prelim);write(structure,struct)
  pr=self.root/"prelim.json";pr.write_text(json.dumps({"status":"PASS_TOP150K_FOUR_MODEL_PRELIMINARY_SELECTION","outputs":{"STAGE1_TOP30000_FOR_C2.tsv":sha(stage)}}))
  sr=self.root/"staging.json";sr.write_text(json.dumps({"status":"PASS_TOP150K_LABEL_FREE_NBB2_ARCHIVE_STAGING","outputs":{"top150k_m2_structure_manifest_v1.tsv":sha(structure)}}))
  return prelim,stage,structure,pr,sr
 def test_build_and_merge_hash_closed_32d(self):
  prelim,stage,structure,pr,sr=self.fixture();planroot=self.root/"plan"
  BUILD.build(argparse.Namespace(stage1=stage,preliminary_receipt=pr,structure_manifest=structure,staging_receipt=sr,output_dir=planroot,expected_rows=16,shards=16))
  plan=json.loads((planroot/"SHARD_PLAN.json").read_text());self.assertEqual(plan["counts"]["rows"],16)
  receptor=["pose_count","acceptable_count","acceptable_fraction","best_composite","top20_composite_mean","top20_composite_std","top20_composite_iqr","top20_score_entropy","best_shape","best_hotspot","best_charge","best_clash_fraction","best_cdr_contact_fraction","best_cdr3_orientation"]
  dual=["common_acceptable_count","common_acceptable_fraction","acceptable_jaccard","best_min_composite","top20_min_composite_mean","top20_min_composite_std","best_receptor_gap","pose_score_correlation"]
  raw=[f"{r}__{x}" for r in ("8x6b","9e6y") for x in receptor]+[f"dual__{x}" for x in dual]
  targets={}
  for role in ("target_npz","target_pdb8","target_pdb9"):
   p=self.root/role;p.write_bytes(role.encode());targets[role]=(p,sha(p))
  shardroot=self.root/"raw"
  for shard in plan["shards"]:
   _,mrows=BUILD.read_tsv(planroot/shard["relative_path"],"m");outdir=shardroot/shard["shard_id"];outdir.mkdir(parents=True)
   rows=[{"candidate_id":r["candidate_id"],"monomer_sha256":r["monomer_sha256"],"feature_schema":MERGE.RAW_SCHEMA,**{name:"0.5" for name in raw}} for r in mrows]
   table=outdir/"coarse_pose_features_36d.tsv";write(table,rows)
   receipt={"schema_version":MERGE.RAW_RECEIPT_SCHEMA,"status":MERGE.RAW_RECEIPT_STATUS,"candidate_count":len(rows),"feature_count":36,"pose_count_per_receptor":300,"all_features_finite":True,"sealed_boundary":{"candidate_docking_pose_files_opened":0,"teacher_label_files_opened":0,"v4_f_files_opened":0},"inputs":{"candidate_manifest":{"path":str((planroot/shard["relative_path"]).resolve()),"sha256":shard["sha256"]},**{role:{"path":str(p.resolve()),"sha256":h} for role,(p,h) in targets.items()}},"outputs":{str(table.resolve()):sha(table)}}
   (outdir/"FEATURE_RECEIPT.json").write_text(json.dumps(receipt))
  out=self.root/"merged";MERGE.merge(argparse.Namespace(plan=planroot/"SHARD_PLAN.json",expected_plan_sha256=sha(planroot/"SHARD_PLAN.json"),shard_output_root=shardroot,target_npz=targets["target_npz"][0],target_npz_sha256=targets["target_npz"][1],target_pdb8=targets["target_pdb8"][0],target_pdb8_sha256=targets["target_pdb8"][1],target_pdb9=targets["target_pdb9"][0],target_pdb9_sha256=targets["target_pdb9"][1],output_dir=out,expected_rows=16))
  with (out/"TOP30000_C2_32D.tsv").open() as f:r=csv.DictReader(f,delimiter="\t");self.assertEqual(len(r.fieldnames)-3,32);self.assertEqual(len(list(r)),16)
 def test_truth_column_rejected(self):
  prelim,stage,structure,pr,sr=self.fixture();prelim[0]["truth_Rdual"]="1";write(stage,prelim);pr.write_text(json.dumps({"status":"PASS_TOP150K_FOUR_MODEL_PRELIMINARY_SELECTION","outputs":{"STAGE1_TOP30000_FOR_C2.tsv":sha(stage)}}))
  with self.assertRaisesRegex(BUILD.ProjectionError,"forbidden_preliminary_field"):
   BUILD.build(argparse.Namespace(stage1=stage,preliminary_receipt=pr,structure_manifest=structure,staging_receipt=sr,output_dir=self.root/"out",expected_rows=16,shards=16))
 def test_final_selector_exact_channels(self):
  rows,stage,*_=self.fixture(16);c2=[]
  for i,r in enumerate(rows):c2.append({"candidate_id":r["candidate_id"],"sequence_sha256":r["sequence_sha256"],SELECT.ALL:str(1-i/16),SELECT.M2C2:str(1-i/32)})
  c2p=self.root/"c2.tsv";write(c2p,c2);out=self.root/"selected"
  result=SELECT.run(argparse.Namespace(stage1=stage,c2=c2p,output_dir=out,stage1_rows=16,final_rows=8,exploitation=5,rescue=2,diversity=1))
  self.assertEqual(result["rows"],8);self.assertEqual(result["channels"],{"C2_REFINED_CONSENSUS":5,"TARGET_MODEL_C2_SUPPORTED_RESCUE":2,"PARENT_BALANCED_C2_DIVERSITY":1});self.assertTrue((out/"TOP7500_C2_REFINED.fasta").is_file())

if __name__=="__main__":unittest.main()
