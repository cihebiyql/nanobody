#!/usr/bin/env python3
"""Aggregate the PVRIG positive-control affinity benchmark and write a report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
GRAPHINITY_PREDS = (
    ROOT
    / "graphinity_single_mutation"
    / "preds_PVRIG-positive-single-interface-mutation.csv"
)
NEUTRAL_DDG = 0.1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pearson(x: pd.Series, y: pd.Series) -> float:
    return float(np.corrcoef(x.astype(float), y.astype(float))[0, 1])


def spearman(x: pd.Series, y: pd.Series) -> float:
    return pearson(x.rank(method="average"), y.rank(method="average"))


def ddg_class(value: float) -> str:
    if value < -NEUTRAL_DDG:
        return "stronger"
    if value > NEUTRAL_DDG:
        return "weaker"
    return "neutral"


def metrics(frame: pd.DataFrame, truth: str, prediction: str) -> dict:
    data = frame.dropna(subset=[truth, prediction]).copy()
    return {
        "n": int(len(data)),
        "pearson": pearson(data[truth], data[prediction]),
        "spearman": spearman(data[truth], data[prediction]),
        "mae": float((data[truth] - data[prediction]).abs().mean()),
        "ternary_direction_correct": int(
            sum(ddg_class(t) == ddg_class(p) for t, p in zip(data[truth], data[prediction]))
        ),
        "ternary_direction_total": int(len(data)),
        "neutral_threshold_kcal_mol": NEUTRAL_DDG,
    }


def fmt(value: float | int | None, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "NA"
    if isinstance(value, (int, np.integer)):
        return str(value)
    return f"{float(value):.{digits}f}"


def markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def main() -> None:
    absolute = pd.read_csv(ROOT / "candidate_level_affinity_summary.tsv", sep="\t")
    known = absolute.dropna(subset=["known_kd_m"]).copy()
    known["experimental_pkd"] = -np.log10(known["known_kd_m"])
    known["prodigy_kd_median_nm"] = np.power(10.0, -known["prodigy_pkd_median"]) * 1e9
    known["prodigy_pkd_abs_error"] = (
        known["prodigy_pkd_median"] - known["experimental_pkd"]
    ).abs()

    absolute_metrics = json.loads((ROOT / "evaluation_metrics.json").read_text())
    corr_by_feature = {item["feature"]: item for item in absolute_metrics["correlations"]}

    foldx = pd.read_csv(ROOT / "fixed_pose_foldx_binding_ddg.tsv", sep="\t")
    foldx_pairs = (
        foldx.groupby("pair_id", sort=False)
        .agg(
            parent=("parent", "first"),
            child=("child", "first"),
            mutation_count=("mutation_count", "first"),
            experimental_ddg_kcal_mol=("experimental_ddg_kcal_mol", "first"),
            foldx_binding_ddg_median=("foldx_binding_ddg", "median"),
            foldx_binding_ddg_mean=("foldx_binding_ddg", "mean"),
            foldx_binding_ddg_stdev=("foldx_binding_ddg", "std"),
            repeat_count=("foldx_binding_ddg", "size"),
        )
        .reset_index()
    )
    foldx_pairs["experimental_class"] = foldx_pairs["experimental_ddg_kcal_mol"].map(
        lambda value: ddg_class(value) if pd.notna(value) else "unknown"
    )
    foldx_pairs["predicted_class"] = foldx_pairs["foldx_binding_ddg_median"].map(ddg_class)
    foldx_pairs.to_csv(ROOT / "fixed_pose_foldx_pair_summary.tsv", sep="\t", index=False)
    foldx_metrics = metrics(
        foldx_pairs,
        "experimental_ddg_kcal_mol",
        "foldx_binding_ddg_median",
    )

    graph_input = pd.read_csv(ROOT / "graphinity_single_mutation_input.csv")
    graph_preds = pd.read_csv(GRAPHINITY_PREDS)
    graph_rows = graph_input.merge(
        graph_preds,
        left_on=["pdb_wt", "pdb_mut"],
        right_on=["wt_pdb", "mut_pdb"],
        how="inner",
        validate="one_to_one",
    )
    assert len(graph_rows) == 27
    graph_mut = (
        graph_rows.groupby(["pair_id", "mutation"], sort=False)
        .agg(
            experimental_pair_ddg_kcal_mol=("experimental_pair_ddg_kcal_mol", "first"),
            graphinity_ddg_median=("pred_score", "median"),
            graphinity_ddg_mean=("pred_score", "mean"),
            graphinity_ddg_stdev=("pred_score", "std"),
            repeat_count=("pred_score", "size"),
        )
        .reset_index()
    )
    graph_mut.to_csv(ROOT / "graphinity_single_mutation_scores.tsv", sep="\t", index=False)

    graph_pairs = (
        graph_mut.groupby("pair_id", sort=False)
        .agg(
            experimental_ddg_kcal_mol=("experimental_pair_ddg_kcal_mol", "first"),
            graphinity_additive_interface_ddg=("graphinity_ddg_median", "sum"),
            interface_mutation_count=("mutation", "size"),
            mutations=("mutation", lambda values: ",".join(values)),
        )
        .reset_index()
    )
    graph_pairs["experimental_class"] = graph_pairs["experimental_ddg_kcal_mol"].map(
        lambda value: ddg_class(value) if pd.notna(value) else "unknown"
    )
    graph_pairs["predicted_class"] = graph_pairs["graphinity_additive_interface_ddg"].map(ddg_class)
    graph_pairs.to_csv(ROOT / "graphinity_pair_additive_summary.tsv", sep="\t", index=False)
    graph_metrics = metrics(
        graph_pairs,
        "experimental_ddg_kcal_mol",
        "graphinity_additive_interface_ddg",
    )

    mutation_manifest = pd.read_csv(ROOT / "graphinity_single_mutation_manifest.tsv", sep="\t")
    interface_count = int(mutation_manifest["is_interface_le4A"].astype(int).sum())
    total_mutation_count = int(len(mutation_manifest))

    prodigy_corr = corr_by_feature["prodigy_pkd_median"]
    foldx_abs_corr = corr_by_feature["foldx_interaction_median"]
    prodigy_direction = absolute_metrics["within_family_pair_direction"]["prodigy_pkd_median"]
    foldx_abs_direction = absolute_metrics["within_family_pair_direction"]["foldx_interaction_median"]

    method_comparison = pd.DataFrame(
        [
            {
                "method": "PRODIGY_median_across_9_independent_docked_poses",
                "task": "absolute_cross_candidate_pKd",
                "n": prodigy_corr["n"],
                "pearson": prodigy_corr["pearson_vs_pKd"],
                "spearman": prodigy_corr["spearman_vs_pKd"],
                "mae": float(known["prodigy_pkd_abs_error"].mean()),
                "mae_unit": "pKd_log10_units",
                "direction_correct": prodigy_direction["correct"],
                "direction_total": prodigy_direction["total"],
                "coverage": "10/10 known-Kd positives",
                "verdict": "weak_prior_only",
            },
            {
                "method": "FoldX_AnalyseComplex_median_across_9_independent_docked_poses",
                "task": "absolute_cross_candidate_interaction_score",
                "n": foldx_abs_corr["n"],
                "pearson": foldx_abs_corr["pearson_vs_pKd"],
                "spearman": foldx_abs_corr["spearman_vs_pKd"],
                "mae": np.nan,
                "mae_unit": "not_comparable_to_pKd",
                "direction_correct": foldx_abs_direction["correct"],
                "direction_total": foldx_abs_direction["total"],
                "coverage": "10/10 known-Kd positives",
                "verdict": "not_recommended_for_cross_candidate_affinity",
            },
            {
                "method": "FoldX_fixed_parent_pose_multi_mutation_binding_ddG_median_5_repeats",
                "task": "same_parent_relative_ddG",
                "n": foldx_metrics["n"],
                "pearson": foldx_metrics["pearson"],
                "spearman": foldx_metrics["spearman"],
                "mae": foldx_metrics["mae"],
                "mae_unit": "kcal_per_mol",
                "direction_correct": foldx_metrics["ternary_direction_correct"],
                "direction_total": foldx_metrics["ternary_direction_total"],
                "coverage": "5/5 known same-parent pairs",
                "verdict": "diagnostic_only_until_pose_calibration",
            },
            {
                "method": "Graphinity_single_interface_mutation_additive_approximation",
                "task": "same_parent_relative_ddG",
                "n": graph_metrics["n"],
                "pearson": graph_metrics["pearson"],
                "spearman": graph_metrics["spearman"],
                "mae": graph_metrics["mae"],
                "mae_unit": "kcal_per_mol",
                "direction_correct": graph_metrics["ternary_direction_correct"],
                "direction_total": graph_metrics["ternary_direction_total"],
                "coverage": f"{interface_count}/{total_mutation_count} substitutions local to interface; 4/5 known pairs scorable",
                "verdict": "rejected_for_current_candidate_ranking",
            },
        ]
    )
    method_comparison.to_csv(ROOT / "final_method_comparison.tsv", sep="\t", index=False)

    final_metrics = {
        "benchmark": {
            "positive_count": 11,
            "known_kd_count": 10,
            "existing_pose_count": 99,
            "poses_per_candidate": 9,
            "redocking_performed": False,
        },
        "prodigy_absolute": {
            **prodigy_corr,
            "mean_absolute_pKd_error": float(known["prodigy_pkd_abs_error"].mean()),
            "median_absolute_pKd_error": float(known["prodigy_pkd_abs_error"].median()),
            "within_family_direction": prodigy_direction,
        },
        "foldx_absolute": {
            **foldx_abs_corr,
            "within_family_direction": foldx_abs_direction,
        },
        "foldx_fixed_pose_relative": foldx_metrics,
        "graphinity": {
            **graph_metrics,
            "single_mutation_predictions": int(len(graph_rows)),
            "pair_specific_interface_mutations": interface_count,
            "total_parent_child_substitutions": total_mutation_count,
            "substitution_coverage_fraction": interface_count / total_mutation_count,
            "aggregation": "median across 3 FoldX conformers per mutation, then additive sum across interface mutations",
            "scope_warning": "Graphinity int_mut is a single-interface-mutation model; additive multi-mutation aggregation is an approximation.",
        },
        "software": {
            "prodigy_executable_sha256": "75b9a60a33fb3b7410d17e239bb53219b68eb47e3fad9fe94a1e9157ee2989a9",
            "foldx_version": "5.1",
            "foldx_executable_sha256": "faed5e54e47744ab6ab75f8f9ad1a1f2e2cdbeac4f0f98d4e36c97049eb14268",
            "graphinity_checkpoint_sha256": "40c9de6081930ef4923f4726fd45ffc84e96edea741a5a9adabe21b2e3beba77",
            "graphinity_runtime": {
                "python": "3.7.10",
                "torch": "1.8.0+cpu",
                "torch_geometric": "1.6.3",
                "pytorch_lightning": "1.2.10",
            },
        },
        "input_hashes": {
            "pose_manifest.tsv": sha256(ROOT / "pose_manifest.tsv"),
            "fixed_pose_pair_manifest.tsv": sha256(ROOT / "fixed_pose_pair_manifest.tsv"),
            "graphinity_single_mutation_manifest.tsv": sha256(
                ROOT / "graphinity_single_mutation_manifest.tsv"
            ),
            "graphinity_single_mutation_input.csv": sha256(
                ROOT / "graphinity_single_mutation_input.csv"
            ),
        },
        "decision": {
            "formal_affinity_hard_gate": "none",
            "usable_now": [
                "PRODIGY median as a weak pose-dependent prior",
                "fixed-pose FoldX ddG as a same-parent diagnostic for carefully validated poses",
            ],
            "rejected_now": [
                "PRODIGY absolute Kd",
                "FoldX independent-docking cross-candidate affinity ranking",
                "Graphinity additive score for current multi-mutation candidates",
            ],
        },
    }
    (ROOT / "final_evaluation_metrics.json").write_text(
        json.dumps(final_metrics, ensure_ascii=False, indent=2) + "\n"
    )

    absolute_rows = []
    for row in known.sort_values("known_kd_m").itertuples(index=False):
        absolute_rows.append(
            [
                row.molecule_name,
                fmt(row.known_kd_m * 1e9, 4),
                fmt(row.prodigy_kd_median_nm, 1),
                fmt(row.prodigy_pkd_abs_error, 2),
                fmt(row.foldx_interaction_median, 2),
            ]
        )

    foldx_rows = []
    for row in foldx_pairs.itertuples(index=False):
        foldx_rows.append(
            [
                f"{row.parent} -> {row.child}",
                row.mutation_count,
                fmt(row.experimental_ddg_kcal_mol),
                fmt(row.foldx_binding_ddg_median),
                f"{row.experimental_class}/{row.predicted_class}",
            ]
        )

    graph_rows_md = []
    for row in graph_pairs.itertuples(index=False):
        graph_rows_md.append(
            [
                row.pair_id,
                row.interface_mutation_count,
                row.mutations,
                fmt(row.experimental_ddg_kcal_mol),
                fmt(row.graphinity_additive_interface_ddg),
                f"{row.experimental_class}/{row.predicted_class}",
            ]
        )

    report = f"""# PVRIG 已有阳性 VHH 计算亲和力方法实测

