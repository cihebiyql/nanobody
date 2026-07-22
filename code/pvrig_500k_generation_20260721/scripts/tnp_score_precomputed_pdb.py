#!/usr/bin/env python3
"""Score an IMGT-numbered VHH PDB with the structure-dependent TNP metrics.

This adapter deliberately reuses a precomputed NanoBodyBuilder2 model.  The
upstream TNP CLI currently exposes sequence input and would otherwise rebuild
the same monomer.  CDR lengths are supplied from the frozen ANARCI/IMGT table;
PSH/PPC/PNC and CDR3 compactness are calculated by the official TNP code.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


def assign_flag(metric: str, value: float) -> str:
    """Apply the thresholds in the official TNP ``bin/TNP`` entry point."""
    if not math.isfinite(value):
        return "NA"
    if metric == "L":
        if value < 20 or value > 39:
            return "red"
        if 20 <= value <= 24 or 37 <= value <= 39:
            return "amber"
        return "green"
    if metric == "L3":
        if value < 5 or value > 23:
            return "red"
        if 5 <= value <= 8 or 21 <= value <= 23:
            return "amber"
        return "green"
    if metric == "C":
        if value < 0.56 or value > 1.61:
            return "red"
        if 0.56 <= value <= 0.81 or 1.57 <= value <= 1.61:
            return "amber"
        return "green"
    if metric == "PSH":
        if value < 73.40 or value > 155.47:
            return "red"
        if 73.40 <= value <= 79.59 or 126.83 <= value <= 155.47:
            return "amber"
        return "green"
    if metric == "PPC":
        if value > 1.18:
            return "red"
        if 0.39 <= value <= 1.18:
            return "amber"
        return "green"
    if metric == "PNC":
        if value > 1.88:
            return "red"
        if 1.47 <= value <= 1.88:
            return "amber"
        return "green"
    raise ValueError(f"unknown TNP metric: {metric}")


def _is_hydrogen_pdb_line(line: str) -> bool:
    if not line.startswith(("ATOM  ", "HETATM")):
        return False
    element = line[76:78].strip().upper() if len(line) >= 78 else ""
    if element == "H":
        return True
    atom_name = line[12:16].strip().upper() if len(line) >= 16 else ""
    atom_name = atom_name.lstrip("0123456789")
    return atom_name.startswith("H")


def write_heavy_atom_pdb(source: Path, destination: Path) -> None:
    with source.open("r", encoding="utf-8", errors="replace") as src, destination.open(
        "w", encoding="utf-8"
    ) as dst:
        for line in src:
            if not _is_hydrogen_pdb_line(line):
                dst.write(line)


def score_precomputed_pdb(
    *,
    candidate_id: str,
    pdb_path: Path,
    cdr1: str,
    cdr2: str,
    cdr3: str,
    h_scale: int = 0,
) -> dict[str, Any]:
    from theraprofnano.CDR_Profiler.CDR3_Conf_Assigner import (
        get_H3_anchor_line,
        get_spherical_coordinates,
        parse_nb,
    )
    from theraprofnano.Hydrophobicity_and_Charge_Profiler.Hydrophobicity_and_Charge_Assigner import (
        CreateAnnotation,
    )

    pdb_path = pdb_path.resolve()
    total_cdr_length = len(cdr1) + len(cdr2) + len(cdr3)
    cdr3_length = len(cdr3)

    tmpdir = Path(tempfile.mkdtemp(prefix="tnp_pdb_"))
    try:
        clean_pdb = tmpdir / "input.pdb"
        write_heavy_atom_pdb(pdb_path, clean_pdb)

        parsed = parse_nb(str(clean_pdb), "imgt")
        anchor_centre, _ = get_H3_anchor_line(parsed)
        import numpy as np

        h3_centre = np.mean(np.asarray(parsed["cdrs"][3]), axis=0)
        rho = float(get_spherical_coordinates(h3_centre, anchor_centre))
        compactness = float(cdr3_length / rho) if rho > 0 else math.nan

        surface = CreateAnnotation(
            h_scale,
            7.4,
            str(clean_pdb),
            "IG",
            "imgt",
            verbose=False,
        )[h_scale]
        psh = float(surface["Patch_Hydrophob_CDR"])
        ppc = float(surface["Patch_Pos_Charge_CDR"])
        pnc = float(surface["Patch_Neg_Charge_CDR"])

        metrics = {
            "total_cdr_length": total_cdr_length,
            "cdr3_length": cdr3_length,
            "cdr3_compactness": compactness,
            "psh": psh,
            "ppc": ppc,
            "pnc": pnc,
        }
        flags = {
            "L": assign_flag("L", float(total_cdr_length)),
            "L3": assign_flag("L3", float(cdr3_length)),
            "C": assign_flag("C", compactness),
            "PSH": assign_flag("PSH", psh),
            "PPC": assign_flag("PPC", ppc),
            "PNC": assign_flag("PNC", pnc),
        }
        return {
            "candidate_id": candidate_id,
            "status": "PASS",
            "failure_reason": "",
            "pdb_path": str(pdb_path),
            "h_scale": h_scale,
            **metrics,
            "flags": flags,
            "red_flag_count": sum(value == "red" for value in flags.values()),
            "amber_flag_count": sum(value == "amber" for value in flags.values()),
            "metric_semantics": "TNP structure developability proxy; not measured expression or purity",
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--pdb", required=True, type=Path)
    parser.add_argument("--cdr1", required=True)
    parser.add_argument("--cdr2", required=True)
    parser.add_argument("--cdr3", required=True)
    parser.add_argument("--h-scale", type=int, default=0, choices=range(5))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        result = score_precomputed_pdb(
            candidate_id=args.candidate_id,
            pdb_path=args.pdb,
            cdr1=args.cdr1,
            cdr2=args.cdr2,
            cdr3=args.cdr3,
            h_scale=args.h_scale,
        )
    except Exception as exc:  # technical failure is explicit NA, never a negative label
        result = {
            "candidate_id": args.candidate_id,
            "status": "TECHNICAL_NA",
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "pdb_path": str(args.pdb.resolve()),
            "metric_semantics": "TNP structure developability proxy; not measured expression or purity",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
