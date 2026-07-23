# V2.20 Phase-1 V1.3 shared-calibration technical recovery

## Status

Design and unit-test package only. It is not approved for deployment or
training. V1.2 remains immutable and is not a source of reusable fold outputs.

## Observed V1.2 technical failure

V1.2 independently recomputes the same eight-batch contact-gradient
calibration in C0 and C1. The selected semantic result is stable, but BF16/GPU
floating reductions produce slightly different gradient norms and cosines.
Consequently the two JSON receipts have different SHA256 values. The frozen
pair launcher requires exact receipt-hash equality, so a fold cannot publish a
pair terminal even when both arms select the same lambda and pass the conflict
gate.

This is a lifecycle/causal-pair closure failure. It is not evidence about model
quality and must not be repaired by weakening the exact-hash gate.

## The only V1.3 method change

For each fold, before either arm creates an optimizer:

1. Construct the frozen seed-43 model and frozen outer-fit batch stream.
2. Invoke the unchanged `calibrate_v220_contact_weight_v1.py` exactly once.
3. Validate the unchanged semantic contract.
4. Materialize one content-addressed shared calibration artifact.
5. Pass the same artifact path and expected SHA256 to C0 and C1.
6. Each arm validates the artifact against its reconstructed initial model and
   copies the exact bytes into its own output directory.
7. Neither arm independently recalibrates.

The shared artifact is a causal input to both arms, not an observed-result
selection. C0 still applies contact weights as zero. C1 still applies the
artifact's selected marginal lambda and `0.5 * lambda` pair coefficient.

## Unchanged frozen method

- 9,849 scalar rows, 54 whole-parent clusters and the same five splits.
- 738 train-only contact candidates and the same contact payloads.
- Seed 43 and the same head-only initial state.
- Frozen ESM2-650M, model architecture, graph inputs and target graphs.
- Eight epochs, batch order, optimizer, learning rate, weight decay, BF16,
  gradient accumulation, clipping and all scalar/contact losses.
- Lambda grid, selection rule and pre-optimizer conflict gate.
- B0 byte-exact replay, all evaluation metrics, bootstrap and core gates.
- No open-development, frozen-test, sealed, quarantine, test32 or prospective
  data access.

## No V1.2 reuse

All ten V1.3 arms must start from the original frozen seed-43 initial-state
artifact and run all eight epochs. V1.2 checkpoints, histories, predictions,
calibration receipts and partial fold outputs are prohibited as V1.3 inputs.

## Fail-closed conditions

Before either optimizer is created, fail if:

- the shared artifact is missing, empty, a symlink, changed during read or has
  the wrong expected SHA256;
- fold, seed or any frozen input binding differs;
- calibration status is not `PASS_CONTACT_WEIGHT_CALIBRATED_NO_OPTIMIZER`;
- batch count is not 8, the lambda grid differs, selected lambda is outside the
  grid, or the conflict count exceeds 2;
- model-state before/after hashes differ or do not match the reconstructed
  initial model; shared-parameter order differs;
- any optimizer step, backward call or training-start flag is present;
- the materializer is called more than once for a fold;
- either arm attempts to invoke the calibrator;
- either arm output exists, the two arm copies differ, or any V1.2 training
  artifact is supplied as an input.

After training, the existing exact pair-hash equality remains mandatory.

## Required verification before any launch

1. Unit tests for one-call materialization and two-arm exact replay.
2. Negative tests for hash, symlink, fold, seed, binding, model-state,
   parameter-order, lambda-grid and conflict failures.
3. Instrumented test proving both arms make zero calibrator calls and create no
   optimizer before shared-artifact validation.
4. Full prior 102-test suite plus new V1.3 tests in one immutable log.
5. Separate-process load-only validation for every fold contract.
6. Independent review and an implementation freeze binding exact bytes.

No V1.3 training may start from this design package alone.
