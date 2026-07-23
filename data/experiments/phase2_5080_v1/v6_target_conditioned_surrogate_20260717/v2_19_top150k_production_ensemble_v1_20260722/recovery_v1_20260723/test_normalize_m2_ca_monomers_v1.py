import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("norm",HERE/"normalize_m2_ca_monomers_v1.py")
MOD=importlib.util.module_from_spec(spec); sys.modules[spec.name]=MOD; spec.loader.exec_module(MOD)


class NormalizeTests(unittest.TestCase):
    def test_insertion_codes_become_contiguous_sequence_positions(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=root/"x.pdb"
            lines=[]
            residues=[("ALA",1," "),("CYS",2," "),("ASP",2,"A")]
            for serial,(resn,resseq,icode) in enumerate(residues,1):
                lines.append(f"ATOM  {serial:5d}  CA  {resn} H{resseq:4d}{icode}   {serial:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{90:6.2f}           C  \n")
            # Real production requires >=80 residues; exercise the core with 80.
            for serial in range(4,81):
                lines.append(f"ATOM  {serial:5d}  CA  ALA H{serial:4d}    {serial:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{90:6.2f}           C  \n")
            src.write_text("".join(lines))
            sequence="ACD"+"A"*77
            job=MOD.Job("x",str(src),MOD.sha256_file(src),"H",sequence,"aa/x.pdb",str(root/"out")); (root/"out").mkdir()
            _,_,count,rel=MOD.normalize_job(job); self.assertEqual(count,80)
            out=(root/"out"/rel).read_text().splitlines()
            self.assertEqual(out[2][22:27],"   3 ")
            self.assertEqual(out[79][22:27],"  80 ")


if __name__=="__main__": unittest.main()
