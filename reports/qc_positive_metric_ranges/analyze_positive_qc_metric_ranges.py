#!/usr/bin/env python3
"""Summarize positive-control QC metric ranges for the PVRIG VHH workflow.

The script intentionally separates positive-derived calibration ranges from
candidate pass/fail gates: the 11 inputs are known positives/leakage controls,
not acceptable new competition submissions.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

DEFAULT_BASE = Path(__file__).resolve().parent
DEFAULT_QC = DEFAULT_BASE / "node1_pvrig_11_positive_qc"


def display_id(raw: str) -> str:
    if raw is None:
        return ""
    raw = str(raw)
    return raw.split("_family_", 1)[0]


def read_delimited(path: Path, delimiter: str = "\t") -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    weight = pos - lo
    return sorted_values[lo] * (1 - weight) + sorted_values[hi] * weight


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def numeric_summary(values: Iterable[Any], total: int) -> dict[str, str]:
    nums = [v for v in (maybe_float(v) for v in values) if v is not None]
    nums.sort()
    return {
        "n": str(len(nums)),
        "missing": str(total - len(nums)),
        "min": fmt(nums[0]) if nums else "",
        "q1": fmt(quantile(nums, 0.25)) if nums else "",
        "median": fmt(median(nums)) if nums else "",
        "q3": fmt(quantile(nums, 0.75)) if nums else "",
        "max": fmt(nums[-1]) if nums else "",
        "mean": fmt(mean(nums)) if nums else "",
        "counts": "",
    }


def categorical_summary(values: Iterable[Any], total: int) -> dict[str, str]:
    normalized = []
    missing = 0
    for value in values:
        text = "" if value is None else str(value).strip()
        if not text:
            missing += 1
        else:
            normalized.append(text)
    counts = Counter(normalized)
    return {
        "n": str(len(normalized)),
        "missing": str(missing + total - len(normalized) - missing),
        "min": "",
        "q1": "",
        "median": "",
        "q3": "",
        "max": "",
        "mean": "",
        "counts": "; ".join(f"{key}={value}" for key, value in counts.most_common()),
    }


def add_row(
    rows: list[dict[str, str]],
    *,
    metric: str,
    source: str,
    kind: str,
    values: list[Any],
    total: int,
    positive_observation: str,
    proposed_use: str,
    robustness: str,
    recommendation: str,
) -> None:
    summary = numeric_summary(values, total) if kind == "numeric" else categorical_summary(values, total)
    rows.append(
        {
            "metric": metric,
            "source": source,
            "kind": kind,
            **summary,
            "positive_observation": positive_observation,
            "proposed_use": proposed_use,
            "robustness": robustness,
            "recommendation": recommendation,
        }
    )


def load_inputs(qc_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    screen = read_delimited(qc_dir / "vhh_screen" / "screen_summary.tsv", "\t")
    vhh_eval = read_delimited(qc_dir / "vhh_screen" / "pvrig11_positive.vhh_eval.tsv", "\t")
    portfolio = read_delimited(qc_dir / "portfolio_ranked.tsv", "\t")
    novelty = read_delimited(qc_dir / "cdr_novelty.tsv", "\t")
    diversity = read_delimited(qc_dir / "team_diversity.tsv", "\t")
    official = read_delimited(qc_dir / "official_failed_reasons.csv", ",")
    details_path = qc_dir / "competition_qc_details.json"
    details = json.loads(details_path.read_text(encoding="utf-8")) if details_path.exists() else {}
    tnp_path = qc_dir / "tnp_safe_all11" / "TNP_Results_Multientry.json"
    tnp = json.loads(tnp_path.read_text(encoding="utf-8")) if tnp_path.exists() else {}

    per: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in screen:
        per[display_id(row.get("id", ""))].update(row)
        per[display_id(row.get("id", ""))]["display_id"] = display_id(row.get("id", ""))
    for row in vhh_eval:
        key = display_id(row.get("id", ""))
        for k, v in row.items():
            per[key][f"eval_{k}"] = v
        per[key]["sequence"] = row.get("sequence", per[key].get("sequence", ""))
    for row in portfolio:
        key = display_id(row.get("candidate_id", ""))
        for k, v in row.items():
            per[key][f"portfolio_{k}"] = v
    for row in novelty:
        key = display_id(row.get("candidate_id", ""))
        for k, v in row.items():
            per[key][f"novelty_{k}"] = v
    for row in diversity:
        key = display_id(row.get("candidate_id", ""))
        for k, v in row.items():
            per[key][f"diversity_{k}"] = v
    for key, row in tnp.items():
        per[display_id(key)]["tnp_total_cdr_length"] = row.get("Total CDR Length", "")
        per[display_id(key)]["tnp_cdr3_length"] = row.get("CDR3 Length", "")
        per[display_id(key)]["tnp_cdr3_compactness"] = row.get("CDR3 Compactness", "")
        per[display_id(key)]["tnp_PSH_all11"] = row.get("PSH", "")
        per[display_id(key)]["tnp_PPC_all11"] = row.get("PPC", "")
        per[display_id(key)]["tnp_PNC_all11"] = row.get("PNC", "")
        flags = row.get("Flags", {}) or {}
        for flag_name, flag_value in flags.items():
            per[display_id(key)][f"tnp_{flag_name}_flag_all11"] = flag_value

    aux = {"official_failed_reasons": official, "details": details, "tnp": tnp}
    return dict(per), aux


def make_metric_rows(per: dict[str, dict[str, Any]], aux: dict[str, Any]) -> list[dict[str, str]]:
    total = len(per)
    rows: list[dict[str, str]] = []
    get = lambda field: [record.get(field, "") for record in per.values()]

    add_row(rows, metric="final_verdict", source="screen_summary.tsv", kind="categorical", values=get("final_verdict"), total=total, positive_observation="阳性校准序列也会被 QC 分成 REVIEW / NOT_VHH_LIKE / DEVELOPABILITY 风险。", proposed_use="不要当阻断生物学 hard gate；只作提交/开发性分层。", robustness="中等", recommendation="已知 blocker 中 6/11 被判 not VHH-like，说明该门控不能等价为不阻断。")
    add_row(rows, metric="L1_numbering_integrity", source="screen_summary.tsv", kind="categorical", values=get("L1_numbering_integrity"), total=total, positive_observation="11/11 PASS。", proposed_use="hard gate", robustness="高", recommendation="新候选必须能稳定编号并取出完整 FR/CDR。")
    add_row(rows, metric="L2_vhh_features", source="screen_summary.tsv", kind="categorical", values=get("L2_vhh_features"), total=total, positive_observation="PASS/WARN/FAIL 都出现在阳性 blocker 中。", proposed_use="warn/review 或提交风险 gate", robustness="低到中", recommendation="不能作为 blocker 否决；可作为表达/单域性风险。")
    add_row(rows, metric="single_domain_suitability", source="screen_summary.tsv", kind="categorical", values=get("single_domain_suitability"), total=total, positive_observation="good/poor 都出现在阳性 blocker 中。", proposed_use="warn/review", robustness="低到中", recommendation="poor 不能自动解释为无阻断；只能提示单域性/表达风险。")
    add_row(rows, metric="L3_developability", source="screen_summary.tsv", kind="categorical", values=get("L3_developability"), total=total, positive_observation="L2 fail 后会跳过，非全量。", proposed_use="warn/ranking；严重责任位点人工复核", robustness="中等", recommendation="不要把单个 developability flag 解释成无阻断。")
    add_row(rows, metric="L4_structure_stability", source="screen_summary.tsv", kind="categorical", values=get("L4_structure_stability"), total=total, positive_observation="本次 vhh-competition-qc 未请求结构工具。", proposed_use="未覆盖；需单独结构流程", robustness="未评估", recommendation="结构稳定性不能从本次 QC 输出判断。")
    add_row(rows, metric="official_validator_pass", source="portfolio_ranked.tsv", kind="categorical", values=get("portfolio_official_validator_pass"), total=total, positive_observation="11/11 FAIL，原因是阳性 CDR 相似性。", proposed_use="hard gate", robustness="高", recommendation="这是泄漏排除成功，不是阳性质量差。")
    add_row(rows, metric="pass_similarity_filter", source="cdr_novelty.tsv", kind="categorical", values=get("novelty_pass_similarity_filter"), total=total, positive_observation="11/11 FAIL。", proposed_use="hard gate", robustness="高", recommendation="新候选任一 CDR 对阳性 identity >=0.80 应拦截；0.75-0.80 标边界。")
    add_row(rows, metric="max_CDR_identity_to_positive", source="cdr_novelty.tsv", kind="numeric", values=get("novelty_max_CDR_identity_to_positive"), total=total, positive_observation="阳性校准集全部触达 exact/near-positive 泄漏信号。", proposed_use="hard gate", robustness="高", recommendation="不要放宽 >=0.80；这是防抄袭/泄漏门控。")

    numeric_defs = [
        ("length", "screen_summary.tsv", "长度阳性范围较窄，但不应把 120-127 当唯一可行长度。", "hard broad range + preferred envelope", "高", "保留 95-160 硬范围；105/110-145 或阳性范围附近作 ranking/warn。"),
        ("imgt_cdr1_len", "screen_summary.tsv", "CDR1 长度有稳定窄范围。", "warn/ranking", "中等", "明显偏离 8-10 时复核编号和结构；不要单独 hard fail。"),
        ("imgt_cdr2_len", "screen_summary.tsv", "CDR2 长度有稳定窄范围。", "warn/ranking", "中等", "明显偏离 7-8 时复核编号和结构。"),
        ("imgt_cdr3_len", "screen_summary.tsv", "CDR3 覆盖短/中/偏长阳性。", "warn/ranking", "中等", "14-19 是本 PVRIG 阳性 envelope；极端 CDR3 需结构确认。"),
        ("fr2_hallmark_score", "screen_summary.tsv", "阳性中最低只有 0.25。", "warn/review", "低", "不能作为 blocker hard gate；用于单域性/表达风险。"),
        ("fr2_interface_hydrophobic_count", "screen_summary.tsv", "阳性中可为 0 或 1。", "warn/review", "中等", "FR2 接触面过疏水提示聚集风险，不是阻断否决。"),
        ("abnativ_vhh_score", "screen_summary.tsv", "9/11 有值且均在较高区间，2 条缺失。", "warn/ranking", "中等", "有值时 <0.55 fail、0.55-0.70 warn 合理；缺值不应直接 hard fail。"),
        ("abnativ_fr_vhh_score", "screen_summary.tsv", "9/11 有值，FR 框架分数整体高。", "warn/ranking", "中等", "用于 VHH-like/框架自然性排序。"),
        ("sapiens_mean_self_probability", "screen_summary.tsv", "阳性自概率偏低到中等，反映人源化负担。", "ranking", "中等", "用于人源化/免疫原性负担，不判断阻断。"),
        ("sapiens_num_suggested_mutations", "screen_summary.tsv", "阳性也需要较多建议突变。", "ranking", "中等", "建议突变数高时降优先级，但不否决 blocker。"),
        ("mw", "screen_summary.tsv", "分子量与 VHH 长度一致。", "sanity/warn", "中等", "主要做异常输入检查。"),
        ("pI", "screen_summary.tsv", "酸性到偏碱性阳性都存在。", "warn/ranking", "中等", "极端 pI 才开发性降级；本范围不是 hard gate。"),
        ("charge_pH7_4", "screen_summary.tsv", "阳性允许负电到轻微正电。", "warn/ranking", "中等", "极端电荷提示表达/非特异风险。"),
        ("gravy", "screen_summary.tsv", "阳性均偏亲水。", "warn/ranking", "中等", "候选明显更疏水时降级/复核。"),
        ("eval_instability_index", "pvrig11_positive.vhh_eval.tsv", "阳性均在 35-40 附近。", "ranking", "中等", "用于可开发性排序，不判断阻断。"),
        ("nglyc_motif_count", "screen_summary.tsv", "11/11 为 0。", "developability warn/hard by location", "中等", "CDR 内 N-glyc motif 可 hard/warn；框架中人工复核。"),
        ("cys_count", "screen_summary.tsv", "2 或 4 个 Cys 均可出现在阳性中。", "warn/review", "中等", "非经典 Cys 不能自动否决 blocker；必须看成键/结构。"),
        ("deamidation_NG_NS_NT_count", "screen_summary.tsv", "阳性允许 0-2 个。", "warn/review", "中等", "位置相关复核，不单独 hard fail。"),
        ("isomerization_DG_DS_DD_DT_count", "screen_summary.tsv", "阳性普遍含 2-5 个。", "warn/review", "低到中", "该 motif 太常见，不能单独 hard fail。"),
        ("acid_cleavage_DP_count", "screen_summary.tsv", "11/11 为 0。", "warn/review", "中等", "出现 DP 时按位置复核。"),
        ("eval_oxidation_MW_count", "pvrig11_positive.vhh_eval.tsv", "阳性仍可有氧化风险计数。", "warn/review", "中等", "评估位置和暴露度。"),
        ("hydrophobic_5_count", "screen_summary.tsv", "有 1 条阳性触发 5 连疏水并 L3 FAIL。", "warn/developability risk", "中等", "不应作为 blocker hard fail，但应降级并人工复核。"),
        ("diversity_max_team_identity", "team_diversity.tsv", "阳性家族内高度相似。", "portfolio constraint", "中等", "用于组合多样性，不评价单条阻断能力。"),
        ("diversity_intra_team_cluster_size", "team_diversity.tsv", "阳性分成多个家族簇。", "portfolio constraint", "中等", "批量提交时限制同簇数量。"),
        ("diversity_diversity_score", "team_diversity.tsv", "多样性分数在硬拒绝背景下仍可计算。", "portfolio ranking", "中等", "只能在 hard gate 通过后用于排序。"),
        ("tnp_total_cdr_length", "TNP_Results_Multientry.json", "all-11 TNP 长度全绿。", "warn/ranking", "中等", "作为 CDR 尺寸/可开发性佐证。"),
        ("tnp_cdr3_length", "TNP_Results_Multientry.json", "all-11 TNP CDR3 长度全绿。", "warn/ranking", "中等", "与 IMGT CDR3 envelope 互相校验。"),
        ("tnp_cdr3_compactness", "TNP_Results_Multientry.json", "all-11 compactness 全绿。", "warn/ranking", "中等", "结构/可开发性风险指标，不替代 docking。"),
        ("tnp_PSH_all11", "TNP_Results_Multientry.json", "all-11 PSH 全绿。", "warn/ranking", "中等", "高表面疏水候选应降级/复核。"),
        ("tnp_PPC_all11", "TNP_Results_Multientry.json", "all-11 PPC 全绿。", "warn/ranking", "中等", "正电 patch 风险用于开发性排序。"),
        ("tnp_PNC_all11", "TNP_Results_Multientry.json", "2/11 阳性 PNC 为红。", "warn/review", "低到中", "PNC 红不能作为 blocker 否决，只能开发性复核。"),
    ]
    for metric, source, obs, use, robust, reco in numeric_defs:
        add_row(rows, metric=metric, source=source, kind="numeric", values=get(metric), total=total, positive_observation=obs, proposed_use=use, robustness=robust, recommendation=reco)

    for flag in ["tnp_L_flag_all11", "tnp_L3_flag_all11", "tnp_C_flag_all11", "tnp_PSH_flag_all11", "tnp_PPC_flag_all11", "tnp_PNC_flag_all11"]:
        obs = "TNP all-11 补跑得到的 flag。"
        reco = "红色 flag 进入开发性复核；不要直接解释为无阻断。"
        if flag != "tnp_PNC_flag_all11":
            reco = "本阳性集全绿，可作为候选开发性风险参考。"
        add_row(rows, metric=flag, source="TNP_Results_Multientry.json", kind="categorical", values=get(flag), total=total, positive_observation=obs, proposed_use="warn/review", robustness="中等", recommendation=reco)

    return rows


def write_per_sequence(per: dict[str, dict[str, Any]], out_path: Path) -> None:
    key_fields = [
        "display_id", "length", "imgt_cdr1_len", "imgt_cdr2_len", "imgt_cdr3_len",
        "final_verdict", "L1_numbering_integrity", "L2_vhh_features", "L3_developability", "L4_structure_stability",
        "fr2_hallmark_score", "single_domain_suitability", "abnativ_vhh_score", "abnativ_fr_vhh_score",
        "sapiens_mean_self_probability", "sapiens_num_suggested_mutations", "mw", "pI", "charge_pH7_4", "gravy", "eval_instability_index",
        "nglyc_motif_count", "cys_count", "deamidation_NG_NS_NT_count", "isomerization_DG_DS_DD_DT_count", "hydrophobic_5_count",
        "tnp_total_cdr_length", "tnp_cdr3_length", "tnp_cdr3_compactness", "tnp_PSH_all11", "tnp_PPC_all11", "tnp_PNC_all11", "tnp_PNC_flag_all11",
        "novelty_max_CDR_identity_to_positive", "novelty_pass_similarity_filter", "portfolio_official_validator_pass", "portfolio_hard_fail", "portfolio_recommendation",
        "diversity_intra_team_cluster_id", "diversity_intra_team_cluster_size", "diversity_max_team_identity", "diversity_diversity_score",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=key_fields)
        writer.writeheader()
        for key in sorted(per):
            record = per[key]
            writer.writerow({field: record.get(field, "") for field in key_fields})


def write_metric_csv(rows: list[dict[str, str]], out_path: Path) -> None:
    fieldnames = ["metric", "source", "kind", "n", "missing", "min", "q1", "median", "q3", "max", "mean", "counts", "positive_observation", "proposed_use", "robustness", "recommendation"]
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def metric_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["metric"]: row for row in rows}


def range_text(row: dict[str, str]) -> str:
    if row["kind"] == "categorical":
        return row["counts"]
    return f"{row['min']} - {row['max']} (median {row['median']}, n={row['n']}, missing={row['missing']})"


def write_report(
    out_path: Path,
    rows: list[dict[str, str]],
    per: dict[str, dict[str, Any]],
    aux: dict[str, Any],
    qc_dir: Path,
    metric_csv: Path,
    per_seq_csv: Path,
) -> None:
    m = metric_lookup(rows)
    details = aux.get("details", {}) or {}
    config = details.get("config", {}) if isinstance(details, dict) else {}
    refs = details.get("reference_counts", {}) if isinstance(details, dict) else {}
    official = aux.get("official_failed_reasons", [])
    tnp = aux.get("tnp", {}) or {}
    official_reason_counts = Counter(row.get("reason_type", "") for row in official)
    official_cdr_counts = Counter(row.get("cdr", "") for row in official)
    official_identity_values = [maybe_float(row.get("identity", "")) for row in official]
    official_identity_values = [v for v in official_identity_values if v is not None]
    pnc_red = [name for name, record in per.items() if str(record.get("tnp_PNC_flag_all11", "")).lower() == "red"]

    def bullet(metric: str, label: str | None = None) -> str:
        row = m[metric]
        name = label or metric
        return f"- {name}: {range_text(row)}"

    lines: list[str] = []
    lines.append("# PVRIG 11 阳性 VHH 的 QC 指标范围与筛选门控稳健性")
    lines.append("")
    lines.append(f"Updated: {date.today().isoformat()}")
    lines.append("")
    lines.append("## 结论先说")
    lines.append("")
    lines.append("有范围，但不能把所有范围都变成 hard gate。现在证据支持把筛选标准分成三层：")
    lines.append("")
    lines.append("1. **稳定 hard gate**：输入合规、标准氨基酸、IMGT/Kabat/ANARCI 编号完整、heavy variable domain、完整 FR/CDR、阳性 CDR 泄漏排除。")
    lines.append("2. **开发性 warn/ranking**：FR2/VHH-like、AbNatiV、Sapiens、人源化负担、pI/charge/GRAVY、TNP、Cys/糖基化/脱酰胺/异构化/疏水 run。")
    lines.append("3. **阻断生物学 gate**：不能由这些序列 QC 指标替代，仍必须走 DeepNano binder 预筛 + 结构预测 + PVRIG/PVRL2 competition docking/occlusion + 多 baseline consensus。")
    lines.append("")
    lines.append("最重要的校准发现是：11 条已知 PVRIG blocker 中，6/11 被 L2 判为 `REJECT_NOT_VHH_LIKE` 或 poor single-domain suitability，2/11 在 all-11 TNP 中出现 PNC red。因此 FR2/VHH-like 或 TNP 单项红旗不能作为“没有阻断作用”的 hard fail，只能作为提交风险/可开发性风险。")
    lines.append("")
    lines.append("## 输入与复跑证据")
    lines.append("")
    lines.append(f"- 阳性 FASTA：`{(DEFAULT_BASE / 'pvrig_11_success_positives.fasta').as_posix()}`，11 条。")
    lines.append(f"- node1 QC 输出：`{qc_dir.as_posix()}`。")
    lines.append("- node1 主命令：`/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc ... --local-positive-cdr-csv ... --top-n 20 --reserve-n 10`。")
    lines.append("- all-11 TNP 补跑：安全 header FASTA `pvrig_11_success_positives_tnp_safe.fasta`，输出 `tnp_safe_all11/TNP_Results_Multientry.json`。")
    lines.append(f"- 机器可读范围表：`{metric_csv.as_posix()}`。")
    lines.append(f"- 每条阳性明细：`{per_seq_csv.as_posix()}`。")
    lines.append("")
    lines.append("## 阳性集核心范围")
    lines.append("")
    for metric, label in [
        ("length", "VHH length"),
        ("imgt_cdr1_len", "IMGT CDR1 length"),
        ("imgt_cdr2_len", "IMGT CDR2 length"),
        ("imgt_cdr3_len", "IMGT CDR3 length"),
        ("fr2_hallmark_score", "FR2 hallmark score"),
        ("abnativ_vhh_score", "AbNatiV VHH score"),
        ("abnativ_fr_vhh_score", "AbNatiV FR-VHH score"),
        ("sapiens_mean_self_probability", "Sapiens mean self probability"),
        ("sapiens_num_suggested_mutations", "Sapiens suggested mutations"),
        ("pI", "pI"),
        ("charge_pH7_4", "net charge pH 7.4"),
        ("gravy", "GRAVY"),
        ("eval_instability_index", "instability index"),
        ("cys_count", "Cys count"),
        ("deamidation_NG_NS_NT_count", "deamidation NG/NS/NT count"),
        ("isomerization_DG_DS_DD_DT_count", "isomerization DG/DS/DD/DT count"),
        ("hydrophobic_5_count", "5-mer hydrophobic run count"),
        ("tnp_total_cdr_length", "TNP total CDR length"),
        ("tnp_cdr3_length", "TNP CDR3 length"),
        ("tnp_cdr3_compactness", "TNP CDR3 compactness"),
        ("tnp_PSH_all11", "TNP PSH"),
        ("tnp_PPC_all11", "TNP PPC"),
        ("tnp_PNC_all11", "TNP PNC"),
    ]:
        lines.append(bullet(metric, label))
    lines.append("")
    lines.append("## 门控稳健性复核")
    lines.append("")
    lines.append("### 可以稳定 hard gate")
    lines.append("")
    lines.append(f"- L1 编号完整性：{range_text(m['L1_numbering_integrity'])}。11/11 阳性都能编号，因此新候选无法编号、无法识别重链 variable domain、FR/CDR 不完整时可以 hard fail。")
    lines.append(f"- CDR 泄漏排除：`identity_threshold={config.get('identity_threshold', '')}`，`safe_identity_threshold={config.get('safe_identity_threshold', '')}`；`pass_similarity_filter` 为 {range_text(m['pass_similarity_filter'])}；阳性 `max_CDR_identity_to_positive` 为 {range_text(m['max_CDR_identity_to_positive'])}。新候选任一 CDR 对阳性参照 identity >=0.80 应 hard fail，0.75-0.80 应边界预警。")
    if official_identity_values:
        lines.append(f"- 官方 validator 失败原因：{len(official)} 条，全为 {dict(official_reason_counts)}；CDR 分布 {dict(official_cdr_counts)}；identity 范围 {fmt(min(official_identity_values))}-{fmt(max(official_identity_values))}。这证明阳性/近阳性会被泄漏门控稳定抓住。")
    lines.append("- 标准 20 AA、单条 VHH、长度粗范围仍可 hard gate；但不要把本批阳性的 120-127 aa 当唯一硬阈值，建议继续保留工具里的宽范围 95-160 aa，并把 105/110-145 aa 或 120-127 aa 附近作为偏好区间。")
    lines.append("")
    lines.append("### 只能 warn/ranking，不能当 blocker hard fail")
    lines.append("")
    lines.append(f"- VHH-like/FR2：L2 结果为 {range_text(m['L2_vhh_features'])}，single-domain suitability 为 {range_text(m['single_domain_suitability'])}，FR2 hallmark score 为 {range_text(m['fr2_hallmark_score'])}。已知阳性里有大量 L2 fail/poor，因此它只能提示单域性、表达和聚集风险。")
    lines.append(f"- AbNatiV：VHH score 为 {range_text(m['abnativ_vhh_score'])}，FR-VHH score 为 {range_text(m['abnativ_fr_vhh_score'])}；2/11 缺值。现有 <0.55 fail、0.55-0.70 warn 的工具阈值可用于自然性风险，但缺值或偏低不能直接判定无阻断。")
    lines.append(f"- Sapiens：mean self probability 为 {range_text(m['sapiens_mean_self_probability'])}，建议突变数为 {range_text(m['sapiens_num_suggested_mutations'])}。它评估人源化负担，不评估 PVRIG/PVRL2 阻断。")
    lines.append(f"- 理化性质：pI 为 {range_text(m['pI'])}，charge 为 {range_text(m['charge_pH7_4'])}，GRAVY 为 {range_text(m['gravy'])}。这些可用于表达/纯化/非特异风险排序，但 PVRIG 阳性允许较宽范围。")
    lines.append(f"- Cys 和责任位点：Cys count 为 {range_text(m['cys_count'])}，N-glyc motif 为 {range_text(m['nglyc_motif_count'])}，deamidation 为 {range_text(m['deamidation_NG_NS_NT_count'])}，isomerization 为 {range_text(m['isomerization_DG_DS_DD_DT_count'])}，hydrophobic 5-run 为 {range_text(m['hydrophobic_5_count'])}。非经典 Cys、异构化 motif、疏水 run 在阳性里也存在，所以必须位置/结构复核。")
    lines.append(f"- TNP：L/L3/C/PSH/PPC flags 全绿，PNC flags 为 {range_text(m['tnp_PNC_flag_all11'])}；PNC red 阳性为 {', '.join(pnc_red) if pnc_red else 'none'}。PNC red 是开发性风险，不是阻断否决。")
    lines.append("")
    lines.append("### 本次 QC 没覆盖或不能替代的指标")
    lines.append("")
    lines.append(f"- `structure_tools` 配置为 `{config.get('structure_tools', '')}`，L4 结果为 {range_text(m['L4_structure_stability'])}；IgFold/NanoNet/NanoBodyBuilder2 coverage、FR RMSD、CDR3 anchor distance 在本次 QC 中为空。")
    lines.append("- `blocker_class`、PVRIG interface contact score、PVRL2 competition score 在本次 QC 中未自动运行；若 TSV 中出现 50.00，那是中性占位，不是 docking 证据。")
    lines.append("- DeepNano 只能作为 sequence-only / prompt-site binder 预筛；它不判断是否阻断 PVRIG-PVRL2。")
    lines.append("- 实验 Kd/IC50/cell assay 不在本 QC 输出中；只能从专利/文献表单独追溯。")
    lines.append("")
    lines.append("## 推荐的批处理筛选标准")
    lines.append("")
    lines.append("1. **先硬门控**：标准 20 AA、单条序列、长度宽范围、ANARCI/AbNumber 编号成功、完整 FR/CDR、heavy chain、CDR 泄漏排除。")
    lines.append("2. **再 binder/阻断门控**：DeepNano 只做 binder 预筛；真正 blocker 必须导入结构预测 + 8X6B/9E6Y 或等价 PVRL2 competition docking/occlusion summary。")
    lines.append("3. **再可开发性分层**：FR2/VHH-like、AbNatiV、Sapiens、TNP、pI/charge/GRAVY、Cys/N-glyc/疏水 run 进入 warn/ranking；只有多项严重异常叠加或位于 CDR/暴露区域时才人工 hard fail。")
    lines.append("4. **最后组合多样性**：team diversity/cluster limit 只在候选已经过硬门控后用于 top-N 组合，不用于判断单条是否 blocker。")
    lines.append("")
    lines.append("## 稳健性结论")
    lines.append("")
    lines.append("- 对批处理来说已经足够稳健的部分：编号完整性、阳性泄漏排除、基础序列合规、粗长度范围、机器可读汇总。")
    lines.append("- 需要保持柔性的部分：VHH-like/FR2、AbNatiV、TNP、Sapiens、理化和责任位点。阳性结果本身证明这些不能单独 hard fail blocker。")
    lines.append("- 仍需外部流程提供证据的部分：结构稳定性交叉验证、复合物 docking、PVRIG/PVRL2 阻断几何、实验 Kd/IC50。")
    lines.append("- 因为当前阳性数只有 11 条，阳性范围应作为校准 envelope 和异常检测，而不是窄硬阈值；真正 hard gate 必须只放在能被阳性集和工具目标共同支持的项目上。")
    lines.append("")
    lines.append("## 工具缺口记录")
    lines.append("")
    lines.append("- all-11 TNP 数值已补齐，但 TNP 在 `--web`/单条后处理日志里仍出现 `Failed to process output PDB` 的非致命错误；本报告采用 `TNP_Results_Multientry.json` 的数值和 flag，不把空的单条 liability JSON 当完整结构 liability 证据。")
    lines.append("- `vhh-competition-qc` 当前不会自动跑新候选 HADDOCK/blocking；必须先单独跑复合物流程，再把 docking summary 导入 QC。")
    lines.append("")
    lines.append("## Reference counts")
    lines.append("")
    lines.append(f"- official positive CDRs: {refs.get('official_positive_cdrs', '')}")
    lines.append(f"- local positive CDRs: {refs.get('local_positive_cdrs', '')}")
    lines.append(f"- portfolio count: {details.get('portfolio_count', len(per)) if isinstance(details, dict) else len(per)}")
    lines.append(f"- TNP all-11 records: {len(tnp)}")
    lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qc-dir", type=Path, default=DEFAULT_QC)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_BASE)
    args = parser.parse_args()

    per, aux = load_inputs(args.qc_dir)
    rows = make_metric_rows(per, aux)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metric_csv = args.out_dir / "pvrig_positive_qc_metric_ranges.csv"
    per_seq_csv = args.out_dir / "pvrig_positive_qc_per_sequence_metrics.csv"
    report = args.out_dir / "PVRIG_POSITIVE_QC_METRIC_RANGES.md"
    write_metric_csv(rows, metric_csv)
    write_per_sequence(per, per_seq_csv)
    write_report(report, rows, per, aux, args.qc_dir, metric_csv, per_seq_csv)
    print(f"wrote {metric_csv}")
    print(f"wrote {per_seq_csv}")
    print(f"wrote {report}")


if __name__ == "__main__":
    main()
