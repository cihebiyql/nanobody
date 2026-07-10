#!/usr/bin/env python3
"""Run the local PVRIG-VHH binding/blocking MVP pipeline end to end.

The MVP joins: public VHH candidate pool -> Phase 1 sequence prior -> PVRIG
known-positive leakage/calibration gates -> ranked leakage-safe candidates and controls.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZYM = ROOT / "datasets/49_hf_broad_antibody/ZYMScott_vhh_affinity-seq/test.csv"
DEFAULT_POS = ROOT / "model_data/pvrig_blocker_positive_calibration_v0.csv"
DEFAULT_MUT = ROOT / "model_data/pvrig_blocker_mutant_control_calibration_v0.csv"
DEFAULT_SCORER = ROOT / "scripts/score_pvrig_candidates_with_calibration.py"
DEFAULT_CONTACT_EXTRACTOR = ROOT / "scripts/extract_sabdab2_single_domain_contacts_mvp.py"


def markdown_table(df: pd.DataFrame) -> str:
    """Render a markdown table without optional tabulate dependency."""
    if df.empty:
        return "当前没有可排序新候选。"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = [str(row.get(c, "")).replace("\n", " ") for c in df.columns]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def clean(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    text = str(v).strip()
    if text.lower() in {"nan", "none", "na", "n/a"}:
        return ""
    return text


def read_required(path: Path, name: str) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"Missing required {name}: {path}")
    return pd.read_csv(path)


def normalize_zym_candidates(path: Path, limit: int, seed: int) -> pd.DataFrame:
    df = read_required(path, "ZYMScott VHH candidate source")
    rows = []
    seen_seq: set[str] = set()
    # Prefer cluster diversity: one representative per cluster before filling remaining rows.
    work = df.copy()
    work["_score_num"] = pd.to_numeric(work.get("score"), errors="coerce")
    work["_score_abs"] = work["_score_num"].abs().fillna(0)
    work = work.sort_values(["cluster_id", "_score_abs", "ID"], ascending=[True, False, True])
    diverse = work.drop_duplicates(subset=["cluster_id"], keep="first") if "cluster_id" in work.columns else work
    fill = pd.concat([diverse, work], ignore_index=True)
    for _, r in fill.iterrows():
        seq = clean(r.get("seq"))
        if not seq or seq in seen_seq:
            continue
        seen_seq.add(seq)
        rows.append(
            {
                "candidate_id": f"zym_test_{clean(r.get('ID')) or len(rows):>s}".replace(" ", "_"),
                "vhh_seq": seq,
                "cdr1": clean(r.get("CDR1")),
                "cdr2": clean(r.get("CDR2")),
                "cdr3": clean(r.get("CDR3")),
                "candidate_role": "new_candidate_from_zym_vhh_affinity_seq_test",
                "source_dataset": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
                "source_score": clean(r.get("score")),
                "source_cluster_id": clean(r.get("cluster_id")),
                "control_expected_role": "rankable_new_candidate_requires_docking_after_ai_prior",
            }
        )
        if len(rows) >= limit:
            break
    return pd.DataFrame(rows)


def normalize_positive_controls(path: Path, limit: int | None = None) -> pd.DataFrame:
    df = read_required(path, "positive calibration controls")
    if limit:
        df = df.head(limit)
    rows = []
    copy_cols = [
        "top_model_consensus_class",
        "top_8x6b_class",
        "top_8x6b_hotspot",
        "top_8x6b_total_occlusion",
        "top_8x6b_cdr3_occlusion",
        "top_8x6b_cdr3_fraction",
        "top_9e6y_class",
        "top_9e6y_hotspot",
        "top_9e6y_total_occlusion",
        "top_9e6y_cdr3_occlusion",
        "top_9e6y_cdr3_fraction",
    ]
    for _, r in df.iterrows():
        rec = {
            "candidate_id": clean(r.get("calibration_id")) or clean(r.get("molecule_name")),
            "vhh_seq": clean(r.get("sequence")),
            "cdr1": clean(r.get("cdr1")),
            "cdr2": clean(r.get("cdr2")),
            "cdr3": clean(r.get("cdr3")),
            "candidate_role": "known_pvrig_blocking_positive_control_not_ranked",
            "source_dataset": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
            "source_score": "",
            "source_cluster_id": clean(r.get("family")),
            "control_expected_role": "exact_known_positive_should_be_excluded_from_new_ranking",
            "source_case_level_call": clean(r.get("case_level_call")),
            "blocking_ic50_nm": clean(r.get("blocking_ic50_nm")),
            "kd_m": clean(r.get("kd_m")),
        }
        for col in copy_cols:
            rec[col] = clean(r.get(col))
        rows.append(rec)
    return pd.DataFrame(rows)


def normalize_mutant_controls(path: Path, limit: int | None = None) -> pd.DataFrame:
    df = read_required(path, "mutant/leakage controls")
    if limit:
        df = df.head(limit)
    rows = []
    for _, r in df.iterrows():
        rows.append(
            {
                "candidate_id": clean(r.get("control_id")),
                "vhh_seq": clean(r.get("sequence")),
                "cdr1": "",
                "cdr2": "",
                "cdr3": "",
                "candidate_role": "mutant_or_leakage_control_not_ranked",
                "source_dataset": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
                "source_score": "",
                "source_cluster_id": clean(r.get("family")),
                "control_expected_role": "exact_or_near_known_positive_should_be_excluded_or_held",
                "source_case_level_call": clean(r.get("mutation_class")),
                "source_leakage_label": clean(r.get("leakage_label")),
                "source_identity_fraction": clean(r.get("identity_fraction")),
            }
        )
    return pd.DataFrame(rows)


def build_candidate_pool(args: argparse.Namespace) -> pd.DataFrame:
    if args.candidates:
        df = pd.read_csv(args.candidates)
        if "candidate_role" not in df.columns:
            df["candidate_role"] = "user_supplied_candidate"
        if "vhh_seq" not in df.columns and "sequence" in df.columns:
            df["vhh_seq"] = df["sequence"]
        return df
    parts = [
        normalize_zym_candidates(Path(args.zym_source), args.candidate_limit, args.seed),
        normalize_positive_controls(Path(args.positive_calibration), args.positive_control_limit),
        normalize_mutant_controls(Path(args.mutant_controls), args.mutant_control_limit),
    ]
    out = pd.concat(parts, ignore_index=True, sort=False)
    out = out.drop_duplicates(subset=["candidate_id"], keep="first")
    return out


def run_scorer(candidate_path: Path, scored_path: Path, top_k: int) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(DEFAULT_SCORER),
        "--candidates",
        str(candidate_path),
        "--out",
        str(scored_path),
        "--top-k",
        str(top_k),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"Scorer failed with {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    try:
        summary = json.loads(proc.stdout)
    except Exception:
        summary = {"stdout": proc.stdout.strip()}
    summary["stderr"] = proc.stderr.strip()
    return summary


def run_contact_extractor(args: argparse.Namespace, contact_out: Path, contact_report: Path) -> dict[str, Any]:
    if args.skip_contact_extraction:
        return {"skipped": True, "reason": "skip_contact_extraction_flag"}
    cmd = [
        sys.executable,
        str(DEFAULT_CONTACT_EXTRACTOR),
        "--max-structures",
        str(args.contact_max_structures),
        "--out",
        str(contact_out),
        "--report",
        str(contact_report),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"Contact extractor failed with {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    try:
        summary = json.loads(proc.stdout)
    except Exception:
        summary = {"stdout": proc.stdout.strip()}
    summary["stderr"] = proc.stderr.strip()
    return summary


def minmax(s: pd.Series) -> pd.Series:
    vals = pd.to_numeric(s, errors="coerce").fillna(0.0)
    lo = vals.min()
    hi = vals.max()
    if float(hi - lo) < 1e-12:
        return pd.Series(np.zeros(len(vals)), index=s.index)
    return (vals - lo) / (hi - lo)


def rank_candidates(scored: pd.DataFrame, pool: pd.DataFrame, top_n: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = scored.merge(pool, on="candidate_id", how="left", suffixes=("", "_input"))
    merged["is_rankable_new_candidate"] = (
        merged.get("candidate_role", "").astype(str).str.contains("new_candidate", na=False)
        & merged.get("leakage_label", "").astype(str).eq("NO_KNOWN_POSITIVE_LEAKAGE")
        & ~merged.get("final_blocker_like_calibrated_label", "").astype(str).str.contains("EXCLUDE|HOLD_NEAR", regex=True, na=False)
    )
    ai_priority = merged.get("ai_prior_label", "").astype(str).map(
        {
            "AI_PRIOR_HIGH_NEEDS_DOCKING": 3.0,
            "AI_PRIOR_MEDIUM_NEEDS_DOCKING": 2.0,
            "AI_PRIOR_LOW_NEEDS_DOCKING": 1.0,
            "AI_PRIOR_NO_TARGET_SIGNAL": 0.0,
        }
    ).fillna(0.0)
    merged["mvp_rank_score"] = (
        0.30 * ai_priority / 3.0
        + 0.25 * minmax(merged.get("ai_pvrig_weighted_target_probability_sum", 0))
        + 0.15 * minmax(merged.get("ai_pvrig_target_recall_top50", 0))
        + 0.15 * minmax(merged.get("ai_max_paratope_probability", 0))
        + 0.10 * minmax(merged.get("ai_max_pvrig_epitope_probability", 0))
        + 0.05 * minmax(merged.get("ai_vhh_score_raw", 0))
    )
    rankable = merged[merged["is_rankable_new_candidate"]].copy()
    top = rankable.sort_values(
        ["mvp_rank_score", "ai_pvrig_weighted_target_probability_sum", "ai_max_paratope_probability"],
        ascending=[False, False, False],
    ).head(top_n)
    controls = merged[~merged["is_rankable_new_candidate"]].copy()
    return top, controls


def write_report(
    args: argparse.Namespace,
    pool: pd.DataFrame,
    scored: pd.DataFrame,
    top: pd.DataFrame,
    controls: pd.DataFrame,
    scorer_summary: dict[str, Any],
    contact_summary: dict[str, Any],
    paths: dict[str, Path],
) -> None:
    label_counts = scored.get("final_blocker_like_calibrated_label", pd.Series(dtype=str)).value_counts().to_dict()
    leakage_counts = scored.get("leakage_label", pd.Series(dtype=str)).value_counts().to_dict()
    role_counts = pool.get("candidate_role", pd.Series(dtype=str)).value_counts().to_dict()
    top_cols = [
        "candidate_id",
        "mvp_rank_score",
        "ai_prior_label",
        "final_blocker_like_calibrated_label",
        "ai_pvrig_weighted_target_probability_sum",
        "ai_pvrig_target_hits_top50",
        "ai_max_paratope_probability",
        "ai_max_pvrig_epitope_probability",
        "recommended_next_step",
    ]
    top_preview = top[[c for c in top_cols if c in top.columns]].head(20)
    metrics_path = ROOT / "models/phase1_sequence_baseline/metrics.json"
    model_metric_summary: dict[str, Any] = {"metrics_path": str(metrics_path), "status": "missing"}
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        model_metric_summary = {
            "metrics_path": str(metrics_path),
            "paratope_test_auroc": metrics.get("paratope", {}).get("metrics", {}).get("test", {}).get("auroc"),
            "paratope_test_auprc": metrics.get("paratope", {}).get("metrics", {}).get("test", {}).get("auprc"),
            "epitope_test_auroc": metrics.get("epitope", {}).get("metrics", {}).get("test", {}).get("auroc"),
            "epitope_test_auprc": metrics.get("epitope", {}).get("metrics", {}).get("test", {}).get("auprc"),
            "vhh_score_test_pearson": metrics.get("vhh_score", {}).get("metrics", {}).get("test", {}).get("pearson"),
            "vhh_score_test_spearman": metrics.get("vhh_score", {}).get("metrics", {}).get("test", {}).get("spearman"),
        }
    new_candidate_count = int(
        scored.merge(pool[["candidate_id", "candidate_role"]], on="candidate_id", how="left")
        .get("candidate_role", "")
        .astype(str)
        .str.contains("new_candidate", na=False)
        .sum()
    )
    report = f"""# PVRIG-VHH 结合/阻断预测 MVP 报告

