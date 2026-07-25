from __future__ import annotations

import csv
import gzip
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

try:
    from runs.pvrig_top7500_dualpanel_screen_v1_20260724.prepare_top200_static import (
        extract_model,
    )
    from runs.pvrig_top7500_dualpanel_screen_v1_20260724.run_top200_static import (
        static_geometry,
    )
except ModuleNotFoundError:
    from prepare_top200_static import extract_model
    from run_top200_static import static_geometry


ROOT = Path(__file__).resolve().parent


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def pdb_atom(
    serial: int,
    atom: str,
    residue: str,
    chain: str,
    index: int,
    x: float,
    y: float,
    z: float,
    element: str,
) -> str:
    return (
        f"ATOM  {serial:5d} {atom:^4s} {residue:>3s} {chain}{index:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00          {element:>2s}\n"
    )


class StaticTop80Test(unittest.TestCase):
    def test_extracts_gzipped_representative_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "job.tar.gz"
            payload = b"ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n"
            compressed = gzip.compress(payload)
            with tarfile.open(archive_path, "w:gz") as archive:
                member = tarfile.TarInfo(
                    "results/job/selected_models/cluster_1_model_1.pdb.gz"
                )
                member.size = len(compressed)
                archive.addfile(member, io.BytesIO(compressed))
            observed, member = extract_model(
                archive_path, "cluster_1_model_1.pdb"
            )
            self.assertEqual(observed, payload)
            self.assertTrue(member.endswith(".pdb.gz"))

    def test_static_geometry_labels_cdr_contacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pose.pdb"
            aa3 = [
                ("ALA", "A"), ("CYS", "C"), ("ASP", "D"), ("GLU", "E"),
                ("PHE", "F"), ("GLY", "G"), ("HIS", "H"), ("ILE", "I"),
                ("LYS", "K"),
            ]
            lines: list[str] = []
            serial = 1
            for index, (residue, _aa) in enumerate(aa3, start=1):
                for atom, element, dy in (("N", "N", 0.0), ("CA", "C", 0.4), ("O", "O", 0.8)):
                    lines.append(
                        pdb_atom(
                            serial, atom, residue, "A", index,
                            float(index * 3), dy, 0.0, element,
                        )
                    )
                    serial += 1
            for index in range(1, 10):
                for atom, element, dy in (("N", "N", 0.0), ("CA", "C", 0.4), ("O", "O", 0.8)):
                    lines.append(
                        pdb_atom(
                            serial, atom, "ALA", "T", index,
                            float(index * 3), dy, 3.0, element,
                        )
                    )
                    serial += 1
            path.write_text("".join(lines) + "END\n", encoding="ascii")
            result = static_geometry(
                path, {"cdr1": "CD", "cdr2": "FG", "cdr3": "IK"}
            )
            self.assertGreater(result["interface_residue_pairs_5a"], 0)
            self.assertGreater(result["cdr1_contact_residue_count"], 0)
            self.assertGreater(result["cdr2_contact_residue_count"], 0)
            self.assertGreater(result["cdr3_contact_residue_count"], 0)

    def test_select_top80_exact_channel_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            top_path = root / "top200.tsv"
            static_path = root / "static.tsv"
            receipt_path = root / "STATIC_COMPLETE.json"
            out = root / "out"
            channels = (
                ["CORE_EXPLOITATION"] * 120
                + ["PARENT_CDR3_DIVERSITY"] * 40
                + ["MODEL_DISAGREEMENT_RESCUE"] * 20
                + ["STRUCTURAL_RESERVE"] * 20
            )
            top_rows = []
            static_rows = []
            for index, channel in enumerate(channels):
                candidate = f"C{index:03d}"
                top_rows.append(
                    {
                        "candidate_id": candidate,
                        "sequence": "ACDEFGHIKLMNPQRSTVWY" * 6,
                        "parent_cluster": f"P{index % 20:02d}",
                        "route": "old_top7500" if index % 2 else "c2_four_seed",
                        "cdr3": "G" * (5 + index),
                        "cdr3_diversity_cluster": f"D{index:03d}",
                        "selection_channel": channel,
                        "selection_score": str(1000 - index),
                        "top200_rank": str(index + 1),
                    }
                )
                for conformation in ("8x6b", "9e6y"):
                    static_rows.append(
                        {
                            "static_job_id": f"{candidate}_{conformation}",
                            "candidate_id": candidate,
                            "conformation": conformation,
                            "interface_atom_contacts_4p5a": "100",
                            "interface_residue_pairs_5a": "20",
                            "interface_contact_density_proxy": "1",
                            "physical_clash_atom_pairs_2a": "0",
                            "hbond_donor_acceptor_distance_proxy_3p5a": "2",
                            "salt_bridge_distance_proxy_4a": "1",
                            "hydrophobic_interface_residue_pairs_5a": "3",
                            "cdr_contact_fraction": "0.8",
                            "cdr3_contact_fraction": "0.4",
                            "exposed_hydrophobic_residue_count_proxy": "2",
                            "ptm_motif_residue_exposed_count_proxy": "1",
                            "rosetta_dSASA_int": "1000",
                            "rosetta_delta_unsatHbonds": "3",
                            "rosetta_hbonds_int": "4",
                            "rosetta_sc_value": "0.6",
                            "rosetta_dG_separated": "-5",
                            "rosetta_per_residue_energy_int": "-0.2",
                            "prodigy_predicted_dg_kcal_mol": "-10",
                        }
                    )
            write_tsv(top_path, top_rows)
            write_tsv(static_path, static_rows)
            receipt_path.write_text(
                json.dumps(
                    {
                        "state": "STATIC_COMPLETE",
                        "candidates": 200,
                        "jobs": 400,
                        "method_roles": {
                            "rosetta": "DESCRIPTIVE_ONLY",
                            "prodigy": "WEAK_PRIOR_ONLY",
                            "foldx": "NOT_RUN_CROSS_CANDIDATE_RANK_REJECTED",
                        },
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "select_top80.py"),
                    "--top200", str(top_path),
                    "--static-metrics", str(static_path),
                    "--static-receipt", str(receipt_path),
                    "--out", str(out),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with (out / "top80_post_static.tsv").open(
                newline="", encoding="utf-8"
            ) as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 80)
            counts: dict[str, int] = {}
            for row in rows:
                channel = row["top80_selection_channel"]
                counts[channel] = counts.get(channel, 0) + 1
            self.assertEqual(
                counts,
                {
                    "CORE_EXPLOITATION": 48,
                    "PARENT_CDR3_DIVERSITY": 16,
                    "MODEL_DISAGREEMENT_RESCUE": 8,
                    "STRUCTURAL_RESERVE": 8,
                },
            )
            top80_receipt = json.loads(
                (out / "TOP80_COMPLETE.json").read_text(encoding="utf-8")
            )
            self.assertEqual(top80_receipt["exact_cdr3_duplicate_count"], 0)
            self.assertLess(
                top80_receipt["max_direct_pairwise_cdr3_identity"], 0.80
            )

    def test_select_final50_and_top10_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            top80_path = root / "top80.tsv"
            top80_receipt = root / "TOP80_COMPLETE.json"
            md_manifest = root / "md_manifest.tsv"
            out = root / "final"
            channels = (
                ["CORE_EXPLOITATION"] * 48
                + ["PARENT_CDR3_DIVERSITY"] * 16
                + ["MODEL_DISAGREEMENT_RESCUE"] * 8
                + ["STRUCTURAL_RESERVE"] * 8
            )
            rows = []
            for index, channel in enumerate(channels):
                rows.append(
                    {
                        "candidate_id": f"C{index:03d}",
                        "sequence": f"ACDEFGHIKLMNPQRSTVWY{index:03d}",
                        "cdr3": "G" * (5 + index),
                        "parent_cluster": f"P{index % 10:02d}",
                        "route": "old_top7500" if index % 2 else "c2_four_seed",
                        "cdr3_diversity_cluster": f"D{index:03d}",
                        "top80_selection_channel": channel,
                        "post_static_selection_score": str(1000 - index),
                    }
                )
            write_tsv(top80_path, rows)
            top80_receipt.write_text(
                json.dumps({"state": "TOP80_COMPLETE", "count": 80}),
                encoding="utf-8",
            )
            md_rows = [
                {
                    "system_id": f"MD_C{index:03d}",
                    "candidate_id": f"C{index:03d}",
                    "source_job_id": f"J{index:03d}",
                    "md_seed": str(seed),
                    "gpu": str(index % 4),
                }
                for index in range(20)
                for seed in (917, 1931, 3253)
            ]
            write_tsv(md_manifest, md_rows)
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "select_final50.py"),
                    "--top80", str(top80_path),
                    "--top80-receipt", str(top80_receipt),
                    "--md-manifest", str(md_manifest),
                    "--out", str(out),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with (out / "final50_ranked.tsv").open(
                newline="", encoding="utf-8"
            ) as handle:
                final = list(csv.DictReader(handle, delimiter="\t"))
            with (out / "top10_priority.tsv").open(
                newline="", encoding="utf-8"
            ) as handle:
                top10 = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(final), 50)
            self.assertEqual(len(top10), 10)
            preaudit = json.loads(
                (out / "FINAL50_PREAUDIT.json").read_text(encoding="utf-8")
            )
            self.assertEqual(preaudit["exact_cdr3_duplicates"], 0)
            self.assertLess(
                preaudit["max_direct_pairwise_cdr3_identity"], 0.80
            )
            self.assertLessEqual(
                max(
                    sum(row["parent_cluster"] == parent for row in final)
                    for parent in {row["parent_cluster"] for row in final}
                ),
                15,
            )
            self.assertLessEqual(
                max(
                    sum(row["route"] == route for row in final)
                    for route in {row["route"] for row in final}
                ),
                35,
            )
            final_qc = root / "final_qc.tsv"
            write_tsv(
                final_qc,
                [
                    {
                        "candidate_id": row["candidate_id"],
                        "sequence": row["sequence"],
                        "official_validator_pass": "PASS",
                        "pass_similarity_filter": "PASS",
                        "hard_fail": "false",
                        "reason_summary": "",
                    }
                    for row in final
                ],
            )
            top80_receipt_for_audit = root / "TOP80_AUDIT.json"
            top80_receipt_for_audit.write_text(
                json.dumps({"state": "TOP80_COMPLETE", "count": 80}),
                encoding="utf-8",
            )
            md_receipt = root / "MD20_ANALYSIS_COMPLETE.json"
            md_receipt.write_text(
                json.dumps({"state": "MD20_ANALYSIS_COMPLETE"}),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "audit_final50.py"),
                    "--final-root", str(out),
                    "--final-qc", str(final_qc),
                    "--top80-receipt", str(top80_receipt_for_audit),
                    "--md-receipt", str(md_receipt),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            audited = json.loads(
                (out / "FINAL50_COMPLETE.json").read_text(encoding="utf-8")
            )
            self.assertEqual(audited["state"], "FINAL50_COMPLETE")
            self.assertEqual(audited["official_validator_pass"], 50)
            self.assertTrue(
                audited["diversity_checks"][
                    "direct_pairwise_cdr3_identity_below_0p80"
                ]
            )
            self.assertLess(
                audited["max_direct_pairwise_cdr3_identity"], 0.80
            )


if __name__ == "__main__":
    unittest.main()
