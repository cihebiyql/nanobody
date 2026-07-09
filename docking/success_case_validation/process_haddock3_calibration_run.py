#!/usr/bin/env python3
"""Postprocess one PVRIG VHH calibration HADDOCK3 run through both baselines."""

from __future__ import annotations

import argparse
import csv
import gzip
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "docking" / "success_case_validation"
HOTSPOT_CSV = ROOT / "data" / "structures" / "PVRIG_hotspot_set_v1.csv"
REF_8X6B = ROOT / "data" / "structures" / "8X6B.pdb"
REF_9E6Y = ROOT / "data" / "structures" / "9E6Y.pdb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--run-dir", type=Path, help="HADDOCK3 run directory. Default: workdir/haddock3/run_<name>_pvrig_hotspot_test")
    parser.add_argument("--cdr1", required=True)
    parser.add_argument("--cdr2", required=True)
    parser.add_argument("--cdr3", required=True)
    parser.add_argument("--top-n", type=int, default=10)
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def model_sort_key(model: str) -> tuple[int, int, str]:
    match = re.fullmatch(r"cluster_(\d+)_model_(\d+)", model)
    if not match:
        return (999999, 999999, model)
    return (int(match.group(1)), int(match.group(2)), model)


def read_traceback_ranks(run_dir: Path) -> dict[str, str]:
    path = run_dir / "traceback" / "consensus.tsv"
    if not path.exists():
        return {}
    ranks: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            model = row["Model"].removesuffix(".pdb")
            ranks[model] = row.get("6_seletopclusts_rank", "") or row.get("Sum-of-Ranks", "")
    return ranks


def selected_model_paths(run_dir: Path, top_n: int) -> list[tuple[str, Path]]:
    source = run_dir / "6_seletopclusts"
    if not source.exists():
        raise SystemExit(f"missing HADDOCK3 seletopclusts output: {source}")
    paths = list(source.glob("cluster_*_model_*.pdb.gz")) + list(source.glob("cluster_*_model_*.pdb"))
    if not paths:
        raise SystemExit(f"no cluster PDB files found under {source}")
    models: list[tuple[str, Path]] = []
    for path in paths:
        model = path.name
        if model.endswith(".pdb.gz"):
            model = model[: -len(".pdb.gz")]
        elif model.endswith(".pdb"):
            model = model[: -len(".pdb")]
        models.append((model, path))
    return sorted(models, key=lambda item: model_sort_key(item[0]))[:top_n]


def unpack_models(model_paths: list[tuple[str, Path]], out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    models: list[str] = []
    for model, src in model_paths:
        dst = out_dir / f"{model}.pdb"
        if src.suffix == ".gz":
            with gzip.open(src, "rb") as in_fh, dst.open("wb") as out_fh:
                shutil.copyfileobj(in_fh, out_fh)
        else:
            shutil.copy2(src, dst)
        models.append(model)
    return models


def write_rank_csv(path: Path, models: list[str], ranks: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["model", "haddock_rank", "haddock_score"])
        writer.writeheader()
        for index, model in enumerate(models, start=1):
            writer.writerow({"model": model, "haddock_rank": ranks.get(model, str(index)), "haddock_score": ""})


def classify_baseline(workdir: Path, name: str, label: str, cdr_csv: Path, mechanism_csv: Path) -> Path:
    out_csv = workdir / "reports" / f"{name}_{label}_blocker_classification.csv"
    out_md = workdir / "reports" / f"{name}_{label}_blocker_classification.md"
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "apply_blocker_judgment.py"),
            "--occlusion-csv",
            str(cdr_csv),
            "--mechanism-csv",
            str(mechanism_csv),
            "--candidate-name",
            f"{name}_{label}",
            "--format-context",
            "naked_vhh",
            "--out-csv",
            str(out_csv),
            "--out-md",
            str(out_md),
        ]
    )
    return out_csv


