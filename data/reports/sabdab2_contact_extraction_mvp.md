# SAbDab2 single-domain structure contact MVP

Updated: 2026-07-09

## Summary

```json
{
  "manifest_rows": 2422,
  "eligible_sampled_structures": 12,
  "processed_structures": 12,
  "structures_with_contacts": 12,
  "contact_rows": 1286,
  "cutoff_angstrom": 4.5,
  "output": "/mnt/d/work/抗体/data/model_data/sabdab2_single_domain_contacts_mvp.csv"
}
```

## Boundary

这是一个无外部依赖的 MVP 级 contact extractor，仅用于证明结构接触数据通路可跑通；它不是最终全量、高精度结构标注器。后续全量训练建议改用 gemmi/Bio.PDB 并加入 CDR 编号映射。

## Structure summaries

| pdb | structure_member | vhh_chains | antigen_chains | contact_residue_pairs | atoms_total | vhh_atoms | antigen_atoms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pdb_000010zo | pdb_000010zo/pdb_000010zo_sabdab.cif | A|C | B|D | 67 | 2841 | 1734 | 1107 |
| pdb_000011ol | pdb_000011ol/pdb_000011ol_sabdab.cif | H|K | A|L | 162 | 5773 | 2552 | 3221 |
| pdb_000011oo | pdb_000011oo/pdb_000011oo_sabdab.cif | H|K | A|L | 164 | 5753 | 2531 | 3222 |
| pdb_000011oq | pdb_000011oq/pdb_000011oq_sabdab.cif | H|K | A|L | 172 | 5670 | 2545 | 3125 |
| pdb_000011or | pdb_000011or/pdb_000011or_sabdab.cif | H|K | L | 133 | 4125 | 2515 | 1610 |
| pdb_000011ou | pdb_000011ou/pdb_000011ou_sabdab.cif | H|K | L | 132 | 4163 | 2529 | 1634 |
| pdb_000011zw | pdb_000011zw/pdb_000011zw_sabdab.cif | H|N | A|L | 147 | 5811 | 2466 | 2461 |
| pdb_000012oy | pdb_000012oy/pdb_000012oy_sabdab.cif | B | A | 32 | 3174 | 967 | 2207 |
| pdb_000012oz | pdb_000012oz/pdb_000012oz_sabdab.cif | B | A | 31 | 3168 | 967 | 2201 |
| pdb_000012pb | pdb_000012pb/pdb_000012pb_sabdab.cif | B | A | 30 | 3168 | 967 | 2201 |
| pdb_00001bzq | pdb_00001bzq/pdb_00001bzq_sabdab.cif | K|L|M|N | A|B|C|D | 184 | 7544 | 3740 | 3804 |
| pdb_00001g6v | pdb_00001g6v/pdb_00001g6v_sabdab.cif | K | A | 32 | 2988 | 949 | 2039 |