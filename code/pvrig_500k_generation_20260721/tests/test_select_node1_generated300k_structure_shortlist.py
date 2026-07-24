from __future__ import annotations

import csv
import gzip
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/select_node1_generated300k_structure_shortlist.py"


def test_route_balance_and_disjoint_reserve(tmp_path: Path) -> None:
    source = tmp_path / "input.tsv.gz"
    fields = [
        "candidate_id",
        "sequence",
        "sequence_hard_gate",
        "IMGT_CDR3",
        "developability_score",
        "expression_purity_risk_score",
        "sapiens_mean_self_probability",
        "abnativ_AbNatiV VHH Score",
        "abnativ_abnativ_status",
        "deepnano_binding_prior",
        "nanobind_binding_prior",
        "novelty_score",
        "binding_model_percentile_disagreement",
    ]
    rows = []
    for route_name in ["rfantibody", "fixed_pose_mpnn"]:
        for index in range(40):
            rows.append(
                {
                    "candidate_id": f"C{index:03d}_source_{route_name}",
                    "sequence": "EVQLVESGGGLVQPGGSLRLSCAAS" + f"{index:03d}",
                    "sequence_hard_gate": "True",
                    "IMGT_CDR3": f"CAR{index:03d}Y",
                    "developability_score": str(index + 1),
                    "expression_purity_risk_score": str(index + 1),
                    "sapiens_mean_self_probability": str(index + 1),
                    "abnativ_AbNatiV VHH Score": str(index + 1),
                    "abnativ_abnativ_status": "PASS",
                    "deepnano_binding_prior": str(index + 1),
                    "nanobind_binding_prior": str(index + 1),
                    "novelty_score": str(index + 1),
                    "binding_model_percentile_disagreement": str(40 - index),
                }
            )
    with gzip.open(source, "wt", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / "output"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(source),
            "--output-dir",
            str(output),
            "--expected",
            "80",
            "--main",
            "40",
            "--reserve",
            "20",
        ],
        check=True,
    )
    ready = json.loads((output / "READY.json").read_text())
    assert ready["main_route_counts"] == {
        "fixed_pose_mpnn": 20,
        "rfantibody": 20,
    }
    assert ready["reserve_route_counts"] == {
        "fixed_pose_mpnn": 10,
        "rfantibody": 10,
    }
    with gzip.open(output / "STRUCTURE_PRIMARY_100K.tsv.gz", "rt") as handle:
        main = {row["candidate_id"] for row in csv.DictReader(handle, delimiter="\t")}
    with gzip.open(output / "STRUCTURE_RESERVE_20K.tsv.gz", "rt") as handle:
        reserve = {
            row["candidate_id"] for row in csv.DictReader(handle, delimiter="\t")
        }
    assert len(main) == 40
    assert len(reserve) == 20
    assert main.isdisjoint(reserve)
