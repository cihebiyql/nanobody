# PVRIG Target Domain Audit V1

Verdict: PASS

- Full sequence: Q6DKI7, 326 aa
- Model input proxy: UniProt 39-171, 133 aa
- Model-index contract: `full_position_1based = model_index_0based + 39`
- Start evidence: official UniProt PDB cross-reference 8X6B covers 39-154.
- End evidence: UniProt predicts a transmembrane helix at 172-192; 9E6Y covers 41-172.
- Local observed numbering coverage: 41-153.
- Target hotspot positions covered: 67-144 (24 positions).
- Boundary warning: 39-171 is a structure-supported model proxy, not a reviewed UniProt topological-domain annotation.
- Evidence boundary: external priors remain binding/site priors, not PVRIG blocker scores.
