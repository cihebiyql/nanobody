from __future__ import annotations
import csv,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from fixture_utils import fixture
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'src/materialize_canonical_multimodal_v1.py';S=importlib.util.spec_from_file_location('v211mat',P);M=importlib.util.module_from_spec(S);sys.modules[S.name]=M;S.loader.exec_module(M)
class Tests(unittest.TestCase):
 def test_materializes_closed_fixture(self):
  with tempfile.TemporaryDirectory() as tmp:
   f=fixture(Path(tmp));out=Path(tmp)/'out';args=M.parser().parse_args(['--teacher',str(f['teacher']),'--split-manifest',str(f['split']),'--structure-v4d',str(f['s4']),'--structure-v4h',str(f['sh']),'--coarse-pose',str(f['c2']),'--esm2-650m-cache',str(f['cache']),'--output-dir',str(out),'--expected-rows','60','--expected-train-rows','48','--expected-development-rows','12'])
   result=M.materialize(args);self.assertEqual(result['rows'],60)
   receipt=json.loads((out/'MATERIALIZATION_RECEIPT.json').read_text());self.assertEqual(receipt['structure_feature_count'],126);self.assertEqual(receipt['coarse_model_feature_count'],32)
   with (out/'canonical_multimodal_open.tsv').open() as h:rows=list(csv.DictReader(h,delimiter='\t'))
   self.assertEqual(sum(r['model_split']=='development' for r in rows),12);self.assertTrue(all(abs(float(r['R_dual_min'])-min(float(r['R_8X6B']),float(r['R_9E6Y'])))<2e-8 for r in rows))
 def test_output_must_not_exist(self):
  with tempfile.TemporaryDirectory() as tmp:
   f=fixture(Path(tmp));out=Path(tmp)/'out';out.mkdir();args=M.parser().parse_args(['--teacher',str(f['teacher']),'--split-manifest',str(f['split']),'--structure-v4d',str(f['s4']),'--structure-v4h',str(f['sh']),'--coarse-pose',str(f['c2']),'--esm2-650m-cache',str(f['cache']),'--output-dir',str(out),'--expected-rows','60','--expected-train-rows','48','--expected-development-rows','12'])
   with self.assertRaisesRegex(M.MaterializationError,'output_exists'):M.materialize(args)
if __name__=='__main__':unittest.main()
