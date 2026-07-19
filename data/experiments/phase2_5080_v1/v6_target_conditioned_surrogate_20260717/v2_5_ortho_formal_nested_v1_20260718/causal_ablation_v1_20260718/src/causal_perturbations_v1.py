#!/usr/bin/env python3
"""Deterministic, label-safe V2.5 causal perturbations.

These utilities only transform already-open target graphs, open-development
contact supervision, or label-free meta features.  They never open labels,
fit models, inspect V4-F/test32, or launch jobs.
"""
from __future__ import annotations

import copy
import hashlib
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


def omit_contact_meta_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    """Remove contact-score predictors for the no-contact meta challenger."""
    result = {key: _clone_value(value) for key, value in row.items() if key not in CONTACT_SCORE_FIELDS}
    require(not any(field in result for field in CONTACT_SCORE_FIELDS), "contact_omission_failed")
    return result


def exact_min_predictions(r8: Sequence[float], r9: Sequence[float]) -> list[float]:
    require(len(r8) == len(r9), "exact_min_length")
    return [min(float(left), float(right)) for left, right in zip(r8, r9)]