Updated: 2026-07-09

## MVP 结论

本 MVP 已把当前本地数据链路串起来：VHH 候选池 -> Phase 1 序列/表位先验模型 -> PVRIG 已知阳性与突变控制校准 -> 泄漏排除 -> Top 新候选排序。

重要边界：没有提供 docking consensus 的新候选不会被宣称为真实 blocker，只能标记为 `*_NEEDS_DOCKING_CALIBRATION`。已知 PVRIG 阳性/阻断 VHH 只作为控制和校准，不进入新候选排名。

## 输入与产物

| 类型 | 路径 |
| --- | --- |
| MVP 候选池 | `{paths['candidate_pool']}` |
| 全量打分表 | `{paths['scores']}` |
| Top 新候选 | `{paths['top']}` |
| 控制组结果 | `{paths['controls']}` |
| 结构 contact MVP | `{paths['contact_out']}` |
| 结构 contact 报告 | `{paths['contact_report']}` |
| 运行摘要 | `{paths['summary']}` |

## 数据规模

| 项目 | 数量 |
| --- | ---: |
| 候选池总行数 | {len(pool)} |
| 新候选输入行数 | {new_candidate_count} |
| Top 输出行数 | {len(top)} |
| 控制组行数 | {len(controls)} |

候选角色分布：

