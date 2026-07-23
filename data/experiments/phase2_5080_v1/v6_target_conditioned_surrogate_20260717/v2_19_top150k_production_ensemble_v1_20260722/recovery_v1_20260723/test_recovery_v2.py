import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIRROR = load("mirror_v2", "materialize_hardlink_mirror_v2.py")


class RecoveryV2Tests(unittest.TestCase):
    def test_atomic_hardlink_mirror_and_revalidation(self):
        with tempfile.TemporaryDirectory(prefix="pvrig_safe_") as td:
            root = Path(td)
            source = root / "source_monomers"
            source.mkdir()
            payload = b"ATOM      1  CA  ALA H   1       0.000   0.000   0.000\n"
            src = source / "aa" / "x.pdb"
            src.parent.mkdir()
            src.write_bytes(payload)
            sha = MIRROR.sha256_file(src)
            manifest = root / "manifest.tsv"
            with manifest.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("candidate_id", "monomer_relative_path", "monomer_sha256"), delimiter="\t")
                writer.writeheader(); writer.writerow({"candidate_id":"x","monomer_relative_path":"aa/x.pdb","monomer_sha256":sha})
            mirror = root / "safe_monomers"
            create = type("Args", (), {"source_root":source,"mirror_root":mirror,"manifest":manifest,"expected_rows":1,"receipt":root/"create.json","mode":"create"})
            validate = type("Args", (), {"source_root":source,"mirror_root":mirror,"manifest":manifest,"expected_rows":1,"receipt":root/"validate.json","mode":"validate"})
            self.assertEqual(MIRROR.run(create)["rows"], 1)
            self.assertEqual(MIRROR.run(validate)["rows"], 1)
            self.assertEqual(src.stat().st_ino, (mirror / "aa" / "x.pdb").stat().st_ino)

    def test_forbidden_safe_root_is_rejected(self):
        with self.assertRaises(MIRROR.MirrorError):
            MIRROR.check_safe_root(Path("/tmp/fixed_pose/cache"))


if __name__ == "__main__":
    unittest.main()
