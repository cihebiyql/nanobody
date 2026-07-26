from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = (
    ROOT
    / "data/audits"
    / "PVRIG_QC397_Final50_P0P1提交冻结与证据闭环_v1_2_20260726"
)


def load_module():
    path = ROOT / "scripts/build_pvrig_final50_submission_xlsx_v1.py"
    spec = importlib.util.spec_from_file_location("submission_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def keyed(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return {row[key]: row for row in rows}


def test_fixed_pose_description_discloses_positive_framework_and_pose() -> None:
    module = load_module()
    joined = keyed(
        AUDIT / "p0p1_joined/Final50_joined_evidence.tsv", "submission_id"
    )
    lineage = keyed(
        AUDIT
        / "fixed_pose_provenance/Final50_fixed_pose_CDR123_redesign_audit.tsv",
        "candidate_id",
    )
    row = dict(joined["PVRIG_CAND_002"])
    row["_fixed_pose_parent_id"] = lineage[row["candidate_id"]]["parent_id"]

    description = module.design_description(row)

    assert "从头设计（全新CDR区）" in description
    assert "公开专利阳性VHH 151H7" in description
    assert "framework" in description
    assert "计算获得的PVRIG结合pose" in description
    assert "CDR1、CDR2和CDR3全部重新设计" in description
    assert "未直接沿用任何已知阳性抗体的完整CDR" in description


def test_nglyc_annotation_reports_boundary_and_cdr_motifs() -> None:
    module = load_module()
    joined = keyed(
        AUDIT / "p0p1_joined/Final50_joined_evidence.tsv", "submission_id"
    )

    boundary = module.nglycosylation_annotation(joined["PVRIG_CAND_026"])
    cdr = module.nglycosylation_annotation(joined["PVRIG_CAND_050"])
    clean = module.nglycosylation_annotation(joined["PVRIG_CAND_001"])

    assert "NVT@58（跨CDR2/FR邻接区域）" in boundary
    assert "潜在糖基化风险" in boundary
    assert "NLS@101（位于CDR3）" in cdr
    assert "内部高风险" in cdr
    assert clean == "全序列N-X-S/T motif=无"
