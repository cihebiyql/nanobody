#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/select_100k_label_free_multimodel.py"
SPEC = importlib.util.spec_from_file_location("v27_selector", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def base_config(total: int = 20) -> dict[str, object]:
    return {
        "schema_version": MOD.CONFIG_SCHEMA,
        "candidate_id_column": "candidate_id",
        "models": [
            {
                "name": "m2",
                "score_column": "m2_score",
                "uncertainty_column": "m2_uncertainty",
                "higher_is_better": True,
                "weight": 1.0,
                "uncertainty_penalty": 0.05,
            },
            {
                "name": "f0",
                "score_column": "f0_score",
                "uncertainty_column": "f0_uncertainty",
                "higher_is_better": True,
                "weight": 1.0,
                "uncertainty_penalty": 0.05,
            },
            {
                "name": "binding_prior",
                "score_column": "binding_score",
                "uncertainty_column": "binding_uncertainty",
                "higher_is_better": True,
                "weight": 0.3,
                "uncertainty_penalty": 0.02,
            },
        ],
        "metadata_columns": {
            "parent": "parent_cluster",
            "cdr3": "cdr3_cluster",
            "patch": "patch",
            "method": "method",
        },
        "qc": {
            "pass_columns": ["qc_pass"],
            "fail_columns": ["hard_fail"],
            "numeric_constraints": {"developability": {"min": 0.2}},
        },
        "dedup_key_columns": ["sequence_sha256"],
        "passthrough_columns": ["sequence"],
        "min_models_required": 2,
        "allow_extra_columns": False,
        "selection": {
            "total": total,
            "quotas": {
                "exploitation": total * 5 // 10,
                "single_model_rescue": total * 2 // 10,
                "disagreement": total // 10,
                "diversity": total // 10,
                "random_sentinel": total - (total * 5 // 10 + total * 2 // 10 + total // 10 + total // 10),
            },
            "group_caps": {"parent_cluster": 8, "cdr3_cluster": 3, "patch": 12, "method": 14},
            "diversity_columns": ["parent_cluster", "patch", "method"],
            "sentinel_strata_columns": ["patch", "method"],
            "sentinel_score_bins": 4,
            "disagreement_best_model_weight": 0.25,
            "random_seed": "unit-test-frozen-seed",
        },
    }


def fixture_rows(n: int = 80) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    for index in range(n):
        sequence = "QVQL" + "".join(alphabet[(index + shift) % len(alphabet)] for shift in range(20)) + f"{index:04d}"
        rows.append(
            {
                "candidate_id": f"C{index:04d}",
                "m2_score": f"{((index * 17) % n) / n:.6f}",
                "m2_uncertainty": f"{((index * 7) % 13) / 100:.6f}",
                "f0_score": f"{((index * 29 + 3) % n) / n:.6f}",
                "f0_uncertainty": f"{((index * 11) % 17) / 100:.6f}",
                "binding_score": f"{((index * 31 + 5) % n) / n:.6f}",
                "binding_uncertainty": f"{((index * 5) % 19) / 100:.6f}",
                "parent_cluster": f"P{index % 12:02d}",
                "cdr3_cluster": f"D{index % 30:02d}",
                "patch": ("A", "B", "C")[index % 3],
                "method": ("RF", "MPNN", "LOCAL", "DE_NOVO")[index % 4],
                "qc_pass": "true",
                "hard_fail": "false",
                "developability": "0.8",
                "sequence_sha256": f"sha-{index:04d}",
                "sequence": sequence,
            }
        )
    return rows


class SelectorTest(unittest.TestCase):
    def run_fixture(self, root: Path, rows: list[dict[str, str]], config: dict[str, object], name: str):
        input_path = root / f"{name}.tsv"
        config_path = root / f"{name}.json"
        output_dir = root / f"{name}_out"
        write_tsv(input_path, rows)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        candidate_id, models, selection = MOD.parse_config(config)
        manifest = MOD.atomic_publish(input_path, config_path, output_dir, config, candidate_id, models, selection)
        return output_dir, manifest

    def test_end_to_end_fixed_quotas_caps_hashes_and_reasons(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output, manifest = self.run_fixture(root, fixture_rows(), base_config(), "run")
            selected = read_tsv(output / "selection.tsv")
            self.assertEqual(len(selected), 20)
            self.assertEqual(len({row["candidate_id"] for row in selected}), 20)
            self.assertEqual(Counter(row["selection_channel"] for row in selected), Counter(base_config()["selection"]["quotas"]))
            self.assertTrue(all(row["selection_reason"] for row in selected))
            self.assertEqual(manifest["label_access"]["docking_truth_columns_consumed"], 0)
            self.assertEqual(manifest["selection_sha256"], MOD.sha256_file(output / "selection.tsv"))
            self.assertTrue((output / "SHA256SUMS").is_file())
            for column, cap in base_config()["selection"]["group_caps"].items():
                counts = Counter(row[column] for row in selected)
                self.assertLessEqual(max(counts.values()), cap)

    def test_row_order_does_not_change_selection_or_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = fixture_rows()
            out_a, _ = self.run_fixture(root, rows, base_config(), "a")
            out_b, _ = self.run_fixture(root, list(reversed(rows)), base_config(), "b")
            projection = lambda path: [
                (row["candidate_id"], row["selection_channel"], row["selection_reason"])
                for row in read_tsv(path / "selection.tsv")
            ]
            self.assertEqual(projection(out_a), projection(out_b))

    def test_qc_and_sequence_dedup_are_applied_before_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = fixture_rows()
            rows[0]["qc_pass"] = "false"
            rows[1]["hard_fail"] = "true"
            rows[2]["developability"] = "0.1"
            rows[4]["sequence_sha256"] = rows[3]["sequence_sha256"]
            output, manifest = self.run_fixture(root, rows, base_config(), "qc")
            ids = {row["candidate_id"] for row in read_tsv(output / "selection.tsv")}
            self.assertFalse({"C0000", "C0001", "C0002"} & ids)
            self.assertEqual(manifest["selection_contract"]["duplicate_rows_dropped"], 1)
            self.assertEqual(manifest["qc_counts"]["ineligible_rows"], 3)

    def test_forbidden_truth_column_fails_closed_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = fixture_rows()
            for row in rows:
                row["r_dual_min"] = "0.5"
            input_path = root / "pool.tsv"
            config_path = root / "config.json"
            output = root / "out"
            write_tsv(input_path, rows)
            config = base_config()
            config["allow_extra_columns"] = True
            config_path.write_text(json.dumps(config), encoding="utf-8")
            cid, models, selection = MOD.parse_config(config)
            with self.assertRaisesRegex(MOD.SelectorError, "forbidden_truth_columns"):
                MOD.atomic_publish(input_path, config_path, output, config, cid, models, selection)
            self.assertFalse(output.exists())

    def test_undeclared_extra_column_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = fixture_rows()
            for row in rows:
                row["mystery"] = "x"
            with self.assertRaisesRegex(MOD.SelectorError, "undeclared_input_columns"):
                self.run_fixture(root, rows, base_config(), "extra")

    def test_prohibited_sealed_path_fails_before_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "sealed_pool.tsv"
            write_tsv(path, fixture_rows())
            with self.assertRaisesRegex(MOD.SelectorError, "prohibited_input_path"):
                MOD.read_input(path, base_config(), "candidate_id", MOD.parse_config(base_config())[1])

    def test_impossible_caps_fail_atomically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config()
            config["selection"]["group_caps"] = {"patch": 1}
            with self.assertRaisesRegex(MOD.SelectorError, "quota_unfillable"):
                self.run_fixture(root, fixture_rows(), config, "caps")
            self.assertFalse((root / "caps_out").exists())

    def test_missing_one_model_can_be_rescued_when_minimum_is_two(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = fixture_rows()
            for index in range(0, 20, 2):
                rows[index]["binding_score"] = ""
                rows[index]["binding_uncertainty"] = ""
            output, manifest = self.run_fixture(root, rows, base_config(), "missing")
            self.assertEqual(manifest["selected_rows"], 20)
            self.assertEqual(len(read_tsv(output / "selection.tsv")), 20)

    def test_empty_group_value_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = fixture_rows()
            rows[0]["parent_cluster"] = ""
            with self.assertRaisesRegex(MOD.SelectorError, "empty_required_value"):
                self.run_fixture(root, rows, base_config(), "empty_group")

    def test_higher_is_better_requires_real_json_boolean(self):
        config = base_config()
        config["models"][0]["higher_is_better"] = "false"
        with self.assertRaisesRegex(MOD.SelectorError, "higher_is_better_must_be_boolean"):
            MOD.parse_config(config)


if __name__ == "__main__":
    unittest.main()
