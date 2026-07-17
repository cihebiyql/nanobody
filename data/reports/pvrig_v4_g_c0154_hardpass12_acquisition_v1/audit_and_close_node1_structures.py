#!/usr/bin/env python3
"""Publish a descriptive NBB2/IgFold crosscheck and terminal closure receipt.

This supplemental V1 audit is non-selective: it cannot remove or replace any
of the 12 preregistered acquisition candidates and defines no pass threshold.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path("/data1/qlyu/projects/pvrig_v4_g_c0154_hardpass12_structures_v1_20260717")
AUDIT = Path("/data1/qlyu/projects/pvrig_v4_g_c0154_hardpass12_structure_crosscheck_v1_20260717")
EXPECTED = {
    "preregistration": "4b11ab21d9abcca4092a78c9bdbe9c4d514d871ac143ede8c8e19a473da1da7d",
    "structure_complete": "6865a62727edf9c5c124703b1fd57c3d57a23d5c21b6e622af87743c8f7dd978",
    "running_marker": "be278b6f46fadb9dc4f80b1158c48235ecff657b5e5f4a6f14270f7ac280f199",
    "monomer_manifest": "1ab840eb0c7705440c2d9e96c67b2be7b0757fafc242d9c72eb2105a3e598ca0",
    "hardpass12": "bd7da905bfc6e1131b711817be92cedbaaedcb87d38975e3ff50d055a597a43e",
}
CLAIM = "descriptive_monomer_crosscheck_only_no_selection_no_replacement_no_binding_or_blocking_claim"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def ca(path: Path) -> dict[int, np.ndarray]:
    values: dict[int, np.ndarray] = {}
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("ATOM  ") and len(line) >= 54 and line[21] == "A" and line[12:16].strip() == "CA":
            values[int(line[22:26])] = np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    return values


def parse_range(value: str) -> set[int]:
    start, end = map(int, value.split("-"))
    return set(range(start, end + 1))


def kabsch(mobile: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mobile_centroid, target_centroid = mobile.mean(axis=0), target.mean(axis=0)
    x, y = mobile - mobile_centroid, target - target_centroid
    u, _s, vt = np.linalg.svd(x.T @ y)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    translation = target_centroid - mobile_centroid @ rotation
    return rotation, translation


def rmsd(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.sum((a - b) ** 2, axis=1))))


def main() -> None:
    paths = {
        "preregistration": ROOT / "PREREGISTRATION.json",
        "structure_complete": ROOT / "status/structures.complete.json",
        "running_marker": ROOT / "status/structures.running.json",
        "monomer_manifest": ROOT / "outputs/monomer_manifest.tsv",
        "hardpass12": ROOT / "inputs/hardpass12.tsv",
    }
    for key, path in paths.items():
        if not path.is_file() or sha(path) != EXPECTED[key]:
            raise RuntimeError(f"frozen input hash mismatch: {key}")
    if AUDIT.exists() and any(AUDIT.iterdir()):
        raise RuntimeError(f"refusing non-empty supplemental audit root: {AUDIT}")
    AUDIT.mkdir(parents=True)
    script = Path(__file__).resolve()
    prereg = {
        "schema_version": "pvrig_v4_g_c0154_hardpass12_monomer_crosscheck_preregistration_v1",
        "status": "FROZEN_BEFORE_SUPPLEMENTAL_CROSSCHECK",
        "frozen_at_utc": now(),
        "implementation_sha256": sha(script),
        "input_hashes": EXPECTED,
        "metrics": ["sequence_and_CA_coverage", "framework_Kabsch_RMSD_A", "CDR3_RMSD_A", "CDR3_flanking_anchor_delta_A"],
        "thresholds": None,
        "selection_effect": "NONE",
        "replacement_effect": "NONE",
        "docking_input_remains": "all 12 NanoBodyBuilder2 primary monomers",
        "claim_boundary": CLAIM,
    }
    write_json(AUDIT / "PREREGISTRATION.json", prereg)

    selected = {row["candidate_id"]: row for row in read_tsv(paths["hardpass12"])}
    monomers = {row["candidate_id"]: row for row in read_tsv(paths["monomer_manifest"])}
    complete = json.loads(paths["structure_complete"].read_text())
    records = {row["candidate_id"]: row for row in complete["records"]}
    if set(selected) != set(monomers) or set(selected) != set(records) or len(selected) != 12:
        raise RuntimeError("candidate closure failed")
    output: list[dict[str, Any]] = []
    for cid in sorted(selected):
        row, manifest = selected[cid], monomers[cid]
        nbb, ig = Path(manifest["primary_pdb"]), Path(manifest["igfold_crosscheck_pdb"])
        if sha(nbb) != manifest["primary_pdb_sha256"] or sha(ig) != manifest["igfold_crosscheck_pdb_sha256"]:
            raise RuntimeError(f"PDB hash mismatch: {cid}")
        nbb_ca, ig_ca = ca(nbb), ca(ig)
        positions = sorted(set(nbb_ca) & set(ig_ca))
        all_cdr = parse_range(row["cdr1_range"]) | parse_range(row["cdr2_range"]) | parse_range(row["cdr3_range"])
        framework = [position for position in positions if position not in all_cdr]
        cdr3 = sorted(parse_range(row["cdr3_range"]) & set(positions))
        if len(positions) != len(row["sequence"]) or len(framework) < 50 or not cdr3:
            raise RuntimeError(f"CA coverage insufficient for descriptive audit: {cid}")
        mobile = np.array([ig_ca[p] for p in framework]); target = np.array([nbb_ca[p] for p in framework])
        rotation, translation = kabsch(mobile, target)
        aligned_framework = mobile @ rotation + translation
        aligned_cdr3 = np.array([ig_ca[p] for p in cdr3]) @ rotation + translation
        nbb_cdr3 = np.array([nbb_ca[p] for p in cdr3])
        cdr3_start, cdr3_end = map(int, row["cdr3_range"].split("-"))
        anchors = [p for p in (cdr3_start - 1, cdr3_end + 1) if p in nbb_ca and p in ig_ca]
        anchor_delta = [float(np.linalg.norm((ig_ca[p] @ rotation + translation) - nbb_ca[p])) for p in anchors]
        output.append({
            "candidate_id": cid,
            "sequence_length": len(row["sequence"]),
            "nbb2_ca_count": len(nbb_ca),
            "igfold_ca_count": len(ig_ca),
            "common_ca_count": len(positions),
            "framework_ca_count": len(framework),
            "framework_kabsch_rmsd_A": rmsd(aligned_framework, target),
            "cdr3_ca_count": len(cdr3),
            "cdr3_rmsd_after_framework_fit_A": rmsd(aligned_cdr3, nbb_cdr3),
            "cdr3_anchor_count": len(anchors),
            "cdr3_anchor_mean_delta_A": float(np.mean(anchor_delta)) if anchor_delta else None,
            "cdr3_anchor_max_delta_A": max(anchor_delta) if anchor_delta else None,
            "nbb2_refinement": records[cid]["nbb2_refinement"],
            "selection_effect": "NONE",
            "replacement_effect": "NONE",
            "claim_boundary": CLAIM,
        })
    table = AUDIT / "nbb2_igfold_crosscheck.tsv"
    with table.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(output)
    summary = {
        "status": "PASS_DESCRIPTIVE_CROSSCHECK_COMPLETE_NO_SELECTION_EFFECT",
        "candidate_count": 12,
        "full_sequence_CA_coverage_count": sum(row["common_ca_count"] == row["sequence_length"] for row in output),
        "nbb2_unrefined_fallback_count": sum(row["nbb2_refinement"] != "refined" for row in output),
        "nbb2_unrefined_fallback_ids": [row["candidate_id"] for row in output if row["nbb2_refinement"] != "refined"],
        "framework_kabsch_rmsd_A": {"min": min(row["framework_kabsch_rmsd_A"] for row in output), "median": float(np.median([row["framework_kabsch_rmsd_A"] for row in output])), "max": max(row["framework_kabsch_rmsd_A"] for row in output)},
        "cdr3_rmsd_A": {"min": min(row["cdr3_rmsd_after_framework_fit_A"] for row in output), "median": float(np.median([row["cdr3_rmsd_after_framework_fit_A"] for row in output])), "max": max(row["cdr3_rmsd_after_framework_fit_A"] for row in output)},
        "table_sha256": sha(table),
        "selection_effect": "NONE",
        "replacement_effect": "NONE",
        "claim_boundary": CLAIM,
    }
    write_json(AUDIT / "SUMMARY.json", summary)
    pid = int((ROOT / "status/launcher.pid").read_text().strip())
    try:
        os.kill(pid, 0); alive = True
    except ProcessLookupError:
        alive = False
    if alive:
        raise RuntimeError("structure launcher unexpectedly still alive")
    closure = {
        "schema_version": "pvrig_v4_g_c0154_hardpass12_structure_terminal_closure_v1",
        "status": "TERMINAL_PASS_SUPERSEDES_HISTORICAL_RUNNING_MARKER",
        "structure_complete_receipt_sha256": EXPECTED["structure_complete"],
        "historical_running_marker_preserved": {"path": str(paths["running_marker"]), "sha256": EXPECTED["running_marker"], "superseded": True},
        "launcher_pid": pid,
        "launcher_alive": False,
        "candidate_count": 12,
        "nbb2_primary_count": 12,
        "igfold_crosscheck_count": 12,
        "nbb2_unrefined_fallback_count": summary["nbb2_unrefined_fallback_count"],
        "nbb2_unrefined_fallback_ids": summary["nbb2_unrefined_fallback_ids"],
        "replacement_policy": "NO_REPLACEMENT_ALL_12_CONTINUE_TO_DOCKING",
        "supplemental_crosscheck_summary_sha256": sha(AUDIT / "SUMMARY.json"),
        "closed_at_utc": now(),
        "claim_boundary": CLAIM,
    }
    write_json(ROOT / "status/structures.terminal_closure_v1.json", closure)
    print(json.dumps({"closure": closure, "summary": summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
