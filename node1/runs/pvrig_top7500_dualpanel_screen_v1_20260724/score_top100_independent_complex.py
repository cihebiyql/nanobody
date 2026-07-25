#!/usr/bin/env python3
"""Normalize and score Top100 Boltz/Chai poses against 8X6B and 9E6Y."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import gemmi
import numpy as np


def load_module(name: str, path: Path) -> ModuleType:
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chain_residues(chain: gemmi.Chain) -> list[gemmi.Residue]:
    return [
        residue for residue in chain
        if gemmi.find_tabulated_residue(residue.name).kind == gemmi.ResidueKind.AA
    ]


def residue_sequence(residues: list[gemmi.Residue]) -> str:
    return "".join(
        gemmi.find_tabulated_residue(residue.name).one_letter_code
        for residue in residues
    )


def normalized_pose(
    source: Path,
    output: Path,
    candidate_sequence: str,
    reference_residues: list[gemmi.Residue],
) -> None:
    structure = gemmi.read_structure(str(source))
    model = structure[0]
    reference_sequence = residue_sequence(reference_residues)
    found_candidate = False
    found_receptor = False
    for chain in model:
        residues = chain_residues(chain)
        sequence = residue_sequence(residues)
        if sequence == candidate_sequence:
            chain.name = "A"
            for index, residue in enumerate(residues, 1):
                residue.seqid = gemmi.SeqId(index, " ")
            found_candidate = True
        elif sequence == reference_sequence:
            chain.name = "T"
            for residue, reference in zip(residues, reference_residues):
                residue.seqid = gemmi.SeqId(
                    reference.seqid.num, reference.seqid.icode
                )
            found_receptor = True
        else:
            raise ValueError(
                f"unknown chain {chain.name} in {source}: length={len(sequence)}"
            )
    if not found_candidate or not found_receptor:
        raise ValueError(
            f"failed to identify both chains in {source}: "
            f"candidate={found_candidate} receptor={found_receptor}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    structure.write_pdb(str(output))


def find_cdr_range(sequence: str, cdr: str) -> set[int]:
    start = sequence.find(cdr)
    if start < 0:
        raise ValueError(f"CDR not found: {cdr}")
    return set(range(start + 1, start + len(cdr) + 1))


def metric(payload: dict[str, Any], *keys: str, default: Any = 0) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def confidence_for_pose(tool: str, source: Path) -> dict[str, Any]:
    if tool == "boltz":
        candidate = source.name[: -len("_model_0.pdb")]
        confidence_path = source.with_name(f"confidence_{candidate}_model_0.json")
        payload = json.loads(confidence_path.read_text(encoding="utf-8"))
        return {
            "confidence_path": str(confidence_path),
            "tool_confidence": payload.get("confidence_score", ""),
            "ptm": payload.get("ptm", ""),
            "iptm": payload.get("iptm", ""),
            "complex_plddt": payload.get("complex_plddt", ""),
            "complex_iplddt": payload.get("complex_iplddt", ""),
            "inter_chain_clash_flag": "",
        }
    index = source.stem.split("_")[-1]
    score_path = source.with_name(f"scores.model_idx_{index}.npz")
    scores = np.load(score_path)
    return {
        "confidence_path": str(score_path),
        "tool_confidence": float(scores["aggregate_score"][0]),
        "ptm": float(scores["ptm"][0]),
        "iptm": float(scores["iptm"][0]),
        "complex_plddt": "",
        "complex_iplddt": "",
        "inter_chain_clash_flag": bool(scores["has_inter_chain_clashes"][0]),
    }


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t",
            extrasaction="ignore", lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    reference_root = args.reference_root.resolve()
    scripts = reference_root / "scripts"
    score_module = load_module("independent_score_pose", scripts / "score_pose.py")
    aggregate_module = load_module(
        "independent_aggregate_results", scripts / "aggregate_results.py"
    )
    summary = json.loads(
        (
            reference_root / "reports" / "reference_normalization_summary.json"
        ).read_text(encoding="utf-8")
    )
    hotspots = summary["hotspots"]
    reference_atoms = {
        reference: score_module.parse_pdb(
            reference_root / "inputs" / "normalized"
            / f"{reference}_TL_reference.pdb"
        )
        for reference in ("8x6b", "9e6y")
    }
    receptor_structure = gemmi.read_structure(
        str(
            reference_root / "inputs" / "normalized"
            / "8x6b_pvrig_receptor.pdb"
        )
    )
    reference_residues = chain_residues(next(iter(receptor_structure[0])))

    manifest_path = (
        project / "manifests" / "top100_independent_complex_manifest.tsv"
    )
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        manifest = list(csv.DictReader(handle, delimiter="\t"))

    pose_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    pair_order = {"STRICT_A": 2, "SUPPORTED_AB": 1, "OTHER": 0}
    for candidate in sorted(manifest, key=lambda row: int(row["top100_rank"])):
        candidate_id = candidate["candidate_id"]
        boltz_matches = list(
            (project / "outputs" / "boltz").rglob(
                f"{candidate_id}_model_0.pdb"
            )
        )
        if len(boltz_matches) != 1:
            raise ValueError(
                f"{candidate_id}: expected one Boltz PDB, got {len(boltz_matches)}"
            )
        sources: list[tuple[str, int, Path]] = [
            ("boltz", 0, boltz_matches[0])
        ]
        for index in (0, 1):
            source = (
                project / "outputs" / "chai" / candidate_id
                / f"pred.model_idx_{index}.cif"
            )
            if not source.is_file():
                raise FileNotFoundError(source)
            sources.append(("chai", index, source))

        cdr_ranges = {
            "cdr1": find_cdr_range(candidate["sequence"], candidate["imgt_cdr1"]),
            "cdr2": find_cdr_range(candidate["sequence"], candidate["imgt_cdr2"]),
            "cdr3": find_cdr_range(candidate["sequence"], candidate["imgt_cdr3"]),
        }
        candidate_poses: list[dict[str, Any]] = []
        for tool, pose_index, source in sources:
            normalized = (
                project / "normalized" / tool / candidate_id
                / f"pose_{pose_index}.pdb"
            )
            normalized_pose(
                source, normalized, candidate["sequence"], reference_residues
            )
            atoms = score_module.parse_pdb(normalized)
            scores = {
                reference: score_module.score_against_reference(
                    atoms,
                    reference_atoms[reference],
                    reference,
                    hotspots,
                    "A",
                    cdr_ranges,
                )
                for reference in ("8x6b", "9e6y")
            }
            classes = {
                reference: aggregate_module.classify_geometry(value)
                for reference, value in scores.items()
            }
            margins = {
                reference: aggregate_module.geometry_margin(value)
                for reference, value in scores.items()
            }
            pair_label = aggregate_module.pair_label(
                classes["8x6b"], classes["9e6y"]
            )
            confidence = confidence_for_pose(tool, source)
            row: dict[str, Any] = {
                "top100_rank": candidate["top100_rank"],
                "candidate_id": candidate_id,
                "tool": tool,
                "pose_index": pose_index,
                "source": str(source),
                "source_sha256": sha256_file(source),
                "normalized_pdb": str(normalized),
                "normalized_pdb_sha256": sha256_file(normalized),
                "monomer_high_uncertainty": candidate[
                    "monomer_high_uncertainty"
                ],
                "pair_label": pair_label,
                **confidence,
            }
            for reference, score in scores.items():
                prefix = reference
                row.update(
                    {
                        f"{prefix}_class": classes[reference],
                        f"{prefix}_geometry_margin": round(
                            float(margins[reference]), 6
                        ),
                        f"{prefix}_hotspot_overlap": metric(
                            score, "hotspot_overlap", "full", "count"
                        ),
                        f"{prefix}_anchor_overlap": metric(
                            score, "hotspot_overlap", "anchor", "count"
                        ),
                        f"{prefix}_holdout_overlap": metric(
                            score, "hotspot_overlap", "holdout", "count"
                        ),
                        f"{prefix}_total_occlusion": metric(
                            score, "vhh_pvrl2_occlusion", "residue_pair_count"
                        ),
                        f"{prefix}_cdr3_occlusion": metric(
                            score, "vhh_pvrl2_occlusion",
                            "by_vhh_region_pair_count", "cdr3"
                        ),
                        f"{prefix}_cdr3_fraction": metric(
                            score, "vhh_pvrl2_occlusion", "cdr3_fraction"
                        ),
                        f"{prefix}_clash_atom_pairs": metric(
                            score, "clashes_2p5a", "atom_pair_count"
                        ),
                        f"{prefix}_clash_residue_pairs": metric(
                            score, "clashes_2p5a", "residue_pair_count"
                        ),
                        f"{prefix}_overlay_rmsd_a": metric(
                            score, "overlay", "t_ca_rmsd_a"
                        ),
                    }
                )
            pose_rows.append(row)
            candidate_poses.append(row)

        boltz = next(row for row in candidate_poses if row["tool"] == "boltz")
        chai = [row for row in candidate_poses if row["tool"] == "chai"]
        chai_best = max(
            chai,
            key=lambda row: (
                pair_order[row["pair_label"]],
                min(
                    float(row["8x6b_geometry_margin"]),
                    float(row["9e6y_geometry_margin"]),
                ),
                float(row["tool_confidence"]),
            ),
        )
        boltz_supported = boltz["pair_label"] in {"STRICT_A", "SUPPORTED_AB"}
        chai_supported = chai_best["pair_label"] in {"STRICT_A", "SUPPORTED_AB"}
        if boltz["pair_label"] == chai_best["pair_label"] == "STRICT_A":
            support = "DUAL_TOOL_STRICT_A"
        elif boltz_supported and chai_supported:
            support = "DUAL_TOOL_SUPPORTED_AB"
        elif boltz_supported or chai_supported:
            support = "SINGLE_TOOL_SUPPORTED"
        else:
            support = "NO_BLOCKER_GEOMETRY_SUPPORT"
        candidate_rows.append(
            {
                "top100_rank": candidate["top100_rank"],
                "candidate_id": candidate_id,
                "monomer_high_uncertainty": candidate[
                    "monomer_high_uncertainty"
                ],
                "boltz_pair_label": boltz["pair_label"],
                "boltz_iptm": boltz["iptm"],
                "boltz_confidence": boltz["tool_confidence"],
                "chai_best_pose_index": chai_best["pose_index"],
                "chai_best_pair_label": chai_best["pair_label"],
                "chai_best_iptm": chai_best["iptm"],
                "chai_best_confidence": chai_best["tool_confidence"],
                "chai_pose_pair_labels": ",".join(
                    str(row["pair_label"]) for row in chai
                ),
                "chai_pose_consistent": str(
                    len({row["pair_label"] for row in chai}) == 1
                ).lower(),
                "cross_tool_pair_label_agreement": str(
                    boltz["pair_label"] == chai_best["pair_label"]
                ).lower(),
                "independent_complex_support": support,
                "high_uncertainty": str(
                    candidate["monomer_high_uncertainty"] == "true"
                    or boltz["pair_label"] != chai_best["pair_label"]
                    or len({row["pair_label"] for row in chai}) != 1
                ).lower(),
            }
        )

    pose_fields = list(pose_rows[0])
    candidate_fields = list(candidate_rows[0])
    reports = project / "reports"
    pose_path = reports / "TOP100_INDEPENDENT_COMPLEX_POSE_SCORES.tsv"
    candidate_path = reports / "TOP100_INDEPENDENT_COMPLEX_CANDIDATE_SUMMARY.tsv"
    uncertain_path = reports / "TOP100_INDEPENDENT_COMPLEX_HIGH_UNCERTAINTY.tsv"
    write_tsv(pose_path, pose_rows, pose_fields)
    write_tsv(candidate_path, candidate_rows, candidate_fields)
    uncertain = [row for row in candidate_rows if row["high_uncertainty"] == "true"]
    write_tsv(uncertain_path, uncertain, candidate_fields)
    summary_payload = {
        "schema_version": "pvrig.top100.independent_complex.scoring.v1",
        "state": "COMPLETE",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(candidate_rows),
        "pose_count": len(pose_rows),
        "tool_pose_counts": dict(
            sorted(Counter(row["tool"] for row in pose_rows).items())
        ),
        "independent_support_counts": dict(
            sorted(
                Counter(
                    row["independent_complex_support"]
                    for row in candidate_rows
                ).items()
            )
        ),
        "boltz_pair_label_counts": dict(
            sorted(Counter(row["boltz_pair_label"] for row in candidate_rows).items())
        ),
        "chai_best_pair_label_counts": dict(
            sorted(
                Counter(row["chai_best_pair_label"] for row in candidate_rows).items()
            )
        ),
        "cross_tool_pair_label_agreement_count": sum(
            row["cross_tool_pair_label_agreement"] == "true"
            for row in candidate_rows
        ),
        "high_uncertainty_count": len(uncertain),
        "manifest_sha256": sha256_file(manifest_path),
        "pose_scores_sha256": sha256_file(pose_path),
        "candidate_summary_sha256": sha256_file(candidate_path),
        "high_uncertainty_sha256": sha256_file(uncertain_path),
        "threshold_note": (
            "Geometry A/B/E uses the frozen legacy HADDOCK calibration thresholds "
            "only as a compatibility diagnostic. Chai/Boltz confidence ranges "
            "remain uncalibrated until positives and disruptive controls are run."
        ),
        "claim_boundary": (
            "Independent complex prediction agreement is computational evidence, "
            "not experimental binding, affinity, purity, or blocking proof."
        ),
    }
    summary_path = reports / "TOP100_INDEPENDENT_COMPLEX_SCORING_SUMMARY.json"
    summary_path.write_text(
        json.dumps(
            summary_payload, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
