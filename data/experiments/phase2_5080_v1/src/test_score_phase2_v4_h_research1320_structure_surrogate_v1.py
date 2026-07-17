import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("score_phase2_v4_h_research1320_structure_surrogate_v1.py")
SPEC = importlib.util.spec_from_file_location("v4h_scorer", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ScorerTests(unittest.TestCase):
    def fixture(self, root: Path, weight: float = 1.0, gamma: float = 0.0):
        features = root / "features.tsv"
        names = [f"f{index:03d}" for index in range(126)]
        fields = ["schema_version", "candidate_id", "sequence_sha256", "parent_framework_cluster", "target_patch_id", "design_mode", "monomer_sha256", *names, "claim_boundary"]
        with features.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index in range(3):
                row = {
                    "schema_version":"x", "candidate_id":f"C{index}", "sequence_sha256":f"{index:064x}",
                    "parent_framework_cluster":"P", "target_patch_id":"A", "design_mode":"H3",
                    "monomer_sha256":f"{index + 10:064x}", "claim_boundary":"x",
                }
                row.update({name: str(float(index + feature)) for feature, name in enumerate(names)})
                writer.writerow(row)
        config = root / "config.json"
        config.write_text(json.dumps({
            "fit_rows":226, "primary_target":"R_dual_min", "structure_feature_names":names,
            "open_development_target_values_accessed":0, "V4_F_test32_labels_accessed":0,
            "full_train_hyperparameters":{"fusion_structure_weight":weight,"residual_gamma":gamma},
        }))
        fits = root / "fits.npz"
        np.savez(fits,
            M2_structure__intercept=np.asarray([0.5]),
            M2_structure__coefficient=np.ones(126),
            M2_structure__center=np.zeros(126),
            M2_structure__scale=np.ones(126),
        )
        return features, config, fits

    def test_scores_and_ranks_structure_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            features, config, fits = self.fixture(root)
            result = module.score(features, config, fits, root / "out", expected_feature_sha256=sha(features), expected_config_sha256=sha(config), expected_fit_sha256=sha(fits), expected_rows=3)
            self.assertEqual(result["row_count"], 3)
            with (root / "out/v4h_research1320_structure_surrogate_ranking_v1.tsv").open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual([row["candidate_id"] for row in rows], ["C2", "C1", "C0"])
            self.assertEqual(result["V4_H_geometry_labels_accessed"], 0)

    def test_rejects_non_structure_selected_fusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            features, config, fits = self.fixture(root, weight=0.5)
            with self.assertRaisesRegex(module.ScoringError, "late_fusion_not_structure_only"):
                module.score(features, config, fits, root / "out", expected_feature_sha256=sha(features), expected_config_sha256=sha(config), expected_fit_sha256=sha(fits), expected_rows=3)

    def test_hash_mismatch_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            features, config, fits = self.fixture(root)
            with self.assertRaisesRegex(module.ScoringError, "feature_table_hash_mismatch"):
                module.score(features, config, fits, root / "out", expected_feature_sha256="0" * 64, expected_config_sha256=sha(config), expected_fit_sha256=sha(fits), expected_rows=3)


if __name__ == "__main__":
    unittest.main()
