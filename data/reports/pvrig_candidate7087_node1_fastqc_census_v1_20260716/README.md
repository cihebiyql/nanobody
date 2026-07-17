# Node1 7,087-candidate large-scale-fast QC census

This is a **sequence/developability large-scale-fast capacity census**, not Full-QC capacity and not docking, binding, affinity, experimental blocking, model correctness, or teacher supervision.

Actual path per chunk:

```text
vhh-competition-qc --gate-policy blocker_calibrated --large-scale-fast
  -> vhh-screen --skip-abnativ --skip-sapiens --skip-tnp
  -> vhh-eval
  -> Python abnumber.Chain IMGT + Kabat numbering
```

Included cheap evidence:

- FR/CDR numbering and framework-integrity checks;
- conserved IMGT cysteines and FR4 checks;
- ProtParam/basic sequence liabilities;
- official-cache and local-positive CDR novelty.

Explicitly deferred or skipped:

- official `ab-data-validator`: deferred to a later Full shortlist;
- AbNatiV: skipped;
- Sapiens: skipped;
- TNP: skipped;
- team diversity: deferred;
- structure prediction: not run;
- docking/geometry/model/experimental labels: not accessed.

The explicit `ANARCI` binary path was supplied to the outer command but was not directly invoked for candidate numbering in this run. Candidate numbering was performed by `vhh-eval` through Python `abnumber.Chain`; the pre-existing positive-CDR cache was not rebuilt.

Terminal result: 7,087 rows across 40 parents; 4,578 large-scale-fast hard pass and 2,509 hard fail. The preregistered fast-capacity threshold marked 29 parents ready and 11 insufficient. These are planning states only.

See `INDEPENDENT_VERIFICATION.json`, `independent_replay/`,
`DEPLOYMENT_RECORD.json`, and `runtime_evidence/`.
