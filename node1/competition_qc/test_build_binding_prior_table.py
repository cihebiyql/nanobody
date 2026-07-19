#!/usr/bin/env python3

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import build_binding_prior_table as prior


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class BindingPriorTableTests(unittest.TestCase):
    def test_missing_single_multi_and_affinity_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fasta = root / "candidates.fasta"
            fasta.write_text(">a\nACDE\n>b\nACDF\n>c\nACDG\n", encoding="utf-8")
            deepnano = root / "deepnano.csv"
            deepnano.write_text(
                "Nanobody ID,Antigen ID,Prediction\na,pvrig,0.2\nb,pvrig,0.8\n",
                encoding="utf-8",
            )
            nabp = root / "nabp.tsv"
            nabp.write_text(
                "candidate_id\tprobabilities\na\t[0.3 0.7]\n",
                encoding="utf-8",
            )
            nanobind = root / "nanobind.csv"
            nanobind.write_text(
                "pair_id,nanobody_id,antigen_id,probability,prediction\n"
                "1,a,pvrig,0.5,1\n2,c,pvrig,0.4,1\n",
                encoding="utf-8",
            )
            affinity = root / "affinity.csv"
            affinity.write_text(
                "nanobody_id,predicted_Kd_intervals\n"
                "a,\"[1e-09,2e-09] M\"\nb,\"> 0.000696 M\"\n",
                encoding="utf-8",
            )
            output = root / "priors.tsv"
            self.assertEqual(prior.main([
                str(fasta), "-o", str(output),
                "--deepnano", str(deepnano),
                "--nabp-bert", str(nabp),
                "--nanobind-seq", str(nanobind),
                "--nanobind-affinity", str(affinity),
            ]), 0)
            rows = {row["candidate_id"]: row for row in read_tsv(output)}
            self.assertEqual(rows["a"]["binding_model_count"], "3")
            self.assertAlmostEqual(float(rows["a"]["binding_prior_consensus"]), (0.2 + 0.7 + 0.5) / 3)
            self.assertAlmostEqual(float(rows["a"]["binding_model_disagreement"]), 0.5)
            self.assertEqual(rows["a"]["binding_prior_status"], "MULTI_MODEL_DISAGREEMENT")
            self.assertEqual(rows["a"]["nanobind_affinity_range"], "[1e-09,2e-09] M")
            self.assertEqual(rows["b"]["binding_model_count"], "1")
            self.assertEqual(rows["b"]["binding_prior_consensus"], "0.80000000")
            self.assertEqual(rows["b"]["binding_model_disagreement"], "")
            self.assertEqual(rows["b"]["binding_prior_status"], "SINGLE_MODEL_ONLY")
            self.assertEqual(rows["c"]["binding_prior_consensus"], "0.40000000")

    def test_affinity_only_does_not_become_probability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fasta = root / "candidates.fasta"
            fasta.write_text(">a\nACDE\n", encoding="utf-8")
            affinity = root / "affinity.csv"
            affinity.write_text(
                "nanobody_id,predicted_Kd_intervals\na,\"[1e-09,2e-09] M\"\n",
                encoding="utf-8",
            )
            output = root / "priors.tsv"
            prior.main([
                str(fasta), "-o", str(output),
                "--nanobind-affinity", str(affinity),
            ])
            row = read_tsv(output)[0]
            self.assertEqual(row["binding_model_count"], "0")
            self.assertEqual(row["binding_prior_consensus"], "")
            self.assertEqual(row["binding_prior_status"], "NO_BINDING_MODEL")
            self.assertEqual(row["nanobind_affinity_range"], "[1e-09,2e-09] M")


if __name__ == "__main__":
    unittest.main()
