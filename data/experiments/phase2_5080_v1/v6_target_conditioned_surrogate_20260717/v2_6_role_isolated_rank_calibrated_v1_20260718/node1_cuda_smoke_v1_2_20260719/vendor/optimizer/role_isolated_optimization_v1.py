#!/usr/bin/env python3
"""V2.6 role-isolated optimizer and RNG primitives.

This module is deliberately independent from data loading, whole-parent split
selection, outer metrics, and deployment.  A model adapter supplies three
exhaustive trainable parameter roles plus scalar/contact closures.  The core
then enforces:

* exactly-one optimizer ownership for every trainable parameter;
* per-role clipping (never one global all-parameter clip);
* strict-detached scalar/contact steps with an isolated contact RNG stream;
* shared-gated contact transfer with a fixed ``kappa`` gradient budget.

The module never reads candidate IDs, parent IDs, M2/126D features, Docking
poses, outer truth, or V4-F/test32 evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterator, Mapping, Sequence

import torch
from torch import Tensor, nn
from torch.optim import AdamW, Optimizer


SCHEMA_VERSION = "pvrig_v2_6_role_isolated_optimizer_v1"
ROLE_SHARED = "shared_encoder"
ROLE_SCALAR = "attention_scalar"
ROLE_CONTACT = "contact_only"
ROLES = (ROLE_SHARED, ROLE_SCALAR, ROLE_CONTACT)
OWNER_SCALAR = "scalar_optimizer"
OWNER_CONTACT = "contact_optimizer"
OWNERS = (OWNER_SCALAR, OWNER_CONTACT)
CLAIM_BOUNDARY = (
    "Training-dynamics primitive for an open-development computational "
    "8X6B/9E6Y Docking-geometry surrogate only; not binding, affinity, "
    "experimental blocking, Docking Gold, or submission evidence."
)


class RoleIsolationError(RuntimeError):
    """Fail-closed V2.6 optimizer/RNG contract error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RoleIsolationError(message)


def require_finite_tensor(value: Tensor, message: str) -> None:
    require(bool(torch.all(torch.isfinite(value))), message)


NamedParameter = tuple[str, nn.Parameter]
RoleMapping = Mapping[str, Sequence[NamedParameter]]


@dataclass(frozen=True)
class RoleOptimizerConfig:
    learning_rate: float = 1e-4
    contact_learning_rate: float = 1e-4
    weight_decay: float = 0.02
    clip_shared: float = 1.0
    clip_scalar: float = 1.0
    clip_contact: float = 1.0
    kappa: float = 0.25
    lambda_contact_shared: float = 1.0
    epsilon: float = 1e-12

    def validate(self) -> None:
        for name, value in asdict(self).items():
            require(math.isfinite(float(value)), f"optimizer_config_nonfinite:{name}")
        require(self.learning_rate > 0.0, "learning_rate_nonpositive")
        require(self.contact_learning_rate > 0.0, "contact_learning_rate_nonpositive")
        require(self.weight_decay >= 0.0, "weight_decay_negative")
        require(self.clip_shared > 0.0, "clip_shared_nonpositive")
        require(self.clip_scalar > 0.0, "clip_scalar_nonpositive")
        require(self.clip_contact > 0.0, "clip_contact_nonpositive")
        require(0.0 <= self.kappa <= 1.0, "kappa_out_of_range")
        require(self.lambda_contact_shared >= 0.0, "lambda_contact_shared_negative")
        require(self.epsilon > 0.0, "epsilon_nonpositive")


@dataclass(frozen=True)
class ContactRngKey:
    base_seed: int
    outer_fold: int
    inner_fold: int
    epoch: int
    optimizer_step: int
    accumulation_microstep: int = 0

    def values(self) -> tuple[Any, ...]:
        return (
            self.base_seed,
            self.outer_fold,
            self.inner_fold,
            self.epoch,
            self.optimizer_step,
            self.accumulation_microstep,
            "contact_rng",
        )


@dataclass(frozen=True)
class ScalarStepOutput:
    loss: Tensor
    contact_payload: Any


def _parameter_list(role_mapping: RoleMapping, role: str) -> list[nn.Parameter]:
    require(role in ROLES, f"role_invalid:{role}")
    return [parameter for _name, parameter in role_mapping[role]]


