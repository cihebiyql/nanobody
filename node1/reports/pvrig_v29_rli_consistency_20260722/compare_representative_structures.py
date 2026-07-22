#!/usr/bin/env python3
"""Compare representative complex coordinates after receptor-chain alignment."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np


def read_tsv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def atom_map(path, chain, atom="CA"):
    opener = gzip.open if str(path).endswith(".gz") else open
    out = {}
    with opener(path, "rt", errors="replace") as fh:
        for line in fh:
            if not line.startswith("ATOM") or line[21:22].strip() != chain or line[12:16].strip() != atom:
                continue
            key = (line[22:26].strip(), line[26:27].strip())
            out[key] = np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])], dtype=float)
    return out


def selected_path(root, job_id, model):
    d = json.load(open(Path(root) / "results" / job_id / "job_result.json"))
    candidates = [p for p in d.get("selected_models", []) if Path(p).name == model]
    if not candidates:
        raise FileNotFoundError(f"{job_id}: {model} not in selected_models")
    p = Path(candidates[0])
    return p if p.is_absolute() else Path(root) / p


def kabsch(x, y):
    cx, cy = x.mean(axis=0), y.mean(axis=0)
    xc, yc = x - cx, y - cy
    u, _, vt = np.linalg.svd(xc.T @ yc)
    r = u @ vt
    if np.linalg.det(r) < 0:
        vt[-1, :] *= -1
        r = u @ vt
    t = cy - cx @ r
    return r, t


def rmsd(x, y):
    return float(np.sqrt(np.mean(np.sum((x - y) ** 2, axis=1))))


def quantiles(vals):
    vals = sorted(vals)
    def q(p): return vals[max(0, math.ceil(p * len(vals)) - 1)]
    return {"n": len(vals), "mean": statistics.fmean(vals), "median": statistics.median(vals), "p90": q(.90), "max": max(vals)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comparison", required=True)
    ap.add_argument("--own-root", required=True)
    ap.add_argument("--rli-root", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    rows = read_tsv(args.comparison)
    out = []
    errors = []
    for row in rows:
        jid = row["job_id"]
        try:
            op = selected_path(args.own_root, jid, "cluster_1_model_1.pdb.gz")
            rp = selected_path(args.rli_root, jid, "cluster_1_model_1.pdb.gz")
            ot, rt = atom_map(op, "T"), atom_map(rp, "T")
            oa, ra = atom_map(op, "A"), atom_map(rp, "A")
            tk = sorted(set(ot) & set(rt)); ak = sorted(set(oa) & set(ra))
            if len(tk) < 90 or len(ak) < 90:
                raise ValueError(f"insufficient CA matches T={len(tk)} A={len(ak)}")
            ox = np.vstack([ot[k] for k in tk]); ry = np.vstack([rt[k] for k in tk])
            r, t = kabsch(ox, ry)
            ox2 = ox @ r + t
            ax = np.vstack([oa[k] for k in ak]) @ r + t
            ay = np.vstack([ra[k] for k in ak])
            out.append({
                "job_id": jid, "entity_id": row["entity_id"], "conformation": row["conformation"],
                "receptor_ca_n": len(tk), "vhh_ca_n": len(ak),
                "receptor_alignment_rmsd_a": rmsd(ox2, ry),
                "vhh_ca_rmsd_after_receptor_alignment_a": rmsd(ax, ay),
                "vhh_centroid_displacement_a": float(np.linalg.norm(ax.mean(axis=0) - ay.mean(axis=0))),
                "same_complex_file_sha256": "not_tested",
            })
        except Exception as exc:
            errors.append({"job_id": jid, "error": repr(exc)})
    fields = list(out[0]) if out else ["job_id"]
    with open(outdir / "representative_structure_comparison.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n"); w.writeheader(); w.writerows(out)
    with open(outdir / "representative_structure_errors.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["job_id", "error"], delimiter="\t", lineterminator="\n"); w.writeheader(); w.writerows(errors)
    summary = {"success_n": len(out), "error_n": len(errors), "all": {}, "by_conformation": {}}
    for label, subset in [("all", out)] + [(c, [r for r in out if r["conformation"] == c]) for c in sorted({r["conformation"] for r in out})]:
        s = {
            "receptor_alignment_rmsd_a": quantiles([float(r["receptor_alignment_rmsd_a"]) for r in subset]),
            "vhh_ca_rmsd_after_receptor_alignment_a": quantiles([float(r["vhh_ca_rmsd_after_receptor_alignment_a"]) for r in subset]),
            "vhh_centroid_displacement_a": quantiles([float(r["vhh_centroid_displacement_a"]) for r in subset]),
            "vhh_rmsd_le_2a_fraction": sum(float(r["vhh_ca_rmsd_after_receptor_alignment_a"]) <= 2 for r in subset) / len(subset),
            "vhh_rmsd_le_5a_fraction": sum(float(r["vhh_ca_rmsd_after_receptor_alignment_a"]) <= 5 for r in subset) / len(subset),
            "vhh_rmsd_le_10a_fraction": sum(float(r["vhh_ca_rmsd_after_receptor_alignment_a"]) <= 10 for r in subset) / len(subset),
        }
        if label == "all": summary["all"] = s
        else: summary["by_conformation"][label] = s
    (outdir / "REPRESENTATIVE_STRUCTURE_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
