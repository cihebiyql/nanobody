#!/usr/bin/env python3
"""Build a deterministic, provenance-rich 100k VHH exploration pool.

The builder imports only RFantibody rows explicitly designated as unused
global/reserve candidates and fills each selected parent to exactly 1,000 rows
with transparent sequence-level proposal methods. It never labels profile
sampling as AntiFold, ProteinMPNN, RFantibody, or fixed-pose optimization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


AA = "ACDEFGHIKLMNPQRSTVWY"
AA_SET = set(AA)
HYDROPHOBIC = set("AILMFWYV")
CLAIM = (
    "Computational candidate generation and prospective Docking-teacher allocation only; "
    "not binding, affinity, experimental blocking, expression, purity, or Docking Gold."
)
METHODS = (
    "NATURAL_CDR_DONOR_REDESIGN",
    "CONSERVATIVE_PROFILE_LOCAL_REDESIGN",
    "DE_NOVO_CDR_EXPLORATION",
    "FIXED_FRAMEWORK_CDR_PERTURBATION",
)
PATCHES = ("A_CENTER", "B_LOWER", "C_CROSS")
MODES = ("H3", "H1H3", "H1H2H3")
REGION_ALPHABET = "ADEFGHIKLMNPQRSTVWY"  # no C: preserve the two framework cysteines
PATCH_WEIGHTS = {
    "A_CENTER": "STNQYFWGDERKAPVILMH",
    "B_LOWER": "YFWSTRNQDEKRGPAVILM",
    "C_CROSS": "GSTNQDEKRYFWAPVILMH",
}


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def stable_rng(seed: int, *parts: object) -> random.Random:
    digest = sha_text("\x1f".join([str(seed), *(str(x) for x in parts)]))
    return random.Random(int(digest[:16], 16))


def locate_regions(sequence: str, cdr1: str, cdr2: str, cdr3: str) -> dict[str, tuple[int, int]]:
    positions: dict[str, tuple[int, int]] = {}
    cursor = 0
    for name, cdr in (("cdr1", cdr1), ("cdr2", cdr2), ("cdr3", cdr3)):
        start = sequence.find(cdr, cursor)
        require(start >= 0, f"cdr_not_found:{name}:{cdr}:{sequence}")
        positions[name] = (start, start + len(cdr))
        cursor = start + len(cdr)
    return positions


def resolve_cdrs(sequence: str, cdr1: str, cdr2: str, cdr3: str) -> tuple[str, str, str]:
    def literal_or_best(query: str, lo: int, hi: int, label: str) -> str:
        if query in sequence:
            return query
        best = (-1.0, "")
        hi = min(len(sequence), hi)
        for start in range(lo, max(lo, hi - len(query) + 1)):
            value = sequence[start : start + len(query)]
            if len(value) != len(query):
                continue
            identity = sum(a == b for a, b in zip(value, query)) / len(query)
            if identity > best[0]:
                best = (identity, value)
        require(best[0] >= 0.5, f"{label}_literal_recovery_failed:{query}:{sequence}")
        return best[1]

    cdr1 = literal_or_best(cdr1, 18, 55, "cdr1")
    cdr2 = literal_or_best(cdr2, 40, 90, "cdr2")
    if cdr3 not in sequence:
        best_tail = (-1.0, "")
        for start in range(75, max(75, len(sequence) - len(cdr3) - 5)):
            value = sequence[start : start + len(cdr3)]
            if len(value) != len(cdr3):
                continue
            identity = sum(a == b for a, b in zip(value, cdr3)) / len(cdr3)
            if identity > best_tail[0]:
                best_tail = (identity, value)
        if best_tail[0] >= 0.45:
            cdr3 = best_tail[1]
            return cdr1, cdr2, cdr3
        # Some legacy ANARCI CSV exports serialize insertion positions in a
        # different order. Recover the literal CDR3 from the conserved terminal
        # Cys-to-FR4-W motif while preserving the source sequence unchanged.
        tail_cys = sequence.rfind("C", 0, max(0, len(sequence) - 8))
        motif_candidates = [sequence.rfind(motif) for motif in ("WGQG", "WGAG", "WGRG", "WGTG", "WGKG", "WGQ", "WGA", "WGR", "WGT", "WGK")]
        fr4_start = max(motif_candidates)
        if fr4_start < 0:
            generic_w = [
                i for i, aa in enumerate(sequence)
                if aa == "W" and i > tail_cys + 3 and len(sequence) - i <= 25 and "G" in sequence[i + 1 : i + 4]
            ]
            fr4_start = max(generic_w) if generic_w else -1
        if fr4_start < 0:
            core = max(sequence.rfind("GQG"), sequence.rfind("GAG"))
            fr4_start = core - 1 if core > 0 else -1
        cys = sequence.rfind("C", 0, fr4_start)
        require(fr4_start > 0 and cys >= 0 and fr4_start - cys - 1 >= 3, f"cdr3_anchor_failed:{sequence}")
        cdr3 = sequence[cys + 1 : fr4_start]
    return cdr1, cdr2, cdr3


def replace_regions(sequence: str, positions: dict[str, tuple[int, int]], replacements: dict[str, str]) -> str:
    pieces: list[str] = []
    cursor = 0
    for name in ("cdr1", "cdr2", "cdr3"):
        start, end = positions[name]
        pieces.append(sequence[cursor:start])
        pieces.append(replacements.get(name, sequence[start:end]))
        cursor = end
    pieces.append(sequence[cursor:])
    return "".join(pieces)


def mutate_region(source: str, rng: random.Random, patch: str, minimum: int, maximum: int) -> str:
    chars = list(source)
    k = min(len(chars), max(minimum, min(maximum, 1 + rng.randrange(maximum))))
    positions = rng.sample(range(len(chars)), k=k)
    alphabet = PATCH_WEIGHTS[patch]
    for pos in positions:
        choices = [aa for aa in alphabet if aa != chars[pos]]
        chars[pos] = rng.choice(choices)
    return "".join(chars)


def sample_region(length: int, rng: random.Random, patch: str) -> str:
    alphabet = PATCH_WEIGHTS[patch]
    for _ in range(100):
        value = "".join(rng.choice(alphabet) for _ in range(length))
        if max(Counter(value).values()) / len(value) <= 0.28 and not any(
            set(value[i : i + 5]) <= HYDROPHOBIC for i in range(max(0, len(value) - 4))
        ):
            return value
    return value


def design_candidate(parent: dict[str, object], donors: list[dict[str, str]], method: str, patch: str, mode: str, index: int, seed: int) -> dict[str, str]:
    rng = stable_rng(seed, parent["sequence_id"], method, patch, mode, index)
    source = str(parent["sequence_aa"])
    before = {name: str(parent[name]) for name in ("cdr1", "cdr2", "cdr3")}
    replacements = dict(before)
    designed = {"H3": ("cdr3",), "H1H3": ("cdr1", "cdr3"), "H1H2H3": ("cdr1", "cdr2", "cdr3")}[mode]

    if method == "NATURAL_CDR_DONOR_REDESIGN":
        for region in designed:
            source_length = len(before[region])
            compatible = [d for d in donors if abs(len(d[region]) - source_length) <= (3 if region == "cdr3" else 1)]
            donor = rng.choice(compatible or donors)
            replacements[region] = donor[region]
    elif method == "CONSERVATIVE_PROFILE_LOCAL_REDESIGN":
        for region in designed:
            replacements[region] = mutate_region(before[region], rng, patch, 2, 5 if region == "cdr3" else 3)
    elif method == "DE_NOVO_CDR_EXPLORATION":
        for region in designed:
            if region == "cdr3":
                length = rng.randint(10, 20)
            else:
                length = len(before[region])
            replacements[region] = sample_region(length, rng, patch)
    elif method == "FIXED_FRAMEWORK_CDR_PERTURBATION":
        for region in designed:
            replacements[region] = mutate_region(before[region], rng, patch, 1, 2)
    else:
        raise RuntimeError(f"unsupported_method:{method}")

    positions = locate_regions(source, before["cdr1"], before["cdr2"], before["cdr3"])
    sequence = replace_regions(source, positions, replacements)
    if sequence == source:
        fallback_region = designed[-1]
        replacements[fallback_region] = mutate_region(before[fallback_region], rng, patch, 1, 1)
        sequence = replace_regions(source, positions, replacements)
    require(sequence != source, f"no_design_edit:{parent['sequence_id']}:{method}:{mode}:{index}")
    return {
        "sequence": sequence,
        "cdr1_before": before["cdr1"], "cdr2_before": before["cdr2"], "cdr3_before": before["cdr3"],
        "cdr1_after": replacements["cdr1"], "cdr2_after": replacements["cdr2"], "cdr3_after": replacements["cdr3"],
        "designed_regions": {"H3": "H3", "H1H3": "H1,H3", "H1H2H3": "H1,H2,H3"}[mode],
    }


def fast_qc(sequence: str, cdr1: str, cdr2: str, cdr3: str, contract: dict[str, object]) -> tuple[bool, str, dict[str, object]]:
    rules = contract["minimum_admission"]
    reasons: list[str] = []
    if not sequence or set(sequence) - AA_SET: reasons.append("nonstandard_amino_acid")
    if not int(rules["minimum_length"]) <= len(sequence) <= int(rules["maximum_length"]): reasons.append("length")
    cysteine_count = sequence.count("C")
    if cysteine_count < int(rules["minimum_cysteine_count"]) or cysteine_count % 2: reasons.append("cysteine_count")
    low_complexity = max(Counter(sequence).values()) / len(sequence)
    if low_complexity > float(rules["maximum_low_complexity_fraction"]): reasons.append("low_complexity")
    hydrophobic_fraction = sum(x in HYDROPHOBIC for x in sequence) / len(sequence)
    if hydrophobic_fraction > float(rules["maximum_hydrophobic_fraction"]): reasons.append("hydrophobic_fraction")
    cdr3_hydrophobic = sum(x in HYDROPHOBIC for x in cdr3) / len(cdr3)
    if cdr3_hydrophobic > float(rules["maximum_cdr3_hydrophobic_fraction"]): reasons.append("cdr3_hydrophobic")
    run = int(rules["forbid_hydrophobic_run_length"])
    if any(set(sequence[i : i + run]) <= HYDROPHOBIC for i in range(len(sequence) - run + 1)): reasons.append("hydrophobic_run")
    if any(re.search(r"N[^P][ST]", cdr) for cdr in (cdr1, cdr2, cdr3)): reasons.append("cdr_n_glycosylation")
    return not reasons, ";".join(reasons), {
        "sequence_length": len(sequence), "cysteine_count": cysteine_count,
        "low_complexity_fraction": low_complexity, "hydrophobic_fraction": hydrophobic_fraction,
        "cdr3_hydrophobic_fraction": cdr3_hydrophobic,
    }


def aligned_identity(a: str, b: str) -> float:
    # Global Needleman-Wunsch, identity over aligned non-double-gap columns.
    n, m = len(a), len(b)
    score = [[0] * (m + 1) for _ in range(n + 1)]
    trace = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1): score[i][0], trace[i][0] = -i, 1
    for j in range(1, m + 1): score[0][j], trace[0][j] = -j, 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            values = (score[i - 1][j - 1] + (1 if a[i - 1] == b[j - 1] else 0), score[i - 1][j] - 1, score[i][j - 1] - 1)
            best = max(range(3), key=lambda k: values[k])
            score[i][j], trace[i][j] = values[best], best
    i, j, matches, columns = n, m, 0, 0
    while i or j:
        step = trace[i][j]
        if i and j and step == 0:
            matches += int(a[i - 1] == b[j - 1]); columns += 1; i -= 1; j -= 1
        elif i and (j == 0 or step == 1): columns += 1; i -= 1
        else: columns += 1; j -= 1
    return matches / columns if columns else 0.0


def max_positive_identity(cdrs: tuple[str, str, str], positives: list[tuple[str, str, str]]) -> tuple[float, str]:
    best = (-1.0, "")
    for pidx, reference in enumerate(positives):
        for ridx, (query, ref) in enumerate(zip(cdrs, reference), 1):
            value = aligned_identity(query, ref)
            if value > best[0]: best = (value, f"positive_{pidx + 1}:cdr{ridx}")
    return best


def choose_parents(top: pd.DataFrame, rf: pd.DataFrame, old_clusters: set[str], count: int) -> pd.DataFrame:
    rf_clusters = set(rf["parent_framework_cluster"])
    chosen_clusters = set(old_clusters) | rf_clusters
    require(chosen_clusters <= set(top["cluster_id"]), "required_parent_missing_from_top200")
    ordered = top.sort_values(["score_v1_1", "cluster_id"], ascending=[False, True])
    for cluster in ordered["cluster_id"]:
        if len(chosen_clusters) >= count: break
        chosen_clusters.add(cluster)
    require(len(chosen_clusters) == count, f"parent_count:{len(chosen_clusters)}")
    result = top[top["cluster_id"].isin(chosen_clusters)].copy()
    result["parent_framework_cluster"] = result["cluster_id"]
    result["is_existing_open3388_parent"] = result["cluster_id"].isin(old_clusters)
    result["is_rfantibody_source_parent"] = result["cluster_id"].isin(rf_clusters)
    result["parent_selection_hash"] = result.apply(lambda r: sha_text(f"pvrig-v2.9-parent|{r['cluster_id']}|{r['sequence_id']}"), axis=1)
    return result.sort_values("parent_selection_hash").reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--top200", type=Path, required=True)
    ap.add_argument("--rf-raw", type=Path, required=True)
    ap.add_argument("--rf-lineage", type=Path, required=True)
    ap.add_argument("--open3388", type=Path, required=True)
    ap.add_argument("--positive-cdr", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    contract = json.loads(args.contract.read_text())
    seed = int(contract["random_seed"])
    top = pd.read_csv(args.top200).fillna("")
    raw = pd.read_csv(args.rf_raw).fillna("")
    lineage = pd.read_csv(args.rf_lineage, sep="\t").fillna("")
    teacher = pd.read_csv(args.open3388, sep="\t").fillna("")
    positive = pd.read_csv(args.positive_cdr).fillna("")
    positive_cdrs = [
        tuple(str(row[x]) for x in ("cdr1", "cdr2", "cdr3"))
        for _, row in positive.iterrows()
        if row.get("numbering_status", "") == "anarci_success"
        and str(row.get("chain", "")).upper() in {"VH", "VHH"}
    ]
    require(bool(positive_cdrs), "no_positive_heavy_cdrs")
    for idx, row in top.iterrows():
        cdr1, cdr2, cdr3 = resolve_cdrs(str(row["sequence_aa"]), str(row["cdr1"]), str(row["cdr2"]), str(row["cdr3"]))
        top.loc[idx, ["cdr1", "cdr2", "cdr3"]] = [cdr1, cdr2, cdr3]

    allowed_roles = {"GLOBAL_POOL_OTHER", "RESERVE2_PARENT"}
    lineage = lineage[lineage["census_role"].isin(allowed_roles)].copy()
    raw = raw.merge(lineage[["candidate_id", "census_role"]], on="candidate_id", how="inner", validate="one_to_one")
    excluded_hashes = set(teacher["sequence_sha256"])
    raw = raw[~raw["sequence_sha256"].isin(excluded_hashes)].copy()
    raw = raw.sort_values("candidate_id").drop_duplicates("sequence_sha256")

    parent_count = int(contract["exploration_pool"]["parent_count"])
    parents = choose_parents(top, raw, set(teacher["parent_framework_cluster"]), parent_count)
    selected_clusters = set(parents["parent_framework_cluster"])
    raw = raw[raw["parent_framework_cluster"].isin(selected_clusters)].copy()
    parent_by_cluster = {r["parent_framework_cluster"]: r for _, r in parents.iterrows()}
    donors = [{x: str(r[x]) for x in ("cdr1", "cdr2", "cdr3")} for _, r in top.iterrows()]

    rows: list[dict[str, object]] = []
    seen_hashes = set(excluded_hashes)
    for _, r in raw.iterrows():
        sequence = str(r["vhh_sequence"]).strip().upper()
        digest = sha_text(sequence)
        if digest in seen_hashes: continue
        seen_hashes.add(digest)
        qc_pass, qc_reason, metrics = fast_qc(sequence, str(r["cdr1_after"]), str(r["cdr2_after"]), str(r["cdr3_after"]), contract)
        identity, identity_detail = max_positive_identity((str(r["cdr1_after"]), str(r["cdr2_after"]), str(r["cdr3_after"])), positive_cdrs)
        rows.append({
            "candidate_id": f"V29_RF__{r['candidate_id']}", "sequence": sequence, "sequence_sha256": digest,
            "parent_id": r["parent_id"], "parent_sequence": r["parent_sequence"],
            "parent_sequence_sha256": r["parent_sequence_sha256"], "parent_framework_cluster": r["parent_framework_cluster"],
            "parent_is_existing_open3388": str(r["parent_framework_cluster"] in set(teacher["parent_framework_cluster"])).lower(),
            "design_method": "RFANTIBODY_RFDIFFUSION_PROTEINMPNN", "generator_name": "RFantibody_RFdiffusion_ProteinMPNN",
            "generator_version": "pvrig_teacher_formal_v1_20260712", "design_seed": f"B{int(r['backbone_index']):02d}_M{int(r['mpnn_index']):02d}",
            "generation_batch": "RFV1_UNUSED_GLOBAL_OR_RESERVE", "target_patch": r["target_patch_id"], "design_mode": r["design_mode"],
            "designed_regions": r["designed_regions"], "cdr1_before": r["cdr1_before"], "cdr2_before": r["cdr2_before"], "cdr3_before": r["cdr3_before"],
            "cdr1_after": r["cdr1_after"], "cdr2_after": r["cdr2_after"], "cdr3_after": r["cdr3_after"],
            "source_candidate_id": r["candidate_id"], "source_pdb": r["source_pdb"], "source_pdb_sha256": r["source_pdb_sha256"],
            "fast_qc_pass": str(qc_pass).lower(), "fast_qc_reason": qc_reason,
            "max_positive_cdr_identity": identity, "max_positive_cdr_identity_detail": identity_detail,
            "positive_cdr_hard_gate_pass": str(identity < float(contract["minimum_admission"]["positive_cdr_hard_fail_identity"])).lower(),
            "positive_cdr_formal75_pass": str(identity < float(contract["minimum_admission"]["formal_panel_max_positive_cdr_identity_exclusive"])).lower(),
            **metrics, "claim_boundary": CLAIM,
        })

    by_parent = Counter(str(r["parent_framework_cluster"]) for r in rows)
    targets = int(contract["exploration_pool"]["rows_per_parent"])
    method_cycle = (
        ["NATURAL_CDR_DONOR_REDESIGN"] * 50
        + ["CONSERVATIVE_PROFILE_LOCAL_REDESIGN"] * 30
        + ["DE_NOVO_CDR_EXPLORATION"] * 15
        + ["FIXED_FRAMEWORK_CDR_PERTURBATION"] * 5
    )
    for cluster in sorted(selected_clusters):
        parent = parent_by_cluster[cluster]
        index = 0
        while by_parent[cluster] < targets:
            method = method_cycle[index % len(method_cycle)]
            patch = PATCHES[(index // len(method_cycle) + index) % 3]
            mode = MODES[(index // 3 + index) % 3]
            proposal = design_candidate(parent, donors, method, patch, mode, index, seed)
            sequence = proposal["sequence"]
            digest = sha_text(sequence)
            index += 1
            if digest in seen_hashes: continue
            qc_pass, qc_reason, metrics = fast_qc(sequence, proposal["cdr1_after"], proposal["cdr2_after"], proposal["cdr3_after"], contract)
            identity, identity_detail = max_positive_identity((proposal["cdr1_after"], proposal["cdr2_after"], proposal["cdr3_after"]), positive_cdrs)
            seen_hashes.add(digest)
            rows.append({
                "candidate_id": f"V29_GEN__{cluster}__{sha_text(f'{method}|{patch}|{mode}|{index}|{digest}')[:16].upper()}",
                "sequence": sequence, "sequence_sha256": digest,
                "parent_id": parent["sequence_id"], "parent_sequence": parent["sequence_aa"], "parent_sequence_sha256": sha_text(str(parent["sequence_aa"])),
                "parent_framework_cluster": cluster, "parent_is_existing_open3388": str(bool(parent["is_existing_open3388_parent"])).lower(),
                "design_method": method, "generator_name": "pvrig_v2_9_deterministic_sequence_proposal_builder",
                "generator_version": "v1", "design_seed": sha_text(f"{seed}|{cluster}|{method}|{patch}|{mode}|{index}")[:16],
                "generation_batch": "V29_PROFILE_GENERATION_V1", "target_patch": patch, "design_mode": mode,
                **proposal, "source_candidate_id": "", "source_pdb": "", "source_pdb_sha256": "",
                "fast_qc_pass": str(qc_pass).lower(), "fast_qc_reason": qc_reason,
                "max_positive_cdr_identity": identity, "max_positive_cdr_identity_detail": identity_detail,
                "positive_cdr_hard_gate_pass": str(identity < float(contract["minimum_admission"]["positive_cdr_hard_fail_identity"])).lower(),
                "positive_cdr_formal75_pass": str(identity < float(contract["minimum_admission"]["formal_panel_max_positive_cdr_identity_exclusive"])).lower(),
                **metrics, "claim_boundary": CLAIM,
            })
            by_parent[cluster] += 1

    pool = pd.DataFrame(rows)
    require(len(pool) == int(contract["exploration_pool"]["total_rows"]), f"pool_rows:{len(pool)}")
    require(pool["sequence_sha256"].nunique() == len(pool), "pool_sequence_not_unique")
    require(set(pool.groupby("parent_framework_cluster").size()) == {targets}, "rows_per_parent_not_exact")
    require(pool["parent_framework_cluster"].nunique() == parent_count, "parent_count_not_exact")
    require((~pool["sequence_sha256"].isin(excluded_hashes)).all(), "open3388_overlap")

    pool.to_csv(args.output_dir / "exploration_pool100k.tsv", sep="\t", index=False)
    with (args.output_dir / "exploration_pool100k.fasta").open("w") as handle:
        for r in pool.itertuples(): handle.write(f">{r.candidate_id}\n{r.sequence}\n")
    parents.to_csv(args.output_dir / "parent100_manifest.tsv", sep="\t", index=False)
    summary = {
        "schema_version": "pvrig_v2_9_exploration_pool100k_summary_v1",
        "status": "PASS_EXACT_100K_EXPLORATION_POOL",
        "rows": len(pool), "unique_sequences": int(pool.sequence_sha256.nunique()),
        "parent_count": int(pool.parent_framework_cluster.nunique()),
        "new_parent_count": int(parents[~parents.is_existing_open3388_parent].shape[0]),
        "new_parent_fraction": float((~parents.is_existing_open3388_parent).mean()),
        "method_counts": pool.design_method.value_counts().sort_index().to_dict(),
        "patch_counts": pool.target_patch.value_counts().sort_index().to_dict(),
        "mode_counts": pool.design_mode.value_counts().sort_index().to_dict(),
        "fast_qc_pass": int((pool.fast_qc_pass == "true").sum()),
        "formal75_pass": int((pool.positive_cdr_formal75_pass == "true").sum()),
        "excluded_open3388_hash_count": len(excluded_hashes), "claim_boundary": CLAIM,
    }
    (args.output_dir / "exploration_pool100k_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
