#!/usr/bin/env python3
"""Validate Case02 patent sequence, CDR, and calibration-batch artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FASTA = ROOT / "机制" / "data" / "sequences" / "PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta"
DEFAULT_MAPPING = ROOT / "机制" / "data" / "literature" / "PVRIG_case02_vhh_20_30_38_39_151_sequence_mapping.csv"
DEFAULT_SUMMARY_CDR = ROOT / "机制" / "data" / "literature" / "PVRIG_case02_vhh_20_30_38_39_151_imgt_cdr_table.csv"
DEFAULT_RAW_ANARCI = ROOT / "机制" / "data" / "literature" / "anarci" / "PVRIG_case02_vhh_20_30_38_39_151_anarci_imgt_H.csv"
DEFAULT_RAW_CDR_OUT = ROOT / "机制" / "data" / "literature" / "PVRIG_case02_vhh_20_30_38_39_151_raw_anarci_exact_cdr_table.csv"
DEFAULT_SERIES = ROOT / "机制" / "data" / "literature" / "PVRIG_case02_success_validation_series.csv"
DEFAULT_BATCH = ROOT / "docking" / "calibration" / "patent_success_validation" / "batch_manifest.csv"
DEFAULT_STATUS = ROOT / "docking" / "calibration" / "patent_success_validation" / "batch_status.csv"
DEFAULT_POSITIVES = ROOT / "positives" / "known_positive_antibodies.fasta"


RAW_CDR_FIELDS = [
    "molecule_name",
    "family",
    "seq_id_no",
    "sequence_type",
    "numbering_scheme",
    "numbering_status",
    "raw_anarci_imgt_cdr1_exact",
    "raw_anarci_imgt_cdr2_exact",
    "raw_anarci_imgt_cdr3_exact",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "cdr1_exact_in_fasta",
    "cdr2_exact_in_fasta",
    "cdr3_exact_in_fasta",
    "summary_cdr1",
    "summary_cdr2",
    "summary_cdr3_display",
    "summary_cdr3_equals_raw_exact",
    "notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fasta", type=Path, default=DEFAULT_FASTA)
    parser.add_argument("--mapping-csv", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--summary-cdr-csv", type=Path, default=DEFAULT_SUMMARY_CDR)
    parser.add_argument("--raw-anarci-csv", type=Path, default=DEFAULT_RAW_ANARCI)
    parser.add_argument("--raw-cdr-out", type=Path, default=DEFAULT_RAW_CDR_OUT)
    parser.add_argument("--success-series-csv", type=Path, default=DEFAULT_SERIES)
    parser.add_argument("--batch-manifest-csv", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--batch-status-csv", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--positives-fasta", type=Path, default=DEFAULT_POSITIVES)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    header = ""
    seq_parts: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header:
                records[header] = "".join(seq_parts)
            header = line[1:]
            seq_parts = []
        else:
            seq_parts.append(line)
    if header:
        records[header] = "".join(seq_parts)
    return records


def short_id(header: str) -> str:
    return header.split("|", 1)[0]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def raw_anarci_cdrs(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []

        def extract(row: dict[str, str], start: str, end: str) -> str:
            cols = fields[fields.index(start) : fields.index(end) + 1]
            return "".join(row[col] for col in cols if row.get(col) and row[col] != "-")

        cdrs: dict[str, dict[str, str]] = {}
        for row in reader:
            name = short_id(row["Id"])
            cdrs[name] = {
                "raw_anarci_imgt_cdr1_exact": extract(row, "27", "38"),
                "raw_anarci_imgt_cdr2_exact": extract(row, "56", "65"),
                "raw_anarci_imgt_cdr3_exact": extract(row, "105", "117"),
            }
        return cdrs


def locate(sequence: str, motif: str) -> tuple[str, str]:
    pos = sequence.find(motif)
    if pos < 0:
        return "", "no"
    start = pos + 1
    end = start + len(motif) - 1
    return f"{start}-{end}", "yes"


def write_raw_cdr_table(
    path: Path,
    fasta_by_name: dict[str, str],
    mapping_rows: list[dict[str, str]],
    summary_rows: dict[str, dict[str, str]],
    raw_cdrs: dict[str, dict[str, str]],
) -> tuple[int, int]:
    rows: list[dict[str, str]] = []
    mismatch_count = 0
    exact_cdr3_count = 0
    for mapping in mapping_rows:
        name = mapping["molecule_name"]
        seq = fasta_by_name[name]
        raw = raw_cdrs[name]
        summary = summary_rows.get(name, {})
        cdr1_range, cdr1_ok = locate(seq, raw["raw_anarci_imgt_cdr1_exact"])
        cdr2_range, cdr2_ok = locate(seq, raw["raw_anarci_imgt_cdr2_exact"])
        cdr3_range, cdr3_ok = locate(seq, raw["raw_anarci_imgt_cdr3_exact"])
        same_cdr3 = summary.get("cdr3", "") == raw["raw_anarci_imgt_cdr3_exact"]
        mismatch_count += 0 if same_cdr3 else 1
        exact_cdr3_count += 1 if cdr3_ok == "yes" else 0
        rows.append(
            {
                "molecule_name": name,
                "family": mapping["family"],
                "seq_id_no": mapping["seq_id_no"],
                "sequence_type": mapping["sequence_type"],
                "numbering_scheme": "IMGT",
                "numbering_status": "anarci_success",
                "raw_anarci_imgt_cdr1_exact": raw["raw_anarci_imgt_cdr1_exact"],
                "raw_anarci_imgt_cdr2_exact": raw["raw_anarci_imgt_cdr2_exact"],
                "raw_anarci_imgt_cdr3_exact": raw["raw_anarci_imgt_cdr3_exact"],
                "cdr1_range": cdr1_range,
                "cdr2_range": cdr2_range,
                "cdr3_range": cdr3_range,
                "cdr1_exact_in_fasta": cdr1_ok,
                "cdr2_exact_in_fasta": cdr2_ok,
                "cdr3_exact_in_fasta": cdr3_ok,
                "summary_cdr1": summary.get("cdr1", ""),
                "summary_cdr2": summary.get("cdr2", ""),
                "summary_cdr3_display": summary.get("cdr3", ""),
                "summary_cdr3_equals_raw_exact": "yes" if same_cdr3 else "no",
                "notes": (
                    "Use raw_anarci_imgt_cdr*_exact and cdr*_range for scorer inputs; "
                    "summary_cdr3_display is retained only as prior display/audit evidence."
                ),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RAW_CDR_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return exact_cdr3_count, mismatch_count


def main() -> None:
    args = parse_args()
    fasta_records = parse_fasta(args.fasta)
    fasta_by_name = {short_id(header): seq for header, seq in fasta_records.items()}
    mapping_rows = read_csv(args.mapping_csv)
    summary_rows = {row["molecule_name"]: row for row in read_csv(args.summary_cdr_csv)}
    raw_cdrs = raw_anarci_cdrs(args.raw_anarci_csv)
    series_rows = read_csv(args.success_series_csv)
    batch_rows = read_csv(args.batch_manifest_csv)
    status_rows = read_csv(args.batch_status_csv)

    require(len(fasta_by_name) == 30, f"expected 30 FASTA records, got {len(fasta_by_name)}")
    require(len(mapping_rows) == 30, f"expected 30 mapping rows, got {len(mapping_rows)}")
    require(len(summary_rows) == 30, f"expected 30 summary CDR rows, got {len(summary_rows)}")
    require(len(raw_cdrs) == 30, f"expected 30 raw ANARCI rows, got {len(raw_cdrs)}")
    require(len(series_rows) == 11, f"expected 11 success-series rows, got {len(series_rows)}")
    require(len(batch_rows) == 11, f"expected 11 batch rows, got {len(batch_rows)}")
    require(len(status_rows) == 11, f"expected 11 status rows, got {len(status_rows)}")

    mapping_by_name = {row["molecule_name"]: row for row in mapping_rows}
    require(set(mapping_by_name) == set(fasta_by_name), "mapping IDs do not exactly match FASTA IDs")
    require(set(summary_rows) == set(fasta_by_name), "summary CDR IDs do not exactly match FASTA IDs")
    require(set(raw_cdrs) == set(fasta_by_name), "raw ANARCI IDs do not exactly match FASTA IDs")
    for name, row in mapping_by_name.items():
        require(row["sequence"] == fasta_by_name[name], f"mapping sequence mismatch for {name}")
        require(row["sha256"] == sha256_text(row["sequence"]), f"mapping sha256 mismatch for {name}")

    expected_series_ids = [
        "PVRIG-151_HR151",
        "PVRIG-20",
        "PVRIG-30",
        "PVRIG-38",
        "PVRIG-39",
        "20H5",
        "30H2",
        "39H2",
        "39H4",
        "151H7",
        "151H8",
    ]
    series_ids = [row["molecule_name"] for row in sorted(series_rows, key=lambda r: int(r["recommended_order"]))]
    batch_ids = [row["molecule_name"] for row in sorted(batch_rows, key=lambda r: int(r["recommended_order"]))]
    status_ids = [row["molecule_name"] for row in sorted(status_rows, key=lambda r: int(r["recommended_order"]))]
    require(series_ids == expected_series_ids, f"unexpected success-series order: {series_ids}")
    require(batch_ids == expected_series_ids, f"unexpected batch order: {batch_ids}")
    require(status_ids == expected_series_ids, f"unexpected status order: {status_ids}")
    require({"PVRIG-20", "PVRIG-30", "PVRIG-38", "PVRIG-39"}.issubset(series_ids), "non-151 original VHHs missing from series")

    families = Counter(row["family"] for row in mapping_rows)
    require(families == Counter({"20": 6, "30": 6, "38": 6, "39": 6, "151": 6}), f"unexpected full family counts: {families}")
    series_families = Counter(row["family"] for row in series_rows)
    require(series_families == Counter({"151": 3, "20": 2, "30": 2, "39": 3, "38": 1}), f"unexpected series family counts: {series_families}")

    positives = parse_fasta(args.positives_fasta)
    hr151_positive = next((seq for header, seq in positives.items() if short_id(header) == "hr151_vhh"), "")
    require(hr151_positive, "missing hr151_vhh in known positives FASTA")
    require(fasta_by_name["PVRIG-151_HR151"] == hr151_positive, "PVRIG-151_HR151 does not match hr151_vhh positive")

    exact_cdr3_count, summary_mismatch_count = write_raw_cdr_table(
        args.raw_cdr_out, fasta_by_name, mapping_rows, summary_rows, raw_cdrs
    )
    require(exact_cdr3_count == 30, f"raw ANARCI CDR3 exact FASTA matches={exact_cdr3_count}, expected 30")
    require(summary_mismatch_count == 30, f"expected 30 summary/raw CDR3 audit mismatches, got {summary_mismatch_count}")
    require(all(row["consensus_csv"] == "yes" for row in status_rows), "not all batch status rows have consensus_csv=yes")

    print("OK patent sequence artifacts validated")
    print("fasta_records=30")
    print("mapping_rows=30")
    print("raw_anarci_rows=30")
    print("success_series_rows=11")
    print("batch_rows=11")
    print("batch_consensus_csv=11")
    print("hr151_sha256=" + sha256_text(hr151_positive))
    print("raw_cdr3_exact_fasta_matches=30")
    print("summary_vs_raw_cdr3_audit_mismatches=30")
    print(f"raw_cdr_table={args.raw_cdr_out}")


if __name__ == "__main__":
    main()
