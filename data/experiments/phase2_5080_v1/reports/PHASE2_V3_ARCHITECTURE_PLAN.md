# Phase 2 V3 Target-Conditioned Binding Prior

## Objective

V3 is a fast, target-conditioned VHH-antigen binding prior for the first stage
of the PVRIG screening funnel. It must demonstrate measurable transfer beyond
simple sequence similarity, frozen cosine scores, and the V2.5-style shallow
head before its score can influence candidate ordering.

V3 does not predict PVRIG blocking truth. Generic affinity ranking, binary
binding, PVRIG target binding, and PVRIG-PVRL2 blocking remain separate evidence
lanes.

## Evidence Lanes

| Lane | Sources | Use |
| --- | --- | --- |
| Open development | NbBench SARS-CoV-2 train/val; NbBench hIL6 train/val | Model fitting, early stopping, baseline selection |
| Formal target transfer | AVIDa-hTNFa | Primary one-shot external-family evaluation |
| Formal secondary transfer | NbBench SARS-CoV-2 test; NbBench hIL6 test | Descriptive unseen-target/mutant evaluation |
| Generic affinity diagnostic | Frozen V2.5 NanoBind formal result | Historical diagnostic only; never V3 tuning |
| PVRIG prospective | Frozen 24-candidate V2.5 assay panel | Score-only deployment after the formal gate |
| PVRIG structure | V2.4 contact/hotspot prior and node1 geometry cascade | Shortlist postprocessing, not training truth |

Constructed negatives and pose proxies are excluded from the primary binary
binding objective. The upstream NbBench splits are retained because their
scientific task is transfer to unseen antigen variants. Exact pair overlap is
forbidden. VHH overlap is reported per formal block and is not hidden.

## Stage 1 Model

Each normalized VHH-antigen pair uses frozen representations:

- VHHBERT mean-pooled VHH embedding: 768 dimensions.
- ESM2-8M mean-pooled VHH embedding: 320 dimensions.
- ESM2-8M mean-pooled antigen embedding: 320 dimensions.
- Deterministic VHH physicochemical and developability descriptors.

The full model projects VHH and antigen features to a shared latent space, then
combines `[v, a, v*a, abs(v-a), cosine(v,a)]`. A learned gate controls the
interaction residual before the binary binding head. Training uses weighted BCE
plus a within-target positive-vs-negative pairwise loss.

The following baselines use the same frozen inputs and development protocol:

1. prevalence-only constant score;
2. frozen ESM2 VHH-antigen cosine;
3. VHH-only learned head;
4. ESM2-pair learned head without VHHBERT or physicochemical features;
5. leakage-safe frozen-embedding nearest-neighbor diagnostic when tractable.

## Split and Seal Contract

- Train/dev labels are open and may be used for optimization.
- Formal manifests retain only model inputs and stable row identities.
- Formal labels live in a separate sealed file.
- Training writes hashes for the prepared records, embedding manifest,
  preregistration, test specification, resolved config, and every checkpoint.
- Formal evaluation is a separate command and may run once for a run directory.
- Any source, feature, model, threshold, metric, or join change after unsealing
  requires a new version.

## Formal Gate

The primary block is external hTNFa target transfer. The primary metric is
average precision (AUPRC). AUROC, EF1%, recall at top 1%, and calibration error
are secondary.

V3 passes only when all conditions hold:

1. the strongest eligible baseline is selected using development data only;
2. the mean three-seed V3 AUPRC exceeds that baseline;
3. every seed has positive AUPRC delta;
4. paired bootstrap 95% CI for ensemble delta has lower bound greater than 0;
5. paired permutation p-value is below 0.05;
6. null-label and target-shuffle controls do not pass the same gate;
7. all split, seal, provenance, and checkpoint hash checks pass.

If the gate fails, deployment uses the strongest baseline and the report must
state that V3 did not establish an improved prior.

## PVRIG Deployment

After the formal decision, the frozen 24-candidate panel is scored against the
same PVRIG structural ectodomain proxy used by the assay execution package.
Outputs include per-seed scores, ensemble mean and uncertainty, baseline scores,
rank, model/provenance hashes, and an explicit non-blocker claim boundary.

The V3 score is a front-screen column only. It must not overwrite the canonical
V2.5 cascade. A separate V3 handoff table is used by node1 to prioritize which
candidates receive expensive structure prediction and docking.

## Runtime Allocation

- Local RTX 5080: frozen embedding generation, model training, formal inference.
- node1: NanoBodyBuilder2/IgFold/NanoNet structure checks, complex modeling,
  HADDOCK3, and dual-baseline geometry consensus for the selected shortlist.
- node1 CPU-heavy work remains load-gated; GPU-capable structure tools may use an
  explicitly selected idle GPU.

## Required Deliverables

- prepared train/dev and blinded/sealed formal manifests;
- resumable frozen embedding cache and provenance manifest;
- three full-model checkpoints and matched learned baselines;
- one-shot formal metrics, statistical decision, and predictions;
- PVRIG 24-candidate score table and node1 handoff manifest;
- final validator output, audit JSON/Markdown, tests, and project status update.
