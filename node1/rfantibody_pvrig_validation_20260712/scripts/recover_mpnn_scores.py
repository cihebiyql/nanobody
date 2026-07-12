#!/usr/bin/env python3
"""Recover ProteinMPNN negative-log-likelihood scores from RFantibody logs."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ATTEMPT_RE = re.compile(r"Attempting pose: .*?/design_(\d+)\.pdb\s*$")
SCORE_PREFIX = "sequence_optimize: "


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_log(hotspot_set: str, path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current_backbone: int | None = None
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            match = ATTEMPT_RE.search(line)
            if match:
                current_backbone = int(match.group(1))
                continue
            if not line.startswith(SCORE_PREFIX):
                continue
            if current_backbone is None:
                raise ValueError(f"{path}:{line_number}: score list without preceding Attempting pose")
            parsed = ast.literal_eval(line[len(SCORE_PREFIX) :])
            if not isinstance(parsed, list):
                raise ValueError(f"{path}:{line_number}: score payload is not a list")
            for mpnn_index, item in enumerate(parsed):
                if not isinstance(item, tuple) or len(item) != 2:
                    raise ValueError(f"{path}:{line_number}: malformed score tuple {item!r}")
                sequence, score = str(item[0]), float(item[1])
                if not math.isfinite(score):
                    raise ValueError(f"{path}:{line_number}: non-finite score")
                rows.append(
                    {
                        "hotspot_set": hotspot_set,
                        "backbone_index": current_backbone,
                        "mpnn_index": mpnn_index,
                        "sequence": sequence,
                        "mpnn_nll_score": score,
                        "source_log": str(path),
                        "source_line": line_number,
                    }
                )
            current_backbone = None
    return rows


def write_tsv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def recover(
    final_tsv: Path,
    logs: dict[str, Path],
    output_dir: Path,
    *,
    expected_per_set: int | None,
    expected_final: int | None,
) -> dict[str, object]:
    all_rows: list[dict[str, object]] = []
    log_hashes: dict[str, str] = {}
    for hotspot_set, path in sorted(logs.items()):
        parsed = parse_log(hotspot_set, path)
        if expected_per_set is not None and len(parsed) != expected_per_set:
            raise ValueError(f"set {hotspot_set}: expected {expected_per_set} log records, found {len(parsed)}")
        all_rows.extend(parsed)
        log_hashes[hotspot_set] = sha256_file(path)

    key_to_score: dict[tuple[str, int, int], dict[str, object]] = {}
    by_backbone: defaultdict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in all_rows:
        key = (str(row["hotspot_set"]), int(row["backbone_index"]), int(row["mpnn_index"]))
        if key in key_to_score:
            raise ValueError(f"duplicate ProteinMPNN score key: {key}")
        key_to_score[key] = row
        by_backbone[key[:2]].append(row)

    for backbone_rows in by_backbone.values():
        for rank, row in enumerate(sorted(backbone_rows, key=lambda item: float(item["mpnn_nll_score"])), start=1):
            row["mpnn_rank_within_backbone"] = rank

    with final_tsv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        final_rows = list(reader)
    if expected_final is not None and len(final_rows) != expected_final:
        raise ValueError(f"expected {expected_final} final records, found {len(final_rows)}")

    selected_rows: list[dict[str, object]] = []
    for row in final_rows:
        key = (row["hotspot_set"], int(row["backbone_index"]), int(row["mpnn_index"]))
        score_row = key_to_score.get(key)
        if score_row is None:
            raise ValueError(f"final candidate missing from ProteinMPNN logs: {row['candidate_id']} key={key}")
        if row["sequence"].strip().upper() != score_row["sequence"]:
            raise ValueError(f"sequence mismatch for final candidate {row['candidate_id']}")
        selected_rows.append(
            {
                "candidate_id": row["candidate_id"],
                "hotspot_set": row["hotspot_set"],
                "backbone_index": int(row["backbone_index"]),
                "mpnn_index": int(row["mpnn_index"]),
                "sequence": row["sequence"],
                "cdr1": row.get("cdr1", ""),
                "cdr2": row.get("cdr2", ""),
                "cdr3": row.get("cdr3", ""),
                "mpnn_nll_score": score_row["mpnn_nll_score"],
                "mpnn_rank_within_backbone": score_row["mpnn_rank_within_backbone"],
                "rfd_mindist": row.get("rfd_mindist", ""),
                "rfd_averagemin": row.get("rfd_averagemin", ""),
                "mpnn_pdb": row.get("mpnn_pdb", ""),
            }
        )

    all_rows.sort(key=lambda row: (str(row["hotspot_set"]), int(row["backbone_index"]), int(row["mpnn_index"])))
    selected_rows.sort(key=lambda row: str(row["candidate_id"]))
    all_fields = [
        "hotspot_set",
        "backbone_index",
        "mpnn_index",
        "sequence",
        "mpnn_nll_score",
        "mpnn_rank_within_backbone",
        "source_log",
        "source_line",
    ]
    selected_fields = [
        "candidate_id",
        "hotspot_set",
        "backbone_index",
        "mpnn_index",
        "sequence",
        "cdr1",
        "cdr2",
        "cdr3",
        "mpnn_nll_score",
        "mpnn_rank_within_backbone",
        "rfd_mindist",
        "rfd_averagemin",
        "mpnn_pdb",
    ]
    all_path = output_dir / "mpnn_scores_all.tsv"
    selected_path = output_dir / "mpnn_scores_selected.tsv"
    write_tsv(all_path, all_rows, all_fields)
    write_tsv(selected_path, selected_rows, selected_fields)

    score_values = [float(row["mpnn_nll_score"]) for row in all_rows]
    summary: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score_definition": "mean masked negative log probability; lower is better",
        "source_final_tsv": str(final_tsv),
        "source_final_tsv_sha256": sha256_file(final_tsv),
        "source_log_sha256": log_hashes,
        "raw_score_records": len(all_rows),
        "selected_score_records": len(selected_rows),
        "unique_backbones": len(by_backbone),
        "records_by_set": dict(sorted(Counter(str(row["hotspot_set"]) for row in all_rows).items())),
        "score_min": min(score_values),
        "score_max": max(score_values),
        "all_checks_passed": True,
        "scientific_boundary": "ProteinMPNN NLL is a sequence-structure compatibility score, not binding affinity or blocker evidence.",
    }
    summary_path = output_dir / "mpnn_score_recovery_summary.json"
    temporary = summary_path.with_suffix(summary_path.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, summary_path)
    return summary


def parse_log_args(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name or not path:
            raise ValueError(f"invalid --log value: {value!r}")
        result[name] = Path(path)
    if not result:
        raise ValueError("at least one --log SET=PATH is required")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("final_tsv", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--log", action="append", default=[], metavar="SET=PATH")
    parser.add_argument("--expected-per-set", type=int)
    parser.add_argument("--expected-final", type=int)
    args = parser.parse_args()
    summary = recover(
        args.final_tsv,
        parse_log_args(args.log),
        args.output_dir,
        expected_per_set=args.expected_per_set,
        expected_final=args.expected_final,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

