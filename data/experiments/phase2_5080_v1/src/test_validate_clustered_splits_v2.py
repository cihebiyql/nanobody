#!/usr/bin/env python3
"""Unit tests for the independent clustered split validator."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_clustered_splits_v2 import validate


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def args_for(root: Path) -> Namespace:
    return Namespace(root=str(root), site=None, pair=None, contact=None, pvrig_controls=None)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def split_seq(prefix: str, split: str, idx: int) -> str:
    return f"{prefix}_{split}_{idx}"


class ClusteredSplitValidatorTests(unittest.TestCase):
    def make_valid_root(self, root: Path) -> None:
        base = root / "experiments/phase2_5080_v1"
        site_rows = []
        pair_rows = []
        contact_rows = []
        for split, count in (("train", 6), ("val", 2), ("test", 2)):
            for idx in range(count):
                vhh = split_seq("VHH", split, idx)
                antigen = split_seq("AG", split, idx)
                site_rows.append(
                    {
                        "sample_id": f"site_{split}_{idx}",
                        "split": split,
                        "vhh_seq": vhh,
                        "antigen_seq": antigen,
                        "binding_label": "1",
                        "vhh_cluster_id": f"vhh_cluster_{split}_{idx}",
                        "cdr3_proxy_cluster_id": f"cdr3_cluster_{split}_{idx}",
                        "antigen_cluster_id": f"ag_cluster_{split}_{idx}",
                        "split_group_id": f"group_{split}_{idx}",
                        "label_source": "cognate_structure_pair",
                        "source_dataset": "fixture",
                        "source_file": "fixture.csv",
                        "source_row": idx,
                    }
                )
                pair_rows.append(
                    {
                        "pair_id": f"pair_pos_{split}_{idx}",
                        "split": split,
                        "vhh_seq": vhh,
                        "antigen_seq": antigen,
                        "binding_label": "1",
                        "vhh_cluster_id": f"vhh_cluster_{split}_{idx}",
                        "cdr3_proxy_cluster_id": f"cdr3_cluster_{split}_{idx}",
                        "antigen_cluster_id": f"ag_cluster_{split}_{idx}",
                        "split_group_id": f"group_{split}_{idx}",
                        "label_source": "cognate_structure_pair",
                        "negative_type": "positive_cognate_pair",
                        "construction_rule": "observed_cognate_pair",
                    }
                )
                pair_rows.append(
                    {
                        "pair_id": f"pair_neg_{split}_{idx}",
                        "split": split,
                        "vhh_seq": vhh,
                        "antigen_seq": split_seq("NEG_AG", split, idx),
                        "binding_label": "0",
                        "vhh_cluster_id": f"vhh_cluster_{split}_{idx}",
                        "cdr3_proxy_cluster_id": f"cdr3_cluster_{split}_{idx}",
                        "antigen_cluster_id": f"neg_ag_cluster_{split}_{idx}",
                        "split_group_id": f"group_{split}_{idx}",
                        "label_source": "constructed_negative",
                        "negative_type": "easy_negative",
                        "construction_rule": "fixture_negative",
                    }
                )
                contact_rows.append(
                    {
                        "complex_id": f"contact_{split}_{idx}",
                        "split": split,
                        "vhh_seq": split_seq("CONTACT_VHH", split, idx),
                        "antigen_seq": split_seq("CONTACT_AG", split, idx),
                        "vhh_cluster_id": f"contact_vhh_cluster_{split}_{idx}",
                        "cdr3_proxy_cluster_id": f"contact_cdr3_cluster_{split}_{idx}",
                        "antigen_cluster_id": f"contact_ag_cluster_{split}_{idx}",
                        "split_group_id": f"contact_group_{split}_{idx}",
                        "positive_pairs": 3,
                        "negative_pairs": 12,
                    }
                )
        write_csv(base / "data_splits/zym_site_split_manifest_v2.csv", site_rows)
        write_csv(base / "data_splits/pair_binding_split_v2.csv", pair_rows)
        write_jsonl(base / "prepared/structure_contact_maps_clustered_v2.jsonl", contact_rows)
        write_csv(
            base / "data_splits/pvrig_external_calibration_manifest_v1.csv",
            [
                {
                    "sample_id": "pvrig_control_1",
                    "split": "pvrig_external",
                    "role": "known_positive_calibration_only",
                    "sequence": "PVRIG_CONTROL_VHH",
                    "label_hint": "positive_blocking_control",
                    "leakage_policy": "exclude_from_training_and_new_candidate_ranking",
                }
            ],
        )

    def test_passes_when_clustered_splits_are_disjoint_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_valid_root(root)
            result = validate(args_for(root))
        self.assertEqual(result["status"], "PASS")

    def test_fails_when_exact_vhh_overlaps_between_splits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_valid_root(root)
            site = root / "experiments/phase2_5080_v1/data_splits/zym_site_split_manifest_v2.csv"
            rows = read_csv(site)
            rows[-1]["vhh_seq"] = rows[0]["vhh_seq"]
            write_csv(site, rows)
            result = validate(args_for(root))
        self.assertIn("site_exact_vhh_overlap_zero", result["failed_checks"])

    def test_fails_when_cluster_overlaps_across_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_valid_root(root)
            site = root / "experiments/phase2_5080_v1/data_splits/zym_site_split_manifest_v2.csv"
            contact = root / "experiments/phase2_5080_v1/prepared/structure_contact_maps_clustered_v2.jsonl"
            site_rows = read_csv(site)
            contact_rows = [json.loads(line) for line in contact.read_text(encoding="utf-8").splitlines()]
            train_cluster = next(row["vhh_cluster_id"] for row in site_rows if row["split"] == "train")
            next(row for row in contact_rows if row["split"] == "test")["vhh_cluster_id"] = train_cluster
            write_jsonl(contact, contact_rows)
            result = validate(args_for(root))
        self.assertIn("combined_vhh_cluster_id_overlap_zero", result["failed_checks"])

    def test_fails_when_pair_source_fields_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_valid_root(root)
            pair = root / "experiments/phase2_5080_v1/data_splits/pair_binding_split_v2.csv"
            rows = read_csv(pair)
            rows[0]["label_source"] = ""
            rows[0]["construction_rule"] = ""
            write_csv(pair, rows)
            result = validate(args_for(root))
        self.assertIn("pair_label_source_complete", result["failed_checks"])
        self.assertIn("pair_source_detail_complete", result["failed_checks"])

    def test_fails_when_pvrig_control_enters_train(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_valid_root(root)
            site = root / "experiments/phase2_5080_v1/data_splits/zym_site_split_manifest_v2.csv"
            rows = read_csv(site)
            rows[0]["vhh_seq"] = "PVRIG_CONTROL_VHH"
            write_csv(site, rows)
            result = validate(args_for(root))
        self.assertIn("site_pvrig_controls_absent_from_train_vhh", result["failed_checks"])


if __name__ == "__main__":
    unittest.main()
