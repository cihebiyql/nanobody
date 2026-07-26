#!/usr/bin/env python3
"""Build the official-format PVRIG Final50 submission workbook from DOCX."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation


WORD_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
}

EXPECTED_HEADERS = [
    "序号",
    "抗体名称",
    "抗体形式",
    "设计类型",
    "VH/VHH\n氨基酸序列",
    "VL\n氨基酸序列",
    "起始分子名称/来源",
    "起始分子\nVH/VHH序列",
    "起始分子\nVL序列",
    "设计说明",
    "自检结果",
    "模型预测得分/推荐依据",
    "推荐排序(Rank)",
]

PARENT_MAP = {
    "positive_pose_source_case02_pos_01_PVRIG-151_HR151": (
        "PVRIG-151_HR151",
        6,
    ),
    "positive_pose_source_case02_pos_10_151H7": ("151H7", 98),
    "positive_pose_source_case02_pos_11_151H8": ("151H8", 99),
    "positive_pose_source_case02_pos_04_PVRIG-38": ("PVRIG-38", 4),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-docx", required=True, type=Path)
    parser.add_argument("--joined-tsv", required=True, type=Path)
    parser.add_argument("--parent-fasta", required=True, type=Path)
    parser.add_argument("--freeze-receipt", required=True, type=Path)
    parser.add_argument("--output-xlsx", required=True, type=Path)
    parser.add_argument("--archive-xlsx", type=Path)
    parser.add_argument("--receipt-json", required=True, type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_template_headers(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    table = root.find(".//w:tbl", WORD_NS)
    if table is None:
        raise ValueError("template DOCX contains no table")
    first_row = table.find("./w:tr", WORD_NS)
    if first_row is None:
        raise ValueError("template table contains no rows")
    headers: list[str] = []
    for cell in first_row.findall("./w:tc", WORD_NS):
        parts: list[str] = []
        for paragraph in cell.findall(".//w:p", WORD_NS):
            text = "".join(
                node.text or "" for node in paragraph.findall(".//w:t", WORD_NS)
            ).strip()
            if text:
                parts.append(text)
        headers.append("\n".join(parts))
    return headers


def parse_fasta(path: Path) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    header: str | None = None
    parts: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                _store_fasta(records, header, "".join(parts))
            header = line[1:]
            parts = []
        else:
            parts.append(line)
    if header is not None:
        _store_fasta(records, header, "".join(parts))
    return records


def _store_fasta(
    records: dict[str, dict[str, str]], header: str, sequence: str
) -> None:
    fields = header.split("|")
    name = fields[0]
    metadata = {"name": name, "sequence": sequence}
    for field in fields[1:]:
        if "=" in field:
            key, value = field.split("=", 1)
            metadata[key] = value
    records[name] = metadata


def as_float(value: str) -> float:
    return float(value)


def design_type(row: dict[str, str]) -> str:
    if row["parent_cluster"] in PARENT_MAP:
        return "优化改造"
    if row["parent_cluster"].startswith("GENERATED_"):
        return "从头设计"
    raise ValueError(f"unmapped design provenance: {row['parent_cluster']}")


def parent_fields(
    row: dict[str, str], parents: dict[str, dict[str, str]]
) -> tuple[str, str]:
    if design_type(row) == "从头设计":
        return "不适用", "不适用"
    name, seq_id = PARENT_MAP[row["parent_cluster"]]
    parent = parents[name]
    source = f"{name} / WO2021180205A1（SEQ ID NO:{seq_id}）"
    return source, parent["sequence"]


def design_description(row: dict[str, str]) -> str:
    if design_type(row) == "从头设计":
        method = {
            "rfantibody": "RFantibody/RFdiffusion骨架与ProteinMPNN序列生成",
            "fixed_pose_mpnn": "PVRIG功能界面固定pose条件下ProteinMPNN序列生成",
        }.get(row["route"], f"{row['route']}生成流程")
        return (
            f"从头设计；采用{method}产生全新CDR组合，随后经过"
            "4个随机种子×2个PVRIG构象对接、PVRL2界面阻断几何、"
            "官方CDR新颖性及统一可开发性筛选。"
        )
    name, _seq_id = PARENT_MAP[row["parent_cluster"]]
    return (
        f"优化改造；以公开专利分子{name}为可追溯起始scaffold/pose，"
        "主要改造CDR1、CDR2、CDR3及结合界面序列；三个对应CDR对"
        "全部阳性参照identity均低于80%，并经4个随机种子×2个构象"
        "对接、阻断几何及统一可开发性筛选。"
    )


def self_check(row: dict[str, str]) -> str:
    identities = [
        as_float(row[f"positive_max_positive_cdr{i}_identity"]) for i in (1, 2, 3)
    ]
    assert row["official_validator_pass"] == "true"
    assert row["positive_all_positive_corresponding_cdrs_below_0p80"] == "true"
    assert max(identities) < 0.80
    return (
        "PASS：官方ab-data-validator；IMGT/ANARCI完整；标准20AA；"
        f"阳性最大CDR identity={identities[0]:.3f}/"
        f"{identities[1]:.3f}/{identities[2]:.3f}（均<0.80）；"
        f"队内最大CDR3 identity={as_float(row['team_max_team_cdr3_identity']):.3f}；"
        f"SHA256={row['sequence_sha256'][:16]}…"
    )


def recommendation(row: dict[str, str]) -> str:
    grade_map = {
        "A_LOWER_RISK": "A",
        "B_REVIEW": "B",
        "C_HIGH_RISK": "C",
    }
    return (
        f"机制rank={row['mechanism_rank_immutable']}；"
        f"{row['source_ranked_blocker_class']}；"
        f"strict/broad seeds={row['source_ranked_strict_seed_count']}/"
        f"{row['source_ranked_broad_seed_count']}；"
        f"pose robustness={as_float(row['source_ranked_pose_robustness_score']):.2f}；"
        f"blocking consensus={as_float(row['source_ranked_blocking_consensus_score']):.2f}；"
        f"开发性={grade_map[row['primary_developability_grade']]}；"
        f"contact cluster={row['epitope_epitope_cluster_id']}"
    )


def build_workbook(headers: list[str], rows: list[dict[str, str]], parents: dict[str, dict[str, str]]) -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "抗体提交表"
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:M{len(rows) + 1}"

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    thin = Side(style="thin", color="B7C9D6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for column, header in enumerate(headers, 1):
        cell = sheet.cell(1, column, header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        cell.border = border
    sheet.row_dimensions[1].height = 46

    design_counts: Counter[str] = Counter()
    for excel_row, row in enumerate(rows, 2):
        dtype = design_type(row)
        design_counts[dtype] += 1
        parent_name, parent_sequence = parent_fields(row, parents)
        values = [
            int(row["competition_rank_1_50"]),
            row["submission_id"],
            "VHH纳米抗体",
            dtype,
            row["sequence"],
            "不适用",
            parent_name,
            parent_sequence,
            "不适用",
            design_description(row),
            self_check(row),
            recommendation(row),
            int(row["competition_rank_1_50"]),
        ]
        for column, value in enumerate(values, 1):
            cell = sheet.cell(excel_row, column, value)
            cell.border = border
            cell.alignment = Alignment(
                vertical="top",
                horizontal="center" if column in {1, 2, 3, 4, 6, 9, 13} else "left",
                wrap_text=True,
            )
            if column in {5, 8}:
                cell.number_format = "@"
                cell.font = Font(name="Consolas", size=9)
            else:
                cell.font = Font(name="Microsoft YaHei", size=9)
        sheet.row_dimensions[excel_row].height = 92

    widths = {
        "A": 7,
        "B": 19,
        "C": 15,
        "D": 12,
        "E": 68,
        "F": 12,
        "G": 34,
        "H": 68,
        "I": 12,
        "J": 52,
        "K": 58,
        "L": 58,
        "M": 14,
    }
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width

    antibody_validation = DataValidation(
        type="list", formula1='"IgG单克隆抗体,VHH纳米抗体"', allow_blank=False
    )
    design_validation = DataValidation(
        type="list", formula1='"从头设计,优化改造"', allow_blank=False
    )
    sheet.add_data_validation(antibody_validation)
    sheet.add_data_validation(design_validation)
    antibody_validation.add(f"C2:C{len(rows) + 1}")
    design_validation.add(f"D2:D{len(rows) + 1}")

    yellow = PatternFill("solid", fgColor="FFF2CC")
    red = PatternFill("solid", fgColor="F4CCCC")
    sheet.conditional_formatting.add(
        f"L2:L{len(rows)+1}",
        FormulaRule(formula=['ISNUMBER(SEARCH("开发性=B",L2))'], fill=yellow),
    )
    sheet.conditional_formatting.add(
        f"L2:L{len(rows)+1}",
        FormulaRule(formula=['ISNUMBER(SEARCH("开发性=C",L2))'], fill=red),
    )

    sheet.print_title_rows = "1:1"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_options.horizontalCentered = True
    sheet.oddFooter.center.text = "PVRIG Final50 — official template fields"
    sheet.oddFooter.right.text = "Page &P / &N"

    assert design_counts == Counter({"从头设计": 27, "优化改造": 23})
    return workbook


def verify_workbook(path: Path, rows: list[dict[str, str]], headers: list[str]) -> None:
    workbook = load_workbook(path, read_only=True, data_only=False)
    sheet = workbook["抗体提交表"]
    actual_headers = [sheet.cell(1, column).value for column in range(1, 14)]
    assert actual_headers == headers
    assert sheet.max_row == 51
    assert sheet.max_column == 13
    for index, source in enumerate(rows, 2):
        assert sheet.cell(index, 1).value == int(source["competition_rank_1_50"])
        assert sheet.cell(index, 2).value == source["submission_id"]
        assert sheet.cell(index, 5).value == source["sequence"]
        assert sheet.cell(index, 13).value == int(source["competition_rank_1_50"])


def main() -> None:
    args = parse_args()
    template_headers = extract_template_headers(args.template_docx)
    normalized = ["".join(header.split()) for header in template_headers]
    expected_normalized = ["".join(header.split()) for header in EXPECTED_HEADERS]
    assert normalized == expected_normalized, (
        f"template headers changed: {template_headers}"
    )
    headers = EXPECTED_HEADERS
    with args.joined_tsv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    rows.sort(key=lambda row: int(row["competition_rank_1_50"]))
    assert len(rows) == 50
    assert [int(row["competition_rank_1_50"]) for row in rows] == list(range(1, 51))
    assert len({row["sequence"] for row in rows}) == 50
    parents = parse_fasta(args.parent_fasta)
    for name, _seq_id in PARENT_MAP.values():
        assert name in parents

    freeze_receipt = json.loads(args.freeze_receipt.read_text(encoding="utf-8"))
    assert freeze_receipt["state"] == "FINAL_FREEZE_COMPLETE"
    assert freeze_receipt["official_validator"]["passed"] == 50
    assert freeze_receipt["official_validator"]["failed"] == 0

    workbook = build_workbook(headers, rows, parents)
    args.output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(args.output_xlsx)
    verify_workbook(args.output_xlsx, rows, headers)

    if args.archive_xlsx:
        args.archive_xlsx.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.output_xlsx, args.archive_xlsx)
        assert sha256(args.output_xlsx) == sha256(args.archive_xlsx)

    receipt = {
        "schema_version": "pvrig_final50_official_submission_xlsx_v1",
        "state": "COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": 50,
        "columns": 13,
        "design_type_counts": {"从头设计": 27, "优化改造": 23},
        "antibody_form": "VHH纳米抗体",
        "ranking": "frozen competition_rank_1_50; literal PVRIG_CAND_001-050",
        "template_headers_exact": True,
        "official_validator_passed": 50,
        "inputs": {
            str(args.template_docx): sha256(args.template_docx),
            str(args.joined_tsv): sha256(args.joined_tsv),
            str(args.parent_fasta): sha256(args.parent_fasta),
            str(args.freeze_receipt): sha256(args.freeze_receipt),
        },
        "outputs": {
            str(args.output_xlsx): sha256(args.output_xlsx),
            **(
                {str(args.archive_xlsx): sha256(args.archive_xlsx)}
                if args.archive_xlsx
                else {}
            ),
        },
        "assertions": {
            "workbook_rows_exact_50": True,
            "workbook_columns_exact_13": True,
            "rank_exact_1_to_50": True,
            "workbook_sequences_exact_joined_evidence": True,
            "all_positive_corresponding_cdrs_below_0p80": True,
            "official_validator_50_of_50": True,
        },
        "claim_boundary": (
            "Computational submission workbook; model scores are recommendation "
            "evidence, not measured expression, purity, BLI, Kd, IC50 or blocking."
        ),
    }
    args.receipt_json.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_json.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
