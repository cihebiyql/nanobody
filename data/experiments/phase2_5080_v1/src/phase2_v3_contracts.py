#!/usr/bin/env python3
"""Shared contracts for the Phase 2 V3 binding-prior pipeline."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

STANDARD_AA = "ACDEFGHIKLMNPQRSTVWY"
AA_SET = set(STANDARD_AA)
VHH_START_MOTIFS = (
    "QVQL",
    "EVQL",
    "DVQL",
    "QVRL",
    "QAQL",
    "QVQP",
    "QMQL",
    "QVLL",
    "QEQL",
    "QVQQ",
    "QVHL",
    "QVEL",
    "QLQL",
)
LABEL_COLUMNS = {"label", "binding_label", "label_value"}


class ContractError(ValueError):
    """Raised when an artifact violates a frozen V3 contract."""


@dataclass(frozen=True)
class NormalizedSequence:
    sequence: str
    original_length: int
    normalized_length: int
    prefix_trimmed: int
    suffix_trimmed: int
    normalization_events: tuple[str, ...]


def clean_text_sequence(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", "", str(value)).upper().rstrip("*")
    if text.lower() in {"", "nan", "none", "na", "n/a"}:
        return ""
    return text


def _validate_standard_aa(sequence: str, label: str) -> None:
    invalid = sorted(set(sequence) - AA_SET)
    if invalid:
        raise ContractError(f"{label} contains non-standard residues: {invalid}")


def normalize_vhh_sequence(value: Any, min_length: int = 80, max_length: int = 179) -> NormalizedSequence:
    original = clean_text_sequence(value)
    if not original:
        raise ContractError("VHH sequence is empty")
    _validate_standard_aa(original, "VHH sequence")
    sequence = original
    events: list[str] = []
    prefix_trimmed = 0
    motif_hits = [sequence.find(motif, 0, 46) for motif in VHH_START_MOTIFS]
    motif_hits = [position for position in motif_hits if position >= 0]
    if motif_hits:
        prefix_trimmed = min(motif_hits)
        if prefix_trimmed:
            sequence = sequence[prefix_trimmed:]
            events.append(f"signal_or_leader_prefix_trimmed:{prefix_trimmed}")

    suffix_trimmed = 0
    tag = re.search(r"(?:GGGGS)?H{5,}$", sequence)
    if tag and tag.start() >= min_length:
        suffix_trimmed = len(sequence) - tag.start()
        sequence = sequence[: tag.start()]
        events.append(f"terminal_histidine_tag_trimmed:{suffix_trimmed}")

    if not min_length <= len(sequence) <= max_length:
        raise ContractError(f"Normalized VHH length {len(sequence)} is outside [{min_length}, {max_length}]")
    return NormalizedSequence(
        sequence=sequence,
        original_length=len(original),
        normalized_length=len(sequence),
        prefix_trimmed=prefix_trimmed,
        suffix_trimmed=suffix_trimmed,
        normalization_events=tuple(events) if events else ("none",),
    )


def normalize_antigen_sequence(value: Any, min_length: int = 20) -> NormalizedSequence:
    sequence = clean_text_sequence(value)
    if not sequence:
        raise ContractError("Antigen sequence is empty")
    _validate_standard_aa(sequence, "Antigen sequence")
    if len(sequence) < min_length:
        raise ContractError(f"Antigen length {len(sequence)} is below {min_length}")
    return NormalizedSequence(sequence, len(sequence), len(sequence), 0, 0, ("none",))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def stable_pair_id(vhh_sha256: str, target_sha256: str) -> str:
    return "v3_pair_" + sha256_text(f"{vhh_sha256}|{target_sha256}")[:24]


def write_csv_atomic(path: Path, rows: Iterable[dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def feature_input_fingerprint(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> str:
    payload = [{column: str(row.get(column, "")) for column in columns} for row in rows]
    payload.sort(key=lambda row: row.get("sample_id", ""))
    return sha256_text(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def ensure_no_label_columns(columns: Iterable[str]) -> None:
    exposed = set(columns) & LABEL_COLUMNS
    if exposed:
        raise ContractError(f"Blinded artifact exposes label columns: {sorted(exposed)}")


def unseal_rows(
    blinded_rows: Sequence[dict[str, Any]],
    label_rows: Sequence[dict[str, Any]],
    input_columns: Sequence[str],
) -> list[dict[str, Any]]:
    label_by_id = {str(row["sample_id"]): row for row in label_rows}
    blinded_ids = [str(row["sample_id"]) for row in blinded_rows]
    if len(label_by_id) != len(label_rows) or set(blinded_ids) != set(label_by_id):
        raise ContractError("Sealed labels do not exactly match blinded sample IDs")
    before = feature_input_fingerprint(blinded_rows, input_columns)
    merged = []
    for blinded in blinded_rows:
        row = dict(blinded)
        label = label_by_id[str(blinded["sample_id"])]
        row["label"] = int(label["label"])
        merged.append(row)
    if feature_input_fingerprint(merged, input_columns) != before:
        raise ContractError("Formal model inputs changed during unsealing")
    return merged


def physicochemical_features(sequence: str) -> list[float]:
    """Dependency-free descriptors used only as deterministic model inputs."""
    length = max(len(sequence), 1)
    features = [sequence.count(aa) / length for aa in STANDARD_AA]
    positive = sum(sequence.count(aa) for aa in "KR") / length
    negative = sum(sequence.count(aa) for aa in "DE") / length
    hydrophobic = sum(sequence.count(aa) for aa in "AVILMFWY") / length
    aromatic = sum(sequence.count(aa) for aa in "FWY") / length
    polar = sum(sequence.count(aa) for aa in "STNQ") / length
    glyco_motifs = sum(1 for index in range(len(sequence) - 2) if sequence[index] == "N" and sequence[index + 1] != "P" and sequence[index + 2] in "ST")
    return features + [
        math.log1p(length) / math.log(180.0),
        positive - negative,
        hydrophobic,
        aromatic,
        polar,
        sequence.count("C") / length,
        min(glyco_motifs, 4) / 4.0,
    ]


def normalized_sequence_dict(result: NormalizedSequence) -> dict[str, Any]:
    return asdict(result)
