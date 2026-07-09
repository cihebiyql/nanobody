#!/usr/bin/env python3
"""Prepare the WO2021180205A1 PVRIG VHH positive-control calibration batch."""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "docking" / "success_case_validation"
DEFAULT_OUT_ROOT = ROOT / "docking" / "calibration" / "patent_success_validation"
DEFAULT_FASTA = ROOT / "机制" / "data" / "sequences" / "PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta"
DEFAULT_SERIES = ROOT / "机制" / "data" / "literature" / "PVRIG_case02_success_validation_series.csv"
DEFAULT_ANARCI = (
    ROOT
    / "机制"
    / "data"
    / "literature"
    / "anarci"
    / "PVRIG_case02_vhh_20_30_38_39_151_anarci_imgt_H.csv"
)
DEFAULT_CDR_TABLE = ROOT / "机制" / "data" / "literature" / "PVRIG_case02_vhh_20_30_38_39_151_imgt_cdr_table.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series-csv", type=Path, default=DEFAULT_SERIES)
    parser.add_argument("--fasta", type=Path, default=DEFAULT_FASTA)
    parser.add_argument("--anarci-csv", type=Path, default=DEFAULT_ANARCI)
    parser.add_argument("--cdr-table-csv", type=Path, default=DEFAULT_CDR_TABLE)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--haddock-sampling", default="40")
    parser.add_argument("--top-models", default="10")
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_fasta(path: Path) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    header = ""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header:
                name = header.split("|", 1)[0]
                records[name] = {"header": header, "sequence": "".join(lines)}
            header = line[1:]
            lines = []
        else:
            lines.append(line)
    if header:
        name = header.split("|", 1)[0]
        records[name] = {"header": header, "sequence": "".join(lines)}
    return records


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return cleaned or "unnamed"


def raw_anarci_cdrs(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []

        def extract(row: dict[str, str], start: str, end: str) -> str:
            cols = fields[fields.index(start) : fields.index(end) + 1]
            return "".join(row[col] for col in cols if row.get(col) and row[col] != "-")

        cdrs: dict[str, dict[str, str]] = {}
        for row in reader:
            name = row["Id"].split("|", 1)[0]
            cdrs[name] = {
                "cdr1": extract(row, "27", "38"),
                "cdr2": extract(row, "56", "65"),
                "cdr3": extract(row, "105", "117"),
                "cdr_source": "raw_anarci_imgt_columns_27-38_56-65_105-117",
            }
        return cdrs


def locate_range(sequence: str, motif: str, molecule_name: str, cdr_name: str) -> tuple[str, str]:
    pos = sequence.find(motif)
    if pos < 0:
        raise SystemExit(f"{molecule_name} {cdr_name} does not exact-match FASTA sequence: {motif}")
    start = pos + 1
    end = start + len(motif) - 1
    return f"{start}-{end}", "exact"


def run_prepare(name: str, seq: str, out_root: Path, cdrs: dict[str, str], sampling: str, top_models: str) -> None:
    cmd = [
        sys.executable,
        str(WORKFLOW_DIR / "prepare_candidate_sequence_workflow.py"),
        "--name",
        name,
        "--sequence",
        seq,
        "--out-root",
        str(out_root),
        "--cdr1",
        cdrs["cdr1_range"],
        "--cdr2",
        cdrs["cdr2_range"],
        "--cdr3",
        cdrs["cdr3_range"],
        "--haddock-sampling",
        sampling,
        "--top-models",
        top_models,
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)


def write_one_metadata(workdir: Path, row: dict[str, str]) -> None:
    fields = list(row)
    write_rows(workdir / "calibration_metadata.csv", [row], fields)


def write_batch_scripts(out_root: Path, batch_rows: list[dict[str, str]]) -> None:
    structure_lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    haddock_lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    postprocess_lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    for row in batch_rows:
        workdir = row["workdir"]
        structure_lines.append(f'bash "{workdir}/run_node1_structure_prediction.sh"')
        haddock_lines.append(f'bash "{workdir}/run_node1_haddock3.sh"')
        postprocess_lines.append(
            "python /mnt/d/work/抗体/docking/success_case_validation/process_haddock3_calibration_run.py "
            f'--workdir "{workdir}" --name "{row["calibration_name"]}" '
            f'--cdr1 {row["cdr1_range"]} --cdr2 {row["cdr2_range"]} --cdr3 {row["cdr3_range"]}'
        )
    scripts = {
        "run_all_node1_structure_predictions.sh": structure_lines,
        "run_all_node1_haddock3.sh": haddock_lines,
        "postprocess_all_haddock3_runs.sh": postprocess_lines,
    }
    for filename, lines in scripts.items():
        path = out_root / filename
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o755)


