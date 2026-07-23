from __future__ import annotations
import argparse,csv,hashlib,importlib.util,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("selector",ROOT/"src/select_top150k_four_model_v1.py")
MOD=importlib.util.module_from_spec(SPEC); assert SPEC.loader; SPEC.loader.exec_module(MOD)

def write(path,fields,rows):
    with path.open("w",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields,delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows)

class SelectorTests(unittest.TestCase):
    def test_exact_quotas_and_truth_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); n=20
            ids=[f"c{i:02d}" for i in range(n)]
            stage=[]; mm=[]; l1=[]; b=[]
            for i,c in enumerate(ids):
                seq="ACDEFGHIKLMNPQRSTVWY"+"A"*i; sha=hashlib.sha256(seq.encode()).hexdigest(); u=1-i/(n-1)
                stage.append({"candidate_id":c,"sequence":seq,"sequence_sha256":sha,"parent_framework_cluster":f"p{i%3}","cdr3":"HIK","target_patch_id":"t","design_method":"g","tnp_review_tier":"CLEAR"})
                mm.append({"candidate_id":c,"sequence_sha256":sha,"parent_framework_cluster":f"p{i%3}",MOD.S0:u,MOD.M2:u})
                common={"candidate_id":c,"sequence_sha256":sha,"ensemble_conservative_top_fraction":1-u,"ensemble_R_dual_std":0.01,"ensemble_receptor_gap_abs":0.02}
                l1.append(common); b.append(dict(common))
            paths={}
            for name,rows in (("stage0",stage),("mm",mm),("l1",l1),("b",b)):
                p=root/f"{name}.tsv";write(p,list(rows[0]),rows);paths[name]=p
            args=argparse.Namespace(stage0=paths["stage0"],multimodal=paths["mm"],l1=paths["l1"],b=paths["b"],expected_rows=n,stage1_rows=10,final_rows=5,exploitation_rows=3,rescue_rows=1,diversity_rows=1,output_dir=root/"out")
            receipt=MOD.run(args);self.assertEqual(receipt["final_rows"],5);self.assertEqual(receipt["channels"],{"CONSENSUS_EXPLOITATION":3,"TARGET_MODEL_RESCUE":1,"PARENT_BALANCED_DIVERSITY":1})
            bad=root/"bad.tsv";write(bad,list(l1[0])+["docking_truth"],[{**l1[0],"docking_truth":1}])
            args.output_dir=root/"out2";args.l1=bad
            with self.assertRaisesRegex(MOD.SelectionError,"forbidden_field"):MOD.run(args)

if __name__=="__main__":unittest.main()
