#!/usr/bin/env python3
"""Parse RF2 multi-seed outputs while keeping strict old and formal gates separate."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCORE_RE = re.compile(r"^SCORE\s+([^:]+):\s+([-+0-9.eE]+)\s*$")
REQUIRED_METRICS = (
    "interaction_pae",
    "pred_lddt",
    "target_aligned_antibody_rmsd",
    "target_aligned_cdr_rmsd",
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]], preferred: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(preferred or [])
    for key in sorted({k for row in rows for k in row}):
        if key not in fields:
            fields.append(key)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def parse_scores(path: Path) -> dict[str, float]:
    scores: dict[str, float] = {}
    with path.open(encoding="ascii", errors="replace") as handle:
        for line in handle:
            match = SCORE_RE.match(line.strip())
            if match:
                scores[match.group(1)] = float(match.group(2))
    return scores


def classify(scores: dict[str, float]) -> tuple[str, str]:
    missing = [name for name in REQUIRED_METRICS if name not in scores or not math.isfinite(scores[name])]
    if missing:
        return "RF2_FAILED_MISSING_METRICS", ",".join(missing)
    if scores["interaction_pae"] >= 10.0:
        return "RF2_LOW_INTERACTION_CONFIDENCE", "interaction_pae>=10"
    if scores["target_aligned_antibody_rmsd"] >= 2.0:
        return "RF2_POSE_NOT_RECOVERED", "target_aligned_antibody_rmsd>=2A"
    if scores["target_aligned_cdr_rmsd"] >= 2.0:
        return "RF2_POSE_NOT_RECOVERED", "target_aligned_cdr_rmsd>=2A"
    return "RF2_POSE_RECOVERED", "interaction_pae<10_and_target_aligned_rmsd<2A"


def old_gate(seed: int, rf2_status: str) -> str:
    if seed != 42:
        return "NOT_APPLICABLE_ENRICHMENT_SEED"
    if rf2_status == "RF2_POSE_RECOVERED":
        return "OLD_GATE_PASS_STRICT_SEED42"
    return "OLD_GATE_FAIL_OR_MISSING_STRICT_SEED42"


def best_recovered(rows: list[dict[str, object]]) -> dict[str, object] | None:
    recovered = [row for row in rows if row["rf2_status"] == "RF2_POSE_RECOVERED"]
    if not recovered:
        return None
    return sorted(
        recovered,
        key=lambda row: (
            float(row.get("interaction_pae") or 999),
            max(float(row.get("target_aligned_antibody_rmsd") or 999), float(row.get("target_aligned_cdr_rmsd") or 999)),
            -float(row.get("pred_lddt") or -999),
            int(row["seed"]),
        ),
    )[0]


def parse(manifest_tsv: Path, output_dir: Path, min_seed42_outputs: int = 1000) -> dict[str, object]:
    manifest_rows = read_tsv(manifest_tsv)
    if not manifest_rows:
        raise ValueError("empty RF2 multiseed manifest")

    parsed: list[dict[str, object]] = []
    for row in manifest_rows:
        seed = int(row["seed"])
        output_pdb = Path(row["expected_output_pdb"])
        scores: dict[str, float] = {}
        if output_pdb.is_file():
            scores = parse_scores(output_pdb)
            status, reason = classify(scores)
        else:
            status, reason = "RF2_FAILED_MISSING_OUTPUT", "missing_best_pdb"
        parsed.append(
            {
                **row,
                "rf2_status": status,
                "rf2_reason": reason,
                "old_gate_status": old_gate(seed, status),
                "interaction_pae": scores.get("interaction_pae", ""),
                "pred_lddt": scores.get("pred_lddt", ""),
                "pae": scores.get("pae", ""),
                "target_aligned_antibody_rmsd": scores.get("target_aligned_antibody_rmsd", ""),
                "target_aligned_cdr_rmsd": scores.get("target_aligned_cdr_rmsd", ""),
                "framework_aligned_antibody_rmsd": scores.get("framework_aligned_antibody_rmsd", ""),
                "framework_aligned_cdr_rmsd": scores.get("framework_aligned_cdr_rmsd", ""),
                "rf2_output_pdb": str(output_pdb),
                "rf2_failure_label_policy": "not_negative_sample" if status.startswith("RF2_FAILED") else "qc_status_only",
            }
        )

    by_candidate: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in parsed:
        by_candidate[str(row["candidate_id"])].append(row)

    seed42_outputs = sum(int(row["seed"]) == 42 and row["rf2_status"] != "RF2_FAILED_MISSING_OUTPUT" for row in parsed)
    enrichment_allowed = seed42_outputs >= min_seed42_outputs
    candidate_rows: list[dict[str, object]] = []
    for candidate_id, rows in sorted(by_candidate.items()):
        seed42 = next((row for row in rows if int(row["seed"]) == 42), None)
        best = best_recovered(rows)
        old_status = str(seed42["old_gate_status"]) if seed42 else "OLD_GATE_FAIL_OR_MISSING_STRICT_SEED42"
        recovered_seeds = [str(row["seed"]) for row in rows if row["rf2_status"] == "RF2_POSE_RECOVERED"]
        missing_seeds = [str(row["seed"]) for row in rows if row["rf2_status"] == "RF2_FAILED_MISSING_OUTPUT"]
        failed_seeds = [str(row["seed"]) for row in rows if str(row["rf2_status"]).startswith("RF2_FAILED")]
        if best is None:
            formal_status = "FORMAL_MULTI_SEED_NO_RECOVERED_POSE"
        elif int(best["seed"]) == 42:
            formal_status = "FORMAL_MULTI_SEED_PASS_PRIMARY_SEED42"
        else:
            formal_status = "FORMAL_MULTI_SEED_PASS_ENRICHMENT_SEED"
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "old_gate_status": old_status,
                "formal_multiseed_gate_status": formal_status,
                "best_seed": best["seed"] if best else "",
                "best_interaction_pae": best.get("interaction_pae", "") if best else "",
                "best_pred_lddt": best.get("pred_lddt", "") if best else "",
                "recovered_seeds": ",".join(recovered_seeds),
                "missing_seeds": ",".join(missing_seeds),
                "failed_seeds": ",".join(failed_seeds),
                "seed42_outputs_global": seed42_outputs,
                "enrichment_allowed_by_seed42_outputs": enrichment_allowed,
                "rf2_failure_label_policy": "RF2 fail/missing is not a negative sample",
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    preferred = [
        "candidate_id", "seed", "gpu_id", "rf2_status", "rf2_reason", "old_gate_status",
        "formal_multiseed_gate_status", "interaction_pae", "pred_lddt",
        "target_aligned_antibody_rmsd", "target_aligned_cdr_rmsd", "rf2_failure_label_policy",
    ]
    write_tsv(output_dir / "rf2_multiseed_metrics.tsv", parsed, preferred)
    write_tsv(
        output_dir / "rf2_multiseed_candidate_gates.tsv",
        candidate_rows,
        [
            "candidate_id", "old_gate_status", "formal_multiseed_gate_status", "best_seed",
            "best_interaction_pae", "best_pred_lddt", "recovered_seeds", "missing_seeds", "failed_seeds",
            "enrichment_allowed_by_seed42_outputs", "rf2_failure_label_policy",
        ],
    )

    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_tsv": str(manifest_tsv),
        "manifest_rows": len(manifest_rows),
        "candidate_count": len(candidate_rows),
        "seed42_output_count": seed42_outputs,
        "seed42_min_outputs_required_for_enrichment": min_seed42_outputs,
        "seed42_enrichment_ready": enrichment_allowed,
        "status_counts": dict(sorted(Counter(str(row["rf2_status"]) for row in parsed).items())),
        "old_gate_counts": dict(sorted(Counter(str(row["old_gate_status"]) for row in parsed).items())),
        "formal_multiseed_gate_counts": dict(sorted(Counter(str(row["formal_multiseed_gate_status"]) for row in candidate_rows).items())),
        "missing_outputs": sum(row["rf2_status"] == "RF2_FAILED_MISSING_OUTPUT" for row in parsed),
        "failed_or_missing_are_negative_samples": False,
        "scientific_boundary": "RF2 failures or missing outputs are QC/missingness records only, not negative binding or blocking labels.",
    }
    (output_dir / "rf2_multiseed_parse_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_tsv", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--min-seed42-outputs", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(parse(args.manifest_tsv, args.output_dir, args.min_seed42_outputs), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