## 1. 结论先行

本次用 **11 条已有 PVRIG 阳性 VHH** 做了真实结构重打分，其中 10 条有已知 Kd，共使用 99 个已有 HADDOCK pose（每条 9 个）。

结果不支持把任何一个方法当成“可靠的 Kd 预测器”：

1. **PRODIGY** 有弱的跨候选方向信号（Spearman={prodigy_corr['spearman_vs_pKd']:.3f}），但绝对 Kd 中位误差为 {float(known['prodigy_pkd_abs_error'].median()):.2f} 个 log10 单位，约差 {10 ** float(known['prodigy_pkd_abs_error'].median()):.0f} 倍。只能作 weak prior，不能写成预测 Kd。
2. **FoldX 独立 docking pose 的 AnalyseComplex** 跨候选排序更弱（Spearman={foldx_abs_corr['spearman_vs_pKd']:.3f}），不建议用于不同 VHH 的绝对亲和力比较。
3. **FoldX 固定 parent pose 的多突变绑定 ΔΔG** 在 20->20H5 和 30->30H2 上方向正确，但总体只有 {foldx_metrics['ternary_direction_correct']}/{foldx_metrics['ternary_direction_total']} 方向正确，对 39 家族失败，对 151H7 基本返回 0。
4. **Graphinity** 的官方单点推理已成功部署，但它只能处理单个界面突变。当前 79 个 parent->child 替换中只有 {interface_count} 个在固定 pose 的 4 A 界面内（{interface_count / total_mutation_count:.1%}）。将这些单点分数加和后，4 个有 Kd 的可评估 pair 只有 {graph_metrics['ternary_direction_correct']}/{graph_metrics['ternary_direction_total']} 方向正确，Spearman={graph_metrics['spearman']:.3f}。**当前不能用于候选排名。**

