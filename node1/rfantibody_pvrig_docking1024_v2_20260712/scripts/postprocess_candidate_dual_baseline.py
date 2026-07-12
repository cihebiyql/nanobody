#!/usr/bin/env python3
"""Score one completed V2 HADDOCK run against 8X6B and 9E6Y baselines."""

from __future__ import annotations

import argparse
import csv
import gzip
import re
import shutil
import subprocess
import sys
from pathlib import Path


HELPERS = Path(__file__).resolve().parent / "postprocess_helpers"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--cdr1", required=True)
    parser.add_argument("--cdr2", required=True)
    parser.add_argument("--cdr3", required=True)
    parser.add_argument("--top-n", type=int, default=4)
    return parser.parse_args()


def model_sort_key(name: str) -> tuple[int, int, str]:
    match = re.fullmatch(r"cluster_(\d+)_model_(\d+)", name)
    return (int(match.group(1)), int(match.group(2)), name) if match else (999999, 999999, name)


def selected_models(run_dir: Path, limit: int) -> list[tuple[str, Path]]:
    selected = run_dir / "6_seletopclusts"
    paths = list(selected.glob("cluster_*_model_*.pdb")) + list(selected.glob("cluster_*_model_*.pdb.gz"))
    by_name: dict[str, Path] = {}
    for path in paths:
        name = path.name.removesuffix(".gz").removesuffix(".pdb")
        current = by_name.get(name)
        if current is None or path.suffix == ".gz":
            by_name[name] = path
    models = sorted(by_name.items(), key=lambda item: model_sort_key(item[0]))[:limit]
    if not models:
        raise ValueError(f"no selected HADDOCK models in {selected}")
    return models


def unpack(models: list[tuple[str, Path]], output: Path) -> list[str]:
    output.mkdir(parents=True, exist_ok=True)
    names = []
    for name, source in models:
        destination = output / f"{name}.pdb"
        if source.suffix == ".gz":
            with gzip.open(source, "rb") as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            shutil.copy2(source, destination)
        names.append(name)
    return names


def haddock_score(path: Path) -> str:
    lines = gzip.open(path, "rt", encoding="ascii", errors="replace") if path.suffix == ".gz" else path.open(encoding="ascii", errors="replace")
    with lines as handle:
        for line in handle:
            match = re.match(r"REMARK\s+(?:HADDOCK\s+)?score:\s*([-+0-9.eE]+)", line, re.I)
            if match:
                return match.group(1)
    return ""


def traceback_ranks(run_dir: Path) -> dict[str, str]:
    path = run_dir / "traceback" / "consensus.tsv"
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["Model"].removesuffix(".pdb"): row.get("6_seletopclusts_rank", "") or row.get("Sum-of-Ranks", "")
            for row in csv.DictReader(handle, delimiter="\t")
        }


