#!/usr/bin/env python3
"""Build exact-sequence CDR type masks for Phase 2.3 VHH inputs.

The output is one row per unique VHH sequence hash across the strict site,
pair, and contact manifests. Exact local CDR annotations are preferred; a
simple motif heuristic is used only when no valid exact annotation exists.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SITE_MANIFEST = ROOT / "experiments/phase2_5080_v1/data_splits/zym_site_split_manifest_v2_clustered.csv"
DEFAULT_PAIR_MANIFEST = ROOT / "experiments/phase2_5080_v1/data_splits/pair_binding_split_v2_clustered.csv"
DEFAULT_CONTACT_MANIFEST = ROOT / "experiments/phase2_5080_v1/prepared/structure_contact_maps_v3_clustered.jsonl"
DEFAULT_INDEX = ROOT / "model_data/index_v0_samples.csv"
DEFAULT_CANDIDATES = ROOT / "model_data/mvp_candidates_v0.csv"
DEFAULT_OUTPUT = ROOT / "experiments/phase2_5080_v1/data_splits/vhh_cdr_type_masks_v2_3.csv"
AA_PATTERN = re.compile(r"^[A-Z]+$")


class CdrAnnotation(NamedTuple):
    cdr1: str
    cdr2: str
    cdr3: str
    source: str


class MaskBuildResult(NamedTuple):
    mask: list[int]
    spans: dict[str, list[int]]
    cdrs: dict[str, str]
    source: str
    status: str
    fallback_reason: str


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper().replace(" ", "")
    if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."}:
        return ""
    return text


def sequence_hash(seq: str) -> str:
    return hashlib.sha256(seq.encode("utf-8")).hexdigest()


def parse_span(raw: str) -> tuple[int, int] | None:
    text = clean(raw)
    if not text:
        return None
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if len(nums) < 2:
        return None
    start, end = nums[0], nums[1]
    if end < start:
        return None
    return start, end


def locate_unique_substring(seq: str, fragment: str) -> tuple[int, int] | None:
    if not fragment:
        return None
    first = seq.find(fragment)
    if first < 0:
        return None
    if seq.find(fragment, first + 1) >= 0:
        return None
    return first, first + len(fragment)


def resolve_span(seq: str, fragment: str, explicit_span: tuple[int, int] | None) -> tuple[int, int] | None:
    if explicit_span is not None:
        start, end = explicit_span
        if 0 <= start < end <= len(seq) and seq[start:end] == fragment:
            return start, end
        # Some local sources use inclusive end coordinates; accept only if exact.
        if 0 <= start <= end < len(seq) and seq[start : end + 1] == fragment:
            return start, end + 1
        return None
    return locate_unique_substring(seq, fragment)


def validate_spans(seq: str, cdrs: dict[str, str], spans: dict[str, tuple[int, int]]) -> str:
    required = ("cdr1", "cdr2", "cdr3")
    if any(not cdrs.get(name) for name in required):
        return "missing_cdr_sequence"
    if any(name not in spans for name in required):
        return "cdr_substring_missing_or_ambiguous"
    ordered = [spans[name] for name in required]
    if any(start < 0 or end > len(seq) or start >= end for start, end in ordered):
        return "span_out_of_bounds"
    if any(seq[start:end] != cdrs[name] for name, (start, end) in spans.items()):
        return "span_substring_mismatch"
    if not (ordered[0][1] <= ordered[1][0] and ordered[1][1] <= ordered[2][0]):
        return "cdr_spans_overlap_or_out_of_order"
    return "ok"


def build_mask(seq: str, spans: dict[str, tuple[int, int]]) -> list[int]:
    mask = [0] * len(seq)
    for value, name in enumerate(("cdr1", "cdr2", "cdr3"), start=1):
        start, end = spans[name]
        for idx in range(start, end):
            mask[idx] = value
    return mask


def annotation_from_row(row: dict[str, str], source_name: str) -> CdrAnnotation | None:
    cdr1 = clean(row.get("cdr1_seq")) or clean(row.get("cdr1"))
    cdr2 = clean(row.get("cdr2_seq")) or clean(row.get("cdr2"))
    cdr3 = clean(row.get("cdr3_seq")) or clean(row.get("cdr3"))
    if not (cdr1 and cdr2 and cdr3):
        return None
    return CdrAnnotation(cdr1, cdr2, cdr3, source_name)


def spans_from_row(seq: str, row: dict[str, str], ann: CdrAnnotation) -> dict[str, tuple[int, int]] | None:
    cdrs = {"cdr1": ann.cdr1, "cdr2": ann.cdr2, "cdr3": ann.cdr3}
    spans: dict[str, tuple[int, int]] = {}
    for name in ("cdr1", "cdr2", "cdr3"):
        span = resolve_span(seq, cdrs[name], parse_span(row.get(f"{name}_span_0based", "")))
        if span is None:
            return None
        spans[name] = span
    return spans


def exact_annotation_result(seq: str, row: dict[str, str], source_name: str) -> MaskBuildResult | None:
    ann = annotation_from_row(row, source_name)
    if ann is None:
        return None
    cdrs = {"cdr1": ann.cdr1, "cdr2": ann.cdr2, "cdr3": ann.cdr3}
    spans = spans_from_row(seq, row, ann)
    if spans is None:
        return None
    status = validate_spans(seq, cdrs, spans)
    if status != "ok":
        return None
    return MaskBuildResult(
        mask=build_mask(seq, spans),
        spans={name: [start, end] for name, (start, end) in spans.items()},
        cdrs=cdrs,
        source=source_name,
        status="exact_annotation",
        fallback_reason="",
    )


def load_exact_annotations(paths: Iterable[tuple[Path, str]]) -> dict[str, MaskBuildResult]:
    annotations: dict[str, MaskBuildResult] = {}
    for path, source_name in paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                seq = clean(row.get("vhh_seq"))
                if not seq or seq in annotations:
                    continue
                result = exact_annotation_result(seq, row, source_name)
                if result is not None:
                    annotations[seq] = result
    return annotations


def find_after(seq: str, motifs: Iterable[str], start: int = 0) -> tuple[int, str] | None:
    hits = [(seq.find(motif, start), motif) for motif in motifs]
    hits = [(idx, motif) for idx, motif in hits if idx >= 0]
    if not hits:
        return None
    return min(hits, key=lambda item: item[0])


def heuristic_result(seq: str, reason: str) -> MaskBuildResult:
    """Infer Kabat-like VHH CDR spans from conserved local sequence motifs."""
    try:
        c1_cys = seq.find("C", 15)
        early_cys = seq.find("C")
        if c1_cys < 0 or (0 <= early_cys < 25):
            c1_cys = early_cys
        if c1_cys < 0:
            raise ValueError("missing_cdr1_cysteine_motif")
        c1_start = c1_cys + 1
        for prefix in ("AAS", "TAS", "AS"):
            if seq.startswith(prefix, c1_start):
                c1_start += len(prefix)
                break
        w1 = find_after(seq, ("WFR", "WYR", "WVR", "WVK", "WVL", "WLR", "WQR", "WIR", "WNW", "WMH", "WMR", "WYH", "WAW"), c1_start + 5)
        if w1 is None:
            raise ValueError("missing_fr2_w_motif_after_cdr1")
        c1_end = w1[0]

        c2_end = find_after(
            seq,
            ("YYADSV", "YADSV", "SADSV", "ADSV", "YADPV", "ADPV", "YTAPV", "TAPV", "SDSVK", "SSVK", "ASSVK", "WAKGR", "AKGR", "KGRFT", "RFTIS", "TISRD", "ISRD", "KSKAT", "VSVKS", "AVSVK", "VKSR", "KSRIT", "SLVTIS", "LVTIS", "LTVDK"),
            w1[0] + 12,
        )
        if c2_end is None:
            raise ValueError("missing_fr3_motif_after_cdr2")
        c2_anchor_motifs = (
            "QEREAVAA", "EREAVAA", "DERVAV", "GREFVAA", "EREFVA", "DERVAI", "DERVAS", "GREVSC",
            "QRELVSR", "QPELIAT", "QRGMVAI", "KQRELVSR", "KQPELIAT", "KQRGMVAI",
            "GKGLEWIG", "QGLEWIG", "GLEWIG", "GKGLEWVS", "GLEWVS", "GREWVS", "EREWVA",
            "EGVAA", "EGVAI", "EGVAT", "EGVSC", "EWVST", "EWVAR", "EWVAA", "EWVSG",
            "AREGVA", "GKGLEW", "QGLEW", "GLEWV", "GREWV", "SLEVISY", "LEVISY", "LEWIG", "EWLG", "EWIG", "EWV",
        )
        anchors = []
        for motif in c2_anchor_motifs:
            idx = seq.find(motif, w1[0] + 6, c2_end[0])
            if idx >= 0:
                anchors.append((idx + len(motif), motif))
        if anchors:
            c2_start = max(anchors)[0]
        else:
            # Last-resort auditable window: use the conserved FR3 boundary and keep a CDR2-sized segment upstream.
            c2_start = max(w1[0] + len(w1[1]) + 8, c2_end[0] - 12)
            if c2_start >= c2_end[0]:
                raise ValueError("missing_cdr2_start_motif")

        c3_cys = seq.rfind("YYC")
        c3_offset = 3
        if c3_cys < c2_end[0]:
            c3_cys = seq.rfind("YHC")
            c3_offset = 3
        if c3_cys < c2_end[0]:
            c3_cys = seq.rfind("YC")
            c3_offset = 2
        if c3_cys < c2_end[0]:
            c3_cys = seq.rfind("C", c2_end[0])
            c3_offset = 1
        if c3_cys < c2_end[0]:
            c3_cys = seq.rfind("YYV")
            c3_offset = 3
        if c3_cys < c2_end[0]:
            raise ValueError("missing_cdr3_cysteine_motif")
        c3_end = find_after(seq, ("WGQG", "WGKG", "FGQG", "WGRG", "WGAG", "WGPG", "RGQG", "GQGT", "GQG", "GTQV", "QVTV", "WGPGT", "GPGT", "TLVTI"), c3_cys + c3_offset + 3)
        if c3_end is None:
            raise ValueError("missing_fr4_wgqg_like_motif")

        spans = {
            "cdr1": (c1_start, c1_end),
            "cdr2": (c2_start, c2_end[0]),
            "cdr3": (c3_cys + c3_offset, c3_end[0]),
        }
        cdrs = {name: seq[start:end] for name, (start, end) in spans.items()}
        status = validate_spans(seq, cdrs, spans)
        if status != "ok":
            raise ValueError(status)
        return MaskBuildResult(
            mask=build_mask(seq, spans),
            spans={name: [start, end] for name, (start, end) in spans.items()},
            cdrs=cdrs,
            source="motif_heuristic_v2_3",
            status="heuristic_fallback",
            fallback_reason=reason,
        )
    except ValueError as exc:
        return MaskBuildResult(
            mask=[0] * len(seq),
            spans={},
            cdrs={"cdr1": "", "cdr2": "", "cdr3": ""},
            source="motif_heuristic_v2_3",
            status="unresolved",
            fallback_reason=f"{reason}; heuristic_failed:{exc}",
        )


def iter_csv_sequences(path: Path, field: str = "vhh_seq") -> Iterable[str]:
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            seq = clean(row.get(field))
            if seq:
                yield seq


def iter_jsonl_sequences(path: Path, field: str = "vhh_seq") -> Iterable[str]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            seq = clean(json.loads(line).get(field))
            if seq:
                yield seq


def collect_manifest_sequences(
    site_manifest: Path,
    pair_manifest: Path,
    contact_manifest: Path,
    inference_candidates: Path | None = None,
    generic_binding_csv: Path | None = None,
) -> dict[str, set[str]]:
    sources: dict[str, set[str]] = defaultdict(set)
    for seq in iter_csv_sequences(site_manifest):
        sources[seq].add("site")
    for seq in iter_csv_sequences(pair_manifest):
        sources[seq].add("pair")
    for seq in iter_jsonl_sequences(contact_manifest):
        sources[seq].add("contact")
    if inference_candidates is not None:
        for seq in iter_csv_sequences(inference_candidates):
            sources[seq].add("pvrig_inference")
    if generic_binding_csv is not None:
        for seq in iter_csv_sequences(generic_binding_csv, field="vhh_sequence"):
            sources[seq].add("generic_real_binding")
    return sources


def build_row(seq: str, manifest_sources: set[str], exact: dict[str, MaskBuildResult]) -> dict[str, str]:
    result = exact.get(seq)
    if result is None:
        result = heuristic_result(seq, "no_valid_exact_local_annotation")
    if len(result.mask) != len(seq):
        raise AssertionError(f"mask length mismatch for {sequence_hash(seq)}")
    spans_json = json.dumps(result.spans, sort_keys=True, separators=(",", ":"))
    return {
        "sequence_hash": sequence_hash(seq),
        "vhh_seq": seq,
        "vhh_len": str(len(seq)),
        "cdr_mask_json": json.dumps(result.mask, separators=(",", ":")),
        "spans_json": spans_json,
        "cdr1_seq": result.cdrs.get("cdr1", ""),
        "cdr2_seq": result.cdrs.get("cdr2", ""),
        "cdr3_seq": result.cdrs.get("cdr3", ""),
        "annotation_source": result.source,
        "status": result.status,
        "fallback_reason": result.fallback_reason,
        "manifest_sources_json": json.dumps(sorted(manifest_sources), separators=(",", ":")),
    }


def write_manifest(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sequence_hash",
        "vhh_seq",
        "vhh_len",
        "cdr_mask_json",
        "spans_json",
        "cdr1_seq",
        "cdr2_seq",
        "cdr3_seq",
        "annotation_source",
        "status",
        "fallback_reason",
        "manifest_sources_json",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_manifest(
    site_manifest: Path,
    pair_manifest: Path,
    contact_manifest: Path,
    index: Path,
    candidates: Path,
    output: Path,
    generic_binding_csv: Path | None = None,
) -> dict[str, int]:
    manifest_sources = collect_manifest_sequences(
        site_manifest,
        pair_manifest,
        contact_manifest,
        candidates,
        generic_binding_csv,
    )
    exact = load_exact_annotations(((index, "model_data/index_v0_samples.csv"), (candidates, "reports/mvp_pvrig_top_candidates_v0.csv")))
    rows = [build_row(seq, manifest_sources[seq], exact) for seq in sorted(manifest_sources, key=sequence_hash)]
    write_manifest(rows, output)
    counts: dict[str, int] = {"rows": len(rows)}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-manifest", type=Path, default=DEFAULT_SITE_MANIFEST)
    parser.add_argument("--pair-manifest", type=Path, default=DEFAULT_PAIR_MANIFEST)
    parser.add_argument("--contact-manifest", type=Path, default=DEFAULT_CONTACT_MANIFEST)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--generic-binding-csv",
        type=Path,
        help="Optional real-label binding CSV with a vhh_sequence column.",
    )
    args = parser.parse_args()
    counts = build_manifest(
        args.site_manifest,
        args.pair_manifest,
        args.contact_manifest,
        args.index,
        args.candidates,
        args.output,
        args.generic_binding_csv,
    )
    print(json.dumps({"output": str(args.output), **counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