```json
{json.dumps(role_counts, ensure_ascii=False, indent=2, sort_keys=True)}
```

最终标签分布：

```json
{json.dumps(label_counts, ensure_ascii=False, indent=2, sort_keys=True)}
```

泄漏标签分布：

```json
{json.dumps(leakage_counts, ensure_ascii=False, indent=2, sort_keys=True)}
```

## Phase 1 小模型资产

本 MVP 复用已经训练好的纯 NumPy baseline，不依赖 PyTorch/sklearn。它包含 VHH paratope residue head、PVRIG/antigen epitope residue head 和 VHH score ridge head。指标只能说明通用 VHH-抗原接触先验有效，不能直接等价为 PVRIG 实验结合或阻断能力。

```json
{json.dumps(model_metric_summary, ensure_ascii=False, indent=2, sort_keys=True)}
```

## 结构接触 MVP

本轮同时抽取了 SAbDab2 single-domain antibody-antigen 结构接触小样本，用于证明结构标注通路可运行。该 contact set 当前作为后续结构模型/图特征的 MVP 证据，不参与本轮序列先验训练。

```json
{json.dumps(contact_summary, ensure_ascii=False, indent=2, sort_keys=True)}
```

## Top 新候选预览

{markdown_table(top_preview)}

## 如何解释分数

