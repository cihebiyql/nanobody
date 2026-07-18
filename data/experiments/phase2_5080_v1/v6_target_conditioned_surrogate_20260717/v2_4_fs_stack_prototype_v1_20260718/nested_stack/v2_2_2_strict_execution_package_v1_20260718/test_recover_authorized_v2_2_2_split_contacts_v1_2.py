import gzip
import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE=Path(__file__).resolve(); spec=importlib.util.spec_from_file_location('v12',HERE.with_name('recover_authorized_v2_2_2_split_contacts_v1_2.py')); v12=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(v12)


class V12FilterTests(unittest.TestCase):
    def test_raw_gzip_filter_preserves_rows_and_candidate_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source.tsv.gz'
            with gzip.open(source,'wt',newline='') as h: h.write('schema\tcandidate_id\tvalue\nS\tA\t1.25\nS\tB\t2.50\nS\tC\t3.75\n')
            destinations={'x':root/'x.gz','y':root/'y.gz'}
            result=v12.filter_raw_gzip(source,destinations,{'A':{'x'},'B':{'x','y'},'C':{'y'}})
            self.assertEqual(result['x']['candidates'],{'A','B'}); self.assertEqual(result['y']['candidates'],{'B','C'})
            with gzip.open(destinations['x'],'rt') as h: self.assertEqual(h.read(),'schema\tcandidate_id\tvalue\nS\tA\t1.25\nS\tB\t2.50\n')


if __name__=='__main__': unittest.main()
