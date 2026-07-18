#!/usr/bin/env python3

from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PATH = Path(__file__).with_name("materialize_outer_split_json_v1.py")
SPEC = importlib.util.spec_from_file_location("split_materializer", PATH)
MOD = importlib.util.module_from_spec(SPEC); assert SPEC.loader is not None; SPEC.loader.exec_module(MOD)


class SplitMaterializerTests(unittest.TestCase):
    def test_fixture_closes_five_folds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); training = root / "train.tsv"; outer = root / "outer.tsv"; output = root / "out"
            train_rows = [{"candidate_id": f"c{i}", "parent_framework_cluster": f"p{i % 31}"} for i in range(1507)]
            with training.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(train_rows[0]), delimiter="\t", lineterminator="\n"); writer.writeheader(); writer.writerows(train_rows)
            rows = []
            for fold in range(5):
                score = {f"p{i}" for i in range(31) if i % 5 == fold}
                train = {f"p{i}" for i in range(31)} - score
                for row in train_rows:
                    rows.append({"outer_fold": str(fold), **row, "candidate_role": "score" if row["parent_framework_cluster"] in score else "train", "train_parent_set_sha256": MOD.parent_sha(train), "score_parent_set_sha256": MOD.parent_sha(score)})
            with outer.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
            receipt = MOD.run(outer, training, output, 8)
            self.assertEqual(receipt["status"], "PASS_FIVE_PARENT_ISOLATED_OUTER_SPLIT_JSON_MANIFESTS")
            self.assertEqual(set(receipt["outputs"]), {"0", "1", "2", "3", "4"})
            self.assertEqual(json.loads((output / "outer_fold_0.json").read_text())["fixed_epochs"], 8)


if __name__ == "__main__":
    unittest.main()
