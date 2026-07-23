# V2.20 V1.3.1 shared-calibration recovery lifecycle

## Scope

V1.3.1 supersedes the rejected, never-deployed V1.3 launcher. The scientific
method remains the frozen V1.2 method. The only recovery is the lifecycle of
the per-fold contact-gradient calibration artifact.

## Atomic exact-once materialization

For each fold, the launcher executes an atomic:

```bash
mkdir "$SHARED_DIR"
```

The directory itself is the fold lock. The command must fail when another
process already owns or previously owned the fold. A failed or interrupted
materialization deliberately leaves the directory in place; there is no retry
inside the same version. This guarantees that the true calibrator is invoked
at most once per fold.

Only after the lock exists may the shell open:

```text
$SHARED_DIR/MATERIALIZATION_TERMINAL.json
$SHARED_DIR/MATERIALIZATION_STDERR.log
```

The artifact path must not exist before the materializer starts. C0 and C1
then read and hash-validate the same artifact and invoke no true calibrator.

## Two-stage authorization

### Stage A: preflight only

The preflight launcher may be independently approved before training. It:

1. runs the frozen legacy 102-test suite;
2. runs all V1.3.1 tests;
3. for each of five folds, in a separate process, materializes one shared
   calibration artifact;
4. in another separate process, reconstructs the fold model and loads the
   artifact for both arm labels without optimizer creation, backward or
   training;
5. publishes a content-addressed preflight receipt with all such flags false.

The preflight launcher has no code path to `run_fold_core` and cannot train.

### Stage B: training only after final authorization

The training launcher is not finalized during Stage A. A later finalization
step must bind by exact SHA256:

- the successful V1.3.1 preflight receipt;
- an independent approval receipt for those exact bytes and evidence;
- the final training launcher;
- preregistration, implementation freeze and all runtime dependencies.

The final authorization document must contain `training_authorized=true`.
Absent any one of those bound artifacts, training fails before shared-directory
creation and before an optimizer.

## Fresh execution

After authorization, all five folds and both arms run from the original seed43
head-only initial state for eight epochs. No V1.2 or rejected V1.3 checkpoint,
history, prediction, calibration or partial fold output is an input.

## Unchanged method

Data, split, initial state, ESM2, architecture, losses, optimizer, batch order,
hyperparameters, lambda grid/selection, conflict gate, evaluation, bootstrap,
core gates and claim boundary are unchanged.

## Required tests

- true temporary-directory runtime smoke proves lock creation occurs before
  stdout/stderr redirection;
- two concurrent same-fold launches yield exactly one materializer call;
- a sequential second launch also fails without a second call;
- materializer failure leaves the lock and cannot be retried;
- load-only validation produces optimizer/backward/training false;
- training template refuses placeholders, absent receipts, wrong hashes,
  false authorization or non-fresh outputs;
- all prior shared-artifact semantic/hash/symlink tests remain active.

## Exact runtime closure added in V1.3.1

The atomic helper writes `EXACT_ONCE_LOCK.json`, exports the lock directory,
nonce and its own SHA256, and only then opens materializer stdout/stderr.  The
materializer independently rejects a missing helper context, a helper hash
mismatch, an artifact outside the lock directory, a wrong fold-directory name,
or direct invocation that did not inherit the helper-created token.  Both the
preflight and future finalized training launcher bind the helper SHA and pass
the exact materializer argv.

The upstream V1.2 runner dynamically imports three sibling modules.  V1.3.1
therefore binds and validates their exact hashes before `prepare_production_inputs`:

```text
calibrate_v220_contact_weight_v1.py
  b0b5e6719324fa8376bc33512c9e76805ef768ae1917081f8d2f83a6c9f858e8
materialize_v220_paired_initial_state_v1.py
  9be8bd8572b297a2b075965775e04c2f066b2ca534738f6f3a8535fd97e988ec
v220_contact_teacher_store_v1.py
  cb6a20cfe752f237f6afb865bb1c2440b4f3b219634b7d8ca59800f2ec5f0953
```

Those hashes and the helper hash are also included in each shared artifact's
`frozen_bindings`, so materialization, load-only validation and future arm
replay use the same code identity.

Load-only receipts and the forbidden training output are path-disjoint in both
directions.  Absence of the training output is checked before model loading,
before receipt writing, and again after receipt writing.  Stable regular-file
reads compare device, inode, mode, size, mtime and ctime but intentionally do
not compare atime, because the first read of a cold file can legitimately
update atime without changing its bytes.

The frozen package contains only an unfinalized training template.  It exits 86
before parsing fold/output arguments.  A concrete launcher can only be rendered
by the finalizer after a five-fold no-training preflight receipt and an
independent approval bind the exact implementation freeze, preregistration and
template hashes.  Finalization creates only the concrete launcher and a
`training_started=false` authorization; it never imports or invokes training.
