#!/usr/bin/env python3
"""Summarize HADDOCK scores and PVRIG-PVRL2 blocker-geometry evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


THRESHOLDS = {
    "hotspot_overlap_count": 14.0,
    "total_vhh_pvrl2_residue_pair_occlusion": 500.0,
    "cdr3_pvrl2_residue_pair_occlusion": 100.0,
    "cdr3_occlusion_fraction": 0.15,
}

CONSENSUS_PRIORITY = {
    "EVIDENCE_INFERENCE_ONLY_E": 0,
    "BLOCKER_PLAUSIBLE_B": 1,
    "SINGLE_BASELINE_BLOCKER_RECHECK": 2,
    "CONSENSUS_BLOCKER_LIKE_A": 3,
}

FORMAL_RF2_PASS = "FORMAL_MULTI_SEED_PASS_2OF3_WITH_STRICT_SUPPORT"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def f(value: Any) -> float:
    return float(value)


def quantile(values: Iterable[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires at least one value")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def describe(values: Iterable[float]) -> dict[str, float | int]:
    data = list(values)
    return {
        "n": len(data),
        "min": min(data),
        "p05": quantile(data, 0.05),
        "p25": quantile(data, 0.25),
        "median": quantile(data, 0.50),
        "p75": quantile(data, 0.75),
        "p95": quantile(data, 0.95),
        "max": max(data),
        "mean": statistics.fmean(data),
        "sd": statistics.pstdev(data),
    }


def tied_rank_auc(scores: list[float], labels: list[int]) -> float:
    ranked = sorted(zip(scores, labels), key=lambda item: item[0])
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return float("nan")
    positive_rank_sum = 0.0
    index = 0
    while index < len(ranked):
        end = index + 1
        while end < len(ranked) and ranked[end][0] == ranked[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        positive_rank_sum += average_rank * sum(label for _, label in ranked[index:end])
        index = end
    return (positive_rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pct(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def candidate_tier(row: dict[str, str]) -> str:
    if int(row["consensus_blocker_like_a_count"]):
        return "TIER_1_DUAL_REFERENCE_A"
    if int(row["single_baseline_recheck_count"]):
        return "TIER_2_SINGLE_REFERENCE_RECHECK"
    if int(row["blocker_plausible_count"]):
        return "TIER_3_PLAUSIBLE"
    return "TIER_4_EVIDENCE_ONLY"


def choose_diverse_panel(ranked_a: list[dict[str, Any]], size: int = 20) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    families: set[str] = set()
    backbones: set[str] = set()
    arm_counts: Counter[str] = Counter()

    def add(row: dict[str, Any]) -> None:
        selected.append(row)
        selected_ids.add(str(row["candidate_id"]))
        families.add(str(row["near_cdr3_family_id"]))
        backbones.add(str(row["backbone_group_id"]))
        arm_counts[str(row["arm_id"])] += 1

    for row in ranked_a:
        if len(selected) >= size:
            break
        if (
            row["near_cdr3_family_id"] not in families
            and row["backbone_group_id"] not in backbones
            and arm_counts[str(row["arm_id"])] < 2
        ):
            add(row)
    for row in ranked_a:
        if len(selected) >= size:
            break
        if row["candidate_id"] in selected_ids:
            continue
        if row["near_cdr3_family_id"] not in families and row["backbone_group_id"] not in backbones:
            add(row)
    for row in ranked_a:
        if len(selected) >= size:
            break
        if row["candidate_id"] in selected_ids:
            continue
        if row["near_cdr3_family_id"] not in families:
            add(row)
    return [{**row, "diverse_panel_rank": index} for index, row in enumerate(selected, start=1)]


def build_analysis(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    paths = {
        "candidates": root / "data/candidates.tsv",
        "training_candidates": root / "data/training_dataset/candidates.tsv",
        "features": root / "data/training_dataset/docking_pose_features.tsv",
        "baseline": root / "data/docking_pose_baseline_metrics.tsv",
        "consensus": root / "data/docking_pose_consensus.tsv",
        "postprocess": root / "data/baseline_postprocess.tsv",
        "candidate_summary": root / "data/training_dataset/candidate_summary.tsv",
        "rf2_gates": root / "data/rf2_candidate_gates.tsv",
        "final_audit": root / "reports/final_audit.json",
        "independent_validation": root / "reports/independent_final_validation.json",
    }
    candidates = {row["candidate_id"]: row for row in read_tsv(paths["candidates"])}
    training_candidates = {row["candidate_id"]: row for row in read_tsv(paths["training_candidates"])}
    features = read_tsv(paths["features"])
    baseline = read_tsv(paths["baseline"])
    consensus = read_tsv(paths["consensus"])
    postprocess = {row["candidate_id"]: row for row in read_tsv(paths["postprocess"])}
    candidate_summary = {row["candidate_id"]: row for row in read_tsv(paths["candidate_summary"])}
    rf2_gates = {row["candidate_id"]: row for row in read_tsv(paths["rf2_gates"])}

    feature_scores = [f(row["haddock_score"]) for row in features]
    feature_scores_by_candidate: defaultdict[str, list[float]] = defaultdict(list)
    for row in features:
        feature_scores_by_candidate[row["candidate_id"]].append(f(row["haddock_score"]))

    baseline_by_pose: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in baseline:
        baseline_by_pose[(row["candidate_id"], row["model"])].append(row)
    deduplicated_top4_scores = [f(rows[0]["haddock_score"]) for rows in baseline_by_pose.values()]
    candidate_best_scores = [min(values) for values in feature_scores_by_candidate.values()]

    baseline_classes_by_reference: dict[str, dict[str, int]] = {}
    for baseline_id in sorted({row["baseline_id"] for row in baseline}):
        baseline_classes_by_reference[baseline_id] = dict(
            sorted(Counter(row["blocker_class"] for row in baseline if row["baseline_id"] == baseline_id).items())
        )
    baseline_class_counts = Counter(row["blocker_class"] for row in baseline)
    baseline_candidates_with_any = {
        label: len({row["candidate_id"] for row in baseline if row["blocker_class"] == label})
        for label in sorted(baseline_class_counts)
    }

    consensus_class_counts = Counter(row["consensus_class"] for row in consensus)
    consensus_candidates_with_any = {
        label: len({row["candidate_id"] for row in consensus if row["consensus_class"] == label})
        for label in sorted(consensus_class_counts)
    }
    consensus_score_by_class = {
        label: describe(
            f(baseline_by_pose[(row["candidate_id"], row["model"])][0]["haddock_score"])
            for row in consensus
            if row["consensus_class"] == label
        )
        for label in sorted(consensus_class_counts)
    }
    baseline_score_by_class = {
        label: describe(f(row["haddock_score"]) for row in baseline if row["blocker_class"] == label)
        for label in sorted(baseline_class_counts)
    }

    contingency = Counter()
    for rows in baseline_by_pose.values():
        classes = {row["baseline_id"]: row["blocker_class"] for row in rows}
        contingency[f"8X6B={classes['8X6B']}|9E6Y={classes['9E6Y']}"] += 1

    candidate_tier_counts = Counter(candidate_tier(row) for row in postprocess.values())
    a_count_distribution = Counter(int(row["consensus_blocker_like_a_count"]) for row in postprocess.values())
    supported_count_distribution = Counter(
        int(row["consensus_blocker_like_a_count"]) + int(row["single_baseline_recheck_count"])
        for row in postprocess.values()
    )

    consensus_favorable_scores = [
        -f(baseline_by_pose[(row["candidate_id"], row["model"])][0]["haddock_score"])
        for row in consensus
    ]
    consensus_a_labels = [int(row["consensus_class"] == "CONSENSUS_BLOCKER_LIKE_A") for row in consensus]
    strong_geometry_labels = [
        int(row["consensus_class"] in {"CONSENSUS_BLOCKER_LIKE_A", "SINGLE_BASELINE_BLOCKER_RECHECK"})
        for row in consensus
    ]

    candidate_rows: list[dict[str, Any]] = []
    consensus_by_candidate: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in consensus:
        consensus_by_candidate[row["candidate_id"]].append(row)
    for candidate_id, candidate in candidates.items():
        post = postprocess[candidate_id]
        gate = rf2_gates[candidate_id]
        training_candidate = training_candidates[candidate_id]
        pose_rows = []
        for consensus_row in consensus_by_candidate[candidate_id]:
            metric_rows = baseline_by_pose[(candidate_id, consensus_row["model"])]
            weakest = {
                key: min(f(row[key]) for row in metric_rows)
                for key in THRESHOLDS
            }
            geometry_margin = min(
                f(row[key]) / threshold
                for row in metric_rows
                for key, threshold in THRESHOLDS.items()
            )
            pose_rows.append(
                {
                    "model": consensus_row["model"],
                    "consensus_class": consensus_row["consensus_class"],
                    "haddock_rank": int(consensus_row["best_haddock_rank"]),
                    "haddock_score": f(metric_rows[0]["haddock_score"]),
                    "weakest": weakest,
                    "geometry_margin": geometry_margin,
                }
            )
        representative = max(
            pose_rows,
            key=lambda row: (
                CONSENSUS_PRIORITY[row["consensus_class"]],
                row["geometry_margin"],
                -row["haddock_score"],
            ),
        )
        tier = candidate_tier(post)
        row = {
            "candidate_id": candidate_id,
            "sequence": candidate["sequence"],
            "sequence_length": int(candidate["sequence_length"]),
            "cdr1": candidate["cdr1"],
            "cdr2": candidate["cdr2"],
            "cdr3": candidate["cdr3"],
            "arm_id": candidate["arm_id"],
            "scaffold_id": candidate["scaffold_id"],
            "h3_regime": candidate["h3_regime"],
            "backbone_group_id": candidate["backbone_group_id"],
            "near_cdr3_family_id": training_candidate["sequence_group_id"],
            "near_cdr3_family_size": int(training_candidate["near_sequence_family_size"]),
            "candidate_tier": tier,
            "consensus_a_pose_count": int(post["consensus_blocker_like_a_count"]),
            "single_baseline_recheck_pose_count": int(post["single_baseline_recheck_count"]),
            "plausible_pose_count": int(post["blocker_plausible_count"]),
            "evidence_only_pose_count": int(post["evidence_only_count"]),
            "best_haddock_score": f(post["best_haddock_score"]),
            "representative_model": representative["model"],
            "representative_consensus_class": representative["consensus_class"],
            "representative_haddock_rank": representative["haddock_rank"],
            "representative_haddock_score": representative["haddock_score"],
            "weakest_hotspot_overlap": int(representative["weakest"]["hotspot_overlap_count"]),
            "weakest_total_occlusion": int(representative["weakest"]["total_vhh_pvrl2_residue_pair_occlusion"]),
            "weakest_cdr3_occlusion": int(representative["weakest"]["cdr3_pvrl2_residue_pair_occlusion"]),
            "weakest_cdr3_fraction": representative["weakest"]["cdr3_occlusion_fraction"],
            "representative_geometry_margin": representative["geometry_margin"],
            "rf2_formal_gate_status": gate["formal_multiseed_gate_status"],
            "rf2_best_interaction_pae": f(gate["best_interaction_pae"]),
            "rf2_best_pred_lddt": f(gate["best_pred_lddt"]),
            "rf2_recovered_seeds": gate["recovered_seeds"],
            "binder_axis_status": candidate_summary[candidate_id]["binder_axis_status"],
            "binder_label": candidate_summary[candidate_id]["binder_label"],
        }
        candidate_rows.append(row)

    tier_order = {
        "TIER_1_DUAL_REFERENCE_A": 0,
        "TIER_2_SINGLE_REFERENCE_RECHECK": 1,
        "TIER_3_PLAUSIBLE": 2,
        "TIER_4_EVIDENCE_ONLY": 3,
    }
    candidate_rows.sort(
        key=lambda row: (
            tier_order[row["candidate_tier"]],
            -row["consensus_a_pose_count"],
            -row["single_baseline_recheck_pose_count"],
            -row["representative_geometry_margin"],
            row["best_haddock_score"],
            row["candidate_id"],
        )
    )
    for index, row in enumerate(candidate_rows, start=1):
        row["geometry_rank"] = index

    ranked_a = [row for row in candidate_rows if row["consensus_a_pose_count"] > 0]
    diverse_panel = choose_diverse_panel(ranked_a, size=20)

    rf2_gate_counts = Counter(row["formal_multiseed_gate_status"] for row in rf2_gates.values())
    rf2_gate_counts_for_a = Counter(
        rf2_gates[row["candidate_id"]]["formal_multiseed_gate_status"] for row in ranked_a
    )
    rf2_pass_ids = {
        candidate_id
        for candidate_id, row in rf2_gates.items()
        if row["formal_multiseed_gate_status"] == FORMAL_RF2_PASS
    }
    a_ids = {row["candidate_id"] for row in ranked_a}

    invalid_bsa_rows = [row for row in features if f(row["buried_surface_area"]) <= -100000]
    energy_distributions = {}
    for field in [
        "haddock_score",
        "vdw_energy",
        "electrostatic_energy",
        "desolvation_energy",
        "air_energy",
        "buried_surface_area",
    ]:
        values = [f(row[field]) for row in features]
        if field == "buried_surface_area":
            values = [value for value in values if value > -100000]
        energy_distributions[field] = describe(values)

    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "scientific_boundary": (
            "Docking score and dual-reference occlusion are computational proxies; "
            "they are not experimental binding, Kd, competition blockade, or cellular-function proof."
        ),
        "source_hashes": {str(path.relative_to(root)): sha256(path) for path in paths.values()},
        "row_counts": {
            "candidates": len(candidates),
            "selected_pose_features": len(features),
            "baseline_rows": len(baseline),
            "deduplicated_top4_poses": len(baseline_by_pose),
            "consensus_rows": len(consensus),
        },
        "haddock_score_distributions": {
            "all_selected_poses": describe(feature_scores),
            "top4_deduplicated_poses": describe(deduplicated_top4_scores),
            "candidate_best": describe(candidate_best_scores),
        },
        "candidate_best_score_threshold_counts": {
            str(threshold): sum(score <= threshold for score in candidate_best_scores)
            for threshold in [-100, -90, -80, -75, -70, -60, -50]
        },
        "selected_pose_energy_distributions": energy_distributions,
        "invalid_buried_surface_area_sentinel_rows": len(invalid_bsa_rows),
        "baseline_class_counts": dict(sorted(baseline_class_counts.items())),
        "baseline_class_counts_by_reference": baseline_classes_by_reference,
        "baseline_candidates_with_any_class": baseline_candidates_with_any,
        "dual_reference_contingency": dict(sorted(contingency.items())),
        "consensus_class_counts": dict(sorted(consensus_class_counts.items())),
        "consensus_candidates_with_any_class": consensus_candidates_with_any,
        "candidate_tier_counts": dict(sorted(candidate_tier_counts.items())),
        "consensus_a_pose_count_distribution": {str(k): v for k, v in sorted(a_count_distribution.items())},
        "a_or_single_pose_count_distribution": {str(k): v for k, v in sorted(supported_count_distribution.items())},
        "baseline_score_by_class": baseline_score_by_class,
        "consensus_score_by_class": consensus_score_by_class,
        "score_only_auc": {
            "consensus_a_vs_other": tied_rank_auc(consensus_favorable_scores, consensus_a_labels),
            "consensus_a_or_single_vs_other": tied_rank_auc(consensus_favorable_scores, strong_geometry_labels),
        },
        "rf2": {
            "formal_gate_counts": dict(sorted(rf2_gate_counts.items())),
            "formal_gate_counts_for_consensus_a_candidates": dict(sorted(rf2_gate_counts_for_a.items())),
            "consensus_a_candidate_count": len(a_ids),
            "formal_pass_candidate_count": len(rf2_pass_ids),
            "consensus_a_and_formal_rf2_pass_intersection": len(a_ids & rf2_pass_ids),
        },
        "diverse_panel": {
            "candidate_count": len(diverse_panel),
            "near_cdr3_family_count": len({row["near_cdr3_family_id"] for row in diverse_panel}),
            "backbone_group_count": len({row["backbone_group_id"] for row in diverse_panel}),
            "arm_count": len({row["arm_id"] for row in diverse_panel}),
            "scaffold_counts": dict(sorted(Counter(row["scaffold_id"] for row in diverse_panel).items())),
            "h3_regime_counts": dict(sorted(Counter(row["h3_regime"] for row in diverse_panel).items())),
        },
        "top_candidates": diverse_panel,
    }
    return summary, candidate_rows, diverse_panel


def render_markdown(summary: dict[str, Any], diverse_panel: list[dict[str, Any]]) -> str:
    score = summary["haddock_score_distributions"]
    baseline = summary["baseline_class_counts_by_reference"]
    consensus = summary["consensus_class_counts"]
    tiers = summary["candidate_tier_counts"]
    rf2 = summary["rf2"]
    lines = [
        "# RFantibody-PVRIG 1,024 条候选：HADDOCK 分数与阻断几何分析",
        "",
        f"> 生成时间：`{summary['generated_at']}`",
        "",
        "## 1. 一句话结论",
        "",
        "这 1,024 条序列都完成了 HADDOCK3，但不能据此宣称任何一条已经能阻断 PVRIG-PVRL2。",
        "计算上有 47 条候选至少出现 1 个 8X6B/9E6Y 双参考一致的 `CONSENSUS_BLOCKER_LIKE_A` pose；",
        "其中只有 1 条在 4/4 个 pose 上都为双参考 A。然而，这 47 条全部没有通过正式的三 seed RF2 独立恢复门槛，",
        "所以当前最合适的结论是“有 blocker-like 几何、值得优先实验”，而不是“已经证明能阻断”。",
        "",
        "## 2. 数据完整性与统计口径",
        "",
        f"- 候选：{summary['row_counts']['candidates']:,} 条 exact-unique VHH。",
        f"- HADDOCK selected models：{summary['row_counts']['selected_pose_features']:,} 个。",
        f"- 双参考 baseline 行：{summary['row_counts']['baseline_rows']:,}，即 1,024 × 4 pose × 2 reference。",
        f"- 去重后的前 4 pose：{summary['row_counts']['deduplicated_top4_poses']:,}。",
        "- 本流程是按 PVRIG-PVRL2 界面热点引导的受约束 docking，不是 blind docking；它检验的是目标表位条件下的 pose 兼容性。",
        "- 9E6Y 是同一 8X6B-guided pose 的 reference-overlay scoring，不是独立第二轮 docking。",
        "- HADDOCK 分数越负通常表示在该 scoring function 下更有利，但不是 Kd、IC50 或阻断率。",
        "",
        "## 3. HADDOCK 分数分布",
        "",
        "| 口径 | n | min | P5 | P25 | median | P75 | P95 | max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = [
        ("全部 selected models", score["all_selected_poses"]),
        ("每候选前 4 pose", score["top4_deduplicated_poses"]),
        ("每候选 best score", score["candidate_best"]),
    ]
    for label, values in labels:
        lines.append(
            f"| {label} | {values['n']:,} | {fmt(values['min'])} | {fmt(values['p05'])} | "
            f"{fmt(values['p25'])} | {fmt(values['median'])} | {fmt(values['p75'])} | "
            f"{fmt(values['p95'])} | {fmt(values['max'])} |"
        )
    lines.extend(
        [
            "",
            "每候选 best score 的中位数是 "
            f"`{fmt(score['candidate_best']['median'])}`；最负值为 `{fmt(score['candidate_best']['min'], 3)}`。",
            "其中 42 条 best score ≤ -100，159 条 ≤ -90，464 条 ≤ -80。",
            "但最负分候选不一定是双参考 blocker-like，因此不能按 HADDOCK 分数单轴截断。",
            "",
            "按 consensus class 看，分数中位数为：",
            "",
            "| consensus class | pose 数 | HADDOCK median | min | max |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for label, values in summary["consensus_score_by_class"].items():
        lines.append(
            f"| `{label}` | {values['n']:,} | {fmt(values['median'])} | {fmt(values['min'])} | {fmt(values['max'])} |"
        )
    lines.extend(
        [
            "",
            "仅用 HADDOCK score 区分双参考 A 与其余 pose 的 AUC 约为 "
            f"`{summary['score_only_auc']['consensus_a_vs_other']:.3f}`；"
            "若把双参考 A 与单参考 recheck 合并为强几何组，AUC 仅约 "
            f"`{summary['score_only_auc']['consensus_a_or_single_vs_other']:.3f}`。",
            "这说明分数和阻断几何有关，但远不足以替代热点/遮挡判定。",
            "",
            "## 4. 双参考阻断几何",
            "",
            "`BLOCKER_LIKE_A` 的规则阈值为：热点重叠 ≥14、总 PVRL2 遮挡 ≥500、CDR3 遮挡 ≥100、CDR3 遮挡比例 ≥0.15。",
            "这些阈值定义的是计算分类，不是生物学真值。",
            "",
            "| reference | BLOCKER_LIKE_A | BLOCKER_PLAUSIBLE_B | EVIDENCE_ONLY_E |",
            "|---|---:|---:|---:|",
            f"| 8X6B | {baseline['8X6B'].get('BLOCKER_LIKE_A', 0):,} | {baseline['8X6B'].get('BLOCKER_PLAUSIBLE_B', 0):,} | {baseline['8X6B'].get('EVIDENCE_INFERENCE_ONLY_E', 0):,} |",
            f"| 9E6Y overlay | {baseline['9E6Y'].get('BLOCKER_LIKE_A', 0):,} | {baseline['9E6Y'].get('BLOCKER_PLAUSIBLE_B', 0):,} | {baseline['9E6Y'].get('EVIDENCE_INFERENCE_ONLY_E', 0):,} |",
            "",
            f"8X6B 的 A 比例为 `{pct(baseline['8X6B'].get('BLOCKER_LIKE_A', 0), 4096):.2f}%`，"
            f"9E6Y overlay 只有 `{pct(baseline['9E6Y'].get('BLOCKER_LIKE_A', 0), 4096):.2f}%`。",
            "这种明显不对称说明 9E6Y 是严格的跨构象过滤器，也说明多数 8X6B A pose 并不稳健。",
            "",
            "| pose consensus | pose 数 | 占 4,096 pose | 涉及候选数 |",
            "|---|---:|---:|---:|",
        ]
    )
    for label in [
        "CONSENSUS_BLOCKER_LIKE_A",
        "SINGLE_BASELINE_BLOCKER_RECHECK",
        "BLOCKER_PLAUSIBLE_B",
        "EVIDENCE_INFERENCE_ONLY_E",
    ]:
        count = consensus.get(label, 0)
        candidate_count = summary["consensus_candidates_with_any_class"].get(label, 0)
        lines.append(f"| `{label}` | {count:,} | {pct(count, 4096):.2f}% | {candidate_count:,} |")
    lines.extend(
        [
            "",
            "候选级互斥分层：",
            "",
            f"- Tier 1：至少一个双参考 A，`{tiers['TIER_1_DUAL_REFERENCE_A']}` 条。",
            f"- Tier 2：没有双参考 A，但至少一个单参考 A，`{tiers['TIER_2_SINGLE_REFERENCE_RECHECK']}` 条。",
            f"- Tier 3：只有 plausible B，`{tiers['TIER_3_PLAUSIBLE']}` 条。",
            f"- Tier 4：只有 evidence-only，`{tiers['TIER_4_EVIDENCE_ONLY']}` 条。",
            "",
            "47 条 Tier 1 中，A-pose 数量分布为：35 条有 1/4、9 条有 2/4、2 条有 3/4、1 条有 4/4。",
            "多 pose 一致性比单个偶然 pose 更值得优先。",
            "",
            "## 5. RF2 独立恢复与证据冲突",
            "",
            f"- 全体正式三 seed RF2 pass：`{rf2['formal_pass_candidate_count']}` / 1,024。",
            f"- 至少一个双参考 A：`{rf2['consensus_a_candidate_count']}` / 1,024。",
            f"- 同时满足双参考 A 与正式 RF2 pass：`{rf2['consensus_a_and_formal_rf2_pass_intersection']}`。",
            "",
            "这不是说 47 条一定不结合；RF2 fail 在本项目里明确只作为 QC，不能直接变成负标签。",
            "但它表示最强 docking 几何没有得到独立 complex-pose 模型的支持，因此整体证据仍然偏弱。",
            "",
            "## 6. 多样化 Top 20 计算候选",
            "",
            "以下排名只代表 docking/blocker-geometry 实验优先级。它优先考虑双参考 A pose 数、单参考支持、跨参考最弱阈值余量和 HADDOCK 分数，",
            "并按 near-CDR3 family、backbone 和 arm 做贪心去冗余。完整序列见 `reports/top20_diverse_blocker_geometry_panel.tsv`。",
            "",
            "| rank | candidate_id | A/4 | 单参/4 | best HADDOCK | 代表 pose | 弱侧热点 | 弱侧总遮挡 | 弱侧 CDR3 | 弱侧比例 | CDR3 | RF2 |",
            "|---:|---|---:|---:|---:|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in diverse_panel:
        lines.append(
            f"| {row['diverse_panel_rank']} | `{row['candidate_id']}` | {row['consensus_a_pose_count']} | "
            f"{row['single_baseline_recheck_pose_count']} | {fmt(row['best_haddock_score'])} | "
            f"{fmt(row['representative_haddock_score'])} | {row['weakest_hotspot_overlap']} | "
            f"{row['weakest_total_occlusion']} | {row['weakest_cdr3_occlusion']} | "
            f"{row['weakest_cdr3_fraction']:.3f} | `{row['cdr3']}` | `{row['rf2_formal_gate_status']}` |"
        )
    top = diverse_panel[0]
    lines.extend(
        [
            "",
            "### 当前最强 docking-geometry 候选",
            "",
            f"`{top['candidate_id']}` 在 4/4 个 pose 上均为双参考 A；best HADDOCK 为 `{fmt(top['best_haddock_score'], 4)}`。",
            f"其代表 pose 在两参考中较弱一侧仍有热点 `{top['weakest_hotspot_overlap']}`、总遮挡 `{top['weakest_total_occlusion']}`、"
            f"CDR3 遮挡 `{top['weakest_cdr3_occlusion']}`、CDR3 比例 `{top['weakest_cdr3_fraction']:.4f}`。",
            f"但其 RF2 状态为 `{top['rf2_formal_gate_status']}`，best interaction PAE 为 `{top['rf2_best_interaction_pae']:.2f}`，",
            "因此应标记为“高 docking-geometry 优先级、未获正交结构确认”。",
            "",
            "## 7. 能否达到阻断效果",
            "",
            "当前不能回答“能”。更准确的结论是：",
            "",
            "1. 47 条候选在至少一个 pose 上满足双参考 blocker-like 几何，值得进入实验；",
            "2. 只有 12 条在至少 2/4 pose 上稳定满足双参考 A，只有 3 条达到至少 3/4；",
            "3. 没有任何 Tier 1 候选同时通过正式三 seed RF2 恢复；",
            "4. 这批数据没有实验 binder label，1,024 条均为 `binder_axis_status=deferred`、`binder_label=unknown`；",
            "5. 所以目前既不能证明它们结合 PVRIG，也不能证明它们阻断 PVRIG-PVRL2。",
            "",
            "建议把 Tier 1 多样化 Top 12-24 送入实验，而不是把 1,024 条或所有低 HADDOCK 分数序列都当成 blocker。",
            "",
            "## 8. 最小实验闭环",
            "",
            "1. 表达与可开发性：小量表达、SEC/UPLC、MS、DSF，先排除聚集和异常降解。",
            "2. PVRIG binding：ELISA 初筛后用 BLI/SPR 测 kon、koff、Kd；不结合者不能解释阻断。",
            "3. 直接 competition：BLI/SPR 或 plate competition 测 PVRIG-PVRL2/CD112，输出 competition % 与 IC50。",
            "4. 表位验证：PVRIG alanine scan、cross-blocking 或 HDX-MS，确认 R95/K135/F139/E141-G142/S143-W144 区域。",
            "5. 功能实验：PVRIG/CD112R reporter 或免疫细胞共培养，确认功能恢复。",
            "6. 对照：已知 blocker、非阻断 PVRIG binder、irrelevant VHH、无 VHH 四类对照必须齐全。",
            "",
            "## 9. 数据质量提醒",
            "",
            f"`docking_pose_features.tsv` 中有 `{summary['invalid_buried_surface_area_sentinel_rows']}` 行 `buried_surface_area=-999999` sentinel。",
            "它们不在用于双参考分类的前 4 pose 中，但训练模型前应转成 missing value，不能作为真实负 BSA 数值。",
            "另外，当前只有 train/validation 两路 split，没有独立 test split；不能用这批数据自证泛化。",
            "",
            "## 10. 输出文件",
            "",
            "- `reports/docking_score_blocker_summary.json`：机器可读统计。",
            "- `reports/ranked_blocker_geometry_candidates.tsv`：1,024 条候选完整排序及全序列。",
            "- `reports/top20_diverse_blocker_geometry_panel.tsv`：去冗余 Top 20 及全序列。",
            "- `scripts/analyze_docking_blocker_scores.py`：可复现统计脚本。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    summary, ranked, diverse = build_analysis(root)
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "docking_score_blocker_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    fields = [
        "geometry_rank",
        "diverse_panel_rank",
        "candidate_id",
        "candidate_tier",
        "sequence",
        "sequence_length",
        "cdr1",
        "cdr2",
        "cdr3",
        "arm_id",
        "scaffold_id",
        "h3_regime",
        "backbone_group_id",
        "near_cdr3_family_id",
        "near_cdr3_family_size",
        "consensus_a_pose_count",
        "single_baseline_recheck_pose_count",
        "plausible_pose_count",
        "evidence_only_pose_count",
        "best_haddock_score",
        "representative_model",
        "representative_consensus_class",
        "representative_haddock_rank",
        "representative_haddock_score",
        "weakest_hotspot_overlap",
        "weakest_total_occlusion",
        "weakest_cdr3_occlusion",
        "weakest_cdr3_fraction",
        "representative_geometry_margin",
        "rf2_formal_gate_status",
        "rf2_best_interaction_pae",
        "rf2_best_pred_lddt",
        "rf2_recovered_seeds",
        "binder_axis_status",
        "binder_label",
    ]
    write_tsv(reports / "ranked_blocker_geometry_candidates.tsv", ranked, fields)
    write_tsv(reports / "top20_diverse_blocker_geometry_panel.tsv", diverse, fields)
    (reports / "DOCKING_SCORE_BLOCKER_ANALYSIS_ZH.md").write_text(
        render_markdown(summary, diverse), encoding="utf-8"
    )
    print(json.dumps({
        "status": "ANALYSIS_COMPLETE",
        "candidate_count": len(ranked),
        "consensus_a_candidates": summary["rf2"]["consensus_a_candidate_count"],
        "diverse_panel_count": len(diverse),
        "report": str(reports / "DOCKING_SCORE_BLOCKER_ANALYSIS_ZH.md"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