- `mvp_rank_score`：MVP 内部排序分数，用于在无 docking 的新候选中优先挑选下一批结构预测/docking 对象。
- `ai_prior_label`：Phase 1 序列模型对 PVRIG 目标表位的先验等级。
- `final_blocker_like_calibrated_label`：融合泄漏控制和可选 docking/consensus 后的最终计算标签。
- `CALIBRATED_BLOCKER_LIKE_A` 只能在有 docking/consensus 或数值 docking gate 支持时出现。
- `AI_PRIOR_*_NEEDS_DOCKING_CALIBRATION` 表示可以进入下一轮 docking，不是实验结合/阻断证明。

## 控制组校准

- exact known-positive 会被标记为 `EXCLUDE_EXACT_KNOWN_POSITIVE_CONTROL`，保留为阳性/泄漏控制，不参与新候选排名。
- near known-positive 或 CDR 相似控制会被标记为 `HOLD_NEAR_KNOWN_POSITIVE_MANUAL_LEAKAGE_REVIEW`。
- mutant/control panel 用于观察流程是否把扰动阳性误当新设计。

## 一键复跑

```bash
./scripts/run_pvrig_mvp_pipeline.py --candidate-limit {args.candidate_limit} --top-n {args.top_n}
```

## 下一步

1. 对 `{paths['top']}` 中的 Top 新候选批量做结构预测。
2. 对预测结构执行 8X6B / 9E6Y 双基线 docking。
3. 把 docking consensus / hotspot / occlusion 列回填后再次运行本脚本。
4. 只有通过泄漏排除且获得 calibrated blocker-like docking 证据的候选，才进入最终 Top 50。