def _canonical_ownership_payload(role_mapping: RoleMapping) -> dict[str, list[dict[str, Any]]]:
    return {
        role: [
            {
                "name": name,
                "shape": list(parameter.shape),
                "numel": parameter.numel(),
                "dtype": str(parameter.dtype),
            }
            for name, parameter in role_mapping[role]
        ]
        for role in ROLES
    }


def role_mapping_from_v25_orthogonal_model(model: nn.Module) -> dict[str, list[NamedParameter]]:
    """Map the frozen V2.5 orthogonal head names into V2.6 roles.

    This is a structural adapter only.  It deliberately imports no V2.5
    trainer and reads no data or metrics.  Unknown trainable prefixes fail
    closed so a future architecture change cannot silently evade ownership.
    """
    require(hasattr(model, "head"), "orthogonal_model_head_missing")
    config = getattr(model.head, "config", None)
    require(config is not None, "orthogonal_model_config_missing")
    contact_enabled = bool(getattr(config, "enable_contact_evidence", False))
    require(
        getattr(config, "contact_encoder_gradient", None) in {"shared", "detached"},
        "contact_encoder_gradient_mode_invalid",
    )
    roles: dict[str, list[NamedParameter]] = {role: [] for role in ROLES}
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        require(name.startswith("head."), f"trainable_parameter_outside_orthogonal_head:{name}")
        local = name[len("head."):]
        if local.startswith(
            (
                "aa_embedding",
                "region_embedding",
                "vhh_graph_encoder",
                "target_graph_encoder",
                "conformer_embedding",
            )
        ):
            roles[ROLE_SHARED].append((name, parameter))
        elif local.startswith(("attention_interaction", "condition_fusion", "scalar_head")):
            roles[ROLE_SCALAR].append((name, parameter))
        elif local.startswith(("contact_interaction", "contact_calibration")):
            roles[ROLE_CONTACT].append((name, parameter))
        else:
            raise RoleIsolationError(f"unclassified_orthogonal_parameter:{name}")
    validate_parameter_roles(model, roles, require_contact=contact_enabled)
    require(bool(roles[ROLE_CONTACT]) == contact_enabled, "contact_role_configuration_mismatch")
    return roles


def validate_parameter_roles(
    model: nn.Module,
    role_mapping: RoleMapping,
    *,
    require_contact: bool = True,
) -> dict[str, Any]:
    """Require exhaustive, unique trainable parameter-role ownership."""
    require(set(role_mapping) == set(ROLES), "parameter_role_set_mismatch")
    trainable = [(name, parameter) for name, parameter in model.named_parameters() if parameter.requires_grad]
    require(bool(trainable), "model_has_no_trainable_parameters")
    expected_by_id = {id(parameter): name for name, parameter in trainable}
    require(len(expected_by_id) == len(trainable), "model_trainable_parameter_alias")

    seen_ids: dict[int, tuple[str, str]] = {}
    seen_names: set[str] = set()
    for role in ROLES:
        values = role_mapping[role]
        if role in (ROLE_SHARED, ROLE_SCALAR) or require_contact:
            require(bool(values), f"required_parameter_role_empty:{role}")
        for name, parameter in values:
            require(isinstance(parameter, nn.Parameter), f"role_value_not_parameter:{role}:{name}")
            require(parameter.requires_grad, f"role_parameter_not_trainable:{role}:{name}")
            require(id(parameter) in expected_by_id, f"role_parameter_not_in_model:{role}:{name}")
            require(expected_by_id[id(parameter)] == name, f"role_parameter_name_mismatch:{role}:{name}")
            require(name not in seen_names, f"parameter_name_duplicate:{name}")
            if id(parameter) in seen_ids:
                previous_role, previous_name = seen_ids[id(parameter)]
                raise RoleIsolationError(
                    f"parameter_role_overlap:{previous_role}:{previous_name}:{role}:{name}"
                )
            seen_ids[id(parameter)] = (role, name)
            seen_names.add(name)

    missing = sorted(set(expected_by_id) - set(seen_ids))
    require(not missing, "trainable_parameter_unowned:" + ",".join(expected_by_id[item] for item in missing))
    extra = sorted(set(seen_ids) - set(expected_by_id))
    require(not extra, "unknown_role_parameter_present")

    payload = _canonical_ownership_payload(role_mapping)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": f"{SCHEMA_VERSION}_parameter_ownership_v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "roles": payload,
        "role_tensor_counts": {role: len(role_mapping[role]) for role in ROLES},
        "role_value_counts": {
            role: sum(parameter.numel() for _name, parameter in role_mapping[role]) for role in ROLES
        },
        "all_trainable_parameters_owned_exactly_once": True,
        "ownership_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def optimizer_parameter_ids(optimizer: Optimizer) -> list[int]:
    return [id(parameter) for group in optimizer.param_groups for parameter in group["params"]]


