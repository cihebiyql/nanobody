#!/usr/bin/env python3
"""Run external nanobody-antigen prior models on PVRIG candidates.

This adapter keeps third-party scores as external priors. It does not label or
calibrate any output as blocker evidence.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NANOBIND_ROOT = Path("/mnt/d/work/抗体/code/downloaded_models/NanoBind")
DEFAULT_DEEPNANO_ROOT = Path("/mnt/d/work/抗体/code/downloaded_models/DeepNano")
DEFAULT_OUTPUT = REPO_ROOT / "experiments/phase2_5080_v1/external_priors/external_prior_scores_v1.csv"
DEFAULT_LOOKUP_CSVS = [
    REPO_ROOT / "model_data/mvp_candidates_v0.csv",
    REPO_ROOT / "reports/mvp_pvrig_top_candidates_v0.csv",
    REPO_ROOT / "model_data/index_v0_samples.csv",
]

MODEL_ALIASES = {
    "all": ["nanobind_seq", "nanobind_site", "nanobind_pro", "deepnano_seq", "deepnano_site"],
    "nanobind": ["nanobind_seq", "nanobind_site", "nanobind_pro"],
    "deepnano": ["deepnano_seq", "deepnano_site"],
}
SUPPORTED_MODELS = tuple(MODEL_ALIASES["all"])
ESM2_NAME = "esm2_t6_8M_UR50D"
ESM2_HIDDEN = 320


class ExternalPriorError(RuntimeError):
    """Expected adapter failure that should become an unavailable status."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run NanoBind/DeepNano external priors against a candidate CSV and PVRIG ECD FASTA."
    )
    parser.add_argument("--candidates-csv", required=True, type=Path, help="Candidate CSV with IDs and VHH sequences.")
    parser.add_argument("--pvrig-ecd-fasta", required=True, type=Path, help="PVRIG ECD antigen FASTA.")
    parser.add_argument(
        "--models",
        default="all",
        help="Comma-separated model selection: all, nanobind, deepnano, nanobind_seq, nanobind_site, nanobind_pro, deepnano_seq, deepnano_site.",
    )
    parser.add_argument("--output-csv", default=DEFAULT_OUTPUT, type=Path, help="Long-form output CSV path.")
    parser.add_argument("--id-column", default="auto", help="Candidate ID column, or auto.")
    parser.add_argument("--sequence-column", default="auto", help="VHH sequence column, or auto.")
    parser.add_argument(
        "--sequence-lookup-csv",
        action="append",
        type=Path,
        default=[],
        help="Optional CSV used to resolve candidate_id -> vhh_seq. Can be repeated.",
    )
    parser.add_argument("--nanobind-root", default=DEFAULT_NANOBIND_ROOT, type=Path, help="NanoBind checkout root.")
    parser.add_argument("--deepnano-root", default=DEFAULT_DEEPNANO_ROOT, type=Path, help="DeepNano checkout root.")
    parser.add_argument("--device", default="auto", help="Torch device: auto, cpu, cuda, cuda:0, etc.")
    parser.add_argument("--max-candidates", type=int, default=None, help="Optional smoke-test limit.")
    parser.add_argument("--site-threshold", type=float, default=0.5, help="Threshold used only for listing site positions.")
    parser.add_argument("--allow-missing-sequences", action="store_true", help="Emit unavailable rows when sequences cannot be resolved.")
    return parser.parse_args()


