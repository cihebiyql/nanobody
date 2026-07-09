#!/usr/bin/env python3
"""Build Phase 0 normalized indexes for the PVRIG VHH-antigen small model."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

SAMPLE_COLUMNS = [
    "sample_id",
    "source_dataset",
    "source_file",
    "split",
    "record_index",
    "task_family",
    "vhh_seq",
    "antibody_heavy_seq",
    "antibody_light_seq",
    "cdr1_seq",
    "cdr2_seq",
    "cdr3_seq",
    "cdr1_span_0based",
    "cdr2_span_0based",
    "cdr3_span_0based",
    "vhh_paratope_mask",
    "antigen_name",
    "antigen_seq",
    "antigen_epitope_mask",
    "epitope_residues_raw",
    "pdb_id",
    "structure_path",
    "antibody_chain_ids",
    "antigen_chain_ids",
    "binding_label_type",
    "binding_label_value",
    "binding_label_unit",
    "binding_label_method",
    "quality_flag",
    "notes",
]


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value)
    if text.lower() == "nan":
        return ""
    return text.strip()


def numeric(value: Any) -> str:
    text = clean(value)
    if not text or text.lower() in {"unknown", "none", "na", "n/a"}:
        return ""
    try:
        return str(float(text))
    except ValueError:
        return ""


def span_0based(seq: str, sub: str) -> str:
    seq = clean(seq)
    sub = clean(sub)
    if not seq or not sub:
        return ""
    start = seq.find(sub)
    if start < 0:
        return ""
    return f"{start}:{start + len(sub)}"


def row_template() -> dict[str, str]:
    return {col: "" for col in SAMPLE_COLUMNS}


def write_jsonl_gz(rows: list[dict[str, str]], out_path: Path) -> None:
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_fasta_sequence(path: Path) -> str:
    seq_parts: list[str] = []
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(">"):
            continue
        seq_parts.append(line.strip())
    return "".join(seq_parts)


def add_zym_paratope(root: Path, rows: list[dict[str, str]], stats: list[dict[str, Any]]) -> None:
    base = root / "datasets/49_hf_broad_antibody/ZYMScott_Paratope"
    for split in ["train", "val", "test"]:
        path = base / f"{split}.csv"
        if not path.exists():
            stats.append({"source_dataset": "ZYMScott_Paratope", "split": split, "status": "missing", "rows": 0})
            continue
        df = pd.read_csv(path)
        ok_para = 0
        ok_epi = 0
        with_aff = 0
        for i, rec in df.iterrows():
            vhh = clean(rec.get("seq_nanobody"))
            para = clean(rec.get("paratope"))
            ag = clean(rec.get("seq_antigen"))
            epi = clean(rec.get("epitope"))
            flags = []
            if len(vhh) == len(para):
                ok_para += 1
            else:
                flags.append("bad_paratope_mask_length")
            if len(ag) == len(epi):
                ok_epi += 1
            else:
                flags.append("bad_epitope_mask_length")
            aff = numeric(rec.get("affinity"))
            if aff:
                with_aff += 1
            row = row_template()
            row.update(
                sample_id=f"zympara_{split}_{i:06d}",
                source_dataset="ZYMScott_Paratope",
                source_file=str(path.relative_to(root)),
                split=split,
                record_index=str(i),
                task_family="vhh_antigen_site_masks",
                vhh_seq=vhh,
                vhh_paratope_mask=para,
                antigen_seq=ag,
                antigen_epitope_mask=epi,
                pdb_id=clean(rec.get("pdb")).lower(),
                antibody_chain_ids=clean(rec.get("nanobody_chain")),
                antigen_chain_ids=clean(rec.get("antigen_chain")),
                binding_label_type="affinity_raw" if aff else "",
                binding_label_value=aff,
                binding_label_unit="raw_source_value" if aff else "",
                binding_label_method=clean(rec.get("affinity_method")),
                quality_flag=";".join(flags) if flags else "ok",
                notes="direct paratope and epitope mask supervision",
            )
            rows.append(row)
        stats.append(
            {
                "source_dataset": "ZYMScott_Paratope",
                "split": split,
                "status": "ok",
                "rows": len(df),
                "mask_len_ok_vhh": ok_para,
                "mask_len_ok_antigen": ok_epi,
                "with_binding_label": with_aff,
                "unique_pdb": df["pdb"].nunique() if "pdb" in df else "",
            }
        )


def add_zym_vhh_affinity(root: Path, rows: list[dict[str, str]], stats: list[dict[str, Any]], dataset_name: str) -> None:
    base = root / f"datasets/49_hf_broad_antibody/{dataset_name}"
    for split in ["train", "val", "test"]:
        path = base / f"{split}.csv"
        if not path.exists():
            stats.append({"source_dataset": dataset_name, "split": split, "status": "missing", "rows": 0})
            continue
        df = pd.read_csv(path)
        span_ok = 0
        for i, rec in df.iterrows():
            seq = clean(rec.get("seq"))
            cdr1 = clean(rec.get("CDR1"))
            cdr2 = clean(rec.get("CDR2"))
            cdr3 = clean(rec.get("CDR3"))
            spans = [span_0based(seq, cdr1), span_0based(seq, cdr2), span_0based(seq, cdr3)]
            flags = []
            if all(spans):
                span_ok += 1
            else:
                flags.append("cdr_span_not_found_by_substring")
            row = row_template()
            row.update(
                sample_id=f"{dataset_name.replace('-', '_')}_{split}_{i:06d}",
                source_dataset=dataset_name,
                source_file=str(path.relative_to(root)),
                split=split,
                record_index=str(i),
                task_family="vhh_sequence_binding_score",
                vhh_seq=seq,
                cdr1_seq=cdr1,
                cdr2_seq=cdr2,
                cdr3_seq=cdr3,
                cdr1_span_0based=spans[0],
                cdr2_span_0based=spans[1],
                cdr3_span_0based=spans[2],
                binding_label_type="zym_vhh_score",
                binding_label_value=numeric(rec.get("score")),
                binding_label_unit="raw_score",
                quality_flag=";".join(flags) if flags else "ok",
                notes=f"VHH-only score row; antigen context is not present in {dataset_name}",
            )
            if "cluster_id" in df.columns:
                row["notes"] += f"; cluster_id={clean(rec.get('cluster_id'))}"
            rows.append(row)
        stats.append(
            {
                "source_dataset": dataset_name,
                "split": split,
                "status": "ok",
                "rows": len(df),
                "cdr_spans_found": span_ok,
                "with_binding_label": pd.to_numeric(df.get("score"), errors="coerce").notna().sum(),
                "unique_vhh_seq": df["seq"].nunique() if "seq" in df else "",
            }
        )


def add_sdab_db(root: Path, rows: list[dict[str, str]], stats: list[dict[str, Any]]) -> None:
    path = root / "datasets/36_sdab_db/sdab_db_affinity_rows.csv"
    if not path.exists():
        stats.append({"source_dataset": "sdAb-DB", "split": "all", "status": "missing", "rows": 0})
        return
    df = pd.read_csv(path)
    kd_values = pd.to_numeric(df.get("kd_nm"), errors="coerce")
    for i, rec in df.iterrows():
        kd = numeric(rec.get("kd_nm"))
        flags = []
        if not kd:
            flags.append("missing_or_unknown_kd")
        if not clean(rec.get("aa_sequence")):
            flags.append("missing_sequence")
        row = row_template()
        row.update(
            sample_id=f"sdabdb_all_{i:06d}",
            source_dataset="sdAb-DB",
            source_file=str(path.relative_to(root)),
            split="all",
            record_index=str(i),
            task_family="sdab_antigen_affinity",
            vhh_seq=clean(rec.get("aa_sequence")),
            antigen_name=clean(rec.get("antigen")) or clean(rec.get("primary_target_antigen")),
            binding_label_type="kd",
            binding_label_value=kd,
            binding_label_unit="nM" if kd else "",
            quality_flag=";".join(flags) if flags else "ok",
            notes=f"sdab_id={clean(rec.get('sdab_id'))}; doi={clean(rec.get('doi'))}; antigen sequence must be resolved separately",
        )
        rows.append(row)
    stats.append(
        {
            "source_dataset": "sdAb-DB",
            "split": "all",
            "status": "ok",
            "rows": len(df),
            "known_kd_nm": int(kd_values.notna().sum()),
            "unique_vhh_seq": df["aa_sequence"].nunique() if "aa_sequence" in df else "",
            "unique_antigen_name": df["antigen"].nunique() if "antigen" in df else "",
        }
    )


def add_silicobio_sabdab(root: Path, rows: list[dict[str, str]], stats: list[dict[str, Any]]) -> None:
    path = root / "datasets/51_hf_gap_fill/silicobio_peleke_antibody-antigen_sabdab/sabdab_training_dataset.csv"
    if not path.exists():
        stats.append({"source_dataset": "silicobio_sabdab_training", "split": "all", "status": "missing", "rows": 0})
        return
    df = pd.read_csv(path)
    nonempty_epitope = 0
    for i, rec in df.iterrows():
        epi = clean(rec.get("epitope_residues"))
        if epi:
            nonempty_epitope += 1
        row = row_template()
        row.update(
            sample_id=f"silicobio_sabdab_all_{i:06d}",
            source_dataset="silicobio_sabdab_training",
            source_file=str(path.relative_to(root)),
            split="all",
            record_index=str(i),
            task_family="full_antibody_antigen_epitope",
            antibody_heavy_seq=clean(rec.get("h_chain_seq")),
            antibody_light_seq=clean(rec.get("l_chain_seq")),
            antigen_seq=clean(rec.get("antigen_seqs")),
            epitope_residues_raw=epi,
            antigen_epitope_mask=clean(rec.get("highlighted_epitope_seqs")),
            pdb_id=clean(rec.get("pdb_id")).lower(),
            antibody_chain_ids="|".join([clean(rec.get("h_chain_id")), clean(rec.get("l_chain_id"))]).strip("|"),
            antigen_chain_ids=clean(rec.get("antigen_ids")),
            quality_flag="ok" if epi else "missing_epitope_residues",
            notes="full antibody-antigen epitope supervision; not VHH-only but useful for antigen epitope head",
        )
        rows.append(row)
    stats.append(
        {
            "source_dataset": "silicobio_sabdab_training",
            "split": "all",
            "status": "ok",
            "rows": len(df),
            "with_epitope_residues": nonempty_epitope,
            "unique_pdb": df["pdb_id"].nunique() if "pdb_id" in df else "",
        }
    )


def build_pvrig_target(root: Path, out_dir: Path) -> dict[str, Any]:
    hotspot_path = root / "structures/PVRIG_hotspot_set_v1.csv"
    full_seq_path = root / "datasets/00_structures/PVRIG_Q6DKI7_uniprot.fasta"
    seq = read_fasta_sequence(full_seq_path)
    hotspot = pd.read_csv(hotspot_path) if hotspot_path.exists() else pd.DataFrame()
    if not hotspot.empty:
        hotspot_out = hotspot.copy()
        hotspot_out["target_role"] = "desired_blocking_epitope_seed"
        hotspot_out.to_csv(out_dir / "pvrig_target_epitope_v0.csv", index=False)
    else:
        pd.DataFrame().to_csv(out_dir / "pvrig_target_epitope_v0.csv", index=False)

    by_pos: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for _, rec in hotspot.iterrows():
        pos = numeric(rec.get("uniprot_position"))
        if pos:
            by_pos[int(float(pos))].append(rec.to_dict())
    mask_rows = []
    for pos, aa in enumerate(seq, start=1):
        hs = by_pos.get(pos, [])
        weight = max([float(clean(h.get("priority_weight")) or 0) for h in hs], default=0.0)
        mask_rows.append(
            {
                "uniprot_accession": "Q6DKI7",
                "uniprot_position": pos,
                "aa": aa,
                "in_target_epitope": "yes" if hs else "no",
                "target_weight": weight,
                "hotspot_ids": ";".join(clean(h.get("hotspot_id")) for h in hs),
                "hotspot_classes": ";".join(clean(h.get("hotspot_class")) for h in hs),
            }
        )
    pd.DataFrame(mask_rows).to_csv(out_dir / "pvrig_full_sequence_mask_v0.csv", index=False)
    (out_dir / "pvrig_target_sequence_v0.fasta").write_text(
        f">PVRIG_HUMAN_Q6DKI7 full sequence with target mask in pvrig_full_sequence_mask_v0.csv\n{seq}\n",
        encoding="utf-8",
    )
    return {"pvrig_sequence_length": len(seq), "pvrig_hotspot_rows": len(hotspot), "pvrig_target_positions": len(by_pos)}


def build_sabdab2_single_domain_manifest(root: Path, out_dir: Path) -> dict[str, Any]:
    summary_path = root / "datasets/13_sabdab_structures/full_all/sabdab2_all_instances_summary.csv"
    archive_path = root / "datasets/13_sabdab_structures/sabdab_all_single_domain_structures.tgz"
    out_path = out_dir / "sabdab2_single_domain_structure_manifest_v0.csv"
    if not summary_path.exists() or not archive_path.exists():
        pd.DataFrame().to_csv(out_path, index=False)
        return {"sabdab2_single_domain_manifest_rows": 0, "sabdab2_single_domain_status": "missing_source"}

    summary = pd.read_csv(summary_path, low_memory=False)
    member_by_pdb: dict[str, str] = {}
    with tarfile.open(archive_path, "r:gz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            top = member.name.split("/", 1)[0]
            if top and top not in member_by_pdb:
                member_by_pdb[top] = member.name

    rows = []
    for pdb, member in sorted(member_by_pdb.items()):
        sub = summary[summary["PDB"].astype(str) == pdb]
        antigen_chains = sorted({clean(x) for x in sub.get("antigen_chain", []) if clean(x) and clean(x) != "NA"})
        h_chains = sorted({clean(x) for x in sub.get("Hchain", []) if clean(x) and clean(x) != "NA"})
        l_chains = sorted({clean(x) for x in sub.get("Lchain", []) if clean(x) and clean(x) != "NA"})
        first = sub.iloc[0].to_dict() if len(sub) else {}
        rows.append(
            {
                "pdb": pdb,
                "archive_path": str(archive_path.relative_to(root)),
                "structure_member": member,
                "instances_in_summary": len(sub),
                "has_antigen_chain_summary": "yes" if antigen_chains else "no",
                "h_chains": "|".join(h_chains),
                "l_chains": "|".join(l_chains),
                "antigen_chains": "|".join(antigen_chains),
                "antigen_type": clean(first.get("antigen_type")),
                "antigen_name": clean(first.get("antigen_name")),
                "short_header": clean(first.get("short_header")),
                "resolution": clean(first.get("resolution")),
                "method": clean(first.get("method")),
                "contact_extraction_status": "pending_no_biopython_or_gemmi_in_phase0",
            }
        )
    pd.DataFrame(rows).to_csv(out_path, index=False)
    with_antigen = sum(1 for row in rows if row["has_antigen_chain_summary"] == "yes")
    return {
        "sabdab2_single_domain_manifest_rows": len(rows),
        "sabdab2_single_domain_with_antigen_chain": with_antigen,
        "sabdab2_single_domain_status": "manifest_built_contacts_pending",
    }




def dataframe_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, rec in df.iterrows():
        vals = []
        for col in df.columns:
            val = clean(rec.get(col))
            val = val.replace("|", "\\|").replace("\n", " ")
            vals.append(val)
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_quality_report(root: Path, out_dir: Path, report_path: Path, stats: list[dict[str, Any]], extra: dict[str, Any], total_rows: int) -> None:
    stats_df = pd.DataFrame(stats)
    lines = [
        "# Phase 0 模型数据索引质量报告",
        "",
        "生成目标：为 PVRIG 方向 VHH-抗原结合小模型建立统一训练索引。",
        "",
        "## 产物",
        "",
        f"- `model_data/index_v0_samples.csv`：统一样本索引，共 {total_rows} 行。",
        "- `model_data/index_v0_samples.jsonl.gz`：同一索引的 JSONL 压缩版本。",
        "- `model_data/source_summary_v0.csv`：各数据源统计。",
        "- `model_data/pvrig_target_epitope_v0.csv`：PVRIG 目标阻断表位/热点。",
        "- `model_data/pvrig_full_sequence_mask_v0.csv`：PVRIG 全长逐残基 target mask。",
        "- `model_data/sabdab2_single_domain_structure_manifest_v0.csv`：SAbDab2 single-domain 结构 manifest；接触抽取待下一阶段。",
        "",
        "## 数据源统计",
        "",
        dataframe_to_markdown(stats_df),
        "",
        "## PVRIG / 结构统计",
        "",
    ]
    for key, value in extra.items():
        lines.append(f"- `{key}`: {value}")
    lines += [
        "",
        "## 重要限制",
        "",
        "- 当前环境没有 `pyarrow`，因此本阶段没有输出 parquet；使用 `csv` 和 `jsonl.gz` 作为稳定交换格式。",
        "- 当前环境没有 `BioPython/gemmi`，因此 SAbDab2 single-domain 结构只生成 manifest，未在本脚本中抽取 4.5 Å 接触。",
        "- `ZYMScott_vhh_affinity-score/seq` 没有 antigen 序列字段，适合作为 VHH 分数/排序监督，不应当单独解释为任意 VHH-antigen pair 的亲和力。",
        "- `sdAb-DB` 的 antigen 多数是名称而不是序列，已保留 Kd 和名称，后续需要解析 UniProt/PDB 才能用于 pair 模型。",
        "- `silicobio_sabdab_training` 多为常规 VH/VL 抗体，可用于抗原 epitope 头，但不要当成 VHH-only 主监督。",
        "",
        "## 下一步建议",
        "",
        "1. 安装或引入结构解析依赖后，从 `sabdab2_single_domain_structure_manifest_v0.csv` 抽取 VHH-antigen 4.5 Å paratope/epitope 接触。",
        "2. 用 `index_v0_samples.csv` 先训练一个 sequence-only baseline：paratope head + epitope head + ranking head。",
        "3. 对 PVRIG 推理时，把 `pvrig_full_sequence_mask_v0.csv` 作为目标 epitope overlap 约束。",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Workspace root, default current directory")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    out_dir = root / "model_data"
    report_dir = root / "reports"
    out_dir.mkdir(exist_ok=True)
    report_dir.mkdir(exist_ok=True)

    rows: list[dict[str, str]] = []
    stats: list[dict[str, Any]] = []
    add_zym_paratope(root, rows, stats)
    add_zym_vhh_affinity(root, rows, stats, "ZYMScott_vhh_affinity-score")
    add_zym_vhh_affinity(root, rows, stats, "ZYMScott_vhh_affinity-seq")
    add_sdab_db(root, rows, stats)
    add_silicobio_sabdab(root, rows, stats)

    index_df = pd.DataFrame(rows, columns=SAMPLE_COLUMNS)
    index_csv = out_dir / "index_v0_samples.csv"
    index_df.to_csv(index_csv, index=False, quoting=csv.QUOTE_MINIMAL)
    write_jsonl_gz(rows, out_dir / "index_v0_samples.jsonl.gz")
    pd.DataFrame(stats).to_csv(out_dir / "source_summary_v0.csv", index=False)

    extra: dict[str, Any] = {}
    extra.update(build_pvrig_target(root, out_dir))
    extra.update(build_sabdab2_single_domain_manifest(root, out_dir))
    write_quality_report(root, out_dir, report_dir / "model_data_quality_v0.md", stats, extra, len(index_df))

    print(json.dumps({"index_rows": len(index_df), **extra}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
