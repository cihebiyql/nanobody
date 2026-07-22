from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/run_oof_early_enrichment_portfolio_v1.py"
SPEC = importlib.util.spec_from_file_location("v212_portfolio_test_module", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("portfolio_import_failed")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class PortfolioTests(unittest.TestCase):
    def test_full_contract_closure_and_exact_min_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            teacher_rows: list[dict[str, str]] = []
            legacy_oof_rows: list[dict[str, str]] = []
            clean_oof_rows: list[dict[str, str]] = []
            for index in range(9849):
                candidate = f"T{index:05d}"
                parent = f"P{index % 54:02d}"
                r8 = 0.45 + (index % 137) / 2000.0
                r9 = 0.46 + (index % 149) / 2100.0
                teacher_rows.append({
                    "candidate_id": candidate,
                    "sequence_sha256": f"{index:064x}",
                    "parent_framework_cluster": parent,
                    "teacher_source": f"SRC{index % 2}",
                    "sample_weight": "1",
                    "R_8X6B": repr(r8),
                    "R_9E6Y": repr(r9),
                })
                row = {
                    "candidate_id": candidate,
                    "parent_framework_cluster": parent,
                    "truth_R8": repr(r8),
                    "truth_R9": repr(r9),
                }
                for offset, prefix in enumerate(MODULE.LEGACY_COLUMNS.values(), start=1):
                    row[f"{prefix}__R8"] = repr(r8 + offset * 0.0002)
                    row[f"{prefix}__R9"] = repr(r9 - offset * 0.0001)
                legacy_oof_rows.append(row)
                clean_oof_rows.append({
                    "candidate_id": candidate,
                    "parent_framework_cluster": parent,
                    "truth_R8": repr(r8),
                    "truth_R9": repr(r9),
                    "B_CLEAN_TARGET_ATTENTION__R8": repr(r8 - 0.0003),
                    "B_CLEAN_TARGET_ATTENTION__R9": repr(r9 + 0.0003),
                })
            legacy_dev_rows: list[dict[str, str]] = []
            clean_dev_rows: list[dict[str, str]] = []
            for index in range(795):
                candidate = f"D{index:04d}"
                parent = f"Q{index % 10:02d}"
                r8 = 0.47 + (index % 83) / 1800.0
                r9 = 0.48 + (index % 79) / 1900.0
                row = {
                    "candidate_id": candidate,
                    "parent_framework_cluster": parent,
                    "truth_R8": repr(r8),
                    "truth_R9": repr(r9),
                }
                for offset, prefix in enumerate(MODULE.LEGACY_COLUMNS.values(), start=1):
                    row[f"{prefix}__R8"] = repr(r8 + offset * 0.0002)
                    row[f"{prefix}__R9"] = repr(r9 - offset * 0.0001)
                legacy_dev_rows.append(row)
                clean_dev_rows.append({
                    "candidate_id": candidate,
                    "parent_framework_cluster": parent,
                    "target_R_8X6B": repr(r8),
                    "target_R_9E6Y": repr(r9),
                    "prediction_R_8X6B": repr(r8 - 0.0003),
                    "prediction_R_9E6Y": repr(r9 + 0.0003),
                })
            paths = {
                "teacher": root / "teacher.tsv",
                "legacy_oof": root / "legacy_oof.tsv",
                "clean_oof": root / "clean_oof.tsv",
                "legacy_development": root / "legacy_dev.tsv",
                "clean_development": root / "clean_dev.tsv",
            }
            for name, rows in (
                ("teacher", teacher_rows),
                ("legacy_oof", legacy_oof_rows),
                ("clean_oof", clean_oof_rows),
                ("legacy_development", legacy_dev_rows),
                ("clean_development", clean_dev_rows),
            ):
                write(paths[name], rows)
            output = root / "output"
            arguments = [
                "--contract", str(ROOT / "PORTFOLIO_CONTRACT_V1.json"),
                "--teacher", str(paths["teacher"]), "--teacher-sha256", sha(paths["teacher"]),
                "--legacy-oof", str(paths["legacy_oof"]), "--legacy-oof-sha256", sha(paths["legacy_oof"]),
                "--clean-oof", str(paths["clean_oof"]), "--clean-oof-sha256", sha(paths["clean_oof"]),
                "--legacy-development", str(paths["legacy_development"]), "--legacy-development-sha256", sha(paths["legacy_development"]),
                "--clean-development", str(paths["clean_development"]), "--clean-development-sha256", sha(paths["clean_development"]),
                "--output-dir", str(output),
            ]
            result = MODULE.run(MODULE.parser().parse_args(arguments))
            self.assertEqual(result["status"], "PASS_OPEN_DEVELOPMENT_PORTFOLIO_COMPLETE")
            metrics = json.loads((output / "METRICS.json").read_text(encoding="utf-8"))
            self.assertFalse(metrics["fit"]["development_used_for_fit_or_selection"])
            self.assertFalse(metrics["fit"]["meta_train_performance_reported_as_oof"])
            with (output / "OPEN_DEVELOPMENT_PORTFOLIO_PREDICTIONS.tsv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 795)
            for row in rows[:20]:
                for prefix in ("CONVEX4_L2_0P01", "POSITIVE_RIDGE4_ALPHA1"):
                    self.assertAlmostEqual(
                        float(row[f"{prefix}__Rdual_exact_min"]),
                        min(float(row[f"{prefix}__R8"]), float(row[f"{prefix}__R9"])),
                    )


if __name__ == "__main__":
    unittest.main()
