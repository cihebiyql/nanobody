#!/usr/bin/env python3
"""End-to-end tests for the resumable large-scale cascade runner."""

from __future__ import annotations

import csv
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

import vhh_large_scale_screen as cascade


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or not path.stat().st_size:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class LargeScaleCascadeTests(unittest.TestCase):
    def test_load_summary_aggregates_raw_dual_receptor_multiseed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "job_results.tsv"
            fields = [
                "entity_id",
                "state",
                "conformation",
                "seed",
                "representative_pair_label",
                "model_pair_consensus_fraction",
                "model_native_cross_support_agreement_fraction",
                "native_hotspot_overlap",
                "cross_hotspot_overlap",
                "native_total_occlusion",
                "cross_total_occlusion",
                "native_cdr3_occlusion",
                "cross_cdr3_occlusion",
                "native_cdr3_fraction",
                "cross_cdr3_fraction",
            ]
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
                writer.writeheader()
                for conformation in ("8x6b", "9e6y"):
                    for seed in ("42", "3047"):
                        writer.writerow(
                            {
                                "entity_id": "candidate_a",
                                "state": "SUCCESS",
                                "conformation": conformation,
                                "seed": seed,
                                "representative_pair_label": "STRICT_A",
                                "model_pair_consensus_fraction": "0.8",
                                "model_native_cross_support_agreement_fraction": "1.0",
                                "native_hotspot_overlap": "16",
                                "cross_hotspot_overlap": "15",
                                "native_total_occlusion": "620",
                                "cross_total_occlusion": "580",
                                "native_cdr3_occlusion": "140",
                                "cross_cdr3_occlusion": "120",
                                "native_cdr3_fraction": "0.22",
                                "cross_cdr3_fraction": "0.19",
                            }
                        )
            summary = cascade.load_summary(path)["candidate_a"]
        self.assertEqual(summary["blocker_class"], "CONSENSUS_BLOCKER_LIKE_A")
        self.assertEqual(summary["minimum_successful_seeds_per_conformation"], "2")
        self.assertEqual(summary["docking_evidence_status"], "MULTISEED_DUAL_REFERENCE")

    def make_fake_qc(self, root: Path) -> Path:
        script = root / "fake_qc.py"
        script.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import argparse
                import csv
                from pathlib import Path

                parser = argparse.ArgumentParser(add_help=False)
                parser.add_argument("fasta")
                parser.add_argument("-o", "--outdir", required=True)
                args, _ = parser.parse_known_args()

                records = []
                name = None
                parts = []
                for raw in Path(args.fasta).read_text().splitlines():
                    if raw.startswith(">"):
                        if name is not None:
                            records.append((name, "".join(parts)))
                        name = raw[1:].split()[0]
                        parts = []
                    elif raw.strip():
                        parts.append(raw.strip())
                if name is not None:
                    records.append((name, "".join(parts)))

                out = Path(args.outdir)
                out.mkdir(parents=True, exist_ok=True)
                fields = [
                    "candidate_id", "sequence", "hard_fail", "recommendation",
                    "reason_summary", "final_score", "initial_screen_proxy_score",
                    "IMGT_CDR1", "IMGT_CDR2", "IMGT_CDR3",
                ]
                with (out / "portfolio_ranked.tsv").open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\\t")
                    writer.writeheader()
                    for index, (record_id, sequence) in enumerate(records):
                        rejected = "reject" in record_id
                        writer.writerow({
                            "candidate_id": record_id,
                            "sequence": sequence,
                            "hard_fail": str(rejected),
                            "recommendation": "REJECT_HARD_GATE" if rejected else "SUBMIT_CANDIDATE",
                            "reason_summary": "synthetic_reject" if rejected else "",
                            "final_score": str(90 - index),
                            "initial_screen_proxy_score": str(80 - index),
                            "IMGT_CDR1": "ABCDEFGH",
                            "IMGT_CDR2": "ABCDEFG",
                            "IMGT_CDR3": "ABCDEFGHIJKLMN",
                        })
                """
            ),
            encoding="utf-8",
        )
        script.chmod(0o755)
        return script

    def test_full_cascade_deduplicates_resumes_and_requires_consensus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_qc = self.make_fake_qc(root)
            fasta = root / "input.fasta"
            fasta.write_text(
                ">a\nACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWY\n"
                ">dup\nACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWY\n"
                ">reject_b\nCDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYA\n"
                ">bad\nXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n"
                ">c\nDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYAC\n"
                ">d\nEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACDEFGHIKLMNPQRSTVWYACD\n",
                encoding="utf-8",
            )
            docking = root / "docking.csv"
            docking.write_text(
                "candidate_id,blocker_class\n"
                "a,CONSENSUS_BLOCKER_LIKE_A\n",
                encoding="utf-8",
            )
            out = root / "run"
            argv = [
                str(fasta),
                "-o",
                str(out),
                "--qc-bin",
                str(fake_qc),
                "--local-positive-cdr-csv",
                str(root / "missing.csv"),
                "--fast-chunk-size",
                "2",
                "--full-chunk-size",
                "2",
                "--full-qc-limit",
                "2",
                "--geometry-limit",
                "1",
                "--skip-final-diversity",
                "--docking-summary",
                str(docking),
            ]
            self.assertEqual(cascade.main(argv), 0)

            manifest = json.loads((out / "cascade_manifest.json").read_text())
            self.assertEqual(manifest["input_records"], 6)
            self.assertEqual(manifest["unique_ready"], 4)
            self.assertEqual(manifest["duplicates"], 1)
            self.assertEqual(manifest["quick_rejects"], 1)
            self.assertEqual(len(read_tsv(out / "fast_merged.tsv")), 4)
            self.assertEqual(len(read_tsv(out / "full_qc_shortlist.tsv")), 2)
            self.assertEqual(len(read_tsv(out / "full_qc_excluded_due_cap.tsv")), 1)
            final = read_tsv(out / "final_blocker_screen.tsv")
            self.assertEqual(len(final), 1)
            self.assertEqual(final[0]["candidate_id"], "a")
            self.assertEqual(final[0]["final_blocker_label"], "FINAL_POSITIVE_HIGH")
            self.assertEqual(len(read_tsv(out / "input_map.tsv")), 6)

            self.assertEqual(cascade.main(argv), 0)
            fast_status = read_tsv(out / "fast_chunk_status.tsv")
            full_status = read_tsv(out / "full_chunk_status.tsv")
            self.assertTrue(all(row["status"] == "reused" for row in fast_status))
            self.assertTrue(all(row["status"] == "reused" for row in full_status))

    def test_full_stage_defers_tnp_by_default(self) -> None:
        args = cascade.parse_args(["input.fasta", "-o", "run"])
        command = cascade.build_qc_command(
            args,
            Path("chunk/input.fasta"),
            Path("chunk/qc_out"),
            fast=False,
        )
        self.assertIn("--skip-tnp", command)
        args_with_tnp = cascade.parse_args(["input.fasta", "-o", "run", "--full-run-tnp"])
        command_with_tnp = cascade.build_qc_command(
            args_with_tnp,
            Path("chunk/input.fasta"),
            Path("chunk/qc_out"),
            fast=False,
        )
        self.assertNotIn("--skip-tnp", command_with_tnp)

    def test_binding_prior_columns_are_preserved_without_changing_hard_gate(self) -> None:
        rows = [
            {"candidate_id": "hard", "hard_fail": "True", "final_score": "99"},
            {"candidate_id": "pass", "hard_fail": "False", "final_score": "50"},
        ]
        summary = {
            "hard": {
                "binding_prior_consensus": "0.99",
                "deepnano_binding_prior": "0.98",
                "nanobind_binding_prior": "1.0",
                "binding_model_count": "2",
                "binding_model_disagreement": "0.02",
                "binding_prior_status": "MULTI_MODEL_CONSENSUS",
                "binding_prior_source": "DeepNano;NanoBind-seq",
            },
            "pass": {
                "binding_prior_consensus": "0.40",
                "nanobind_affinity_range": "[1e-09,2e-09] M",
                "binding_model_count": "1",
                "binding_prior_status": "SINGLE_MODEL_ONLY",
                "binding_prior_source": "DeepNano",
            },
        }
        cascade.annotate_binder(rows, summary)
        self.assertEqual(rows[0]["external_binder_score"], "99.000000")
        self.assertEqual(rows[1]["external_binder_score"], "40.000000")
        rows.sort(key=cascade.merged_sort_key)
        self.assertEqual(rows[0]["candidate_id"], "pass")
        self.assertEqual(rows[1]["candidate_id"], "hard")
        self.assertEqual(rows[0]["nanobind_affinity_range"], "[1e-09,2e-09] M")
        self.assertEqual(rows[1]["deepnano_binding_prior"], "0.98")
        self.assertEqual(rows[1]["hard_fail"], "True")


if __name__ == "__main__":
    unittest.main()