def write_report(out_root: Path, rows: list[dict[str, str]]) -> None:
    families = Counter(row["family"] for row in rows)
    cdr3_mismatches = sum(1 for row in rows if row["raw_anarci_cdr3_equals_existing_cdr_table"] == "no")
    lines = [
        "# Patent Success Series Calibration Batch",
        "",
        "## Result",
        "",
        f"- Prepared calibration workdirs: {len(rows)}",
        f"- Families covered: {', '.join(f'{k}={v}' for k, v in sorted(families.items()))}",
        f"- Raw ANARCI CDR3 exact FASTA matches: {sum(1 for row in rows if row['cdr_exact_match_status'] == 'exact')}/{len(rows)}",
        f"- Existing summarized CDR-table CDR3 mismatches kept as audit warnings: {cdr3_mismatches}",
        "",
        "## Boundary",
        "",
        "- These 11 sequences are positive controls for calibration and leakage exclusion.",
        "- They must not be submitted or ranked as new designs.",
        "- CDR ranges below are sequence-position ranges derived from raw ANARCI IMGT columns.",
        "- `run_node1_structure_prediction.sh` normalizes NanoBodyBuilder2 output to chain A with sequential residue IDs before HADDOCK.",
        "- The generated NanoBodyBuilder2 command uses `-u` to avoid rare ImmuneBuilder/OpenMM sidechain-repair failures; local geometry QC still checks backbone sanity.",
        "",
        "## Batch Commands",
        "",
        "```bash",
        f"bash {out_root}/run_all_node1_structure_predictions.sh",
        f"bash {out_root}/run_all_node1_haddock3.sh",
        f"bash {out_root}/postprocess_all_haddock3_runs.sh",
        "python docking/success_case_validation/check_patent_success_calibration_status.py",
        "python docking/success_case_validation/summarize_patent_success_calibration.py",
        "python docking/success_case_validation/validate_patent_sequence_artifacts.py",
        "```",
        "",
        "## Sequences",
        "",
        "| order | name | family | IC50 nM | Kd M | CDR1 | CDR2 | CDR3 | workdir |",
        "| ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['recommended_order']} | {row['molecule_name']} | {row['family']} | "
            f"{row['blocking_ic50_nm']} | {row['kd_m']} | {row['cdr1_range']} | {row['cdr2_range']} | "
            f"{row['cdr3_range']} | `{row['workdir']}` |"
        )
    lines.extend(
        [
            "",
            "## CDR Audit Note",
            "",
            "The previously summarized IMGT CDR table is retained as source evidence, but this batch uses raw ANARCI column order.",
            "That matters for long CDR3s with insertion columns such as 111A/111B/111C/112C/112B/112A.",
            "",
            "Execution-safe CDR table:",
            "",
            "```text",
            "机制/data/literature/PVRIG_case02_vhh_20_30_38_39_151_raw_anarci_exact_cdr_table.csv",
            "```",
            "",
            "Use `raw_anarci_imgt_cdr*_exact` and `cdr*_range` from that file for scorer",
            "inputs. The older summarized CDR3 column is retained only as an audit/display",
            "field because it differs from raw exact FASTA order for all 30 patent records.",
            "",
        ]
    )
    (out_root / "PATENT_SUCCESS_SERIES_CALIBRATION.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    series_rows = sorted(read_rows(args.series_csv), key=lambda row: int(row["recommended_order"]))
    fasta_records = parse_fasta(args.fasta)
    raw_cdrs = raw_anarci_cdrs(args.anarci_csv)
    existing_cdrs = {row["molecule_name"]: row for row in read_rows(args.cdr_table_csv)}

    batch_rows: list[dict[str, str]] = []
    for series_row in series_rows:
        molecule = series_row["molecule_name"]
        fasta_id = series_row["fasta_id"]
        if "not a new design candidate" not in series_row["suggested_computational_use"]:
            raise SystemExit(f"{molecule} is missing not-a-new-design boundary")
        if fasta_id not in fasta_records:
            raise SystemExit(f"{molecule} fasta_id not found in FASTA: {fasta_id}")
        if molecule not in raw_cdrs:
            raise SystemExit(f"{molecule} missing raw ANARCI row")

        seq = fasta_records[fasta_id]["sequence"]
        cdrs = dict(raw_cdrs[molecule])
        statuses = []
        for key in ["cdr1", "cdr2", "cdr3"]:
            cdr_range, status = locate_range(seq, cdrs[key], molecule, key)
            cdrs[f"{key}_range"] = cdr_range
            statuses.append(status)

        order = int(series_row["recommended_order"])
        calibration_name = f"case02_pos_{order:02d}_{sanitize_name(molecule)}"
        run_prepare(calibration_name, seq, out_root, cdrs, args.haddock_sampling, args.top_models)
        workdir = (out_root / calibration_name).resolve()

        existing = existing_cdrs.get(molecule, {})
        batch_row = {
            "recommended_order": series_row["recommended_order"],
            "calibration_name": calibration_name,
            "molecule_name": molecule,
            "family": series_row["family"],
            "seq_id_no": series_row["seq_id_no"],
            "sequence_type": series_row["sequence_type"],
            "validation_role": series_row["validation_role"],
            "blocking_ic50_nm": series_row["blocking_ic50_nm"],
            "kd_m": series_row["kd_m"],
            "reporter_ec50_nm": series_row["reporter_ec50_nm"],
            "fasta_id": fasta_id,
            "sequence_length": str(len(seq)),
            "cdr_source": cdrs["cdr_source"],
            "cdr1": cdrs["cdr1"],
            "cdr1_range": cdrs["cdr1_range"],
            "cdr2": cdrs["cdr2"],
            "cdr2_range": cdrs["cdr2_range"],
            "cdr3": cdrs["cdr3"],
            "cdr3_range": cdrs["cdr3_range"],
            "cdr_exact_match_status": "exact" if all(status == "exact" for status in statuses) else "non_exact",
            "existing_cdr_table_cdr3": existing.get("cdr3", ""),
            "raw_anarci_cdr3_equals_existing_cdr_table": "yes" if existing.get("cdr3") == cdrs["cdr3"] else "no",
            "workdir": str(workdir),
            "structure_status": "pending",
            "docking_status": "pending",
            "consensus_status": "pending",
            "usage_boundary": "positive_calibration_and_leakage_exclusion_only_not_new_design",
        }
        write_one_metadata(workdir, batch_row)
        batch_rows.append(batch_row)

    fields = list(batch_rows[0])
    write_rows(out_root / "batch_manifest.csv", batch_rows, fields)
    write_rows(out_root / "patent_success_validation_cdr_ranges.csv", batch_rows, fields)
    write_batch_scripts(out_root, batch_rows)
    write_report(out_root, batch_rows)
    print(f"prepared_patent_success_validation_batch={out_root}")
    print(f"rows={len(batch_rows)}")
    print("families=" + ",".join(f"{k}:{v}" for k, v in sorted(Counter(row["family"] for row in batch_rows).items())))


if __name__ == "__main__":
    main()