def write_rank_csv(path: Path, models: list[tuple[str, Path]], ranks: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model", "haddock_rank", "haddock_score"])
        writer.writeheader()
        for index, (name, source) in enumerate(models, start=1):
            writer.writerow({"model": name, "haddock_rank": ranks.get(name, str(index)), "haddock_score": haddock_score(source)})


def run(command: list[str], root: Path) -> None:
    subprocess.run(command, cwd=root, check=True)


def score_baseline(
    root: Path,
    work: Path,
    names: list[str],
    pose_dir: Path,
    pose_pattern: str,
    output_pose_dir: Path,
    report_dir: Path,
    reference: Path,
    label: str,
    ref_pvrig_chain: str,
    ref_pvrl2_chain: str,
    mobile_ref_column: str,
    reference_ref_column: str,
    hotspot_ref_column: str,
    cdr1: str,
    cdr2: str,
    cdr3: str,
    rank_csv: Path,
) -> tuple[Path, Path]:
    hotspot_csv = root / "inputs/docking/PVRIG_hotspot_set_v1.csv"
    run(
        [
            sys.executable,
            str(HELPERS / "score_reference_baseline.py"),
            "--models", ",".join(names),
            "--pose-dir", str(pose_dir),
            "--pose-pattern", pose_pattern,
            "--output-pose-dir", str(output_pose_dir),
            "--out-dir", str(report_dir),
            "--reference-pdb", str(reference),
            "--baseline-label", label,
            "--mobile-pvrig-chain", "T",
            "--reference-pvrig-chain", ref_pvrig_chain,
            "--vhh-chain", "A",
            "--reference-pvrl2-chain", ref_pvrl2_chain,
            "--pair-map-csv", str(hotspot_csv),
            "--mobile-ref-column", mobile_ref_column,
            "--reference-ref-column", reference_ref_column,
            "--hotspots-csv", str(hotspot_csv),
            "--hotspot-ref-column", hotspot_ref_column,
            "--cdr1", cdr1,
            "--cdr2", cdr2,
            "--cdr3", cdr3,
            "--rank-score-csv", str(rank_csv),
        ],
        root,
    )
    return (
        report_dir / f"haddock3_top_model_mechanism_scores_{label}.csv",
        report_dir / f"cdr3_occlusion_summary_{label}.csv",
    )


def classify(root: Path, candidate: str, label: str, mechanism: Path, occlusion: Path, reports: Path) -> Path:
    output = reports / f"{candidate}_{label}_blocker_classification.csv"
    run(
        [
            sys.executable,
            str(HELPERS / "apply_blocker_judgment.py"),
            "--occlusion-csv", str(occlusion),
            "--mechanism-csv", str(mechanism),
            "--candidate-name", f"{candidate}_{label}",
            "--format-context", "naked_vhh",
            "--out-csv", str(output),
            "--out-md", str(reports / f"{candidate}_{label}_blocker_classification.md"),
        ],
        root,
    )
    return output


def main() -> int:
    args = parse_args()
    root = args.run_root.resolve()
    candidate = args.candidate_id
    run_dir = root / "docking/haddock" / candidate / f"run_{candidate}_pvrig_8x6b_full_interface"
    work = root / "docking/postprocessed" / candidate
    reports = work / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    model_paths = selected_models(run_dir, args.top_n)
    names = unpack(model_paths, work / "haddock3/top_models_unzipped")
    rank_csv = reports / "haddock3_model_ranks.csv"
    write_rank_csv(rank_csv, model_paths, traceback_ranks(run_dir))

    mechanism8, occlusion8 = score_baseline(
        root, work, names,
        work / "haddock3/top_models_unzipped", "{model}.pdb",
        work / "haddock3/top_models_aligned_to_8x6b", reports / "8x6b_baseline",
        root / "inputs/docking/8X6B.pdb", "8x6b", "B", "A",
        "pdb_8x6b_ref", "pdb_8x6b_ref", "pdb_8x6b_ref",
        args.cdr1, args.cdr2, args.cdr3, rank_csv,
    )
    class8 = classify(root, candidate, "8x6b", mechanism8, occlusion8, reports)
    mechanism9, occlusion9 = score_baseline(
        root, work, names,
        work / "haddock3/top_models_aligned_to_8x6b", "{model}_aligned_to_8x6b.pdb",
        work / "haddock3/top_models_aligned_to_9e6y", reports / "9e6y_baseline",
        root / "inputs/docking/9E6Y.pdb", "9e6y", "A", "D",
        "pdb_8x6b_ref", "pdb_9e6y_ref", "pdb_9e6y_ref",
        args.cdr1, args.cdr2, args.cdr3, rank_csv,
    )
    class9 = classify(root, candidate, "9e6y", mechanism9, occlusion9, reports)
    run(
        [
            sys.executable,
            str(HELPERS / "summarize_multibaseline_judgment.py"),
            "--classification", f"8x6b={class8}",
            "--classification", f"9e6y={class9}",
            "--candidate-name", candidate,
            "--out-csv", str(reports / f"{candidate}_8x6b_9e6y_consensus.csv"),
            "--out-md", str(reports / f"{candidate}_8x6b_9e6y_consensus.md"),
        ],
        root,
    )
    print(f"candidate={candidate} models={len(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
