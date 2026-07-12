#!/usr/bin/env python3
"""Create the frozen RFantibody V2 generation matrix."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


PATCHES = (
    (
        "P1_core_blocker",
        "T57,T97,T101,T103,T105,T106",
        "R95,K135,F139,E141,S143,W144",
        "T33,T36,T43,T52,T60,T62,T99,T100,T102,T104",
        "core blocker anchors shared by the two receptor-ligand references",
    ),
    (
        "P2_bridge_N_C",
        "T33,T36,T57,T60,T101,T105,T106",
        "S71,T74,R95,R98,F139,S143,W144",
        "T43,T44,T45,T52,T54,T62,T97,T99,T102,T103,T104",
        "bridge the N-terminal and C-terminal PVRIG interface patches",
    ),
    (
        "P3_charge_aromatic",
        "T57,T60,T62,T97,T101,T105,T106",
        "R95,R98,W100,K135,F139,S143,W144",
        "T33,T36,T43,T44,T45,T52,T54,T99,T102,T103,T104",
        "rescue the weak legacy hydrophobic patch with charged anchors",
    ),
    (
        "P4_cterm_robust",
        "T97,T99,T101,T102,T103,T105,T106",
        "K135,A137,F139,P140,E141,S143,W144",
        "T33,T36,T43,T44,T45,T52,T54,T57,T60,T62",
        "dense C-terminal patch for receptor-conformation robustness",
    ),
    (
        "P5_upper_interface",
        "T43,T44,T45,T52,T54,T57,T60",
        "N81,G82,A83,V90,H92,R95,R98",
        "T33,T36,T62,T97,T99,T101,T102,T103,T104,T105,T106",
        "explore an upper-interface orientation not dominated by W144",
    ),
    (
        "P6_holdout_ablation",
        "T57,T97,T101,T105,T106",
        "R95,K135,F139,S143,W144",
        "T33,T36,T43,T52,T60,T62,T103",
        "sparse ablation arm with explicit unprompted holdout scoring",
    ),
)

SCAFFOLDS = (
    (
        "orig",
        "inputs/scaffolds/h-NbBCII10_original.pdb",
        "none",
        "diagnostic_baseline_only",
    ),
    (
        "qrg",
        "inputs/scaffolds/h-NbBCII10_vhh_qrg.pdb",
        "Kabat_H44Q_H45R_H47G",
        "primary_vhhified",
    ),
    (
        "ekg",
        "inputs/scaffolds/h-NbBCII10_vhh_ekg.pdb",
        "Kabat_H44E_H45K_H47G",
        "primary_vhhified",
    ),
    (
        "qkg",
        "inputs/scaffolds/h-NbBCII10_vhh_qkg.pdb",
        "Kabat_H44Q_H45K_H47G",
        "primary_vhhified",
    ),
)

H3_REGIMES = (
    ("S", "H1:7,H2:6,H3:5-10", "short_to_medium_h3"),
    ("L", "H1:7,H2:6,H3:11-15", "long_h3_for_interface_occlusion"),
)

GPU_IDS = (1, 2, 3, 4, 5, 7)


def build_rows(backbones: int, sequences: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    index = 0
    for patch_id, hotspots, uniprot, holdout, patch_purpose in PATCHES:
        patch_short = patch_id.split("_", 1)[0]
        for scaffold_id, framework, mutations, scaffold_lane in SCAFFOLDS:
            for h3_id, design_loops, h3_purpose in H3_REGIMES:
                arm_id = f"{patch_short}_{scaffold_id}_{h3_id}"
                rows.append(
                    {
                        "arm_id": arm_id,
                        "gpu_id": GPU_IDS[index % len(GPU_IDS)],
                        "patch_id": patch_id,
                        "hotspots_pdb": hotspots,
                        "hotspots_uniprot": uniprot,
                        "holdout_hotspots_pdb": holdout,
                        "scaffold_id": scaffold_id,
                        "framework_relpath": framework,
                        "framework_mutations": mutations,
                        "scaffold_lane": scaffold_lane,
                        "h3_regime": h3_id,
                        "design_loops": design_loops,
                        "target_backbones": backbones,
                        "seqs_per_backbone": sequences,
                        "mpnn_temperature": 0.2,
                        "generation_seed_lane": index,
                        "purpose": f"{patch_purpose};{h3_purpose}",
                    }
                )
                index += 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--backbones-per-arm", type=int, default=8)
    parser.add_argument("--sequences-per-backbone", type=int, default=4)
    args = parser.parse_args()

    rows = build_rows(args.backbones_per_arm, args.sequences_per_backbone)
    if len(rows) != 48 or len({row["arm_id"] for row in rows}) != 48:
        raise RuntimeError("The frozen design must contain exactly 48 unique arms")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    total_backbones = sum(int(row["target_backbones"]) for row in rows)
    total_sequences = sum(
        int(row["target_backbones"]) * int(row["seqs_per_backbone"])
        for row in rows
    )
    summary = {
        "schema_version": 1,
        "arm_count": len(rows),
        "patch_count": len(PATCHES),
        "scaffold_count": len(SCAFFOLDS),
        "h3_regime_count": len(H3_REGIMES),
        "gpu_ids": list(GPU_IDS),
        "total_backbones": total_backbones,
        "total_raw_sequences": total_sequences,
        "primary_vhhified_raw_sequences": sum(
            int(row["target_backbones"]) * int(row["seqs_per_backbone"])
            for row in rows
            if row["scaffold_lane"] == "primary_vhhified"
        ),
        "by_gpu": dict(sorted(Counter(str(row["gpu_id"]) for row in rows).items())),
        "docking_cohort_target": 1024,
        "selection_policy": "primary_vhhified_only_then_arm_and_backbone_balanced",
        "scientific_boundary": "hotspot-conditioned generation is not binding or blockade evidence",
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
