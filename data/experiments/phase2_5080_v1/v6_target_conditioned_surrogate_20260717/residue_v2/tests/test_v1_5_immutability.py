from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


V1_ROOT = Path(__file__).parents[2] / "residue_v1"
FROZEN = {
    "IMPLEMENTATION_FREEZE_V1_5.json": "3a4046462bcf138c25c5c36005d1f6e24f2df3f931fe32369dba80ee834e155e",
    "RESIDUE_V1_5_CONTRACT.json": "8bea5ce97308fcf1a2133c7c30457aa997eaaec24c072bf6965b39deb4e8945d",
    "src/train_nested_residue_surrogate_v1_5.py": "6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af",
    "src/collect_residue_oof_v1_5.py": "a15db4aceaeb8c62bca277d9d39015aff3e7e95bacf30a3dd635c1d18558cee0",
    "src/residue_model.py": "c6745faf5d9c4afb101015f751b89e2aefb82aa4ccfbf3259c2d2c9cba4b05bb",
    "src/build_dual_contact_targets.py": "59f0f8bc2f311a776b2d61ea2d075d55488e811b68d55d3665e8a760069594e5",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class V15ImmutabilityTests(unittest.TestCase):
    def test_frozen_v1_5_files_remain_byte_identical(self) -> None:
        for relative, expected in FROZEN.items():
            path = V1_ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertFalse(path.is_symlink(), relative)
            self.assertEqual(sha256(path), expected, relative)


if __name__ == "__main__":
    unittest.main()
