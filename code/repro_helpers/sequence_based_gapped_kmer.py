#!/usr/bin/env python3
"""Reproduce a sequence-based nanobody-antigen binding baseline.

This helper is intentionally separate from the downloaded third-party repository.
It removes hard-coded notebook paths and implements the paper's gapped k-mer
spectrum idea with a Random Forest baseline.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, matthews_corrcoef, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import ShuffleSplit, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier

try:
    import joblib
except Exception:  # pragma: no cover - optional save dependency
    joblib = None

DEFAULT_BINDING_CSV = Path("downloaded_models/Sequence-Based-NABP/Dataset/Ag-Nb Binding Data with Sequences - Sheet1.csv")
DEFAULT_DISTANCE_CSV = Path("downloaded_models/Sequence-Based-NABP/Dataset/Antibodies_Pairwise_Distance_Matrix.csv")
DEFAULT_ALPHABET = "ACDEFGHIKLMNPQRSTVWXY-"


def normalize_seq(seq: str) -> str:
    return "".join(ch if ch in DEFAULT_ALPHABET else "X" for ch in seq.strip().upper())


def gapped_variants(kmer: str) -> Iterable[str]:
    """Return original k-mer plus variants with exactly one gap.

    The paper's example for ACD is: ACD, -CD, A-D, AC-.
    """
    yield kmer
    for i in range(len(kmer)):
        yield kmer[:i] + "-" + kmer[i + 1 :]


def all_patterns(alphabet: str, k: int) -> List[str]:
    return ["".join(chars) for chars in itertools.product(alphabet, repeat=k)]


def spectrum(seq: str, k: int, pattern_to_index: Dict[str, int]) -> np.ndarray:
    seq = normalize_seq(seq)
    vec = np.zeros(len(pattern_to_index), dtype=np.float32)
    if len(seq) < k:
        return vec
    for start in range(0, len(seq) - k + 1):
        for pat in gapped_variants(seq[start : start + k]):
            idx = pattern_to_index.get(pat)
            if idx is not None:
                vec[idx] += 1.0
    total = vec.sum()
    if total:
        vec /= total
    return vec


def read_binding_rows(path: Path) -> List[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "nb_id": row.get("Nanobody ID", row.get("NB_ID", "")),
                    "ag_id": row.get("Antigen_ID", ""),
                    "nb_seq": row["Nanobody Sequence"],
                    "ag_seq": row["Antigen Sequence"],
                    "label": 1,
                }
            )
    return rows


def read_distance_matrix(path: Path) -> Dict[Tuple[str, str], float]:
    matrix = {}
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.reader(handle)
        header = next(reader)[1:]
        for row in reader:
            src = row[0]
            for dst, value in zip(header, row[1:]):
                try:
                    matrix[(src, dst)] = float(value)
                except ValueError:
                    continue
    return matrix


def augment_similar_positives(rows: List[dict], distances: Dict[Tuple[str, str], float], similarity_cutoff: float) -> List[dict]:
    by_ag = {}
    for row in rows:
        by_ag.setdefault(row["ag_id"], row["ag_seq"])
    known = {(r["nb_id"], r["ag_id"]) for r in rows}
    augmented = list(rows)
    for row in rows:
        for other_ag, other_seq in by_ag.items():
            if other_ag == row["ag_id"] or (row["nb_id"], other_ag) in known:
                continue
            if distances.get((row["ag_id"], other_ag), 1.0) < similarity_cutoff:
                clone = dict(row)
                clone["ag_id"] = other_ag
                clone["ag_seq"] = other_seq
                augmented.append(clone)
                known.add((row["nb_id"], other_ag))
    return augmented


def make_negatives(rows: List[dict], distances: Dict[Tuple[str, str], float], threshold: float, ratio: float, seed: int) -> List[dict]:
    rng = random.Random(seed)
    antigens = {}
    for row in rows:
        antigens[row["ag_id"]] = row["ag_seq"]
    known = {(r["nb_id"], r["ag_id"]) for r in rows}
    candidates = []
    for row in rows:
        for ag_id, ag_seq in antigens.items():
            if (row["nb_id"], ag_id) in known:
                continue
            if distances.get((row["ag_id"], ag_id), 0.0) >= threshold:
                candidates.append(
                    {
                        "nb_id": row["nb_id"],
                        "ag_id": ag_id,
                        "nb_seq": row["nb_seq"],
                        "ag_seq": ag_seq,
                        "label": 0,
                    }
                )
    rng.shuffle(candidates)
    n = min(len(candidates), int(round(len(rows) * ratio)))
    return candidates[:n]


def featurize(rows: Sequence[dict], k: int, alphabet: str) -> Tuple[np.ndarray, np.ndarray]:
    patterns = all_patterns(alphabet, k)
    pattern_to_index = {pattern: i for i, pattern in enumerate(patterns)}
    x = np.zeros((len(rows), len(patterns) * 2), dtype=np.float32)
    y = np.zeros(len(rows), dtype=np.int64)
    nb_cache = {}
    ag_cache = {}
    for i, row in enumerate(rows):
        nb_seq = row["nb_seq"]
        ag_seq = row["ag_seq"]
        if nb_seq not in nb_cache:
            nb_cache[nb_seq] = spectrum(nb_seq, k, pattern_to_index)
        if ag_seq not in ag_cache:
            ag_cache[ag_seq] = spectrum(ag_seq, k, pattern_to_index)
        x[i] = np.concatenate([nb_cache[nb_seq], ag_cache[ag_seq]])
        y[i] = int(row["label"])
    return x, y


def build_classifier(name: str, seed: int):
    if name == "rf":
        return RandomForestClassifier(n_estimators=300, random_state=seed, class_weight="balanced", n_jobs=-1)
    if name == "svm":
        return make_pipeline(StandardScaler(with_mean=False), LinearSVC(class_weight="balanced", random_state=seed, max_iter=20000))
    if name == "lr":
        return make_pipeline(StandardScaler(with_mean=False), LogisticRegression(class_weight="balanced", random_state=seed, max_iter=5000))
    if name == "dt":
        return DecisionTreeClassifier(random_state=seed, class_weight="balanced")
    if name == "nb":
        return GaussianNB()
    if name == "knn":
        return KNeighborsClassifier(n_neighbors=5)
    if name == "mlp":
        return make_pipeline(StandardScaler(with_mean=False), MLPClassifier(hidden_layer_sizes=(128,), max_iter=500, random_state=seed))
    raise ValueError(f"unknown classifier: {name}")


def score_model(model, x_test: np.ndarray, y_test: np.ndarray) -> dict:
    pred = model.predict(x_test)
    if hasattr(model, "predict_proba"):
        prob = model.predict_proba(x_test)[:, 1]
    elif hasattr(model, "decision_function"):
        score = model.decision_function(x_test)
        prob = (score - score.min()) / (score.max() - score.min() + 1e-12)
    else:
        prob = pred
    return {
        "accuracy": accuracy_score(y_test, pred),
        "precision": precision_score(y_test, pred, zero_division=0),
        "recall": recall_score(y_test, pred, zero_division=0),
        "f1_macro": f1_score(y_test, pred, average="macro", zero_division=0),
        "f1_weighted": f1_score(y_test, pred, average="weighted", zero_division=0),
        "mcc": matthews_corrcoef(y_test, pred),
        "roc_auc": roc_auc_score(y_test, prob) if len(set(y_test)) > 1 else float("nan"),
        "aupr": average_precision_score(y_test, prob) if len(set(y_test)) > 1 else float("nan"),
    }


def summarize(scores: List[dict]) -> dict:
    keys = scores[0].keys()
    return {key: {"mean": float(np.mean([s[key] for s in scores])), "std": float(np.std([s[key] for s in scores]))} for key in keys}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sequence-based nanobody-antigen gapped k-mer baseline")
    parser.add_argument("--binding-csv", type=Path, default=DEFAULT_BINDING_CSV)
    parser.add_argument("--distance-csv", type=Path, default=DEFAULT_DISTANCE_CSV)
    parser.add_argument("--out-dir", type=Path, default=Path("repro_outputs/sequence_based_gapped_kmer"))
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--alphabet", default=DEFAULT_ALPHABET)
    parser.add_argument("--negative-threshold", type=float, default=0.85)
    parser.add_argument("--negative-ratio", type=float, default=1.0)
    parser.add_argument("--similar-positive-cutoff", type=float, default=0.25)
    parser.add_argument("--no-similar-positive-augmentation", action="store_true")
    parser.add_argument("--splits", type=int, default=5)
    parser.add_argument("--test-size", type=float, default=0.30)
    parser.add_argument("--cv", choices=["shuffle", "stratified"], default="shuffle")
    parser.add_argument("--classifier", choices=["rf", "svm", "lr", "dt", "nb", "knn", "mlp"], default="rf")
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--save-model", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    positives = read_binding_rows(args.binding_csv)
    distances = read_distance_matrix(args.distance_csv)
    if not args.no_similar_positive_augmentation:
        positives = augment_similar_positives(positives, distances, args.similar_positive_cutoff)
    negatives = make_negatives(positives, distances, args.negative_threshold, args.negative_ratio, args.seed)
    rows = positives + negatives
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    x, y = featurize(rows, args.k, args.alphabet)

    if args.cv == "stratified":
        splitter = StratifiedKFold(n_splits=args.splits, shuffle=True, random_state=args.seed).split(x, y)
    else:
        splitter = ShuffleSplit(n_splits=args.splits, test_size=args.test_size, random_state=args.seed).split(x, y)

    fold_scores = []
    last_model = None
    for fold, (train_idx, test_idx) in enumerate(splitter, start=1):
        model = build_classifier(args.classifier, args.seed + fold)
        model.fit(x[train_idx], y[train_idx])
        metrics = score_model(model, x[test_idx], y[test_idx])
        metrics["fold"] = fold
        fold_scores.append(metrics)
        last_model = model
        print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))

    summary = summarize([{k: v for k, v in s.items() if k != "fold"} for s in fold_scores])
    metadata = {
        "binding_csv": str(args.binding_csv),
        "distance_csv": str(args.distance_csv),
        "k": args.k,
        "alphabet": args.alphabet,
        "classifier": args.classifier,
        "positives": len(positives),
        "negatives": len(negatives),
        "class_counts": dict(Counter(map(int, y))),
        "summary": summary,
    }
    (args.out_dir / "metrics.json").write_text(json.dumps({"folds": fold_scores, "metadata": metadata}, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.save_model and joblib is not None and last_model is not None:
        joblib.dump(last_model, args.out_dir / f"{args.classifier}_last_fold.joblib")
    print("summary", json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print("wrote", args.out_dir / "metrics.json")


if __name__ == "__main__":
    main()
