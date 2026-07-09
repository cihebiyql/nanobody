#!/usr/bin/env python3
"""Build the allowlist for syncing lightweight nanobody project artifacts."""
from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
MAX_BYTES = int(os.environ.get("NANOBODY_SYNC_MAX_BYTES", DEFAULT_MAX_BYTES))

ALLOWED_SUFFIXES = {
    ".bash",
    ".cfg",
    ".cif",
    ".conf",
    ".csv",
    ".css",
    ".fa",
    ".faa",
    ".fasta",
    ".fna",
    ".htm",
    ".html",
    ".ini",
    ".ipynb",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".markdown",
    ".md",
    ".mmcif",
    ".pdf",
    ".pdb",
    ".pml",
    ".png",
    ".py",
    ".r",
    ".rst",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsv",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}

ALLOWED_BASENAMES = {
    ".gitattributes",
    ".gitignore",
    "Dockerfile",
    "LICENSE",
    "Makefile",
    "NOTICE",
    "README",
    "requirements",
}

EXCLUDED_PREFIXES = {
    ".conda-envs",
    ".git",
    ".local",
    ".omx",
    "code/.omx",
    "code/downloaded_models/DeepNano-data",
    "code/downloaded_models/NABP-BERT/NABP-BERT-models",
    "code/downloaded_models/NABP-LSTM-Att/model",
    "code/downloads_background",
    "code/repro_outputs",
    "data/.omx",
    "data/datasets",
    "data/model_data",
    "data/models",
    "tools/.omx",
    "tools/nanobody_tool_survey/code",
    "tools/nanobody_tool_survey/logs",
    "tools/nanobody_tool_survey/papers",
}

EXCLUDED_DIR_NAMES = {
    ".cache",
    ".git",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "cache",
    "env",
    "gdown_venv",
    "logs",
    "node_modules",
    "pids",
    "status",
    "tmp",
    "venv",
}

DOWNLOAD_MODEL_SKIP_NAMES = {"_downloads", "data", "output", "outputs"}
DOCKING_SKIP_NAMES = {
    "boltz_8x6b",
    "boltz_poses",
    "chai1_8x6b",
    "chai1_poses",
    "complex",
    "haddock3",
    "logs",
    "monomer",
    "overlays",
    "remote",
    "test_outputs",
    "top_model_scores",
    "top_models_aligned_to_8x6b",
    "top_models_aligned_to_9e6y",
    "top_models_unzipped",
    "workdirs",
}


def as_posix(path: Path) -> str:
    text = path.as_posix()
    return "" if text == "." else text


def has_prefix(rel: str, prefix: str) -> bool:
    return rel == prefix or rel.startswith(prefix + "/")


def is_excluded_dir(rel: str) -> bool:
    if not rel or rel == ".":
        return False
    parts = rel.split("/")
    name = parts[-1]
    if name in EXCLUDED_DIR_NAMES:
        return True
    if name.startswith("gdown_venv.bad"):
        return True
    if any(has_prefix(rel, prefix) for prefix in EXCLUDED_PREFIXES):
        return True
    if len(parts) >= 3 and parts[0] == "code" and parts[1] == "downloaded_models":
        if name in DOWNLOAD_MODEL_SKIP_NAMES:
            return True
    if parts[0] == "docking":
        if name in DOCKING_SKIP_NAMES or name.startswith("run_"):
            return True
    return False


def is_allowed_file(rel: str, size: int) -> bool:
    path = Path(rel)
    name = path.name
    if name == ".DS_Store":
        return False
    if size > MAX_BYTES:
        return False
    if any(part in EXCLUDED_DIR_NAMES for part in path.parts[:-1]):
        return False
    if name in ALLOWED_BASENAMES:
        return True
    if name.startswith("."):
        return name in ALLOWED_BASENAMES
    return path.suffix.lower() in ALLOWED_SUFFIXES


def build_manifest(root: Path) -> list[tuple[str, int]]:
    selected: list[tuple[str, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = as_posix(Path(dirpath).relative_to(root)) if Path(dirpath) != root else ""
        kept_dirs = []
        for dirname in dirnames:
            rel = f"{rel_dir}/{dirname}" if rel_dir else dirname
            if not is_excluded_dir(rel):
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in filenames:
            file_path = Path(dirpath) / filename
            rel = as_posix(file_path.relative_to(root))
            try:
                stat = file_path.stat()
            except OSError:
                continue
            if file_path.is_file() and is_allowed_file(rel, stat.st_size):
                selected.append((rel, stat.st_size))
    return sorted(selected)


def write_manifest(files: list[tuple[str, int]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{rel}\n" for rel, _ in files), encoding="utf-8")


def print_summary(files: list[tuple[str, int]]) -> None:
    by_top: Counter[str] = Counter()
    bytes_by_top: defaultdict[str, int] = defaultdict(int)
    for rel, size in files:
        top = rel.split("/", 1)[0] if "/" in rel else "."
        by_top[top] += 1
        bytes_by_top[top] += size
    total = sum(bytes_by_top.values())
    print(f"selected_files={len(files)}")
    print(f"selected_bytes={total}")
    print(f"selected_mib={total / 1024 / 1024:.2f}")
    print("top,count,mib")
    for top, count in sorted(by_top.items(), key=lambda item: (-bytes_by_top[item[0]], item[0])):
        print(f"{top},{count},{bytes_by_top[top] / 1024 / 1024:.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--output", default=".omx/lightweight_sync_manifest.txt")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files = build_manifest(root)
    write_manifest(files, root / args.output)
    if args.summary:
        print_summary(files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
