#!/usr/bin/env python3
"""Write the final Chinese audit report from authoritative V2 artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    generation = read_json(root / "data/generation_freeze_summary.json")
    rf2 = read_json(root / "rf2/results/rf2_multiseed_parse_summary.json")
    docking = read_json(root / "reports/docking_status.json")
    dual = read_json(root / "data/dual_baseline_summary.json")
    dataset = read_json(root / "data/training_dataset/dataset_manifest.json")
    qc_rows = read_tsv(root / "data/sequence_qc.tsv")
    candidate_rows = read_tsv(root / "data/candidates.tsv")
    qc_hard_fail = sum(row.get("hard_fail", "").lower() == "true" for row in qc_rows)
    qc_recommendations = Counter(row.get("recommendation", "") for row in qc_rows)
    nbb2_success = int(docking.get("nbb2_counts", {}).get("success", 0)) if isinstance(docking.get("nbb2_counts"), dict) else 0
    haddock_success = int(docking.get("haddock_counts", {}).get("success", 0)) if isinstance(docking.get("haddock_counts"), dict) else 0
    candidate_count = len(candidate_rows)
    exact_unique = len({row.get("sequence_sha256") or hashlib.sha256(row.get("sequence", "").encode()).hexdigest() for row in candidate_rows})
    seed42_outputs = int(rf2.get("seed42_output_count", 0))
    postprocess_success = int(dual.get("postprocess_success_candidates", 0))
    checks = {
        "candidate_count_1024": candidate_count == 1024,
        "candidate_exact_unique_1024": exact_unique == 1024,
        "sequence_qc_rows_1024": len(qc_rows) == 1024,
        "rf2_seed42_outputs_ge_1000": seed42_outputs >= 1000,
        "nbb2_success_ge_1000": nbb2_success >= 1000,
        "haddock_success_ge_1000": haddock_success >= 1000,
        "dual_reference_success_ge_1000": postprocess_success >= 1000,
        "training_candidate_count_1024": int(dataset.get("candidate_count", 0)) == 1024,
        "training_completed_docking_ge_1000": int(dataset.get("completed_docking_candidates", 0)) >= 1000,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    key_files = [
        root / "data/candidates.tsv",
        root / "data/rf2_metrics.tsv",
        root / "data/monomer_qc.tsv",
        root / "data/docking_runs.tsv",
        root / "data/docking_pose_baseline_metrics.tsv",
        root / "data/training_dataset/dataset_manifest.json",
    ]
    hashes = {str(path.relative_to(root)): sha256(path) for path in key_files if path.is_file()}
    audit = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checks": checks,
        "counts": {
            "candidates": candidate_count,
            "exact_unique_sequences": exact_unique,
            "sequence_qc_rows": len(qc_rows),
            "sequence_qc_hard_fail": qc_hard_fail,
            "rf2_seed42_outputs": seed42_outputs,
            "nbb2_success": nbb2_success,
            "haddock_success": haddock_success,
            "dual_reference_success": postprocess_success,
            "pose_consensus_rows": dual.get("pose_consensus_rows", 0),
            "baseline_metric_rows": dual.get("baseline_metric_rows", 0),
        },
        "hashes": hashes,
        "scientific_boundary": "computational QC and guided docking data are not experimental binding, Kd, or blockade proof",
    }
    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "final_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# PVRIG RFantibody V2：1,024 条 RF2 与 Docking 最终审计",
        "",
        f"- 审计状态：`{status}`",
        f"- 冻结候选：{candidate_count} 条；exact-unique：{exact_unique} 条",
        f"- sequence QC：{len(qc_rows)} 条；hard-fail：{qc_hard_fail} 条",
        f"- RF2 seed42 实际输出：{seed42_outputs} 条",
        f"- NanoBodyBuilder2 成功：{nbb2_success} 条",
        f"- HADDOCK3 成功候选：{haddock_success} 条",
        f"- 8X6B/9E6Y 双参考评分成功：{postprocess_success} 条",
        f"- pose consensus：{dual.get('pose_consensus_rows', 0)} 行；baseline metrics：{dual.get('baseline_metric_rows', 0)} 行",
        "",
        "## 验收门槛",
        "",
    ]
    lines.extend(f"- {'PASS' if passed else 'FAIL'} `{name}`" for name, passed in checks.items())
    lines.extend(["", "## QC 建议分布", ""])
    lines.extend(f"- `{name or 'EMPTY'}`：{count}" for name, count in sorted(qc_recommendations.items()))
    lines.extend(
        [
            "",
            "## 可训练数据",
            "",
            "- `data/training_dataset/candidates.tsv`：候选与 generation provenance。",
            "- `data/training_dataset/rf2_metrics.tsv`：seed 级 RF2 指标与失败/missingness。",
            "- `data/training_dataset/monomer_qc.tsv`：NBB2 chain-A、序列一致性与主链几何。",
            "- `data/training_dataset/docking_runs.tsv`：candidate-level HADDOCK 状态。",
            "- `data/training_dataset/docking_pose_features.tsv`：pose-level HADDOCK score 与能量。",
            "- `data/docking_pose_baseline_metrics.tsv`：8X6B/9E6Y 长表几何标签。",
            "- `data/training_dataset/splits_by_backbone.tsv`：backbone/arm/near-CDR3 family 防泄漏 split。",
            "- `data/training_dataset/failures.tsv`：失败、缺失和 deferred 记录。",
            "",
            "## 科学边界",
            "",
            "- 本批数据证明的是序列 QC、RF2 pose recovery、NBB2 单体可建模性、受约束 HADDOCK 姿势和界面遮挡代理。",
            "- 9E6Y 当前是对 8X6B-guided docking pose 的参考叠合评分，不是独立 9E6Y docking。",
            "- 任何计算分类都不能替代实验 binding、Kd 或 PVRIG-PVRL2 blockade assay。",
            "- known positives 只允许进入 calibration/holdout，不作为普通训练正例。",
            "",
            "## SHA256",
            "",
        ]
    )
    lines.extend(f"- `{name}`：`{digest}`" for name, digest in sorted(hashes.items()))
    (report_dir / "PVRIG_RFANTIBODY_DOCKING1024_V2_FINAL_ZH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
