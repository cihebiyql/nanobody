#!/usr/bin/env python3
"""Freeze the 47 protocol-regression control monomers."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from common import atomic_write_text, is_standard_atom_line, project_root, sha256_file, write_json, write_tsv

PATENT_ROOT = Path("/mnt/d/work/抗体/docking/calibration/patent_success_validation")
MUTANT_ROOT = Path("/mnt/d/work/抗体/docking/calibration/mutant_validation_panel/workdirs")
EXPECTED_PATENT = 11
EXPECTED_MUTANT = 36
FIELDNAMES = [
    "control_id",
    "control_index",
    "source_panel",
    "source_case_id",
    "source_monomer_file",
    "source_path",
    "frozen_monomer_path",
    "sha256",
    "size_bytes",
    "atom_count",
    "chain_ids",
]


def root() -> Path:
    return Path(__import__("os").environ.get("PVRIG_PROJECT_ROOT", project_root())).resolve()


def sanitize(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def discover(panel: str, source_root: Path, expected_count: int) -> list[Path]:
    paths = sorted(source_root.glob("*/monomer/*.pdb"), key=lambda p: (p.parent.parent.name, p.name))
    if len(paths) != expected_count:
        raise RuntimeError(
            f"{panel} control source expected {expected_count} monomer PDBs, found {len(paths)} under {source_root}"
        )
    return paths


def pdb_stats(path: Path) -> tuple[int, str]:
    chains: set[str] = set()
    atom_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if is_standard_atom_line(line):
                atom_count += 1
                if len(line) > 21:
                    chains.add(line[21].strip() or "_")
    if atom_count == 0:
        raise RuntimeError(f"no standard amino-acid ATOM records in {path}")
    return atom_count, ",".join(sorted(chains))


def atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.tmp")
    try:
        shutil.copyfile(src, tmp)
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)


def build() -> list[dict[str, str]]:
    patent_root = Path(__import__("os").environ.get("PVRIG_PATENT_CONTROL_ROOT", PATENT_ROOT))
    mutant_root = Path(__import__("os").environ.get("PVRIG_MUTANT_CONTROL_ROOT", MUTANT_ROOT))
    sources = [("patent_success_validation", discover("patent", patent_root, EXPECTED_PATENT))]
    sources.append(("mutant_validation_panel", discover("mutant", mutant_root, EXPECTED_MUTANT)))

    rows: list[dict[str, str]] = []
    out_dir = root() / "inputs" / "control_monomers"
    index = 0
    for source_panel, paths in sources:
        prefix = "PATENT" if source_panel.startswith("patent") else "MUTANT"
        for local_index, src in enumerate(paths, start=1):
            index += 1
            case_id = src.parent.parent.name
            control_id = f"CTRL_{prefix}_{local_index:03d}_{sanitize(case_id)}"
            frozen = out_dir / f"{control_id}.pdb"
            atomic_copy(src, frozen)
            src_hash = sha256_file(src)
            frozen_hash = sha256_file(frozen)
            if src_hash != frozen_hash:
                raise RuntimeError(f"copy hash mismatch for {src}")
            atom_count, chain_ids = pdb_stats(frozen)
            rows.append(
                {
                    "control_id": control_id,
                    "control_index": str(index),
                    "source_panel": source_panel,
                    "source_case_id": case_id,
                    "source_monomer_file": src.name,
                    "source_path": str(src),
                    "frozen_monomer_path": str(frozen.relative_to(root())),
                    "sha256": frozen_hash,
                    "size_bytes": str(frozen.stat().st_size),
                    "atom_count": str(atom_count),
                    "chain_ids": chain_ids,
                }
            )
    if len(rows) != EXPECTED_PATENT + EXPECTED_MUTANT:
        raise RuntimeError(f"expected 47 controls, built {len(rows)}")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="inputs/calibration_controls_47.tsv")
    parser.add_argument("--summary", default="reports/control_manifest_summary.json")
    args = parser.parse_args(argv)
    try:
        rows = build()
        write_tsv(root() / args.output, rows, FIELDNAMES)
        summary = {
            "status": "OK",
            "control_count": len(rows),
            "patent_count": sum(1 for r in rows if r["source_panel"] == "patent_success_validation"),
            "mutant_count": sum(1 for r in rows if r["source_panel"] == "mutant_validation_panel"),
            "output": args.output,
            "sha256": sha256_file(root() / args.output),
        }
        write_json(root() / args.summary, summary)
        return 0
    except Exception as exc:  # deterministic non-zero failure with no traceback noise
        atomic_write_text(root() / "reports" / "control_manifest_error.txt", f"ERROR: {exc}\n")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
