#!/usr/bin/env python3
"""Competition-level VHH QC wrapper.

This script keeps the official compliance gate separate from internal
developability and portfolio ranking. It is intentionally conservative:
official validator failures and unstable VHH numbering remain hard gates,
while structure/docking signals can be absent or imported later.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import xml.sax.saxutils as xml_escape
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Sequence
from zipfile import ZIP_DEFLATED, ZipFile


STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
CDR_FIELDS = {
    "CDRH1": "imgt_cdr1",
    "CDRH2": "imgt_cdr2",
    "CDRH3": "imgt_cdr3",
}


@dataclass(frozen=True)
class FastaRecord:
    name: str
    sequence: str
    description: str = ""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run official + internal competition QC gates for VHH candidates."
    )
    parser.add_argument("fasta", type=Path, help="Candidate VHH FASTA")
    parser.add_argument("-o", "--outdir", type=Path, required=True)
    parser.add_argument("--prefix", default="competition_qc")
    parser.add_argument("--vhh-screen-bin", default="/data/qlyu/software/vhh_eval_tools/bin/vhh-screen")
    parser.add_argument("--validator-bin", default="/data/qlyu/software/vhh_eval_tools/bin/ab-data-validator")
    parser.add_argument("--anarci-bin", default="/data/qlyu/anaconda3/envs/boltz/bin/ANARCI")
    parser.add_argument("--muscle-bin", default="/data/qlyu/software/vhh_eval_tools/bin/muscle")
    parser.add_argument(
        "--positive-csv",
        default="/data/qlyu/software/ab-data-validator/src/ab_data_validator/data/positive.csv",
        type=Path,
        help="Official positive library CSV from ab-data-validator.",
    )
    parser.add_argument(
        "--official-positive-cdr-cache",
        default="/data/qlyu/software/vhh_eval_tools/references/official_positive_library_cdrs.csv",
        type=Path,
        help="Cached IMGT CDR table for the official positive library.",
    )
    parser.add_argument(
        "--refresh-positive-cdr-cache",
        action="store_true",
        help="Rebuild the official positive CDR cache with ANARCI before novelty scoring.",
    )
    parser.add_argument(
        "--local-positive-cdr-csv",
        type=Path,
        help="Optional local PVRIG positive CDR CSV with molecule/name and CDR columns.",
    )
    parser.add_argument("--identity-threshold", type=float, default=0.8)
    parser.add_argument("--safe-identity-threshold", type=float, default=0.75)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--tnp-ncores", type=int, default=1)
    parser.add_argument("--structure-tools", default="", help="Comma-separated tools passed to vhh-screen.")
    parser.add_argument("--max-structures", type=int, default=0)
    parser.add_argument("--gpu", default="")
    parser.add_argument("--skip-vhh-screen", action="store_true")
    parser.add_argument(
        "--defer-official-validator",
        action="store_true",
        help="Defer the official CLI to the full shortlist; official/local CDR cache novelty still runs.",
    )
    parser.add_argument("--skip-abnativ", action="store_true", help="Pass --skip-abnativ to vhh-screen.")
    parser.add_argument("--skip-sapiens", action="store_true", help="Pass --skip-sapiens to vhh-screen.")
    parser.add_argument("--skip-tnp", action="store_true", help="Pass --skip-tnp to vhh-screen.")
    parser.add_argument(
        "--reuse-vhh-screen",
        action="store_true",
        help="Reuse an existing vhh_screen/screen_summary.tsv instead of deleting and rerunning it.",
    )
    parser.add_argument(
        "--skip-team-diversity",
        action="store_true",
        help="Assign independent neutral clusters and defer O(N^2) diversity to a later shortlist.",
    )
    parser.add_argument(
        "--novelty-only-official-pass",
        action="store_true",
        help="Skip local novelty work for candidates already rejected by the official validator.",
    )
    parser.add_argument(
        "--gate-policy",
        choices=["competition", "blocker_calibrated"],
        default="competition",
        help="Keep competition submission gates or use positive-calibrated blocker sensitivity gates.",
    )
    parser.add_argument(
        "--identity-cache-size",
        type=int,
        default=200000,
        help="Maximum cached MUSCLE pair identities; 0 disables caching.",
    )
    parser.add_argument(
        "--disable-novelty-bound-pruning",
        action="store_true",
        help="Disable exact LCS upper-bound pruning before MUSCLE comparisons.",
    )
    parser.add_argument(
        "--large-scale-fast",
        action="store_true",
        help="Shorthand for light all-library gates: skip AbNatiV/Sapiens/TNP/team diversity, "
        "skip novelty for official rejects, and use blocker_calibrated gates.",
    )
    parser.add_argument(
        "--docking-summary",
        type=Path,
        help="Optional CSV/TSV with candidate_id/id/name and blocker_class or occlusion fields.",
    )
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--reserve-n", type=int, default=20)
    parser.add_argument("--cluster-identity", type=float, default=0.9)
    parser.add_argument("--cluster-limit", type=int, default=3)
    args = parser.parse_args(argv)
    if args.large_scale_fast:
        args.skip_abnativ = True
        args.skip_sapiens = True
        args.skip_tnp = True
        args.skip_team_diversity = True
        args.defer_official_validator = True
        args.novelty_only_official_pass = False
        args.gate_policy = "blocker_calibrated"
    return args


def main() -> int:
    args = parse_args()
    timings: list[dict[str, str]] = []
    args.outdir.mkdir(parents=True, exist_ok=True)
    records = timed_stage(timings, "parse_fasta", parse_fasta, args.fasta)
    if not records:
        raise SystemExit(f"No FASTA records found in {args.fasta}")

    normalized_fasta = args.outdir / f"{args.prefix}.normalized.fasta"
    timed_stage(timings, "write_normalized_fasta", write_fasta, normalized_fasta, records)
    args.normalized_fasta = normalized_fasta
    official_xlsx = args.outdir / f"{args.prefix}.official_submit.xlsx"
    timed_stage(timings, "write_official_xlsx", write_validator_xlsx, official_xlsx, records)

    if args.defer_official_validator:
        official_failures: dict[str, list[dict[str, str]]] = {}
        (args.outdir / "official_failed_reasons.csv").write_text("", encoding="utf-8")
        (args.outdir / "official_validator.log").write_text(
            "DEFERRED_TO_FULL_SHORTLIST: official positive CDR cache novelty remains active.\n",
            encoding="utf-8",
        )
        timings.append({"stage": "official_validator_deferred", "elapsed_seconds": "0.000"})
    else:
        official_failures = timed_stage(
            timings, "official_validator", run_official_validator, args, official_xlsx
        )
    screen_dir = args.outdir / "vhh_screen"
    if not args.skip_vhh_screen:
        timed_stage(timings, "vhh_screen", run_vhh_screen, args, screen_dir)

    screen_summary = timed_stage(timings, "read_screen_summary", read_tsv, screen_dir / "screen_summary.tsv")
    vhh_eval_path = screen_dir / f"{args.prefix}.vhh_eval.tsv"
    if not vhh_eval_path.exists():
        candidates = screen_summary
        if screen_summary and any(
            not row.get("imgt_cdr1") or not row.get("imgt_cdr2") or not row.get("imgt_cdr3")
            for row in screen_summary
        ):
            raise SystemExit(
                f"Missing {vhh_eval_path}; screen summary alone does not contain CDR sequences. "
                "Use the original prefix or rerun vhh-screen."
            )
    else:
        candidates = timed_stage(
            timings,
            "merge_vhh_eval",
            merge_rows_by_id,
            screen_summary,
            read_tsv(vhh_eval_path),
        )
    record_ids = {record.name for record in records}
    candidate_ids = {row.get("id", "") for row in candidates}
    if record_ids != candidate_ids:
        missing = sorted(record_ids - candidate_ids)[:5]
        extra = sorted(candidate_ids - record_ids)[:5]
        raise SystemExit(
            "Candidate IDs from vhh-screen do not match the normalized FASTA; "
            f"missing={missing}, extra={extra}. Do not reuse outputs from a different input."
        )

    official_positive_cdrs = timed_stage(timings, "load_official_positive_cdrs", load_official_positive_cdrs, args)
    local_positive_cdrs = timed_stage(timings, "load_local_positive_cdrs", load_local_positive_cdrs, args.local_positive_cdr_csv)
    all_positive_cdrs = official_positive_cdrs + local_positive_cdrs

    novelty_candidates = candidates
    skipped_novelty_rows: list[dict[str, str]] = []
    if args.novelty_only_official_pass:
        novelty_candidates = [row for row in candidates if row.get("id", "") not in official_failures]
        skipped_novelty_rows = make_skipped_novelty_rows(
            row for row in candidates if row.get("id", "") in official_failures
        )
    novelty_performance: dict[str, object] = {}
    computed_novelty_rows = timed_stage(
        timings,
        "positive_cdr_novelty",
        compute_positive_novelty,
        args,
        novelty_candidates,
        all_positive_cdrs,
        novelty_performance,
    )
    novelty_rows = computed_novelty_rows + skipped_novelty_rows
    if args.skip_team_diversity:
        team_rows, cluster_map, cluster_sizes = timed_stage(
            timings, "team_diversity_deferred", make_independent_team_diversity, candidates
        )
    else:
        team_rows, cluster_map, cluster_sizes = timed_stage(
            timings, "team_diversity", compute_team_diversity, args, candidates
        )
    docking_rows = timed_stage(timings, "load_docking_summary", load_docking_summary, args.docking_summary)
    portfolio_rows = timed_stage(
        timings,
        "build_portfolio",
        build_portfolio,
        args=args,
        records=records,
        candidates=candidates,
        official_failures=official_failures,
        novelty_rows=novelty_rows,
        team_rows=team_rows,
        cluster_map=cluster_map,
        cluster_sizes=cluster_sizes,
        docking_rows=docking_rows,
    )

    timed_stage(timings, "write_cdr_novelty", write_tsv, args.outdir / "cdr_novelty.tsv", novelty_rows)
    timed_stage(timings, "write_team_diversity", write_tsv, args.outdir / "team_diversity.tsv", team_rows)
    timed_stage(timings, "write_portfolio_ranked", write_tsv, args.outdir / "portfolio_ranked.tsv", portfolio_rows)
    selected, reserve = timed_stage(timings, "select_portfolio", select_portfolio, args, portfolio_rows)
    timed_stage(timings, "write_submission_fasta", write_fasta, args.outdir / f"submission_top{args.top_n}.fasta", rows_to_records(selected))
    timed_stage(timings, "write_reserve_fasta", write_fasta, args.outdir / f"reserve_{args.reserve_n}.fasta", rows_to_records(reserve))
    timed_stage(timings, "write_submission_xlsx", write_submission_xlsx, args.outdir / f"submission_top{args.top_n}.xlsx", selected)
    timed_stage(timings, "write_report", write_report, args, records, official_failures, novelty_rows, team_rows, portfolio_rows, selected, reserve)
    timed_stage(
        timings,
        "write_details",
        write_details,
        args,
        official_positive_cdrs,
        local_positive_cdrs,
        portfolio_rows,
        novelty_performance,
    )
    write_tsv(args.outdir / "stage_timings.tsv", timings)
    return 0


def timed_stage(timings: list[dict[str, str]], stage: str, function, *args, **kwargs):
    start = time.perf_counter()
    result = function(*args, **kwargs)
    elapsed = time.perf_counter() - start
    timings.append({"stage": stage, "elapsed_seconds": f"{elapsed:.3f}"})
    return result

def parse_fasta(path: Path) -> list[FastaRecord]:
    records: list[FastaRecord] = []
    current_name: str | None = None
    current_desc = ""
    parts: list[str] = []
    with path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_name is not None:
                    records.append(FastaRecord(current_name, normalize_sequence(parts), current_desc))
                header = line[1:].strip()
                current_name = sanitize_id(header.split()[0])
                current_desc = header
                parts = []
            else:
                parts.append(line)
    if current_name is not None:
        records.append(FastaRecord(current_name, normalize_sequence(parts), current_desc))
    seen: set[str] = set()
    unique: list[FastaRecord] = []
    for record in records:
        name = record.name
        suffix = 2
        while name in seen:
            name = f"{record.name}_{suffix}"
            suffix += 1
        seen.add(name)
        if name != record.name:
            record = FastaRecord(name, record.sequence, record.description)
        unique.append(record)
    return unique


def sanitize_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "_", value.strip())
    return cleaned or "candidate"


def normalize_sequence(parts: Iterable[str]) -> str:
    return "".join("".join(parts).split()).upper().replace("*", "")


def write_fasta(path: Path, records: Iterable[FastaRecord]) -> None:
    with path.open("w") as handle:
        for record in records:
            handle.write(f">{record.name}\n")
            seq = record.sequence
            for i in range(0, len(seq), 80):
                handle.write(seq[i : i + 80] + "\n")


def write_validator_xlsx(path: Path, records: list[FastaRecord]) -> None:
    rows: list[dict[int, str]] = [{2: "name", 3: "VH", 4: "VL", 7: "parent_VH", 8: "parent_VL"}]
    for record in records:
        rows.append({2: record.name, 3: record.sequence, 4: "", 7: "", 8: ""})
    write_simple_xlsx(path, rows)


def write_submission_xlsx(path: Path, rows: list[dict[str, str]]) -> None:
    headers = [
        "rank",
        "candidate_id",
        "sequence",
        "final_score",
        "recommendation",
        "reason_summary",
    ]
    xlsx_rows: list[dict[int, str]] = [{i + 1: header for i, header in enumerate(headers)}]
    for row in rows:
        xlsx_rows.append({i + 1: row.get(header, "") for i, header in enumerate(headers)})
    write_simple_xlsx(path, xlsx_rows)


def write_simple_xlsx(path: Path, rows: list[dict[int, str]]) -> None:
    max_col = max((max(row) for row in rows if row), default=1)
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index in range(1, max_col + 1):
            value = row.get(col_index, "")
            ref = f"{column_name(col_index)}{row_index}"
            text = xml_escape.escape(str(value))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">' + "".join(cells) + "</row>")
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        + "".join(sheet_rows)
        + "</sheetData></worksheet>"
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def column_name(index: int) -> str:
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(ord("A") + rem) + name
    return name


def run_official_validator(args: argparse.Namespace, xlsx: Path) -> dict[str, list[dict[str, str]]]:
    output = args.outdir / "official_failed_reasons.csv"
    log_path = args.outdir / "official_validator.log"
    command = [
        args.validator_bin,
        "validate",
        "--input",
        str(xlsx),
        "--output",
        str(output),
        "--identity-threshold",
        str(args.identity_threshold),
        "--anarci-bin",
        args.anarci_bin,
        "--muscle-bin",
        args.muscle_bin,
        "--workers",
        str(args.workers),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    log_path.write_text(
        "$ " + " ".join(command) + "\n\nSTDOUT:\n" + completed.stdout + "\nSTDERR:\n" + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise SystemExit(f"Official validator failed; see {log_path}")
    failures = defaultdict(list)
    if output.exists():
        for row in read_csv_auto(output):
            failures[row.get("name", "")].append(row)
    return dict(failures)


def run_vhh_screen(args: argparse.Namespace, outdir: Path) -> None:
    if args.reuse_vhh_screen and (outdir / "screen_summary.tsv").exists():
        return
    if outdir.exists():
        shutil.rmtree(outdir)
    command = [
        args.vhh_screen_bin,
        str(getattr(args, "normalized_fasta", args.fasta)),
        "-o",
        str(outdir),
        "--prefix",
        args.prefix,
        "--tnp-ncores",
        str(args.tnp_ncores),
    ]
    if args.skip_abnativ:
        command.append("--skip-abnativ")
    if args.skip_sapiens:
        command.append("--skip-sapiens")
    if args.skip_tnp:
        command.append("--skip-tnp")
    if args.structure_tools:
        command.extend(["--structure-tools", args.structure_tools])
    if args.max_structures:
        command.extend(["--max-structures", str(args.max_structures)])
    if args.gpu:
        command.extend(["--gpu", str(args.gpu)])
    log_path = args.outdir / "vhh_screen.log"
    env = os.environ.copy()
    if args.gpu:
        env["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
    completed = subprocess.run(command, text=True, capture_output=True, env=env, check=False)
    log_path.write_text(
        "$ " + " ".join(command) + "\n\nSTDOUT:\n" + completed.stdout + "\nSTDERR:\n" + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise SystemExit(f"vhh-screen failed; see {log_path}")


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_csv_auto(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t") if sample.strip() else csv.excel
        return list(csv.DictReader(handle, dialect=dialect))


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def merge_rows_by_id(left: list[dict[str, str]], right: list[dict[str, str]]) -> list[dict[str, str]]:
    right_by_id = {row.get("id", ""): row for row in right}
    merged = []
    for row in left:
        candidate_id = row.get("id", "")
        combined = dict(right_by_id.get(candidate_id, {}))
        combined.update(row)
        merged.append(combined)
    for candidate_id, row in right_by_id.items():
        if not any(item.get("id") == candidate_id for item in merged):
            merged.append(dict(row))
    return merged


def add_validator_src_to_path() -> None:
    validator_src = os.environ.get("AB_DATA_VALIDATOR_SRC", "/data/qlyu/software/ab-data-validator/src")
    if Path(validator_src).exists() and validator_src not in sys.path:
        sys.path.insert(0, validator_src)


def load_official_positive_cdrs(args: argparse.Namespace) -> list[dict[str, str]]:
    cache_path = args.official_positive_cdr_cache
    if cache_path.exists() and not args.refresh_positive_cdr_cache:
        return read_csv_auto(cache_path)

    positives = build_official_positive_cdrs(args)
    if cache_path:
        write_csv(cache_path, positives)
    return positives


def build_official_positive_cdrs(args: argparse.Namespace) -> list[dict[str, str]]:
    add_validator_src_to_path()
    from ab_data_validator.anarci_runner import run_anarci
    from ab_data_validator.cdr import extract_imgt_cdrs

    positives: list[dict[str, str]] = []
    with args.positive_csv.open(newline="") as handle:
        for row in csv.DictReader(handle):
            name = row.get("抗体名称") or row.get("name") or row.get("id") or "positive"
            sequence = normalize_sequence([row.get("抗体重链氨基酸", "") or row.get("vh", "")])
            if not sequence:
                continue
            try:
                residues = run_anarci(sequence, sequence_id=sanitize_id(name), anarci_bin=args.anarci_bin)
                cdrs = extract_imgt_cdrs(residues, chain_prefix="H")
            except Exception as error:
                cdrs = {}
                print(f"warning: failed to number positive {name}: {error}", file=sys.stderr)
            positives.append(
                {
                    "reference_set": "official_ab_data_validator",
                    "positive_name": sanitize_id(name),
                    "positive_type": row.get("类型(IgG/VHH)", ""),
                    "positive_source": row.get("来自专利", ""),
                    "positive_cdr1": cdrs.get("CDRH1", ""),
                    "positive_cdr2": cdrs.get("CDRH2", ""),
                    "positive_cdr3": cdrs.get("CDRH3", ""),
                }
            )
    return positives


def load_local_positive_cdrs(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    rows: list[dict[str, str]] = []
    for row in read_csv_auto(path):
        name = (
            row.get("molecule_name")
            or row.get("positive_name")
            or row.get("name")
            or row.get("fasta_id")
            or "local_positive"
        )
        rows.append(
            {
                "reference_set": "local_pvrig_positive",
                "positive_name": sanitize_id(name),
                "positive_type": row.get("sequence_type", "VHH"),
                "positive_source": row.get("source", row.get("family", "")),
                "positive_cdr1": row.get("raw_anarci_imgt_cdr1_exact") or row.get("cdr1") or row.get("CDRH1") or "",
                "positive_cdr2": row.get("raw_anarci_imgt_cdr2_exact") or row.get("cdr2") or row.get("CDRH2") or "",
                "positive_cdr3": row.get("raw_anarci_imgt_cdr3_exact") or row.get("cdr3") or row.get("CDRH3") or "",
            }
        )
    return rows


def lcs_length(a: str, b: str) -> int:
    """Return longest-common-subsequence length using O(min(m, n)) memory."""
    if len(a) < len(b):
        a, b = b, a
    previous = [0] * (len(b) + 1)
    for aa in a:
        current = [0]
        for index, bb in enumerate(b, start=1):
            if aa == bb:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def max_possible_aligned_identity(a: str, b: str) -> float:
    """Exact upper bound for matches/alignment-length identity.

    Any global alignment has at most LCS(a, b) matches and at least
    max(len(a), len(b)) columns. Pairs below the current best can therefore be
    skipped without changing the winning MUSCLE identity.
    """
    if not a or not b:
        return 0.0
    return lcs_length(a, b) / max(len(a), len(b))


def best_identity_against_references(
    candidate_sequence: str,
    references: list[tuple[str, str, str]],
    identity_function: Callable[[str, str], float],
    *,
    use_bound_pruning: bool = True,
) -> tuple[float, str, str, dict[str, int]]:
    """Find the exact best identity while pruning provably losing pairs."""
    stats = {
        "reference_pairs": len(references),
        "identity_requests": 0,
        "upper_bound_pruned": 0,
    }
    if not candidate_sequence or not references:
        return 0.0, "", "", stats

    bounded: list[tuple[float, int, str, str, str]] = []
    for index, (name, reference_set, sequence) in enumerate(references):
        upper_bound = (
            max_possible_aligned_identity(candidate_sequence, sequence)
            if use_bound_pruning
            else 1.0
        )
        bounded.append((upper_bound, index, name, reference_set, sequence))
    bounded.sort(key=lambda item: (-item[0], item[1]))

    best_identity = -1.0
    best_index = len(references) + 1
    best_name = ""
    best_set = ""
    for position, (upper_bound, index, name, reference_set, sequence) in enumerate(bounded):
        if use_bound_pruning and best_identity >= 0:
            strictly_worse = upper_bound < best_identity - 1e-12
            tied_but_later = abs(upper_bound - best_identity) <= 1e-12 and index >= best_index
            if strictly_worse:
                stats["upper_bound_pruned"] += len(bounded) - position
                break
            if tied_but_later:
                stats["upper_bound_pruned"] += 1
                continue
        identity = identity_function(candidate_sequence, sequence)
        stats["identity_requests"] += 1
        if identity > best_identity + 1e-12 or (
            abs(identity - best_identity) <= 1e-12 and index < best_index
        ):
            best_identity = identity
            best_index = index
            best_name = name
            best_set = reference_set
        if best_identity >= 1.0 and best_index == min(item[1] for item in bounded if item[0] >= 1.0):
            stats["upper_bound_pruned"] += len(bounded) - position - 1
            break
    if best_identity < 0:
        best_identity = 0.0
    return best_identity, best_name, best_set, stats


def compute_positive_novelty(
    args: argparse.Namespace,
    candidates: list[dict[str, str]],
    positives: list[dict[str, str]],
    performance: dict[str, object] | None = None,
) -> list[dict[str, str]]:
    add_validator_src_to_path()
    from ab_data_validator.muscle import align_pair
    from ab_data_validator.similarity import calculate_identity

    @lru_cache(maxsize=max(0, args.identity_cache_size))
    def cached_identity(sequence_a: str, sequence_b: str) -> float:
        aligned_a, aligned_b = align_pair(sequence_a, sequence_b, muscle_bin=args.muscle_bin)
        return calculate_identity(aligned_a, aligned_b)

    def identity(sequence_a: str, sequence_b: str) -> float:
        if sequence_a <= sequence_b:
            return cached_identity(sequence_a, sequence_b)
        return cached_identity(sequence_b, sequence_a)

    def best_for(candidate: dict[str, str]) -> tuple[dict[str, str], dict[str, int]]:
        candidate_id = candidate.get("id", "")
        out: dict[str, str] = {"candidate_id": candidate_id}
        max_all = 0.0
        nearest = ""
        local_stats = {"reference_pairs": 0, "identity_requests": 0, "upper_bound_pruned": 0}
        for cdr_name, field in CDR_FIELDS.items():
            candidate_cdr = candidate.get(field, "")
            out[f"{cdr_name}_sequence"] = candidate_cdr
            references = []
            seen_sequences: set[str] = set()
            for positive in positives:
                positive_cdr = positive.get(f"positive_cdr{cdr_name[-1]}", "")
                if not positive_cdr or positive_cdr in seen_sequences:
                    continue
                seen_sequences.add(positive_cdr)
                references.append(
                    (
                        positive.get("positive_name", ""),
                        positive.get("reference_set", ""),
                        positive_cdr,
                    )
                )
            best_value, best_name, best_set, stats = best_identity_against_references(
                candidate_cdr,
                references,
                identity,
                use_bound_pruning=not args.disable_novelty_bound_pruning,
            )
            for key in local_stats:
                local_stats[key] += stats[key]
            out[f"{cdr_name}_max_identity_to_positive"] = f"{best_value:.6f}"
            out[f"{cdr_name}_nearest_positive"] = best_name
            out[f"{cdr_name}_nearest_reference_set"] = best_set
            if best_value > max_all:
                max_all = best_value
                nearest = best_name
        out["max_CDR_identity_to_positive"] = f"{max_all:.6f}"
        out["nearest_positive_name"] = nearest
        out["pass_similarity_filter"] = "PASS" if max_all < args.identity_threshold else "FAIL"
        out["novelty_margin_flag"] = (
            "SAFE"
            if max_all < args.safe_identity_threshold
            else "BORDERLINE"
            if max_all < args.identity_threshold
            else "FAIL"
        )
        out["novelty_score"] = f"{score_novelty(max_all, args.identity_threshold):.2f}"
        return out, local_stats

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        results = list(executor.map(best_for, candidates))
    if performance is not None:
        aggregate = {"reference_pairs": 0, "identity_requests": 0, "upper_bound_pruned": 0}
        for _, stats in results:
            for key in aggregate:
                aggregate[key] += stats[key]
        cache = cached_identity.cache_info()
        performance.update(
            {
                "candidate_count": len(candidates),
                "positive_reference_count": len(positives),
                **aggregate,
                "muscle_cache_hits": cache.hits,
                "muscle_cache_misses": cache.misses,
                "muscle_cache_maxsize": cache.maxsize,
                "bound_pruning_enabled": not args.disable_novelty_bound_pruning,
            }
        )
    return [row for row, _ in results]


def make_skipped_novelty_rows(candidates: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for candidate in candidates:
        rows.append(
            {
                "candidate_id": candidate.get("id", ""),
                "max_CDR_identity_to_positive": "",
                "nearest_positive_name": "",
                "pass_similarity_filter": "SKIPPED_UPSTREAM_HARD_FAIL",
                "novelty_margin_flag": "SKIPPED",
                "novelty_score": "0.00",
            }
        )
    return rows


def make_independent_team_diversity(
    candidates: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, str], dict[str, int]]:
    rows: list[dict[str, str]] = []
    cluster_map: dict[str, str] = {}
    cluster_sizes: dict[str, int] = {}
    for index, candidate in enumerate(candidates, start=1):
        candidate_id = candidate.get("id", "")
        cluster_id = f"DEFERRED_{index:08d}"
        cluster_map[candidate_id] = cluster_id
        cluster_sizes[cluster_id] = 1
        rows.append(
            {
                "candidate_id": candidate_id,
                "nearest_team_neighbor": "",
                "max_team_identity": "",
                "intra_team_cluster_id": cluster_id,
                "intra_team_cluster_size": "1",
                "diversity_score": "100.00",
                "diversity_status": "DEFERRED_TO_SHORTLIST",
            }
        )
    return rows, cluster_map, cluster_sizes


def compute_team_diversity(
    args: argparse.Namespace, candidates: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, str], dict[str, int]]:
    add_validator_src_to_path()
    from ab_data_validator.muscle import align_pair
    from ab_data_validator.similarity import calculate_identity

    ids = [row.get("id", "") for row in candidates]
    edges: dict[str, set[str]] = {candidate_id: set() for candidate_id in ids}
    rows: list[dict[str, str]] = []
    best_by_id: dict[str, tuple[float, str]] = {candidate_id: (0.0, "") for candidate_id in ids}

    def cdr_identity(a: dict[str, str], b: dict[str, str], field: str) -> float:
        seq_a = a.get(field, "")
        seq_b = b.get(field, "")
        if not seq_a or not seq_b:
            return 0.0
        aligned_a, aligned_b = align_pair(seq_a, seq_b, muscle_bin=args.muscle_bin)
        return calculate_identity(aligned_a, aligned_b)

    by_id = {row.get("id", ""): row for row in candidates}
    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1 :]:
            row_a = by_id[id_a]
            row_b = by_id[id_b]
            identities = [cdr_identity(row_a, row_b, field) for field in CDR_FIELDS.values()]
            avg_identity = sum(identities) / len(identities)
            cdr3_identity = identities[2]
            full_identity = quick_sequence_identity(row_a.get("sequence", ""), row_b.get("sequence", ""))
            pair_identity = max(avg_identity, cdr3_identity, full_identity)
            if pair_identity >= args.cluster_identity:
                edges[id_a].add(id_b)
                edges[id_b].add(id_a)
            if pair_identity > best_by_id[id_a][0]:
                best_by_id[id_a] = (pair_identity, id_b)
            if pair_identity > best_by_id[id_b][0]:
                best_by_id[id_b] = (pair_identity, id_a)
    for candidate_id in ids:
        best_identity, best_neighbor = best_by_id[candidate_id]
        rows.append(
            {
                "candidate_id": candidate_id,
                "nearest_team_neighbor": best_neighbor,
                "max_team_identity": f"{best_identity:.6f}",
            }
        )
    cluster_map = connected_components(edges)
    cluster_sizes = defaultdict(int)
    for cluster_id in cluster_map.values():
        cluster_sizes[cluster_id] += 1
    for row in rows:
        cluster_id = cluster_map.get(row["candidate_id"], "")
        row["intra_team_cluster_id"] = cluster_id
        row["intra_team_cluster_size"] = str(cluster_sizes.get(cluster_id, 1))
        row["diversity_score"] = f"{score_diversity(cluster_sizes.get(cluster_id, 1)):.2f}"
    return rows, cluster_map, dict(cluster_sizes)


def connected_components(edges: dict[str, set[str]]) -> dict[str, str]:
    cluster_map: dict[str, str] = {}
    cluster_index = 1
    for start in sorted(edges):
        if start in cluster_map:
            continue
        cluster_id = f"C{cluster_index:04d}"
        cluster_index += 1
        queue: deque[str] = deque([start])
        cluster_map[start] = cluster_id
        while queue:
            item = queue.popleft()
            for neighbor in sorted(edges[item]):
                if neighbor not in cluster_map:
                    cluster_map[neighbor] = cluster_id
                    queue.append(neighbor)
    return cluster_map


def quick_sequence_identity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if len(a) == len(b):
        return sum(aa == bb for aa, bb in zip(a, b, strict=True)) / len(a)
    matches = sum(aa == bb for aa, bb in zip(a, b))
    return matches / max(len(a), len(b))


def load_docking_summary(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.exists():
        return {}
    rows = read_csv_auto(path)
    by_id = {}
    for row in rows:
        candidate_id = (
            row.get("candidate_id")
            or row.get("id")
            or row.get("name")
            or row.get("fasta_id")
            or row.get("molecule_name")
        )
        if candidate_id:
            if not row.get("blocker_class") and row.get("top_model_consensus_class"):
                row["blocker_class"] = row["top_model_consensus_class"]
            if not row.get("hotspot_overlap_count") and row.get("top_8x6b_hotspot"):
                row["hotspot_overlap_count"] = row["top_8x6b_hotspot"]
            if not row.get("total_vhh_pvrl2_residue_pair_occlusion") and row.get("top_8x6b_total_occlusion"):
                row["total_vhh_pvrl2_residue_pair_occlusion"] = row["top_8x6b_total_occlusion"]
            by_id[candidate_id] = row
    return by_id


def build_portfolio(
    *,
    args: argparse.Namespace,
    records: list[FastaRecord],
    candidates: list[dict[str, str]],
    official_failures: dict[str, list[dict[str, str]]],
    novelty_rows: list[dict[str, str]],
    team_rows: list[dict[str, str]],
    cluster_map: dict[str, str],
    cluster_sizes: dict[str, int],
    docking_rows: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    record_map = {record.name: record for record in records}
    novelty_by_id = {row["candidate_id"]: row for row in novelty_rows}
    team_by_id = {row["candidate_id"]: row for row in team_rows}
    portfolio: list[dict[str, str]] = []
    for candidate in candidates:
        candidate_id = candidate.get("id", "")
        record = record_map.get(candidate_id, FastaRecord(candidate_id, candidate.get("sequence", "")))
        official = summarize_official_failures(official_failures.get(candidate_id, []))
        novelty = novelty_by_id.get(candidate_id, {})
        team = team_by_id.get(candidate_id, {})
        docking = docking_rows.get(candidate_id, {})

        developability_score = score_developability(candidate)
        expression_score = score_expression_purity(candidate)
        structure_score = score_structure(candidate)
        novelty_score = parse_float(novelty.get("novelty_score"), default=50.0)
        diversity_score = parse_float(team.get("diversity_score"), default=100.0)
        binding_score = score_binding(docking)
        blocking_score = score_blocking(docking)
        final_score = (
            0.20 * binding_score
            + 0.20 * blocking_score
            + 0.20 * developability_score
            + 0.15 * expression_score
            + 0.10 * structure_score
            + 0.10 * novelty_score
            + 0.05 * diversity_score
        )
        hard_fail, recommendation, reasons = classify_candidate(
            candidate=candidate,
            official=official,
            novelty=novelty,
            developability_score=developability_score,
            expression_score=expression_score,
            structure_score=structure_score,
            gate_policy=args.gate_policy,
        )
        row = {
            "candidate_id": candidate_id,
            "sequence": record.sequence or candidate.get("sequence", ""),
            "length": candidate.get("length", str(len(record.sequence))),
            "standard_aa_only": str(set(record.sequence) <= STANDARD_AA),
            "official_validator_pass": (
                "DEFERRED_TO_FULL_SHORTLIST"
                if args.defer_official_validator
                else "PASS"
                if not official["has_failure"]
                else "FAIL"
            ),
            "official_validator_failed_reason": official["reason_summary"],
            "ANARCI_status": candidate.get("imgt_ok", ""),
            "imgt_chain_type": candidate.get("imgt_chain_type", ""),
            "IMGT_CDR1": candidate.get("imgt_cdr1", ""),
            "IMGT_CDR2": candidate.get("imgt_cdr2", ""),
            "IMGT_CDR3": candidate.get("imgt_cdr3", ""),
            "CDR1_length": str(len(candidate.get("imgt_cdr1", ""))),
            "CDR2_length": str(len(candidate.get("imgt_cdr2", ""))),
            "CDR3_length": str(len(candidate.get("imgt_cdr3", ""))),
            "max_CDR_identity_to_positive": novelty.get("max_CDR_identity_to_positive", ""),
            "nearest_positive_name": novelty.get("nearest_positive_name", ""),
            "pass_similarity_filter": novelty.get("pass_similarity_filter", ""),
            "novelty_margin_flag": novelty.get("novelty_margin_flag", ""),
            "max_team_identity": team.get("max_team_identity", ""),
            "nearest_team_neighbor": team.get("nearest_team_neighbor", ""),
            "intra_team_cluster_id": cluster_map.get(candidate_id, ""),
            "intra_team_cluster_size": str(cluster_sizes.get(cluster_map.get(candidate_id, ""), 1)),
            "fr2_hallmark_score": candidate.get("fr2_hallmark_score", ""),
            "single_domain_suitability": candidate.get("single_domain_suitability", ""),
            "AbNatiV_VHH_score": candidate.get("abnativ_vhh_score", ""),
            "has_unusual_cysteine": str(candidate.get("cys_count", "") not in {"", "2"}),
            "has_N_glycosylation_motif": str(parse_int(candidate.get("nglyc_motif_count")) > 0),
            "deamidation_risk_count": candidate.get("deamidation_NG_NS_NT_count", ""),
            "oxidation_risk_count": candidate.get("oxidation_MW_count", ""),
            "isomerization_risk_count": candidate.get("isomerization_DG_DS_DD_DT_count", ""),
            "clipping_risk_count": candidate.get("acid_cleavage_DP_count", ""),
            "pI": candidate.get("pI", ""),
            "net_charge_pH7": candidate.get("charge_pH7_4", ""),
            "MW": candidate.get("mw", ""),
            "GRAVY": candidate.get("gravy", ""),
            "instability_index": candidate.get("instability_index", ""),
            "TNP_flags": "/".join(
                candidate.get(key, "")
                for key in ["tnp_L_flag", "tnp_L3_flag", "tnp_C_flag", "tnp_PSH_flag", "tnp_PPC_flag", "tnp_PNC_flag"]
            ),
            "structure_quality_flag": candidate.get("L4_structure_stability", ""),
            "FR_RMSD_cross_tool": candidate.get("fr_rmsd_igfold_vs_nanobodybuilder2", ""),
            "binding_score": f"{binding_score:.2f}",
            "PVRIG_interface_contact_score": docking.get("hotspot_overlap_count", ""),
            "PVRL2_competition_score": f"{blocking_score:.2f}",
            "blocker_class": docking.get("blocker_class") or docking.get("class") or "NOT_RUN",
            "developability_score": f"{developability_score:.2f}",
            "expression_purity_risk_score": f"{expression_score:.2f}",
            "structure_score": f"{structure_score:.2f}",
            "novelty_score": f"{novelty_score:.2f}",
            "diversity_score": f"{diversity_score:.2f}",
            "initial_screen_proxy_score": f"{0.70 * binding_score + 0.20 * expression_score + 0.10 * expression_score:.2f}",
            "rescreen_proxy_score": f"{0.50 * binding_score + 0.50 * blocking_score:.2f}",
            "hard_fail": str(hard_fail),
            "recommendation": recommendation,
            "reason_summary": ";".join(reasons),
            "final_score": f"{final_score:.2f}",
        }
        portfolio.append(row)
    portfolio.sort(key=lambda row: (row["hard_fail"] == "True", -parse_float(row["final_score"]), row["candidate_id"]))
    for rank, row in enumerate(portfolio, start=1):
        row["rank"] = str(rank)
    return portfolio


def summarize_official_failures(failures: list[dict[str, str]]) -> dict[str, object]:
    if not failures:
        return {"has_failure": False, "reason_summary": ""}
    parts = []
    for failure in failures:
        reason = failure.get("reason_type", "failure")
        cdr = failure.get("cdr", "")
        positive = failure.get("positive_name", "")
        identity = failure.get("identity", "")
        detail = reason
        if cdr:
            detail += f":{cdr}"
        if positive:
            detail += f":{positive}"
        if identity:
            detail += f":{identity}"
        parts.append(detail)
    return {"has_failure": True, "reason_summary": "|".join(parts)}


def classify_candidate(
    *,
    candidate: dict[str, str],
    official: dict[str, object],
    novelty: dict[str, str],
    developability_score: float,
    expression_score: float,
    structure_score: float,
    gate_policy: str = "competition",
) -> tuple[bool, str, list[str]]:
    reasons: list[str] = []
    if official["has_failure"]:
        reasons.append("official_validator_failed")
    if candidate.get("L1_numbering_integrity") == "FAIL" or candidate.get("imgt_ok") not in {"True", "PASS", "true"}:
        reasons.append("numbering_or_framework_failed")
    if candidate.get("L2_vhh_features") == "FAIL" or candidate.get("single_domain_suitability") == "poor":
        reasons.append("not_vhh_like")
    if novelty.get("pass_similarity_filter") == "FAIL":
        reasons.append("positive_cdr_identity_ge_threshold")
    if parse_int(candidate.get("invalid_aa_count")) > 0:
        reasons.append("invalid_amino_acids")
    if parse_int(candidate.get("cys_count")) % 2 == 1:
        reasons.append("odd_cysteine_count")
    if parse_int(candidate.get("hydrophobic_5_count")) > 0:
        reasons.append("hydrophobic_run")
    if candidate.get("L4_structure_stability") == "FAIL":
        reasons.append("structure_failed")

    competition_hard_fail_reasons = {
        "official_validator_failed",
        "numbering_or_framework_failed",
        "not_vhh_like",
        "positive_cdr_identity_ge_threshold",
        "invalid_amino_acids",
        "odd_cysteine_count",
        "hydrophobic_run",
        "structure_failed",
    }
    blocker_calibrated_hard_fail_reasons = {
        "official_validator_failed",
        "numbering_or_framework_failed",
        "positive_cdr_identity_ge_threshold",
        "invalid_amino_acids",
        "odd_cysteine_count",
        "structure_failed",
    }
    hard_fail_reasons = (
        blocker_calibrated_hard_fail_reasons
        if gate_policy == "blocker_calibrated"
        else competition_hard_fail_reasons
    )
    hard_fail = any(reason in hard_fail_reasons for reason in reasons)
    if hard_fail:
        return True, "REJECT_HARD_GATE", reasons
    if gate_policy == "blocker_calibrated" and any(
        reason in {"not_vhh_like", "hydrophobic_run"} for reason in reasons
    ):
        return False, "REVIEW_DEVELOPABILITY", reasons
    if developability_score < 65 or expression_score < 65 or structure_score < 50:
        reasons.append("score_review")
        return False, "REVIEW_RISK", reasons
    if novelty.get("novelty_margin_flag") == "BORDERLINE":
        reasons.append("novelty_borderline")
        return False, "REVIEW_NOVELTY_MARGIN", reasons
    if candidate.get("L3_developability") == "WARN":
        reasons.append("developability_warn")
        return False, "REVIEW_DEVELOPABILITY", reasons
    return False, "SUBMIT_CANDIDATE", reasons


def score_novelty(max_identity: float, threshold: float) -> float:
    if max_identity >= threshold:
        return 0.0
    if max_identity <= 0.5:
        return 100.0
    return max(0.0, min(100.0, (threshold - max_identity) / (threshold - 0.5) * 100.0))


def score_diversity(cluster_size: int) -> float:
    if cluster_size <= 1:
        return 100.0
    if cluster_size == 2:
        return 85.0
    if cluster_size <= 4:
        return 70.0
    return 55.0


def score_developability(row: dict[str, str]) -> float:
    score = 100.0
    if row.get("L3_developability") == "WARN":
        score -= 12
    if row.get("L3_developability") == "FAIL":
        score -= 45
    for key in ["tnp_L_flag", "tnp_L3_flag", "tnp_C_flag", "tnp_PSH_flag", "tnp_PPC_flag", "tnp_PNC_flag"]:
        score -= flag_penalty(row.get(key, ""))
    score -= min(20, parse_int(row.get("nglyc_motif_count")) * 8)
    score -= min(12, parse_int(row.get("deamidation_NG_NS_NT_count")) * 2)
    score -= min(8, parse_int(row.get("isomerization_DG_DS_DD_DT_count")) * 2)
    score -= min(8, parse_int(row.get("acid_cleavage_DP_count")) * 3)
    if parse_int(row.get("cys_count")) != 2:
        score -= 15
    if parse_float(row.get("abnativ_vhh_score"), default=0.7) < 0.55:
        score -= 20
    elif parse_float(row.get("abnativ_vhh_score"), default=0.7) < 0.70:
        score -= 8
    return clamp(score)


def score_expression_purity(row: dict[str, str]) -> float:
    score = 100.0
    p_i = parse_float(row.get("pI"), default=7.0)
    charge = abs(parse_float(row.get("charge_pH7_4"), default=0.0))
    gravy = parse_float(row.get("gravy"), default=-0.2)
    instability = parse_float(row.get("instability_index"), default=30.0)
    if p_i < 4.5 or p_i > 10.5:
        score -= 35
    elif p_i < 5.0 or p_i > 9.5:
        score -= 15
    if charge > 12:
        score -= 30
    elif charge > 8:
        score -= 12
    if gravy > 0.2:
        score -= 20
    elif gravy > 0.0:
        score -= 8
    if instability > 50:
        score -= 15
    elif instability > 40:
        score -= 8
    if parse_int(row.get("hydrophobic_5_count")) > 0:
        score -= 35
    if parse_int(row.get("cys_count")) != 2:
        score -= 20
    if row.get("polyreactivity_proxy") == "high":
        score -= 25
    elif row.get("polyreactivity_proxy") == "moderate":
        score -= 10
    for key in ["tnp_PSH_flag", "tnp_PPC_flag", "tnp_PNC_flag"]:
        score -= flag_penalty(row.get(key, "")) * 1.2
    return clamp(score)


def score_structure(row: dict[str, str]) -> float:
    status = row.get("L4_structure_stability", "")
    if status == "PASS":
        return 100.0
    if status == "WARN":
        return 70.0
    if status == "FAIL":
        return 0.0
    if status == "SKIPPED" or not status:
        return 60.0
    return 60.0


def score_binding(docking: dict[str, str]) -> float:
    for key in ["binding_score", "PVRIG_binding_score", "score"]:
        if key in docking and str(docking[key]).strip():
            return clamp(parse_float(docking[key], default=50.0))
    blocker_class = docking.get("blocker_class") or docking.get("class") or ""
    if "BLOCKER_LIKE_A" in blocker_class:
        return 90.0
    if "BLOCKER_PLAUSIBLE_B" in blocker_class or "SINGLE_BASELINE" in blocker_class:
        return 80.0
    if "BINDER_LIKE_C" in blocker_class:
        return 70.0
    if "EVIDENCE" in blocker_class:
        return 40.0
    return 50.0


def score_blocking(docking: dict[str, str]) -> float:
    for key in ["blocking_score", "PVRL2_competition_score"]:
        if key in docking and str(docking[key]).strip():
            return clamp(parse_float(docking[key], default=50.0))
    blocker_class = docking.get("blocker_class") or docking.get("class") or ""
    if "BLOCKER_LIKE_A" in blocker_class:
        return 100.0
    if "SINGLE_BASELINE" in blocker_class:
        return 75.0
    if "BLOCKER_PLAUSIBLE_B" in blocker_class:
        return 70.0
    if "BINDER_LIKE_C" in blocker_class:
        return 25.0
    if "EVIDENCE" in blocker_class:
        return 30.0
    total = parse_float(docking.get("total_vhh_pvrl2_residue_pair_occlusion"), default=math.nan)
    if not math.isnan(total):
        return clamp(total / 500.0 * 100.0)
    return 50.0


def flag_penalty(value: str) -> float:
    normalized = value.strip().lower()
    if normalized in {"green", "pass", "ok", ""}:
        return 0.0
    if normalized in {"yellow", "warn", "warning", "amber"}:
        return 8.0
    if normalized in {"red", "fail", "failed"}:
        return 20.0
    return 5.0


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def select_portfolio(args: argparse.Namespace, rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    eligible = [row for row in rows if row.get("hard_fail") != "True"]
    cluster_counts = defaultdict(int)
    selected: list[dict[str, str]] = []
    overflow: list[dict[str, str]] = []
    for row in eligible:
        cluster_id = row.get("intra_team_cluster_id", "")
        if len(selected) < args.top_n and cluster_counts[cluster_id] < args.cluster_limit:
            selected.append(row)
            cluster_counts[cluster_id] += 1
        else:
            overflow.append(row)
    reserve = overflow[: args.reserve_n]
    for rank, row in enumerate(selected, start=1):
        row["submission_rank"] = str(rank)
    for rank, row in enumerate(reserve, start=1):
        row["reserve_rank"] = str(rank)
    return selected, reserve


def rows_to_records(rows: list[dict[str, str]]) -> list[FastaRecord]:
    return [FastaRecord(row["candidate_id"], row["sequence"]) for row in rows]


def write_report(
    args: argparse.Namespace,
    records: list[FastaRecord],
    official_failures: dict[str, list[dict[str, str]]],
    novelty_rows: list[dict[str, str]],
    team_rows: list[dict[str, str]],
    portfolio_rows: list[dict[str, str]],
    selected: list[dict[str, str]],
    reserve: list[dict[str, str]],
) -> None:
    counts = defaultdict(int)
    for row in portfolio_rows:
        counts[row.get("recommendation", "")] += 1
    hard_fail_count = sum(1 for row in portfolio_rows if row.get("hard_fail") == "True")
    report = [
        "# VHH competition QC run report",
        "",
        f"Input FASTA: `{args.fasta}`",
        f"Output directory: `{args.outdir}`",
        f"Candidates: {len(records)}",
        f"Official validator failures: {len(official_failures)}",
        f"Official validator deferred: {args.defer_official_validator}",
        f"Hard gate rejects: {hard_fail_count}",
        f"Selected Top {args.top_n}: {len(selected)}",
        f"Reserve {args.reserve_n}: {len(reserve)}",
        f"Gate policy: {args.gate_policy}",
        f"Team diversity deferred: {args.skip_team_diversity}",
        "",
        "## Recommendation counts",
        "",
    ]
    for key in sorted(counts):
        report.append(f"- {key}: {counts[key]}")
    report.extend(
        [
            "",
            "## Output files",
            "",
            "- `official_failed_reasons.csv`",
            "- `vhh_screen/screen_summary.tsv`",
            "- `cdr_novelty.tsv`",
            "- `team_diversity.tsv`",
            "- `portfolio_ranked.tsv`",
            f"- `submission_top{args.top_n}.fasta`",
            f"- `submission_top{args.top_n}.xlsx`",
            f"- `reserve_{args.reserve_n}.fasta`",
            "",
            "## Notes",
            "",
            "- `official_validator_pass=FAIL` is a hard gate.",
            "- `official_validator_pass=DEFERRED_TO_FULL_SHORTLIST` is not a pass; the full shortlist must rerun the official CLI.",
            "- `pass_similarity_filter=FAIL` means at least one CDR has identity >= threshold.",
            "- Structure and docking scores are neutral if those gates were not run/imported.",
            "- Docking labels are computational hypotheses, not experimental IC50/Kd evidence.",
            "- `blocker_calibrated` keeps VHH-like and hydrophobic-run findings as review signals, not blocker hard fails.",
            "- Deferred team diversity must be recomputed on the final shortlist before portfolio selection.",
        ]
    )
    (args.outdir / "portfolio_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def write_details(
    args: argparse.Namespace,
    official_positive_cdrs: list[dict[str, str]],
    local_positive_cdrs: list[dict[str, str]],
    portfolio_rows: list[dict[str, str]],
    novelty_performance: dict[str, object] | None = None,
) -> None:
    details = {
        "config": {
            "identity_threshold": args.identity_threshold,
            "safe_identity_threshold": args.safe_identity_threshold,
            "cluster_identity": args.cluster_identity,
            "cluster_limit": args.cluster_limit,
            "structure_tools": args.structure_tools,
            "gate_policy": args.gate_policy,
            "large_scale_fast": args.large_scale_fast,
            "official_validator_deferred": args.defer_official_validator,
            "skip_abnativ": args.skip_abnativ,
            "skip_sapiens": args.skip_sapiens,
            "skip_tnp": args.skip_tnp,
            "team_diversity_deferred": args.skip_team_diversity,
            "novelty_only_official_pass": args.novelty_only_official_pass,
            "identity_cache_size": args.identity_cache_size,
            "novelty_bound_pruning": not args.disable_novelty_bound_pruning,
        },
        "reference_counts": {
            "official_positive_cdrs": len(official_positive_cdrs),
            "local_positive_cdrs": len(local_positive_cdrs),
        },
        "portfolio_count": len(portfolio_rows),
        "novelty_performance": novelty_performance or {},
    }
    (args.outdir / "competition_qc_details.json").write_text(json.dumps(details, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
