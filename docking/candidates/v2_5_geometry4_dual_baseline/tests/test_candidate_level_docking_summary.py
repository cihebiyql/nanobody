#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_candidate_level_docking_summary.py"
REAL_MANIFEST = ROOT / "manifests/geometry4_candidates.tsv"
REAL_BLIND_ID = "PV25-25F7D6778F87"
PDB_SEQUENCE = "ACD"
SEQ_HASH = hashlib.sha256(PDB_SEQUENCE.encode()).hexdigest()
METRICS = {
    "hotspot_overlap_count": "10",
    "total_vhh_pvrl2_residue_pair_occlusion": "400",
    "cdr3_pvrl2_residue_pair_occlusion": "80",
    "cdr3_occlusion_fraction": "0.5",
}

spec = importlib.util.spec_from_file_location("candidate_summary", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class CandidateLevelDockingSummaryTest(unittest.TestCase):
    @staticmethod
    def write_input_pdb(path: Path, sequence: str = PDB_SEQUENCE) -> None:
        aa1_to_3 = {"A": "ALA", "C": "CYS", "D": "ASP"}
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for idx, residue in enumerate(sequence, start=1):
            lines.append(
                f"ATOM  {idx:5d}  CA  {aa1_to_3[residue]:>3s} A{idx:4d}    "
                f"{float(idx):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C\n"
            )
        path.write_text("".join(lines) + "END\n", encoding="ascii")

    def make_case(
        self,
        tmp: Path,
        candidate_id: str,
        source_candidate_id: str,
        baseline_classes: list[str],
        *,
        consensus_class: str | None = None,
        seq_hash: str = SEQ_HASH,
        write_consensus: bool = True,
        write_input_pdb: bool = True,
        include_row_hashes: bool = True,
        metrics_8: dict[str, str] | None = None,
        metrics_9: dict[str, str] | None = None,
    ) -> Path:
        workdir = tmp / candidate_id
        reports = workdir / "reports"
        reports.mkdir(parents=True)
        if write_input_pdb:
            self.write_input_pdb(workdir / "data" / f"{source_candidate_id}_vhh_chainA.pdb")
        if write_consensus:
            with (reports / f"{source_candidate_id}_8x6b_9e6y_consensus.csv").open("w", newline="", encoding="utf-8") as handle:
                consensus_fields = ["model", "best_haddock_rank", "consensus_class"]
                if include_row_hashes:
                    consensus_fields.append("vhh_seq_sha256")
                writer = csv.DictWriter(
                    handle,
                    fieldnames=consensus_fields,
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "model": "cluster_1_model_2",
                        "best_haddock_rank": "2",
                        "consensus_class": "BLOCKER_PLAUSIBLE_B",
                        **({"vhh_seq_sha256": seq_hash} if include_row_hashes else {}),
                    }
                )
                writer.writerow(
                    {
                        "model": "cluster_1_model_1",
                        "best_haddock_rank": "1",
                        "consensus_class": consensus_class or "",
                        **({"vhh_seq_sha256": seq_hash} if include_row_hashes else {}),
                    }
                )
        refs = ["8x6b", "9e6y"]
        metric_rows = [metrics_8 or METRICS, metrics_9 or METRICS]
        for ref, cls, metric_row in zip(refs, baseline_classes, metric_rows):
            with (reports / f"{source_candidate_id}_{ref}_blocker_classification.csv").open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                fields = ["model", "blocker_class"]
                if include_row_hashes:
                    fields.append("vhh_seq_sha256")
                fields.extend(METRICS.keys())
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                other = {"model": "cluster_1_model_2", "blocker_class": "BLOCKER_PLAUSIBLE_B"}
                if include_row_hashes:
                    other["vhh_seq_sha256"] = seq_hash
                other.update({key: "999" for key in METRICS})
                writer.writerow(other)
                row = {"model": "cluster_1_model_1", "blocker_class": cls}
                if include_row_hashes:
                    row["vhh_seq_sha256"] = seq_hash
                row.update(metric_row)
                writer.writerow(row)
        return workdir

    def write_manifest(self, tmp: Path, rows: list[dict[str, str]]) -> Path:
        manifest = tmp / "manifest.tsv"
        fields = ["candidate_id", "source_candidate_id", "vhh_seq_sha256", "workdir", "consensus_filename"]
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for row in rows:
                full = {field: "" for field in fields}
                full.update(row)
                writer.writerow(full)
        return manifest

    def manifest_row(self, cid: str, source: str, workdir: Path, seq_hash: str = SEQ_HASH) -> dict[str, str]:
        return {
            "candidate_id": cid,
            "source_candidate_id": source,
            "vhh_seq_sha256": seq_hash,
            "workdir": str(workdir),
            "consensus_filename": f"{source}_8x6b_9e6y_consensus.csv",
        }

    def run_builder(self, manifest: Path, out_csv: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--manifest", str(manifest), "--out-csv", str(out_csv)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_aa_consensus_and_best_rank_payload_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            workdir = self.make_case(tmp, "blind_1", "src_1", ["BLOCKER_LIKE_A", "BLOCKER_LIKE_A"], consensus_class="A")
            manifest = self.write_manifest(tmp, [self.manifest_row("blind_1", "src_1", workdir)])
            out_csv = tmp / "out.csv"
            result = self.run_builder(manifest, out_csv)
            self.assertEqual(result.returncode, 0, result.stderr)
            row = read_csv(out_csv)[0]
            self.assertEqual(row["candidate_id"], "blind_1")
            self.assertEqual(row["source_candidate_id"], "src_1")
            self.assertEqual(row["blocker_class"], "CONSENSUS_BLOCKER_LIKE_A")
            self.assertEqual(row["top_model_consensus_class"], "CONSENSUS_BLOCKER_LIKE_A")
            self.assertEqual(row["top_model"], "cluster_1_model_1")
            self.assertEqual(row["baseline_count"], "2")
            self.assertEqual(row["baseline_classes"], "8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_LIKE_A")
            self.assertEqual(row["run_status"], "RUN")
            self.assertEqual(row["import_status"], "IMPORTED")
            self.assertEqual(row["evidence_boundary"], module.EVIDENCE_BOUNDARY)
            self.assertEqual(hashlib.sha256(row["payload_json"].encode()).hexdigest(), row["payload_sha256"])
            self.assertIn("src_1_8x6b_9e6y_consensus.csv", row["source_hashes_json"])
            self.assertEqual(json.loads(row["payload_json"])["candidate_id"], "blind_1")

    def test_ab_single_baseline_ac_and_missing_classifications(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            wd_ab = self.make_case(
                tmp,
                "ab",
                "src_ab",
                ["BLOCKER_LIKE_A", "BLOCKER_PLAUSIBLE_B"],
                consensus_class="SINGLE_BASELINE_BLOCKER_RECHECK",
            )
            wd_single = self.make_case(tmp, "single", "src_single", ["BLOCKER_LIKE_A"], consensus_class="A")
            wd_ac = self.make_case(
                tmp, "ac", "src_ac", ["BLOCKER_LIKE_A", "BINDER_LIKE_C"], consensus_class="DISCORDANT_REDOCK_REQUIRED"
            )
            wd_missing = self.make_case(tmp, "missing", "src_missing", [], write_consensus=False)
            manifest = self.write_manifest(
                tmp,
                [
                    self.manifest_row("ab", "src_ab", wd_ab),
                    self.manifest_row("single", "src_single", wd_single),
                    self.manifest_row("ac", "src_ac", wd_ac),
                    self.manifest_row("missing", "src_missing", wd_missing),
                ],
            )
            out_csv = tmp / "out.csv"
            result = self.run_builder(manifest, out_csv)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = {row["candidate_id"]: row for row in read_csv(out_csv)}
            self.assertEqual(rows["ab"]["blocker_class"], "SINGLE_BASELINE_BLOCKER_RECHECK")
            self.assertEqual(rows["single"]["blocker_class"], "INCOMPLETE")
            self.assertEqual(rows["single"]["baseline_count"], "0")
            self.assertEqual(rows["ac"]["blocker_class"], "DISCORDANT_REDOCK_REQUIRED")
            self.assertEqual(rows["missing"]["blocker_class"], "INCOMPLETE")
            self.assertEqual(rows["missing"]["run_status"], "NOT_RUN")
            self.assertEqual(rows["missing"]["import_status"], "INCOMPLETE")

    def test_recheck_baseline_labels_never_collapse_to_a(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            workdir = self.make_case(
                tmp,
                "stale_recheck",
                "src_stale_recheck",
                ["SINGLE_BASELINE_BLOCKER_RECHECK", "SINGLE_BASELINE_BLOCKER_RECHECK"],
                consensus_class="CONSENSUS_BLOCKER_LIKE_A",
            )
            manifest = self.write_manifest(
                tmp, [self.manifest_row("stale_recheck", "src_stale_recheck", workdir)]
            )
            result = self.run_builder(manifest, tmp / "out.csv")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported baseline class", result.stderr)

    def test_real_input_pdb_binds_hashless_source_rows_to_manifest_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bound = self.make_case(
                tmp,
                "bound",
                "src_bound",
                ["BLOCKER_LIKE_A", "BLOCKER_LIKE_A"],
                consensus_class="CONSENSUS_BLOCKER_LIKE_A",
                include_row_hashes=False,
            )
            unbound = self.make_case(
                tmp,
                "unbound",
                "src_unbound",
                ["BLOCKER_LIKE_A", "BLOCKER_LIKE_A"],
                consensus_class="CONSENSUS_BLOCKER_LIKE_A",
                include_row_hashes=False,
                write_input_pdb=False,
            )
            manifest = self.write_manifest(
                tmp,
                [
                    self.manifest_row("bound", "src_bound", bound),
                    self.manifest_row("unbound", "src_unbound", unbound),
                ],
            )
            out_csv = tmp / "out.csv"
            result = self.run_builder(manifest, out_csv)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = {row["candidate_id"]: row for row in read_csv(out_csv)}
            self.assertEqual(rows["bound"]["import_status"], "IMPORTED")
            bound_hashes = json.loads(rows["bound"]["source_hashes_json"])
            self.assertEqual(bound_hashes["input_vhh_sequence_sha256"], SEQ_HASH)
            self.assertEqual(rows["unbound"]["import_status"], "INCOMPLETE")
            self.assertIn("missing sequence-bound VHH input PDB", rows["unbound"]["payload_json"])

    def test_conservative_metrics_take_min_and_preserve_per_reference(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            metrics_8 = {
                "hotspot_overlap_count": "12",
                "total_vhh_pvrl2_residue_pair_occlusion": "500",
                "cdr3_pvrl2_residue_pair_occlusion": "90",
                "cdr3_occlusion_fraction": "0.6",
            }
            metrics_9 = {
                "hotspot_overlap_count": "9",
                "total_vhh_pvrl2_residue_pair_occlusion": "300",
                "cdr3_pvrl2_residue_pair_occlusion": "70",
                "cdr3_occlusion_fraction": "0.7",
            }
            workdir = self.make_case(
                tmp,
                "metric",
                "src_metric",
                ["BLOCKER_PLAUSIBLE_B", "BLOCKER_PLAUSIBLE_B"],
                consensus_class="B",
                metrics_8=metrics_8,
                metrics_9=metrics_9,
            )
            manifest = self.write_manifest(tmp, [self.manifest_row("metric", "src_metric", workdir)])
            out_csv = tmp / "out.csv"
            result = self.run_builder(manifest, out_csv)
            self.assertEqual(result.returncode, 0, result.stderr)
            row = read_csv(out_csv)[0]
            self.assertEqual(row["blocker_class"], "BLOCKER_PLAUSIBLE_B")
            self.assertEqual(row["hotspot_overlap_count"], "9")
            self.assertEqual(row["total_vhh_pvrl2_residue_pair_occlusion"], "300")
            self.assertEqual(row["cdr3_pvrl2_residue_pair_occlusion"], "70")
            self.assertEqual(row["cdr3_occlusion_fraction"], "0.6")
            self.assertEqual(row["top_8x6b_cdr3_occlusion_fraction"], "0.6")
            self.assertEqual(row["top_9e6y_total_vhh_pvrl2_residue_pair_occlusion"], "300")

    def test_real_zym_test_108006_manifest_integration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_csv = Path(td) / "geometry4_summary.csv"
            result = self.run_builder(REAL_MANIFEST, out_csv)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = {row["candidate_id"]: row for row in read_csv(out_csv)}
            row = rows[REAL_BLIND_ID]
            self.assertEqual(row["source_candidate_id"], "zym_test_108006")
            self.assertEqual(row["blocker_class"], "CONSENSUS_BLOCKER_LIKE_A")
            self.assertEqual(row["top_model"], "cluster_1_model_1")
            self.assertEqual(row["baseline_classes"], "8x6b:BLOCKER_LIKE_A;9e6y:BLOCKER_LIKE_A")
            self.assertEqual(row["hotspot_overlap_count"], "15")
            self.assertEqual(row["total_vhh_pvrl2_residue_pair_occlusion"], "610")
            self.assertEqual(row["cdr3_pvrl2_residue_pair_occlusion"], "106")
            self.assertEqual(row["cdr3_occlusion_fraction"], "0.17377")
            self.assertEqual(hashlib.sha256(row["payload_json"].encode()).hexdigest(), row["payload_sha256"])

    def test_rejects_duplicate_candidate_bad_hash_hash_mismatch_and_class_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            workdir = self.make_case(tmp, "dup", "src_dup", ["BINDER_LIKE_C", "BINDER_LIKE_C"], consensus_class="C")
            dup_manifest = self.write_manifest(
                tmp,
                [
                    self.manifest_row("dup", "src_dup", workdir),
                    self.manifest_row("dup", "src_dup", workdir),
                ],
            )
            result = self.run_builder(dup_manifest, tmp / "dup.csv")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate candidate_id", result.stderr)

            bad_hash_manifest = self.write_manifest(
                tmp,
                [self.manifest_row("bad_hash", "src_dup", workdir, seq_hash="ABC")],
            )
            result = self.run_builder(bad_hash_manifest, tmp / "bad_hash.csv")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sha256", result.stderr)

            mismatch_workdir = self.make_case(
                tmp, "hm", "src_hm", ["BLOCKER_LIKE_A", "BLOCKER_LIKE_A"], consensus_class="A", seq_hash="b" * 64
            )
            mismatch_manifest = self.write_manifest(tmp, [self.manifest_row("hm", "src_hm", mismatch_workdir)])
            result = self.run_builder(mismatch_manifest, tmp / "hm.csv")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hash mismatch", result.stderr)

            class_workdir = self.make_case(tmp, "cm", "src_cm", ["BLOCKER_LIKE_A", "BLOCKER_LIKE_A"], consensus_class="C")
            class_manifest = self.write_manifest(tmp, [self.manifest_row("cm", "src_cm", class_workdir)])
            result = self.run_builder(class_manifest, tmp / "cm.csv")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("consensus and baseline class disagree", result.stderr)


if __name__ == "__main__":
    unittest.main()
