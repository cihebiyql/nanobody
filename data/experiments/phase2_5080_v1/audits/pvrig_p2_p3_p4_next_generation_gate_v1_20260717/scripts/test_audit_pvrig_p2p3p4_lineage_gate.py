import csv
import json
import tempfile
import unittest
from pathlib import Path

import audit_pvrig_p2p3p4_lineage_gate as audit


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class P2P3P4LineageGateAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        phases = [phase for phase, count in audit.EXPECTED_PHASE_COUNTS.items() for _ in range(count)]
        self.v4c = [
            {"candidate_id": f"C{i:03d}", "sequence_sha256": f"ch{i:03d}", "phase": phase}
            for i, phase in enumerate(phases)
        ]
        splits = [split for split, count in audit.EXPECTED_OPEN_SPLITS.items() for _ in range(count)]
        self.v4d = [
            {
                "candidate_id": f"D{i:03d}",
                "sequence_sha256": f"dh{i:03d}",
                "model_split": split,
                "target_patch_id": ["A_CENTER", "B_LOWER", "C_CROSS"][i % 3],
                "design_mode": ["H1H3", "H3"][i % 2],
            }
            for i, split in enumerate(splits)
        ]
        self.teacher = [dict(row) for row in self.v4d]
        self.evaluator = {
            "status": "PASS",
            "unlockable": True,
            "gates": {"all": {"status": "PASS"}},
        }
        self.enrichment = {
            "status": "FAIL",
            "unlockable": False,
            "eligible_phases": [],
            "candidate_call_counts": {"total_candidates": 128, "evaluable_candidates": 128},
            "phase_results": [{"phase": phase} for phase in ("P2", "P3", "P4")],
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_audit(self):
        paths = {name: self.root / name for name in (
            "v4c.tsv", "v4d.tsv", "teacher.tsv", "evaluator.json", "enrichment.json", "enrichment.tsv"
        )}
        write_tsv(paths["v4c.tsv"], self.v4c)
        write_tsv(paths["v4d.tsv"], self.v4d)
        write_tsv(paths["teacher.tsv"], self.teacher)
        paths["evaluator.json"].write_text(json.dumps(self.evaluator), encoding="utf-8")
        paths["enrichment.json"].write_text(json.dumps(self.enrichment), encoding="utf-8")
        paths["enrichment.tsv"].write_text("phase\nP2\nP3\nP4\n", encoding="utf-8")
        return audit.build_audit(
            v4c_manifest=paths["v4c.tsv"],
            v4d_manifest=paths["v4d.tsv"],
            v4e_teacher=paths["teacher.tsv"],
            evaluator=paths["evaluator.json"],
            enrichment=paths["enrichment.json"],
            enrichment_tsv=paths["enrichment.tsv"],
        )

    def test_expected_state_passes_audit_and_blocks_generation(self):
        payload = self.run_audit()
        self.assertEqual(payload["status"], "PASS_FAIL_CLOSED_AUDIT")
        self.assertEqual(payload["decision"], "BLOCKED_NO_RELIABLE_P2_P3_P4_ENRICHMENT")
        self.assertFalse(payload["new_sequence_generation_authorized"])
        self.assertEqual(payload["cross_campaign_identity"]["p1_p6_mapping_closure_for_v4e_open258"], 0)

    def test_cross_campaign_sequence_overlap_is_rejected(self):
        self.v4d[0]["sequence_sha256"] = self.v4c[0]["sequence_sha256"]
        self.teacher[0]["sequence_sha256"] = self.v4c[0]["sequence_sha256"]
        with self.assertRaisesRegex(audit.AuditError, "unexpected_v4c_v4d_identity_overlap"):
            self.run_audit()

    def test_any_eligible_phase_is_rejected_from_fail_closed_state(self):
        self.enrichment["status"] = "PASS"
        self.enrichment["unlockable"] = True
        self.enrichment["eligible_phases"] = ["P4"]
        with self.assertRaisesRegex(audit.AuditError, "v3_enrichment_not_expected_fail_closed_state"):
            self.run_audit()


if __name__ == "__main__":
    unittest.main()
