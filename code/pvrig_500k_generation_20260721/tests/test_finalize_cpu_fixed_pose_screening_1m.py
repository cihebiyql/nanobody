from __future__ import annotations

import csv
import gzip
import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "finalize_cpu_fixed_pose_screening_1m.py"
SPEC = importlib.util.spec_from_file_location("finalize_cpu_fixed_pose_screening_1m", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def compressed_tsv(candidate_id: str) -> bytes:
    payload = io.StringIO()
    writer = csv.DictWriter(payload, fieldnames=["candidate_id", "sequence"], delimiter="\t")
    writer.writeheader()
    writer.writerow({"candidate_id": candidate_id, "sequence": "ACDEFGHIK"})
    return gzip.compress(payload.getvalue().encode())


class ArchiveRowsTests(unittest.TestCase):
    def test_reads_tar_members_in_name_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for node_index in range(8):
                node = root / f"node_{node_index:02d}"
                node.mkdir()
                archive = node / f"node_{node_index:02d}_sequence_outputs.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    for worker_index in reversed(range(64)):
                        data = compressed_tsv(f"N{node_index:02d}W{worker_index:02d}")
                        info = tarfile.TarInfo(f"worker_{worker_index:02d}.tsv.gz")
                        info.size = len(data)
                        tar.addfile(info, io.BytesIO(data))

            rows = list(MODULE.archive_rows(root))
            self.assertEqual(len(rows), 8 * 64)
            self.assertEqual(rows[0]["candidate_id"], "N00W00")
            self.assertEqual(rows[-1]["candidate_id"], "N07W63")


if __name__ == "__main__":
    unittest.main()
