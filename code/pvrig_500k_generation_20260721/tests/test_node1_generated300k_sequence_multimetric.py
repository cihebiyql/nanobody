from __future__ import annotations

import csv
import gzip
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_node1_generated300k_sequence_multimetric.py"


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def test_exact_id_normalization_and_hardpass_closure(tmp_path: Path) -> None:
    ids = ["NODE1GEN_000001_source_rfantibody", "NODE1GEN_000002_source_fixed_pose"]
    fast = tmp_path / "fast.tsv.gz"
    sapiens = tmp_path / "sapiens.tsv.gz"
    abnativ = tmp_path / "abnativ.tsv.gz"
    binding = tmp_path / "binding.tsv.gz"
    write_tsv(
        fast,
        [
            "candidate_id",
            "sequence",
            "hard_fail",
            "standard_aa_only",
            "ANARCI_status",
            "pass_similarity_filter",
            "reason_summary",
        ],
        [
            {
                "candidate_id": ids[0],
                "sequence": "ACDEFGHIK",
                "hard_fail": "False",
                "standard_aa_only": "True",
                "ANARCI_status": "True",
                "pass_similarity_filter": "PASS",
                "reason_summary": "",
            },
            {
                "candidate_id": ids[1],
                "sequence": "LMNPQRSTV",
                "hard_fail": "True",
                "standard_aa_only": "True",
                "ANARCI_status": "True",
                "pass_similarity_filter": "FAIL",
                "reason_summary": "positive_cdr_identity_ge_threshold",
            },
        ],
    )
    write_tsv(
        sapiens,
        ["seq_id", "mean_self_probability", "num_suggested_mutations"],
        [
            {
                "seq_id": ids[0],
                "mean_self_probability": "0.8",
                "num_suggested_mutations": "5",
            }
        ],
    )
    write_tsv(
        abnativ,
        ["seq_id", "AbNatiV VHH Score", "abnativ_status", "abnativ_failure_reason"],
        [
            {
                "seq_id": ids[0],
                "AbNatiV VHH Score": "0.9",
                "abnativ_status": "PASS",
                "abnativ_failure_reason": "",
            }
        ],
    )
    write_tsv(
        binding,
        [
            "candidate_id",
            "deepnano_binding_prior",
            "nanobind_binding_prior",
            "binding_model_percentile_disagreement",
        ],
        [
            {
                "candidate_id": "NODE1GEN_000001|source=rfantibody",
                "deepnano_binding_prior": "0.9",
                "nanobind_binding_prior": "0.9",
                "binding_model_percentile_disagreement": "0.1",
            },
            {
                "candidate_id": "NODE1GEN_000002|source=fixed_pose",
                "deepnano_binding_prior": "0.1",
                "nanobind_binding_prior": "0.1",
                "binding_model_percentile_disagreement": "0.1",
            },
        ],
    )
    output = tmp_path / "output"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fast-qc",
            str(fast),
            "--sapiens",
            str(sapiens),
            "--abnativ",
            str(abnativ),
            "--binding",
            str(binding),
            "--output-dir",
            str(output),
            "--expected",
            "2",
        ],
        check=True,
    )
    receipt = json.loads((output / "READY.json").read_text())
    assert receipt["status"] == "READY_FOR_PRESTRUCTURE_SELECTION"
    assert receipt["records"] == 2
    assert receipt["hardpass_records"] == 1
    with gzip.open(
        output / "node1_generated300k_sequence_multimetric.tsv.gz", "rt"
    ) as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert {row["candidate_id"] for row in rows} == set(ids)
    assert rows[0]["binding_raw_candidate_id"].startswith("NODE1GEN_000001|")
    assert sum(row["sequence_hard_gate"] == "True" for row in rows) == 1