def validate_optimizer_ownership(
    role_mapping: RoleMapping,
    scalar_optimizer: Optimizer,
    contact_optimizer: Optimizer,
) -> dict[str, Any]:
    """Bind the two optimizers to their frozen disjoint roles."""
    expected_scalar = {
        id(parameter)
        for role in (ROLE_SHARED, ROLE_SCALAR)
        for parameter in _parameter_list(role_mapping, role)
    }
    expected_contact = {id(parameter) for parameter in _parameter_list(role_mapping, ROLE_CONTACT)}
    actual_scalar_list = optimizer_parameter_ids(scalar_optimizer)
    actual_contact_list = optimizer_parameter_ids(contact_optimizer)
    require(len(actual_scalar_list) == len(set(actual_scalar_list)), "scalar_optimizer_internal_overlap")
    require(len(actual_contact_list) == len(set(actual_contact_list)), "contact_optimizer_internal_overlap")
    actual_scalar = set(actual_scalar_list)
    actual_contact = set(actual_contact_list)
    require(not (actual_scalar & actual_contact), "optimizer_parameter_overlap")
    require(actual_scalar == expected_scalar, "scalar_optimizer_role_ownership_mismatch")
    require(actual_contact == expected_contact, "contact_optimizer_role_ownership_mismatch")
    return {
        "schema_version": f"{SCHEMA_VERSION}_optimizer_ownership_v1",
        "scalar_optimizer_roles": [ROLE_SHARED, ROLE_SCALAR],
        "contact_optimizer_roles": [ROLE_CONTACT],
        "overlap_count": 0,
        "all_parameters_owned_by_expected_optimizer": True,
    }


def validate_scalar_optimizer_ownership(
    role_mapping: RoleMapping,
    scalar_optimizer: Optimizer,
) -> dict[str, Any]:
    expected = {
        id(parameter)
        for role in (ROLE_SHARED, ROLE_SCALAR)
        for parameter in _parameter_list(role_mapping, role)
    }
    actual_list = optimizer_parameter_ids(scalar_optimizer)
    require(len(actual_list) == len(set(actual_list)), "scalar_optimizer_internal_overlap")
    require(set(actual_list) == expected, "scalar_optimizer_role_ownership_mismatch")
    contact_ids = {id(parameter) for parameter in _parameter_list(role_mapping, ROLE_CONTACT)}
    require(not (set(actual_list) & contact_ids), "scalar_optimizer_owns_contact_parameter")
    return {
        "schema_version": f"{SCHEMA_VERSION}_scalar_optimizer_ownership_v1",
        "scalar_optimizer_roles": [ROLE_SHARED, ROLE_SCALAR],
        "contact_parameter_owned_by_scalar_optimizer": False,
        "all_scalar_parameters_owned": True,
    }


def build_scalar_reference_optimizer(
    model: nn.Module,
    role_mapping: RoleMapping,
    config: RoleOptimizerConfig,
) -> tuple[AdamW, dict[str, Any]]:
    """Build the B-lane reference optimizer when no contact module exists."""
    config.validate()
    role_audit = validate_parameter_roles(model, role_mapping, require_contact=False)
    optimizer = AdamW(
        [
            {
                "params": _parameter_list(role_mapping, ROLE_SHARED),
                "role": ROLE_SHARED,
                "lr": config.learning_rate,
                "weight_decay": config.weight_decay,
            },
            {
                "params": _parameter_list(role_mapping, ROLE_SCALAR),
                "role": ROLE_SCALAR,
                "lr": config.learning_rate,
                "weight_decay": config.weight_decay,
            },
        ]
    )
    return optimizer, {
        "parameter_roles": role_audit,
        "optimizer_ownership": validate_scalar_optimizer_ownership(role_mapping, optimizer),
        "config": asdict(config),
    }


