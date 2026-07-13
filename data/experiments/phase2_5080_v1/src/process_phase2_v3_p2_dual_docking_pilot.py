#!/usr/bin/env python3
"""Postprocess independent 8X6B/9E6Y Pilot64 docking runs.

Each receptor-generated pose set is evaluated against both PVRIG:PVRL2
reference structures.  Cross-conformer poses are explicitly remapped from the
generation receptor's native residue numbering to the scoring receptor's
numbering before hotspot scoring.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import IO, Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent
WORKFLOW_DIR = WORKSPACE_ROOT / "docking/success_case_validation"
DOCKING_SCRIPTS = WORKSPACE_ROOT / "docking/scripts"
HOTSPOT_CSV = DATA_ROOT / "structures/PVRIG_hotspot_set_v1.csv"
RECONCILIATION_CSV = DATA_ROOT / "structures/PVRIG_numbering_reconciliation.csv"

DEFAULT_PACKAGE_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_package_v2"
DEFAULT_MANIFEST = DEFAULT_PACKAGE_ROOT / "manifests/run_manifest.csv"
DEFAULT_SYNC_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_v2_node1_selected"
DEFAULT_WORK_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_v2_postprocessed"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p2_dual_docking_pilot_v2_postprocess_audit.json"

PROTOCOL_ID = "DG_A_PILOT64_V1_1"
CLAIM_BOUNDARY = "independent_dual_conformer_docking_geometry_not_experimental_binding_or_blocking_truth"
RECEPTORS = {
    "8x6b": {
        "pdb": DATA_ROOT / "structures/8X6B.pdb",
        "pdb_id": "8X6B",
        "pvrig_chain": "B",
        "pvrl2_chain": "A",
        "map_column": "pdb_8x6b_ref",
    },
    "9e6y": {
        "pdb": DATA_ROOT / "structures/9E6Y.pdb",
        "pdb_id": "9E6Y",
        "pvrig_chain": "A",
        "pvrl2_chain": "D",
        "map_column": "pdb_9e6y_ref",
    },
}
POSTPROCESS_TOOLCHAIN_PATHS = {
    "postprocessor": Path(__file__).resolve(),
    "align_pdb_by_chain": DOCKING_SCRIPTS / "align_pdb_by_chain.py",
    "score_pvrig_vhh_pose": DOCKING_SCRIPTS / "score_pvrig_vhh_pose.py",
    "score_cdr_region_occlusion": DOCKING_SCRIPTS / "score_cdr_region_occlusion.py",
    "apply_blocker_judgment": WORKFLOW_DIR / "apply_blocker_judgment.py",
    "summarize_multibaseline_judgment": WORKFLOW_DIR / "summarize_multibaseline_judgment.py",
}
POSTPROCESS_REFERENCE_PATHS = {
    "hotspot_csv": HOTSPOT_CSV,
    "numbering_reconciliation_csv": RECONCILIATION_CSV,
    "8x6b_scoring_reference": Path(RECEPTORS["8x6b"]["pdb"]),
    "9e6y_scoring_reference": Path(RECEPTORS["9e6y"]["pdb"]),
}
MODEL_RE = re.compile(r"cluster_(\d+)_model_(\d+)")
POSTPROCESS_ARTIFACT_KEYS = (
    "consensus",
    "classification_8x6b",
    "classification_9e6y",
    "mechanism_8x6b",
    "mechanism_9e6y",
    "canonical_contact_summary",
    "canonical_contact_pairs",
    "ranks",
)
POSTPROCESS_COUNT_FIELDS = (
    "selected_models",
    "pose_clusters",
    "consensus_rows",
    "classification_8x6b_rows",
    "classification_9e6y_rows",
    "mechanism_8x6b_rows",
    "mechanism_9e6y_rows",
    "canonical_contact_pose_rows",
    "canonical_contact_pair_rows",
    "contact_failures",
)


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_csv(path: Path, rows: Sequence[dict[str, Any]], preferred_fields: Sequence[str]) -> None:
    fields = list(preferred_fields)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def postprocess_artifact_paths(workdir: Path, run_id: str) -> dict[str, Path]:
    reports = workdir / "reports"
    return {
        "consensus": reports / f"{run_id}_dual_baseline_consensus.csv",
        "classification_8x6b": reports / f"{run_id}_8x6b_blocker_classification.csv",
        "classification_9e6y": reports / f"{run_id}_9e6y_blocker_classification.csv",
        "mechanism_8x6b": workdir / "8x6b_baseline/haddock3_top_model_mechanism_scores_8x6b.csv",
        "mechanism_9e6y": workdir / "9e6y_baseline/haddock3_top_model_mechanism_scores_9e6y.csv",
        "canonical_contact_summary": reports / f"{run_id}_canonical_contact_summary.csv",
        "canonical_contact_pairs": reports / f"{run_id}_canonical_contact_pairs.csv",
        "ranks": reports / "haddock3_model_ranks.csv",
    }


def read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def hash_named_paths(paths: dict[str, Path]) -> dict[str, str]:
    missing = [f"{name}:{path}" for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing frozen postprocess inputs: {missing}")
    return {name: sha256_file(path) for name, path in paths.items()}


def postprocess_marker_matches(marker_path: Path, expected: dict[str, Any]) -> bool:
    if not marker_path.is_file():
        return False
    try:
        return read_json_object(marker_path) == expected
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def build_postprocess_marker(
    row: dict[str, str],
    sync_root: Path,
    workdir: Path,
    run_dir: Path,
    selected: Sequence[tuple[str, Path, int]],
    evidence: dict[str, Any],
    run_manifest_sha256: str,
) -> dict[str, Any]:
    run_id = row["run_id"]
    completion_relpath = row.get("completion_relpath", f"runs/{run_id}/{run_id}.complete.json")
    completion_path = Path(completion_relpath)
    if not completion_path.is_absolute():
        completion_path = sync_root / completion_path
    if not completion_path.is_file():
        raise FileNotFoundError(f"Missing original docking completion: {completion_path}")
    docking_completion = read_json_object(completion_path)
    identity_expectations = {
        "protocol_id": PROTOCOL_ID,
        "run_id": run_id,
        "pilot_id": row["pilot_id"],
        "source_candidate_id": row["source_candidate_id"],
        "seed_role": row["seed_role"],
    }
    for field, expected in identity_expectations.items():
        if docking_completion.get(field) != expected:
            raise ValueError(
                f"Docking completion identity mismatch for {run_id}: "
                f"{field}={docking_completion.get(field)!r}!={expected!r}"
            )
    if str(docking_completion.get("receptor_id", "")).lower() != row["receptor_id"].lower():
        raise ValueError(f"Docking completion receptor mismatch for {run_id}")
    if docking_completion.get("status") != "PASS_DOCKING_OUTPUT_COMPLETE":
        raise ValueError(f"Docking completion is not PASS for {run_id}")

    artifacts: dict[str, dict[str, str]] = {}
    for key, path in postprocess_artifact_paths(workdir, run_id).items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing postprocess artifact {key}: {path}")
        artifacts[key] = {
            "relpath": str(path.relative_to(workdir)),
            "sha256": sha256_file(path),
        }
    selected_inventory = []
    for model, path, rank in selected:
        if not path.is_file() or not path.stat().st_size:
            raise FileNotFoundError(f"Missing selected pose for {run_id}: {path}")
        selected_inventory.append(
            {
                "model": model,
                "filename": path.name,
                "sha256": sha256_file(path),
                "haddock_rank": rank,
            }
        )
    counts = {field: evidence[field] for field in POSTPROCESS_COUNT_FIELDS}
    return {
        "schema_version": "phase2_v3_p2_dual_docking_run_postprocess_v1_1",
        "protocol_id": PROTOCOL_ID,
        "status": "PASS",
        "run_id": run_id,
        "pilot_id": row["pilot_id"],
        "source_candidate_id": row["source_candidate_id"],
        "generation_receptor": row["receptor_id"].lower(),
        "seed_role": row["seed_role"],
        "run_manifest_sha256": run_manifest_sha256,
        "docking_completion": {
            "relpath": completion_relpath,
            "sha256": sha256_file(completion_path),
            **docking_completion,
        },
        "input_sha256": {
            "config": row["config_sha256"],
            "monomer": row["monomer_sha256"],
            "receptor": row["receptor_sha256"],
        },
        "selected_pose_files": selected_inventory,
        "counts": counts,
        "artifacts": artifacts,
        "toolchain_sha256": hash_named_paths(POSTPROCESS_TOOLCHAIN_PATHS),
        "reference_sha256": hash_named_paths(POSTPROCESS_REFERENCE_PATHS),
        "consensus_sha256": artifacts["consensus"]["sha256"],
        "run_dir": str(run_dir),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def model_name(path: Path) -> str:
    name = path.name
    for suffix in (".pdb.gz", ".pdb"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def traceback_ranks(run_dir: Path) -> dict[str, int]:
    path = run_dir / "traceback/consensus.tsv"
    if not path.exists():
        return {}
    ranks: dict[str, int] = {}
    for row in read_csv(path, delimiter="\t"):
        model = row.get("Model", "").removesuffix(".pdb")
        raw = row.get("6_seletopclusts_rank", "") or row.get("Sum-of-Ranks", "")
        try:
            ranks[model] = int(float(raw))
        except ValueError:
            continue
    return ranks


def selected_models(run_dir: Path, top_n: int) -> list[tuple[str, Path, int]]:
    selected = run_dir / "6_seletopclusts"
    paths = list(selected.glob("cluster_*_model_*.pdb.gz")) + list(selected.glob("cluster_*_model_*.pdb"))
    unique: dict[str, Path] = {}
    for path in paths:
        name = model_name(path)
        current = unique.get(name)
        if current is None or (current.suffix != ".gz" and path.suffix == ".gz"):
            unique[name] = path
    ranks = traceback_ranks(run_dir)

    def sort_key(item: tuple[str, Path]) -> tuple[int, int, int, str]:
        name, _path = item
        match = MODEL_RE.fullmatch(name)
        cluster = int(match.group(1)) if match else 10**9
        model = int(match.group(2)) if match else 10**9
        return ranks.get(name, 10**9), cluster, model, name

    ordered = sorted(unique.items(), key=sort_key)[:top_n]
    return [(name, path, ranks.get(name, index)) for index, (name, path) in enumerate(ordered, start=1)]


def unpack_pose(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == ".gz":
        with gzip.open(source, "rb") as in_handle, destination.open("wb") as out_handle:
            shutil.copyfileobj(in_handle, out_handle)
    else:
        shutil.copy2(source, destination)


def parse_reconciliation(path: Path = RECONCILIATION_CSV) -> dict[str, dict[int, tuple[str, int, str]]]:
    by_pdb: dict[str, dict[int, tuple[str, int, str]]] = {"8X6B": {}, "9E6Y": {}}
    for row in read_csv(path):
        pdb_id = row.get("pdb_id", "").upper()
        if pdb_id not in by_pdb or not row.get("uniprot_position", "").strip():
            continue
        uniprot = int(row["uniprot_position"])
        value = (row["pvrig_chain"], int(row["pdb_resseq"]), row.get("pdb_icode", "").strip())
        previous = by_pdb[pdb_id].get(uniprot)
        if previous is not None and previous != value:
            raise ValueError(f"Ambiguous {pdb_id} mapping at UniProt {uniprot}: {previous} vs {value}")
        by_pdb[pdb_id][uniprot] = value
    return by_pdb


def native_to_uniprot_map(receptor: str) -> dict[tuple[int, str], int]:
    pdb_id = str(RECEPTORS[receptor]["pdb_id"])
    return {
        (resseq, icode): uniprot
        for uniprot, (_chain, resseq, icode) in parse_reconciliation()[pdb_id].items()
    }


def canonical_contact_rows(
    pose: Path,
    model: str,
    source_receptor: str,
    cutoff: float = 4.5,
) -> list[dict[str, Any]]:
    """Extract VHH-PVRIG residue contacts using canonical PVRIG UniProt IDs."""
    atoms: dict[str, list[tuple[int, str, str, float, float, float]]] = {"A": [], "B": []}
    for line in pose.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or len(line) < 54 or line[21] not in atoms:
            continue
        atom_name = line[12:16].strip().upper()
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if element in {"H", "D"} or (not element and atom_name.startswith(("H", "D"))):
            continue
        try:
            atoms[line[21]].append(
                (
                    int(line[22:26]),
                    line[26].strip(),
                    line[17:20].strip().upper(),
                    float(line[30:38]),
                    float(line[38:46]),
                    float(line[46:54]),
                )
            )
        except ValueError:
            continue
    if not atoms["A"] or not atoms["B"]:
        raise ValueError(f"Missing VHH/PVRIG atoms in {pose}: A={len(atoms['A'])} B={len(atoms['B'])}")
    canonical = native_to_uniprot_map(source_receptor)
    cell = cutoff
    grid: dict[tuple[int, int, int], list[tuple[int, str, str, float, float, float]]] = {}
    for atom in atoms["B"]:
        key = (math.floor(atom[3] / cell), math.floor(atom[4] / cell), math.floor(atom[5] / cell))
        grid.setdefault(key, []).append(atom)
    cutoff_sq = cutoff * cutoff
    pairs: dict[tuple[int, str, str, int, str, str], float] = {}
    for vhh in atoms["A"]:
        origin = (math.floor(vhh[3] / cell), math.floor(vhh[4] / cell), math.floor(vhh[5] / cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for pvrig in grid.get((origin[0] + dx, origin[1] + dy, origin[2] + dz), []):
                        distance_sq = (vhh[3] - pvrig[3]) ** 2 + (vhh[4] - pvrig[4]) ** 2 + (vhh[5] - pvrig[5]) ** 2
                        if distance_sq > cutoff_sq:
                            continue
                        key = (pvrig[0], pvrig[1], pvrig[2], vhh[0], vhh[1], vhh[2])
                        distance = math.sqrt(distance_sq)
                        if key not in pairs or distance < pairs[key]:
                            pairs[key] = distance
    output: list[dict[str, Any]] = []
    for key, distance in sorted(pairs.items()):
        pvrig_resseq, pvrig_icode, pvrig_resname, vhh_resseq, vhh_icode, vhh_resname = key
        uniprot = canonical.get((pvrig_resseq, pvrig_icode))
        if uniprot is None:
            raise ValueError(
                f"No canonical UniProt mapping for {source_receptor} PVRIG {pvrig_resseq}{pvrig_icode} in {pose}"
            )
        output.append(
            {
                "model": model,
                "generation_receptor": source_receptor,
                "pvrig_pose_resseq": pvrig_resseq,
                "pvrig_pose_icode": pvrig_icode,
                "pvrig_resname": pvrig_resname,
                "pvrig_uniprot_position": uniprot,
                "vhh_resseq": vhh_resseq,
                "vhh_icode": vhh_icode,
                "vhh_resname": vhh_resname,
                "min_heavy_atom_distance_A": f"{distance:.4f}",
            }
        )
    return output


def residue_number_map(source_receptor: str, target_receptor: str) -> dict[tuple[int, str], tuple[int, str]]:
    mappings = parse_reconciliation()
    source_id = str(RECEPTORS[source_receptor]["pdb_id"])
    target_id = str(RECEPTORS[target_receptor]["pdb_id"])
    source = mappings[source_id]
    target = mappings[target_id]
    return {
        (source[uniprot][1], source[uniprot][2]): (target[uniprot][1], target[uniprot][2])
        for uniprot in sorted(source.keys() & target.keys())
    }


def remap_pose_receptor_numbering(
    source: Path,
    destination: Path,
    source_receptor: str,
    target_receptor: str,
    pose_chain: str = "B",
) -> dict[str, int]:
    """Rewrite only the pose PVRIG residue IDs; VHH coordinates/IDs are unchanged."""
    mapping = residue_number_map(source_receptor, target_receptor)
    output: list[str] = []
    unmapped_ids: dict[tuple[int, str], int] = {}
    remapped_residues: set[tuple[int, str]] = set()
    observed_residues: set[tuple[int, str]] = set()
    next_unmapped = -900
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 27 and line[21] == pose_chain:
            try:
                original = (int(line[22:26]), line[26].strip())
            except ValueError:
                output.append(line)
                continue
            observed_residues.add(original)
            target = mapping.get(original)
            if target is None:
                if original not in unmapped_ids:
                    unmapped_ids[original] = next_unmapped
                    next_unmapped += 1
                target = (unmapped_ids[original], "")
            else:
                remapped_residues.add(original)
            line = f"{line[:22]}{target[0]:4d}{(target[1] or ' ')[:1]}{line[27:]}"
        output.append(line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(output) + "\n", encoding="utf-8")
    return {
        "observed_receptor_residues": len(observed_residues),
        "remapped_receptor_residues": len(remapped_residues),
        "unmapped_receptor_residues": len(unmapped_ids),
    }


def write_alignment_pair_map(source_receptor: str, target_receptor: str, path: Path) -> int:
    """Write an unambiguous 23-point map with the mobile PVRIG relabelled B."""
    source_column = str(RECEPTORS[source_receptor]["map_column"])
    target_column = str(RECEPTORS[target_receptor]["map_column"])
    rows: list[dict[str, str]] = []
    for row in read_csv(HOTSPOT_CSV):
        if row.get("hotspot_class") not in {"core_hotspot", "secondary_hotspot"}:
            continue
        mobile = row.get(source_column, "").strip()
        reference = row.get(target_column, "").strip()
        if not mobile or not reference:
            continue
        mobile = f"B:{mobile.split(':', 1)[1]}"
        rows.append({"mobile_ref": mobile, "reference_ref": reference})
    if len(rows) != 23 or len({row["mobile_ref"] for row in rows}) != 23:
        raise ValueError(
            f"Expected 23 unique alignment points for {source_receptor}->{target_receptor}; found {len(rows)}"
        )
    write_csv(path, rows, ["mobile_ref", "reference_ref"])
    return len(rows)


def run_logged(command: Sequence[str], log: IO[str]) -> str:
    log.write("+ " + " ".join(map(str, command)) + "\n")
    log.flush()
    completed = subprocess.run(
        list(map(str, command)),
        cwd=WORKSPACE_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )
    log.write(completed.stdout)
    log.flush()
    return completed.stdout


def parse_rmsd(output: str) -> str:
    for line in output.splitlines():
        if "rmsd=" in line:
            return line.split("rmsd=", 1)[1].split()[0]
    return ""


def summarize_cdr_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    regions = data["regions"]
    cdr1, cdr2, cdr3, framework = (regions[name] for name in ("CDR1", "CDR2", "CDR3", "framework"))
    total_atoms = data["total_occluding_atom_contact_count"]
    total_pairs = data["total_occluding_residue_pair_count"]
    return {
        "total_vhh_pvrl2_atom_occlusion": total_atoms,
        "total_vhh_pvrl2_residue_pair_occlusion": total_pairs,
        "total_vhh_pvrl2_atom_clash": data["total_clash_atom_contact_count"],
        "total_vhh_pvrl2_residue_pair_clash": data["total_clash_residue_pair_count"],
        "cdr3_atom_occlusion": cdr3["occluding_atom_contact_count"],
        "cdr3_atom_occlusion_fraction": cdr3["occluding_atom_contact_count"] / total_atoms if total_atoms else 0,
        "cdr3_residue_pair_occlusion": cdr3["occluding_residue_pair_count"],
        "cdr3_residue_pair_occlusion_fraction": cdr3["occluding_residue_pair_count"] / total_pairs if total_pairs else 0,
        "cdr3_atom_clash": cdr3["clash_atom_contact_count"],
        "cdr3_residue_pair_clash": cdr3["clash_residue_pair_count"],
        "cdr12_atom_occlusion": cdr1["occluding_atom_contact_count"] + cdr2["occluding_atom_contact_count"],
        "cdr12_residue_pair_occlusion": cdr1["occluding_residue_pair_count"] + cdr2["occluding_residue_pair_count"],
        "framework_atom_occlusion": framework["occluding_atom_contact_count"],
        "framework_residue_pair_occlusion": framework["occluding_residue_pair_count"],
    }


def score_baseline(
    models: Sequence[str],
    ranks: dict[str, int],
    raw_pose_dir: Path,
    output_dir: Path,
    source_receptor: str,
    target_receptor: str,
    cdr_ranges: tuple[str, str, str],
    log: IO[str],
) -> tuple[Path, Path, Path]:
    target = RECEPTORS[target_receptor]
    target_column = str(target["map_column"])
    aligned_dir = output_dir / f"aligned_to_{target_receptor}"
    report_dir = output_dir / f"{target_receptor}_baseline"
    (report_dir / "per_model_scores").mkdir(parents=True, exist_ok=True)
    (report_dir / "json").mkdir(parents=True, exist_ok=True)
    pose_rows: list[dict[str, Any]] = []
    cdr_rows: list[dict[str, Any]] = []
    pair_map = output_dir / "alignment_maps" / f"{source_receptor}_to_{target_receptor}.csv"
    write_alignment_pair_map(source_receptor, target_receptor, pair_map)

    for model in models:
        raw_pose = raw_pose_dir / f"{model}.pdb"
        aligned_native = aligned_dir / f".{model}_aligned_native.pdb"
        align_output = run_logged(
            [
                sys.executable,
                DOCKING_SCRIPTS / "align_pdb_by_chain.py",
                "--mobile-pdb",
                raw_pose,
                "--reference-pdb",
                target["pdb"],
                "--mobile-chain",
                "B",
                "--reference-chain",
                target["pvrig_chain"],
                "--pair-map-csv",
                pair_map,
                "--mobile-ref-column",
                "mobile_ref",
                "--reference-ref-column",
                "reference_ref",
                "--out-pdb",
                aligned_native,
            ],
            log,
        )
        final_pose = aligned_dir / f"{model}_aligned_to_{target_receptor}.pdb"
        if source_receptor == target_receptor:
            aligned_native.replace(final_pose)
            remap_evidence = {
                "observed_receptor_residues": "",
                "remapped_receptor_residues": "",
                "unmapped_receptor_residues": 0,
            }
        else:
            remap_evidence = remap_pose_receptor_numbering(
                aligned_native,
                final_pose,
                source_receptor,
                target_receptor,
            )
            aligned_native.unlink()

        pose_score = report_dir / "per_model_scores" / f"{model}_{target_receptor}_pose_score.csv"
        run_logged(
            [
                sys.executable,
                DOCKING_SCRIPTS / "score_pvrig_vhh_pose.py",
                "--pose-pdb",
                final_pose,
                "--reference-pdb",
                target["pdb"],
                "--pvrig-chain",
                "B",
                "--vhh-chain",
                "A",
                "--ref-pvrig-chain",
                target["pvrig_chain"],
                "--ref-pvrl2-chain",
                target["pvrl2_chain"],
                "--hotspots-csv",
                HOTSPOT_CSV,
                "--hotspot-ref-column",
                target_column,
                "--assume-aligned",
                "--cdr-ranges",
                f"CDR1:{cdr_ranges[0]},CDR2:{cdr_ranges[1]},CDR3:{cdr_ranges[2]}",
                "--out-csv",
                pose_score,
            ],
            log,
        )
        pose_row = read_csv(pose_score)[0]
        pose_row.update(
            {
                "model": model,
                "baseline": target_receptor,
                "haddock_rank": ranks[model],
                "haddock_score": "",
                "align_rmsd_A": parse_rmsd(align_output),
                "generation_receptor": source_receptor,
                **remap_evidence,
            }
        )
        pose_rows.append(pose_row)

        cdr_json = report_dir / "json" / f"{model}_{target_receptor}_cdr_occlusion.json"
        run_logged(
            [
                sys.executable,
                DOCKING_SCRIPTS / "score_cdr_region_occlusion.py",
                "--pose-pdb",
                final_pose,
                "--reference-pdb",
                target["pdb"],
                "--vhh-chain",
                "A",
                "--ref-pvrl2-chain",
                target["pvrl2_chain"],
                "--cdr1",
                cdr_ranges[0],
                "--cdr2",
                cdr_ranges[1],
                "--cdr3",
                cdr_ranges[2],
                "--out-json",
                cdr_json,
            ],
            log,
        )
        cdr_row: dict[str, Any] = {
            "model": model,
            "baseline": target_receptor,
            "haddock_rank": ranks[model],
            "haddock_score": "",
            "hotspot_overlap_count": pose_row["hotspot_overlap_count"],
            "align_rmsd_A": pose_row["align_rmsd_A"],
            "generation_receptor": source_receptor,
        }
        cdr_row.update(summarize_cdr_json(cdr_json))
        cdr_rows.append(cdr_row)

    mechanism = report_dir / f"haddock3_top_model_mechanism_scores_{target_receptor}.csv"
    cdr_summary = report_dir / f"cdr3_occlusion_summary_{target_receptor}.csv"
    write_csv(mechanism, pose_rows, ["model", "baseline", "haddock_rank", "haddock_score", "align_rmsd_A"])
    write_csv(cdr_summary, cdr_rows, ["model", "baseline", "haddock_rank", "haddock_score", "hotspot_overlap_count"])

    classification = output_dir / "reports" / f"{output_dir.name}_{target_receptor}_blocker_classification.csv"
    classification_md = classification.with_suffix(".md")
    run_logged(
        [
            sys.executable,
            WORKFLOW_DIR / "apply_blocker_judgment.py",
            "--occlusion-csv",
            cdr_summary,
            "--mechanism-csv",
            mechanism,
            "--candidate-name",
            f"{output_dir.name}_{target_receptor}",
            "--format-context",
            "naked_vhh",
            "--out-csv",
            classification,
            "--out-md",
            classification_md,
        ],
        log,
    )
    return mechanism, cdr_summary, classification


def resolve_run_dir(sync_root: Path, row: dict[str, str]) -> Path:
    relative = row.get("run_dir_relpath", "").strip()
    if relative and (sync_root / relative).is_dir():
        return sync_root / relative
    run_id = row["run_id"]
    candidates = [
        sync_root / "runs" / run_id / f"run_{run_id}",
        sync_root / "runs" / run_id / row.get("haddock_run_dir", f"run_{run_id}"),
    ]
    matches = [path for path in candidates if path.is_dir()]
    if len(matches) != 1:
        raise ValueError(f"Expected one synced run directory for {run_id}; found {matches}")
    return matches[0]


def completion_evidence(workdir: Path, run_id: str, expected_models: int) -> dict[str, Any]:
    paths = postprocess_artifact_paths(workdir, run_id)

    def rows_for(key: str) -> list[dict[str, str]]:
        path = paths[key]
        return read_csv(path) if path.is_file() else []

    row_counts = {
        "consensus_rows": len(rows_for("consensus")),
        "classification_8x6b_rows": len(rows_for("classification_8x6b")),
        "classification_9e6y_rows": len(rows_for("classification_9e6y")),
        "mechanism_8x6b_rows": len(rows_for("mechanism_8x6b")),
        "mechanism_9e6y_rows": len(rows_for("mechanism_9e6y")),
    }
    canonical_rows = rows_for("canonical_contact_summary")
    canonical_pair_rows = rows_for("canonical_contact_pairs")
    rank_rows = rows_for("ranks")
    canonical_failures = sum(row.get("status") != "PASS" for row in canonical_rows)
    contact_failures = (
        max(0, expected_models - row_counts["mechanism_8x6b_rows"])
        + max(0, expected_models - row_counts["mechanism_9e6y_rows"])
        + canonical_failures
    )
    complete = (
        all(value == expected_models for value in row_counts.values())
        and len(canonical_rows) == expected_models
        and len(rank_rows) == expected_models
        and paths["canonical_contact_pairs"].is_file()
        and contact_failures == 0
    )
    return {
        **row_counts,
        "contact_rows": row_counts["mechanism_8x6b_rows"] + row_counts["mechanism_9e6y_rows"],
        "canonical_contact_pose_rows": len(canonical_rows),
        "canonical_contact_pair_rows": len(canonical_pair_rows),
        "rank_rows": len(rank_rows),
        "contact_failures": contact_failures,
        "complete": complete,
    }


def process_one(
    row: dict[str, str],
    sync_root: Path,
    work_root: Path,
    top_n: int,
    min_models: int,
    run_manifest_sha256: str,
) -> dict[str, Any]:
    run_id = row["run_id"]
    workdir = work_root / run_id
    started = time.monotonic()
    try:
        run_dir = resolve_run_dir(sync_root, row)
        selected = selected_models(run_dir, top_n)
        if len(selected) < min_models:
            raise ValueError(f"Only {len(selected)} selected models for {run_id}; minimum is {min_models}")
        cluster_count = len({MODEL_RE.fullmatch(name).group(1) for name, _path, _rank in selected if MODEL_RE.fullmatch(name)})
        if cluster_count < 2:
            raise ValueError(f"Only {cluster_count} pose clusters for {run_id}")
        expected = len(selected)
        before = completion_evidence(workdir, run_id, expected)
        before.update({"selected_models": expected, "pose_clusters": cluster_count})
        if before["complete"]:
            marker = build_postprocess_marker(
                row, sync_root, workdir, run_dir, selected, before, run_manifest_sha256
            )
            if postprocess_marker_matches(workdir / "postprocess.complete.json", marker):
                return {
                    "run_id": run_id,
                    "pilot_id": row["pilot_id"],
                    "status": "SKIP_COMPLETE",
                    "seconds": 0.0,
                    "selected_models": expected,
                    "pose_clusters": cluster_count,
                    **before,
                }

        raw_dir = workdir / "poses_unpacked"
        raw_dir.mkdir(parents=True, exist_ok=True)
        ranks: dict[str, int] = {}
        for name, source, rank in selected:
            unpack_pose(source, raw_dir / f"{name}.pdb")
            ranks[name] = rank
        (workdir / "reports").mkdir(parents=True, exist_ok=True)
        write_csv(
            workdir / "reports/haddock3_model_ranks.csv",
            [{"model": name, "haddock_rank": ranks[name], "haddock_score": ""} for name in ranks],
            ["model", "haddock_rank", "haddock_score"],
        )
        source_receptor = row["receptor_id"].lower()
        canonical_pairs: list[dict[str, Any]] = []
        canonical_summary: list[dict[str, Any]] = []
        for name in ranks:
            pairs = canonical_contact_rows(raw_dir / f"{name}.pdb", name, source_receptor)
            canonical_pairs.extend(pairs)
            canonical_summary.append(
                {
                    "model": name,
                    "generation_receptor": source_receptor,
                    "canonical_residue_pair_count": len(pairs),
                    "status": "PASS",
                }
            )
        write_csv(
            workdir / "reports" / f"{run_id}_canonical_contact_pairs.csv",
            canonical_pairs,
            [
                "model",
                "generation_receptor",
                "pvrig_pose_resseq",
                "pvrig_pose_icode",
                "pvrig_resname",
                "pvrig_uniprot_position",
                "vhh_resseq",
                "vhh_icode",
                "vhh_resname",
                "min_heavy_atom_distance_A",
            ],
        )
        write_csv(
            workdir / "reports" / f"{run_id}_canonical_contact_summary.csv",
            canonical_summary,
            ["model", "generation_receptor", "canonical_residue_pair_count", "status"],
        )
        cdr_ranges = (row["cdr1_range"], row["cdr2_range"], row["cdr3_range"])
        classifications: dict[str, Path] = {}
        log_path = workdir / "postprocess.log"
        with log_path.open("w", encoding="utf-8") as log:
            for target_receptor in RECEPTORS:
                _mechanism, _cdr, classification = score_baseline(
                    list(ranks),
                    ranks,
                    raw_dir,
                    workdir,
                    source_receptor,
                    target_receptor,
                    cdr_ranges,
                    log,
                )
                classifications[target_receptor] = classification
            consensus = workdir / "reports" / f"{run_id}_dual_baseline_consensus.csv"
            run_logged(
                [
                    sys.executable,
                    WORKFLOW_DIR / "summarize_multibaseline_judgment.py",
                    "--classification",
                    f"8x6b={classifications['8x6b']}",
                    "--classification",
                    f"9e6y={classifications['9e6y']}",
                    "--candidate-name",
                    run_id,
                    "--out-csv",
                    consensus,
                    "--out-md",
                    consensus.with_suffix(".md"),
                ],
                log,
            )
        evidence = completion_evidence(workdir, run_id, expected)
        evidence.update({"selected_models": expected, "pose_clusters": cluster_count})
        if not evidence["complete"]:
            raise ValueError(f"Incomplete postprocess evidence for {run_id}: {evidence}")
        completion = build_postprocess_marker(
            row, sync_root, workdir, run_dir, selected, evidence, run_manifest_sha256
        )
        (workdir / "postprocess.complete.json").write_text(json.dumps(completion, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "run_id": run_id,
            "pilot_id": row["pilot_id"],
            "status": "PASS",
            "seconds": round(time.monotonic() - started, 3),
            "selected_models": expected,
            "pose_clusters": cluster_count,
            **evidence,
        }
    except Exception as error:
        return {
            "run_id": run_id,
            "pilot_id": row.get("pilot_id", ""),
            "status": f"FAIL:{type(error).__name__}:{error}",
            "seconds": round(time.monotonic() - started, 3),
            "complete": False,
        }


def filter_rows(rows: Sequence[dict[str, str]], args: argparse.Namespace) -> list[dict[str, str]]:
    output = list(rows)
    if args.pilot_id:
        wanted = set(args.pilot_id)
        output = [row for row in output if row["pilot_id"] in wanted]
        missing = wanted - {row["pilot_id"] for row in output}
        if missing:
            raise ValueError(f"Unknown pilot IDs: {sorted(missing)}")
    if args.receptor:
        output = [row for row in output if row["receptor_id"].lower() in set(args.receptor)]
    if args.seed_role:
        output = [row for row in output if row["seed_role"] in set(args.seed_role)]
    return output


def run(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_csv(args.manifest)
    rows = filter_rows(rows, args)
    if not rows:
        raise ValueError("No docking runs selected")
    invalid_protocol = [
        row["run_id"]
        for row in rows
        if row.get("protocol_id") != PROTOCOL_ID
        or row.get("per_candidate_failure_tolerance_override", "").lower() != "false"
    ]
    if invalid_protocol:
        raise ValueError(f"Invalid Pilot64 v1.1 protocol rows: {invalid_protocol[:10]}")
    args.work_root.mkdir(parents=True, exist_ok=True)
    manifest_sha256 = sha256_file(args.manifest)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                process_one,
                row,
                args.sync_root,
                args.work_root,
                args.top_n,
                args.min_models,
                manifest_sha256,
            ): row["run_id"]
            for row in rows
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["run_id"])
    failures = [row for row in results if row["status"] not in {"PASS", "SKIP_COMPLETE"}]
    audit = {
        "schema_version": "phase2_v3_p2_dual_docking_pilot_postprocess_audit_v1_1",
        "protocol_id": PROTOCOL_ID,
        "status": "PASS" if not failures else "FAIL_POSTPROCESS_INCOMPLETE",
        "manifest": str(args.manifest),
        "manifest_sha256": manifest_sha256,
        "sync_root": str(args.sync_root),
        "work_root": str(args.work_root),
        "requested_runs": len(rows),
        "complete_runs": sum(row["status"] in {"PASS", "SKIP_COMPLETE"} for row in results),
        "failed_runs": len(failures),
        "generation_receptor_counts": dict(Counter(row["receptor_id"].lower() for row in rows)),
        "seed_role_counts": dict(Counter(row["seed_role"] for row in rows)),
        "cross_conformer_numbering_remap": True,
        "results": results,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        raise RuntimeError(json.dumps(audit, indent=2, sort_keys=True))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sync-root", type=Path, default=DEFAULT_SYNC_ROOT)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--min-models", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--pilot-id", action="append")
    parser.add_argument("--receptor", action="append", choices=tuple(RECEPTORS))
    parser.add_argument("--seed-role", action="append", choices=("main", "replicate"))
    args = parser.parse_args(argv)
    if args.top_n <= 0 or args.min_models <= 0 or args.min_models > args.top_n or args.workers <= 0:
        parser.error("Require 0 < --min-models <= --top-n and positive --workers")
    return args


def main() -> None:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
