#!/usr/bin/env python3
"""Fold-local label-free PCA8 transformer for a future coarse-pose base branch.

The object is intentionally unaware of labels and split manifests.  The caller
must pass only the current train-parent rows to ``fit_pca8``.  Fold-specific PCA
coordinates must not be pooled as shared meta features; only fold-specific base
model predictions may be stacked.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PCA8State:
    mean: np.ndarray
    scale: np.ndarray
    retained_columns: np.ndarray
    components: np.ndarray
    singular_values: np.ndarray


def fit_pca8(train: np.ndarray, components: int = 8, minimum_scale: float = 1e-8) -> PCA8State:
    train = np.asarray(train, dtype=np.float64)
    if train.ndim != 2 or train.shape[0] < 2:
        raise ValueError("PCA train matrix must be two-dimensional with at least two rows")
    if not np.isfinite(train).all():
        raise ValueError("PCA train matrix contains non-finite values")
    mean = train.mean(axis=0)
    scale = train.std(axis=0)
    retained = np.flatnonzero(scale > minimum_scale)
    if len(retained) < components:
        raise ValueError("fewer nonconstant train columns than requested PCA components")
    standardized = (train[:, retained] - mean[retained]) / scale[retained]
    _, singular_values, right = np.linalg.svd(standardized, full_matrices=False)
    axes = right[:components].copy()
    for index in range(len(axes)):
        anchor = int(np.argmax(np.abs(axes[index])))
        if axes[index, anchor] < 0:
            axes[index] *= -1.0
    return PCA8State(mean, scale, retained, axes, singular_values[:components].copy())


def transform_pca8(values: np.ndarray, state: PCA8State) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != len(state.mean):
        raise ValueError("PCA transform matrix has incompatible shape")
    if not np.isfinite(values).all():
        raise ValueError("PCA transform matrix contains non-finite values")
    standardized = (
        values[:, state.retained_columns] - state.mean[state.retained_columns]
    ) / state.scale[state.retained_columns]
    transformed = standardized @ state.components.T
    if not np.isfinite(transformed).all():
        raise ValueError("PCA transform produced non-finite values")
    return transformed