## Scorer stdout summary

```json
{json.dumps(scorer_summary, ensure_ascii=False, indent=2, sort_keys=True)}
```
"""
    paths["report"].write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="", help="Optional user candidate CSV. If omitted, build an MVP pool from local data.")
    parser.add_argument("--zym-source", default=str(DEFAULT_ZYM))
    parser.add_argument("--positive-calibration", default=str(DEFAULT_POS))
    parser.add_argument("--mutant-controls", default=str(DEFAULT_MUT))
    parser.add_argument("--candidate-limit", type=int, default=500)
    parser.add_argument("--positive-control-limit", type=int, default=0, help="0 means all")
    parser.add_argument("--mutant-control-limit", type=int, default=0, help="0 means all")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--top-k-residues", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260709)
    parser.add_argument("--candidate-pool-out", default="model_data/mvp_candidates_v0.csv")
    parser.add_argument("--scores-out", default="reports/mvp_pvrig_candidate_scores_v0.csv")
    parser.add_argument("--top-out", default="reports/mvp_pvrig_top_candidates_v0.csv")
    parser.add_argument("--controls-out", default="reports/mvp_pvrig_control_scores_v0.csv")
    parser.add_argument("--summary-out", default="reports/mvp_pvrig_summary_v0.json")
    parser.add_argument("--report-out", default="reports/MVP_PVRIG_VHH_WORKFLOW_REPORT.md")
    parser.add_argument("--contact-out", default="model_data/sabdab2_single_domain_contacts_mvp.csv")
    parser.add_argument("--contact-report", default="reports/sabdab2_contact_extraction_mvp.md")
    parser.add_argument("--contact-max-structures", type=int, default=12)
    parser.add_argument("--skip-contact-extraction", action="store_true")
    args = parser.parse_args()

    if args.positive_control_limit <= 0:
        args.positive_control_limit = None
    if args.mutant_control_limit <= 0:
        args.mutant_control_limit = None

    paths = {
        "candidate_pool": ROOT / args.candidate_pool_out,
        "scores": ROOT / args.scores_out,
        "top": ROOT / args.top_out,
        "controls": ROOT / args.controls_out,
        "summary": ROOT / args.summary_out,
        "report": ROOT / args.report_out,
        "contact_out": ROOT / args.contact_out,
        "contact_report": ROOT / args.contact_report,
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    pool = build_candidate_pool(args)
    if pool.empty:
        raise SystemExit("MVP candidate pool is empty")
    required = {"candidate_id", "vhh_seq"}
    missing = required - set(pool.columns)
    if missing:
        raise SystemExit(f"Candidate pool missing required columns: {sorted(missing)}")
    pool.to_csv(paths["candidate_pool"], index=False, quoting=csv.QUOTE_MINIMAL)

    scorer_summary = run_scorer(paths["candidate_pool"], paths["scores"], args.top_k_residues)
    contact_summary = run_contact_extractor(args, paths["contact_out"], paths["contact_report"])
    scored = pd.read_csv(paths["scores"])
    top, controls = rank_candidates(scored, pool, args.top_n)
    top.to_csv(paths["top"], index=False, quoting=csv.QUOTE_MINIMAL)
    controls.to_csv(paths["controls"], index=False, quoting=csv.QUOTE_MINIMAL)

    summary = {
        "candidate_pool_rows": int(len(pool)),
        "scored_rows": int(len(scored)),
        "top_rows": int(len(top)),
        "control_rows": int(len(controls)),
        "candidate_role_counts": pool.get("candidate_role", pd.Series(dtype=str)).value_counts().to_dict(),
        "final_label_counts": scored.get("final_blocker_like_calibrated_label", pd.Series(dtype=str)).value_counts().to_dict(),
        "leakage_label_counts": scored.get("leakage_label", pd.Series(dtype=str)).value_counts().to_dict(),
        "contact_extraction_summary": contact_summary,
        "paths": {k: str(v) for k, v in paths.items()},
        "boundary": "MVP computational prioritization only; new candidates require docking and experimental validation.",
    }
    paths["summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    write_report(args, pool, scored, top, controls, scorer_summary, contact_summary, paths)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
