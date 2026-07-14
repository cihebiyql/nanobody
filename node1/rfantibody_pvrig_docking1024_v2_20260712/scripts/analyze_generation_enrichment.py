#!/usr/bin/env python3
"""Analyze which RFantibody design regions enrich docking-geometry success."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if not total:
        return 0.0, 0.0
    rate = successes / total
    denominator = 1.0 + z * z / total
    center = (rate + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt(rate * (1.0 - rate) / total + z * z / (4.0 * total * total)) / denominator
    return center - half, center + half


def pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def aggregate(group_type: str, group_key: str, rows: list[dict[str, Any]], global_rates: dict[str, float]) -> list[dict[str, Any]]:
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[group_key])].append(row)
    output = []
    for value, members in groups.items():
        n = len(members)
        counts = {
            "any_consensus_a": sum(row["a_count"] >= 1 for row in members),
            "stable_consensus_a": sum(row["a_count"] >= 2 for row in members),
            "strict_good": sum(row["a_count"] >= 1 and row["best_haddock_score"] <= -80 for row in members),
            "stable_strict_good": sum(row["a_count"] >= 2 and row["best_haddock_score"] <= -80 for row in members),
            "any_9e6y_a": sum(row["a9_pose_count"] >= 1 for row in members),
            "best_haddock_le_m80": sum(row["best_haddock_score"] <= -80 for row in members),
            "best_haddock_le_m90": sum(row["best_haddock_score"] <= -90 for row in members),
        }
        any_low, any_high = wilson(counts["any_consensus_a"], n)
        strict_low, strict_high = wilson(counts["strict_good"], n)
        output.append(
            {
                "group_type": group_type,
                "group_value": value,
                "n": n,
                **{f"{key}_count": count for key, count in counts.items()},
                **{f"{key}_rate": count / n for key, count in counts.items()},
                "any_consensus_a_wilson95_low": any_low,
                "any_consensus_a_wilson95_high": any_high,
                "strict_good_wilson95_low": strict_low,
                "strict_good_wilson95_high": strict_high,
                "any_consensus_a_lift": (counts["any_consensus_a"] / n) / global_rates["any_consensus_a"],
                "strict_good_lift": (counts["strict_good"] / n) / global_rates["strict_good"],
                "consensus_a_pose_count": sum(row["a_count"] for row in members),
                "9e6y_a_pose_count": sum(row["a9_pose_count"] for row in members),
                "median_best_haddock": statistics.median(row["best_haddock_score"] for row in members),
                "mean_best_haddock": statistics.fmean(row["best_haddock_score"] for row in members),
            }
        )
    return sorted(
        output,
        key=lambda row: (
            -row["any_consensus_a_rate"],
            -row["stable_consensus_a_rate"],
            -row["strict_good_rate"],
            row["group_value"],
        ),
    )


def subset_summary(name: str, members: list[dict[str, Any]], global_rates: dict[str, float]) -> dict[str, Any]:
    n = len(members)
    any_a = sum(row["a_count"] >= 1 for row in members)
    stable_a = sum(row["a_count"] >= 2 for row in members)
    strict = sum(row["a_count"] >= 1 and row["best_haddock_score"] <= -80 for row in members)
    stable_strict = sum(row["a_count"] >= 2 and row["best_haddock_score"] <= -80 for row in members)
    return {
        "name": name,
        "n": n,
        "any_consensus_a_count": any_a,
        "any_consensus_a_rate": any_a / n,
        "stable_consensus_a_count": stable_a,
        "stable_consensus_a_rate": stable_a / n,
        "strict_good_count": strict,
        "strict_good_rate": strict / n,
        "stable_strict_good_count": stable_strict,
        "stable_strict_good_rate": stable_strict / n,
        "any_consensus_a_lift": (any_a / n) / global_rates["any_consensus_a"],
        "strict_good_lift": (strict / n) / global_rates["strict_good"],
        "median_best_haddock": statistics.median(row["best_haddock_score"] for row in members),
    }


def build(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = read_tsv(root / "data/candidates.tsv")
    postprocess = {row["candidate_id"]: row for row in read_tsv(root / "data/baseline_postprocess.tsv")}
    baseline = read_tsv(root / "data/docking_pose_baseline_metrics.tsv")
    training_candidates = {
        row["candidate_id"]: row for row in read_tsv(root / "data/training_dataset/candidates.tsv")
    }

    baseline_by_pose: defaultdict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    a9_by_candidate: Counter[str] = Counter()
    for row in baseline:
        baseline_by_pose[(row["candidate_id"], row["model"])][row["baseline_id"]] = row
        if row["baseline_id"] == "9E6Y" and row["blocker_class"] == "BLOCKER_LIKE_A":
            a9_by_candidate[row["candidate_id"]] += 1

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        post = postprocess[candidate_id]
        rows.append(
            {
                **candidate,
                "near_cdr3_family": training_candidates[candidate_id]["sequence_group_id"],
                "near_cdr3_family_size": int(training_candidates[candidate_id]["near_sequence_family_size"]),
                "a_count": int(post["consensus_blocker_like_a_count"]),
                "single_count": int(post["single_baseline_recheck_count"]),
                "a9_pose_count": a9_by_candidate[candidate_id],
                "best_haddock_score": float(post["best_haddock_score"]),
            }
        )

    global_rates = {
        "any_consensus_a": sum(row["a_count"] >= 1 for row in rows) / len(rows),
        "strict_good": sum(row["a_count"] >= 1 and row["best_haddock_score"] <= -80 for row in rows) / len(rows),
    }
    group_specs = [
        ("patch", "patch_id"),
        ("scaffold", "scaffold_id"),
        ("h3_regime", "h3_regime"),
        ("cdr3_length", "cdr3_length"),
        ("arm", "arm_id"),
        ("backbone_group", "backbone_group_id"),
        ("near_cdr3_family", "near_cdr3_family"),
    ]
    groups = [item for group_type, key in group_specs for item in aggregate(group_type, key, rows, global_rates)]

    all_rows = subset_summary("all_1024", rows, global_rates)
    long_rows = [row for row in rows if row["h3_regime"] == "L"]
    p234_long = [
        row
        for row in rows
        if row["h3_regime"] == "L" and row["patch_id"] in {"P2_bridge_N_C", "P3_charge_aromatic", "P4_cterm_robust"}
    ]
    p234_long_13 = [row for row in p234_long if row["cdr3_length"] == "13"]
    p234_long_11_13 = [row for row in p234_long if row["cdr3_length"] in {"11", "13"}]
    subsets = [
        all_rows,
        subset_summary("long_h3", long_rows, global_rates),
        subset_summary("p2_p3_p4_long_h3", p234_long, global_rates),
        subset_summary("p2_p3_p4_long_h3_cdr3_13", p234_long_13, global_rates),
        subset_summary("p2_p3_p4_long_h3_cdr3_11_or_13", p234_long_11_13, global_rates),
    ]

    failure_gate_counts = Counter()
    failure_combinations = Counter()
    a8_to_9_non_a = 0
    for pose_rows in baseline_by_pose.values():
        row8 = pose_rows["8X6B"]
        row9 = pose_rows["9E6Y"]
        if row8["blocker_class"] != "BLOCKER_LIKE_A" or row9["blocker_class"] == "BLOCKER_LIKE_A":
            continue
        a8_to_9_non_a += 1
        failed = []
        for gate in ["pass_hotspot", "pass_total_occlusion", "pass_cdr3_occlusion", "pass_cdr3_fraction"]:
            if row9[gate] == "no":
                failure_gate_counts[gate] += 1
                failed.append(gate)
        failure_combinations["+".join(failed) or "none"] += 1

    budget = [
        {
            "lane": "EXPLOIT_P3_STABLE",
            "fraction": 0.25,
            "example_raw_count_8192": 2048,
            "patches": "P3_charge_aromatic",
            "scaffolds": "ekg;qkg;qrg",
            "design_loops": "H1:7,H2:6,H3:13",
            "backbone_strategy": "half winner-backbone resampling; half new RFdiffusion backbones",
            "proteinmpnn": "16-32 sequences/backbone; temperatures 0.1,0.2,0.3",
            "purpose": "maximize stable A_count and favorable HADDOCK score",
        },
        {
            "lane": "EXPLOIT_P2_YIELD",
            "fraction": 0.25,
            "example_raw_count_8192": 2048,
            "patches": "P2_bridge_N_C",
            "scaffolds": "qrg;ekg;qkg",
            "design_loops": "H1:7,H2:6,H3:13",
            "backbone_strategy": "prioritize P2_qrg_L_bb003/bb004 and P2_qkg_L_bb003/bb006",
            "proteinmpnn": "16-32 sequences/backbone; temperatures 0.1,0.2,0.3",
            "purpose": "maximize number of candidates with at least one dual-reference A pose",
        },
        {
            "lane": "EXPLOIT_P4_ROBUST",
            "fraction": 0.20,
            "example_raw_count_8192": 1638,
            "patches": "P4_cterm_robust",
            "scaffolds": "ekg;qkg;qrg",
            "design_loops": "H1:7,H2:6,H3:13",
            "backbone_strategy": "winner-backbone resampling plus new backbone search",
            "proteinmpnn": "16-32 sequences/backbone; temperatures 0.1,0.2,0.3",
            "purpose": "retain a second robust high-yield patch family",
        },
        {
            "lane": "NEIGHBOR_LENGTHS",
            "fraction": 0.10,
            "example_raw_count_8192": 819,
            "patches": "P2_bridge_N_C;P3_charge_aromatic;P4_cterm_robust",
            "scaffolds": "ekg;qrg;qkg",
            "design_loops": "H1:7,H2:6,H3:11|14|15",
            "backbone_strategy": "new RFdiffusion backbones only",
            "proteinmpnn": "8-16 sequences/backbone; temperatures 0.2,0.3",
            "purpose": "avoid overfitting all capacity to length 13",
        },
        {
            "lane": "9E6Y_CONFORMER_SEARCH",
            "fraction": 0.10,
            "example_raw_count_8192": 819,
            "patches": "P2/P3/P4 mapped consensus hotspots",
            "scaffolds": "ekg;qrg;qkg",
            "design_loops": "H1:7,H2:6,H3:13",
            "backbone_strategy": "generate against aligned 9E6Y PVRIG conformer and rescore in both references",
            "proteinmpnn": "8-16 sequences/backbone; temperatures 0.2,0.3",
            "purpose": "directly attack the 9E6Y hotspot-overlap bottleneck",
        },
        {
            "lane": "NOVELTY_AND_BIAS_AUDIT",
            "fraction": 0.10,
            "example_raw_count_8192": 820,
            "patches": "P1;P5;P6;new cross-lobe hotspot combinations",
            "scaffolds": "balanced",
            "design_loops": "H1:7,H2:6,H3:11-15",
            "backbone_strategy": "new backbones with family caps",
            "proteinmpnn": "8 sequences/backbone; temperatures 0.2,0.3",
            "purpose": "maintain exploration and detect surrogate or restraint shortcuts",
        },
    ]

    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": "maximize computational dual-reference docking-geometry successes, not experimental outcomes",
        "success_definitions": {
            "any_consensus_a": "candidate has at least one of four poses classified CONSENSUS_BLOCKER_LIKE_A",
            "stable_consensus_a": "candidate has at least two of four poses classified CONSENSUS_BLOCKER_LIKE_A",
            "strict_good": "any_consensus_a and candidate best HADDOCK score <= -80",
            "stable_strict_good": "stable_consensus_a and candidate best HADDOCK score <= -80",
        },
        "global": all_rows,
        "subsets": subsets,
        "9e6y_bottleneck": {
            "8x6b_a_to_9e6y_non_a_pose_count": a8_to_9_non_a,
            "failed_gate_counts": dict(failure_gate_counts),
            "failure_combinations": dict(failure_combinations.most_common()),
        },
        "recommended_default_raw_pool": 8192,
        "recommended_docking_batch": 1024,
        "retrospective_projection_for_1024_docked": {
            "if_p2_p3_p4_long_h3_cdr3_13_rate_repeats_any_a": round(1024 * subsets[3]["any_consensus_a_rate"]),
            "if_rate_repeats_strict_good": round(1024 * subsets[3]["strict_good_rate"]),
            "warning": "retrospective extrapolation only; prospective yield may regress",
        },
        "mandatory_metric_repairs_before_optimization": [
            "exclude HETATM waters and crystallization additives from PVRL2 protein occlusion/clash calculations",
            "keep hotspot overlap, total occlusion, CDR3 occlusion, HADDOCK score, and diversity as separate fields",
            "validate any cheap pre-docking surrogate prospectively before using it as a hard gate",
        ],
    }
    return summary, groups, budget


def render_markdown(summary: dict[str, Any], groups: list[dict[str, Any]], budget: list[dict[str, Any]]) -> str:
    subsets = {row["name"]: row for row in summary["subsets"]}
    all_rows = subsets["all_1024"]
    enriched = subsets["p2_p3_p4_long_h3_cdr3_13"]
    group_map: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in groups:
        group_map[row["group_type"]].append(row)
    lines = [
        "# 如何增加尽可能多的 docking 更好序列",
        "",
        f"> 生成时间：`{summary['generated_at']}`",
        "",
        "本报告只讨论计算生成与 docking 富集，不讨论实验验证。",
        "",
        "## 1. 直接结论",
        "",
        "不要再按 36 个 arm 平均分配。下一轮应把主体预算集中到：",
        "",
        "```text",
        "P2_bridge_N_C / P3_charge_aromatic / P4_cterm_robust",
        "+ long H3",
        "+ fixed CDR3 length 13",
        "+ ekg/qrg 为主，qkg 保留稳定命中支线",
        "```",
        "",
        f"全量 1,024 条中，至少一个双参考 A 的比例为 `{pct(all_rows['any_consensus_a_rate'])}`，"
        f"同时满足 A 且 best HADDOCK≤-80 的严格比例为 `{pct(all_rows['strict_good_rate'])}`。",
        f"在 `P2/P3/P4 + long H3 + CDR3=13` 的 100 条回看子集中，这两个比例分别达到 "
        f"`{pct(enriched['any_consensus_a_rate'])}` 和 `{pct(enriched['strict_good_rate'])}`，"
        f"约为全量的 `{enriched['any_consensus_a_lift']:.1f}x` 和 `{enriched['strict_good_lift']:.1f}x`。",
        "这是当前最明确的计算扩增方向，但它是 retrospective enrichment，不是未来批次的保证。",
        "",
        "## 2. 先定义什么叫 docking 更好",
        "",
        "建议不要只按 HADDOCK score，而采用四级计算目标：",
        "",
        "1. 主目标：`A_count >= 1`，至少一个 top4 pose 为双参考 `CONSENSUS_BLOCKER_LIKE_A`。",
        "2. 稳定目标：`A_count >= 2`，避免单 pose 偶然命中。",
        "3. 严格目标：`A_count >= 1 && best_HADDOCK <= -80`。",
        "4. 强严格目标：`A_count >= 2 && best_HADDOCK <= -80`。",
        "",
        "HADDOCK 分数只在同一几何等级内排序；不能让低分但 9E6Y 热点不通过的序列排到双参考 A 前面。",
        "",
        "## 3. 现有数据中的富集规律",
        "",
        "### H3 长度",
        "",
        "| 区域 | n | 任一双参考 A | 稳定 A>=2 | 严格 good |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ["all_1024", "long_h3", "p2_p3_p4_long_h3", "p2_p3_p4_long_h3_cdr3_13"]:
        row = subsets[name]
        lines.append(
            f"| `{name}` | {row['n']} | {row['any_consensus_a_count']} ({pct(row['any_consensus_a_rate'])}) | "
            f"{row['stable_consensus_a_count']} ({pct(row['stable_consensus_a_rate'])}) | "
            f"{row['strict_good_count']} ({pct(row['strict_good_rate'])}) |"
        )
    lines.extend(
        [
            "",
            "长 H3 的任一 A 命中率为 8.4%，短 H3 只有 0.6%。CDR3 长度 5、7、8 在本批合计没有产生任何双参考 A；CDR3=13 最强。",
            "",
            "### patch",
            "",
            "| patch | n | 任一 A | 稳定 A | 严格 good | HADDOCK≤-90 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in group_map["patch"]:
        lines.append(
            f"| `{row['group_value']}` | {row['n']} | {row['any_consensus_a_count']} ({pct(row['any_consensus_a_rate'])}) | "
            f"{row['stable_consensus_a_count']} ({pct(row['stable_consensus_a_rate'])}) | "
            f"{row['strict_good_count']} ({pct(row['strict_good_rate'])}) | "
            f"{row['best_haddock_le_m90_count']} ({pct(row['best_haddock_le_m90_rate'])}) |"
        )
    lines.extend(
        [
            "",
            "P6 虽然有不少很负的 HADDOCK 分数，但几乎不产生双参考 A，说明继续优化单一分数会浪费算力。",
            "",
            "### 最优 arm 和 backbone seed",
            "",
            "任一 A 命中率最高的主 arm 是 `P2_qrg_L` (6/29)、`P4_ekg_L` (5/29)、"
            "`P3_ekg_L`、`P3_qkg_L`、`P3_qrg_L` (各 4/29)。",
            "局部扩增优先使用 `P3_ekg_L_bb003`、`P2_qrg_L_bb003/bb004`、`P4_qkg_L_bb003`、"
            "`P2_qkg_L_bb006` 和 `P5_qrg_L_bb004`。",
            "",
            "## 4. 真正的瓶颈是 9E6Y 热点覆盖",
            "",
            f"共有 `{summary['9e6y_bottleneck']['8x6b_a_to_9e6y_non_a_pose_count']}` 个 pose 在 8X6B 为 A、但在 9E6Y 不是 A。",
            f"其中 `{summary['9e6y_bottleneck']['failed_gate_counts'].get('pass_hotspot', 0)}` 个未通过 9E6Y hotspot gate；"
            f"`{summary['9e6y_bottleneck']['failure_combinations'].get('pass_hotspot', 0)}` 个只差 hotspot，其他三个阈值均已通过。",
            "因此下一轮不应主要继续增加总遮挡或把 HADDOCK 再压低，而应增加同一 pose 在 9E6Y 构象下覆盖的 PVRIG 共识热点数量。",
            "",
            "具体做法：",
            "",
            "- 保留 8X6B-guided 主标签，增加 9E6Y PVRIG conformer 的 RFdiffusion 生成支线。",
            "- 用 P2/P3/P4 的跨 N/C 端热点组合，而不是只压一个局部 patch。",
            "- acquisition score 中直接使用 `min(hotspot_8X6B, hotspot_9E6Y)` 和 9E6Y hotspot margin。",
            "- 对进入 HADDOCK 的候选要求 cheap generated-pose proxy 在 9E6Y 上至少接近阈值，再保留一部分 uncertainty 候选防止误杀。",
            "",
            "## 5. 最快增加数量的方法：先扩成功 backbone 的序列邻域",
            "",
            "当前每个 RFdiffusion backbone 只生成 4 条 ProteinMPNN 序列。要快速增加数量，最便宜的做法不是全部重新跑 RFdiffusion，而是：",
            "",
            "1. 选 12-20 个成功 backbone；",
            "2. 每个 backbone 生成 16-32 条序列；",
            "3. 使用 temperature 0.1/0.2/0.3 三档；",
            "4. 保留 exact-unique，并限制单个 near-CDR3 family 的进入 docking 数；",
            "5. 然后再补充新 RFdiffusion backbone，避免全部候选成为同一姿势的近重复。",
            "",
            "`H1:7,H2:6,H3:13` 是 RFantibody 支持的固定长度语法，可以直接用于下一轮 arm。",
            "",
            "## 6. 推荐的 8,192 条 raw pool 预算",
            "",
            "| lane | 比例 | raw 数 | patch | scaffold | loop | 目的 |",
            "|---|---:|---:|---|---|---|---|",
        ]
    )
    for row in budget:
        lines.append(
            f"| `{row['lane']}` | {pct(row['fraction'])} | {row['example_raw_count_8192']} | "
            f"{row['patches']} | {row['scaffolds']} | `{row['design_loops']}` | {row['purpose']} |"
        )
    projection = summary["retrospective_projection_for_1024_docked"]
    lines.extend(
        [
            "",
            "推荐漏斗：",
            "",
            "```text",
            "8,192 raw RFantibody/ProteinMPNN sequences",
            "  -> exact unique + sequence QC",
            "  -> generated-pose 双参考快速几何 + surrogate 预筛",
            "  -> 1,536 NanoBodyBuilder2",
            "  -> 1,024 HADDOCK3",
            "  -> top4 pose 的 8X6B/9E6Y 全量后处理",
            "```",
            "",
            f"如果 100 条富集子集的历史比例完全复现，1,024 条 docking 可得到约 "
            f"`{projection['if_p2_p3_p4_long_h3_cdr3_13_rate_repeats_any_a']}` 条任一 A、"
            f"`{projection['if_rate_repeats_strict_good']}` 条严格 good。这个数字只能作为容量规划上限，"
            "实际 prospective yield 应按回归到均值后的 100-170 条严格 good 规划。",
            "",
            "## 7. 主动学习循环",
            "",
            "每完成一批 512-1,024 条 docking，就用新标签重训四个独立头：",
            "",
            "- `P(A_count>=1)`；",
            "- `E[A_count]`；",
            "- `9E6Y hotspot margin`；",
            "- `best HADDOCK score`。",
            "",
            "进入下一批的比例建议为 70% exploitation、20% uncertainty、10% novelty。"
            "不要把四个头压成一个未经验证的总分；先过双参考几何硬门，再用 HADDOCK 排序。",
            "",
            "计算停止条件可以设为：连续两批严格 good 命中率低于 5%，或每新增一条严格 good 需要超过 30 条完整 docking。",
            "",
            "## 8. 优化前必须修正的评分问题",
            "",
            "当前两个 occlusion scorer 都读取 `HETATM`。9E6Y 的 PVRL2 chain 中存在 HOH/EDO，"
            "因此总遮挡、clash 和 CDR3 fraction 可能包含结晶水或添加剂。下一轮训练 surrogate 或优化 geometry margin 前必须：",
            "",
            "- PVRIG/PVRL2 蛋白接触只保留标准氨基酸 `ATOM`；",
            "- HOH、EDO 和其他 ligand 单独记录，不进入 protein occlusion；",
            "- 重新计算旧 1,024 条的 clean geometry label，再开始 active learning。",
            "",
            "否则大量生成会逐渐学会利用评分器漏洞，而不是产生真正更好的蛋白 docking 几何。",
            "",
            "## 9. 不应继续做的事情",
            "",
            "- 不再平均扩全部 36 个 arm。",
            "- 不把 CDR3 长度 5/7/8 作为主线。",
            "- 不因 P6 的 HADDOCK 很负就增加 P6 预算。",
            "- 不全量跑三 seed RF2；它与当前 Tier 1 没有交集，可把 GPU 预算转给更多生成和 NBB2。",
            "- 不允许一个 near-CDR3 family 吃掉全部 docking 名额。",
            "- 不在修复 HETATM 计分前训练最终 surrogate。",
            "",
            "## 10. 输出",
            "",
            "- `reports/docking_generation_enrichment_summary.json`：机器可读摘要。",
            "- `reports/docking_generation_group_enrichment.tsv`：全部 group 富集统计。",
            "- `reports/proposed_generation_budget_v3.tsv`：下一轮预算表。",
            "- `scripts/analyze_generation_enrichment.py`：可复现分析脚本。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    summary, groups, budget = build(root)
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "docking_generation_enrichment_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    group_fields = list(groups[0])
    write_tsv(reports / "docking_generation_group_enrichment.tsv", groups, group_fields)
    budget_fields = list(budget[0])
    write_tsv(reports / "proposed_generation_budget_v3.tsv", budget, budget_fields)
    (reports / "DOCKING_ENRICHMENT_GENERATION_STRATEGY_ZH.md").write_text(
        render_markdown(summary, groups, budget), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "candidate_count": summary["global"]["n"],
                "enriched_subset": summary["subsets"][3],
                "report": str(reports / "DOCKING_ENRICHMENT_GENERATION_STRATEGY_ZH.md"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
