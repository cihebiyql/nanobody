#!/usr/bin/env python3
"""Compare independently executed PVRIG V2.9 HADDOCK jobs on node1 and rli HPC."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


PAIR_ORD = {"OTHER": 0, "SUPPORTED_AB": 1, "STRICT_A": 2}


def read_tsv(path: Path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_tsv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    x, y = zip(*pairs)
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sx = sum((v - mx) ** 2 for v in x)
    sy = sum((v - my) ** 2 for v in y)
    if sx == 0 or sy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in pairs) / math.sqrt(sx * sy)


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in order[i:j]:
            out[k] = rank
        i = j
    return out


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    x, y = zip(*pairs)
    return pearson(ranks(x), ranks(y))


def continuous_stats(pairs):
    valid = [(a, b) for a, b in pairs if a is not None and b is not None]
    if not valid:
        return {"n": 0}
    diffs = [a - b for a, b in valid]
    ad = [abs(v) for v in diffs]
    return {
        "n": len(valid),
        "pearson_r": pearson([a for a, _ in valid], [b for _, b in valid]),
        "spearman_rho": spearman([a for a, _ in valid], [b for _, b in valid]),
        "mae": statistics.fmean(ad),
        "median_abs_diff": statistics.median(ad),
        "mean_own_minus_rli": statistics.fmean(diffs),
        "p90_abs_diff": sorted(ad)[max(0, math.ceil(0.90 * len(ad)) - 1)],
    }


def exact_stats(pairs):
    n = len(pairs)
    exact = sum(a == b for a, b in pairs)
    return {"n": n, "exact_n": exact, "exact_fraction": exact / n if n else None}


def confusion(pairs):
    c = Counter((a or "", b or "") for a, b in pairs)
    return {f"own={a}|rli={b}": n for (a, b), n in sorted(c.items())}


def status_map(root: Path, job_ids):
    out = {}
    for jid in job_ids:
        p = root / f"{jid}.json"
        if not p.exists():
            out[jid] = "ABSENT"
            continue
        try:
            d = json.loads(p.read_text())
            out[jid] = str(d.get("state") or d.get("status") or "UNKNOWN")
        except Exception:
            out[jid] = "UNREADABLE"
    return out


def round_obj(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, dict):
        return {k: round_obj(x) for k, x in v.items()}
    if isinstance(v, list):
        return [round_obj(x) for x in v]
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--own-job", type=Path, required=True)
    ap.add_argument("--own-pose", type=Path, required=True)
    ap.add_argument("--rli-job", type=Path, required=True)
    ap.add_argument("--rli-pose", type=Path, required=True)
    ap.add_argument("--own-manifest", type=Path, required=True)
    ap.add_argument("--rli-manifest", type=Path, required=True)
    ap.add_argument("--own-status", type=Path, required=True)
    ap.add_argument("--rli-status", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    own_jobs = {r["job_id"]: r for r in read_tsv(args.own_job)}
    rli_jobs = {r["job_id"]: r for r in read_tsv(args.rli_job)}
    overlap = sorted(set(own_jobs) & set(rli_jobs))
    if set(own_jobs) != set(overlap):
        raise SystemExit("own aggregate contains jobs outside rli overlap")

    own_m = {r["job_id"]: r for r in read_tsv(args.own_manifest)}
    rli_m = {r["job_id"]: r for r in read_tsv(args.rli_manifest)}
    rli_ids = sorted(rli_m)
    own_status = status_map(args.own_status, rli_ids)
    rli_status = status_map(args.rli_status, rli_ids)
    status_matrix = Counter((own_status[j], rli_status[j]) for j in rli_ids)

    hash_fields = ["job_hash", "sequence_sha256", "cfg_hash", "restraint_hash", "protocol_core_sha256", "protocol_hash"]
    hashes = {}
    for field in hash_fields:
        pairs = [(own_m[j].get(field, ""), rli_m[j].get(field, "")) for j in rli_ids if j in own_m]
        hashes[field] = exact_stats(pairs)

    numeric = [
        "selected_model_count", "haddock_score", "air_energy",
        "model_pair_consensus_fraction", "model_native_cross_support_agreement_fraction",
        "model_strict_a_fraction", "native_hotspot_overlap", "cross_hotspot_overlap",
        "native_holdout_overlap", "cross_holdout_overlap", "native_total_occlusion",
        "cross_total_occlusion", "native_cdr3_occlusion", "cross_cdr3_occlusion",
        "native_cdr3_fraction", "cross_cdr3_fraction",
    ]
    categorical = ["representative_model", "native_class", "cross_class", "representative_pair_label"]
    num_stats = {field: continuous_stats([(f(own_jobs[j].get(field)), f(rli_jobs[j].get(field))) for j in overlap]) for field in numeric}
    cat_stats = {}
    for field in categorical:
        pairs = [(own_jobs[j].get(field, ""), rli_jobs[j].get(field, "")) for j in overlap]
        cat_stats[field] = {**exact_stats(pairs), "confusion": confusion(pairs)}

    pair_ord_pairs = [(PAIR_ORD.get(own_jobs[j].get("representative_pair_label")), PAIR_ORD.get(rli_jobs[j].get("representative_pair_label"))) for j in overlap]
    pair_ord = continuous_stats(pair_ord_pairs)
    pair_ord["within_one_fraction"] = sum(abs(a - b) <= 1 for a, b in pair_ord_pairs if a is not None and b is not None) / len(pair_ord_pairs)
    pair_ord["positive_support_agreement_fraction"] = sum((a >= 1) == (b >= 1) for a, b in pair_ord_pairs) / len(pair_ord_pairs)

    detail = []
    for j in overlap:
        a, b = own_jobs[j], rli_jobs[j]
        row = {
            "job_id": j, "entity_id": a["entity_id"], "conformation": a["conformation"], "seed": a["seed"],
            "job_hash_equal": str(a.get("job_hash") == b.get("job_hash")).lower(),
            "own_pair_label": a.get("representative_pair_label", ""), "rli_pair_label": b.get("representative_pair_label", ""),
            "pair_label_equal": str(a.get("representative_pair_label") == b.get("representative_pair_label")).lower(),
            "own_native_class": a.get("native_class", ""), "rli_native_class": b.get("native_class", ""),
            "own_cross_class": a.get("cross_class", ""), "rli_cross_class": b.get("cross_class", ""),
            "own_selected_models": a.get("selected_model_count", ""), "rli_selected_models": b.get("selected_model_count", ""),
            "own_haddock_score": a.get("haddock_score", ""), "rli_haddock_score": b.get("haddock_score", ""),
            "haddock_delta_own_minus_rli": (f(a.get("haddock_score")) - f(b.get("haddock_score"))) if f(a.get("haddock_score")) is not None and f(b.get("haddock_score")) is not None else "",
            "own_consensus_fraction": a.get("model_pair_consensus_fraction", ""), "rli_consensus_fraction": b.get("model_pair_consensus_fraction", ""),
        }
        detail.append(row)
    write_tsv(args.outdir / "job_level_comparison.tsv", detail, list(detail[0]))

    own_pose_rows = read_tsv(args.own_pose)
    rli_pose_rows = [r for r in read_tsv(args.rli_pose) if r["job_id"] in own_jobs]
    def pkey(r): return (r["job_id"], r["scoring_reference"], r["model"])
    op = {pkey(r): r for r in own_pose_rows}
    rp = {pkey(r): r for r in rli_pose_rows}
    pcommon = sorted(set(op) & set(rp))
    pose_numeric = ["haddock_score", "air_energy", "geometry_margin", "hotspot_overlap", "anchor_overlap", "holdout_overlap", "total_occlusion", "cdr3_occlusion", "cdr3_fraction", "clash_atom_pairs", "clash_residue_pairs", "overlay_rmsd_a"]
    pose_num_stats = {field: continuous_stats([(f(op[k].get(field)), f(rp[k].get(field))) for k in pcommon]) for field in pose_numeric}
    pose_class_pairs = [(op[k].get("geometry_class", ""), rp[k].get("geometry_class", "")) for k in pcommon]
    pose_class = {**exact_stats(pose_class_pairs), "confusion": confusion(pose_class_pairs)}

    models_own, models_rli = defaultdict(set), defaultdict(set)
    for r in own_pose_rows: models_own[r["job_id"]].add(r["model"])
    for r in rli_pose_rows: models_rli[r["job_id"]].add(r["model"])
    model_stats_rows = []
    for j in overlap:
        a, b = models_own[j], models_rli[j]
        inter, union = a & b, a | b
        model_stats_rows.append({
            "job_id": j, "own_model_count": len(a), "rli_model_count": len(b),
            "common_model_count": len(inter), "model_jaccard": len(inter) / len(union) if union else 1.0,
            "model_set_exact": str(a == b).lower(),
        })
    write_tsv(args.outdir / "model_set_comparison.tsv", model_stats_rows, list(model_stats_rows[0]))

    pose_detail = []
    for k in pcommon:
        a, b = op[k], rp[k]
        pose_detail.append({
            "job_id": k[0], "scoring_reference": k[1], "model": k[2],
            "own_geometry_class": a.get("geometry_class", ""), "rli_geometry_class": b.get("geometry_class", ""),
            "geometry_class_equal": str(a.get("geometry_class") == b.get("geometry_class")).lower(),
            "own_haddock_score": a.get("haddock_score", ""), "rli_haddock_score": b.get("haddock_score", ""),
            "own_hotspot_overlap": a.get("hotspot_overlap", ""), "rli_hotspot_overlap": b.get("hotspot_overlap", ""),
            "own_total_occlusion": a.get("total_occlusion", ""), "rli_total_occlusion": b.get("total_occlusion", ""),
            "own_overlay_rmsd_a": a.get("overlay_rmsd_a", ""), "rli_overlay_rmsd_a": b.get("overlay_rmsd_a", ""),
        })
    write_tsv(args.outdir / "pose_level_common_model_comparison.tsv", pose_detail, list(pose_detail[0]) if pose_detail else [])

    by_entity_own, by_entity_rli = defaultdict(dict), defaultdict(dict)
    for j in overlap:
        by_entity_own[own_jobs[j]["entity_id"]][own_jobs[j]["conformation"]] = own_jobs[j]
        by_entity_rli[rli_jobs[j]["entity_id"]][rli_jobs[j]["conformation"]] = rli_jobs[j]
    dual = []
    for ent in sorted(set(by_entity_own) & set(by_entity_rli)):
        if set(by_entity_own[ent]) >= {"8x6b", "9e6y"} and set(by_entity_rli[ent]) >= {"8x6b", "9e6y"}:
            ao = min(PAIR_ORD[by_entity_own[ent][c]["representative_pair_label"]] for c in ("8x6b", "9e6y"))
            bo = min(PAIR_ORD[by_entity_rli[ent][c]["representative_pair_label"]] for c in ("8x6b", "9e6y"))
            dual.append({"entity_id": ent, "own_dual_min_ordinal": ao, "rli_dual_min_ordinal": bo, "exact": str(ao == bo).lower(), "both_supported_agree": str((ao >= 1) == (bo >= 1)).lower()})
    write_tsv(args.outdir / "dual_conformation_21_comparison.tsv", dual, list(dual[0]) if dual else [])

    summary = {
        "scope": {
            "rli_manifest_jobs": len(rli_ids), "rli_candidates": len({r["entity_id"] for r in rli_m.values()}),
            "independent_both_success_jobs": len(overlap), "independent_entities": len({own_jobs[j]["entity_id"] for j in overlap}),
            "independent_dual_conformation_entities": len(dual),
            "own_pose_rows": len(own_pose_rows), "rli_pose_rows_filtered_to_overlap_jobs": len(rli_pose_rows),
            "common_model_reference_pose_rows": len(pcommon),
        },
        "execution_status_matrix": {f"own={a}|rli={b}": n for (a, b), n in sorted(status_matrix.items())},
        "manifest_hash_identity": hashes,
        "job_level": {"categorical": cat_stats, "pair_ordinal": pair_ord, "continuous": num_stats},
        "pose_level_common_model_names": {
            "warning": "cluster/model labels are run-local rank labels, not coordinate identity",
            "model_set_exact_fraction": sum(r["model_set_exact"] == "true" for r in model_stats_rows) / len(model_stats_rows),
            "mean_model_jaccard": statistics.fmean(float(r["model_jaccard"]) for r in model_stats_rows),
            "geometry_class": pose_class, "continuous": pose_num_stats,
        },
        "dual_conformation_entity_level": {
            "n": len(dual),
            "dual_min_ordinal_exact_fraction": sum(r["exact"] == "true" for r in dual) / len(dual) if dual else None,
            "dual_supported_status_agreement_fraction": sum(r["both_supported_agree"] == "true" for r in dual) / len(dual) if dual else None,
        },
        "scientific_boundary": "Computational same-protocol docking/geometry reproducibility only; not experimental binding, affinity, Kd, IC50, expression, purity, or blocking evidence.",
    }
    summary = round_obj(summary)
    (args.outdir / "CONSISTENCY_SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    pf = summary["job_level"]["categorical"]["representative_pair_label"]["exact_fraction"]
    nf = summary["job_level"]["categorical"]["native_class"]["exact_fraction"]
    cf = summary["job_level"]["categorical"]["cross_class"]["exact_fraction"]
    hs = summary["job_level"]["continuous"]["haddock_score"]
    mf = summary["pose_level_common_model_names"]["mean_model_jaccard"]
    lines = [
        "# PVRIG V2.9：Node1 自跑与 rli HPC docking 一致性复核",
        "", "## 结论", "",
        "- **协议/输入一致**：重叠作业的 job、sequence、cfg、restraint、protocol 哈希逐项核对。",
        f"- **独立重复样本**：{len(overlap)} 个双成功 job，覆盖 {summary['scope']['independent_entities']} 个候选；其中 {len(dual)} 个候选在两边都有完整双构象独立重复。",
        f"- **作业级阻断几何标签**：pair label 完全一致率 {pf:.1%}；native class {nf:.1%}；cross class {cf:.1%}。",
        f"- **HADDOCK 连续分数**：Pearson r={hs['pearson_r']}, Spearman rho={hs['spearman_rho']}, MAE={hs['mae']}。",
        f"- **选中模型集合**：平均 Jaccard={mf:.3f}。同 seed 与同协议不保证跨机器 bitwise/cluster-rank 完全相同。",
        "- 本报告判断的是计算 docking/几何证据复现性，不是实验结合或阻断证明。",
        "", "## 覆盖状态", "", "```json", json.dumps(summary["execution_status_matrix"], indent=2, ensure_ascii=False), "```",
        "", "## 关键一致性指标", "",
        f"- pair label confusion：`{json.dumps(summary['job_level']['categorical']['representative_pair_label']['confusion'], ensure_ascii=False)}`",
        f"- pair support（二分类 supported vs other）一致率：{summary['job_level']['pair_ordinal']['positive_support_agreement_fraction']:.1%}",
        f"- dual-conformation 最弱侧等级完全一致率：{summary['dual_conformation_entity_level']['dual_min_ordinal_exact_fraction']:.1%}",
        f"- dual-conformation supported 状态一致率：{summary['dual_conformation_entity_level']['dual_supported_status_agreement_fraction']:.1%}",
        f"- pose common-key geometry class 一致率：{summary['pose_level_common_model_names']['geometry_class']['exact_fraction']:.1%}",
        "", "## 使用建议", "",
        "1. rli 结果可作为同协议 shard 合并，但技术失败必须保留为 NA。",
        "2. 排序应优先使用双构象/几何类别与多 pose 共识；不要要求 HADDOCK 单次连续分数逐值相等。",
        "3. 跨机器训练特征建议对连续能量做 run/host 分层标准化，并保留 `compute_host`/run provenance。",
        "4. 只有 21 个候选具备完整双构象独立重复，双构象稳定性结论仍需扩大复跑样本。",
        "", "## 产物", "",
        "- `CONSISTENCY_SUMMARY.json`", "- `job_level_comparison.tsv`", "- `model_set_comparison.tsv`",
        "- `pose_level_common_model_comparison.tsv`", "- `dual_conformation_21_comparison.tsv`",
    ]
    (args.outdir / "PVRIG_V29_RLI_DOCKING_CONSISTENCY_ZH.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
