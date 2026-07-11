#!/usr/bin/env python3
"""Build candidate-level docking summaries from pose and baseline CSV outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

EVIDENCE_BOUNDARY = "computational_pose_qc_proxy_not_binding_or_blocker_proof"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
AA3_TO_1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "SEC": "U",
    "PYL": "O",
}
BASELINE_CLASS_CODES = {
    "A": "A",
    "BLOCKER_LIKE_A": "A",
    "B": "B",
    "BLOCKER_PLAUSIBLE_B": "B",
    "C": "C",
    "BINDER_LIKE_C": "C",
}
CONSENSUS_CLASS_ALIASES = {
    "A": "CONSENSUS_BLOCKER_LIKE_A",
    "BLOCKER_LIKE_A": "CONSENSUS_BLOCKER_LIKE_A",
    "CONSENSUS_BLOCKER_LIKE_A": "CONSENSUS_BLOCKER_LIKE_A",
    "B": "BLOCKER_PLAUSIBLE_B",
    "BLOCKER_PLAUSIBLE_B": "BLOCKER_PLAUSIBLE_B",
    "C": "CONSENSUS_BINDER_LIKE_C",
    "BINDER_LIKE_C": "CONSENSUS_BINDER_LIKE_C",
    "CONSENSUS_BINDER_LIKE_C": "CONSENSUS_BINDER_LIKE_C",
    "SINGLE_BASELINE_BLOCKER_RECHECK": "SINGLE_BASELINE_BLOCKER_RECHECK",
    "DISCORDANT_REDOCK_REQUIRED": "DISCORDANT_REDOCK_REQUIRED",
    "INCOMPLETE": "INCOMPLETE",
}
GENERIC_METRICS = (
    "hotspot_overlap_count",
    "total_vhh_pvrl2_residue_pair_occlusion",
    "cdr3_pvrl2_residue_pair_occlusion",
    "cdr3_occlusion_fraction",
)
OUTPUT_FIELDS = (
    "candidate_id",
    "source_candidate_id",
    "blocker_class",
    "top_model_consensus_class",
    "top_model",
    "baseline_count",
    "baseline_classes",
    *GENERIC_METRICS,
    *(f"top_8x6b_{name}" for name in GENERIC_METRICS),
    *(f"top_9e6y_{name}" for name in GENERIC_METRICS),
    "run_status",
    "import_status",
    "evidence_boundary",
    "source_hashes_json",
    "payload_json",
    "payload_sha256",
)


class SummaryError(ValueError):
    """Input contract violation that should fail the import."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="TSV manifest with candidate_id/source/workdir/hash columns.")
    parser.add_argument("--out-csv", required=True, help="Output finalize-compatible candidate-level CSV.")
    return parser.parse_args(argv)


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle, delimiter=delimiter)]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_FIELDS))
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def require_hash(value: str, label: str) -> None:
    if not HASH_RE.fullmatch(value):
        raise SummaryError(f"{label} must be lowercase 64-hex sha256, got {value!r}")


def baseline_class_code(value: str) -> str:
    return BASELINE_CLASS_CODES.get((value or "").strip().upper(), "")


def canonical_consensus_class(value: str) -> str:
    return CONSENSUS_CLASS_ALIASES.get((value or "").strip().upper(), "")


def recompute_consensus(classes: list[str]) -> str:
    complete = [item for item in classes if item in {"A", "B", "C"}]
    if len(complete) < 2:
        if complete == ["A"]:
            return "SINGLE_BASELINE_BLOCKER_RECHECK"
        return "INCOMPLETE"
    counts = {code: complete.count(code) for code in ("A", "B", "C")}
    if counts["A"] == 2 and counts["C"] == 0:
        return "CONSENSUS_BLOCKER_LIKE_A"
    if counts["A"] and counts["C"]:
        return "DISCORDANT_REDOCK_REQUIRED"
    if counts["A"] == 1 and counts["B"] == 1:
        return "SINGLE_BASELINE_BLOCKER_RECHECK"
    if counts["B"] == 2:
        return "BLOCKER_PLAUSIBLE_B"
    if counts["C"] == 2:
        return "CONSENSUS_BINDER_LIKE_C"
    if counts["B"] and counts["C"]:
        return "DISCORDANT_REDOCK_REQUIRED"
    return "INCOMPLETE"


