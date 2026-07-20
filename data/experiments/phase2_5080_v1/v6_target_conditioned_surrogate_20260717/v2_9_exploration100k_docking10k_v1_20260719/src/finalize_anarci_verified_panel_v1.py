#!/usr/bin/env python3
"""Bind the selected panel to ANARCI/IMGT evidence and emit structure inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


CLAIM = (
    "Sequence admission and monomer-structure input freeze only; not binding, affinity, "
    "competition, experimental blocking, expression, purity, or Docking Gold."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(panel_path: Path, anarci_path: Path, output_dir: Path, expected: int) -> dict[str, object]:
    require(not output_dir.exists(), f"output_exists:{output_dir}")
    panel = pd.read_csv(panel_path, sep="\t", dtype=str).fillna("")
    anarci = pd.read_csv(anarci_path, sep="\t", dtype=str).fillna("")
    require(len(panel) == expected, f"panel_count:{len(panel)}:{expected}")
    require(panel.candidate_id.nunique() == expected, "panel_candidate_id_not_unique")
    require(panel.sequence_sha256.nunique() == expected, "panel_sequence_hash_not_unique")
    require(anarci.candidate_id.nunique() == len(anarci), "anarci_candidate_id_not_unique")
    anarci_columns = [
        "candidate_id", "anarci_imgt_pass", "anarci_chain_type", "anarci_hmm_species",
        "anarci_e_value", "anarci_score", "anarci_position1_present",
        "anarci_position128_present", "anarci_cdr1", "anarci_cdr2", "anarci_cdr3",
        "anarci_failure_reason",
    ]
    require(set(anarci_columns) <= set(anarci.columns), "anarci_columns_missing")
    merged = panel.merge(anarci[anarci_columns], on="candidate_id", how="left", validate="one_to_one")
    require(len(merged) == expected, "merged_count")
    require((merged.anarci_imgt_pass.str.lower() == "true").all(), "selected_anarci_failure")
    require((merged.anarci_chain_type == "H").all(), "selected_non_heavy_chain")
    require((merged.anarci_position1_present.str.lower() == "true").all(), "imgt_position1_missing")
    require((merged.anarci_position128_present.str.lower() == "true").all(), "imgt_position128_missing")
    require(not merged[["anarci_cdr1", "anarci_cdr2", "anarci_cdr3"]].eq("").any().any(), "imgt_cdr_missing")
    for row in merged.itertuples():
        require(sha256_text(row.sequence) == row.sequence_sha256, f"sequence_hash_mismatch:{row.candidate_id}")
    merged["research_pool_state"] = "RESEARCH_READY"
    merged["structure_input_state"] = "ANARCI_IMGT_VERIFIED"
    merged["monomer_model_policy"] = "NanoBodyBuilder2_refined_then_unrefined_fallback"
    merged["technical_failure_semantics"] = "NA_NOT_NEGATIVE"
    merged["structure_claim_boundary"] = CLAIM
    output_dir.mkdir(parents=True)
    manifest = output_dir / "structure_candidates10000.tsv"
    fasta = output_dir / "structure_candidates10000.fasta"
    merged.to_csv(manifest, sep="\t", index=False)
    with fasta.open("w") as handle:
        for row in merged.itertuples():
            handle.write(f">{row.candidate_id}\n{row.sequence}\n")
    receipt = {
        "schema_version": "pvrig_v2_9_anarci_verified_structure_inputs_v1",
        "status": "PASS_STRUCTURE_INPUT_FREEZE",
        "candidate_count": expected,
        "unique_sequence_count": int(merged.sequence_sha256.nunique()),
        "parent_count": int(merged.parent_framework_cluster.nunique()),
        "anarci_imgt_pass_count": int((merged.anarci_imgt_pass.str.lower() == "true").sum()),
        "input_hashes": {"panel": sha256_file(panel_path), "anarci_ledger": sha256_file(anarci_path)},
        "output_hashes": {"manifest": sha256_file(manifest), "fasta": sha256_file(fasta)},
        "claim_boundary": CLAIM,
    }
    (output_dir / "STRUCTURE_INPUT_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--anarci-ledger", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected", type=int, default=10000)
    args = parser.parse_args()
    print(json.dumps(run(args.panel, args.anarci_ledger, args.output_dir, args.expected), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
