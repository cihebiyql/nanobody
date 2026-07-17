# V4-F96 Formal Evaluator V2 — Scope Clarifications

Status: `PRELABEL_CLARIFICATION_ONLY_NO_SCIENTIFIC_CONTRACT_CHANGE`

1. The embedded `phase2_v4_f_primary_evaluation_policy_v1` belongs to the earlier **label-free prediction freeze**. Its `secondary_metrics` list was frozen before EF@Top10% was required. EF@Top10% is therefore not a model-selection or prediction-generation input. It is a prospectively added **formal evaluation co-gate** defined and hash-frozen by `phase2_v4_f96_formal_evaluator_v2_preregistration.json` before any V4-F96 Docking label exists or is opened.
2. `constant` remains listed among historical shortcut names for schema compatibility, but it is not rank-comparable because its Spearman correlation is undefined. V2 therefore rejects `constant` as a Spearman-delta formal comparator before label access. A formal shortcut comparator must be a nonconstant, explicitly pre-frozen comparator present in the frozen 96-row prediction receipt.

Claim boundary: computational independent dual-receptor Docking geometry only; not binding, affinity, competition, Docking Gold, experimental blocking, or final submission authority.

Label access at clarification: zero V4-F96/test32 Docking label paths opened; formal evaluator not executed.
