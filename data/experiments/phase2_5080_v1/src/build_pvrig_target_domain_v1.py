#!/usr/bin/env python3
"""Build the explicit PVRIG full-sequence to model-domain mapping contract."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


def read_fasta(path: Path) -> tuple[str, str]:
    seq_id = ""
    parts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            if not seq_id:
                seq_id = line[1:].split()[0]
            continue
        parts.append(line.strip())
    sequence = "".join(parts).upper()
    if not sequence:
        raise ValueError(f"No FASTA sequence in {path}")
    return seq_id, sequence


def classify_evidence(row: dict[str, str]) -> str:
    classes = row.get("hotspot_classes", "")
    if not classes:
        return "none"
    has_structural = "core_hotspot" in classes or "secondary_hotspot" in classes
    has_soft = "soft_hint" in classes
    if has_structural and has_soft:
        return "hybrid"
    return "structure_interface" if has_structural else "heuristic_soft_hint"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--start", type=int, default=39, help="Inclusive UniProt position for the model-domain proxy.")
    parser.add_argument("--end", type=int, default=171, help="Inclusive UniProt position for the model-domain proxy.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    source_fasta = root / "model_data/pvrig_target_sequence_v0.fasta"
    source_mask = root / "model_data/pvrig_full_sequence_mask_v0.csv"
    snapshot_path = root / "model_data/pvrig_uniprot_annotation_snapshot_v1.json"
    output_fasta = root / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
    output_mapping = root / "model_data/pvrig_target_domain_mapping_v1.csv"
    output_contract = root / "model_data/pvrig_target_domain_contract_v1.json"
    audit_path = root / "experiments/phase2_5080_v1/audits/PVRIG_TARGET_DOMAIN_AUDIT_V1.md"

    seq_id, sequence = read_fasta(source_fasta)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    with source_mask.open(newline="", encoding="utf-8") as handle:
        mask_rows = list(csv.DictReader(handle))
    if len(sequence) != 326 or len(mask_rows) != len(sequence):
        raise ValueError(f"Expected aligned 326-aa full sequence and mask, got {len(sequence)} and {len(mask_rows)}")
    if snapshot.get("sequence") != sequence:
        raise ValueError("Local FASTA does not match the retrieved UniProt snapshot")
    if not (1 <= args.start <= args.end <= len(sequence)):
        raise ValueError(f"Invalid model-domain bounds: {args.start}-{args.end}")

    domain_sequence = sequence[args.start - 1 : args.end]
    mapping_rows: list[dict[str, Any]] = []
    for full_index, (aa, mask) in enumerate(zip(sequence, mask_rows)):
        full_position = full_index + 1
        if int(mask["uniprot_position"]) != full_position or mask["aa"] != aa:
            raise ValueError(f"Mask mismatch at full position {full_position}")
        in_domain = args.start <= full_position <= args.end
        model_index = full_position - args.start if in_domain else ""
        mapping_rows.append(
            {
                "uniprot_accession": "Q6DKI7",
                "full_index_0based": full_index,
                "full_position_1based": full_position,
                "aa": aa,
                "model_domain_id": "pvrig_structural_ectodomain_proxy_v1",
                "in_model_domain": "yes" if in_domain else "no",
                "model_index_0based": model_index,
                "model_position_1based": model_index + 1 if in_domain else "",
                "in_target_epitope": mask["in_target_epitope"],
                "target_weight": mask["target_weight"],
                "hotspot_ids": mask["hotspot_ids"],
                "hotspot_classes": mask["hotspot_classes"],
                "evidence_tier": classify_evidence(mask),
            }
        )

    output_fasta.write_text(
        f">PVRIG_HUMAN_Q6DKI7 structural_ectodomain_proxy={args.start}-{args.end} "
        "derived_from_PDB_coverage_and_TM_start_not_reviewed_topological_domain\n"
        + domain_sequence
        + "\n",
        encoding="ascii",
    )
    with output_mapping.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(mapping_rows[0]))
        writer.writeheader()
        writer.writerows(mapping_rows)

    tm_features = [f for f in snapshot["selected_features"] if f["type"] == "Transmembrane"]
    contract = {
        "contract_version": "pvrig_target_domain_contract_v1",
        "accession": "Q6DKI7",
        "full_sequence_id": seq_id,
        "full_sequence_length": len(sequence),
        "full_sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest(),
        "model_domain_id": "pvrig_structural_ectodomain_proxy_v1",
        "model_domain_start_1based_inclusive": args.start,
        "model_domain_end_1based_inclusive": args.end,
        "model_domain_length": len(domain_sequence),
        "model_domain_sequence_sha256": hashlib.sha256(domain_sequence.encode("ascii")).hexdigest(),
        "index_formula": f"full_position_1based = model_index_0based + {args.start}",
        "boundary_status": "derived_structure_supported_proxy_not_reviewed_uniprot_topological_domain",
        "start_rationale": "Official UniProt PDB cross-reference 8X6B covers Q6DKI7 positions 39-154.",
        "end_rationale": "Position 171 is immediately before the UniProt predicted transmembrane feature starting at 172; 9E6Y covers 41-172.",
        "local_structure_mapping_coverage": "41-153 in structures/PVRIG_numbering_reconciliation.csv",
        "functional_interface_evidence_range": "67-144 including soft hints; structure-backed core/secondary interface is 71-144",
        "uniprot_snapshot": str(snapshot_path.relative_to(root)),
        "uniprot_source_url": snapshot["source_url"],
        "uniprot_entry_type": snapshot["entry_type"],
        "selected_pdb_cross_references": snapshot["selected_pdb_cross_references"],
        "selected_transmembrane_features": tm_features,
        "fasta_path": str(output_fasta.relative_to(root)),
        "mapping_path": str(output_mapping.relative_to(root)),
        "evidence_boundary": "Sequence-model target proxy only; not experimental binding or blocker evidence.",
    }
    output_contract.write_text(json.dumps(contract, indent=2, ensure_ascii=True) + "\n", encoding="ascii")

    hotspot_positions = [int(row["full_position_1based"]) for row in mapping_rows if row["hotspot_ids"]]
    if hotspot_positions and not all(args.start <= pos <= args.end for pos in hotspot_positions):
        raise ValueError("The selected target domain does not contain every hotspot/control position")
    lines = [
        "# PVRIG Target Domain Audit V1",
        "",
        "Verdict: PASS",
        "",
        f"- Full sequence: Q6DKI7, {len(sequence)} aa",
        f"- Model input proxy: UniProt {args.start}-{args.end}, {len(domain_sequence)} aa",
        f"- Model-index contract: `full_position_1based = model_index_0based + {args.start}`",
        "- Start evidence: official UniProt PDB cross-reference 8X6B covers 39-154.",
        "- End evidence: UniProt predicts a transmembrane helix at 172-192; 9E6Y covers 41-172.",
        "- Local observed numbering coverage: 41-153.",
        f"- Target hotspot positions covered: {min(hotspot_positions)}-{max(hotspot_positions)} ({len(hotspot_positions)} positions).",
        "- Boundary warning: 39-171 is a structure-supported model proxy, not a reviewed UniProt topological-domain annotation.",
        "- Evidence boundary: external priors remain binding/site priors, not PVRIG blocker scores.",
        "",
    ]
    audit_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": "PASS", "fasta": str(output_fasta), "mapping": str(output_mapping), "contract": str(output_contract), "audit": str(audit_path)}, indent=2))


if __name__ == "__main__":
    main()
