#!/usr/bin/env python3
"""Check the patent success-series calibration batch status."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH_ROOT = ROOT / "docking" / "calibration" / "patent_success_validation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def exists_text(path: Path) -> str:
    return "yes" if path.exists() else "no"


def main() -> None:
    args = parse_args()
    batch_root = args.batch_root.resolve()
    manifest = batch_root / "batch_manifest.csv"
    if not manifest.exists():
        raise SystemExit(f"missing batch manifest: {manifest}")
    rows = read_rows(manifest)
    if len(rows) != 11:
        raise SystemExit(f"expected 11 calibration rows, got {len(rows)}")
    bad_boundary = [row["molecule_name"] for row in rows if "not_new_design" not in row["usage_boundary"]]
    if bad_boundary:
        raise SystemExit(f"rows missing positive-control usage boundary: {bad_boundary}")
    bad_cdr = [row["molecule_name"] for row in rows if row["cdr_exact_match_status"] != "exact"]
    if bad_cdr:
        raise SystemExit(f"rows without exact raw ANARCI CDR-to-FASTA match: {bad_cdr}")

    status_rows: list[dict[str, str]] = []
    for row in rows:
        workdir = Path(row["workdir"])
        name = row["calibration_name"]
        consensus = workdir / "reports" / f"{name}_8x6b_9e6y_consensus.csv"
        status_rows.append(
            {
                "recommended_order": row["recommended_order"],
                "molecule_name": row["molecule_name"],
                "family": row["family"],
                "workdir": str(workdir),
                "input_fasta": exists_text(workdir / "inputs" / f"{name}_vhh.fasta"),
                "cdr_ambig_tbl": exists_text(workdir / "haddock3" / "data" / f"{name}_cdr_to_pvrig_hotspot_ambig.tbl"),
                "haddock_cfg": exists_text(workdir / "haddock3" / f"{name}_pvrig_hotspot_test.cfg"),
                "node1_structure_script": exists_text(workdir / "run_node1_structure_prediction.sh"),
                "node1_haddock_script": exists_text(workdir / "run_node1_haddock3.sh"),
                "monomer_raw_pdb": exists_text(workdir / "monomer" / f"{name}_nanobodybuilder2.pdb"),
                "monomer_chainA_pdb": exists_text(workdir / "haddock3" / "data" / f"{name}_vhh_chainA.pdb"),
                "haddock_run_dir": exists_text(workdir / "haddock3" / f"run_{name}_pvrig_hotspot_test"),
                "consensus_csv": exists_text(consensus),
            }
        )

    out_csv = batch_root / "batch_status.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(status_rows[0]))
        writer.writeheader()
        writer.writerows(status_rows)

    family_counts = Counter(row["family"] for row in rows)
    monomer_count = sum(1 for row in status_rows if row["monomer_chainA_pdb"] == "yes")
    docking_count = sum(1 for row in status_rows if row["haddock_run_dir"] == "yes")
    consensus_count = sum(1 for row in status_rows if row["consensus_csv"] == "yes")
    print("OK patent success calibration batch status checked")
    print(f"manifest_rows={len(rows)}")
    print("families=" + ",".join(f"{key}:{value}" for key, value in sorted(family_counts.items())))
    print(f"prepared_workdirs={sum(1 for row in status_rows if row['haddock_cfg'] == 'yes')}")
    print(f"monomer_chainA_pdb={monomer_count}")
    print(f"haddock_run_dirs={docking_count}")
    print(f"consensus_csv={consensus_count}")
    print(f"status_csv={out_csv}")


if __name__ == "__main__":
    main()
