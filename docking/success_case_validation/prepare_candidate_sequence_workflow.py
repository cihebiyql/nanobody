#!/usr/bin/env python3
"""Prepare a candidate-sequence workflow scaffold for PVRIG blocker evaluation."""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = ROOT / "docking" / "candidates"
HOTSPOT_CSV = ROOT / "data" / "structures" / "PVRIG_hotspot_set_v1.csv"
PVRIG_8X6B_PDB = ROOT / "docking" / "case02_hr151_pvrig" / "haddock3" / "data" / "pvrig_8x6b_chainB.pdb"
DEFAULT_ANARCI_BIN = ROOT / ".conda-envs" / "ab-data-validator" / "bin" / "ANARCI"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a candidate VHH sequence workflow scaffold for structure, docking, and blocker judgment."
    )
    parser.add_argument("--name", required=True, help="Candidate identifier, e.g. cand001.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sequence", help="Raw VHH amino-acid sequence.")
    group.add_argument("--fasta", type=Path, help="FASTA file containing one VHH sequence.")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_BASE, help=f"Output root. Default: {DEFAULT_BASE}")
    parser.add_argument("--cdr1", default="26-35", help="Candidate VHH CDR1 residue range in modeled numbering.")
    parser.add_argument("--cdr2", default="53-59", help="Candidate VHH CDR2 residue range in modeled numbering.")
    parser.add_argument("--cdr3", default="98-116", help="Candidate VHH CDR3 residue range in modeled numbering.")
    parser.add_argument(
        "--auto-cdr",
        action="store_true",
        help="Derive CDR ranges from local ANARCI IMGT output instead of using --cdr* values.",
    )
    parser.add_argument(
        "--anarci-bin",
        type=Path,
        default=DEFAULT_ANARCI_BIN,
        help=f"ANARCI executable used with --auto-cdr. Default: {DEFAULT_ANARCI_BIN}",
    )
    parser.add_argument(
        "--hmmerpath",
        type=Path,
        help="Optional directory containing hmmscan. By default the ANARCI executable directory is added to PATH.",
    )
    parser.add_argument("--haddock-sampling", default="40", help="HADDOCK rigidbody sampling count for the template cfg.")
    parser.add_argument("--top-models", default="10", help="Number of selected top models in the template cfg.")
    return parser.parse_args()


def read_fasta_sequence(path: Path) -> str:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(">"):
            continue
        lines.append(line)
    return "".join(lines)


def clean_sequence(sequence: str) -> str:
    seq = re.sub(r"\s+", "", sequence).upper()
    if not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWYXBZUO]+", seq):
        raise SystemExit("Sequence contains non-amino-acid characters")
    if len(seq) < 90 or len(seq) > 180:
        print(f"WARNING: VHH-like sequence length is unusual: {len(seq)} aa")
    return seq


def parse_range(text: str) -> list[int]:
    match = re.fullmatch(r"(\d+)-(\d+)", text.strip())
    if not match:
        raise SystemExit(f"Invalid range {text!r}; expected START-END")
    start, end = map(int, match.groups())
    if end < start:
        raise SystemExit(f"Invalid range {text!r}: end < start")
    return list(range(start, end + 1))


def extract_anarci_cdr(row: dict[str, str], fields: list[str], start: str, end: str) -> str:
    cols = fields[fields.index(start) : fields.index(end) + 1]
    return "".join(row[col] for col in cols if row.get(col) and row[col] != "-")


def locate_range(sequence: str, motif: str, label: str) -> str:
    pos = sequence.find(motif)
    if pos < 0:
        raise SystemExit(f"ANARCI {label} does not exact-match the input FASTA sequence: {motif}")
    start = pos + 1
    end = start + len(motif) - 1
    return f"{start}-{end}"


