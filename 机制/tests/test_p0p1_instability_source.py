from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = (
    ROOT
    / "data/audits"
    / "PVRIG_QC397_Final50_P0P1提交冻结与证据闭环_v1_20260726"
)


def load_module():
    path = ROOT / "scripts/build_qc397_final50_p0p1_joined_evidence_v1.py"
    spec = importlib.util.spec_from_file_location("p0p1_builder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def keyed(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return {row[key]: row for row in rows}


def deprefix(row: dict[str, str], prefix: str) -> dict[str, str]:
    return {
        key.removeprefix(prefix): value
        for key, value in row.items()
        if key.startswith(prefix)
    }


def test_primary_instability_comes_from_vhh_eval() -> None:
    module = load_module()
    freeze = keyed(
        AUDIT / "input_freeze/Final50_submission_freeze.tsv", "submission_id"
    )
    screen = keyed(
        AUDIT
        / "uniform_tnp_completion/Final50_uniform_screen_summary_tnp_completed.tsv",
        "id",
    )
    vhh = keyed(
        AUDIT
        / "uniform_full_qc/vhh_screen/final50_submission.vhh_eval.tsv",
        "id",
    )
    joined = keyed(
        AUDIT / "p0p1_joined/Final50_joined_evidence.tsv", "submission_id"
    )

    assert "instability_index" not in screen["PVRIG_CAND_014"]
    assert vhh["PVRIG_CAND_008"]["instability_index"] == "30.843"
    assert vhh["PVRIG_CAND_014"]["instability_index"] == "41.739"

    grades: dict[str, dict[str, str]] = {}
    for submission_id in ("PVRIG_CAND_008", "PVRIG_CAND_014"):
        frozen = dict(freeze[submission_id])
        frozen["parent_cluster"] = joined[submission_id]["parent_cluster"]
        frozen["route"] = joined[submission_id]["route"]
        grades[submission_id] = module.grade_candidate(
            official_pass=True,
            freeze=frozen,
            screen=screen[submission_id],
            vhh_eval=vhh[submission_id],
            structure=deprefix(joined[submission_id], "structure_"),
            prefusion=deprefix(joined[submission_id], "prefusion_"),
            profile_name="PRIMARY",
        )

    assert grades["PVRIG_CAND_008"]["developability_grade"] == "A_LOWER_RISK"
    assert grades["PVRIG_CAND_008"]["instability_index"] == "30.843000"
    assert grades["PVRIG_CAND_014"]["developability_grade"] == "B_REVIEW"
    assert grades["PVRIG_CAND_014"]["instability_index"] == "41.739000"
    assert (
        "INSTABILITY_INDEX_GE_40"
        in grades["PVRIG_CAND_014"]["review_reasons"]
    )
