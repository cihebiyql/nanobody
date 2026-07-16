#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("merge_pvrig_candidate_evidence_v2.py")
SPEC = importlib.util.spec_from_file_location("candidate_evidence_v2", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def sequence_for(index: int) -> str:
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    suffix = ""
    value = index
    for _ in range(4):
        suffix += alphabet[value % len(alphabet)]
        value //= len(alphabet)
    return "QVQLVESGGG" + suffix + "WGQGTQVTVSS"


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t" if path.suffix == ".tsv" else ",")
        writer.writeheader()
        writer.writerows(rows)


class CandidateEvidenceV2Tests(unittest.TestCase):
    def make_sources(self, directory: Path) -> dict[str, Path]:
        fields = [
            "candidate_id", "sequence", "sequence_sha256", "source_cohort", "geometry_status",
            "tnp_status", "tnp_flags", "structure_crosscheck_status", *MOD.TEACHER_FIELDS,
        ]
        # dict expansion above deliberately supplies all existing geometry columns.
        fields = list(dict.fromkeys(fields))
        master_rows = []
        split_rows = []
        for index in range(418):
            candidate_id = f"C{index:03d}"
            sequence = sequence_for(index)
            row = {field: "" for field in fields}
            row.update({
                "candidate_id": candidate_id, "sequence": sequence,
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "source_cohort": "FULLQC290_PRIMARY" if index < 290 else "DUAL128_SECONDARY",
                "geometry_status": "V1_PENDING",
            })
            master_rows.append(row)
            if index < 290:
                split_rows.append({
                    "candidate_id": candidate_id, "sequence": sequence,
                    "sequence_sha256": row["sequence_sha256"],
                    "model_split": "OPEN_TRAIN" if index < 226 else "OPEN_DEVELOPMENT" if index < 258 else "PROSPECTIVE_COMPUTATIONAL_TEST",
                })
        master = directory / "master.tsv"
        split = directory / "split.tsv"
        write_rows(master, fields, master_rows)
        write_rows(split, list(split_rows[0]), split_rows)
        return {"master": master, "split": split, "rows": master_rows}  # type: ignore[return-value]

    def make_teacher(self, directory: Path, source: dict[str, Path], include_test: bool = False) -> Path:
        rows = source["rows"]  # type: ignore[assignment]
        selected = list(range(258))
        if include_test:
            selected[-1] = 258
        fields = ["candidate_id", "sequence_sha256", *[aliases[0] for aliases in MOD.TEACHER_FIELDS.values()]]
        teacher_rows = []
        for index in selected:
            row = rows[index]
            teacher_rows.append({
                "candidate_id": row["candidate_id"], "sequence_sha256": row["sequence_sha256"],
                "R_8X6B": "0.8", "R_9E6Y": "0.7", "R_dual_mean": "0.75", "R_dual_min": "0.7", "R_dual_gap": "0.1",
                "geometry_uncertainty": "0.02", "native_cross_support_agreement_mean": "0.9", "model_pair_consensus_fraction_mean": "0.85",
                "successful_seed_count_8X6B": "3", "successful_seed_count_9E6Y": "3",
            })
        path = directory / "teacher.tsv"
        write_rows(path, fields, teacher_rows)
        return path

    def test_happy_path_merges_open_teacher_and_100_row_deep_qc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.make_sources(directory)
            teacher = self.make_teacher(directory, source)
            rows = source["rows"]  # type: ignore[assignment]
            tnp_rows = [{"candidate_id": row["candidate_id"], "sequence_sha256": row["sequence_sha256"], "TNP_flags": "ok", "PSH": "1", "PPC": "2", "PNC": "3"} for row in rows[:100]]
            igfold_rows = [{"candidate_id": row["candidate_id"], "coverage": "0.98", "path": "models/x.pdb", "status": "PASS"} for row in rows[:100]]
            nbb2_rows = [{
                "candidate_id": row["candidate_id"], "crosscheck_status": "SEQUENCE_MATCH",
                "common_framework_ca_count": "92", "framework_ca_rmsd": "1.25",
                "cdr3_anchor_distance_delta": "0.40",
            } for row in rows[:100]]
            tnp, igfold, nbb2 = directory / "tnp.tsv", directory / "igfold.tsv", directory / "nbb2.tsv"
            write_rows(tnp, list(tnp_rows[0]), tnp_rows)
            write_rows(igfold, list(igfold_rows[0]), igfold_rows)
            write_rows(nbb2, list(nbb2_rows[0]), nbb2_rows)
            outdir = directory / "out"
            audit = MOD.run(MOD.parse_args(["--input", str(source["master"]), "--v4d-split", str(source["split"]), "--v4d-open-teacher", str(teacher), "--tnp-summary", str(tnp), "--igfold-summary", str(igfold), "--igfold-nbb2-audit", str(nbb2), "--outdir", str(outdir)]))
            self.assertEqual(audit["row_count"], 418)
            self.assertEqual(audit["v4d"]["open_teacher_rows"], 258)
            self.assertEqual(audit["v4d"]["sealed_test_rows"], 32)
            self.assertEqual(audit["deep_qc"], {"tnp_merged_rows": 100, "igfold_merged_rows": 100, "nbb2_merged_rows": 100})
            with (outdir / "candidate_evidence_master.tsv").open(newline="") as handle:
                output = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(output[0]["r_dual_mean"], "0.75")
            self.assertEqual(output[258]["geometry_status"], MOD.SEALED_STATUS)
            self.assertEqual(output[0]["tnp_merge_status"], "MERGED_TNP_QC_ONLY")
            self.assertEqual(output[0]["successful_seeds_8x6b"], "3")
            self.assertEqual(output[0]["geometry_status"], "OPEN_AVAILABLE_V4D_COMPUTATIONAL_GEOMETRY")
            self.assertEqual(output[0]["igfold_nbb2_framework_ca_rmsd"], "1.25")
            self.assertTrue((outdir / "SHA256SUMS").is_file())
            self.assertEqual(json.loads((outdir / "candidate_evidence_lineage_audit.json").read_text())["status"], "PASS_V2_MERGE")

    def test_teacher_test_leakage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.make_sources(directory)
            with self.assertRaisesRegex(MOD.MergeError, "sealed_test_id_present"):
                MOD.run(MOD.parse_args(["--input", str(source["master"]), "--v4d-split", str(source["split"]), "--v4d-open-teacher", str(self.make_teacher(directory, source, include_test=True)), "--outdir", str(directory / "out")]))

    def test_deep_qc_unknown_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.make_sources(directory)
            tnp = directory / "tnp.tsv"
            write_rows(tnp, ["candidate_id", "PSH"], [{"candidate_id": "NOT_IN_MASTER", "PSH": "1"}])
            with self.assertRaisesRegex(MOD.MergeError, "unknown_candidate_id"):
                MOD.run(MOD.parse_args(["--input", str(source["master"]), "--v4d-split", str(source["split"]), "--tnp-summary", str(tnp), "--outdir", str(directory / "out")]))

    def test_missing_optional_inputs_remain_explicitly_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.make_sources(directory)
            outdir = directory / "out"
            MOD.run(MOD.parse_args(["--input", str(source["master"]), "--v4d-split", str(source["split"]), "--outdir", str(outdir)]))
            with (outdir / "candidate_evidence_master.tsv").open(newline="") as handle:
                output = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(output[0]["v4d_teacher_merge_status"], "PENDING_V4D_OPEN_TEACHER_INPUT")
            self.assertEqual(output[0]["tnp_merge_status"], "PENDING_TNP_SUMMARY_INPUT")
            self.assertEqual(output[0]["igfold_merge_status"], "PENDING_IGFOLD_SUMMARY_INPUT")
            self.assertEqual(output[0]["nbb2_merge_status"], "PENDING_NBB2_AUDIT_INPUT")
            self.assertEqual(output[258]["v4d_teacher_merge_status"], MOD.SEALED_STATUS)


if __name__ == "__main__":
    unittest.main()
