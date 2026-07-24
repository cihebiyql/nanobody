#!/usr/bin/env python3
"""Build P30/P38/P39 positive-versus-destructive MD expansion manifests."""

from __future__ import annotations

import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent
source = HERE / "ROSETTA_JOB_MANIFEST.tsv"
rows = list(csv.DictReader(source.open(newline="", encoding="utf-8"), delimiter="\t"))
by_key = {
    (row["entity_id"], row["conformation"], row["docking_seed"]): row for row in rows
}

pairs = {
    "P30_W100A": {
        "positive": "CTRL_PATENT_003_case02_pos_03_PVRIG-30",
        "destructive": "CTRL_MUTANT_009_mut_09_PVRIG-30_cdr3_arom_W100A",
    },
    "P38_F100A": {
        "positive": "CTRL_PATENT_004_case02_pos_04_PVRIG-38",
        "destructive": "CTRL_MUTANT_014_mut_14_PVRIG-38_cdr3_arom_F100A",
    },
    "P39_F99A": {
        "positive": "CTRL_PATENT_005_case02_pos_05_PVRIG-39",
        "destructive": "CTRL_MUTANT_019_mut_19_PVRIG-39_cdr3_arom_F99A",
    },
}

systems = []
for pair_id, entities in pairs.items():
    for role, entity_id in entities.items():
        row = by_key[(entity_id, "8x6b", "917")]
        systems.append(
            {
                "system_id": f"{pair_id}_{role}",
                "pair_id": pair_id,
                "pair_role": role,
                "source_job_id": row["job_id"],
                "entity_id": entity_id,
                "source_job_hash": row["job_hash"],
                "source_pdb": f'inputs/pdb/{row["job_id"]}.pdb',
                "expected_behavior": row["expected_behavior"],
            }
        )

system_fields = list(systems[0])
with (HERE / "MD_EXPANSION_SYSTEMS.tsv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=system_fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(systems)

gpu_list = [0, 1, 2, 4, 5, 6, 7]
production = []
index = 0
for seed in (917, 1931, 3253):
    for system in systems:
        production.append(
            {
                "system_id": system["system_id"],
                "pair_id": system["pair_id"],
                "pair_role": system["pair_role"],
                "source_job_id": system["source_job_id"],
                "md_seed": seed,
                "gpu": gpu_list[index % len(gpu_list)],
                "nvt_ps": 100,
                "npt_ps": 100,
                "production_ns": 2,
                "force_field": "CHARMM36m_feb2026",
                "water_model": "TIP3P",
                "salt_molar": 0.15,
            }
        )
        index += 1

production_fields = list(production[0])
with (HERE / "MD_EXPANSION_PRODUCTION.tsv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(
        handle, fieldnames=production_fields, delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(production)
print(f"wrote {len(systems)} systems and {len(production)} production jobs")
