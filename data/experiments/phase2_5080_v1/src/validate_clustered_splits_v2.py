#!/usr/bin/env python3
"""Validate Phase 2 clustered site/pair/contact split manifests.

The validator is intentionally independent of the training scripts.  It checks
split hygiene and label/source invariants from the materialized manifests only.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

SPLITS = ("train", "val", "test")
LABEL_MAP = {
    "": "unlabeled",
    "-1": "unknown",
    "0": "negative",
    "1": "positive",
    "negative": "negative",
    "neg": "negative",
    "positive": "positive",
    "pos": "positive",
    "unknown": "unknown",
    "unk": "unknown",
    "ambiguous": "unknown",
    "observed_positive": "positive",
    "observed_negative": "negative",
    "constructed_negative": "negative",
    "unlabeled": "unlabeled",
    "unlabeled_contrastive": "unlabeled",
}
DEFAULT_RATIO_BOUNDS = {
    "train": (0.55, 0.85),
    "val": (0.05, 0.30),
    "test": (0.05, 0.30),
}
CLUSTER_FIELDS = ("vhh_cluster_id", "cdr3_proxy_cluster_id", "antigen_cluster_id", "split_group_id")


@dataclass
class Check:
    name: str
    passed: bool
    evidence: str
    severity: str = "error"


@dataclass
class ManifestStats:
    name: str
    path: str
    rows: int = 0
    split_counts: dict[str, int] = field(default_factory=dict)
    ratios: dict[str, float] = field(default_factory=dict)
    vhh_sequences: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    antigen_sequences: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    partition_values: dict[str, dict[str, set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    label_states: set[str] = field(default_factory=set)
    label_sources: Counter[str] = field(default_factory=Counter)
    source_fields: dict[str, int] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "rows": self.rows,
            "split_counts": dict(self.split_counts),
            "ratios": self.ratios,
            "unique_vhh_by_split": {k: len(v) for k, v in self.vhh_sequences.items()},
            "unique_antigen_by_split": {k: len(v) for k, v in self.antigen_sequences.items()},
            "unique_partition_values_by_split": {
                field_name: {split: len(values) for split, values in by_split.items()}
                for field_name, by_split in self.partition_values.items()
            },
            "label_states": sorted(self.label_states),
            "label_sources": dict(self.label_sources),
            "source_fields": self.source_fields,
            "extra": self.extra,
        }


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."}:
        return ""
    return text


def normalize_label(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    if text in {"nan", "none", "na", "n/a", "?", "."}:
        text = ""
    return LABEL_MAP.get(text, f"invalid:{text or '<empty>'}")


def normalize_pair_label(row: dict[str, Any]) -> str:
    label = normalize_label(row.get("binding_label"))
    if label != "unlabeled":
        return label
    label_state = normalize_label(row.get("label_state"))
    if label_state != "unlabeled":
        return label_state
    contrastive = normalize_label(row.get("contrastive_target"))
    if contrastive in {"positive", "negative"}:
        return "unlabeled" if clean(row.get("ordinary_bce_eligible")).lower() == "no" else contrastive
    return label


def resolve_path(root: Path, explicit: str | None, candidates: list[str], label: str) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else root / path
    matches: list[Path] = []
    for pattern in candidates:
        matches.extend(root.glob(pattern))
    matches = sorted(
        {p for p in matches if p.is_file() and p.stat().st_size > 0},
        key=lambda p: (p.stat().st_mtime, str(p)),
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(f"No {label} manifest found under {root}")
    return matches[0]


def read_table(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                row["_line_no"] = line_no
                yield row
        return
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row_no, row in enumerate(reader, start=2):
            row["_line_no"] = row_no
            yield row


def add_sequence(stats: ManifestStats, row: dict[str, Any], split: str) -> None:
    vhh = clean(row.get("vhh_seq") or row.get("sequence_vhh") or row.get("nanobody_seq") or row.get("sequence"))
    antigen = clean(row.get("antigen_seq") or row.get("sequence_antigen"))
    if vhh:
        stats.vhh_sequences[split].add(vhh)
    if antigen:
        stats.antigen_sequences[split].add(antigen)


def load_manifest(name: str, path: Path) -> tuple[ManifestStats, list[Check]]:
    checks: list[Check] = []
    stats = ManifestStats(name=name, path=str(path))
    missing_split_rows: list[str] = []
    missing_vhh_rows: list[str] = []
    missing_antigen_rows: list[str] = []
    invalid_split_rows: list[str] = []
    positive_pairs = 0
    negative_pairs = 0
    missing_partition_fields: dict[str, list[str]] = defaultdict(list)

    for row in read_table(path):
        stats.rows += 1
        split = clean(row.get("split")).lower()
        row_id = clean(row.get("sample_id") or row.get("pair_id") or row.get("complex_id") or row.get("_line_no"))
        if not split:
            missing_split_rows.append(row_id)
            continue
        if split not in SPLITS:
            invalid_split_rows.append(f"{row_id}:{split}")
            continue
        stats.split_counts[split] = stats.split_counts.get(split, 0) + 1
        row_vhh = clean(row.get("vhh_seq") or row.get("sequence_vhh") or row.get("nanobody_seq") or row.get("sequence"))
        row_antigen = clean(row.get("antigen_seq") or row.get("sequence_antigen"))
        add_sequence(stats, row, split)
        for field_name in CLUSTER_FIELDS:
            value = clean(row.get(field_name))
            if value:
                stats.partition_values[field_name][split].add(value)
            else:
                missing_partition_fields[field_name].append(row_id)
        structure_id = clean(row.get("pdb_id") or row.get("pdb")).lower()
        if structure_id:
            stats.partition_values["pdb_id"][split].add(structure_id)
        if not row_vhh:
            missing_vhh_rows.append(row_id)
        if name != "site" and not row_antigen:
            missing_antigen_rows.append(row_id)
        if "binding_label" in row:
            stats.label_states.add(normalize_label(row.get("binding_label")))
        label_source = clean(row.get("label_source"))
        if label_source:
            stats.label_sources[label_source] += 1
        for key in ("source_dataset", "source_file", "source_row", "label_source", "negative_type", "construction_rule"):
            if key in row and clean(row.get(key)):
                stats.source_fields[key] = stats.source_fields.get(key, 0) + 1
        if "positive_pairs" in row:
            try:
                positive_pairs += int(row.get("positive_pairs") or 0)
            except (TypeError, ValueError):
                pass
        if "negative_pairs" in row:
            try:
                negative_pairs += int(row.get("negative_pairs") or 0)
            except (TypeError, ValueError):
                pass

    if stats.rows:
        stats.ratios = {split: stats.split_counts.get(split, 0) / stats.rows for split in SPLITS}
    if positive_pairs or negative_pairs:
        stats.extra["positive_pairs"] = positive_pairs
        stats.extra["negative_pairs"] = negative_pairs

    checks.append(Check(f"{name}_manifest_present", path.exists() and path.stat().st_size > 0, f"path={path} rows={stats.rows}"))
    checks.append(Check(f"{name}_rows_nonempty", stats.rows > 0, f"rows={stats.rows}"))
    checks.append(
        Check(
            f"{name}_split_values_valid",
            not missing_split_rows and not invalid_split_rows,
            f"missing={missing_split_rows[:5]} invalid={invalid_split_rows[:5]}",
        )
    )
    checks.append(
        Check(
            f"{name}_split_nonempty",
            all(stats.split_counts.get(split, 0) > 0 for split in SPLITS),
            json.dumps(stats.split_counts, ensure_ascii=False, sort_keys=True),
        )
    )
    ratio_failures = [
        f"{split}={stats.ratios.get(split, 0):.3f} not in [{lo:.2f},{hi:.2f}]"
        for split, (lo, hi) in DEFAULT_RATIO_BOUNDS.items()
        if stats.rows and not (lo <= stats.ratios.get(split, 0) <= hi)
    ]
    checks.append(Check(f"{name}_split_ratios_reasonable", not ratio_failures, "; ".join(ratio_failures) or json.dumps(stats.ratios, sort_keys=True)))
    checks.append(Check(f"{name}_vhh_sequences_present", not missing_vhh_rows and any(stats.vhh_sequences.values()), f"missing_rows={missing_vhh_rows[:5]}"))
    checks.append(Check(f"{name}_antigen_sequences_present", name == "site" or (not missing_antigen_rows and any(stats.antigen_sequences.values())), f"missing_rows={missing_antigen_rows[:5]}"))
    for field_name in CLUSTER_FIELDS:
        missing = missing_partition_fields[field_name]
        checks.append(
            Check(
                f"{name}_{field_name}_complete",
                not missing,
                f"missing_rows={missing[:5]} count={len(missing)}",
            )
        )
    if name == "contact" and (positive_pairs or negative_pairs):
        checks.append(Check("contact_positive_and_negative_pairs_nonempty", positive_pairs > 0 and negative_pairs > 0, f"positive_pairs={positive_pairs} negative_pairs={negative_pairs}"))
    return stats, checks


def overlap_checks(stats_by_name: dict[str, ManifestStats]) -> list[Check]:
    checks: list[Check] = []
    combined_vhh: dict[str, set[str]] = defaultdict(set)
    combined_antigen: dict[str, set[str]] = defaultdict(set)
    combined_partitions: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for stats in stats_by_name.values():
        for split in SPLITS:
            combined_vhh[split].update(stats.vhh_sequences.get(split, set()))
            combined_antigen[split].update(stats.antigen_sequences.get(split, set()))
            for field_name, by_split in stats.partition_values.items():
                combined_partitions[field_name][split].update(by_split.get(split, set()))
        for kind, seqs_by_split in (("vhh", stats.vhh_sequences), ("antigen", stats.antigen_sequences)):
            overlaps = {}
            for left, right in combinations(SPLITS, 2):
                shared = seqs_by_split.get(left, set()) & seqs_by_split.get(right, set())
                if shared:
                    overlaps[f"{left}_vs_{right}"] = len(shared)
            checks.append(Check(f"{stats.name}_exact_{kind}_overlap_zero", not overlaps, json.dumps(overlaps, sort_keys=True) if overlaps else "all pairwise overlaps=0"))
        for field_name, values_by_split in stats.partition_values.items():
            overlaps = {}
            for left, right in combinations(SPLITS, 2):
                shared = values_by_split.get(left, set()) & values_by_split.get(right, set())
                if shared:
                    overlaps[f"{left}_vs_{right}"] = len(shared)
            checks.append(
                Check(
                    f"{stats.name}_{field_name}_overlap_zero",
                    not overlaps,
                    json.dumps(overlaps, sort_keys=True) if overlaps else "all pairwise overlaps=0",
                )
            )
    for kind, seqs_by_split in (("vhh", combined_vhh), ("antigen", combined_antigen)):
        overlaps = {}
        for left, right in combinations(SPLITS, 2):
            shared = seqs_by_split.get(left, set()) & seqs_by_split.get(right, set())
            if shared:
                overlaps[f"{left}_vs_{right}"] = len(shared)
        checks.append(Check(f"combined_exact_{kind}_overlap_zero", not overlaps, json.dumps(overlaps, sort_keys=True) if overlaps else "all pairwise overlaps=0"))
    for field_name, values_by_split in combined_partitions.items():
        overlaps = {}
        for left, right in combinations(SPLITS, 2):
            shared = values_by_split.get(left, set()) & values_by_split.get(right, set())
            if shared:
                overlaps[f"{left}_vs_{right}"] = len(shared)
        checks.append(
            Check(
                f"combined_{field_name}_overlap_zero",
                not overlaps,
                json.dumps(overlaps, sort_keys=True) if overlaps else "all pairwise overlaps=0",
            )
        )
    return checks


def pair_checks(pair_stats: ManifestStats, pair_path: Path) -> list[Check]:
    checks: list[Check] = []
    invalid_labels: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    missing_label_source = 0
    missing_source_detail = 0
    for row in read_table(pair_path):
        label = normalize_pair_label(row)
        if label.startswith("invalid:"):
            invalid_labels[label] += 1
        else:
            label_counts[label] += 1
        if not clean(row.get("label_source")):
            missing_label_source += 1
        if not (clean(row.get("source_dataset")) or clean(row.get("source_file")) or clean(row.get("construction_rule"))):
            missing_source_detail += 1
    checks.append(Check("pair_labels_are_tristate_domain", not invalid_labels and set(label_counts).issubset({"positive", "negative", "unlabeled", "unknown"}), json.dumps(invalid_labels, sort_keys=True) if invalid_labels else json.dumps(label_counts, sort_keys=True)))
    checks.append(
        Check(
            "pair_has_positive_and_nonpositive_supervision_state",
            label_counts["positive"] > 0 and (label_counts["negative"] > 0 or label_counts["unlabeled"] > 0 or label_counts["unknown"] > 0),
            json.dumps(label_counts, sort_keys=True),
        )
    )
    checks.append(Check("pair_label_source_complete", missing_label_source == 0, f"missing_label_source_rows={missing_label_source}"))
    checks.append(Check("pair_source_detail_complete", missing_source_detail == 0, f"missing_source_detail_rows={missing_source_detail}"))
    pair_stats.extra["pair_label_counts"] = dict(label_counts)
    return checks


def load_pvrig_controls(path: Path) -> tuple[set[str], list[Check], dict[str, Any]]:
    checks: list[Check] = []
    sequences: set[str] = set()
    rows = 0
    ordinary_split_rows: list[str] = []
    bad_policy_rows: list[str] = []
    for row in read_table(path):
        rows += 1
        row_id = clean(row.get("sample_id") or row.get("_line_no"))
        seq = clean(row.get("sequence") or row.get("vhh_seq"))
        if seq:
            sequences.add(seq)
        split = clean(row.get("split")).lower()
        role = clean(row.get("role")).lower()
        label_hint = clean(row.get("label_hint")).lower()
        policy = clean(row.get("leakage_policy")).lower()
        is_control_row = (
            "control" in role
            or "control" in label_hint
            or "known_positive" in role
            or "known_positive" in label_hint
            or "calibration" in role
            or "exact_known" in label_hint
            or "near_known" in label_hint
            or "positive_blocking" in label_hint
        )
        if split in SPLITS:
            ordinary_split_rows.append(f"{row_id}:{split}")
        if is_control_row and "exclude" not in policy and "hold" not in policy and "calibration" not in role:
            bad_policy_rows.append(row_id)
    checks.append(Check("pvrig_controls_manifest_present", path.exists() and path.stat().st_size > 0, f"path={path} rows={rows}"))
    checks.append(Check("pvrig_controls_not_marked_as_ordinary_split", not ordinary_split_rows, f"ordinary_split_rows={ordinary_split_rows[:5]}"))
    checks.append(Check("pvrig_controls_have_exclusion_or_calibration_policy", not bad_policy_rows, f"bad_policy_rows={bad_policy_rows[:5]}"))
    return sequences, checks, {"path": str(path), "rows": rows, "unique_sequences": len(sequences)}


def pvrig_leakage_checks(control_sequences: set[str], stats_by_name: dict[str, ManifestStats]) -> list[Check]:
    checks: list[Check] = []
    for stats in stats_by_name.values():
        train_hits = stats.vhh_sequences.get("train", set()) & control_sequences
        checks.append(Check(f"{stats.name}_pvrig_controls_absent_from_train_vhh", not train_hits, f"train_control_hits={len(train_hits)}"))
    combined_train = set().union(*(stats.vhh_sequences.get("train", set()) for stats in stats_by_name.values()))
    hits = combined_train & control_sequences
    checks.append(Check("combined_pvrig_controls_absent_from_ordinary_training", not hits, f"train_control_hits={len(hits)}"))
    return checks


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Clustered Split V2 Validation",
        "",
        f"Verdict: {result['status']}",
        "",
        "## Manifests",
        "",
        "| Manifest | Rows | Split counts | Ratios |",
        "| --- | ---: | --- | --- |",
    ]
    for manifest in result["manifests"].values():
        lines.append(
            f"| {manifest['name']} | {manifest['rows']} | `{json.dumps(manifest['split_counts'], sort_keys=True)}` | `{json.dumps(manifest['ratios'], sort_keys=True)}` |"
        )
    lines.extend(["", "## Checks", "", "| Check | Status | Evidence |", "| --- | --- | --- |"])
    for check in result["checks"]:
        evidence = str(check["evidence"]).replace("|", "/").replace("\n", " ")[:900]
        lines.append(f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | `{evidence}` |")
    if result["failed_checks"]:
        lines.extend(["", "## Failed Checks", ""])
        lines.extend(f"- {name}" for name in result["failed_checks"])
    return "\n".join(lines) + "\n"


def validate(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    base = root / "experiments/phase2_5080_v1"
    site_path = resolve_path(root, args.site, ["experiments/phase2_5080_v1/data_splits/*site*split*.csv", "experiments/phase2_5080_v1/data_splits/*site*manifest*.csv"], "site")
    pair_path = resolve_path(root, args.pair, ["experiments/phase2_5080_v1/data_splits/*pair*split*.csv", "experiments/phase2_5080_v1/data_splits/*pair*manifest*.csv"], "pair")
    contact_path = resolve_path(
        root,
        args.contact,
        [
            "experiments/phase2_5080_v1/prepared/*contact*cluster*.jsonl",
            "experiments/phase2_5080_v1/prepared/*contact*full*.jsonl",
            "experiments/phase2_5080_v1/prepared/*contact*.jsonl",
        ],
        "contact",
    )
    controls_path = resolve_path(root, args.pvrig_controls, ["experiments/phase2_5080_v1/data_splits/*pvrig*calibration*.csv", "experiments/phase2_5080_v1/data_splits/*pvrig*control*.csv"], "PVRIG controls")

    checks: list[Check] = []
    stats_by_name: dict[str, ManifestStats] = {}
    for name, path in (("site", site_path), ("pair", pair_path), ("contact", contact_path)):
        stats, manifest_checks = load_manifest(name, path)
        stats_by_name[name] = stats
        checks.extend(manifest_checks)
    checks.extend(overlap_checks(stats_by_name))
    checks.extend(pair_checks(stats_by_name["pair"], pair_path))
    controls, control_checks, control_summary = load_pvrig_controls(controls_path)
    checks.extend(control_checks)
    checks.extend(pvrig_leakage_checks(controls, stats_by_name))

    failed = [check.name for check in checks if not check.passed and check.severity == "error"]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "root": str(root),
        "base": str(base),
        "failed_checks": failed,
        "manifests": {name: stats.to_json() for name, stats in stats_by_name.items()},
        "pvrig_controls": control_summary,
        "checks": [check.__dict__ for check in checks],
    }
    return result


def write_output(path_arg: str | None, text: str) -> None:
    if not path_arg:
        return
    if path_arg == "-":
        print(text, end="" if text.endswith("\n") else "\n")
        return
    path = Path(path_arg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository/workspace root containing experiments/phase2_5080_v1")
    parser.add_argument("--site", help="Override site split manifest path")
    parser.add_argument("--pair", help="Override pair split manifest path")
    parser.add_argument("--contact", help="Override contact split JSONL/CSV path")
    parser.add_argument("--pvrig-controls", help="Override PVRIG calibration/control manifest path")
    parser.add_argument("--json-out", default="-", help="JSON output path, '-' for stdout, or omit with empty string")
    parser.add_argument("--markdown-out", help="Markdown output path, '-' for stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate(args)
    except Exception as exc:  # noqa: BLE001 - CLI validator should report hard setup failures as JSON.
        result = {"status": "FAIL", "failed_checks": ["validator_runtime_error"], "error": str(exc), "checks": []}
    write_output(args.json_out, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    write_output(args.markdown_out, render_markdown(result) if "manifests" in result else f"# Clustered Split V2 Validation\n\nVerdict: FAIL\n\n- {result.get('error', 'unknown error')}\n")
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