因此，当前亲和力路线的合理位置是：**PRODIGY 作弱先验，FoldX 固定 pose ΔΔG 作同 parent 诊断，不设亲和力 hard gate。**

## 2. 数据和评估口径

- 阳性面板：11 条；10 条有 Kd，5 条有 IC50。
- 结构输入：每个候选固定取 9 个已有 HADDOCK pose，共 99 个；本次没有重新 docking。
- 绝对排序：将 PRODIGY 中位 pKd、FoldX 中位 interaction energy 与实验 pKd 比较。
- 相对排序：同 parent 的 humanized child 在 parent 固定 pose 上建模，实验值按 `RT ln(Kd_child/Kd_parent)` 计算。
- 方向判定：ΔΔG < -{NEUTRAL_DDG} kcal/mol 为变强，> +{NEUTRAL_DDG} 为变弱，其余为中性。
- 技术边界：这些是 pose-dependent 计算分数，不是实验 Kd，也不等于阻断效果。

## 3. PRODIGY 绝对 Kd 结果

{markdown_table(['阳性', '实验 Kd (nM)', 'PRODIGY 中位 Kd (nM)', '|pKd 误差|', 'FoldX interaction 中位'], absolute_rows)}

统计：

- PRODIGY：Pearson={prodigy_corr['pearson_vs_pKd']:.3f}，Spearman={prodigy_corr['spearman_vs_pKd']:.3f}，pKd MAE={float(known['prodigy_pkd_abs_error'].mean()):.3f}；同家族两两方向 {prodigy_direction['correct']}/{prodigy_direction['total']}。
- FoldX absolute interaction：Pearson={foldx_abs_corr['pearson_vs_pKd']:.3f}，Spearman={foldx_abs_corr['spearman_vs_pKd']:.3f}；同家族方向 {foldx_abs_direction['correct']}/{foldx_abs_direction['total']}。
- PRODIGY 预测的 Kd 全部比实验值弱，不能直接填入“预测 Kd”字段。

