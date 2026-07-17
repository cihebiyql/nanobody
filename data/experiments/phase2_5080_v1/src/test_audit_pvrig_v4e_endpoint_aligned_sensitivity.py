#!/usr/bin/env python3
from __future__ import annotations

import unittest

from audit_pvrig_v4e_endpoint_aligned_sensitivity import representative_pairs, scaled, sensitivity


def row(job: str, model: str, ref: str, score: float, value: float) -> dict[str, str]:
    return {
        "job_id": job,
        "model": model,
        "scoring_reference": ref,
        "haddock_score": str(score),
        "hotspot_overlap": str(value),
        "total_occlusion": str(value * 40),
        "cdr3_occlusion": str(value * 8),
        "cdr3_fraction": str(value / 80),
    }


def pair(job: str, model: str, score: float, value: float) -> dict[str, dict[str, str]]:
    return {
        ref: row(job, model, ref, score, value)
        for ref in ("8x6b", "9e6y")
    }


class EndpointAlignedSensitivityTests(unittest.TestCase):
    def test_decimal_boundary_is_exact(self) -> None:
        self.assertEqual(scaled(0.15, 1.1), 0.165)

    def test_representative_is_lowest_haddock_score_per_job(self) -> None:
        selected = representative_pairs([
            pair("j1", "worse", -10.0, 20.0),
            pair("j1", "best", -20.0, 20.0),
            pair("j2", "only", -5.0, 20.0),
        ])
        self.assertEqual([next(iter(item.values()))["model"] for item in selected], ["best", "only"])

    def test_sensitivity_passes_with_stable_pairs(self) -> None:
        result = sensitivity([pair("j1", "m", -1.0, 20.0)], 0.2)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["absolute_rate_deltas"], {"0.9": 0.0, "1.1": 0.0})

    def test_sensitivity_fails_large_boundary_shift(self) -> None:
        pairs = [pair(f"j{i}", "m", -1.0, 15.0) for i in range(4)]
        pairs.append(pair("stable", "m", -1.0, 20.0))
        result = sensitivity(pairs, 0.2)
        self.assertEqual(result["status"], "FAIL")
        self.assertGreater(result["absolute_rate_deltas"]["1.1"], 0.2)


if __name__ == "__main__":
    unittest.main()
