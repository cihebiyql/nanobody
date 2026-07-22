from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


PKG = Path(__file__).resolve().parents[1]


def load_module():
    path = PKG / "src/aggregate_phase_b_3seed_v1.py"
    spec = importlib.util.spec_from_file_location("v213_phase_b_aggregate_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = load_module()


def write_seed(path: Path, variant: str, seed: int, *, tamper: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "candidate_id", "sequence_sha256", "parent_framework_cluster", "fold_id", "seed", "variant",
        "truth_R8", "truth_R9", "truth_Rdual_exact_min",
        f"B_TOP5_{variant}__R8", f"B_TOP5_{variant}__R9", f"B_TOP5_{variant}__Rdual_exact_min",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for index in range(9849):
            truth8 = index / 10000.0
            truth9 = (9848-index) / 10000.0
            # Seed 917 is deliberately poor. It must remain in the primary mean.
            if seed == 43:
                pred8, pred9 = truth8, truth9
            elif seed == 917:
                pred8, pred9 = 0.95-truth8, 0.95-truth9
            else:
                pred8, pred9 = truth8+0.01, truth9-0.01
            candidate = f"C{index:05d}"
            if tamper and seed == 1931 and index == 0:
                candidate = "TAMPERED"
            writer.writerow({
                "candidate_id": candidate,
                "sequence_sha256": f"{index:064x}",
                "parent_framework_cluster": f"P{index%54:02d}",
                "fold_id": index % 5,
                "seed": seed,
                "variant": variant,
                "truth_R8": truth8,
                "truth_R9": truth9,
                "truth_Rdual_exact_min": min(truth8, truth9),
                f"B_TOP5_{variant}__R8": pred8,
                f"B_TOP5_{variant}__R9": pred9,
                f"B_TOP5_{variant}__Rdual_exact_min": min(pred8, pred9),
            })


def contracts(root: Path, variant: str = "L2") -> tuple[Path, Path]:
    promotion = json.loads((PKG / "PHASE_B_PROMOTION_CONTRACT_V1.json").read_text())
    promotion_path = root / "promotion.json"
    promotion_path.write_text(json.dumps(promotion))
    selection = {
        "status": "PASS_PHASE_A_VARIANT_PROMOTED",
        "selected_variant": variant,
        "variants": {variant: {"pooled_ef5": 0.0}},
        "input_access": {"open_development_rows": 0, "frozen_test_rows": 0},
    }
    selection_path = root / "selection.json"
    selection_path.write_text(json.dumps(selection))
    return promotion_path, selection_path


class PhaseBAggregateTests(unittest.TestCase):
    def test_primary_is_mean_receptors_then_exact_min_and_retains_bad_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            promotion, selection = contracts(root)
            paths = {seed: root / f"seed{seed}.tsv" for seed in MOD.SEEDS}
            for seed, path in paths.items():
                write_seed(path, "L2", seed)
            output = root / "nested/aggregate"
            receipt = MOD.aggregate(promotion, selection, paths, output)
            self.assertFalse(receipt["bad_seed_excluded"])
            with (output / "TOP5_L2_3SEED_OOF_PREDICTIONS.tsv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            row = rows[1234]
            mean8 = np.mean([float(row[f"seed{seed}_R8"]) for seed in MOD.SEEDS])
            mean9 = np.mean([float(row[f"seed{seed}_R9"]) for seed in MOD.SEEDS])
            mean_seed_dual = np.mean([float(row[f"seed{seed}_Rdual_exact_min"]) for seed in MOD.SEEDS])
            primary = float(row["primary_Rdual_exact_min"])
            self.assertAlmostEqual(primary, min(mean8, mean9), places=12)
            self.assertNotAlmostEqual(primary, mean_seed_dual, places=6)

    def test_cross_seed_candidate_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            promotion, selection = contracts(root)
            paths = {seed: root / f"seed{seed}.tsv" for seed in MOD.SEEDS}
            for seed, path in paths.items():
                write_seed(path, "L2", seed, tamper=True)
            with self.assertRaisesRegex(MOD.AggregateError, "cross_seed_candidate_closure"):
                MOD.aggregate(promotion, selection, paths, root / "out")

    def test_nonzero_data_access_fails_closed_before_seed_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            promotion, selection = contracts(root)
            payload = json.loads(selection.read_text())
            payload["input_access"]["frozen_test_rows"] = 1
            selection.write_text(json.dumps(payload))
            with self.assertRaisesRegex(MOD.AggregateError, "selection_access"):
                MOD.aggregate(promotion, selection, {43: root/"a", 917: root/"b", 1931: root/"c"}, root/"out")


if __name__ == "__main__":
    unittest.main()