def derive_cdr_ranges_with_anarci(
    name: str,
    sequence: str,
    anarci_bin: Path,
    hmmerpath: Path | None,
) -> tuple[dict[str, str], dict[str, str], str]:
    if not anarci_bin.exists():
        raise SystemExit(f"--auto-cdr requested but ANARCI executable is missing: {anarci_bin}")
    with tempfile.TemporaryDirectory(prefix=f"{name}_anarci_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        fasta = tmpdir / f"{name}.fasta"
        out_prefix = tmpdir / f"{name}_imgt"
        fasta.write_text(f">{name}\n{sequence}\n", encoding="utf-8")
        cmd = [
            str(anarci_bin),
            "-i",
            str(fasta),
            "-o",
            str(out_prefix),
            "-s",
            "imgt",
            "-r",
            "H",
            "--csv",
        ]
        if hmmerpath is not None:
            cmd.extend(["--hmmerpath", str(hmmerpath)])
        env = os.environ.copy()
        env["PATH"] = f"{anarci_bin.parent}:{env.get('PATH', '')}"
        subprocess.run(cmd, cwd=ROOT, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out_csv = tmpdir / f"{name}_imgt_H.csv"
        if not out_csv.exists():
            raise SystemExit(f"ANARCI did not produce heavy-chain CSV: {out_csv}")
        with out_csv.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            rows = list(reader)
        if len(rows) != 1:
            raise SystemExit(f"Expected one ANARCI heavy-chain row, got {len(rows)}")
        row = rows[0]
        cdrs = {
            "cdr1": extract_anarci_cdr(row, fields, "27", "38"),
            "cdr2": extract_anarci_cdr(row, fields, "56", "65"),
            "cdr3": extract_anarci_cdr(row, fields, "105", "117"),
            "hmm_species": row.get("hmm_species", ""),
            "chain_type": row.get("chain_type", ""),
            "e_value": row.get("e-value", ""),
            "score": row.get("score", ""),
            "seqstart_index": row.get("seqstart_index", ""),
            "seqend_index": row.get("seqend_index", ""),
        }
        ranges = {
            "cdr1": locate_range(sequence, cdrs["cdr1"], "CDR1"),
            "cdr2": locate_range(sequence, cdrs["cdr2"], "CDR2"),
            "cdr3": locate_range(sequence, cdrs["cdr3"], "CDR3"),
        }
        return ranges, cdrs, out_csv.read_text(encoding="utf-8")


def hotspot_residues_8x6b() -> list[int]:
    residues: list[int] = []
    with HOTSPOT_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            ref = row.get("pdb_8x6b_ref", "")
            match = re.match(r"B:(\d+)", ref)
            if match:
                value = int(match.group(1))
                if value not in residues:
                    residues.append(value)
    return residues


def write_ambig_tbl(path: Path, cdr_residues: list[int], hotspot_residues: list[int]) -> None:
    lines: list[str] = []
    hotspot_block = "\n        or\n".join(f"       (resi {res} and segid B)" for res in hotspot_residues)
    for cdr_res in cdr_residues:
        lines.extend(
            [
                f"assign (resi {cdr_res} and segid A)",
                "(",
                hotspot_block,
                ") 2.0 2.0 0.0",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_lines(path: Path, values: list[int]) -> None:
    path.write_text("\n".join(str(v) for v in values) + "\n", encoding="utf-8")


def write_haddock_cfg(path: Path, name: str, sampling: str, top_models: str) -> None:
    path.write_text(
        f"""# {name} VHH to PVRIG 8X6B hotspot-guided HADDOCK3 docking template
run_dir = "run_{name}_pvrig_hotspot_test"
mode = "local"
ncores = 8

molecules = [
    "data/{name}_vhh_chainA.pdb",
    "data/pvrig_8x6b_chainB.pdb",
]

[topoaa]

[rigidbody]
ambig_fname = "data/{name}_cdr_to_pvrig_hotspot_ambig.tbl"
tolerance = 5
sampling = {sampling}

[seletop]
select = {top_models}

[flexref]
tolerance = 10
ambig_fname = "data/{name}_cdr_to_pvrig_hotspot_ambig.tbl"

[emref]
ambig_fname = "data/{name}_cdr_to_pvrig_hotspot_ambig.tbl"

[clustfcc]
min_population = 1

[seletopclusts]
top_models = {top_models}
""",
        encoding="utf-8",
    )


def write_node1_commands(path: Path, name: str, seq: str, workdir: Path) -> None:
    remote_root = f"/data/qlyu/projects/pvrig_candidates/{name}"
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

WD={workdir}

# 1) Check GPU first; choose an idle device before longer jobs.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \\
  'nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits'

# 2) Build VHH monomer with NanoBodyBuilder2 on node1.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 'set -euo pipefail
BIN=/data/qlyu/anaconda3/envs/boltz/bin
mkdir -p {remote_root}/monomer
SEQ=\"{seq}\"
# -u avoids an ImmuneBuilder/OpenMM strained-sidechain repair bug observed in
# rare mutant controls; local pdb_geometry_qc.py still checks backbone sanity.
CUDA_VISIBLE_DEVICES=0 PATH=\"$BIN:$PATH\" NanoBodyBuilder2 -H \"$SEQ\" -o {remote_root}/monomer/{name}_nanobodybuilder2.pdb -u --n_threads 4 -v
'

# 3) Copy the monomer PDB back through ssh.exe. Linux scp may not know the
#    Windows SSH alias/proxy for node1.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \\
  'cat {remote_root}/monomer/{name}_nanobodybuilder2.pdb' > "$WD/monomer/{name}_nanobodybuilder2.pdb"

# 4) Normalize the monomer to chain A and sequential residue numbering.
#    The CDR ranges in this workdir are sequence-position ranges.
python /mnt/d/work/抗体/docking/scripts/normalize_pdb_chain.py \\
  --in-pdb "$WD/monomer/{name}_nanobodybuilder2.pdb" \\
  --out-pdb "$WD/haddock3/data/{name}_vhh_chainA.pdb" \\
  --chain-id A \\
  --expected-residue-count {len(seq)}

# 5) Upload the prepared HADDOCK3 input bundle to node1.
tar -C "$WD/haddock3" -cf - . | ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \\
  'mkdir -p {remote_root}/haddock3 && tar -C {remote_root}/haddock3 -xf -'
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def write_haddock3_commands(path: Path, name: str, workdir: Path) -> None:
    remote_root = f"/data/qlyu/projects/pvrig_candidates/{name}"
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

WD={workdir}
REMOTE={remote_root}

# Run HADDOCK3 on node1 after `run_node1_structure_prediction.sh` has uploaded inputs.
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 'set -euo pipefail
cd {remote_root}/haddock3
/data/qlyu/anaconda3/envs/haddock3/bin/haddock3 {name}_pvrig_hotspot_test.cfg
'

# Bring the run directory back for local scoring/postprocessing.
mkdir -p "$WD/haddock3"
ssh.exe -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6 node1 \\
  'cd {remote_root}/haddock3 && tar -cf - run_{name}_pvrig_hotspot_test' | tar -C "$WD/haddock3" -xf -
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def write_postprocess_commands(path: Path, name: str, workdir: Path, cdr1: str, cdr2: str, cdr3: str) -> None:
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

ROOT=/mnt/d/work/抗体
WD={workdir}

# Expected after docking:
#   $WD/haddock3/top_models_aligned_to_8x6b/{{model}}_aligned_to_8x6b.pdb
#   $WD/reports/haddock3_top_model_mechanism_scores.csv
#   $WD/reports/cdr_region_occlusion/cdr3_occlusion_summary.csv

python "$ROOT/docking/success_case_validation/apply_blocker_judgment.py" \\
  --occlusion-csv "$WD/reports/cdr_region_occlusion/cdr3_occlusion_summary.csv" \\
  --mechanism-csv "$WD/reports/haddock3_top_model_mechanism_scores.csv" \\
  --candidate-name {name}_8x6b \\
  --format-context naked_vhh \\
  --out-csv "$WD/reports/{name}_8x6b_blocker_classification.csv" \\
  --out-md "$WD/reports/{name}_8x6b_blocker_classification.md"

# Optional but recommended: once top model names are known, run 9E6Y baseline and combine:
# python "$ROOT/docking/success_case_validation/score_reference_baseline.py" \\
#   --models cluster_1_model_1,cluster_2_model_1 \\
#   --pose-dir "$WD/haddock3/top_models_aligned_to_8x6b" \\
#   --pose-pattern '{{model}}_aligned_to_8x6b.pdb' \\
#   --output-pose-dir "$WD/haddock3/top_models_aligned_to_9e6y" \\
#   --out-dir "$WD/reports/9e6y_baseline" \\
#   --reference-pdb "$ROOT/data/structures/9E6Y.pdb" \\
#   --baseline-label 9e6y \\
#   --mobile-pvrig-chain B \\
#   --reference-pvrig-chain A \\
#   --vhh-chain A \\
#   --reference-pvrl2-chain D \\
#   --pair-map-csv "$ROOT/data/structures/PVRIG_hotspot_set_v1.csv" \\
#   --mobile-ref-column pdb_8x6b_ref \\
#   --reference-ref-column pdb_9e6y_ref \\
#   --hotspots-csv "$ROOT/data/structures/PVRIG_hotspot_set_v1.csv" \\
#   --hotspot-ref-column pdb_9e6y_ref \\
#   --cdr1 {cdr1} --cdr2 {cdr2} --cdr3 {cdr3} \\
#   --rank-score-csv "$WD/reports/haddock3_top_model_mechanism_scores.csv"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def write_readme(path: Path, name: str, seq: str, cdr1: str, cdr2: str, cdr3: str) -> None:
    path.write_text(
        f"""# Candidate sequence workflow: {name}

This workdir is for a candidate VHH sequence entering the PVRIG blocker workflow.

## Input

- Candidate: `{name}`
- Length: {len(seq)} aa
- CDR ranges for first-pass scoring: CDR1 `{cdr1}`, CDR2 `{cdr2}`, CDR3 `{cdr3}`

## What this workflow can decide

It can decide whether docking poses are structurally blocker-like against
PVRIG-PVRL2/CD112 under the success-case-calibrated rules.

It cannot prove experimental blocking. A `BLOCKER_LIKE_A` call means:

```text
pose geometry is consistent with successful PVRIG blocker cases
and should be prioritized for leakage checks, second-baseline scoring, and assay.
```

## Required stages

1. Sequence sanity and optional DeepNano binding-like prescreen.
2. VHH monomer prediction with NanoBodyBuilder2.
3. Hotspot/CDR-guided docking to fixed PVRIG.
4. 8X6B PVRL2 overlay occlusion scoring.
5. 9E6Y PVRL2 overlay occlusion scoring.
6. Multi-baseline consensus classification.
7. Positive-control leakage exclusion against HR-151/Tab5/known positives.

## Files generated here

    - `inputs/{name}_vhh.fasta`
    - `inputs/{name}_cdr_ranges.csv`
    - `haddock3/{name}_pvrig_hotspot_test.cfg`
- `haddock3/data/{name}_cdr_to_pvrig_hotspot_ambig.tbl`
- `run_node1_structure_prediction.sh`
- `postprocess_after_docking.sh`

## Current caution

    The workflow has learned other successful cases as rules plus the completed
    WO2021180205A1 VHH calibration batch. Non-VHH cases still influence the
    decision through anti-overfit, Fc/NK, format, CD226/TIGIT, and
    binder-vs-blocker criteria.
""",
        encoding="utf-8",
    )


def write_cdr_metadata(path: Path, name: str, source: str, ranges: dict[str, str], cdrs: dict[str, str]) -> None:
    fields = [
        "candidate_name",
        "cdr_source",
        "cdr1_range",
        "cdr2_range",
        "cdr3_range",
        "raw_anarci_imgt_cdr1_exact",
        "raw_anarci_imgt_cdr2_exact",
        "raw_anarci_imgt_cdr3_exact",
        "hmm_species",
        "chain_type",
        "e_value",
        "score",
        "seqstart_index",
        "seqend_index",
    ]
    row = {
        "candidate_name": name,
        "cdr_source": source,
        "cdr1_range": ranges["cdr1"],
        "cdr2_range": ranges["cdr2"],
        "cdr3_range": ranges["cdr3"],
        "raw_anarci_imgt_cdr1_exact": cdrs.get("cdr1", ""),
        "raw_anarci_imgt_cdr2_exact": cdrs.get("cdr2", ""),
        "raw_anarci_imgt_cdr3_exact": cdrs.get("cdr3", ""),
        "hmm_species": cdrs.get("hmm_species", ""),
        "chain_type": cdrs.get("chain_type", ""),
        "e_value": cdrs.get("e_value", ""),
        "score": cdrs.get("score", ""),
        "seqstart_index": cdrs.get("seqstart_index", ""),
        "seqend_index": cdrs.get("seqend_index", ""),
    }
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def main() -> None:
    args = parse_args()
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.name).strip("_")
    if not name:
        raise SystemExit("Candidate name becomes empty after sanitization")
    seq = clean_sequence(args.sequence if args.sequence else read_fasta_sequence(args.fasta))
    cdr_ranges = {"cdr1": args.cdr1, "cdr2": args.cdr2, "cdr3": args.cdr3}
    cdr_values: dict[str, str] = {}
    cdr_source = "manual_or_default_ranges"
    raw_anarci_csv_text = ""
    if args.auto_cdr:
        cdr_ranges, cdr_values, raw_anarci_csv_text = derive_cdr_ranges_with_anarci(
            name, seq, args.anarci_bin, args.hmmerpath
        )
        cdr_source = "raw_anarci_imgt_columns_27-38_56-65_105-117_exact_fasta_match"
    workdir = args.out_root / name
    for subdir in [
        "inputs",
        "monomer",
        "haddock3/data",
        "haddock3/top_models_aligned_to_8x6b",
        "haddock3/top_models_aligned_to_9e6y",
        "reports/cdr_region_occlusion",
        "reports/9e6y_baseline",
    ]:
        (workdir / subdir).mkdir(parents=True, exist_ok=True)
    workdir = workdir.resolve()
    (workdir / "inputs" / f"{name}_vhh.fasta").write_text(f">{name}|candidate_vhh\n{seq}\n", encoding="utf-8")
    write_cdr_metadata(workdir / "inputs" / f"{name}_cdr_ranges.csv", name, cdr_source, cdr_ranges, cdr_values)
    if raw_anarci_csv_text:
        (workdir / "inputs" / f"{name}_anarci_imgt_H.csv").write_text(raw_anarci_csv_text, encoding="utf-8")

    cdr_residues = parse_range(cdr_ranges["cdr1"]) + parse_range(cdr_ranges["cdr2"]) + parse_range(cdr_ranges["cdr3"])
    hotspots = hotspot_residues_8x6b()
    write_lines(workdir / "haddock3" / "data" / f"{name}_cdr_residues_seq_numbering.txt", cdr_residues)
    write_lines(workdir / "haddock3" / "data" / "hotspot_residues_8x6b.txt", hotspots)
    write_ambig_tbl(workdir / "haddock3" / "data" / f"{name}_cdr_to_pvrig_hotspot_ambig.tbl", cdr_residues, hotspots)
    shutil.copy2(PVRIG_8X6B_PDB, workdir / "haddock3" / "data" / "pvrig_8x6b_chainB.pdb")
    write_haddock_cfg(workdir / "haddock3" / f"{name}_pvrig_hotspot_test.cfg", name, args.haddock_sampling, args.top_models)
    write_node1_commands(workdir / "run_node1_structure_prediction.sh", name, seq, workdir)
    write_haddock3_commands(workdir / "run_node1_haddock3.sh", name, workdir)
    write_postprocess_commands(
        workdir / "postprocess_after_docking.sh",
        name,
        workdir,
        cdr_ranges["cdr1"],
        cdr_ranges["cdr2"],
        cdr_ranges["cdr3"],
    )
    write_readme(workdir / "README.md", name, seq, cdr_ranges["cdr1"], cdr_ranges["cdr2"], cdr_ranges["cdr3"])
    print(f"prepared candidate workflow: {workdir}")
    print(f"sequence_length={len(seq)}")
    print(f"cdr_source={cdr_source}")
    print(f"cdr1={cdr_ranges['cdr1']} cdr2={cdr_ranges['cdr2']} cdr3={cdr_ranges['cdr3']}")
    print(f"cdr_residue_count={len(cdr_residues)} hotspot_count={len(hotspots)}")


if __name__ == "__main__":
    main()
