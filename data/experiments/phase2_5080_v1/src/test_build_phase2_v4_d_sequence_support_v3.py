#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_phase2_v4_d_sequence_support_v3.py")
SPEC = importlib.util.spec_from_file_location("build_phase2_v4_d_sequence_support_v3", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def record(
    candidate_id: str,
    parent: str,
    full: tuple[float, ...],
    cdr_embedding: tuple[float, ...],
    cdrs: tuple[str, str, str],
    contact: tuple[float, ...],
    *,
    digest: str | None = None,
):
    return MODULE.SupportRecord(
        candidate_id=candidate_id,
        sequence_sha256=digest or (candidate_id.lower().replace("_", "") + "0" * 64)[:64],
        declared_parent=parent,
        full_esm=full,
        cdr_esm=cdr_embedding,
        cdr1=cdrs[0],
        cdr2=cdrs[1],
        cdr3=cdrs[2],
        contact=contact,
    )


def thresholds(value: float = 0.01) -> dict[str, float]:
    output = {channel: value for channel in MODULE.REQUIRED_CHANNELS}
    output["cdr1_edit"] = 0.0
    output["cdr2_edit"] = 0.0
    output["cdr3_edit"] = 0.0
    output["cdr_2mer_cosine"] = 0.0
    output["cdr_3mer_cosine"] = 0.0
    return output


class SupportV3SyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lock = MODULE.load_preregistration()
        cls.a1 = record(
            "A1", "PA", (1.0, 0.0, 0.0), (1.0, 0.0, 0.0),
            ("ACDE", "FGHI", "KLMN"), (0.0, 0.0), digest="a" * 64,
        )
        cls.a2 = record(
            "A2", "PA", (0.0, 1.0, 0.0), (0.0, 1.0, 0.0),
            ("NPQR", "STVW", "YACD"), (1.0, 1.0), digest="b" * 64,
        )
        cls.a3 = record(
            "A3", "PA", (0.0, 0.0, 1.0), (0.0, 0.0, 1.0),
            ("CEGH", "IKLM", "NPQS"), (2.0, 2.0), digest="c" * 64,
        )
        cls.b1 = record(
            "B1", "PB", (0.7, 0.7, 0.0), (0.0, 0.7, 0.7),
            ("RSTV", "WYAC", "DEFG"), (3.0, 3.0), digest="d" * 64,
        )
        cls.references = [cls.a1, cls.a2, cls.a3, cls.b1]
        cls.thresholds = thresholds()

    def panel(self, prototype, *, count: int = 20):
        return [
            replace(prototype, candidate_id=f"{prototype.candidate_id}_{index}", sequence_sha256=f"{index + 10:064x}")
            for index in range(count)
        ]

    def assert_null_passes_and_leak_fails(self, kind: str, prototype, leak):
        safe = MODULE.evaluate_null_control(
            kind,
            self.panel(prototype),
            self.references,
            self.thresholds,
            self.thresholds,
            self.lock,
        )
        self.assertTrue(safe["passed"], safe)
        leaky_panel = self.panel(prototype, count=17) + self.panel(leak, count=3)
        failed = MODULE.evaluate_null_control(
            kind,
            leaky_panel,
            self.references,
            self.thresholds,
            self.thresholds,
            self.lock,
        )
        self.assertFalse(failed["passed"], failed)

    def test_preregistration_and_locked_input_hashes_fail_closed(self) -> None:
        self.assertEqual(
            MODULE.sha256_file(MODULE.DEFAULT_PREREGISTRATION),
            MODULE.EXPECTED_PREREGISTRATION_SHA256,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "locked.json"
            raw = MODULE.DEFAULT_PREREGISTRATION.read_bytes()
            path.write_bytes(raw)
            MODULE.verify_locked_path(path, MODULE.sha256_bytes(raw), "synthetic")
            path.write_bytes(raw + b"\n")
            with self.assertRaises(MODULE.SupportV3Error):
                MODULE.verify_locked_path(path, MODULE.sha256_bytes(raw), "synthetic")
            with self.assertRaises(MODULE.SupportV3Error):
                MODULE.load_preregistration(path)

    def test_same_neighbor_domain_logic_never_borrows_across_references(self) -> None:
        legitimate = replace(
            self.a1, candidate_id="A_LEGIT", sequence_sha256="e" * 64
        )
        decision = MODULE.classify_domain(
            legitimate, self.references, self.thresholds, self.thresholds
        )
        self.assertEqual(decision.label, "IN_DOMAIN")
        self.assertEqual(decision.neighbor_id, "A1")

        mosaic = record(
            "A_MOSAIC", "PA", self.a1.full_esm, self.a2.cdr_esm,
            (self.a2.cdr1, self.a2.cdr2, self.a2.cdr3), self.a3.contact,
            digest="f" * 64,
        )
        decision = MODULE.classify_domain(
            mosaic, self.references, self.thresholds, self.thresholds
        )
        self.assertEqual(decision.label, "OUT_OF_DOMAIN")

        unseen = replace(
            self.b1, candidate_id="UNSEEN_NEAR", sequence_sha256="1" * 64,
            declared_parent="P_UNSEEN",
        )
        decision = MODULE.classify_domain(
            unseen, self.references, self.thresholds, self.thresholds
        )
        self.assertEqual(decision.label, "NEAR_DOMAIN")
        self.assertEqual(decision.neighbor_id, "B1")

    def test_cdr_composition_shuffle_null_gate(self) -> None:
        shuffled = record(
            "SHUFFLE", "PA", self.a1.full_esm, self.a3.cdr_esm,
            ("EDCA", "IHGF", "NMLK"), self.a3.contact,
        )
        leak = replace(self.a1, candidate_id="SHUFFLE_LEAK", sequence_sha256="2" * 64)
        self.assert_null_passes_and_leak_fails("cdr_composition_shuffle", shuffled, leak)

    def test_cross_parent_cdr_graft_null_gate(self) -> None:
        graft = record(
            "GRAFT", "PA", self.a1.full_esm, self.b1.cdr_esm,
            (self.b1.cdr1, self.b1.cdr2, self.b1.cdr3), self.b1.contact,
        )
        leak = replace(self.a1, candidate_id="GRAFT_LEAK", sequence_sha256="3" * 64)
        self.assert_null_passes_and_leak_fails("cross_parent_cdr_graft", graft, leak)

    def test_channel_splice_null_gate(self) -> None:
        splice = record(
            "SPLICE", "PA", self.a1.full_esm, self.a2.cdr_esm,
            (self.a2.cdr1, self.a2.cdr2, self.a2.cdr3), self.a3.contact,
        )
        leak = replace(self.a1, candidate_id="SPLICE_LEAK", sequence_sha256="4" * 64)
        self.assert_null_passes_and_leak_fails("channel_splice", splice, leak)

    def test_unseen_parent_chimera_null_gate(self) -> None:
        chimera = record(
            "CHIMERA", "P_UNSEEN", self.a1.full_esm, self.b1.cdr_esm,
            (self.b1.cdr1, self.b1.cdr2, self.b1.cdr3), self.a1.contact,
        )
        near_leak = replace(
            self.b1, candidate_id="CHIMERA_NEAR_LEAK", sequence_sha256="5" * 64,
            declared_parent="P_UNSEEN",
        )
        self.assert_null_passes_and_leak_fails("unseen_parent_chimera", chimera, near_leak)


if __name__ == "__main__":
    unittest.main()
