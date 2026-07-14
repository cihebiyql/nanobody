#!/usr/bin/env python3
"""Build the fixed 128-candidate PVRIG V3 redocking panel."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Keep this script runnable both as ``python scripts/...`` and from tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import atomic_write_text, project_root, read_json, read_tsv, sha256_file, write_json, write_tsv  # noqa: E402

DEFAULT_SOURCE_ROOT = Path("/mnt/d/work/抗体/node1/rfantibody_pvrig_docking1024_v2_20260712")
PANEL_ID = "fixed128_v1"
ALGORITHM = "fixed128_deterministic_v1"
SOURCE_FILES = {
    "candidates": Path("data/candidates.tsv"),
    "docking_pose_consensus": Path("data/docking_pose_consensus.tsv"),
    "rf2_candidate_gates": Path("data/rf2_candidate_gates.tsv"),
    "sequence_qc": Path("data/sequence_qc.tsv"),
    "ranked_blocker_geometry_candidates": Path("reports/ranked_blocker_geometry_candidates.tsv"),
}
RF2_FORMAL_PASS = "FORMAL_MULTI_SEED_PASS_2OF3_WITH_STRICT_SUPPORT"
RF2_NEAR_PASS = "RF2_NEAR_PASS_CALIBRATION_ONLY"
TIER1 = "TIER_1_DUAL_REFERENCE_A"
TIER2 = "TIER_2_SINGLE_REFERENCE_RECHECK"
TIER3 = "TIER_3_PLAUSIBLE"
TIER4 = "TIER_4_EVIDENCE_ONLY"

PANEL_FIELDS = [
    "panel_rank",
    "panel_id",
    "selection_algorithm",
    "selection_bucket",
    "bucket_rank",
    "candidate_id",
    "source_run_id",
    "sequence_sha256",
    "sequence",
    "sequence_length",
    "valid_sequence",
    "qc_hard_fail",
    "qc_recommendation",
    "candidate_tier",
    "geometry_rank",
    "diverse_panel_rank",
    "rf2_formal_gate_status",
    "rf2_best_interaction_pae",
    "rf2_best_pred_lddt",
    "rf2_recovered_seeds",
    "consensus_a_pose_count",
    "single_baseline_recheck_pose_count",
    "plausible_pose_count",
    "evidence_only_pose_count",
    "representative_model",
    "representative_consensus_class",
    "representative_haddock_rank",
    "representative_haddock_score",
    "best_haddock_score",
    "weakest_hotspot_overlap",
    "weakest_total_occlusion",
    "weakest_cdr3_occlusion",
    "weakest_cdr3_fraction",
    "representative_geometry_margin",
    "arm_id",
    "scaffold_id",
    "h3_regime",
    "backbone_group_id",
    "near_cdr3_family_id",
    "near_cdr3_family_size",
    "cdr1",
    "cdr2",
    "cdr3",
]


class PanelBuildError(RuntimeError):
    """Raised when the fixed panel contract cannot be satisfied."""


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def int_value(row: dict[str, str], key: str, default: int = 10**12) -> int:
    value = row.get(key, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise PanelBuildError(f"non-integer {key}={value!r} for {row.get('candidate_id', '<unknown>')}") from exc


def row_sort_key(row: dict[str, str]) -> tuple[int, str]:
    return (int_value(row, "geometry_rank"), row["candidate_id"])


def rowset_hash(rows: list[dict[str, str]]) -> str:
    canonical_rows = [json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in rows]
    return hashlib.sha256(("\n".join(sorted(canonical_rows)) + "\n").encode("utf-8")).hexdigest()


def load_sources(source_root: Path) -> dict[str, list[dict[str, str]]]:
    loaded: dict[str, list[dict[str, str]]] = {}
    for name, relpath in SOURCE_FILES.items():
        path = source_root / relpath
        if not path.exists():
            raise PanelBuildError(f"missing source file: {path}")
        loaded[name] = read_tsv(path)
    return loaded


def unique_by_candidate(rows: list[dict[str, str]], source_name: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        if not candidate_id:
            raise PanelBuildError(f"missing candidate_id in {source_name}")
        if candidate_id in result:
            raise PanelBuildError(f"duplicate candidate_id in {source_name}: {candidate_id}")
        result[candidate_id] = row
    return result


def sequence_qc_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        sequence = row.get("sequence", "")
        if not sequence:
            raise PanelBuildError("sequence_qc.tsv row missing sequence")
        key = (sequence, hashlib.sha256(sequence.encode("utf-8")).hexdigest())
        if key in result:
            raise PanelBuildError(f"duplicate sequence/sha256 in sequence_qc.tsv: {key[1]}")
        result[key] = row
    return result


def enrich_ranked_rows(sources: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    candidates = unique_by_candidate(sources["candidates"], "candidates.tsv")
    rf2 = unique_by_candidate(sources["rf2_candidate_gates"], "rf2_candidate_gates.tsv")
    qc_by_sequence_sha = sequence_qc_index(sources["sequence_qc"])
    pose_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for pose in sources["docking_pose_consensus"]:
        candidate_id = pose.get("candidate_id", "")
        consensus_class = pose.get("consensus_class", "")
        if not candidate_id or not consensus_class:
            raise PanelBuildError("docking_pose_consensus.tsv row missing candidate_id or consensus_class")
        pose_counts[candidate_id][consensus_class] += 1

    enriched: list[dict[str, str]] = []
    seen: set[str] = set()
    for ranked in sources["ranked_blocker_geometry_candidates"]:
        candidate_id = ranked.get("candidate_id", "")
        if not candidate_id:
            raise PanelBuildError("ranked blocker row missing candidate_id")
        if candidate_id in seen:
            raise PanelBuildError(f"duplicate candidate_id in ranked blocker report: {candidate_id}")
        seen.add(candidate_id)
        candidate = candidates.get(candidate_id)
        gate = rf2.get(candidate_id)
        if candidate is None:
            raise PanelBuildError(f"ranked candidate missing from candidates.tsv: {candidate_id}")
        if gate is None:
            raise PanelBuildError(f"ranked candidate missing from rf2 gates: {candidate_id}")
        sequence = candidate.get("sequence", "")
        sequence_sha256 = candidate.get("sequence_sha256", "")
        if hashlib.sha256(sequence.encode("utf-8")).hexdigest() != sequence_sha256:
            raise PanelBuildError(f"sequence_sha256 mismatch in candidates.tsv: {candidate_id}")
        qc = qc_by_sequence_sha.get((sequence, sequence_sha256))
        if qc is None:
            raise PanelBuildError(f"sequence_qc join failed by sequence/sha256 for {candidate_id}")
        if qc.get("candidate_id", "") == candidate_id:
            raise PanelBuildError(f"sequence_qc unexpectedly joined by candidate_id for {candidate_id}")
        counts = pose_counts.get(candidate_id)
        if counts is None:
            raise PanelBuildError(f"docking poses missing for {candidate_id}")
        expected_pose_counts = {
            "CONSENSUS_BLOCKER_LIKE_A": int_value(ranked, "consensus_a_pose_count", 0),
            "SINGLE_BASELINE_BLOCKER_RECHECK": int_value(ranked, "single_baseline_recheck_pose_count", 0),
            "BLOCKER_PLAUSIBLE_B": int_value(ranked, "plausible_pose_count", 0),
            "EVIDENCE_INFERENCE_ONLY_E": int_value(ranked, "evidence_only_pose_count", 0),
        }
        actual_pose_counts = {name: counts[name] for name in expected_pose_counts}
        if actual_pose_counts != expected_pose_counts:
            raise PanelBuildError(f"docking pose consensus count mismatch for {candidate_id}")
        merged = dict(candidate)
        merged.update(ranked)
        merged["formal_multiseed_gate_status"] = gate.get("formal_multiseed_gate_status", "")
        if merged.get("rf2_formal_gate_status", "") != gate.get("formal_multiseed_gate_status", ""):
            raise PanelBuildError(f"RF2 status mismatch for {candidate_id}")
        merged["qc_hard_fail"] = qc.get("hard_fail", "")
        merged["qc_recommendation"] = qc.get("recommendation", "")
        enriched.append(merged)
    if len(enriched) != len(candidates):
        raise PanelBuildError("ranked blocker report and candidates.tsv have different candidate counts")
    return sorted(enriched, key=row_sort_key)


def is_excluded(row: dict[str, str]) -> bool:
    return row.get("candidate_tier") == TIER4 or truthy(row.get("qc_hard_fail", ""))


def cap_key(row: dict[str, str], cap_name: str) -> str:
    return row.get(cap_name, "")


def check_caps_for_add(row: dict[str, str], counters: dict[str, Counter[str]], caps: dict[str, int]) -> bool:
    for cap_name in ("backbone_group_id", "near_cdr3_family_id", "arm_id", "scaffold_id"):
        key = cap_key(row, cap_name)
        if counters[cap_name][key] >= int(caps[cap_name]):
            return False
    if row.get("h3_regime") == "L" and counters["h3_regime"]["L"] >= int(caps["h3_L_max"]):
        return False
    return True


def add_row(row: dict[str, str], bucket: str, selected: list[dict[str, str]], selected_ids: set[str], counters: dict[str, Counter[str]]) -> None:
    selected_ids.add(row["candidate_id"])
    panel_row = dict(row)
    panel_row["selection_bucket"] = bucket
    selected.append(panel_row)
    for cap_name in ("backbone_group_id", "near_cdr3_family_id", "arm_id", "scaffold_id", "h3_regime"):
        counters[cap_name][cap_key(row, cap_name)] += 1


def assert_current_caps(counters: dict[str, Counter[str]], caps: dict[str, int]) -> None:
    for cap_name in ("backbone_group_id", "near_cdr3_family_id", "arm_id", "scaffold_id"):
        over = {key: count for key, count in counters[cap_name].items() if count > int(caps[cap_name])}
        if over:
            raise PanelBuildError(f"cap exceeded for {cap_name}: {over}")
    if counters["h3_regime"]["L"] > int(caps["h3_L_max"]):
        raise PanelBuildError("h3_L_max cap exceeded")
    if counters["h3_regime"]["S"] < 0:
        raise PanelBuildError("invalid h3 S counter")


def select_bucket(
    rows: list[dict[str, str]],
    bucket: str,
    quota: int,
    selected: list[dict[str, str]],
    selected_ids: set[str],
    counters: dict[str, Counter[str]],
    caps: dict[str, int],
) -> None:
    bucket_start_count = len(selected)
    for row in rows:
        if len(selected) - bucket_start_count >= quota:
            break
        if row["candidate_id"] in selected_ids or is_excluded(row):
            continue
        global_slots_after_this = 128 - len(selected) - 1
        h3_s_needed_after_this = max(0, int(caps["h3_S_min"]) - (counters["h3_regime"]["S"] + (1 if row.get("h3_regime") == "S" else 0)))
        if h3_s_needed_after_this > global_slots_after_this:
            continue
        if not check_caps_for_add(row, counters, caps):
            continue
        add_row(row, bucket, selected, selected_ids, counters)
    actual = len(selected) - bucket_start_count
    if actual != quota:
        raise PanelBuildError(f"could not fill bucket {bucket}: selected {actual}, expected {quota}")


def build_panel(protocol: dict[str, Any], sources: dict[str, list[dict[str, str]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidate_spec = protocol["candidate_panel"]
    quotas = candidate_spec["bucket_quotas"]
    caps = candidate_spec["caps"]
    ranked = enrich_ranked_rows(sources)
    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    counters: dict[str, Counter[str]] = defaultdict(Counter)

    bucket_predicates = [
        ("LOCKED_DUAL_REFERENCE_A", lambda row: row.get("candidate_tier") == TIER1),
        ("RF2_FORMAL_PASS", lambda row: row.get("rf2_formal_gate_status") == RF2_FORMAL_PASS),
        ("RF2_NEAR_PASS", lambda row: row.get("rf2_formal_gate_status") == RF2_NEAR_PASS),
    ]
    for bucket, predicate in bucket_predicates:
        rows = [row for row in ranked if predicate(row) and not is_excluded(row)]
        if len(rows) != int(quotas[bucket]):
            raise PanelBuildError(f"mandatory bucket {bucket} has {len(rows)} rows, expected {quotas[bucket]}")
        for row in rows:
            if row["candidate_id"] in selected_ids:
                raise PanelBuildError(f"candidate selected in more than one mandatory bucket: {row['candidate_id']}")
            add_row(row, bucket, selected, selected_ids, counters)
        assert_current_caps(counters, caps)

    select_bucket(
        [row for row in ranked if row.get("candidate_tier") == TIER2],
        "SINGLE_BASELINE_RECHECK",
        int(quotas["SINGLE_BASELINE_RECHECK"]),
        selected,
        selected_ids,
        counters,
        caps,
    )
    select_bucket(
        [row for row in ranked if row.get("candidate_tier") == TIER3],
        "DIVERSE_PLAUSIBLE",
        int(quotas["DIVERSE_PLAUSIBLE"]),
        selected,
        selected_ids,
        counters,
        caps,
    )

    if len(selected) != int(candidate_spec["expected_count"]):
        raise PanelBuildError(f"panel size {len(selected)} != expected {candidate_spec['expected_count']}")
    if counters["h3_regime"]["S"] < int(caps["h3_S_min"]):
        raise PanelBuildError(f"h3_S_min not satisfied: {counters['h3_regime']['S']} < {caps['h3_S_min']}")
    assert_current_caps(counters, caps)

    selected.sort(key=lambda row: (list(quotas).index(row["selection_bucket"]), row_sort_key(row)))
    bucket_ranks: Counter[str] = Counter()
    panel_rows: list[dict[str, Any]] = []
    for panel_rank, row in enumerate(selected, start=1):
        bucket = row["selection_bucket"]
        bucket_ranks[bucket] += 1
        out = {field: row.get(field, "") for field in PANEL_FIELDS}
        out.update(
            {
                "panel_rank": panel_rank,
                "panel_id": PANEL_ID,
                "selection_algorithm": ALGORITHM,
                "bucket_rank": bucket_ranks[bucket],
                "qc_hard_fail": str(truthy(row.get("qc_hard_fail", ""))),
            }
        )
        panel_rows.append(out)

    summary = {
        "algorithm": ALGORITHM,
        "bucket_counts": dict(sorted(Counter(row["selection_bucket"] for row in panel_rows).items())),
        "cap_counts": {
            "arm_id": dict(sorted(Counter(row["arm_id"] for row in panel_rows).items())),
            "backbone_group_id_max": max(Counter(row["backbone_group_id"] for row in panel_rows).values()),
            "h3_regime": dict(sorted(Counter(row["h3_regime"] for row in panel_rows).items())),
            "near_cdr3_family_id_max": max(Counter(row["near_cdr3_family_id"] for row in panel_rows).values()),
            "scaffold_id": dict(sorted(Counter(row["scaffold_id"] for row in panel_rows).items())),
        },
        "caps": caps,
        "expected_count": candidate_spec["expected_count"],
        "panel_id": PANEL_ID,
        "protocol_id": protocol["protocol_id"],
        "quota_contract": quotas,
        "selected_count": len(panel_rows),
        "source_rowset_hashes": {name: rowset_hash(rows) for name, rows in sorted(sources.items())},
    }
    return panel_rows, summary


def write_sha256_sidecar(path: Path) -> None:
    atomic_write_text(path.with_suffix(path.suffix + ".sha256"), f"{sha256_file(path)}  {path.name}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--protocol", type=Path, default=root / "config/protocol_spec.json")
    parser.add_argument("--output-tsv", type=Path, default=root / "inputs/candidates_128.tsv")
    parser.add_argument("--summary-json", type=Path, default=root / "reports/candidate_panel_summary.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    protocol = read_json(args.protocol)
    sources = load_sources(args.source_root)
    panel_rows, summary = build_panel(protocol, sources)
    write_tsv(args.output_tsv, panel_rows, PANEL_FIELDS)
    summary["output_hashes"] = {
        "candidates_128_tsv_sha256": sha256_file(args.output_tsv),
    }
    write_json(args.summary_json, summary)
    write_sha256_sidecar(args.output_tsv)
    write_sha256_sidecar(args.summary_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