def build_role_optimizers(
    model: nn.Module,
    role_mapping: RoleMapping,
    config: RoleOptimizerConfig,
) -> tuple[AdamW, AdamW, dict[str, Any]]:
    config.validate()
    role_audit = validate_parameter_roles(model, role_mapping, require_contact=True)
    scalar_optimizer = AdamW(
        [
            {
                "params": _parameter_list(role_mapping, ROLE_SHARED),
                "role": ROLE_SHARED,
                "lr": config.learning_rate,
                "weight_decay": config.weight_decay,
            },
            {
                "params": _parameter_list(role_mapping, ROLE_SCALAR),
                "role": ROLE_SCALAR,
                "lr": config.learning_rate,
                "weight_decay": config.weight_decay,
            },
        ]
    )
    contact_optimizer = AdamW(
        [
            {
                "params": _parameter_list(role_mapping, ROLE_CONTACT),
                "role": ROLE_CONTACT,
                "lr": config.contact_learning_rate,
                "weight_decay": config.weight_decay,
            }
        ]
    )
    optimizer_audit = validate_optimizer_ownership(role_mapping, scalar_optimizer, contact_optimizer)
    return scalar_optimizer, contact_optimizer, {
        "parameter_roles": role_audit,
        "optimizer_ownership": optimizer_audit,
        "config": asdict(config),
    }


def _tensor_bytes(value: Tensor) -> bytes:
    # Viewing as raw bytes also supports BF16 tensors, which NumPy cannot
    # represent directly on every supported runtime.
    return value.detach().contiguous().cpu().view(torch.uint8).numpy().tobytes()


def rng_state_sha256(device: torch.device | str | None = None) -> str:
    """Hash the main CPU RNG and, when requested, one CUDA device RNG."""
    selected = torch.device("cpu" if device is None else device)
    digest = hashlib.sha256()
    digest.update(b"cpu\0")
    digest.update(_tensor_bytes(torch.random.get_rng_state()))
    if selected.type == "cuda":
        require(torch.cuda.is_available(), "cuda_rng_requested_but_unavailable")
        index = torch.cuda.current_device() if selected.index is None else selected.index
        digest.update(f"cuda:{index}\0".encode("ascii"))
        digest.update(_tensor_bytes(torch.cuda.get_rng_state(index)))
    return digest.hexdigest()


def derive_contact_seed(key: ContactRngKey) -> int:
    encoded = json.dumps(key.values(), separators=(",", ":"), ensure_ascii=True).encode("ascii")
    # torch.Generator accepts signed 64-bit seeds; keep the sign bit clear.
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") & ((1 << 63) - 1)


def _fork_devices(device: torch.device) -> list[int]:
    if device.type != "cuda":
        return []
    require(torch.cuda.is_available(), "cuda_contact_rng_requested_but_unavailable")
    return [torch.cuda.current_device() if device.index is None else device.index]


def _seed_only_forked_generators(seed: int, device: torch.device) -> None:
    cpu_generator = torch.Generator(device="cpu")
    cpu_generator.manual_seed(seed)
    torch.random.set_rng_state(cpu_generator.get_state())
    if device.type == "cuda":
        index = torch.cuda.current_device() if device.index is None else device.index
        cuda_generator = torch.Generator(device=f"cuda:{index}")
        cuda_generator.manual_seed(seed)
        torch.cuda.set_rng_state(cuda_generator.get_state(), device=index)


@contextmanager
def isolated_contact_rng(key: ContactRngKey, device: torch.device | str) -> Iterator[int]:
    """Run all contact-only randomness without advancing the main RNG stream."""
    selected = torch.device(device)
    seed = derive_contact_seed(key)
    before = rng_state_sha256(selected)
    with torch.random.fork_rng(devices=_fork_devices(selected), enabled=True):
        _seed_only_forked_generators(seed, selected)
        yield seed
    after = rng_state_sha256(selected)
    require(after == before, "contact_rng_state_leak")


def parameter_state_sha256(named_parameters: Sequence[NamedParameter]) -> str:
    digest = hashlib.sha256()
    for name, parameter in sorted(named_parameters, key=lambda item: item[0]):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(parameter.dtype).encode("ascii"))
        digest.update(b"\0")
        digest.update(json.dumps(list(parameter.shape), separators=(",", ":")).encode("ascii"))
        digest.update(b"\0")
        digest.update(_tensor_bytes(parameter))
    return digest.hexdigest()


def scalar_trajectory_sha256(role_mapping: RoleMapping) -> str:
    return parameter_state_sha256(list(role_mapping[ROLE_SHARED]) + list(role_mapping[ROLE_SCALAR]))


