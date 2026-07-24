#!/usr/bin/env python3

import csv
import gzip
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from build_top5000_dualreceptor_4seed_handoff_v1 import (
    CONFORMATIONS,
    EXPECTED_CFG_HASHES,
    EXPECTED_PROTOCOL_CORE_SHA256,
    JOB_HASH_BOUND_FIELDS,
    SEEDS,
    build_handoff,
    calculate_cfg_hashes,
    canonical_json,
    sha256_file,
    sha256_text,
    validate_job_hash_binding,
)


AA3 = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "K": "LYS",
    "L": "LEU",
    "M": "MET",
    "N": "ASN",
    "P": "PRO",
    "Q": "GLN",
    "R": "ARG",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
    "Y": "TYR",
}
ANCHORS = [71, 74, 82, 87, 92, 96, 98, 135, 138, 140, 142, 144]
ALPHABET = "ACDEFGHIKLMNPQRSTVWY"


def protocol() -> dict:
    return {
        "status": "HANDOFF_LOCKED",
        "docking": {
            "ncores": 4,
            "sampling": 40,
            "seletop_select": 10,
            "seletopclusts_top_models": 4,
            "rigidbody_tolerance": 5,
            "flexref_tolerance": 10,
            "randremoval": True,
            "npart": 2,
        },
        "references": {
            "conformations": {
                "8x6b": {
                    "normalized_receptor_pdb": (
                        "inputs/normalized/8x6b_pvrig_receptor.pdb"
                    )
                },
                "9e6y": {
                    "normalized_receptor_pdb": (
                        "inputs/normalized/9e6y_pvrig_receptor.pdb"
                    )
                },
            },
            "receptor_chain": "T",
            "ligand_chain": "L",
            "numbering": "UniProt_Q6DKI7",
        },
    }


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def write_gzip_tsv(
    path: Path, fields: list[str], rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def pdb_line(serial: int, aa: str, residue: int) -> str:
    line = (
        f"ATOM  {serial:5d}  CA  {AA3[aa]:>3s} H{residue:4d} "
        f"   {float(serial):8.3f}{0.0:8.3f}{0.0:8.3f}"
        "  1.00 20.00           C"
    )
    assert line[17:20] == AA3[aa]
    assert line[21] == "H"
    return line


def pdb_bytes(sequence: str) -> bytes:
    lines = [
        pdb_line(index, aa, 100 + index)
        for index, aa in enumerate(sequence, 1)
    ]
    return ("\n".join(lines) + "\nTER\nEND\n").encode("ascii")


class Top5000HandoffBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.template = self.root / "template"
        self.release_tsv = self.root / "TOP5000_RELEASE.tsv"
        self.release_fasta = self.root / "TOP5000_RELEASE.fasta"
        self.shortlist = self.root / "SHORTLIST100K.tsv.gz"
        self.manifest = self.root / "NBB2_MANIFEST.tsv.gz"
        self.output = self.root / "handoff"
        self.archives: list[Path] = []
        self._write_template()
        self._write_inputs()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_template(self) -> None:
        self.template.mkdir()
        files: dict[str, bytes] = {
            "config/protocol_spec.json": (
                json.dumps(protocol(), indent=2, sort_keys=True) + "\n"
            ).encode(),
            "config/blocker_judgment_rules_v2.json": b"{}\n",
            "inputs/normalized/8x6b_pvrig_receptor.pdb": (
                b"ATOM      1  CA  ALA T  71       0.000   0.000   0.000"
                b"  1.00 20.00           C\n"
            ),
            "inputs/normalized/9e6y_pvrig_receptor.pdb": (
                b"ATOM      1  CA  ALA T  71       0.000   0.000   0.000"
                b"  1.00 20.00           C\n"
            ),
            "inputs/normalized/8x6b_TL_reference.pdb": b"synthetic\n",
            "inputs/normalized/9e6y_TL_reference.pdb": b"synthetic\n",
            "scripts/common.py": b"# synthetic common\n",
            "scripts/build_docking_jobs.py": b"# synthetic builder\n",
            "scripts/run_job.py": b"# synthetic runner\n",
            "scripts/score_pose.py": b"# synthetic scorer\n",
        }
        hotspot_lines = ["uniprot_position\trestraint_role"] + [
            f"{position}\tAIR_ANCHOR" for position in ANCHORS
        ]
        files["inputs/normalized/interface_hotspots_uniprot.tsv"] = (
            "\n".join(hotspot_lines) + "\n"
        ).encode()
        lock_rows = []
        for relative, content in files.items():
            path = self.template / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            lock_rows.append(
                {
                    "path": relative,
                    "bytes": len(content),
                    "sha256": sha256_text(content.decode("ascii")),
                }
            )
        lock = {
            "status": "CORE_LOCKED",
            "protocol_core_sha256": EXPECTED_PROTOCOL_CORE_SHA256,
            "files": lock_rows,
        }
        (self.template / "PROTOCOL_CORE_LOCK.json").write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        portable_files = {
            "scripts/validate_protocol.py": b"# synthetic validator\n",
            "scripts/aggregate_external_candidate_results.py": (
                b"# synthetic candidate aggregator\n"
            ),
            "scripts/aggregate_results.py": b"# synthetic legacy aggregator\n",
            "scripts/status.py": b"# synthetic status\n",
            "inputs/source/8X6B.pdb": b"synthetic 8X6B source\n",
            "inputs/source/9E6Y.pdb": b"synthetic 9E6Y source\n",
            "inputs/source/PVRIG_hotspot_set_v1.csv": (
                b"position,role\n71,AIR_ANCHOR\n"
            ),
        }
        for relative, content in portable_files.items():
            path = self.template / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def _write_inputs(self) -> None:
        release_rows: list[dict[str, str]] = []
        shortlist_rows: list[dict[str, str]] = []
        manifest_rows: list[dict[str, str]] = []
        fasta_lines: list[str] = []
        for index in range(8):
            candidate_id = f"CAND_{index:02d}"
            sequence = ALPHABET[index:] + ALPHABET[:index]
            cdr1 = sequence[2:5]
            cdr2 = sequence[7:10]
            cdr3 = sequence[13:18]
            sequence_hash = sha256_text(sequence)
            release_rows.append(
                {
                    "release_rank": str(index + 1),
                    "candidate_id": candidate_id,
                    "sequence": sequence,
                    "sequence_sha256": sequence_hash,
                }
            )
            fasta_lines.extend([f">{candidate_id}", sequence])
            shortlist_rows.append(
                {
                    "candidate_id": candidate_id,
                    "sequence": sequence,
                    "IMGT_CDR1": cdr1,
                    "IMGT_CDR2": cdr2,
                    "IMGT_CDR3": cdr3,
                    "unused_metric": str(index / 10),
                }
            )
            content = pdb_bytes(sequence)
            pdb_hash = sha256_text(content.decode("ascii"))
            pdb_name = f"{candidate_id}.pdb"
            manifest_rows.append(
                {
                    "candidate_id": candidate_id,
                    "sequence_sha256": sequence_hash,
                    "structure_model": "NanoBodyBuilder2",
                    "structure_model_version": "ImmuneBuilder-1.2",
                    "pdb_relative_path": pdb_name,
                    "pdb_sha256": pdb_hash,
                    "pdb_bytes": str(len(content)),
                    "pdb_sequence_match": "true",
                    "status": "SUCCESS",
                }
            )
            archive_path = self.root / f"node_{index:03d}.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo(
                    f"node_{index:03d}/raw/worker_00/{pdb_name}"
                )
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            self.archives.append(archive_path)
        write_tsv(
            self.release_tsv,
            ["release_rank", "candidate_id", "sequence", "sequence_sha256"],
            release_rows,
        )
        self.release_fasta.write_text(
            "\n".join(fasta_lines) + "\n", encoding="utf-8"
        )
        write_gzip_tsv(
            self.shortlist,
            [
                "candidate_id",
                "sequence",
                "IMGT_CDR1",
                "IMGT_CDR2",
                "IMGT_CDR3",
                "unused_metric",
            ],
            shortlist_rows,
        )
        write_gzip_tsv(
            self.manifest,
            [
                "candidate_id",
                "sequence_sha256",
                "structure_model",
                "structure_model_version",
                "pdb_relative_path",
                "pdb_sha256",
                "pdb_bytes",
                "pdb_sequence_match",
                "status",
            ],
            manifest_rows,
        )

    def build(self) -> dict:
        return build_handoff(
            self.release_tsv,
            self.release_fasta,
            self.shortlist,
            self.manifest,
            self.archives,
            self.template,
            self.output,
            "2026-07-24T12:00:00+08:00",
            expected_candidates=8,
            expected_shortlist_rows=8,
            shard_count=8,
            production=False,
        )

    def test_frozen_four_seed_cfg_hashes(self) -> None:
        self.assertEqual(calculate_cfg_hashes(protocol()), EXPECTED_CFG_HASHES)

    def test_synthetic_build_has_exact_balanced_closure(self) -> None:
        receipt = self.build()
        self.assertEqual(receipt["status"], "SYNTHETIC_TEST_ONLY_PASS")
        self.assertFalse(receipt["docking_started"])
        self.assertEqual(receipt["counts"]["candidates"], 8)
        self.assertEqual(receipt["counts"]["materialized_pdbs"], 8)
        self.assertEqual(receipt["counts"]["jobs"], 64)
        self.assertEqual(receipt["counts"]["jobs_per_shard"], [8] * 8)
        portable_support = receipt["portable_support"]["copied"]
        self.assertEqual(
            {row["path"] for row in portable_support},
            {
                "scripts/validate_protocol.py",
                "scripts/aggregate_external_candidate_results.py",
                "scripts/aggregate_results.py",
                "scripts/status.py",
                "inputs/source/8X6B.pdb",
                "inputs/source/9E6Y.pdb",
                "inputs/source/PVRIG_hotspot_set_v1.csv",
            },
        )
        for row in portable_support:
            copied_path = self.output / row["path"]
            self.assertTrue(copied_path.is_file())
            self.assertFalse(copied_path.is_symlink())
            self.assertEqual(sha256_file(copied_path), row["sha256"])
        self.assertTrue(
            receipt["invariants"]["portable_support_required_present"]
        )
        self.assertEqual(
            receipt["invariants"]["portable_support_sha256"],
            {row["path"]: row["sha256"] for row in portable_support},
        )
        self.assertEqual(
            len(list((self.output / "inputs/candidate_monomers").glob("*.pdb"))),
            8,
        )

        candidates = read_tsv(self.output / "inputs/top5000_candidates.tsv")
        self.assertEqual(candidates[0]["cdr1_range"], "3-5")
        self.assertEqual(candidates[0]["cdr2_range"], "8-10")
        self.assertEqual(candidates[0]["cdr3_range"], "14-18")
        self.assertEqual(candidates[0]["cdr1_pdb_residues"], "103,104,105")
        self.assertEqual(
            candidates[0]["cdr3_pdb_residues"], "114,115,116,117,118"
        )

        jobs = read_tsv(self.output / "manifests/docking_jobs.tsv")
        self.assertEqual(len(jobs), 64)
        self.assertEqual(len({row["job_id"] for row in jobs}), 64)
        self.assertEqual(len({row["job_hash"] for row in jobs}), 64)
        matrix = {
            (row["seed"], row["conformation"]) for row in jobs
        }
        self.assertEqual(
            matrix,
            {
                (str(seed), conformation)
                for seed in SEEDS
                for conformation in CONFORMATIONS
            },
        )
        for job in jobs:
            validate_job_hash_binding(job)
            basis = json.loads(job["job_hash_basis"])
            self.assertEqual(set(basis), set(JOB_HASH_BOUND_FIELDS))

        shard_hashes: list[str] = []
        for index in range(8):
            shard = read_tsv(
                self.output
                / f"manifests/shards_exact_8/shard_{index:02d}.tsv"
            )
            self.assertEqual(len(shard), 8)
            self.assertEqual(len({row["entity_id"] for row in shard}), 1)
            self.assertEqual(
                {
                    (row["seed"], row["conformation"]) for row in shard
                },
                matrix,
            )
            shard_hashes.extend(row["job_hash"] for row in shard)
        self.assertEqual(len(shard_hashes), len(set(shard_hashes)))
        self.assertEqual(
            set(shard_hashes), {row["job_hash"] for row in jobs}
        )

        shard_receipt = json.loads(
            (
                self.output
                / "manifests/shards_exact_8/SHARD_RECEIPT.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            shard_receipt["status"], "PASS_EXACT_CLOSURE_BALANCED"
        )
        self.assertTrue(shard_receipt["exact_hash_set_closure"])
        ready = json.loads(
            (self.output / "READY.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ready["jobs"], 64)
        self.assertEqual(
            ready["handoff_receipt_sha256"],
            sha256_file(self.output / "HANDOFF_RECEIPT.json"),
        )
        for line in (self.output / "SHA256SUMS").read_text(
            encoding="utf-8"
        ).splitlines():
            expected, relative = line.split("  ", 1)
            self.assertEqual(sha256_file(self.output / relative), expected)

    def test_complete_job_hash_rejects_bound_field_mutation(self) -> None:
        self.build()
        job = read_tsv(self.output / "manifests/docking_jobs.tsv")[0]
        validate_job_hash_binding(job)
        job["priority"] = "999"
        with self.assertRaisesRegex(ValueError, "job_hash_basis mismatch"):
            validate_job_hash_binding(job)

    def test_rejects_imgt_cdr_that_is_not_a_unique_substring(self) -> None:
        with gzip.open(
            self.shortlist, "rt", encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        rows[0]["IMGT_CDR1"] = "AA"
        write_gzip_tsv(self.shortlist, fields, rows)
        with self.assertRaisesRegex(ValueError, "must occur exactly once"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_archive_pdb_not_matching_manifest_hash(self) -> None:
        with gzip.open(
            self.manifest, "rt", encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        rows[0]["pdb_sha256"] = "0" * 64
        write_gzip_tsv(self.manifest, fields, rows)
        with self.assertRaisesRegex(ValueError, "archive PDB hash mismatch"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_pdb_chain_h_sequence_mismatch_after_hash_passes(self) -> None:
        wrong_sequence = "C" + ALPHABET[1:]
        content = pdb_bytes(wrong_sequence)
        archive_path = self.archives[0]
        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo(
                "node_000/raw/worker_00/CAND_00.pdb"
            )
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        with gzip.open(
            self.manifest, "rt", encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        rows[0]["pdb_sha256"] = sha256_text(content.decode("ascii"))
        rows[0]["pdb_bytes"] = str(len(content))
        write_gzip_tsv(self.manifest, fields, rows)
        with self.assertRaisesRegex(ValueError, "chain H sequence mismatch"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_production_rejects_missing_validate_protocol_support(self) -> None:
        (
            self.template / "scripts/validate_protocol.py"
        ).unlink()
        with self.assertRaisesRegex(
            ValueError, "required portable support is missing.*validate_protocol"
        ):
            build_handoff(
                self.release_tsv,
                self.release_fasta,
                self.shortlist,
                self.manifest,
                self.archives,
                self.template,
                self.output,
                "2026-07-24T12:00:00+08:00",
                production=True,
            )
        self.assertFalse(self.output.exists())

    def test_production_rejects_missing_external_aggregator_support(self) -> None:
        (
            self.template
            / "scripts/aggregate_external_candidate_results.py"
        ).unlink()
        with self.assertRaisesRegex(
            ValueError,
            "required portable support is missing.*"
            "aggregate_external_candidate_results",
        ):
            build_handoff(
                self.release_tsv,
                self.release_fasta,
                self.shortlist,
                self.manifest,
                self.archives,
                self.template,
                self.output,
                "2026-07-24T12:00:00+08:00",
                production=True,
            )
        self.assertFalse(self.output.exists())

    def test_job_basis_is_canonical_json(self) -> None:
        self.build()
        job = read_tsv(self.output / "manifests/docking_jobs.tsv")[0]
        basis = {
            field: job[field] for field in JOB_HASH_BOUND_FIELDS
        }
        self.assertEqual(job["job_hash_basis"], canonical_json(basis))
        self.assertEqual(job["job_hash"], sha256_text(canonical_json(basis)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
