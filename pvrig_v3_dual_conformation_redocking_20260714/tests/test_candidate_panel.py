#!/usr/bin/env python3
"""Tests for the fixed 128-candidate panel builder."""

from __future__ import annotations

import csv
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_candidate_panel as panel
from common import read_json, read_tsv


class CandidatePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.protocol = read_json(ROOT / "config/protocol_spec.json")
        cls.sources = panel.load_sources(panel.DEFAULT_SOURCE_ROOT)
        cls.rows, cls.summary = panel.build_panel(cls.protocol, cls.sources)

    def test_contract_counts_and_caps(self) -> None:
        quotas = self.protocol["candidate_panel"]["bucket_quotas"]
        caps = self.protocol["candidate_panel"]["caps"]
        self.assertEqual(len(self.rows), 128)
        self.assertEqual(
            {bucket: sum(1 for row in self.rows if row["selection_bucket"] == bucket) for bucket in quotas},
            quotas,
        )
        for row in self.rows:
            self.assertNotEqual(row["candidate_tier"], panel.TIER4)
            self.assertEqual(row["qc_hard_fail"], "False")
        for cap_name in ("backbone_group_id", "near_cdr3_family_id", "arm_id", "scaffold_id"):
            counts: dict[str, int] = {}
            for row in self.rows:
                counts[row[cap_name]] = counts.get(row[cap_name], 0) + 1
            self.assertLessEqual(max(counts.values()), caps[cap_name])
        h3_counts = {key: sum(1 for row in self.rows if row["h3_regime"] == key) for key in ("L", "S")}
        self.assertLessEqual(h3_counts["L"], caps["h3_L_max"])
        self.assertGreaterEqual(h3_counts["S"], caps["h3_S_min"])

    def test_mandatory_inclusions(self) -> None:
        selected_ids = {row["candidate_id"] for row in self.rows}
        ranked = panel.enrich_ranked_rows(self.sources)
        tier1 = {row["candidate_id"] for row in ranked if row["candidate_tier"] == panel.TIER1}
        formal = {row["candidate_id"] for row in ranked if row["rf2_formal_gate_status"] == panel.RF2_FORMAL_PASS}
        near = {row["candidate_id"] for row in ranked if row["rf2_formal_gate_status"] == panel.RF2_NEAR_PASS}
        self.assertEqual(len(tier1), 47)
        self.assertEqual(len(formal), 4)
        self.assertEqual(len(near), 28)
        self.assertTrue(tier1 <= selected_ids)
        self.assertTrue(formal <= selected_ids)
        self.assertTrue(near <= selected_ids)

    def test_sequence_qc_is_not_candidate_id_joined(self) -> None:
        candidate_ids = {row["candidate_id"] for row in self.sources["candidates"]}
        qc_ids = {row["candidate_id"] for row in self.sources["sequence_qc"]}
        self.assertEqual(len(candidate_ids & qc_ids), 0)
        ranked = panel.enrich_ranked_rows(self.sources)
        self.assertEqual(len(ranked), 1024)
        self.assertTrue(all("qc_hard_fail" in row for row in ranked))

    def test_shuffled_input_rows_are_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir) / "source"
            for relpath in panel.SOURCE_FILES.values():
                src = panel.DEFAULT_SOURCE_ROOT / relpath
                dst = source_root / relpath
                dst.parent.mkdir(parents=True, exist_ok=True)
                rows = read_tsv(src)
                rng = random.Random(str(relpath))
                rng.shuffle(rows)
                with dst.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
            out_a = Path(tmpdir) / "a.tsv"
            sum_a = Path(tmpdir) / "a.json"
            out_b = Path(tmpdir) / "b.tsv"
            sum_b = Path(tmpdir) / "b.json"
            panel.main(["--source-root", str(panel.DEFAULT_SOURCE_ROOT), "--output-tsv", str(out_a), "--summary-json", str(sum_a)])
            panel.main(["--source-root", str(source_root), "--output-tsv", str(out_b), "--summary-json", str(sum_b)])
            self.assertEqual(out_a.read_bytes(), out_b.read_bytes())
            self.assertEqual(sum_a.read_bytes(), sum_b.read_bytes())

    def test_repository_outputs_match_builder_when_present(self) -> None:
        output = ROOT / "inputs/candidates_128.tsv"
        summary = ROOT / "reports/candidate_panel_summary.json"
        if not output.exists() or not summary.exists():
            self.skipTest("panel outputs have not been generated yet")
        with tempfile.TemporaryDirectory() as tmpdir:
            expected_tsv = Path(tmpdir) / "candidates_128.tsv"
            expected_json = Path(tmpdir) / "candidate_panel_summary.json"
            panel.main(["--output-tsv", str(expected_tsv), "--summary-json", str(expected_json)])
            self.assertEqual(output.read_bytes(), expected_tsv.read_bytes())
            self.assertEqual(summary.read_bytes(), expected_json.read_bytes())


if __name__ == "__main__":
    unittest.main()
