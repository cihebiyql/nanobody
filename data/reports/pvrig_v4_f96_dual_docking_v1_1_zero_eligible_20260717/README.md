# V4-F96 dual-Docking V1.1 zero-eligible terminal evidence

## Result

The frozen V4-F96 panel produced **0 Full-QC hard-pass candidates** and **96 hard-fail candidates**. The independently versioned Node23 V1.1 waiter verified the exact canonical Node1 receipt and terminated as `NO_ELIGIBLE_DOCKING`.

- Docking jobs started: **0**
- Node23 scientific work started: **false**
- Docking-label receipt produced: **false**
- formal evaluator run: **false**
- threshold relaxation, trimming, replacement, imputation: **none**
- bootstrap PID `2069185`: terminal/dead after clean zero branch

V1 had a deployment-only shell bug (`ROOT` readonly assignment collision) and exited before scientific work. V1.1 uses version-isolated paths, a separate `STATUS_ROOT` environment key, and a sanitized `env -i` launch. No scientific policy changed.

## Evidence

- `DEPLOYMENT_RECORD.json`: machine-readable summary.
- `REMOTE_PACKAGE_SHA256SUMS`: exact deployed package and terminal-output hashes.
- `REMOTE_WAITER_STATUS.json`: terminal waiter state.
- `REMOTE_PROCESS_TERMINAL.txt`: direct dead-PID and removed waiter-PID evidence.
- `REMOTE_NO_ELIGIBLE_DOCKING_RECEIPT.json`: zero-job receipt.
- `REMOTE_FORBIDDEN_ARTIFACT_SCAN.txt`: confirms no results/runs/release artifacts.
- `V1_PRE_SCIENTIFIC_DEPLOYMENT_FAILURE.txt`: superseded V1 failure evidence.

## Claim boundary

This result is sequence/developability attrition evidence only. It is not Docking geometry, binding, affinity, competition, experimental blocking, Docking Gold, or final submission authority.