def maximum_parameter_delta(left: RoleMapping, right: RoleMapping, roles: Sequence[str]) -> float:
    maximum = 0.0
    for role in roles:
        left_values = {name: parameter for name, parameter in left[role]}
        right_values = {name: parameter for name, parameter in right[role]}
        require(set(left_values) == set(right_values), f"parameter_comparison_name_mismatch:{role}")
        for name in left_values:
            require(left_values[name].shape == right_values[name].shape, f"parameter_comparison_shape:{name}")
            delta = float((left_values[name].detach() - right_values[name].detach()).abs().max().cpu())
            maximum = max(maximum, delta)
    return maximum


def _grad_norm_from_values(gradients: Sequence[Tensor | None]) -> Tensor:
    values = [gradient.float().norm(2) for gradient in gradients if gradient is not None]
    if not values:
        return torch.tensor(0.0)
    return torch.stack(values).norm(2)


def _grad_dot(left: Sequence[Tensor | None], right: Sequence[Tensor | None]) -> Tensor:
    require(len(left) == len(right), "gradient_dot_length_mismatch")
    values = [
        (a.float().reshape(-1) * b.float().reshape(-1)).sum()
        for a, b in zip(left, right)
        if a is not None and b is not None
    ]
    if not values:
        return torch.tensor(0.0)
    return torch.stack(values).sum()


def _all_none_or_zero(gradients: Sequence[Tensor | None]) -> bool:
    return all(gradient is None or bool(torch.all(gradient == 0)) for gradient in gradients)


def _collect_parameter_grads(parameters: Sequence[nn.Parameter]) -> list[Tensor | None]:
    return [parameter.grad for parameter in parameters]


def _assign_gradients(parameters: Sequence[nn.Parameter], gradients: Sequence[Tensor | None]) -> None:
    require(len(parameters) == len(gradients), "gradient_assignment_length_mismatch")
    for parameter, gradient in zip(parameters, gradients):
        parameter.grad = None if gradient is None else gradient.detach().clone()


def _clip_one_role(
    role: str,
    parameters: Sequence[nn.Parameter],
    maximum_norm: float,
) -> dict[str, Any]:
    require(role in ROLES, f"clip_role_invalid:{role}")
    require(math.isfinite(maximum_norm) and maximum_norm > 0.0, f"clip_threshold_invalid:{role}")
    active = [parameter for parameter in parameters if parameter.grad is not None]
    require(bool(active), f"clip_role_has_no_gradients:{role}")
    before = float(_grad_norm_from_values([parameter.grad for parameter in active]).cpu())
    returned = nn.utils.clip_grad_norm_(active, maximum_norm, error_if_nonfinite=True)
    after = float(_grad_norm_from_values([parameter.grad for parameter in active]).cpu())
    return {
        "role": role,
        "max_norm": maximum_norm,
        "pre_clip_norm": before,
        "clip_grad_norm_return": float(returned.detach().cpu()),
        "post_clip_norm": after,
        "parameter_tensors": len(active),
    }


def validate_clip_events(events: Sequence[Mapping[str, Any]], expected_roles: Sequence[str]) -> None:
    observed = [str(event.get("role")) for event in events]
    require("GLOBAL_ALL" not in observed, "global_all_parameter_clip_forbidden")
    require(observed == list(expected_roles), "per_role_clip_sequence_mismatch")


def _require_loss(loss: Tensor, name: str) -> None:
    require(isinstance(loss, Tensor) and loss.ndim == 0, f"{name}_must_be_scalar_tensor")
    require(loss.requires_grad, f"{name}_must_require_grad")
    require_finite_tensor(loss, f"{name}_nonfinite")


def _require_detached_payload(value: Any, path: str = "contact_payload") -> None:
    if isinstance(value, Tensor):
        require(
            not value.requires_grad and value.grad_fn is None,
            f"strict_detached_contact_payload_requires_grad:{path}",
        )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _require_detached_payload(item, f"{path}.{key}")
        return
    if isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _require_detached_payload(item, f"{path}[{index}]")


