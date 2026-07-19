#!/usr/bin/env python3
"""Deterministic, label-safe V2.5 causal perturbations, hardened V1.1.

These utilities only transform already-open target graphs, open-development
contact supervision, or label-free meta features.  They never open labels,
fit models, inspect V4-F/test32, or launch jobs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
from collections import defaultdict
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import torch


RECEPTORS = ("8x6b", "9e6y")
MASK_FIELDS = ("hotspot_mask", "interface_mask")
TARGET_REQUIRED_FIELDS = {
    "node_features", "edge_index", "edge_features", "hotspot_mask", "interface_mask",
}
CONTACT_SCORE_FIELDS = ("contact_score_R8", "contact_score_R9")
FORBIDDEN_DONOR_PAYLOAD_FIELDS = {
    "candidate_id", "parent_framework_cluster", "sequence", "targets",
    "truth_R8", "truth_R9", "truth_Rdual", "R_8X6B", "R_9E6Y", "R_dual_min",
    "input_ids", "attention_mask", "residue_mask", "vhh_aa_index", "vhh_region_index",
    "vhh_confidence", "vhh_edge_index", "vhh_edge_features",
}
SEALED_TOKENS = ("v4_f", "v4-f", "test32", "sealed")
MASK_NULL_REPLICATES = 256
MASK_NULL_MASTER_SEED = 1931
DONOR_POWER_THRESHOLDS = {
    "complete_payload_changed_fraction_min": 0.90,
    "supervision_changed_fraction_min": 0.80,
    "supervision_median_distance_min": 0.01,
    "supervision_mapped_to_eligible_median_ratio_min": 0.50,
    "supervision_kish_effective_fraction_min": 0.50,
    "per_parent_supervision_changed_fraction_min": 0.50,
    "distance_epsilon": 1e-8,
}


class CausalPerturbationError(RuntimeError):
    """Fail-closed perturbation contract error."""


def require(value: bool, message: str) -> None:
    if not value:
        raise CausalPerturbationError(message)


def reject_sealed_text(value: str) -> None:
    lowered = value.casefold()
    require(not any(token in lowered for token in SEALED_TOKENS), f"sealed_token:{value}")


def _clone_value(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().clone()
    return copy.deepcopy(value)


def clone_target_graphs(
    target_graphs: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    require(set(target_graphs) == set(RECEPTORS), "target_receptor_set")
    cloned: dict[str, dict[str, Any]] = {}
    for receptor in RECEPTORS:
        graph = target_graphs[receptor]
        require(TARGET_REQUIRED_FIELDS <= set(graph), f"target_fields:{receptor}")
        nodes = graph["node_features"]
        require(isinstance(nodes, torch.Tensor) and nodes.ndim == 2, f"target_nodes:{receptor}")
        node_count = int(nodes.shape[0])
        for field in MASK_FIELDS:
            mask = graph[field]
            require(
                isinstance(mask, torch.Tensor) and mask.shape == (node_count,),
                f"target_mask:{receptor}:{field}",
            )
        cloned[receptor] = {key: _clone_value(value) for key, value in graph.items()}
    return cloned


def swap_hotspot_interface_masks(
    target_graphs: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Swap mask semantics at fixed target residue positions.

    This is an inference-only perturbation.  Node features, topology, receptor
    keys, scalar outputs, and contact logits are untouched; only downstream
    label-free contact summaries and the contact-aware meta stack may change.
    """
    result = clone_target_graphs(target_graphs)
    for receptor in RECEPTORS:
        hotspot = result[receptor]["hotspot_mask"].clone()
        interface = result[receptor]["interface_mask"].clone()
        require(not torch.equal(hotspot, interface), f"identical_masks:{receptor}")
        result[receptor]["hotspot_mask"] = interface
        result[receptor]["interface_mask"] = hotspot
    return result


def _mask_null_seed(master_seed: int, replicate: int, receptor: str) -> int:
    require(isinstance(master_seed, int) and master_seed >= 0, "mask_null_master_seed")
    require(isinstance(replicate, int) and replicate >= 0, "mask_null_replicate")
    digest = hashlib.sha256(
        f"pvrig-v2.5-mask-position-null-v1.1:{master_seed}:{replicate}:{receptor}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") % (2**63 - 1)


