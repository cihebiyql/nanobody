#!/usr/bin/env python3
"""Prepare a local mutant/control panel for PVRIG VHH workflow robustness tests."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / "docking" / "success_case_validation"
DEFAULT_FASTA = ROOT / "机制" / "data" / "sequences" / "PVRIG_case02_vhh_20_30_38_39_151_patent_sequences.fasta"
DEFAULT_BATCH = ROOT / "docking" / "calibration" / "patent_success_validation" / "batch_manifest.csv"
DEFAULT_OUT_ROOT = ROOT / "docking" / "calibration" / "mutant_validation_panel"
DEFAULT_BASES = "PVRIG-20,PVRIG-30,PVRIG-38,PVRIG-39,20H5,30H2,39H4"
CONSERVATIVE = {
    "D": "E",
    "E": "D",
    "N": "Q",
    "Q": "N",
    "S": "T",
    "T": "S",
    "K": "R",
    "R": "K",
    "Y": "F",
    "F": "Y",
}
PANEL_FIELDS = [
    "panel_order",
    "mutant_name",
    "base_molecule",
    "family",
    "control_type",
    "mutation_class",
    "mutations_1based",
    "changed_cdr",
    "intended_role",
    "sequence_length",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "sequence",
    "workdir",
    "required_next_stage",
]


@dataclass(frozen=True)
class MutationRecord:
    name_suffix: str
    control_type: str
    mutation_class: str
    changes: tuple[tuple[int, str, str], ...]
    changed_cdr: str
    intended_role: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fasta", type=Path, default=DEFAULT_FASTA)
    parser.add_argument("--batch-manifest", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--bases", default=DEFAULT_BASES, help="Comma-separated base VHH IDs from batch_manifest.csv.")
    parser.add_argument("--haddock-sampling", default="40")
    parser.add_argument("--top-models", default="10")
    parser.add_argument("--no-workdirs", action="store_true", help="Only write panel CSV/FASTA/README, do not scaffold candidate workdirs.")
    parser.add_argument("--limit", type=int, help="Optional first-N records for smoke testing.")
    return parser.parse_args()


def parse_fasta(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    header = ""
    parts: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header:
                records[header.split("|", 1)[0]] = "".join(parts)
            header = line[1:]
            parts = []
        else:
            parts.append(line)
    if header:
        records[header.split("|", 1)[0]] = "".join(parts)
    return records


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def range_positions(text: str) -> set[int]:
    start_s, end_s = text.split("-", 1)
    start, end = int(start_s), int(end_s)
    return set(range(start, end + 1))


def apply_changes(sequence: str, changes: tuple[tuple[int, str, str], ...]) -> str:
    chars = list(sequence)
    for pos, expected, replacement in changes:
        if pos < 1 or pos > len(chars):
            raise ValueError(f"position {pos} out of range for sequence length {len(chars)}")
        observed = chars[pos - 1]
        if observed != expected:
            raise ValueError(f"position {pos} expected {expected}, observed {observed}")
        chars[pos - 1] = replacement
    return "".join(chars)


def mutation_text(changes: tuple[tuple[int, str, str], ...]) -> str:
    if not changes:
        return "none"
    return ";".join(f"{old}{pos}{new}" for pos, old, new in changes)


def conservative_cdr3(sequence: str, cdr3: set[int]) -> MutationRecord | None:
    for pos in sorted(cdr3):
        aa = sequence[pos - 1]
        if aa in CONSERVATIVE:
            return MutationRecord(
                name_suffix=f"cdr3_cons_{aa}{pos}{CONSERVATIVE[aa]}",
                control_type="mutant",
                mutation_class="single_conservative_cdr3",
                changes=((pos, aa, CONSERVATIVE[aa]),),
                changed_cdr="CDR3",
                intended_role="small CDR3 perturbation; should test whether the workflow is overly brittle to conservative substitutions",
            )
    return None


def cdr3_aromatic_to_alanine(sequence: str, cdr3: set[int]) -> MutationRecord | None:
    for pos in sorted(cdr3):
        aa = sequence[pos - 1]
        if aa in {"F", "Y", "W"}:
            return MutationRecord(
                name_suffix=f"cdr3_arom_{aa}{pos}A",
                control_type="mutant",
                mutation_class="single_aromatic_to_alanine_cdr3",
                changes=((pos, aa, "A"),),
                changed_cdr="CDR3",
                intended_role="paratope-disruptive single substitution; should usually weaken retained blocker-like geometry after real docking",
            )
    return None


def cdr3_center_alanine(sequence: str, cdr3: set[int]) -> MutationRecord | None:
    midpoint = (min(cdr3) + max(cdr3)) / 2
    candidates = [pos for pos in sorted(cdr3, key=lambda p: (abs(p - midpoint), p)) if sequence[pos - 1] not in {"A", "C"}]
    chosen = sorted(candidates[:3])
    if not chosen:
        return None
    changes = tuple((pos, sequence[pos - 1], "A") for pos in chosen)
    return MutationRecord(
        name_suffix="cdr3_center_ala_scan",
        control_type="mutant",
        mutation_class="multi_cdr3_alanine_scan",
        changes=changes,
        changed_cdr="CDR3",
        intended_role="strong CDR3 perturbation; negative/fragility control for sequence-to-docking ranking",
    )


def framework_conservative(sequence: str, cdrs: set[int]) -> MutationRecord | None:
    positions = [pos for pos in range(8, len(sequence) - 7) if pos not in cdrs and sequence[pos - 1] in CONSERVATIVE]
    if not positions:
        return None
    midpoint = len(sequence) / 2
    pos = sorted(positions, key=lambda p: (abs(p - midpoint), p))[0]
    aa = sequence[pos - 1]
    return MutationRecord(
        name_suffix=f"fw_cons_{aa}{pos}{CONSERVATIVE[aa]}",
        control_type="mutant",
        mutation_class="single_conservative_framework",
        changes=((pos, aa, CONSERVATIVE[aa]),),
        changed_cdr="no",
        intended_role="framework plumbing control; CDR ranges should remain stable and ranking should not be driven by sequence parser artifacts",
    )


def pvrig20_patent_style(sequence: str) -> MutationRecord | None:
    pos = 103
    if len(sequence) >= pos and sequence[pos - 1] == "D":
        return MutationRecord(
            name_suffix="patent_20_D103E_style",
            control_type="mutant",
            mutation_class="known_20_family_cdr3_stability_delta",
            changes=((pos, "D", "E"),),
            changed_cdr="CDR3",
            intended_role="known PVRIG-20 to 20H-style CDR3 D-to-E perturbation; positive-retention/stability calibration candidate",
        )
    return None


def build_records(base_rows: list[dict[str, str]], fasta: dict[str, str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    order = 1
    for row in base_rows:
        base = row["molecule_name"]
        sequence = fasta[base]
        cdr1 = range_positions(row["cdr1_range"])
        cdr2 = range_positions(row["cdr2_range"])
        cdr3 = range_positions(row["cdr3_range"])
        cdrs = cdr1 | cdr2 | cdr3
        recipes: list[MutationRecord] = [
            MutationRecord(
                name_suffix="base_reference",
                control_type="base_reference",
                mutation_class="unmutated_positive_control",
                changes=(),
                changed_cdr="no",
                intended_role="known positive/control leakage anchor; not a new design candidate",
            )
        ]
        for recipe in [conservative_cdr3(sequence, cdr3), cdr3_aromatic_to_alanine(sequence, cdr3), cdr3_center_alanine(sequence, cdr3), framework_conservative(sequence, cdrs)]:
            if recipe is not None:
                recipes.append(recipe)
        if base == "PVRIG-20":
            recipe = pvrig20_patent_style(sequence)
            if recipe is not None:
                recipes.append(recipe)
        seen_names: set[str] = set()
        for recipe in recipes:
            mutant_name = f"mut_{order:02d}_{base}_{recipe.name_suffix}"
            if mutant_name in seen_names:
                continue
            seen_names.add(mutant_name)
            mutated = apply_changes(sequence, recipe.changes)
            records.append(
                {
                    "panel_order": str(order),
                    "mutant_name": mutant_name,
                    "base_molecule": base,
                    "family": row["family"],
                    "control_type": recipe.control_type,
                    "mutation_class": recipe.mutation_class,
                    "mutations_1based": mutation_text(recipe.changes),
                    "changed_cdr": recipe.changed_cdr,
                    "intended_role": recipe.intended_role,
                    "sequence_length": str(len(mutated)),
                    "cdr1_range": row["cdr1_range"],
                    "cdr2_range": row["cdr2_range"],
                    "cdr3_range": row["cdr3_range"],
                    "sequence": mutated,
                    "workdir": "",
                    "required_next_stage": "local scaffold -> node1 NanoBodyBuilder2 -> HADDOCK3 -> 8X6B/9E6Y postprocess",
                }
            )
            order += 1
    return records


def write_panel_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PANEL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_fasta(path: Path, rows: list[dict[str, str]]) -> None:
    lines: list[str] = []
    for row in rows:
        lines.append(
            f">{row['mutant_name']}|base={row['base_molecule']}|class={row['mutation_class']}|mut={row['mutations_1based']}"
        )
        lines.append(row["sequence"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_workdirs(rows: list[dict[str, str]], out_root: Path, sampling: str, top_models: str) -> None:
    workdir_root = out_root / "workdirs"
    script = WORKFLOW_DIR / "prepare_candidate_sequence_workflow.py"
    for row in rows:
        cmd = [
            sys.executable,
            str(script),
            "--name",
            row["mutant_name"],
            "--sequence",
            row["sequence"],
            "--out-root",
            str(workdir_root),
            "--cdr1",
            row["cdr1_range"],
            "--cdr2",
            row["cdr2_range"],
            "--cdr3",
            row["cdr3_range"],
            "--haddock-sampling",
            sampling,
            "--top-models",
            top_models,
        ]
        subprocess.run(cmd, cwd=ROOT, check=True)
        row["workdir"] = str((workdir_root / row["mutant_name"]).resolve())


def write_batch_scripts(out_root: Path, rows: list[dict[str, str]]) -> None:
    def write_runner(path: Path, script_name: str, title: str) -> None:
        lines = ["#!/usr/bin/env bash", "set -euo pipefail", "", f"echo {title!r}"]
        for row in rows:
            if not row["workdir"]:
                continue
            lines.append(f"bash {Path(row['workdir']) / script_name}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o755)

    write_runner(out_root / "run_all_node1_structure_predictions.sh", "run_node1_structure_prediction.sh", "running mutant panel structure prediction")
    write_runner(out_root / "run_all_node1_haddock3.sh", "run_node1_haddock3.sh", "running mutant panel HADDOCK3")
    write_runner(out_root / "postprocess_all_after_docking.sh", "postprocess_after_docking.sh", "postprocessing mutant panel docking outputs")


def write_readme(path: Path, rows: list[dict[str, str]], bases: list[str]) -> None:
    classes = Counter(row["mutation_class"] for row in rows)
    lines = [
        "# Mutant Validation Panel",
        "",
        "This panel is for robustness validation of the PVRIG VHH sequence-to-blocker workflow.",
        "It is not a new-design submission set.",
        "",
        "## Scope",
        "",
        f"- Base VHHs: {', '.join(bases)}",
        f"- Panel records: {len(rows)}",
        "- Uses known positive/control sequences and local amino-acid perturbations to test pipeline stability, leakage detection, and threshold sensitivity.",
        "- Current panel execution is complete when `summarize_mutant_panel_status.py` and `validate_mutant_panel_completion.py` both pass.",
        "- These rows remain calibration/leakage controls, not new-design submissions.",
        "",
        "## Mutation classes",
        "",
    ]
    for key, value in sorted(classes.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Execution order",
            "",
            "```bash",
            "python docking/success_case_validation/prepare_mutant_validation_batch.py",
            "python docking/success_case_validation/check_vhh_sequence_leakage.py \\",
            "  --candidate-csv docking/calibration/mutant_validation_panel/mutant_panel.csv \\",
            "  --out-csv docking/calibration/mutant_validation_panel/mutant_panel_sequence_leakage.csv",
            "python docking/success_case_validation/run_mutant_panel_batch.py --stage structure --keep-going",
            "python docking/success_case_validation/run_mutant_panel_batch.py --stage docking --jobs 4 --keep-going",
            "python docking/success_case_validation/run_mutant_panel_batch.py --stage postprocess --jobs 4 --keep-going",
            "python docking/success_case_validation/summarize_mutant_panel_status.py",
            "python docking/success_case_validation/validate_mutant_panel_completion.py",
            "python docking/success_case_validation/summarize_mutant_panel_results.py",
            "python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py",
            "```",
            "",
            "## Interpretation",
            "",
            "- Base-reference rows are leakage/positive controls and must not be ranked as novel candidates.",
            "- Conservative CDR3 substitutions are sensitivity controls; retained A-level labels mean the workflow is not overly brittle, but still need pose review.",
            "- CDR3 alanine/aromatic-to-alanine rows are negative/fragility controls; a retained high score should trigger manual pose inspection rather than automatic biological interpretation.",
            "- Framework controls test pipeline plumbing and CDR-range stability, not biological improvement.",
            "",
            "## Status refresh",
            "",
            "```bash",
            "python docking/success_case_validation/summarize_mutant_panel_status.py",
            "python docking/success_case_validation/validate_mutant_panel_completion.py",
            "python docking/success_case_validation/summarize_mutant_panel_results.py",
            "python docking/success_case_validation/analyze_mutant_panel_threshold_sensitivity.py",
            "```",
            "",
            "Outputs:",
            "",
            "- `mutant_panel_status.csv`",
            "- `MUTANT_PANEL_STATUS_SUMMARY.md`",
            "- `MUTANT_PANEL_COMPLETION_VALIDATION.md`",
            "- `MUTANT_PANEL_RESULT_STRATIFICATION.md`",
            "- `mutant_panel_result_stratification_summary.csv`",
            "- `MUTANT_PANEL_THRESHOLD_SENSITIVITY_REPORT.md`",
            "- `mutant_panel_threshold_sensitivity_summary.csv`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_root = args.out_root.resolve()
    bases = [item.strip() for item in args.bases.split(",") if item.strip()]
    fasta = parse_fasta(args.fasta)
    manifest = {row["molecule_name"]: row for row in read_csv(args.batch_manifest)}
    missing = [base for base in bases if base not in fasta or base not in manifest]
    if missing:
        raise SystemExit(f"base IDs missing from FASTA or manifest: {missing}")
    base_rows = [manifest[base] for base in bases]
    rows = build_records(base_rows, fasta)
    if args.limit is not None:
        rows = rows[: args.limit]
    if not args.no_workdirs:
        prepare_workdirs(rows, out_root, args.haddock_sampling, args.top_models)
        write_batch_scripts(out_root, rows)
    write_panel_csv(out_root / "mutant_panel.csv", rows)
    write_fasta(out_root / "mutant_panel.fasta", rows)
    write_readme(out_root / "README.md", rows, bases)
    print("OK mutant validation panel prepared")
    print(f"bases={len(bases)}")
    print(f"records={len(rows)}")
    print(f"out_root={out_root}")
    print(f"panel_csv={out_root / 'mutant_panel.csv'}")
    print(f"panel_fasta={out_root / 'mutant_panel.fasta'}")
    if not args.no_workdirs:
        print(f"workdirs={out_root / 'workdirs'}")


if __name__ == "__main__":
    main()