def scalar_only_step(
    *,
    role_mapping: RoleMapping,
    scalar_optimizer: Optimizer,
    contact_optimizer: Optimizer | None,
    scalar_closure: Callable[[], ScalarStepOutput],
    config: RoleOptimizerConfig,
) -> dict[str, Any]:
    """One B-lane scalar-only step used as the strict dynamics reference."""
    config.validate()
    if contact_optimizer is None:
        validate_scalar_optimizer_ownership(role_mapping, scalar_optimizer)
    else:
        validate_optimizer_ownership(role_mapping, scalar_optimizer, contact_optimizer)
    shared = _parameter_list(role_mapping, ROLE_SHARED)
    scalar = _parameter_list(role_mapping, ROLE_SCALAR)
    contact = _parameter_list(role_mapping, ROLE_CONTACT)
    scalar_optimizer.zero_grad(set_to_none=True)
    if contact_optimizer is not None:
        contact_optimizer.zero_grad(set_to_none=True)
    scalar_result = scalar_closure()
    require(isinstance(scalar_result, ScalarStepOutput), "scalar_closure_output_invalid")
    _require_loss(scalar_result.loss, "scalar_loss")
    scalar_result.loss.backward()
    require(_all_none_or_zero(_collect_parameter_grads(contact)), "scalar_loss_reaches_contact_parameters")
    clip_events = [
        _clip_one_role(ROLE_SHARED, shared, config.clip_shared),
        _clip_one_role(ROLE_SCALAR, scalar, config.clip_scalar),
    ]
    validate_clip_events(clip_events, (ROLE_SHARED, ROLE_SCALAR))
    scalar_optimizer.step()
    scalar_optimizer.zero_grad(set_to_none=True)
    if contact_optimizer is not None:
        contact_optimizer.zero_grad(set_to_none=True)
    return {
        "schema_version": f"{SCHEMA_VERSION}_scalar_only_step_v1",
        "mode": "B_SCALAR_ATTENTION_ONLY",
        "scalar_loss": float(scalar_result.loss.detach().cpu()),
        "clip_events": clip_events,
        "global_all_parameter_clip_used": False,
        "scalar_contact_optimizer_overlap": False,
    }


def strict_detached_step(
    *,
    role_mapping: RoleMapping,
    scalar_optimizer: Optimizer,
    contact_optimizer: Optimizer,
    scalar_closure: Callable[[], ScalarStepOutput],
    contact_closure: Callable[[Any], Tensor],
    rng_key: ContactRngKey,
    device: torch.device | str,
    config: RoleOptimizerConfig,
) -> dict[str, Any]:
    """One dynamics-independent scalar step followed by a contact-only step."""
    config.validate()
    validate_optimizer_ownership(role_mapping, scalar_optimizer, contact_optimizer)
    shared = _parameter_list(role_mapping, ROLE_SHARED)
    scalar = _parameter_list(role_mapping, ROLE_SCALAR)
    contact = _parameter_list(role_mapping, ROLE_CONTACT)
    scalar_optimizer.zero_grad(set_to_none=True)
    contact_optimizer.zero_grad(set_to_none=True)

    scalar_result = scalar_closure()
    require(isinstance(scalar_result, ScalarStepOutput), "scalar_closure_output_invalid")
    _require_loss(scalar_result.loss, "scalar_loss")
    _require_detached_payload(scalar_result.contact_payload)
    scalar_result.loss.backward()
    require(_all_none_or_zero(_collect_parameter_grads(contact)), "scalar_loss_reaches_contact_parameters")
    scalar_clips = [
        _clip_one_role(ROLE_SHARED, shared, config.clip_shared),
        _clip_one_role(ROLE_SCALAR, scalar, config.clip_scalar),
    ]
    validate_clip_events(scalar_clips, (ROLE_SHARED, ROLE_SCALAR))
    scalar_optimizer.step()
    scalar_optimizer.zero_grad(set_to_none=True)
    contact_optimizer.zero_grad(set_to_none=True)

    rng_before = rng_state_sha256(device)
    with isolated_contact_rng(rng_key, device) as contact_seed:
        contact_loss = contact_closure(scalar_result.contact_payload)
        _require_loss(contact_loss, "contact_loss")
        contact_loss.backward()
    rng_after = rng_state_sha256(device)
    require(rng_after == rng_before, "contact_rng_state_leak_after_closure")
    require(
        _all_none_or_zero(_collect_parameter_grads(shared + scalar)),
        "strict_detached_contact_gradient_reaches_scalar_path",
    )
    contact_grad_norm = float(_grad_norm_from_values(_collect_parameter_grads(contact)).cpu())
    require(contact_grad_norm > 0.0, "contact_loss_has_zero_contact_gradient")
    contact_clips = [_clip_one_role(ROLE_CONTACT, contact, config.clip_contact)]
    validate_clip_events(contact_clips, (ROLE_CONTACT,))
    contact_optimizer.step()
    scalar_optimizer.zero_grad(set_to_none=True)
    contact_optimizer.zero_grad(set_to_none=True)
    return {
        "schema_version": f"{SCHEMA_VERSION}_strict_detached_step_v1",
        "mode": "E_STRICT_DETACHED_DYNAMICS_CONTROL",
        "scalar_loss": float(scalar_result.loss.detach().cpu()),
        "contact_loss": float(contact_loss.detach().cpu()),
        "contact_seed": contact_seed,
        "main_rng_sha256_before_contact": rng_before,
        "main_rng_sha256_after_contact": rng_after,
        "main_rng_restored": True,
        "scalar_clip_events": scalar_clips,
        "contact_clip_events": contact_clips,
        "contact_pre_clip_gradient_norm": contact_grad_norm,
        "global_all_parameter_clip_used": False,
        "scalar_contact_optimizer_overlap": False,
    }


