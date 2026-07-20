#!/usr/bin/env python3
"""Score the 100k pool, freeze a quota-exact 10k panel and allocate 25k jobs.

The sequence models in this file are deliberately lightweight acquisition
proxies. Their predictions are saved as provenance and must not be described as
binding, blocking or experimental probabilities. An optional ANARCI pass table
can be supplied to fail closed before the final panel is frozen.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


AA = "ACDEFGHIKLMNPQRSTVWY"
HYDROPHOBIC = set("AVILMFWY")
AROMATIC = set("FWY")
POSITIVE = set("KRH")
NEGATIVE = set("DE")
CLAIM = (
    "Computational candidate generation and prospective Docking-teacher allocation only; "
    "not binding, affinity, experimental blocking, expression, purity, or Docking Gold."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stable_hash(seed: str, *parts: object) -> str:
    return sha_text("\x1f".join([seed, *(str(x) for x in parts)]))


class Dinic:
    def __init__(self, n: int):
        self.graph: list[list[list[int]]] = [[] for _ in range(n)]

    def add(self, left: int, right: int, capacity: int) -> list[int]:
        forward = [right, capacity, len(self.graph[right]), capacity]
        backward = [left, 0, len(self.graph[left]), 0]
        self.graph[left].append(forward); self.graph[right].append(backward)
        return forward

    def flow(self, source: int, sink: int) -> int:
        total = 0
        while True:
            level = [-1] * len(self.graph); level[source] = 0; queue = [source]
            for node in queue:
                for edge in self.graph[node]:
                    if edge[1] > 0 and level[edge[0]] < 0:
                        level[edge[0]] = level[node] + 1; queue.append(edge[0])
            if level[sink] < 0: return total
            cursor = [0] * len(self.graph)
            def send(node: int, available: int) -> int:
                if node == sink: return available
                while cursor[node] < len(self.graph[node]):
                    edge = self.graph[node][cursor[node]]
                    if edge[1] > 0 and level[edge[0]] == level[node] + 1:
                        pushed = send(edge[0], min(available, edge[1]))
                        if pushed:
                            edge[1] -= pushed; self.graph[edge[0]][edge[2]][1] += pushed
                            return pushed
                    cursor[node] += 1
                return 0
            while True:
                pushed = send(source, 10**9)
                if not pushed: break
                total += pushed


def region_features(value: str) -> list[float]:
    n = max(1, len(value))
    counts = Counter(value)
    probs = [counts[x] / n for x in AA]
    entropy = -sum(p * math.log(p + 1e-12) for p in probs) / math.log(20)
    return [
        float(len(value)), *probs,
        sum(counts[x] for x in HYDROPHOBIC) / n,
        sum(counts[x] for x in AROMATIC) / n,
        sum(counts[x] for x in POSITIVE) / n,
        sum(counts[x] for x in NEGATIVE) / n,
        (sum(counts[x] for x in POSITIVE) - sum(counts[x] for x in NEGATIVE)) / n,
        counts["G"] / n, counts["P"] / n, counts["C"] / n,
        entropy, max(counts.values()) / n,
    ]


def physchem_matrix(frame: pd.DataFrame) -> np.ndarray:
    return np.asarray([
        sum((region_features(str(row[x])) for x in ("sequence", "cdr1_after", "cdr2_after", "cdr3_after")), [])
        for _, row in frame.iterrows()
    ], dtype=np.float32)


def hashed_kmer_matrix(values: list[str], n_features: int = 512) -> np.ndarray:
    matrix = np.zeros((len(values), n_features), dtype=np.float32)
    for row_index, value in enumerate(values):
        for width in (2, 3, 4, 5):
            for start in range(max(0, len(value) - width + 1)):
                token = value[start : start + width]
                digest = hashlib.blake2b(token.encode("ascii"), digest_size=8).digest()
                index = int.from_bytes(digest, "little") % n_features
                matrix[row_index, index] += 1.0
        norm = float(np.linalg.norm(matrix[row_index]))
        if norm:
            matrix[row_index] /= norm
    return matrix


def fit_weighted_ridge(x: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float) -> np.ndarray:
    weighted_x = x * np.sqrt(weights)[:, None]
    weighted_y = y * np.sqrt(weights)[:, None]
    gram = weighted_x.T @ weighted_x
    gram.flat[:: gram.shape[0] + 1] += alpha
    return np.linalg.solve(gram, weighted_x.T @ weighted_y)


def fit_and_score(pool: pd.DataFrame, teacher: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, dict[str, object], dict[str, object]]:
    required_teacher = {"sequence", "cdr1", "cdr2", "cdr3", "R_8X6B", "R_9E6Y"}
    require(required_teacher <= set(teacher.columns), f"teacher_columns_missing:{sorted(required_teacher - set(teacher.columns))}")
    train_text = (teacher.sequence + "|" + teacher.cdr1 + "|" + teacher.cdr2 + "|" + teacher.cdr3).tolist()
    pool_text = (pool.sequence + "|" + pool.cdr1_after + "|" + pool.cdr2_after + "|" + pool.cdr3_after).tolist()
    x_train = hashed_kmer_matrix(train_text)
    x_pool = hashed_kmer_matrix(pool_text)
    y = teacher[["R_8X6B", "R_9E6Y"]].astype(float).to_numpy()
    weights = teacher["sample_weight"].astype(float).to_numpy() if "sample_weight" in teacher else np.ones(len(teacher))
    kmer_coefficients = fit_weighted_ridge(x_train, y, weights, alpha=25.0)
    ridge_pred = x_pool @ kmer_coefficients

    teacher_phys = teacher.rename(columns={"cdr1": "cdr1_after", "cdr2": "cdr2_after", "cdr3": "cdr3_after"})
    x2_train = physchem_matrix(teacher_phys)
    x2_pool = physchem_matrix(pool)
    mean = np.average(x2_train, axis=0, weights=weights)
    variance = np.average((x2_train - mean) ** 2, axis=0, weights=weights)
    scale = np.sqrt(np.maximum(variance, 1e-8))
    phys_coefficients = fit_weighted_ridge((x2_train - mean) / scale, y, weights, alpha=25.0)
    forest_pred = ((x2_pool - mean) / scale) @ phys_coefficients
    ensemble = (ridge_pred + forest_pred) / 2.0
    disagreement = np.max(np.abs(ridge_pred - forest_pred), axis=1)
    pool = pool.copy()
    pool["proxy_kmer_R8"] = ridge_pred[:, 0]
    pool["proxy_kmer_R9"] = ridge_pred[:, 1]
    pool["proxy_physchem_R8"] = forest_pred[:, 0]
    pool["proxy_physchem_R9"] = forest_pred[:, 1]
    pool["proxy_ensemble_R8"] = ensemble[:, 0]
    pool["proxy_ensemble_R9"] = ensemble[:, 1]
    pool["proxy_Rdual_exact_min"] = np.minimum(ensemble[:, 0], ensemble[:, 1])
    pool["proxy_model_disagreement"] = disagreement
    deciles = pd.qcut(pool["proxy_Rdual_exact_min"].rank(method="first"), 10, labels=False) + 1
    pool["proxy_score_decile"] = deciles.astype(int)
    model_bundle = {
        "schema_version": "pvrig_v2_9_acquisition_proxy_models_v1",
        "claim_boundary": CLAIM,
        "kmer_coefficients": kmer_coefficients,
        "physchem_mean": mean,
        "physchem_scale": scale,
        "physchem_coefficients": phys_coefficients,
    }
    summary = {
        "schema_version": "pvrig_v2_9_acquisition_proxy_summary_v1",
        "training_rows": len(teacher), "scored_rows": len(pool),
        "models": ["char_2_5_hashing_ridge", "physchem_ridge"],
        "claim_boundary": CLAIM,
    }
    return pool, model_bundle, summary


def build_slots(parents: pd.DataFrame, eligible: pd.DataFrame, contract: dict[str, object]) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = contract["panel"]
    method_target = dict(panel["method_quotas"])
    patch_values = [x for name, count in panel["patch_quotas"].items() for x in [name] * int(count)]
    acquisition_values = [x for name, count in panel["acquisition_quotas"].items() for x in [name] * int(count)]
    seed = str(contract["random_seed"])
    total_capacity = eligible.groupby("parent_framework_cluster").size()
    candidate_parents = total_capacity[total_capacity >= int(panel["maximum_rows_per_parent"])].index.tolist()
    candidate_parents.sort(key=lambda x: (-int(total_capacity[x]), stable_hash(seed, "panel-parent", x)))
    selected_parent_ids = candidate_parents[: int(panel["parent_count"])]
    require(len(selected_parent_ids) == int(panel["parent_count"]), f"eligible_parent_capacity:{len(selected_parent_ids)}")
    selected_parents = parents[parents.parent_framework_cluster.isin(selected_parent_ids)].copy()
    new_fraction = (~selected_parents.is_existing_open3388_parent.astype(bool)).mean()
    require(new_fraction >= 0.5, f"new_parent_fraction:{new_fraction}")
    row_delta = int(panel["maximum_rows_per_parent"]) - int(panel["minimum_rows_per_parent"])
    require(row_delta == 1, f"parent_row_delta:{row_delta}")
    low_count = int(panel["total"]) - int(panel["minimum_rows_per_parent"]) * int(panel["parent_count"])
    require(0 <= low_count <= int(panel["parent_count"]), f"parent_count_arithmetic:{low_count}")
    ordered_parents = sorted(selected_parent_ids, key=lambda x: stable_hash(seed, "parent-row-target", x))
    parent_target = {
        parent: int(panel["maximum_rows_per_parent"]) if index < low_count else int(panel["minimum_rows_per_parent"])
        for index, parent in enumerate(ordered_parents)
    }
    capacity = eligible[eligible.parent_framework_cluster.isin(selected_parent_ids)].groupby(["parent_framework_cluster", "design_method"]).size().to_dict()
    allocation = {p: Counter() for p in selected_parent_ids}
    remaining = dict(parent_target)
    natural_method = "NATURAL_CDR_DONOR_REDESIGN"
    required_nonnatural = {
        p: max(0, parent_target[p] - int(capacity.get((p, natural_method), 0)))
        for p in selected_parent_ids
    }
    non_natural = [
        "RFANTIBODY_RFDIFFUSION_PROTEINMPNN",
        "FIXED_FRAMEWORK_CDR_PERTURBATION",
        "DE_NOVO_CDR_EXPLORATION",
        "CONSERVATIVE_PROFILE_LOCAL_REDESIGN",
    ]
    for method in non_natural:
        target = int(method_target[method])
        for iteration in range(target):
            candidates = [
                p for p in selected_parent_ids
                if remaining[p] > 0 and allocation[p][method] < int(capacity.get((p, method), 0))
            ]
            require(bool(candidates), f"method_capacity_exhausted:{method}:{iteration}:{target}")
            candidates.sort(key=lambda p: (
                sum(allocation[p][m] for m in non_natural) >= required_nonnatural[p],
                -(required_nonnatural[p] - sum(allocation[p][m] for m in non_natural)),
                allocation[p][method] / max(1, int(capacity.get((p, method), 0))),
                -remaining[p],
                stable_hash(seed, "method-allocation", method, iteration, p),
            ))
            chosen = candidates[0]
            allocation[chosen][method] += 1; remaining[chosen] -= 1
    natural = natural_method
    require(sum(remaining.values()) == int(method_target[natural]), "natural_remaining_total")
    for parent, count in remaining.items():
        require(count <= int(capacity.get((parent, natural), 0)), f"natural_capacity:{parent}:{count}:{capacity.get((parent,natural),0)}")
        allocation[parent][natural] = count
    slots: list[dict[str, object]] = []
    for parent in sorted(selected_parent_ids):
        index = 0
        for method in method_target:
            for _ in range(allocation[parent][method]):
                index += 1
                slots.append({"parent_framework_cluster": parent, "design_method": method, "slot_in_parent": index})
        require(index == parent_target[parent], f"parent_slot_count:{parent}:{index}:{parent_target[parent]}")
    require(Counter(x["design_method"] for x in slots) == Counter({k: int(v) for k, v in method_target.items()}), "method_slot_quota")

    order = sorted(range(len(slots)), key=lambda i: stable_hash(seed, "patch", slots[i]["parent_framework_cluster"], slots[i]["design_method"], slots[i]["slot_in_parent"]))
    for idx, value in zip(order, patch_values): slots[idx]["target_patch"] = value
    order = sorted(range(len(slots)), key=lambda i: stable_hash(seed, "acq", slots[i]["parent_framework_cluster"], slots[i]["design_method"], slots[i]["slot_in_parent"]))
    for idx, value in zip(order, acquisition_values): slots[idx]["acquisition_lane"] = value

    # Exact mode quotas with parent/method/mode capacity closure via max flow.
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, slot in enumerate(slots):
        groups[(str(slot["parent_framework_cluster"]), str(slot["design_method"]))].append(index)
    mode_targets = {k: int(v) for k, v in panel["design_mode_quotas"].items()}
    modes = list(mode_targets)
    group_keys = sorted(groups)
    source = 0; mode_offset = 1; group_offset = 1 + len(modes); sink = group_offset + len(group_keys)
    network = Dinic(sink + 1)
    for midx, mode in enumerate(modes): network.add(source, mode_offset + midx, mode_targets[mode])
    mode_group_edges: dict[tuple[str, tuple[str, str]], list[int]] = {}
    triple_capacity = eligible.groupby(["parent_framework_cluster", "design_method", "design_mode"]).size().to_dict()
    for gidx, group_key in enumerate(group_keys):
        network.add(group_offset + gidx, sink, len(groups[group_key]))
        for midx, mode in enumerate(modes):
            edge = network.add(mode_offset + midx, group_offset + gidx, int(triple_capacity.get((*group_key, mode), 0)))
            mode_group_edges[(mode, group_key)] = edge
    require(network.flow(source, sink) == len(slots), "mode_quota_capacity_flow_failed")
    for group_key in group_keys:
        ordered = sorted(groups[group_key], key=lambda i: stable_hash(seed, "mode-slot", group_key[0], group_key[1], slots[i]["slot_in_parent"]))
        cursor = 0
        for mode in modes:
            edge = mode_group_edges[(mode, group_key)]
            assigned = edge[3] - edge[1]
            for index in ordered[cursor : cursor + assigned]: slots[index]["design_mode"] = mode
            cursor += assigned
        require(cursor == len(ordered), f"mode_group_assignment:{group_key}:{cursor}:{len(ordered)}")
    return pd.DataFrame(slots), selected_parents


def choose_for_lane(group: pd.DataFrame, lane: str, seed: str) -> pd.DataFrame:
    frame = group.copy()
    frame["_hash"] = frame.candidate_id.map(lambda x: stable_hash(seed, lane, x))
    if lane == "EXPLOITATION_HIGH":
        return frame.sort_values(["proxy_Rdual_exact_min", "_hash"], ascending=[False, True])
    if lane == "BOUNDARY_MIDDLE":
        median = float(frame.proxy_Rdual_exact_min.median())
        frame["_boundary"] = (frame.proxy_Rdual_exact_min - median).abs()
        return frame.sort_values(["_boundary", "_hash"])
    if lane == "QC_PASS_LOW_RANDOM_CONTROL":
        return frame.sort_values(["proxy_Rdual_exact_min", "_hash"], ascending=[True, True])
    if lane == "MODEL_DISAGREEMENT_UNCERTAINTY":
        return frame.sort_values(["proxy_model_disagreement", "_hash"], ascending=[False, True])
    if lane == "NEW_PARENT_PATCH_METHOD_EXPLORATION":
        return frame.sort_values(["parent_is_existing_open3388", "_hash"], ascending=[True, True])
    raise RuntimeError(f"unknown_lane:{lane}")


def select_panel(pool: pd.DataFrame, parents: pd.DataFrame, contract: dict[str, object], anarci_pass: set[str] | None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eligible = pool[(pool.fast_qc_pass == "true") & (pool.positive_cdr_formal75_pass == "true")].copy()
    if anarci_pass is not None:
        eligible = eligible[eligible.candidate_id.isin(anarci_pass)].copy()
    slots, selected_parents = build_slots(parents, eligible, contract)
    used: set[str] = set()
    selected: list[pd.Series] = []
    slot_rows: list[dict[str, object]] = []
    seed = str(contract["random_seed"])
    lane_priority = ["MODEL_DISAGREEMENT_UNCERTAINTY", "QC_PASS_LOW_RANDOM_CONTROL", "BOUNDARY_MIDDLE", "EXPLOITATION_HIGH", "NEW_PARENT_PATCH_METHOD_EXPLORATION"]
    slots["_lane_order"] = slots.acquisition_lane.map({x: i for i, x in enumerate(lane_priority)})
    for slot in slots.sort_values(["_lane_order", "parent_framework_cluster", "slot_in_parent"]).itertuples():
        group = eligible[
            (eligible.parent_framework_cluster == slot.parent_framework_cluster)
            & (eligible.design_method == slot.design_method)
            & (eligible.target_patch == slot.target_patch)
            & (eligible.design_mode == slot.design_mode)
            & (~eligible.candidate_id.isin(used))
        ]
        if group.empty:
            # Preserve parent/method/mode hard quotas. Patch is an approximately
            # balanced design annotation and may use a deterministic rescue.
            group = eligible[
                (eligible.parent_framework_cluster == slot.parent_framework_cluster)
                & (eligible.design_method == slot.design_method)
                & (eligible.design_mode == slot.design_mode)
                & (~eligible.candidate_id.isin(used))
            ]
            rescue = "PATCH_CAPACITY_RESCUE"
        else:
            rescue = "NONE"
        require(not group.empty, f"slot_capacity:{slot.parent_framework_cluster}:{slot.design_method}:{slot.target_patch}:{slot.design_mode}")
        choice = choose_for_lane(group, slot.acquisition_lane, seed).iloc[0]
        used.add(str(choice.candidate_id))
        selected.append(choice)
        slot_rows.append({
            "candidate_id": choice.candidate_id, "slot_parent": slot.parent_framework_cluster,
            "slot_method": slot.design_method, "slot_patch": slot.target_patch,
            "slot_mode": slot.design_mode, "acquisition_lane": slot.acquisition_lane,
            "slot_capacity_rescue": rescue,
        })
    panel = pd.DataFrame(selected).merge(pd.DataFrame(slot_rows), on="candidate_id", validate="one_to_one")
    panel["selection_rank"] = np.arange(1, len(panel) + 1)
    require(len(panel) == int(contract["panel"]["total"]), "panel_count")
    require(panel.sequence_sha256.nunique() == len(panel), "panel_sequence_unique")
    require(panel.parent_framework_cluster.nunique() == int(contract["panel"]["parent_count"]), "panel_parent_count")
    allowed_parent_rows = {
        int(contract["panel"]["minimum_rows_per_parent"]),
        int(contract["panel"]["maximum_rows_per_parent"]),
    }
    require(set(panel.groupby("parent_framework_cluster").size()) <= allowed_parent_rows, "panel_parent_rows")
    require(Counter(panel.design_method) == Counter({k: int(v) for k, v in contract["panel"]["method_quotas"].items()}), "panel_method_quota")
    require(Counter(panel.acquisition_lane) == Counter({k: int(v) for k, v in contract["panel"]["acquisition_quotas"].items()}), "panel_acquisition_quota")
    return panel, slots.drop(columns="_lane_order"), selected_parents


def hamming_identity(a: str, b: str) -> float:
    require(len(a) == len(b), "hamming_length")
    return sum(x == y for x, y in zip(a, b)) / len(a)


def assign_near_cdr3(panel: pd.DataFrame, threshold: float) -> pd.DataFrame:
    result = panel.copy()
    family_by_id: dict[str, str] = {}
    representative_by_family: dict[str, str] = {}
    for (parent, length), group in panel.groupby(["parent_framework_cluster", panel.cdr3_after.str.len()]):
        representatives: list[tuple[str, str]] = []
        for row in group.sort_values("sequence_sha256").itertuples():
            assigned = ""
            for family, representative in representatives:
                if hamming_identity(row.cdr3_after, representative) >= threshold:
                    assigned = family; break
            if not assigned:
                assigned = f"NC3_{parent}_{int(length):02d}_{len(representatives)+1:04d}"
                representatives.append((assigned, row.cdr3_after))
                representative_by_family[assigned] = row.cdr3_after
            family_by_id[row.candidate_id] = assigned
    result["near_cdr3_family"] = result.candidate_id.map(family_by_id)
    result["near_cdr3_family_representative"] = result.near_cdr3_family.map(representative_by_family)
    return result


def assign_parent_splits(panel: pd.DataFrame, contract: dict[str, object]) -> tuple[pd.DataFrame, pd.DataFrame]:
    seed = str(contract["split"]["seed"])
    parents = sorted(panel.parent_framework_cluster.unique(), key=lambda x: stable_hash(seed, x))
    expected = int(contract["panel"]["parent_count"])
    require(len(parents) == expected, f"split_parent_count:{len(parents)}:{expected}")
    development_count = int(round(expected * float(contract["split"]["development_fraction"])))
    test_count = int(round(expected * float(contract["split"]["test_fraction"])))
    train_count = expected - development_count - test_count
    require(train_count > 0 and development_count > 0 and test_count > 0, "invalid_split_counts")
    mapping = {p: "train" for p in parents[:train_count]}
    mapping.update({p: "development" for p in parents[train_count : train_count + development_count]})
    mapping.update({p: "frozen_test" for p in parents[train_count + development_count :]})
    panel = panel.copy(); panel["model_split"] = panel.parent_framework_cluster.map(mapping)
    manifest = pd.DataFrame({"parent_framework_cluster": parents, "model_split": [mapping[x] for x in parents]})
    manifest["parent_split_hash"] = manifest.apply(lambda r: stable_hash(seed, r.parent_framework_cluster, r.model_split), axis=1)
    require(
        Counter(manifest.model_split)
        == Counter({"train": train_count, "development": development_count, "frozen_test": test_count}),
        "split_parent_counts",
    )
    return panel, manifest


def stratified_repeat_selection(panel: pd.DataFrame, contract: dict[str, object]) -> tuple[set[str], set[str]]:
    seed = str(contract["random_seed"])
    seed2: set[str] = set()
    seed3: set[str] = set()
    parents = sorted(panel.parent_framework_cluster.unique(), key=lambda x: stable_hash(seed, "repeat-parent", x))
    seed2_total = int(contract["docking_allocation"]["seed2_candidate_count"])
    seed3_total = int(contract["docking_allocation"]["seed3_candidate_count"])
    seed2_base, seed2_extra = divmod(seed2_total, len(parents))
    seed3_base, seed3_extra = divmod(seed3_total, len(parents))
    seed2_targets = {p: seed2_base + (i < seed2_extra) for i, p in enumerate(parents)}
    seed3_targets = {p: seed3_base + (i < seed3_extra) for i, p in enumerate(parents)}
    for parent, group in panel.groupby("parent_framework_cluster"):
        # 28-29/parent. Round-robin sorted cells cover score, acquisition and method.
        group = group.copy()
        group["_repeat_hash"] = group.candidate_id.map(lambda x: stable_hash(seed, "seed2", parent, x))
        group = group.sort_values(["proxy_score_decile", "acquisition_lane", "design_method", "target_patch", "design_mode", "_repeat_hash"])
        target2 = seed2_targets[parent]
        positions = np.linspace(0, len(group) - 1, target2, dtype=int)
        chosen = group.iloc[positions].drop_duplicates("candidate_id")
        if len(chosen) < target2:
            extra = group[~group.candidate_id.isin(chosen.candidate_id)].head(target2 - len(chosen))
            chosen = pd.concat([chosen, extra])
        seed2.update(chosen.candidate_id)

        candidates = chosen.copy()
        picks: list[str] = []
        ordered_views = [
            candidates.sort_values("proxy_model_disagreement", ascending=False),
            candidates.sort_values("proxy_Rdual_exact_min", ascending=False),
            candidates.iloc[(candidates.proxy_score_decile - 5).abs().argsort()],
            candidates.sort_values("proxy_Rdual_exact_min", ascending=True),
            candidates.sort_values("_repeat_hash"),
        ]
        while len(ordered_views) < seed3_targets[parent]:
            ordered_views.append(candidates.sort_values("_repeat_hash").iloc[len(ordered_views)-4:])
        for ordered in ordered_views:
            for candidate in ordered.candidate_id:
                if candidate not in picks:
                    picks.append(candidate); break
            if len(picks) == seed3_targets[parent]: break
        require(len(picks) == seed3_targets[parent], f"seed3_parent_capacity:{parent}")
        seed3.update(picks)
    require(len(seed2) == seed2_total, f"seed2_count:{len(seed2)}")
    require(len(seed3) == seed3_total and seed3 <= seed2, f"seed3_count:{len(seed3)}")
    return seed2, seed3


def build_allocation(panel: pd.DataFrame, contract: dict[str, object], protocol_root: Path) -> pd.DataFrame:
    lock = json.loads((protocol_root / "PROTOCOL_LOCK.json").read_text())
    seed2, seed3 = stratified_repeat_selection(panel, contract)
    jobs: list[dict[str, object]] = []
    for row in panel.itertuples():
        seeds = [917] + ([1931] if row.candidate_id in seed2 else []) + ([3253] if row.candidate_id in seed3 else [])
        for seed in seeds:
            for receptor in ("8x6b", "9e6y"):
                job_id = f"{row.candidate_id}__{receptor}__seed{seed}"
                jobs.append({
                    "job_id": job_id, "candidate_id": row.candidate_id, "sequence_sha256": row.sequence_sha256,
                    "receptor": receptor, "seed": seed, "model_split": row.model_split,
                    "acquisition_lane": row.acquisition_lane, "design_method": row.design_method,
                    "target_patch": row.target_patch, "design_mode": row.design_mode,
                    "monomer_model": "PENDING", "monomer_model_version": "PENDING",
                    "monomer_pdb_path": "", "monomer_pdb_sha256": "",
                    "protocol_id": lock["protocol_id"], "protocol_core_sha256": lock["protocol_core_sha256"],
                    "source_protocol_lock_sha256": lock["protocol_lock_sha256"],
                    "allocation_state": "WAITING_MONOMER_STRUCTURE_AND_NEW_PROTOCOL_FREEZE",
                    "allocation_hash": stable_hash("pvrig-v2.9-allocation", job_id, row.sequence_sha256, lock["protocol_core_sha256"]),
                    "claim_boundary": CLAIM,
                })
    result = pd.DataFrame(jobs)
    require(len(result) == int(contract["docking_allocation"]["candidate_job_count"]), f"allocation_count:{len(result)}")
    require(Counter(result.seed) == Counter({917: 20000, 1931: 4000, 3253: 1000}), "seed_job_counts")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--pool", type=Path, required=True)
    ap.add_argument("--parents", type=Path, required=True)
    ap.add_argument("--teacher", type=Path, required=True)
    ap.add_argument("--protocol-root", type=Path, required=True)
    ap.add_argument("--anarci-pass", type=Path)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    contract = json.loads(args.contract.read_text())
    pool = pd.read_csv(args.pool, sep="\t", dtype=str).fillna("")
    numeric = ["max_positive_cdr_identity", "sequence_length", "cysteine_count", "low_complexity_fraction", "hydrophobic_fraction", "cdr3_hydrophobic_fraction"]
    for column in numeric: pool[column] = pd.to_numeric(pool[column])
    parents = pd.read_csv(args.parents, sep="\t")
    teacher = pd.read_csv(args.teacher, sep="\t")
    anarci_pass = None
    if args.anarci_pass:
        table = pd.read_csv(args.anarci_pass, sep="\t")
        require({"candidate_id", "anarci_imgt_pass"} <= set(table.columns), "anarci_table_columns")
        anarci_pass = set(table.loc[table.anarci_imgt_pass.astype(str).str.lower() == "true", "candidate_id"])

    eligible_mask = (pool.fast_qc_pass == "true") & (pool.positive_cdr_formal75_pass == "true")
    score_input = pool[eligible_mask].copy().reset_index(drop=True)
    scored, models, proxy_summary = fit_and_score(score_input, teacher, int(contract["random_seed"]))
    scored.to_csv(args.output_dir / "eligible_pool_proxy_scores.tsv", sep="\t", index=False)
    np.savez_compressed(
        args.output_dir / "acquisition_proxy_models.npz",
        kmer_coefficients=models["kmer_coefficients"],
        physchem_mean=models["physchem_mean"],
        physchem_scale=models["physchem_scale"],
        physchem_coefficients=models["physchem_coefficients"],
    )
    panel, slots, selected_parents = select_panel(scored, parents, contract, anarci_pass)
    panel = assign_near_cdr3(panel, float(contract["near_cdr3_family"]["identity_threshold"]))
    panel, split_manifest = assign_parent_splits(panel, contract)
    allocation = build_allocation(panel, contract, args.protocol_root)
    panel.to_csv(args.output_dir / "docking_panel10000.tsv", sep="\t", index=False)
    slots.to_csv(args.output_dir / "selection_slots10000.tsv", sep="\t", index=False)
    split_manifest.to_csv(args.output_dir / "parent_split_manifest.tsv", sep="\t", index=False)
    selected_parents.to_csv(args.output_dir / "selected_parent70_manifest.tsv", sep="\t", index=False)
    allocation.to_csv(args.output_dir / "docking_allocation25000.tsv", sep="\t", index=False)
    with (args.output_dir / "docking_panel10000.fasta").open("w") as handle:
        for row in panel.itertuples(): handle.write(f">{row.candidate_id}\n{row.sequence}\n")
    summary = {
        **proxy_summary,
        "status": "PASS_PROVISIONAL_PANEL" if anarci_pass is None else "PASS_ANARCI_VERIFIED_PANEL",
        "panel_rows": len(panel), "panel_unique_sequences": int(panel.sequence_sha256.nunique()),
        "parent_count": int(panel.parent_framework_cluster.nunique()),
        "new_parent_fraction": float((panel.parent_is_existing_open3388.astype(str) == "false").mean()),
        "method_counts": panel.design_method.value_counts().sort_index().to_dict(),
        "patch_counts_observed": panel.target_patch.value_counts().sort_index().to_dict(),
        "mode_counts_observed": panel.design_mode.value_counts().sort_index().to_dict(),
        "acquisition_counts": panel.acquisition_lane.value_counts().sort_index().to_dict(),
        "slot_capacity_rescue_count": int((panel.slot_capacity_rescue != "NONE").sum()),
        "near_cdr3_family_count": int(panel.near_cdr3_family.nunique()),
        "allocation_rows": len(allocation),
        "allocation_state": "WAITING_MONOMER_STRUCTURE_AND_NEW_PROTOCOL_FREEZE",
        "input_hashes": {
            "contract": sha_file(args.contract), "pool": sha_file(args.pool), "parents": sha_file(args.parents),
            "teacher": sha_file(args.teacher), "protocol_lock": sha_file(args.protocol_root / "PROTOCOL_LOCK.json"),
            **({"anarci_pass": sha_file(args.anarci_pass)} if args.anarci_pass else {}),
        },
        "claim_boundary": CLAIM,
    }
    (args.output_dir / "PANEL_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
