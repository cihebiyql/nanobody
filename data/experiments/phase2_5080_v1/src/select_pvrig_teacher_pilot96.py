#!/usr/bin/env python3
"""Select a deterministic, provenance-complete 96-candidate docking pilot."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Callable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_CANDIDATES = EXP_DIR / "prepared/pvrig_rfantibody_v1/candidate_manifest.tsv"
DEFAULT_FAST = EXP_DIR / "runs/pvrig_teacher_v1_20260712/fast_screen_v1/fast_merged.tsv"
DEFAULT_OUTDIR = EXP_DIR / "data_splits/pvrig_teacher_pilot96"
CLAIM_BOUNDARY = "docking_teacher_pilot_selection_not_binding_or_blocker_proof"
HOTSPOT_QUOTA = 24
BACKBONE_CAP = 2
SEED = "pvrig_teacher_pilot96_v1_seed73"

FIELDS = [
    "schema_version",
    "selection_rank",
    "candidate_id",
    "source_candidate_id",
    "sequence",
    "sequence_sha256",
    "hotspot_set",
    "hotspots_uniprot",
    "framework_id",
    "parent_framework_cluster",
    "backbone_index",
    "mpnn_index",
    "cdr1",
    "cdr2",
    "cdr3",
    "cdr3_length",
    "rfd_mindist",
    "rfd_hotspot_distance_bin",
    "fast_score",
    "fast_rank",
    "fast_recommendation",
    "fast_reason_summary",
    "selection_stratum",
    "teacher_split",
    "formal_model_eligible",
    "source_mpnn_pdb",
    "monomer_plan",
    "claim_boundary",
]


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(clean(value))
    except ValueError:
        return default


def as_int(value: object, default: int = 0) -> int:
    try:
        return int(float(clean(value)))
    except ValueError:
        return default


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def random_key(candidate_id: str) -> str:
    return hashlib.sha256(f"{SEED}\t{candidate_id}".encode()).hexdigest()


def select_rows(candidates: Sequence[dict[str, str]], fast_rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    by_id = {row["candidate_id"]: row for row in candidates}
    fast_by_id = {row["candidate_id"]: row for row in fast_rows}
    if len(by_id) != 1000 or len(fast_by_id) != 1000:
        raise ValueError(f"Expected 1000 candidate and fast rows, found {len(by_id)} and {len(fast_by_id)}")
    missing = sorted(set(by_id) ^ set(fast_by_id))
    if missing:
        raise ValueError(f"Candidate/Fast ID mismatch: {missing[:10]}")

    joined: list[dict[str, str]] = []
    for candidate_id, row in by_id.items():
        fast = fast_by_id[candidate_id]
        if fast.get("hard_fail") == "True":
            continue
        joined.append(
            {
                **row,
                "fast_score": clean(fast.get("final_score")),
                "fast_rank": clean(fast.get("cascade_fast_rank")),
                "fast_recommendation": clean(fast.get("recommendation")),
                "fast_reason_summary": clean(fast.get("reason_summary")),
            }
        )
    if len(joined) != 1000:
        raise ValueError(f"Expected all repaired candidates to pass hard gates; found {len(joined)}")

    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    backbone_counts: Counter[tuple[str, str]] = Counter()

    def take(pool: Sequence[dict[str, str]], count: int, stratum: str) -> None:
        taken = 0
        for row in pool:
            if row["candidate_id"] in selected_ids:
                continue
            key = (row["hotspot_set"], row["backbone_index"])
            if backbone_counts[key] >= BACKBONE_CAP:
                continue
            out = dict(row)
            out["selection_stratum"] = stratum
            selected.append(out)
            selected_ids.add(row["candidate_id"])
            backbone_counts[key] += 1
            taken += 1
            if taken == count:
                return
        raise ValueError(f"Could not fill stratum {stratum}: requested {count}, selected {taken}")

    for hotspot in "ABCD":
        pool = [row for row in joined if row["hotspot_set"] == hotspot]
        exploit = sorted(
            pool,
            key=lambda row: (
                -as_float(row["fast_score"]),
                as_float(row["rfd_mindist"], 999.0),
                random_key(row["candidate_id"]),
            ),
        )
        take(exploit, 8, f"{hotspot}:fast_geometry_exploitation")

        diversity = sorted(
            pool,
            key=lambda row: (
                backbone_counts[(hotspot, row["backbone_index"])],
                as_int(row.get("cdr3_length"), len(row.get("cdr3", ""))) % 3,
                -len(row.get("cdr3", "")),
                random_key(row["candidate_id"]),
            ),
        )
        take(diversity, 8, f"{hotspot}:backbone_cdr3_diversity")

        boundary = sorted(
            pool,
            key=lambda row: (
                -as_float(row["rfd_mindist"]),
                as_float(row["fast_score"]),
                random_key(row["candidate_id"]),
            ),
        )
        take(boundary, 4, f"{hotspot}:geometry_boundary_or_failure_mode")

        sentinel = sorted(pool, key=lambda row: random_key(row["candidate_id"]))
        take(sentinel, 4, f"{hotspot}:deterministic_random_sentinel")

    if len(selected) != 96:
        raise ValueError(f"Expected 96 selected rows, found {len(selected)}")
    for rank, row in enumerate(selected, start=1):
        row["selection_rank"] = str(rank)
    return selected


def output_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "schema_version": "pvrig_teacher_pilot96_manifest_v1",
        "selection_rank": row["selection_rank"],
        "candidate_id": row["candidate_id"],
        "source_candidate_id": row["source_candidate_id"],
        "sequence": row["sequence"],
        "sequence_sha256": row["sequence_sha256"],
        "hotspot_set": row["hotspot_set"],
        "hotspots_uniprot": row["hotspots_uniprot"],
        "framework_id": row["framework_id"],
        "parent_framework_cluster": row["parent_framework_cluster"],
        "backbone_index": row["backbone_index"],
        "mpnn_index": row["mpnn_index"],
        "cdr1": row["cdr1"],
        "cdr2": row["cdr2"],
        "cdr3": row["cdr3"],
        "cdr3_length": str(len(row["cdr3"])),
        "rfd_mindist": row["rfd_mindist"],
        "rfd_hotspot_distance_bin": row["rfd_hotspot_distance_bin"],
        "fast_score": row["fast_score"],
        "fast_rank": row["fast_rank"],
        "fast_recommendation": row["fast_recommendation"],
        "fast_reason_summary": row["fast_reason_summary"],
        "selection_stratum": row["selection_stratum"],
        "teacher_split": "pilot_only",
        "formal_model_eligible": "false_single_framework_pilot",
        "source_mpnn_pdb": row["source_mpnn_pdb"],
        "monomer_plan": "NanoBodyBuilder2_from_FR4_completed_sequence",
        "claim_boundary": CLAIM_BOUNDARY,
    }


def run(candidate_path: Path, fast_path: Path, outdir: Path) -> dict[str, object]:
    selected = [output_row(row) for row in select_rows(read_tsv(candidate_path), read_tsv(fast_path))]
    outdir.mkdir(parents=True, exist_ok=True)
    manifest_path = outdir / "pvrig_teacher_pilot96_manifest.tsv"
    fasta_path = outdir / "pvrig_teacher_pilot96.fasta"
    audit_path = outdir / "selection_audit.json"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(selected)
    with fasta_path.open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")

    hotspot_counts = Counter(row["hotspot_set"] for row in selected)
    backbone_counts = Counter((row["hotspot_set"], row["backbone_index"]) for row in selected)
    stratum_counts = Counter(row["selection_stratum"].split(":", 1)[1] for row in selected)
    audit: dict[str, object] = {
        "status": "PASS",
        "schema_version": "pvrig_teacher_pilot96_selection_audit_v1",
        "seed": SEED,
        "records": len(selected),
        "exact_unique_ids": len({row["candidate_id"] for row in selected}),
        "exact_unique_sequences": len({row["sequence"] for row in selected}),
        "hotspot_counts": dict(sorted(hotspot_counts.items())),
        "stratum_counts": dict(sorted(stratum_counts.items())),
        "represented_backbones": len(backbone_counts),
        "max_candidates_per_hotspot_backbone": max(backbone_counts.values()),
        "cdr3_length_counts": dict(sorted(Counter(len(row["cdr3"]) for row in selected).items())),
        "rfd_distance_bins": dict(sorted(Counter(row["rfd_hotspot_distance_bin"] for row in selected).items())),
        "single_framework_limitation": "All 96 derive from h-NbBCII10 and are pilot-only; they cannot support parent-cluster formal evaluation.",
        "source_sha256": {
            str(candidate_path): sha256_file(candidate_path),
            str(fast_path): sha256_file(fast_path),
        },
        "manifest_sha256": sha256_file(manifest_path),
        "fasta_sha256": sha256_file(fasta_path),
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if hotspot_counts != Counter({key: HOTSPOT_QUOTA for key in "ABCD"}):
        audit["status"] = "FAIL_HOTSPOT_QUOTA"
    if max(backbone_counts.values()) > BACKBONE_CAP:
        audit["status"] = "FAIL_BACKBONE_CAP"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if audit["status"] != "PASS":
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--fast", type=Path, default=DEFAULT_FAST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    print(json.dumps(run(args.candidates, args.fast, args.outdir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
