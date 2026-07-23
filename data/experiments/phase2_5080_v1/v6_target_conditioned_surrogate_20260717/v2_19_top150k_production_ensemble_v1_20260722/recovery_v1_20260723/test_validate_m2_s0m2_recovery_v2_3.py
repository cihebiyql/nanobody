#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("validator", HERE / "validate_m2_s0m2_recovery_v2_3.py")
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


class ValidatorTests(unittest.TestCase):
    def write_m2(self, path: Path, extra: list[str] | None = None) -> list[str]:
        features = [f"ALL__feature_{index:03d}" for index in range(126)]
        header = [
            "schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster",
            "model_split", "asset_lane", "monomer_sha256", *features, "claim_boundary", *(extra or []),
        ]
        row = ["v", "c1", "s1", "p1", "production", "monomer", "m1", *(["1.0"] * 126), "label-free", *(["2.0"] * len(extra or []))]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(header)
            writer.writerow(row)
        return features

    def test_claim_boundary_is_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "m2.tsv"
            expected = self.write_m2(path)
            mapping, observed = MOD.validate_m2(path, 1)
            self.assertEqual(expected, observed)
            self.assertEqual(mapping["c1"], ("s1", "p1"))

    def test_real_127th_feature_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "m2.tsv"
            self.write_m2(path, ["ALL__unexpected_feature"])
            with self.assertRaisesRegex(MOD.ValidationError, "m2_feature_count:127"):
                MOD.validate_m2(path, 1)


if __name__ == "__main__":
    unittest.main()
