#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("terminalizer", HERE / "terminalize_phase2_v4_f_holdout96_zero_eligible_v2_1.py")
M = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise RuntimeError("loader unavailable")
SPEC.loader.exec_module(M)


class ZeroEligibleTerminalizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v4f96_zero_eligible_v21_"))
        self.source = self.tmp / "source"
        self.output = self.tmp / "output"
        self.output.mkdir()
        self.protocol_path = self.output / M.PROTOCOL_NAME
        self.script_path = self.output / Path(__file__).name
        shutil.copyfile(HERE / "terminalize_phase2_v4_f_holdout96_zero_eligible_v2_1.py", self.script_path)
        self._make_fixture()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    @staticmethod
    def _write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)

    def _make_fixture(self):
        manifest = []
        fast = []
        for index in range(96):
            candidate_id = f"C{index:03d}"
            sequence = "QVQLVESGGGLVQAGGSLRLSCAAS" + "A" * (70 + index % 4) + "WGQGTQVTVSS"
            digest = hashlib.sha256(sequence.encode()).hexdigest()
            manifest.append({"candidate_id": candidate_id, "sequence": sequence, "sequence_sha256": digest})
            fast.append({"candidate_id": candidate_id, "sequence": sequence, "hard_fail": "True", "reason_summary": "numbering_or_framework_failed", "external_binder_status": "NOT_PROVIDED", "external_binder_score": ""})
        self._write_tsv(self.source / "inputs/prospective_holdout96_manifest.tsv", manifest)
        self._write_tsv(self.source / "cascade/fast_merged.tsv", fast)
        state = {"stages": {"prepare": {"status": "complete"}, "fast": {"status": "complete"}, "merge_fast": {"status": "complete", "hard_pass": 0}, "full": {"status": "complete", "chunks": 0, "reason": "no survivors"}}}
        (self.source / "cascade/cascade_state.json").write_text(json.dumps(state))
        for name in ("full_qc_shortlist.tsv", "full_qc_shortlist.fasta", "full_qc_excluded_due_cap.tsv"):
            (self.source / "cascade" / name).write_bytes(b"")
        for index in range(8):
            path = self.source / "cascade/fast_chunks" / f"chunk_{index+1:06d}" / "complete.json"
            path.parent.mkdir(parents=True); path.write_text(json.dumps({"status": "complete", "candidate_count": 12}))
        (self.source / "status").mkdir()
        (self.source / "status/runner.failed.json").write_text(json.dumps({"status": "FAIL_V4_F96_FULL_QC_RECOVERY_V2", "error": "RuntimeError:cascade_stage_not_complete:merge_full", "pid": 999999999}))
        (self.source / "status/runner.launch.pid").write_text("999999999\n")
        for relative in ("IMPLEMENTATION_FREEZE.json", "PACKAGE_RECEIPT.json", "phase2_v4_f_holdout96_full_qc_recovery_v2_preregistration.json", "run_phase2_v4_f_holdout96_full_qc_recovery_v2_node1.py", "inputs/prospective_holdout96_audit.json", "inputs/prospective_holdout96_receipt.json", "inputs/holdout96.fasta", "logs/full_qc_runner.log"):
            path = self.source / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(relative + "\n")
        source_files = [path for path in self.source.rglob("*") if path.is_file() and "fast_chunks" not in str(path) and path.name != "runner.launch.pid"]
        hashes = {str(path.relative_to(self.source)): M.sha256(path) for path in source_files}
        chunk_files = sorted((self.source / "cascade/fast_chunks").glob("chunk_*/complete.json"))
        chunk_set = hashlib.sha256("".join(f"{path.relative_to(self.source)}\t{M.sha256(path)}\n" for path in chunk_files).encode()).hexdigest()
        protocol = {"source_root": str(self.source), "output_root": str(self.output), "source_hashes": hashes, "fast_chunk_completion_set_sha256": chunk_set}
        self.protocol_path.write_text(json.dumps(protocol))
        freeze = {"hashes": {"protocol": M.sha256(self.protocol_path), "terminalizer": M.sha256(self.script_path)}}
        (self.output / M.FREEZE_NAME).write_text(json.dumps(freeze))

    def test_zero_eligible_closure_and_receipt(self):
        receipt = M.finalize(self.source, self.output, self.protocol_path, self.script_path)
        self.assertEqual(receipt["hardpass_count"], 0)
        self.assertEqual(receipt["downstream_docking_eligible_count"], 0)
        summary = json.loads((self.output / "outputs/eligibility_terminal_summary.json").read_text())
        self.assertEqual(summary["terminal_state"], "COMPLETE_WITH_ZERO_ELIGIBLE")
        self.assertFalse(summary["full_qc_executed"])
        with (self.output / "outputs/tnp_three_state_unrun_summary.tsv").open(newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), 96)
        self.assertTrue(all(row["tnp_supervision_state"] == "UPSTREAM_FAST_HARD_FAIL_NA" and not row["tnp_score"] and not row["tnp_flag"] for row in rows))

    def test_one_fast_pass_fails_closed(self):
        rows = M.read_tsv(self.source / "cascade/fast_merged.tsv")
        rows[0]["hard_fail"] = "False"
        self._write_tsv(self.source / "cascade/fast_merged.tsv", rows)
        protocol = json.loads(self.protocol_path.read_text())
        protocol["source_hashes"]["cascade/fast_merged.tsv"] = M.sha256(self.source / "cascade/fast_merged.tsv")
        self.protocol_path.write_text(json.dumps(protocol))
        with self.assertRaisesRegex(RuntimeError, "nonzero_eligible_candidate"):
            M.validate_source(self.source, protocol)

    def test_nonempty_shortlist_fails_closed(self):
        path = self.source / "cascade/full_qc_shortlist.tsv"; path.write_text("candidate_id\nC000\n")
        protocol = json.loads(self.protocol_path.read_text()); protocol["source_hashes"]["cascade/full_qc_shortlist.tsv"] = M.sha256(path)
        with self.assertRaisesRegex(RuntimeError, "nonempty_zero_eligible_artifact"):
            M.validate_source(self.source, protocol)

    def test_source_mutation_fails_hash_gate(self):
        path = self.source / "inputs/holdout96.fasta"; path.write_text("tamper\n")
        with self.assertRaisesRegex(RuntimeError, "source_hash_mismatch"):
            M.validate_source(self.source, json.loads(self.protocol_path.read_text()))

    def test_missing_fast_chunk_fails_closed(self):
        next((self.source / "cascade/fast_chunks").glob("chunk_*/complete.json")).unlink()
        protocol = json.loads(self.protocol_path.read_text())
        with self.assertRaisesRegex(RuntimeError, "fast_chunk_count"):
            M.validate_source(self.source, protocol)

    def test_unexpected_merge_full_fails_closed(self):
        state_path = self.source / "cascade/cascade_state.json"
        state = json.loads(state_path.read_text()); state["stages"]["merge_full"] = {"status": "complete"}; state_path.write_text(json.dumps(state))
        protocol = json.loads(self.protocol_path.read_text()); protocol["source_hashes"]["cascade/cascade_state.json"] = M.sha256(state_path)
        with self.assertRaisesRegex(RuntimeError, "unexpected_merge_full_stage"):
            M.validate_source(self.source, protocol)

    def test_freeze_tamper_fails_closed(self):
        freeze = json.loads((self.output / M.FREEZE_NAME).read_text()); freeze["hashes"]["terminalizer"] = "0" * 64; (self.output / M.FREEZE_NAME).write_text(json.dumps(freeze))
        with self.assertRaisesRegex(RuntimeError, "implementation_freeze_mismatch"):
            M.validate_package(self.output, self.protocol_path, self.script_path)

    def test_existing_output_fails_closed(self):
        path = self.output / "outputs/existing.txt"; path.parent.mkdir(); path.write_text("x")
        with self.assertRaisesRegex(RuntimeError, "nonzero_terminalization_output"):
            M.finalize(self.source, self.output, self.protocol_path, self.script_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