def score_baseline(
    models: list[str],
    pose_dir: Path,
    pose_pattern: str,
    output_pose_dir: Path,
    out_dir: Path,
    reference_pdb: Path,
    baseline_label: str,
    reference_pvrig_chain: str,
    reference_pvrl2_chain: str,
    mobile_ref_column: str,
    reference_ref_column: str,
    hotspot_ref_column: str,
    cdr1: str,
    cdr2: str,
    cdr3: str,
    rank_csv: Path,
) -> tuple[Path, Path]:
    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "score_reference_baseline.py"),
            "--models",
            ",".join(models),
            "--pose-dir",
            str(pose_dir),
            "--pose-pattern",
            pose_pattern,
            "--output-pose-dir",
            str(output_pose_dir),
            "--out-dir",
            str(out_dir),
            "--reference-pdb",
            str(reference_pdb),
            "--baseline-label",
            baseline_label,
            "--mobile-pvrig-chain",
            "B",
            "--reference-pvrig-chain",
            reference_pvrig_chain,
            "--vhh-chain",
            "A",
            "--reference-pvrl2-chain",
            reference_pvrl2_chain,
            "--pair-map-csv",
            str(HOTSPOT_CSV),
            "--mobile-ref-column",
            mobile_ref_column,
            "--reference-ref-column",
            reference_ref_column,
            "--hotspots-csv",
            str(HOTSPOT_CSV),
            "--hotspot-ref-column",
            hotspot_ref_column,
            "--cdr1",
            cdr1,
            "--cdr2",
            cdr2,
            "--cdr3",
            cdr3,
            "--rank-score-csv",
            str(rank_csv),
        ]
    )
    mechanism_csv = out_dir / f"haddock3_top_model_mechanism_scores_{baseline_label}.csv"
    cdr_csv = out_dir / f"cdr3_occlusion_summary_{baseline_label}.csv"
    return mechanism_csv, cdr_csv


def main() -> None:
    args = parse_args()
    workdir = args.workdir.resolve()
    run_dir = (args.run_dir or workdir / "haddock3" / f"run_{args.name}_pvrig_hotspot_test").resolve()
    model_paths = selected_model_paths(run_dir, args.top_n)
    models = unpack_models(model_paths, workdir / "haddock3" / "top_models_unzipped")
    rank_csv = workdir / "reports" / "haddock3_model_ranks.csv"
    write_rank_csv(rank_csv, models, read_traceback_ranks(run_dir))

    mech_8, cdr_8 = score_baseline(
        models=models,
        pose_dir=workdir / "haddock3" / "top_models_unzipped",
        pose_pattern="{model}.pdb",
        output_pose_dir=workdir / "haddock3" / "top_models_aligned_to_8x6b",
        out_dir=workdir / "reports" / "8x6b_baseline",
        reference_pdb=REF_8X6B,
        baseline_label="8x6b",
        reference_pvrig_chain="B",
        reference_pvrl2_chain="A",
        mobile_ref_column="pdb_8x6b_ref",
        reference_ref_column="pdb_8x6b_ref",
        hotspot_ref_column="pdb_8x6b_ref",
        cdr1=args.cdr1,
        cdr2=args.cdr2,
        cdr3=args.cdr3,
        rank_csv=rank_csv,
    )
    class_8 = classify_baseline(workdir, args.name, "8x6b", cdr_8, mech_8)

    mech_9, cdr_9 = score_baseline(
        models=models,
        pose_dir=workdir / "haddock3" / "top_models_aligned_to_8x6b",
        pose_pattern="{model}_aligned_to_8x6b.pdb",
        output_pose_dir=workdir / "haddock3" / "top_models_aligned_to_9e6y",
        out_dir=workdir / "reports" / "9e6y_baseline",
        reference_pdb=REF_9E6Y,
        baseline_label="9e6y",
        reference_pvrig_chain="A",
        reference_pvrl2_chain="D",
        mobile_ref_column="pdb_8x6b_ref",
        reference_ref_column="pdb_9e6y_ref",
        hotspot_ref_column="pdb_9e6y_ref",
        cdr1=args.cdr1,
        cdr2=args.cdr2,
        cdr3=args.cdr3,
        rank_csv=rank_csv,
    )
    class_9 = classify_baseline(workdir, args.name, "9e6y", cdr_9, mech_9)

    run(
        [
            sys.executable,
            str(WORKFLOW_DIR / "summarize_multibaseline_judgment.py"),
            "--classification",
            f"8x6b={class_8}",
            "--classification",
            f"9e6y={class_9}",
            "--candidate-name",
            args.name,
            "--out-csv",
            str(workdir / "reports" / f"{args.name}_8x6b_9e6y_consensus.csv"),
            "--out-md",
            str(workdir / "reports" / f"{args.name}_8x6b_9e6y_consensus.md"),
        ]
    )
    print(f"processed_haddock3_calibration_run={workdir}")
    print(f"models={','.join(models)}")


if __name__ == "__main__":
    main()