## 4. FoldX 固定 pose 多突变绑定 ΔΔG

{markdown_table(['pair', '突变数', '实验 ΔΔG', 'FoldX 中位 ΔΔG', '实验/预测方向'], foldx_rows)}

总体：Pearson={foldx_metrics['pearson']:.3f}，Spearman={foldx_metrics['spearman']:.3f}，MAE={foldx_metrics['mae']:.3f} kcal/mol，方向 {foldx_metrics['ternary_direction_correct']}/{foldx_metrics['ternary_direction_total']}。样本数只有 5，只能看成定性诊断。

## 5. Graphinity 单界面突变实测

Graphinity 官方 example smoke 已成功；本次又对 9 个 pair-specific 界面突变、3 个 FoldX 构象重复，共 27 个 WT/mutant 对成功推理。

{markdown_table(['pair', '界面突变数', '突变', '实验 pair ΔΔG', 'Graphinity 加和', '实验/预测方向'], graph_rows_md)}

不接受 Graphinity 结果作当前排名依据，原因是：

1. 模型实际口径是单界面突变，而当前 child 有 8--20 个突变；简单相加忽略 epistasis。
2. 只覆盖 {interface_count}/{total_mutation_count} 个替换，大多数突变不在当前 pose 的 4 A 界面内。
3. 20H5 和 30H2 的实验方向都被预测反了；39H2/39H4 因 parent pose 和 RA26G 完全相同而得到相同分数，无法解释其它差异。
4. 多个“界面突变”出现在 VHH 第 1 位残基，这提示当前 docking pose 可能含有不理想的 N 端接触。

