#!/usr/bin/env python3

from __future__ import annotations

import csv
import importlib.util
import json
import tarfile
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("materialize_phase2_v4_d_open258_structure_inputs_v1.py")
SPEC = importlib.util.spec_from_file_location("structure_inputs_v1", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


SPLIT_FIELDS = (
    "candidate_id", "sequence_sha256", "sequence", "parent_id",
    "parent_framework_cluster", "original_formal_split", "model_split",
    "design_method", "design_mode", "target_patch_id", "cdr1", "cdr2",
    "cdr3", "cdr3_length", "new_dual_docking_label_policy", "claim_boundary",
)
JOB_FIELDS = (
    "job_id", "priority", "entity_type", "entity_id", "control_class",
    "expected_behavior", "conformation", "seed", "sequence_sha256",
    "cdr1_range", "cdr2_range", "cdr3_range", "cdr_residues",
    "monomer_source", "monomer_source_kind", "monomer_source_chain",
    "receptor_pdb", "receptor_chain", "ligand_chain", "vhh_chain",
    "numbering", "cfg_hash", "restraint_hash", "protocol_core_sha256",
    "protocol_hash", "job_hash", "job_hash_basis",
)


def write_tsv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pdb_text(candidate_id: str) -> str:
    return (
        f"REMARK  {candidate_id}\n"
        "ATOM      1  N   GLN A   1       0.000   0.000   0.000  1.00  0.80           N  \n"
        "ATOM      2  CA  GLN A   1       1.000   0.000   0.000  1.00  0.80           C  \n"
        "ATOM      3  CA  VAL A   2       2.000   1.000   0.000  1.00  0.70           C  \n"
        "ATOM      4  CA  GLY A   3       3.000   1.000   1.000  1.00  0.60           C  \n"
        "END\n"
    )


class MaterializerTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        campaign = root / "campaign"
        split_rows: list[dict[str, str]] = []
        job_rows: list[dict[str, str]] = []
        split_roles = ["OPEN_TRAIN"] * 226 + ["OPEN_DEVELOPMENT"] * 32 + [MOD.SEALED_SPLIT] * 32
        for index, role in enumerate(split_roles):
            candidate_id = f"CAND_{index:03d}"
            sequence = f"SEQ{index:03d}"
            import hashlib
            sequence_sha = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            split_rows.append({
                "candidate_id": candidate_id,
                "sequence_sha256": sequence_sha,
                "sequence": sequence,
                "parent_id": f"P{index // 13:02d}",
                "parent_framework_cluster": f"C{index // 13:02d}",
                "original_formal_split": "train",
                "model_split": role,
                "design_method": "test",
                "design_mode": "H3",
                "target_patch_id": "A_CENTER",
                "cdr1": "AAA",
                "cdr2": "BBB",
                "cdr3": "CCC",
                "cdr3_length": "3",
                "new_dual_docking_label_policy": "frozen",
                "claim_boundary": "test",
            })
            relative = f"inputs/candidate_monomers/{candidate_id}.pdb"
            if role != MOD.SEALED_SPLIT:
                pdb = campaign / relative
                pdb.parent.mkdir(parents=True, exist_ok=True)
                pdb.write_text(pdb_text(candidate_id), encoding="ascii")
            for job_index, (conformation, seed) in enumerate(
                [(c, s) for c in ("8x6b", "9e6y") for s in (917, 1931, 3253)]
            ):
                row = {field: "" for field in JOB_FIELDS}
                row.update({
                    "job_id": f"JOB_{candidate_id}_{job_index}",
                    "priority": str(job_index + 1),
                    "entity_type": "candidate",
                    "entity_id": candidate_id,
                    "conformation": conformation,
                    "seed": str(seed),
                    "sequence_sha256": sequence_sha,
                    "cdr1_range": "1-1",
                    "cdr2_range": "2-2",
                    "cdr3_range": "3-3",
                    "cdr_residues": "1,2,3",
                    "monomer_source": relative,
                    "monomer_source_kind": MOD.EXPECTED_MONOMER_KIND,
                    "monomer_source_chain": "A",
                })
                job_rows.append(row)
        split = root / "split.tsv"
        jobs = root / "jobs.tsv"
        write_tsv(split, SPLIT_FIELDS, split_rows)
        write_tsv(jobs, JOB_FIELDS, job_rows)
        return split, jobs, campaign

    def test_materializes_exact_open258_and_skips_missing_sealed_pdbs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            split, jobs, campaign = self.build_fixture(root)
            result = MOD.materialize(split, jobs, campaign, root / "out")
            self.assertEqual(result["candidate_count"], 258)
            self.assertEqual(result["sealed_monomer_files_opened"], 0)
            manifest = root / "out/outputs" / MOD.MANIFEST_NAME
            with manifest.open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 258)
            self.assertFalse(any(row["model_split"] == MOD.SEALED_SPLIT for row in rows))
            audit = json.loads((root / "out/outputs" / MOD.AUDIT_NAME).read_text())
            self.assertEqual(audit["sealed_boundary"]["sealed_monomer_files_opened"], 0)
            self.assertEqual(audit["sealed_boundary"]["geometry_label_values_read"], 0)
            with tarfile.open(root / "out" / MOD.ARCHIVE_NAME, "r:gz") as bundle:
                self.assertEqual(len(bundle.getmembers()), 261)

    def test_archive_is_deterministic_for_same_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            split, jobs, campaign = self.build_fixture(root)
            first = MOD.materialize(split, jobs, campaign, root / "out1")
            second = MOD.materialize(split, jobs, campaign, root / "out2")
            self.assertEqual(first["archive_sha256"], second["archive_sha256"])

    def test_rejects_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            split, jobs, campaign = self.build_fixture(root)
            output = root / "out"
            output.mkdir()
            with self.assertRaisesRegex(MOD.MaterializationError, "output_exists"):
                MOD.materialize(split, jobs, campaign, output)

    def test_rejects_symlinked_open_monomer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            split, jobs, campaign = self.build_fixture(root)
            path = campaign / "inputs/candidate_monomers/CAND_000.pdb"
            target = path.with_suffix(".real.pdb")
            path.replace(target)
            path.symlink_to(target.name)
            with self.assertRaisesRegex(MOD.MaterializationError, "not_regular_or_symlink"):
                MOD.materialize(split, jobs, campaign, root / "out")

    def test_rejects_job_invariant_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            split, jobs, campaign = self.build_fixture(root)
            with jobs.open(newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
                fields = tuple(rows[0])
            rows[1]["cdr3_range"] = "4-4"
            write_tsv(jobs, fields, rows)
            with self.assertRaisesRegex(MOD.MaterializationError, "job_invariant_mismatch"):
                MOD.materialize(split, jobs, campaign, root / "out")


if __name__ == "__main__":
    unittest.main()