def first_value(row: dict[str, str], names: Iterable[str]) -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower(), "")
        if value != "":
            return value
    return ""


def float_value(row: dict[str, str], metric: str) -> float | None:
    value = first_value(row, (metric,))
    if value == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise SummaryError(f"bad numeric field {metric}={value!r}") from exc


def fmt_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.12g}"


def pdb_chain_sequence(path: Path, chain: str = "A") -> str:
    residues: dict[tuple[int, str], str] = {}
    with path.open(encoding="ascii", errors="replace") as handle:
        for line in handle:
            if not line.startswith("ATOM  ") or len(line) < 27:
                continue
            if (line[21].strip() or "_") != chain:
                continue
            try:
                resseq = int(line[22:26])
            except ValueError:
                continue
            key = (resseq, line[26].strip())
            resname = line[17:20].strip().upper()
            if resname not in AA3_TO_1:
                raise SummaryError(f"unsupported residue {resname!r} in VHH input PDB: {path}")
            residues.setdefault(key, AA3_TO_1[resname])
    if not residues:
        raise SummaryError(f"no chain {chain} residues in VHH input PDB: {path}")
    return "".join(residues.values())


def bind_input_sequence(
    workdir: Path, source_candidate_id: str, expected_hash: str, source_hashes: dict[str, Any]
) -> str | None:
    pdb_path = workdir / "data" / f"{source_candidate_id}_vhh_chainA.pdb"
    if not pdb_path.is_file():
        return f"missing sequence-bound VHH input PDB: {pdb_path}"
    sequence = pdb_chain_sequence(pdb_path, "A")
    observed_hash = hashlib.sha256(sequence.encode("ascii")).hexdigest()
    source_hashes[str(pdb_path)] = file_sha256(pdb_path)
    source_hashes["input_vhh_sequence_sha256"] = observed_hash
    if observed_hash != expected_hash:
        raise SummaryError(
            f"VHH input PDB sequence hash mismatch for {source_candidate_id}: "
            f"{observed_hash} != {expected_hash}"
        )
    return None


def discover_consensus_path(workdir: Path, filename: str) -> Path | None:
    if filename:
        path = Path(filename)
        if path.is_absolute():
            return path
        for base in (workdir, workdir / "reports"):
            candidate = base / path
            if candidate.exists():
                return candidate
        return workdir / path
    matches = sorted(path for path in (workdir / "reports").glob("*.csv") if "consensus" in path.name.lower())
    if not matches:
        matches = sorted(path for path in workdir.glob("*.csv") if "consensus" in path.name.lower())
    return matches[0] if matches else None


def baseline_path(workdir: Path, source_candidate_id: str, ref: str) -> Path:
    return workdir / "reports" / f"{source_candidate_id}_{ref}_blocker_classification.csv"


def ref_key(path: Path, row: dict[str, str]) -> str:
    ref = first_value(row, ("reference", "baseline", "target", "pdb", "ref")) or path.stem
    text = ref.lower()
    if "8x6b" in text:
        return "8x6b"
    if "9e6y" in text:
        return "9e6y"
    return ""