## 6. 对筛选流程的决策

### 现在可以保留

- `prodigy_binding_prior`：保留为连续弱先验，不 hard fail，不称 Kd。
- `foldx_fixed_pose_ddg`：只在同 parent、同 pose、界面经人工/规则质控时使用，并保留 5 个 repeat 的方差。
- 两者都与 blocker geometry、developability、expression/purity 分开存储。

### 现在不能使用

- PRODIGY 绝对 Kd；
- 独立 docking pose 的 FoldX 跨候选排名；
- Graphinity 对当前多突变 VHH 的直接排名或 hard gate；
- 任何将计算亲和力分数等同于阻断效果的表述。

## 7. 下一个最有价值的计算实验

不是再堆更多通用 sequence-only binding classifier，而是为 5--10 个已知阳性家族建立**经校准的同 parent 复合物姿势**，做小规模 pose ensemble + FoldX/Flex-ddG 或短 MD 后 MM/GBSA，先看能否稳定复现 20/30/39/151 家族的已知相对方向。只有这个校准关通过，才值得把结构亲和力项加入 50 万条前筛。

## 8. 可复现文件

- `pose_manifest.tsv`：99 个冻结 pose。
- `pose_level_affinity_scores.tsv`：PRODIGY/FoldX pose-level 结果。
- `candidate_level_affinity_summary.tsv`：候选汇总。
- `fixed_pose_foldx_binding_ddg.tsv`：30 个 FoldX 重复。
- `fixed_pose_foldx_pair_summary.tsv`：同 parent pair 汇总。
- `graphinity_single_mutation_input.csv`：27 个 Graphinity 合法单点输入。
- `graphinity_single_mutation_scores.tsv`：Graphinity 单突变汇总。
- `graphinity_pair_additive_summary.tsv`：仅供评估的加和近似。
- `final_method_comparison.tsv` 与 `final_evaluation_metrics.json`：最终机器可读结论。
"""
    (ROOT / "PVRIG_POSITIVE_AFFINITY_METHOD_BENCHMARK_ZH.md").write_text(report)

    print(method_comparison.to_string(index=False))
    print(f"\nWrote report: {ROOT / 'PVRIG_POSITIVE_AFFINITY_METHOD_BENCHMARK_ZH.md'}")


if __name__ == "__main__":
    main()
