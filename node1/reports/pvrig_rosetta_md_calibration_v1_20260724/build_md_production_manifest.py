#!/usr/bin/env python3
"""Expand the three minimized calibration systems to three 2 ns seeds each."""

from __future__ import annotations

import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent
source = HERE / "MD_STAGE_A_MANIFEST.tsv"
rows = list(csv.DictReader(source.open(newline="", encoding="utf-8"), delimiter="\t"))
if len(rows) != 3:
    raise SystemExit(f"expected three minimized systems, found {len(rows)}")

output = []
for gpu, row in enumerate(rows):
    for seed in (917, 1931, 3253):
        output.append(
            {
                "system_id": f'{row["pair_id"]}_{row["pair_role"]}',
                "pair_id": row["pair_id"],
                "pair_role": row["pair_role"],
                "source_job_id": row["job_id"],
                "md_seed": seed,
                "gpu": gpu,
                "nvt_ps": 100,
                "npt_ps": 100,
                "production_ns": 2,
                "force_field": "CHARMM36m_feb2026",
                "water_model": "TIP3P",
                "salt_molar": 0.15,
            }
        )

fields = list(output[0])
with (HERE / "MD_PRODUCTION_MANIFEST.tsv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(output)
print(f"wrote {len(output)} MD production jobs")
