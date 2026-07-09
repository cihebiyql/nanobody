#!/usr/bin/env python3
"""Numerical regression test for align_pdb_by_chain.py Kabsch fitting."""

from __future__ import annotations

import math

import numpy as np

import align_pdb_by_chain as aligner


def main() -> None:
    rng = np.random.default_rng(7)
    mobile = rng.normal(size=(16, 3))
    angle = math.radians(37.0)
    rotation = np.array(
        [
            [math.cos(angle), -math.sin(angle), 0.0],
            [math.sin(angle), math.cos(angle), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    translation = np.array([4.0, -2.0, 8.0])
    reference = mobile @ rotation + translation
    r, mobile_centroid, ref_centroid, rmsd, n = aligner.kabsch_transform(mobile, reference)
    aligned = (mobile - mobile_centroid) @ r + ref_centroid
    max_abs_err = float(np.max(np.abs(aligned - reference)))
    if n != len(mobile) or rmsd > 1e-10 or max_abs_err > 1e-10:
        raise SystemExit(
            f"Kabsch regression failed: n={n} rmsd={rmsd:.3g} max_abs_err={max_abs_err:.3g}"
        )
    print(f"OK align_pdb_by_chain Kabsch test passed: rmsd={rmsd:.3g} max_abs_err={max_abs_err:.3g}")


if __name__ == "__main__":
    main()