def _autograd_all(
    loss: Tensor,
    parameters: Sequence[nn.Parameter],
    *,
    retain_graph: bool,
) -> list[Tensor | None]:
    return list(
        torch.autograd.grad(
            loss,
            parameters,
            retain_graph=retain_graph,
            allow_unused=True,
            create_graph=False,
        )
    )


def shared_gated_contact_step(
    *,
    role_mapping: RoleMapping,
    scalar_optimizer: Optimizer,
    contact_optimizer: Optimizer,
    scalar_closure: Callable[[], ScalarStepOutput],
    contact_closure: Callable[[Any], Tensor],
    rng_key: ContactRngKey,
    device: torch.device | str,
    config: RoleOptimizerConfig,
) -> dict[str, Any]:
    """One F-lane step with a fixed contact-to-shared gradient budget."""
    config.validate()
    validate_optimizer_ownership(role_mapping, scalar_optimizer, contact_optimizer)
    shared = _parameter_list(role_mapping, ROLE_SHARED)
    scalar = _parameter_list(role_mapping, ROLE_SCALAR)
    contact = _parameter_list(role_mapping, ROLE_CONTACT)
    all_parameters = shared + scalar + contact
    scalar_optimizer.zero_grad(set_to_none=True)
    contact_optimizer.zero_grad(set_to_none=True)

    scalar_result = scalar_closure()
    require(isinstance(scalar_result, ScalarStepOutput), "scalar_closure_output_invalid")
    _require_loss(scalar_result.loss, "scalar_loss")
    rng_before = rng_state_sha256(device)
    with isolated_contact_rng(rng_key, device) as contact_seed:
        contact_loss = contact_closure(scalar_result.contact_payload)
        _require_loss(contact_loss, "contact_loss")
    rng_after = rng_state_sha256(device)
    require(rng_after == rng_before, "contact_rng_state_leak_after_closure")

    scalar_gradients = _autograd_all(scalar_result.loss, all_parameters, retain_graph=True)
    contact_gradients = _autograd_all(contact_loss, all_parameters, retain_graph=False)
    n_shared = len(shared)
    n_scalar = len(scalar)
    scalar_shared = scalar_gradients[:n_shared]
    scalar_scalar = scalar_gradients[n_shared:n_shared + n_scalar]
    scalar_contact = scalar_gradients[n_shared + n_scalar:]
    contact_shared = contact_gradients[:n_shared]
    contact_scalar = contact_gradients[n_shared:n_shared + n_scalar]
    contact_contact = contact_gradients[n_shared + n_scalar:]
    require(_all_none_or_zero(scalar_contact), "scalar_loss_reaches_contact_parameters")
    require(_all_none_or_zero(contact_scalar), "contact_loss_reaches_attention_scalar_parameters")

    scalar_shared_norm_tensor = _grad_norm_from_values(scalar_shared)
    contact_shared_norm_tensor = _grad_norm_from_values(contact_shared)
    scalar_shared_norm = float(scalar_shared_norm_tensor.cpu())
    contact_shared_norm = float(contact_shared_norm_tensor.cpu())
    require(scalar_shared_norm > 0.0, "scalar_shared_gradient_zero")
    require(contact_shared_norm > 0.0, "contact_shared_gradient_zero")
    contact_contact_norm = float(_grad_norm_from_values(contact_contact).cpu())
    require(contact_contact_norm > 0.0, "contact_terminal_gradient_zero")

    cap = min(
        1.0,
        config.kappa * (scalar_shared_norm + config.epsilon)
        / (contact_shared_norm + config.epsilon),
    )
    combined_shared: list[Tensor | None] = []
    for scalar_gradient, contact_gradient in zip(scalar_shared, contact_shared):
        if scalar_gradient is None and contact_gradient is None:
            combined_shared.append(None)
        elif scalar_gradient is None:
            combined_shared.append(config.lambda_contact_shared * cap * contact_gradient)
        elif contact_gradient is None:
            combined_shared.append(scalar_gradient)
        else:
            combined_shared.append(
                scalar_gradient + config.lambda_contact_shared * cap * contact_gradient
            )
    dot = _grad_dot(scalar_shared, contact_shared)
    cosine = float(
        (dot / (scalar_shared_norm_tensor * contact_shared_norm_tensor).clamp_min(config.epsilon)).cpu()
    )
    preclip_final_shared_norm = float(_grad_norm_from_values(combined_shared).cpu())
    _assign_gradients(shared, combined_shared)
    _assign_gradients(scalar, scalar_scalar)
    _assign_gradients(contact, contact_contact)
    clip_events = [
        _clip_one_role(ROLE_SHARED, shared, config.clip_shared),
        _clip_one_role(ROLE_SCALAR, scalar, config.clip_scalar),
        _clip_one_role(ROLE_CONTACT, contact, config.clip_contact),
    ]
    validate_clip_events(clip_events, ROLES)
    scalar_optimizer.step()
    contact_optimizer.step()
    scalar_optimizer.zero_grad(set_to_none=True)
    contact_optimizer.zero_grad(set_to_none=True)

    return {
        "schema_version": f"{SCHEMA_VERSION}_shared_gated_step_v1",
        "mode": "F_SHARED_GATED_CONTACT_TRANSFER",
        "scalar_loss": float(scalar_result.loss.detach().cpu()),
        "contact_loss": float(contact_loss.detach().cpu()),
        "contact_seed": contact_seed,
        "main_rng_sha256_before_contact": rng_before,
        "main_rng_sha256_after_contact": rng_after,
        "main_rng_restored": True,
        "scalar_shared_gradient_norm": scalar_shared_norm,
        "contact_shared_gradient_norm": contact_shared_norm,
        "scalar_contact_gradient_cosine": cosine,
        "contact_cap_multiplier": cap,
        "contact_capped_gradient_norm": cap * contact_shared_norm,
        "contact_budget_norm_limit": config.kappa * (scalar_shared_norm + config.epsilon),
        "preclip_final_shared_gradient_norm": preclip_final_shared_norm,
        "clip_events": clip_events,
        "global_all_parameter_clip_used": False,
        "scalar_contact_optimizer_overlap": False,
        "kappa": config.kappa,
        "lambda_contact_shared": config.lambda_contact_shared,
    }