def read_csv_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ExternalPriorError(f"CSV has no header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def read_first_fasta(path: Path) -> Tuple[str, str]:
    if not path.exists():
        raise ExternalPriorError(f"FASTA not found: {path}")
    seq_id: Optional[str] = None
    seq_parts: List[str] = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if seq_id is not None:
                    break
                seq_id = line[1:].split()[0] or "pvrig_ecd"
            else:
                seq_parts.append(line)
    sequence = "".join(seq_parts).replace(" ", "").upper()
    if not sequence:
        raise ExternalPriorError(f"No sequence found in FASTA: {path}")
    return seq_id or "pvrig_ecd", sequence


def pick_column(fieldnames: Sequence[str], requested: str, candidates: Sequence[str]) -> Optional[str]:
    if requested != "auto":
        if requested not in fieldnames:
            raise ExternalPriorError(f"Requested column '{requested}' not found; available columns: {', '.join(fieldnames)}")
        return requested
    lowered = {name.lower(): name for name in fieldnames}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def normalize_sequence(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper().replace(" ", "")
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    return text


def build_sequence_lookup(paths: Iterable[Path]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            fields, rows = read_csv_rows(path)
        except Exception:
            continue
        id_col = pick_column(fields, "auto", ["candidate_id", "sample_id", "id", "sequence_id"])
        seq_col = pick_column(fields, "auto", ["vhh_seq", "nanobody_seq", "nb_seq", "sequence", "antibody_heavy_seq"])
        if not id_col or not seq_col:
            continue
        for row in rows:
            cid = (row.get(id_col) or "").strip()
            seq = normalize_sequence(row.get(seq_col))
            if cid and seq and cid not in lookup:
                lookup[cid] = seq
    return lookup


def resolve_candidates(args: argparse.Namespace) -> Tuple[List[Dict[str, str]], str, str]:
    fields, rows = read_csv_rows(args.candidates_csv)
    id_col = pick_column(fields, args.id_column, ["candidate_id", "sample_id", "id", "sequence_id"])
    seq_col = pick_column(fields, args.sequence_column, ["vhh_seq", "nanobody_seq", "nb_seq", "sequence", "antibody_heavy_seq"])
    if not id_col:
        raise ExternalPriorError("Could not infer an ID column; pass --id-column.")

    lookup_paths = list(args.sequence_lookup_csv) + DEFAULT_LOOKUP_CSVS
    sequence_lookup = build_sequence_lookup(lookup_paths)
    resolved: List[Dict[str, str]] = []
    for idx, row in enumerate(rows[: args.max_candidates] if args.max_candidates else rows):
        cid = (row.get(id_col) or f"row_{idx + 1}").strip() or f"row_{idx + 1}"
        seq = normalize_sequence(row.get(seq_col)) if seq_col else ""
        if not seq:
            seq = sequence_lookup.get(cid, "")
        if not seq and not args.allow_missing_sequences:
            # Still emit rows later; this keeps reruns auditable rather than failing mid-batch.
            seq = ""
        resolved.append({"candidate_id": cid, "vhh_seq": seq, "input_row_index": str(idx)})
    return resolved, id_col, seq_col or ""


def expand_models(selection: str) -> List[str]:
    models: List[str] = []
    for raw in selection.split(","):
        token = raw.strip().lower().replace("-", "_")
        if not token:
            continue
        if token in MODEL_ALIASES:
            models.extend(MODEL_ALIASES[token])
        elif token in SUPPORTED_MODELS:
            models.append(token)
        else:
            raise ExternalPriorError(f"Unsupported model selection '{raw}'. Supported: {', '.join(SUPPORTED_MODELS)}")
    deduped: List[str] = []
    for model in models:
        if model not in deduped:
            deduped.append(model)
    return deduped or list(SUPPORTED_MODELS)


def checkpoint_info(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {"checkpoint_path": str(path), "checkpoint_status": "missing", "checkpoint_size_bytes": "", "checkpoint_mtime": ""}
    stat = path.stat()
    return {
        "checkpoint_path": str(path),
        "checkpoint_status": "present",
        "checkpoint_size_bytes": str(stat.st_size),
        "checkpoint_mtime": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(stat.st_mtime)),
    }


def base_row(candidate: Dict[str, str], model_key: str, metadata: Dict[str, str]) -> Dict[str, str]:
    sequence = candidate.get("vhh_seq", "")
    row = {
        "candidate_id": candidate["candidate_id"],
        "input_row_index": candidate["input_row_index"],
        "candidate_sequence_length": str(len(sequence)) if sequence else "",
        "candidate_sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest() if sequence else "",
        "model_key": model_key,
        "model_family": metadata.get("model_family", ""),
        "model_name": metadata.get("model_name", ""),
        "model_version": metadata.get("model_version", ""),
        "status": "unavailable",
        "raw_score": "",
        "raw_prediction": "",
        "raw_score_name": metadata.get("raw_score_name", ""),
        "raw_site_scores_json": "",
        "raw_site_positions_json": "",
        "raw_components_json": "",
        "checkpoint_path": metadata.get("checkpoint_path", ""),
        "checkpoint_status": metadata.get("checkpoint_status", ""),
        "checkpoint_size_bytes": metadata.get("checkpoint_size_bytes", ""),
        "checkpoint_mtime": metadata.get("checkpoint_mtime", ""),
        "source_model_root": metadata.get("source_model_root", ""),
        "source_script": metadata.get("source_script", ""),
        "adapter_version": "external_priors_v1.1",
        "evidence_boundary": "external_nanobody_antigen_prior_not_blocker_score",
        "error": "",
    }
    return row


def unavailable_rows(candidates: Sequence[Dict[str, str]], model_key: str, metadata: Dict[str, str], reason: str) -> List[Dict[str, str]]:
    rows = []
    for candidate in candidates:
        row = base_row(candidate, model_key, metadata)
        row["status"] = "unavailable"
        row["error"] = reason
        rows.append(row)
    return rows


def import_requirements(root: Path, module_name: str, class_name: str) -> Any:
    if not root.exists():
        raise ExternalPriorError(f"model root not found: {root}")
    missing = []
    for dep in ["torch", "transformers", "Bio"]:
        try:
            importlib.import_module(dep)
        except Exception as exc:
            missing.append(f"{dep} ({exc.__class__.__name__}: {exc})")
    if missing:
        raise ExternalPriorError("missing Python dependencies: " + "; ".join(missing))
    top_level = module_name.split(".", 1)[0]
    loaded = sys.modules.get(top_level)
    loaded_origins: list[str] = []
    if loaded:
        if getattr(loaded, "__file__", None):
            loaded_origins.append(str(loaded.__file__))
        loaded_origins.extend(str(path) for path in getattr(loaded, "__path__", []))
    if loaded:
        belongs_to_root = False
        for origin in loaded_origins:
            try:
                belongs_to_root = belongs_to_root or Path(origin).resolve().is_relative_to(root.resolve())
            except (OSError, ValueError):
                continue
        if not belongs_to_root:
            for key in [name for name in sys.modules if name == top_level or name.startswith(f"{top_level}.")]:
                del sys.modules[key]
    for model_root in (DEFAULT_NANOBIND_ROOT, DEFAULT_DEEPNANO_ROOT):
        while str(model_root) in sys.path:
            sys.path.remove(str(model_root))
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    except Exception as exc:
        raise ExternalPriorError(f"could not import {module_name}.{class_name}: {exc}") from exc


@contextlib.contextmanager
def pushd_and_syspath(root: Path):
    old_cwd = Path.cwd()
    old_path = list(sys.path)
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        yield
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_path


def torch_device(device_arg: str) -> Any:
    import torch

    if device_arg == "auto":
        return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if device_arg == "cuda":
        return torch.device("cuda:0")
    return torch.device(device_arg)


def as_float(value: Any) -> float:
    try:
        if hasattr(value, "detach"):
            value = value.detach()
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            value = value.numpy()
        if hasattr(value, "flatten"):
            value = value.flatten()[0]
        return float(value)
    except Exception as exc:
        raise ExternalPriorError(f"could not convert model output to float: {exc}") from exc


def tensor_to_float_list(value: Any) -> List[float]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    try:
        return [float(x) for x in value.reshape(-1).tolist()]
    except AttributeError:
        return [float(x) for x in value]


def run_loaded_model(
    candidates: Sequence[Dict[str, str]],
    model_key: str,
    metadata: Dict[str, str],
    predictor: Callable[[str, str], Dict[str, str]],
    antigen_seq: str,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for candidate in candidates:
        row = base_row(candidate, model_key, metadata)
        nb_seq = candidate.get("vhh_seq", "")
        if not nb_seq:
            row["status"] = "unavailable"
            row["error"] = "candidate sequence unavailable; provide a sequence column or lookup CSV"
            rows.append(row)
            continue
        try:
            prediction = predictor(nb_seq, antigen_seq)
            row.update(prediction)
            row["status"] = "ok"
        except Exception as exc:
            row["status"] = "unavailable"
            row["error"] = f"prediction failed: {exc.__class__.__name__}: {exc}"
        rows.append(row)
    return rows


def nanobind_metadata(root: Path, kind: str) -> Dict[str, str]:
    scripts = {"seq": "predict_seq.py", "site": "predict_site.py", "pro": "predict_pro.py"}
    ckpts = {
        "seq": "NanoBind_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model",
        "site": "NanoBind_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model",
        "pro": "NanoBind_pro(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model",
    }
    info = checkpoint_info(root / "output/checkpoint" / ckpts[kind])
    info.update(
        {
            "model_family": "NanoBind",
            "model_name": f"NanoBind-{kind}",
            "model_version": "local_checkout_esm2_t6_8M_UR50D",
            "source_model_root": str(root),
            "source_script": str(root / scripts[kind]),
            "raw_score_name": "probability" if kind != "site" else "antigen_site_probability_vector",
        }
    )
    return info


def run_nanobind(
    candidates: Sequence[Dict[str, str]], root: Path, kind: str, antigen_seq: str, device_arg: str, site_threshold: float
) -> List[Dict[str, str]]:
    model_key = f"nanobind_{kind}"
    metadata = nanobind_metadata(root, kind)
    try:
        if metadata["checkpoint_status"] != "present":
            raise ExternalPriorError(f"checkpoint missing: {metadata['checkpoint_path']}")
        class_name = {"seq": "NanoBind_seq", "site": "NanoBind_site", "pro": "NanoBind_pro"}[kind]
        model_class = import_requirements(root, f"models.NanoBind_{kind}", class_name)
        import torch

        device = torch_device(device_arg)
        with pushd_and_syspath(root):
            if kind == "pro":
                site_ckpt = root / "output/checkpoint/NanoBind_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model"
                model = model_class(
                    pretrained_model=str(root / "models" / ESM2_NAME),
                    hidden_size=ESM2_HIDDEN,
                    finetune=0,
                    Model_BSite_path=str(site_ckpt),
                ).to(device)
            else:
                model = model_class(pretrained_model=str(root / "models" / ESM2_NAME), hidden_size=ESM2_HIDDEN, finetune=0).to(device)
            weights = torch.load(metadata["checkpoint_path"], map_location=device)
            model.load_state_dict(weights)
            model.eval()

            def predictor(nb_seq: str, ag_seq: str) -> Dict[str, str]:
                with torch.no_grad():
                    if kind == "pro":
                        # NanoBind-pro squeezes away the batch axis at batch=1; duplicate and keep item 0.
                        output = model([nb_seq, nb_seq], [ag_seq, ag_seq], device)[0]
                    else:
                        output = model(nb_seq, ag_seq, device)
                if kind == "site":
                    scores = tensor_to_float_list(output)
                    positions = [
                        {"position_1based": i + 1, "aa": ag_seq[i], "score": score}
                        for i, score in enumerate(scores[: len(ag_seq)])
                        if score > site_threshold
                    ]
                    return {
                        "raw_site_scores_json": json.dumps(scores[: len(ag_seq)], separators=(",", ":")),
                        "raw_site_positions_json": json.dumps(positions, separators=(",", ":")),
                    }
                score = as_float(output)
                threshold = 0.3 if kind == "seq" else 0.5
                return {"raw_score": f"{score:.10g}", "raw_prediction": str(int(score > threshold))}

            return run_loaded_model(candidates, model_key, metadata, predictor, antigen_seq)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ExternalPriorError) else f"{exc.__class__.__name__}: {exc}"
        return unavailable_rows(candidates, model_key, metadata, reason)


def deepnano_metadata(root: Path, kind: str, esm2: str = "8M") -> Dict[str, str]:
    ckpts = {
        "seq": f"DeepNano_seq({ESM2_NAME})_SabdabData_finetune1_TF0_best.model",
        "site": f"DeepNano_site({ESM2_NAME})_SabdabData_finetune1_TF0_best.model",
    }
    info = checkpoint_info(root / "output/checkpoint" / ckpts[kind])
    info.update(
        {
            "model_family": "DeepNano",
            "model_name": f"DeepNano-{kind}(NAI)-{esm2}",
            "model_version": "local_checkout_esm2_t6_8M_UR50D",
            "source_model_root": str(root),
            "source_script": str(root / "predict.py"),
            "raw_score_name": "ensemble_probability" if kind == "seq" else "antigen_site_probability_vector",
        }
    )
    return info


def run_deepnano(
    candidates: Sequence[Dict[str, str]], root: Path, kind: str, antigen_seq: str, device_arg: str, site_threshold: float
) -> List[Dict[str, str]]:
    model_key = f"deepnano_{kind}"
    metadata = deepnano_metadata(root, kind)
    try:
        if metadata["checkpoint_status"] != "present":
            raise ExternalPriorError(f"checkpoint missing: {metadata['checkpoint_path']}")
        class_name = "DeepNano_seq" if kind == "seq" else "DeepNano_site"
        model_class = import_requirements(root, "models.models", class_name)
        import torch

        device = torch_device(device_arg)
        with pushd_and_syspath(root):
            model = model_class(pretrained_model=str(root / "models" / ESM2_NAME), hidden_size=ESM2_HIDDEN, finetune=0).to(device)
            weights = torch.load(metadata["checkpoint_path"], map_location=device)
            model.load_state_dict(weights)
            model.eval()

            def predictor(nb_seq: str, ag_seq: str) -> Dict[str, str]:
                # DeepNano tokenizes DataLoader-style batches, unlike NanoBind's scalar-string API.
                with torch.no_grad():
                    output = model([nb_seq], [ag_seq], device)
                if kind == "site":
                    scores = tensor_to_float_list(output)
                    positions = [
                        {"position_1based": i + 1, "aa": ag_seq[i], "score": score}
                        for i, score in enumerate(scores[: len(ag_seq)])
                        if score > site_threshold
                    ]
                    return {
                        "raw_site_scores_json": json.dumps(scores[: len(ag_seq)], separators=(",", ":")),
                        "raw_site_positions_json": json.dumps(positions, separators=(",", ":")),
                    }
                p_ave, p_min, p_max = output
                components = {"p_ave": as_float(p_ave), "p_min": as_float(p_min), "p_max": as_float(p_max)}
                score = (components["p_ave"] + components["p_min"] + components["p_max"]) / 3.0
                return {
                    "raw_score": f"{score:.10g}",
                    "raw_prediction": str(int(score > 0.5)),
                    "raw_components_json": json.dumps(components, separators=(",", ":")),
                }

            return run_loaded_model(candidates, model_key, metadata, predictor, antigen_seq)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ExternalPriorError) else f"{exc.__class__.__name__}: {exc}"
        return unavailable_rows(candidates, model_key, metadata, reason)


def write_rows(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "candidate_id",
        "input_row_index",
        "candidate_sequence_length",
        "candidate_sequence_sha256",
        "antigen_id",
        "antigen_length",
        "antigen_sequence_sha256",
        "antigen_fasta_path",
        "model_key",
        "model_family",
        "model_name",
        "model_version",
        "status",
        "raw_score",
        "raw_prediction",
        "raw_score_name",
        "raw_site_scores_json",
        "raw_site_positions_json",
        "raw_components_json",
        "checkpoint_path",
        "checkpoint_status",
        "checkpoint_size_bytes",
        "checkpoint_mtime",
        "source_model_root",
        "source_script",
        "adapter_version",
        "evidence_boundary",
        "error",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def main() -> int:
    args = parse_args()
    models = expand_models(args.models)
    candidates, id_col, seq_col = resolve_candidates(args)
    antigen_id, antigen_seq = read_first_fasta(args.pvrig_ecd_fasta)

    rows: List[Dict[str, str]] = []
    for model_key in models:
        if model_key.startswith("nanobind_"):
            rows.extend(run_nanobind(candidates, args.nanobind_root, model_key.split("_", 1)[1], antigen_seq, args.device, args.site_threshold))
        elif model_key.startswith("deepnano_"):
            rows.extend(run_deepnano(candidates, args.deepnano_root, model_key.split("_", 1)[1], antigen_seq, args.device, args.site_threshold))
        else:
            raise ExternalPriorError(f"internal unsupported model key: {model_key}")
    antigen_sha256 = hashlib.sha256(antigen_seq.encode("ascii")).hexdigest()
    for row in rows:
        row.update(
            {
                "antigen_id": antigen_id,
                "antigen_length": str(len(antigen_seq)),
                "antigen_sequence_sha256": antigen_sha256,
                "antigen_fasta_path": str(args.pvrig_ecd_fasta),
            }
        )

    write_rows(args.output_csv, rows)
    status_counts: Dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    print(
        json.dumps(
            {
                "output_csv": str(args.output_csv),
                "candidate_count": len(candidates),
                "row_count": len(rows),
                "models": models,
                "status_counts": status_counts,
                "candidate_id_column": id_col,
                "candidate_sequence_column": seq_col,
                "antigen_id": antigen_id,
                "evidence_boundary": "external_nanobody_antigen_prior_not_blocker_score",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExternalPriorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