def read_baselines(
    workdir: Path, source_candidate_id: str, expected_hash: str, top_model: str
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    baselines: list[dict[str, Any]] = []
    hashes: list[str] = []
    for ref in ("8x6b", "9e6y"):
        path = baseline_path(workdir, source_candidate_id, ref)
        if not path.exists():
            return baselines, hashes, f"missing baseline classification CSV: {path}"
        rows = read_csv(path)
        hashes.append(file_sha256(path))
        matching = [row for row in rows if first_value(row, ("model",)) == top_model]
        if len(matching) != 1:
            return baselines, hashes, f"expected one {ref} baseline row for model {top_model!r} in {path}"
        row = matching[0]
        row_hash = first_value(row, ("vhh_seq_sha256", "candidate_vhh_seq_sha256", "sequence_sha256"))
        if row_hash:
            require_hash(row_hash, f"{path}:vhh_seq_sha256")
            if row_hash != expected_hash:
                raise SummaryError(f"hash mismatch for {path}: {row_hash} != {expected_hash}")
        raw_class = first_value(row, ("baseline_class", "class", "blocker_class", "classification"))
        cls = baseline_class_code(raw_class)
        if not cls:
            raise SummaryError(f"unsupported baseline class {raw_class!r} in {path}")
        baselines.append({"path": path, "row": row, "class": cls, "raw_class": raw_class, "ref": ref})
    return baselines, hashes, None


def best_pose(consensus_path: Path, expected_hash: str) -> tuple[dict[str, str] | None, str | None]:
    if not consensus_path.exists():
        return None, f"missing consensus CSV: {consensus_path}"
    rows = read_csv(consensus_path)
    if not rows:
        return None, f"empty consensus CSV: {consensus_path}"
    best: tuple[float, int, dict[str, str]] | None = None
    for idx, row in enumerate(rows):
        row_hash = first_value(row, ("vhh_seq_sha256", "candidate_vhh_seq_sha256", "sequence_sha256"))
        if row_hash:
            require_hash(row_hash, f"{consensus_path}:vhh_seq_sha256")
            if row_hash != expected_hash:
                raise SummaryError(f"hash mismatch for {consensus_path}: {row_hash} != {expected_hash}")
        rank_text = first_value(row, ("best_haddock_rank", "haddock_rank", "rank"))
        if not rank_text:
            return None, f"missing best_haddock_rank in {consensus_path}"
        try:
            rank = float(rank_text)
        except ValueError:
            return None, f"bad best_haddock_rank in {consensus_path}: {rank_text!r}"
        if best is None or (rank, idx) < (best[0], best[1]):
            best = (rank, idx, row)
    return best[2] if best else None, None


def row_consensus_class(row: dict[str, str]) -> str:
    return first_value(row, ("top_model_consensus_class", "consensus_class", "blocker_class", "classification"))


def candidate_incomplete(manifest_row: dict[str, str], reason: str, source_hashes: dict[str, Any] | None = None) -> dict[str, str]:
    payload = {
        "candidate_id": manifest_row["candidate_id"],
        "source_candidate_id": manifest_row.get("source_candidate_id", ""),
        "blocker_class": "INCOMPLETE",
        "reason": reason,
    }
    payload_json = stable_json(payload)
    row = {field: "" for field in OUTPUT_FIELDS}
    row.update(
        {
            "candidate_id": manifest_row["candidate_id"],
            "source_candidate_id": manifest_row.get("source_candidate_id", ""),
            "blocker_class": "INCOMPLETE",
            "top_model_consensus_class": "INCOMPLETE",
            "baseline_count": "0",
            "baseline_classes": "",
            "run_status": "NOT_RUN" if "missing" in reason.lower() else "INCOMPLETE",
            "import_status": "INCOMPLETE",
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "source_hashes_json": stable_json(source_hashes or {}),
            "payload_json": payload_json,
            "payload_sha256": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        }
    )
    return row


def summarize_candidate(manifest_row: dict[str, str], manifest_dir: Path | None = None) -> dict[str, str]:
    candidate_id = manifest_row["candidate_id"].strip()
    expected_hash = manifest_row["vhh_seq_sha256"].strip()
    require_hash(expected_hash, f"{candidate_id}:vhh_seq_sha256")
    workdir = Path(manifest_row["workdir"].strip())
    if not workdir.is_absolute():
        workdir = (manifest_dir or Path.cwd()) / workdir
    source_hashes: dict[str, Any] = {"manifest_vhh_seq_sha256": expected_hash}
    if not workdir.exists():
        return candidate_incomplete(manifest_row, f"missing workdir: {workdir}", source_hashes)

    consensus_path = discover_consensus_path(workdir, manifest_row.get("consensus_filename", "").strip())
    if consensus_path is None:
        return candidate_incomplete(manifest_row, "missing consensus CSV", source_hashes)
    top_pose, consensus_error = best_pose(consensus_path, expected_hash)
    if consensus_error:
        if consensus_path.exists():
            source_hashes[str(consensus_path)] = file_sha256(consensus_path)
        return candidate_incomplete(manifest_row, consensus_error, source_hashes)
    assert top_pose is not None
    source_hashes[str(consensus_path)] = file_sha256(consensus_path)

    sequence_error = bind_input_sequence(
        workdir, manifest_row.get("source_candidate_id", ""), expected_hash, source_hashes
    )
    if sequence_error:
        return candidate_incomplete(manifest_row, sequence_error, source_hashes)

    top_model = first_value(top_pose, ("top_model", "model", "pose_id", "pose", "filename"))
    if not top_model:
        return candidate_incomplete(manifest_row, "missing top model in consensus row", source_hashes)

    baselines, baseline_hashes, baseline_error = read_baselines(
        workdir, manifest_row.get("source_candidate_id", ""), expected_hash, top_model
    )
    for baseline in baselines:
        source_hashes[str(baseline["path"])] = file_sha256(baseline["path"])
    if baseline_error:
        source_hashes["baseline_file_sha256"] = baseline_hashes
        return candidate_incomplete(manifest_row, baseline_error, source_hashes)

    baseline_classes = [baseline["class"] for baseline in baselines]
    labeled_baseline_classes = [f"{baseline['ref']}:{baseline['raw_class']}" for baseline in baselines]
    blocker_class = recompute_consensus(baseline_classes)
    raw_top_consensus = row_consensus_class(top_pose)
    top_consensus = canonical_consensus_class(raw_top_consensus)
    if not top_consensus:
        return candidate_incomplete(
            manifest_row,
            f"missing or unsupported consensus class {raw_top_consensus!r} in {consensus_path}",
            source_hashes,
        )
    if top_consensus != blocker_class:
        raise SummaryError(
            f"consensus and baseline class disagree for {candidate_id}: "
            f"{raw_top_consensus!r} vs {blocker_class!r}"
        )

    per_ref: dict[str, dict[str, float | None]] = {"8x6b": {}, "9e6y": {}}
    try:
        for baseline in baselines:
            ref = baseline["ref"]
            if ref in per_ref:
                for metric in GENERIC_METRICS:
                    value = float_value(baseline["row"], metric)
                    if value is None:
                        raise SummaryError(f"missing numeric field {metric} in {baseline['path']}")
                    per_ref[ref][metric] = value
    except SummaryError as exc:
        return candidate_incomplete(manifest_row, str(exc), source_hashes)
    generic = {
        metric: min((value for ref in per_ref.values() if (value := ref.get(metric)) is not None), default=None)
        for metric in GENERIC_METRICS
    }

    payload = {
        "candidate_id": candidate_id,
        "source_candidate_id": manifest_row.get("source_candidate_id", ""),
        "blocker_class": blocker_class,
        "top_model_consensus_class": blocker_class,
        "top_model": top_model,
        "baseline_count": len(baselines),
        "baseline_classes": labeled_baseline_classes,
        "metrics": generic,
        "top_8x6b_metrics": per_ref["8x6b"],
        "top_9e6y_metrics": per_ref["9e6y"],
        "evidence_boundary": EVIDENCE_BOUNDARY,
        "source_hashes": source_hashes,
    }
    payload_json = stable_json(payload)
    out = {field: "" for field in OUTPUT_FIELDS}
    out.update(
        {
            "candidate_id": candidate_id,
            "source_candidate_id": manifest_row.get("source_candidate_id", ""),
            "blocker_class": blocker_class,
            "top_model_consensus_class": blocker_class,
            "top_model": top_model,
            "baseline_count": str(len(baselines)),
            "baseline_classes": ";".join(labeled_baseline_classes),
            "run_status": "RUN",
            "import_status": "IMPORTED",
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "source_hashes_json": stable_json(source_hashes),
            "payload_json": payload_json,
            "payload_sha256": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        }
    )
    for metric in GENERIC_METRICS:
        out[metric] = fmt_number(generic[metric])
        out[f"top_8x6b_{metric}"] = fmt_number(per_ref["8x6b"].get(metric))
        out[f"top_9e6y_{metric}"] = fmt_number(per_ref["9e6y"].get(metric))
    return out


def read_manifest(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path, delimiter="\t")
    required = {"candidate_id", "source_candidate_id", "vhh_seq_sha256", "workdir"}
    missing = required.difference(rows[0].keys() if rows else set())
    if missing:
        raise SummaryError(f"manifest missing required columns: {', '.join(sorted(missing))}")
    seen: set[str] = set()
    for row in rows:
        cid = row["candidate_id"].strip()
        if not cid:
            raise SummaryError("manifest contains blank candidate_id")
        if cid in seen:
            raise SummaryError(f"duplicate candidate_id: {cid}")
        seen.add(cid)
    return rows


def build_summary(manifest: Path) -> list[dict[str, str]]:
    manifest = manifest.resolve()
    return [summarize_candidate(row, manifest.parent) for row in read_manifest(manifest)]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        rows = build_summary(Path(args.manifest))
        write_csv(Path(args.out_csv), rows)
    except SummaryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
