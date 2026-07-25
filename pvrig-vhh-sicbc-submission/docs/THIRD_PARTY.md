# Third-party data, software, and model sources

| Component | Role in this submission | Distribution treatment |
| --- | --- | --- |
| PDB 8X6B and 9E6Y | Public PVRIG/PVRL2 receptor conformations | Compact coordinate inputs included; cite the PDB entries. |
| `ab-data-validator` | Official sequence/Excel validation, ANARCI/IMGT and similarity workflow | MIT source vendored in `third_party/ab-data-validator/` with original LICENSE. |
| ANARCI / AbNumber / MUSCLE | Numbering, CDR boundaries, alignment | Not vendored; install upstream. |
| NanoBodyBuilder2 | VHH monomer structures | Not vendored; install upstream. |
| HADDOCK3 | Constrained docking and refinement | Not vendored; install upstream. |
| AbNatiV 2.0.8 | VHH-likeness | Checkpoint not redistributed; use official initialization. |
| Sapiens / BioPhi | Human-likeness proxy | Model files not redistributed; obtain upstream models. |
| RFantibody/RFdiffusion/ProteinMPNN | Generative and fixed-pose design | Code integration retained; external binaries and weights not redistributed. |

No proprietary raw dataset, full docking archive, cached model, or private
credential is included.  See `data/provenance/model_weights_manifest.tsv` for
recorded weight versions and SHA256 values where captured.