def _joint_mask_contingency(hotspot: torch.Tensor, interface: torch.Tensor) -> dict[str, int]:
    require(hotspot.dtype == torch.bool and interface.dtype == torch.bool, "mask_null_bool_dtype")
    return {
        "00": int((~hotspot & ~interface).sum().item()),
        "01": int((~hotspot & interface).sum().item()),
        "10": int((hotspot & ~interface).sum().item()),
        "11": int((hotspot & interface).sum().item()),
    }


def matched_prevalence_mask_position_null(
    target_graphs: Mapping[str, Mapping[str, Any]],
    *,
    replicate: int,
    master_seed: int = MASK_NULL_MASTER_SEED,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Relocate the clean mask pair while preserving every prevalence statistic.

    The same permutation is applied to the two-column hotspot/interface row
    payload.  Therefore hotspot count, interface count, overlap, and the full
    2x2 contingency table remain exact.  This is a spatial-position null, not a
    mask-size perturbation.  A degenerate graph for which relocation cannot
    change either mask fails closed.
    """
    result = clone_target_graphs(target_graphs)
    audit: dict[str, dict[str, Any]] = {}
    for receptor in RECEPTORS:
        original_hotspot = result[receptor]["hotspot_mask"]
        original_interface = result[receptor]["interface_mask"]
        require(original_hotspot.dtype == torch.bool, f"mask_null_hotspot_dtype:{receptor}")
        require(original_interface.dtype == torch.bool, f"mask_null_interface_dtype:{receptor}")
        count = int(original_hotspot.numel())
        require(count > 1, f"mask_null_target_too_short:{receptor}")
        joint = torch.stack((original_hotspot, original_interface), dim=1)
        require(torch.unique(joint, dim=0).shape[0] > 1, f"mask_null_relocation_impossible:{receptor}")

        generator = torch.Generator(device="cpu")
        derived_seed = _mask_null_seed(master_seed, replicate, receptor)
        generator.manual_seed(derived_seed)
        permutation = torch.randperm(count, generator=generator)
        relocated = joint.index_select(0, permutation.to(joint.device))
        if torch.equal(relocated, joint):
            found = False
            for shift in range(1, count):
                candidate = torch.roll(joint, shifts=shift, dims=0)
                if not torch.equal(candidate, joint):
                    relocated = candidate
                    permutation = torch.roll(torch.arange(count), shifts=shift)
                    found = True
                    break
            require(found, f"mask_null_relocation_impossible:{receptor}")

        null_hotspot = relocated[:, 0].clone()
        null_interface = relocated[:, 1].clone()
        original_contingency = _joint_mask_contingency(original_hotspot, original_interface)
        null_contingency = _joint_mask_contingency(null_hotspot, null_interface)
        require(int(null_hotspot.sum()) == int(original_hotspot.sum()), f"mask_null_hotspot_count:{receptor}")
        require(int(null_interface.sum()) == int(original_interface.sum()), f"mask_null_interface_count:{receptor}")
        require(null_contingency == original_contingency, f"mask_null_contingency:{receptor}")
        require(
            not torch.equal(null_hotspot, original_hotspot)
            or not torch.equal(null_interface, original_interface),
            f"mask_null_no_position_change:{receptor}",
        )
        result[receptor]["hotspot_mask"] = null_hotspot
        result[receptor]["interface_mask"] = null_interface
        audit[receptor] = {
            "derived_seed": derived_seed,
            "replicate": replicate,
            "node_count": count,
            "hotspot_cardinality": int(null_hotspot.sum()),
            "interface_cardinality": int(null_interface.sum()),
            "hotspot_prevalence": float(null_hotspot.float().mean()),
            "interface_prevalence": float(null_interface.float().mean()),
            "overlap_cardinality": int((null_hotspot & null_interface).sum()),
            "joint_contingency": null_contingency,
            "position_changed": True,
            "permutation_sha256": hashlib.sha256(
                json.dumps([int(value) for value in permutation.tolist()]).encode()
            ).hexdigest(),
        }
    return result, audit


def build_matched_prevalence_mask_null_bank(
    target_graphs: Mapping[str, Mapping[str, Any]],
    *,
    replicates: int = MASK_NULL_REPLICATES,
    master_seed: int = MASK_NULL_MASTER_SEED,
) -> tuple[list[dict[str, dict[str, Any]]], list[dict[str, dict[str, Any]]]]:
    """Build the preregistered deterministic mask-position null bank."""
    require(replicates == MASK_NULL_REPLICATES, "mask_null_replicate_count_frozen")
    require(master_seed == MASK_NULL_MASTER_SEED, "mask_null_master_seed_frozen")
    nulls: list[dict[str, dict[str, Any]]] = []
    audits: list[dict[str, dict[str, Any]]] = []
    fingerprints: set[tuple[str, str]] = set()
    for replicate in range(replicates):
        null_graphs, audit = matched_prevalence_mask_position_null(
            target_graphs, replicate=replicate, master_seed=master_seed
        )
        fingerprint = tuple(audit[receptor]["permutation_sha256"] for receptor in RECEPTORS)
        require(fingerprint not in fingerprints, f"mask_null_duplicate_replicate:{replicate}")
        fingerprints.add(fingerprint)
        nulls.append(null_graphs)
        audits.append(audit)
    require(len(nulls) == MASK_NULL_REPLICATES, "mask_null_bank_closure")
    return nulls, audits


def swap_receptor_conformer_payloads(
    target_graphs: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Swap complete receptor graph payloads while retaining receptor keys.

    The model's receptor-index/conformer embeddings and R8/R9 output positions
    remain fixed.  This tests whether those roles are aligned to the actual
    8X6B/9E6Y graph content rather than acting as arbitrary slots.
    """
    cloned = clone_target_graphs(target_graphs)
    return {"8x6b": cloned["9e6y"], "9e6y": cloned["8x6b"]}


def _derived_seed(seed: int, receptor: str) -> int:
    require(isinstance(seed, int) and seed >= 0, "permutation_seed")
    digest = hashlib.sha256(f"pvrig-v2.5-target-permutation:{seed}:{receptor}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % (2**63 - 1)


def permute_target_residue_features(
    target_graphs: Mapping[str, Mapping[str, Any]],
    *,
    seed: int = 1931,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[int]]]:
    """Permute node-feature rows, leaving topology and masks fixed.

    A graph-consistent node relabeling would be an invariance test and would
    not disrupt target identity at a position.  The frozen causal perturbation
    deliberately permutes only residue/node features against fixed adjacency,
    interface masks, and hotspot masks.
    """
    result = clone_target_graphs(target_graphs)
    audit: dict[str, list[int]] = {}
    for receptor in RECEPTORS:
        features = result[receptor]["node_features"]
        count = int(features.shape[0])
        require(count > 1, f"target_too_short:{receptor}")
        generator = torch.Generator(device="cpu")
        generator.manual_seed(_derived_seed(seed, receptor))
        permutation = torch.randperm(count, generator=generator)
        if torch.equal(permutation, torch.arange(count)):
            permutation = torch.roll(permutation, shifts=1)
        result[receptor]["node_features"] = features.index_select(
            0, permutation.to(device=features.device)
        )
        audit[receptor] = [int(value) for value in permutation.tolist()]
    return result, audit


def within_parent_donor_map(
    rows: Sequence[Mapping[str, Any]],
    *,
    partition_id: str,
    seed: int = 1931,
    candidate_field: str = "candidate_id",
    parent_field: str = "parent_framework_cluster",
) -> dict[str, str]:
    """Build a deterministic same-parent derangement inside one train split.

    The caller must pass only the current inner-train or outer-train rows.  A
    parent singleton is a hard failure rather than a reason to borrow contact
    labels across parents or across a held-out partition.
    """
    reject_sealed_text(partition_id)
    require(rows, "donor_rows_empty")
    grouped: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        candidate = str(row[candidate_field])
        parent = str(row[parent_field])
        require(candidate and parent and candidate not in seen, f"donor_row_invalid:{candidate}")
        reject_sealed_text(candidate)
        seen.add(candidate)
        grouped[parent].append(candidate)
    mapping: dict[str, str] = {}
    for parent, candidates in sorted(grouped.items()):
        require(len(candidates) >= 2, f"parent_singleton:{parent}")
        ordered = sorted(
            candidates,
            key=lambda candidate: hashlib.sha256(
                f"{seed}|{partition_id}|{parent}|{candidate}".encode()
            ).hexdigest(),
        )
        donors = ordered[1:] + ordered[:1]
        for recipient, donor in zip(ordered, donors):
            require(recipient != donor, f"donor_self:{recipient}")
            mapping[recipient] = donor
    require(set(mapping) == seen, "donor_mapping_closure")
    return mapping


def apply_contact_donor_map(
    rows: Sequence[Mapping[str, Any]],
    donor_map: Mapping[str, str],
    *,
    contact_payload_fields: Iterable[str],
    candidate_field: str = "candidate_id",
    parent_field: str = "parent_framework_cluster",
) -> list[dict[str, Any]]:
    """Copy the complete contact payload from the frozen donor mapping.

    Scalar targets, sequence/structure inputs, identifiers, and parent fields
    remain attached to the recipient.  Missingness, masks, uncertainty, tier,
    marginal labels, and pair labels must therefore all be listed as payload
    fields by the execution adapter.
    """
    fields = tuple(contact_payload_fields)
    require(fields and len(set(fields)) == len(fields), "contact_payload_fields")
    require(not (set(fields) & FORBIDDEN_DONOR_PAYLOAD_FIELDS), "forbidden_contact_payload_field")
    by_id = {str(row[candidate_field]): row for row in rows}
    require(len(by_id) == len(rows), "donor_apply_duplicate_candidate")
    require(set(by_id) == set(donor_map), "donor_apply_closure")
    result: list[dict[str, Any]] = []
    for row in rows:
        recipient = str(row[candidate_field])
        donor = str(donor_map[recipient])
        require(donor in by_id and donor != recipient, f"donor_apply_invalid:{recipient}")
        require(
            str(row[parent_field]) == str(by_id[donor][parent_field]),
            f"donor_apply_cross_parent:{recipient}:{donor}",
        )
        output = {key: _clone_value(value) for key, value in row.items()}
        for field in fields:
            require(field in by_id[donor], f"donor_payload_missing:{field}")
            output[field] = _clone_value(by_id[donor][field])
        result.append(output)
    return result


def _numeric_tensor(value: Any, field: str) -> torch.Tensor | None:
    if isinstance(value, torch.Tensor):
        tensor = value.detach().cpu()
    elif isinstance(value, (bool, int, float)):
        tensor = torch.tensor([value])
    elif isinstance(value, (list, tuple)):
        try:
            tensor = torch.as_tensor(value)
        except (TypeError, ValueError):
            return None
    else:
        return None
    require(tensor.numel() > 0, f"payload_empty_numeric:{field}")
    if tensor.dtype == torch.bool:
        return tensor
    tensor = tensor.to(torch.float64)
    require(bool(torch.isfinite(tensor).all()), f"payload_nonfinite:{field}")
    return tensor


def _value_distance(left: Any, right: Any, field: str) -> float:
    left_tensor = _numeric_tensor(left, field)
    right_tensor = _numeric_tensor(right, field)
    if left_tensor is not None or right_tensor is not None:
        require(left_tensor is not None and right_tensor is not None, f"payload_type_mismatch:{field}")
        require(left_tensor.shape == right_tensor.shape, f"payload_shape_mismatch:{field}")
        if left_tensor.dtype == torch.bool or right_tensor.dtype == torch.bool:
            require(left_tensor.dtype == right_tensor.dtype == torch.bool, f"payload_bool_type:{field}")
            return float((left_tensor != right_tensor).to(torch.float64).mean())
        return min(1.0, float(torch.abs(left_tensor - right_tensor).mean()))
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        require(isinstance(left, Mapping) and isinstance(right, Mapping), f"payload_mapping_type:{field}")
        require(set(left) == set(right) and left, f"payload_mapping_keys:{field}")
        return statistics.fmean(
            _value_distance(left[key], right[key], f"{field}.{key}") for key in sorted(left)
        )
    require(type(left) is type(right), f"payload_type_mismatch:{field}")
    return 0.0 if left == right else 1.0


def contact_payload_distance(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    fields: Sequence[str],
) -> tuple[float, dict[str, float]]:
    """Return a field-balanced normalized contact-payload distance."""
    require(fields and len(set(fields)) == len(fields), "payload_distance_fields")
    require(not (set(fields) & FORBIDDEN_DONOR_PAYLOAD_FIELDS), "forbidden_contact_payload_field")
    per_field: dict[str, float] = {}
    for field in fields:
        require(field in left and field in right, f"payload_distance_missing:{field}")
        distance = _value_distance(left[field], right[field], field)
        require(math.isfinite(distance) and 0.0 <= distance <= 1.0, f"payload_distance_range:{field}")
        per_field[field] = distance
    return statistics.fmean(per_field.values()), per_field


def _quantile(values: Sequence[float], fraction: float) -> float:
    require(values and 0.0 <= fraction <= 1.0, "quantile_input")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _kish_effective_fraction(distances: Sequence[float], epsilon: float) -> float:
    weights = [max(0.0, float(value) - epsilon) for value in distances]
    total = sum(weights)
    squared = sum(value * value for value in weights)
    if total <= 0.0 or squared <= 0.0:
        return 0.0
    return ((total * total) / squared) / len(weights)


def _donor_map_sha256(donor_map: Mapping[str, str]) -> str:
    payload = "".join(f"{recipient}\t{donor}\n" for recipient, donor in sorted(donor_map.items()))
    return hashlib.sha256(payload.encode()).hexdigest()


def audit_contact_donor_power(
    rows: Sequence[Mapping[str, Any]],
    donor_map: Mapping[str, str],
    *,
    partition_id: str,
    contact_payload_fields: Sequence[str],
    supervision_fields: Sequence[str],
    candidate_field: str = "candidate_id",
    parent_field: str = "parent_framework_cluster",
    thresholds: Mapping[str, float] = DONOR_POWER_THRESHOLDS,
) -> dict[str, Any]:
    """Fail closed when a same-parent donor shuffle is too weak to be a null.

    This function must run on the canonicalized *current train partition*
    before optimizer/model initialization.  It never reads scalar truth.  The
    mapped supervision distance is also compared with all eligible non-self
    same-parent distances so a deterministic but unusually weak rotation is
    rejected.
    """
    reject_sealed_text(partition_id)
    require(rows, "donor_power_rows_empty")
    required_thresholds = set(DONOR_POWER_THRESHOLDS)
    require(set(thresholds) == required_thresholds, "donor_power_threshold_schema")
    for key, frozen in DONOR_POWER_THRESHOLDS.items():
        require(float(thresholds[key]) == frozen, f"donor_power_threshold_not_frozen:{key}")
    fields = tuple(contact_payload_fields)
    supervision = tuple(supervision_fields)
    require(fields and supervision and set(supervision) <= set(fields), "donor_power_field_scope")
    require(not (set(fields) & FORBIDDEN_DONOR_PAYLOAD_FIELDS), "forbidden_contact_payload_field")
    by_id = {str(row[candidate_field]): row for row in rows}
    require(len(by_id) == len(rows) and set(by_id) == set(donor_map), "donor_power_closure")

    epsilon = float(thresholds["distance_epsilon"])
    complete_distances: list[float] = []
    supervision_distances: list[float] = []
    eligible_supervision_distances: list[float] = []
    per_parent_distances: dict[str, list[float]] = defaultdict(list)
    grouped: dict[str, list[str]] = defaultdict(list)
    for candidate, row in by_id.items():
        grouped[str(row[parent_field])].append(candidate)

    for recipient, donor in sorted(donor_map.items()):
        require(recipient in by_id and donor in by_id and recipient != donor, f"donor_power_invalid:{recipient}")
        recipient_row = by_id[recipient]
        donor_row = by_id[donor]
        parent = str(recipient_row[parent_field])
        require(parent == str(donor_row[parent_field]), f"donor_power_cross_parent:{recipient}:{donor}")
        complete_distance, _ = contact_payload_distance(recipient_row, donor_row, fields=fields)
        supervision_distance, _ = contact_payload_distance(recipient_row, donor_row, fields=supervision)
        complete_distances.append(complete_distance)
        supervision_distances.append(supervision_distance)
        per_parent_distances[parent].append(supervision_distance)

    for parent, candidates in sorted(grouped.items()):
        require(len(candidates) >= 2, f"donor_power_parent_singleton:{parent}")
        for index, left in enumerate(sorted(candidates)):
            for right in sorted(candidates)[index + 1:]:
                distance, _ = contact_payload_distance(by_id[left], by_id[right], fields=supervision)
                eligible_supervision_distances.append(distance)

    complete_changed_fraction = sum(value > epsilon for value in complete_distances) / len(complete_distances)
    supervision_changed_fraction = sum(value > epsilon for value in supervision_distances) / len(supervision_distances)
    supervision_median = statistics.median(supervision_distances)
    eligible_median = statistics.median(eligible_supervision_distances)
    ratio = supervision_median / eligible_median if eligible_median > epsilon else 0.0
    kish_fraction = _kish_effective_fraction(supervision_distances, epsilon)
    per_parent = {
        parent: {
            "candidate_count": len(values),
            "supervision_changed_fraction": sum(value > epsilon for value in values) / len(values),
            "supervision_median_distance": statistics.median(values),
        }
        for parent, values in sorted(per_parent_distances.items())
    }
    minimum_parent_changed = min(value["supervision_changed_fraction"] for value in per_parent.values())

    require(
        complete_changed_fraction >= thresholds["complete_payload_changed_fraction_min"],
        "donor_null_ineffective:complete_payload_changed_fraction",
    )
    require(
        supervision_changed_fraction >= thresholds["supervision_changed_fraction_min"],
        "donor_null_ineffective:supervision_changed_fraction",
    )
    require(
        supervision_median >= thresholds["supervision_median_distance_min"],
        "donor_null_ineffective:supervision_median_distance",
    )
    require(
        ratio >= thresholds["supervision_mapped_to_eligible_median_ratio_min"],
        "donor_null_ineffective:mapped_to_eligible_ratio",
    )
    require(
        kish_fraction >= thresholds["supervision_kish_effective_fraction_min"],
        "donor_null_ineffective:kish_effective_fraction",
    )
    require(
        minimum_parent_changed >= thresholds["per_parent_supervision_changed_fraction_min"],
        "donor_null_ineffective:per_parent_changed_fraction",
    )
    return {
        "schema_version": "pvrig_v2_5_contact_donor_payload_power_audit_v1_1",
        "status": "PASS_EFFECTIVE_CONTACT_DONOR_NULL",
        "partition_id": partition_id,
        "candidate_count": len(rows),
        "parent_count": len(grouped),
        "complete_payload_changed_fraction": complete_changed_fraction,
        "supervision_changed_fraction": supervision_changed_fraction,
        "supervision_mean_distance": statistics.fmean(supervision_distances),
        "supervision_median_distance": supervision_median,
        "supervision_q10_distance": _quantile(supervision_distances, 0.10),
        "supervision_q25_distance": _quantile(supervision_distances, 0.25),
        "eligible_supervision_median_distance": eligible_median,
        "supervision_mapped_to_eligible_median_ratio": ratio,
        "supervision_kish_effective_fraction": kish_fraction,
        "per_parent": per_parent,
        "donor_map_sha256": _donor_map_sha256(donor_map),
        "thresholds": dict(thresholds),
        "uses_scalar_truth": False,
        "uses_heldout_rows": False,
    }


def omit_contact_meta_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    """Remove contact-score predictors for the no-contact meta challenger."""
    result = {key: _clone_value(value) for key, value in row.items() if key not in CONTACT_SCORE_FIELDS}
    require(not any(field in result for field in CONTACT_SCORE_FIELDS), "contact_omission_failed")
    return result


def exact_min_predictions(r8: Sequence[float], r9: Sequence[float]) -> list[float]:
    require(len(r8) == len(r9), "exact_min_length")
    return [min(float(left), float(right)) for left, right in zip(r8, r9)]
