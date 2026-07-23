from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import torch
from torch import nn


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "materialize_v220_paired_initial_state_v1.py"
)
SPEC = importlib.util.spec_from_file_location("v220_paired_initial_state", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class SyntheticHead(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.shared_encoder = nn.Linear(3, 4)
        self.attention_scalar = nn.Linear(4, 2)
        self.contact = nn.Linear(4, 3)
        self.config = types.SimpleNamespace(
            enable_contact_evidence=True, contact_encoder_gradient="shared"
        )


class SyntheticBackbone(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.embedding = nn.Embedding(19, 11)
        self.projection = nn.Linear(11, 7)
        for parameter in self.parameters():
            parameter.requires_grad_(False)


class SyntheticLaneE(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.backbone = SyntheticBackbone()
        self.head = SyntheticHead()


BACKBONE_IDENTITY = hashlib.sha256(b"synthetic-frozen-backbone-v1").hexdigest()


def factory(seed: int = 43):
    def build() -> SyntheticLaneE:
        mod.seed_everything(seed)
        return SyntheticLaneE()

    return build


def roles(model: nn.Module):
    return mod.infer_parameter_roles(model)


class PairedInitialStateTests(unittest.TestCase):
    def test_five_folds_are_byte_identical_and_hash_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "paired"
            manifest = mod.materialize_paired_initial_states(
                model_factory=factory(),
                role_resolver=roles,
                output_dir=output,
                backbone_identity_sha256=BACKBONE_IDENTITY,
            )
            self.assertTrue(manifest["all_fold_serializations_identical"])
            hashes = {
                mod.file_sha256(output / f"fold_{fold}" / "initial_state_seed43.pt")
                for fold in range(5)
            }
            self.assertEqual(len(hashes), 1)
            self.assertEqual(hashes.pop(), manifest["serialized_checkpoint_sha256"])
            saved = json.loads(
                (output / "PAIRED_INITIAL_STATE_MANIFEST.json").read_text()
            )
            self.assertEqual(saved["initialization_seed"], 43)
            self.assertEqual(saved["contact_encoder_gradient"], "shared")
            self.assertEqual(saved["serialized_state_scope"], "model.head")
            self.assertEqual(
                saved["backbone_binding"]["artifact_identity_sha256"],
                BACKBONE_IDENTITY,
            )
            checkpoint = mod._decode_checkpoint(
                output / "paired_initial_state_seed43.pt"
            )
            self.assertTrue(checkpoint["head_state_dict"])
            self.assertTrue(
                all(name.startswith("head.") for name in checkpoint["head_state_dict"])
            )
            self.assertFalse(
                any("backbone" in name for name in checkpoint["head_state_dict"])
            )
            self.assertFalse(
                checkpoint["backbone_binding"]["serialized_in_checkpoint"]
            )

    def test_runner_save_load_and_verify_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fold0.pt"
            mod.seed_everything(43)
            original = SyntheticLaneE()
            receipt = mod.save_paired_initial_state(
                path,
                original,
                0,
                43,
                backbone_identity_sha256=BACKBONE_IDENTITY,
            )
            backbone_before = mod.canonical_state_sha256(
                original.backbone.state_dict()
            )
            with torch.no_grad():
                for parameter in original.head.parameters():
                    parameter.add_(5.0)
            loaded = mod.load_and_verify_initial_state(
                path,
                original,
                backbone_identity_sha256=BACKBONE_IDENTITY,
                receipt_path=Path(f"{path}.receipt.json"),
                expected_checkpoint_sha256=receipt[
                    "serialized_checkpoint_sha256"
                ],
                expected_receipt_sha256=mod.file_sha256(
                    Path(f"{path}.receipt.json")
                ),
            )
            self.assertEqual(loaded["hashes"], receipt["hashes"])
            self.assertEqual(loaded["status"], "PASS_INITIAL_STATE_LOADED_AND_VERIFIED")
            self.assertEqual(loaded["serialized_state_scope"], "model.head")
            self.assertEqual(
                loaded["hashes"]["parameter_order_sha256"],
                loaded["hashes"]["head_parameter_order_sha256"],
            )
            self.assertEqual(
                backbone_before,
                mod.canonical_state_sha256(original.backbone.state_dict()),
            )
            sidecar = json.loads(Path(f"{path}.receipt.json").read_text())
            self.assertEqual(sidecar["fold_id"], 0)

    def test_runner_api_serializes_same_seed_state_identically_across_folds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hashes = []
            state_hashes = []
            for fold in (0, 1):
                mod.seed_everything(43)
                model = SyntheticLaneE()
                receipt = mod.save_paired_initial_state(
                    Path(temporary) / f"fold_{fold}.pt",
                    model,
                    fold,
                    43,
                    backbone_identity_sha256=BACKBONE_IDENTITY,
                )
                hashes.append(receipt["serialized_checkpoint_sha256"])
                state_hashes.append(receipt["hashes"])
            self.assertEqual(hashes[0], hashes[1])
            self.assertEqual(state_hashes[0], state_hashes[1])
            self.assertEqual(
                state_hashes[0]["backbone_identity_sha256"], BACKBONE_IDENTITY
            )

    def test_hash_subsets_have_expected_mutation_scope(self) -> None:
        mod.seed_everything(43)
        model = SyntheticLaneE()
        baseline = mod.state_hashes(model, BACKBONE_IDENTITY)
        with torch.no_grad():
            model.head.contact.weight.add_(1.0)
        contact_changed = mod.state_hashes(model, BACKBONE_IDENTITY)
        self.assertNotEqual(
            baseline["full_state_sha256"], contact_changed["full_state_sha256"]
        )
        self.assertEqual(
            baseline["scalar_state_sha256"], contact_changed["scalar_state_sha256"]
        )
        self.assertEqual(
            baseline["shared_state_sha256"], contact_changed["shared_state_sha256"]
        )

        mod.seed_everything(43)
        model = SyntheticLaneE()
        baseline = mod.state_hashes(model, BACKBONE_IDENTITY)
        with torch.no_grad():
            model.head.attention_scalar.weight.add_(1.0)
        scalar_changed = mod.state_hashes(model, BACKBONE_IDENTITY)
        self.assertNotEqual(
            baseline["scalar_state_sha256"], scalar_changed["scalar_state_sha256"]
        )
        self.assertEqual(
            baseline["shared_state_sha256"], scalar_changed["shared_state_sha256"]
        )

        mod.seed_everything(43)
        model = SyntheticLaneE()
        baseline = mod.state_hashes(model, BACKBONE_IDENTITY)
        with torch.no_grad():
            model.head.shared_encoder.weight.add_(1.0)
        shared_changed = mod.state_hashes(model, BACKBONE_IDENTITY)
        self.assertNotEqual(
            baseline["full_state_sha256"], shared_changed["full_state_sha256"]
        )
        self.assertNotEqual(
            baseline["scalar_state_sha256"], shared_changed["scalar_state_sha256"]
        )
        self.assertNotEqual(
            baseline["shared_state_sha256"], shared_changed["shared_state_sha256"]
        )

    def test_seed_and_parameter_order_are_bound(self) -> None:
        mod.seed_everything(43)
        first = SyntheticLaneE()
        mod.seed_everything(44)
        second = SyntheticLaneE()
        self.assertNotEqual(
            mod.state_hashes(first, BACKBONE_IDENTITY)["full_state_sha256"],
            mod.state_hashes(second, BACKBONE_IDENTITY)["full_state_sha256"],
        )
        self.assertEqual(
            mod.state_hashes(first, BACKBONE_IDENTITY)["parameter_order_sha256"],
            mod.state_hashes(second, BACKBONE_IDENTITY)["parameter_order_sha256"],
        )

    def test_backbone_identity_and_runtime_state_are_separately_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "paired.pt"
            mod.seed_everything(43)
            source = SyntheticLaneE()
            saved = mod.save_paired_initial_state(
                path,
                source,
                0,
                43,
                backbone_identity_sha256=BACKBONE_IDENTITY,
            )
            receipt_path = Path(f"{path}.receipt.json")
            receipt_sha256 = mod.file_sha256(receipt_path)

            mod.seed_everything(43)
            wrong_identity = SyntheticLaneE()
            with self.assertRaisesRegex(
                mod.PairedInitialStateError, "backbone binding mismatch"
            ):
                mod.load_and_verify_initial_state(
                    path,
                    wrong_identity,
                    backbone_identity_sha256=hashlib.sha256(b"other").hexdigest(),
                    receipt_path=receipt_path,
                    expected_checkpoint_sha256=saved[
                        "serialized_checkpoint_sha256"
                    ],
                    expected_receipt_sha256=receipt_sha256,
                )

            mod.seed_everything(43)
            changed_backbone = SyntheticLaneE()
            with torch.no_grad():
                changed_backbone.backbone.embedding.weight.add_(1.0)
            with self.assertRaisesRegex(
                mod.PairedInitialStateError, "backbone binding mismatch"
            ):
                mod.load_and_verify_initial_state(
                    path,
                    changed_backbone,
                    backbone_identity_sha256=BACKBONE_IDENTITY,
                    receipt_path=receipt_path,
                    expected_checkpoint_sha256=saved[
                        "serialized_checkpoint_sha256"
                    ],
                    expected_receipt_sha256=receipt_sha256,
                )

    def test_external_checkpoint_and_receipt_hashes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "paired.pt"
            model = SyntheticLaneE()
            saved = mod.save_paired_initial_state(
                path,
                model,
                0,
                43,
                backbone_identity_sha256=BACKBONE_IDENTITY,
            )
            receipt_path = Path(f"{path}.receipt.json")
            receipt_sha256 = mod.file_sha256(receipt_path)
            wrong = hashlib.sha256(b"not-the-frozen-artifact").hexdigest()
            with self.assertRaisesRegex(
                mod.PairedInitialStateError,
                "externally frozen checkpoint SHA256 mismatch",
            ):
                mod.load_and_verify_initial_state(
                    path,
                    model,
                    backbone_identity_sha256=BACKBONE_IDENTITY,
                    receipt_path=receipt_path,
                    expected_checkpoint_sha256=wrong,
                    expected_receipt_sha256=receipt_sha256,
                )
            with self.assertRaisesRegex(
                mod.PairedInitialStateError,
                "externally frozen receipt SHA256 mismatch",
            ):
                mod.load_and_verify_initial_state(
                    path,
                    model,
                    backbone_identity_sha256=BACKBONE_IDENTITY,
                    receipt_path=receipt_path,
                    expected_checkpoint_sha256=saved[
                        "serialized_checkpoint_sha256"
                    ],
                    expected_receipt_sha256=wrong,
                )

    def test_unfrozen_backbone_and_invalid_identity_fail_closed(self) -> None:
        model = SyntheticLaneE()
        model.backbone.embedding.weight.requires_grad_(True)
        with self.assertRaisesRegex(
            mod.PairedInitialStateError, "backbone must be fully frozen"
        ):
            mod.state_hashes(model, BACKBONE_IDENTITY)
        with self.assertRaisesRegex(
            mod.PairedInitialStateError, "must be a lowercase-compatible SHA256"
        ):
            mod.state_hashes(SyntheticLaneE(), "tiny_synthetic")

    def test_fail_closed_for_wrong_lane_or_detached_contact(self) -> None:
        model = SyntheticLaneE()
        with self.assertRaises(mod.PairedInitialStateError):
            mod.validate_lane_e_shared(model, lane="B_SCALAR_ONLY")
        model.head.config.contact_encoder_gradient = "detached"
        with self.assertRaises(mod.PairedInitialStateError):
            mod.validate_lane_e_shared(model)

    def test_role_overlap_and_unclassified_parameter_fail(self) -> None:
        model = SyntheticLaneE()
        mapping = roles(model)
        mapping["contact"].append(mapping["shared_encoder"][0])
        with self.assertRaises(mod.PairedInitialStateError):
            mod.validate_parameter_roles(model, mapping)

        model.extra = nn.Linear(2, 1)
        with self.assertRaises(mod.PairedInitialStateError):
            mod.infer_parameter_roles(model)

    def test_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "paired"
            mod.materialize_paired_initial_states(
                model_factory=factory(),
                role_resolver=roles,
                output_dir=output,
                backbone_identity_sha256=BACKBONE_IDENTITY,
            )
            with self.assertRaises(mod.PairedInitialStateError):
                mod.materialize_paired_initial_states(
                    model_factory=factory(),
                    role_resolver=roles,
                    output_dir=output,
                    backbone_identity_sha256=BACKBONE_IDENTITY,
                )


if __name__ == "__main__":
    unittest.main()
