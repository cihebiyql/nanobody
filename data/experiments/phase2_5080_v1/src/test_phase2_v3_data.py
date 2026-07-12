#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase2_v3_contracts import (  # noqa: E402
    ContractError,
    feature_input_fingerprint,
    normalize_vhh_sequence,
    stable_pair_id,
    unseal_rows,
)
from prepare_phase2_v3_binding_data import SourceSpec, prepare  # noqa: E402


class Phase2V3DataTests(unittest.TestCase):
    def write_source(self, path: Path, rows: list[dict]) -> Path:
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def test_vhh_normalization_trims_leader_and_histidine_tag(self) -> None:
        core = "QVQL" + "A" * 96
        result = normalize_vhh_sequence("MKYLLPTAAAGLLLLAAQPA" + core + "HHHHHH")
        self.assertEqual(result.sequence, core)
        self.assertGreater(result.prefix_trimmed, 0)
        self.assertEqual(result.suffix_trimmed, 6)
        with self.assertRaises(ContractError):
            normalize_vhh_sequence("QVQL" + "A" * 10 + "X")

    def test_stable_pair_id_is_deterministic(self) -> None:
        self.assertEqual(stable_pair_id("a", "b"), stable_pair_id("a", "b"))
        self.assertNotEqual(stable_pair_id("a", "b"), stable_pair_id("b", "a"))

    def test_prepare_seals_formal_labels_and_drops_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_a = "A" * 40
            target_b = "C" * 40
            vhh_a = "QVQL" + "A" * 96
            vhh_b = "QVQL" + "C" * 96
            train = self.write_source(
                root / "train.csv",
                [
                    {"VHH_sequence": vhh_a, "Ag_label": "a", "Ag_sequence": target_a, "label": 1},
                    {"VHH_sequence": vhh_b, "Ag_label": "a", "Ag_sequence": target_a, "label": 0},
                    {"VHH_sequence": vhh_b, "Ag_label": "a", "Ag_sequence": target_a, "label": 1},
                ],
            )
            formal = self.write_source(
                root / "formal.csv",
                [{"VHH_sequence": "QVQL" + "D" * 96, "Ag_label": "b", "label": 1}],
            )
            antigen_map = self.write_source(root / "antigens.csv", [{"Ag_label": "b", "Ag_sequence": target_b}])
            summary = prepare(
                [
                    SourceSpec("train", train, "train", "train"),
                    SourceSpec("formal", formal, "external", "formal", "external_hTNFa", antigen_map),
                ],
                root / "out",
                chunksize=2,
            )
            self.assertEqual(summary["duplicate_audit"]["conflicting_pair_count"], 1)
            blinded = pd.read_csv(root / "out/binding_formal_blinded_v3.csv")
            labels = pd.read_csv(root / "out/binding_formal_labels_sealed_v3.csv")
            self.assertNotIn("label", blinded.columns)
            self.assertEqual(labels["label"].tolist(), [1])
            self.assertEqual(summary["split_audit"]["primary_external_hTNFa_vhh_overlap"], 0)

    def test_unseal_preserves_feature_fingerprint(self) -> None:
        blinded = [{"sample_id": "x", "vhh_sequence": "AAAA", "target_sequence": "CCCC"}]
        labels = [{"sample_id": "x", "label": 1}]
        columns = ["sample_id", "vhh_sequence", "target_sequence"]
        before = feature_input_fingerprint(blinded, columns)
        merged = unseal_rows(blinded, labels, columns)
        self.assertEqual(before, feature_input_fingerprint(merged, columns))
        self.assertEqual(merged[0]["label"], 1)

    def test_primary_formal_vhh_overlap_is_excluded_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vhh = "QVQL" + "A" * 96
            train = self.write_source(
                root / "train.csv",
                [{"VHH_sequence": vhh, "Ag_label": "a", "Ag_sequence": "A" * 40, "label": 1}],
            )
            formal = self.write_source(
                root / "formal.csv",
                [
                    {"VHH_sequence": vhh, "Ag_label": "b", "label": 0},
                    {"VHH_sequence": "QVQL" + "C" * 96, "Ag_label": "b", "label": 1},
                ],
            )
            antigen_map = self.write_source(root / "antigens.csv", [{"Ag_label": "b", "Ag_sequence": "C" * 40}])
            summary = prepare(
                [
                    SourceSpec("train", train, "train", "train"),
                    SourceSpec("formal", formal, "external", "formal", "external_hTNFa", antigen_map),
                ],
                root / "out",
            )
            self.assertEqual(summary["primary_overlap_filter"]["excluded_row_count"], 1)
            self.assertEqual(summary["split_audit"]["primary_external_hTNFa_vhh_overlap"], 0)
            self.assertEqual(len(pd.read_csv(root / "out/binding_formal_blinded_v3.csv")), 1)


if __name__ == "__main__":
    unittest.main()