def implementation_contract() -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}_contract_v1",
        "claim_boundary": CLAIM_BOUNDARY,
        "parameter_roles": list(ROLES),
        "optimizer_owners": {
            OWNER_SCALAR: [ROLE_SHARED, ROLE_SCALAR],
            OWNER_CONTACT: [ROLE_CONTACT],
        },
        "each_trainable_parameter_has_exactly_one_owner": True,
        "global_all_parameter_clip_allowed": False,
        "per_role_clip_defaults": {
            ROLE_SHARED: 1.0,
            ROLE_SCALAR: 1.0,
            ROLE_CONTACT: 1.0,
        },
        "contact_rng": {
            "mechanism": "torch.random.fork_rng",
            "seed": "SHA256(base_seed,outer_fold,inner_fold,epoch,optimizer_step,accumulation_microstep,contact_rng)",
            "main_cpu_and_current_cuda_state_restored": True,
        },
        "strict_detached": {
            "contact_gradient_to_shared_or_scalar_allowed": False,
            "contact_optimizer_owns_shared_parameter": False,
        },
        "shared_gated": {
            "kappa": 0.25,
            "lambda_contact_shared": 1.0,
            "formula": "gC_capped=gC*min(1,kappa*(norm(gS)+eps)/(norm(gC)+eps));gShared=gS+lambda*gC_capped",
        },
        "outer_metrics_accessed": False,
        "v4_f_test32_accessed": False,
    }
